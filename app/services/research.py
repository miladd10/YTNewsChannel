from __future__ import annotations

import html
import json
import math
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import xml.etree.ElementTree as ET
import httpx
from ddgs import DDGS

from .ai import generate_text
from .cinema_format import FORMAT_BY_KEY, research_query_groups, section_label, format_packet

CINEMA_QUERY_GROUPS = research_query_groups()
CATEGORY_LABELS = {key: section_label(key) for key in FORMAT_BY_KEY}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def google_news_rss_url(query: str, date_start: str, date_end: str, locale: str = "CA") -> str:
    dated = query.strip()
    if date_start:
        dated += f" after:{date_start}"
    if date_end:
        dated += f" before:{date_end}"
    return f"https://news.google.com/rss/search?q={quote_plus(dated)}&hl=en-CA&gl={locale}&ceid={locale}:en"


def _plain(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _published(entry) -> str:
    raw = getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except Exception:
        return raw


def fetch_google_news(date_start: str, date_end: str, *, per_query_limit: int = 35) -> tuple[list[dict], list[dict]]:
    articles: list[dict] = []
    diagnostics: list[dict] = []
    headers = {"User-Agent": "Mozilla/5.0 YTNewsChannel/0.1"}
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        for category, query in CINEMA_QUERY_GROUPS:
            url = google_news_rss_url(query, date_start, date_end)
            try:
                response = client.get(url)
                response.raise_for_status()
                root = ET.fromstring(response.text)
                channel = root.find("channel")
                feed_title = _plain(channel.findtext("title") if channel is not None else "")
                count = 0
                for item in ([] if channel is None else channel.findall("item")):
                    if count >= per_query_limit:
                        break
                    title = _plain(item.findtext("title") or "")
                    link = (item.findtext("link") or "").strip()
                    if not title or not link:
                        continue
                    source = _plain(item.findtext("source") or "")
                    raw_published = item.findtext("pubDate") or ""
                    try:
                        published_at = parsedate_to_datetime(raw_published).astimezone(timezone.utc).isoformat() if raw_published else ""
                    except Exception:
                        published_at = raw_published
                    articles.append({
                        "id": str(uuid.uuid4()),
                        "title": title,
                        "url": link,
                        "source": source,
                        "published_at": published_at,
                        "category": category,
                        "snippet": _plain(item.findtext("description") or ""),
                        "query_key": query,
                        "raw": {"feed_title": feed_title},
                    })
                    count += 1
                diagnostics.append({"category": category, "query": query, "url": url, "count": count, "ok": True})
            except Exception as exc:
                diagnostics.append({"category": category, "query": query, "url": url, "count": 0, "ok": False, "error": str(exc)})
    return articles, diagnostics


SOCIAL_DOMAINS = {
    "reddit": ("reddit.com",),
    "x": ("x.com", "twitter.com"),
    "tiktok": ("tiktok.com",),
}

SOCIAL_SECTION_QUERIES = {
    "trend": [
        "movie film reaction cinema this week",
        "movie box office audience reaction this week",
    ],
    "industry": [
        "Hollywood studio merger acquisition executive statement",
    ],
    "upcoming_films": [
        "new movie trailer first look casting official",
        "upcoming film director actor announcement",
    ],
    "celebrities": [
        "actor actress director filmmaker announcement interview movie",
        "Hollywood celebrity award event personal announcement film",
    ],
    "ai_tech": [
        "AI film actor VFX Hollywood viral technology",
    ],
    "viral_images": [
        "movie celebrity viral photo image post cinema",
        "actor director on set photo award viral",
    ],
    "now_available": [
        "movie digital release VOD streaming available now",
    ],
    "toxic_news": [
        "Hollywood weird funny bizarre actor director movie incident",
        "film celebrity social media mishap viral",
    ],
}


def _social_platform_for_url(url: str) -> str:
    value = (url or "").casefold()
    if "reddit.com/" in value:
        return "reddit"
    if "x.com/" in value or "twitter.com/" in value:
        return "x"
    if "tiktok.com/" in value:
        return "tiktok"
    return ""


def _social_source_label(platform: str) -> str:
    return {"reddit": "Reddit", "x": "X / Twitter", "tiktok": "TikTok"}.get(platform, platform.title())


def _social_queries(date_start: str, date_end: str) -> list[tuple[str, str, str]]:
    queries: list[tuple[str, str, str]] = []
    for category, terms in SOCIAL_SECTION_QUERIES.items():
        allowed = set((FORMAT_BY_KEY.get(category) or {}).get("social_sources") or [])
        for platform in ("x", "tiktok", "reddit"):
            if platform not in allowed:
                continue
            domains = SOCIAL_DOMAINS[platform]
            site_part = " OR ".join(f"site:{domain}" for domain in domains)
            for term in terms:
                query = f"({site_part}) {term}"
                if date_start:
                    query += f" after:{date_start}"
                if date_end:
                    query += f" before:{date_end}"
                queries.append((category, platform, query))
    return queries


def fetch_social_sources(
    date_start: str,
    date_end: str,
    *,
    per_query_limit: int = 8,
) -> tuple[list[dict], list[dict]]:
    """Discover public Reddit/X/TikTok URLs through web search.

    This intentionally does not pretend to have authenticated private-platform
    access. It discovers public posts/pages that search engines can index.
    """
    articles: list[dict] = []
    diagnostics: list[dict] = []
    seen_urls: set[str] = set()

    for category, platform, query in _social_queries(date_start, date_end):
        count = 0
        try:
            results = list(DDGS().text(query, max_results=per_query_limit) or [])
            for result in results:
                url = str(result.get("href") or result.get("url") or "").strip()
                actual_platform = _social_platform_for_url(url)
                if not url or actual_platform != platform or url in seen_urls:
                    continue
                title = _plain(str(result.get("title") or ""))
                body = _plain(str(result.get("body") or result.get("snippet") or ""))
                if not title and not body:
                    continue
                seen_urls.add(url)
                raw_date = str(result.get("date") or result.get("published") or "")
                articles.append({
                    "id": str(uuid.uuid4()),
                    "title": title or body[:180],
                    "url": url,
                    "source": _social_source_label(platform),
                    "published_at": raw_date,
                    "category": category,
                    "snippet": body[:1000],
                    "query_key": query,
                    "raw": {
                        "source_kind": "social",
                        "platform": platform,
                        "discovery": "ddgs_public_web",
                        "trust_role": (
                            "community_signal" if platform == "reddit"
                            else "primary_post_candidate"
                        ),
                    },
                })
                count += 1
            diagnostics.append({
                "category": category,
                "platform": platform,
                "query": query,
                "count": count,
                "ok": True,
                "source_kind": "social",
            })
        except Exception as exc:
            diagnostics.append({
                "category": category,
                "platform": platform,
                "query": query,
                "count": 0,
                "ok": False,
                "error": str(exc),
                "source_kind": "social",
            })
    return articles, diagnostics


def normalize_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"\s+-\s+[^-]{2,60}$", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [w for w in text.split() if w not in {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "from", "new", "latest"}]
    return " ".join(words)


def _title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    sa, sb = set(na.split()), set(nb.split())
    jac = len(sa & sb) / max(1, len(sa | sb))
    return max(seq, jac)


def cluster_articles(articles: list[dict]) -> list[dict]:
    clusters: list[list[dict]] = []
    for article in sorted(articles, key=lambda x: x.get("published_at", ""), reverse=True):
        best_index = -1
        best_score = 0.0
        for idx, cluster in enumerate(clusters):
            representative = cluster[0]
            score = _title_similarity(article["title"], representative["title"])
            if score > best_score:
                best_index, best_score = idx, score
        if best_index >= 0 and best_score >= 0.66:
            clusters[best_index].append(article)
        else:
            clusters.append([article])

    stories: list[dict] = []
    for cluster in clusters:
        categories = defaultdict(int)
        sources = set()
        snippets = []
        for item in cluster:
            categories[item["category"]] += 1
            if item.get("source"):
                sources.add(item["source"])
            if item.get("snippet"):
                snippets.append(item["snippet"])
        category = max(categories, key=categories.get)
        source_count = max(len(sources), len(cluster)) if not sources else len(sources)
        platforms = sorted({
            str((item.get("raw") or {}).get("platform") or "")
            for item in cluster
            if str((item.get("raw") or {}).get("platform") or "")
        })
        source_kinds = sorted({
            str((item.get("raw") or {}).get("source_kind") or "news")
            for item in cluster
        })
        reddit_only = bool(cluster) and all(
            str((item.get("raw") or {}).get("platform") or "") == "reddit"
            for item in cluster
        )
        primary_social_count = sum(
            1 for item in cluster
            if str((item.get("raw") or {}).get("trust_role") or "") == "primary_post_candidate"
        )
        score = heuristic_score(cluster, source_count)
        stories.append({
            "id": str(uuid.uuid4()),
            "canonical_title": cluster[0]["title"],
            "summary": snippets[0][:700] if snippets else "",
            "category": category,
            "attention": _bucket(score, 7.5, 4.5),
            "importance": "medium",
            "freshness": "current",
            "confidence": "confirmed" if source_count >= 3 else "reported",
            "visual_potential": "high" if category in {"trend", "upcoming_films", "celebrities"} else "medium",
            "uniqueness": "medium",
            "rationale": f"Found across {source_count} source{'s' if source_count != 1 else ''} in the selected week.",
            "score": score,
            "decision": "include" if score >= 7.5 else ("maybe" if score >= 4.0 else "skip"),
            "article_ids": [x["id"] for x in cluster],
            "source_count": source_count,
            "source_platforms": platforms,
            "source_kinds": source_kinds,
            "reddit_only": reddit_only,
            "primary_social_count": primary_social_count,
        })
    stories.sort(key=lambda x: (x["score"], x["source_count"]), reverse=True)
    return stories


def heuristic_score(cluster: list[dict], source_count: int) -> float:
    category_weight = {
        "trend": 2.5,
        "industry": 2.1,
        "upcoming_films": 2.2,
        "tv_series": 1.8,
        "celebrities": 1.5,
        "ai_tech": 1.6,
        "viral_images": 1.4,
        "box_office": 2.3,
        "now_available": 1.3,
        "toxic_news": 1.1,
    }.get(cluster[0].get("category", ""), 1.0)
    source_signal = min(4.5, 1.4 * math.log2(max(1, source_count) + 1))
    title = cluster[0].get("title", "").lower()
    event_signal = 0.0
    for token in ("box office", "trailer", "first look", "cancel", "renew", "cast", "release", "merger", "acquisition", "award", "record", "opening"):
        if token in title:
            event_signal += 0.35
    return round(min(10.0, category_weight + source_signal + min(2.0, event_signal)), 2)


def _bucket(score: float, high: float, medium: float) -> str:
    return "high" if score >= high else ("medium" if score >= medium else "low")


def ai_rank_stories(stories: list[dict], project: dict, provider: str, model: str) -> tuple[list[dict], str, str]:
    if not stories:
        return stories, provider, model
    compact = [
        {
            "id": s["id"],
            "title": s["canonical_title"],
            "current_category": s["category"],
            "summary": s["summary"][:650],
            "source_count": s["source_count"],
            "source_platforms": s.get("source_platforms") or [],
            "source_kinds": s.get("source_kinds") or [],
            "reddit_only": bool(s.get("reddit_only")),
            "primary_social_count": int(s.get("primary_social_count") or 0),
            "heuristic_score": s["score"],
        }
        for s in stories[:100]
    ]
    system = """You are the section editor and ranking editor for a weekly cinema-news show.

You receive strict SECTION CONTRACTS and discovered stories. Classify each story by MEANING, not by the query that happened to find it.

Return ONLY valid JSON: one object per supplied story using exactly these keys:
id, category, section_fit, attention, importance, freshness, confidence, visual_potential, uniqueness, score, decision, rationale.

Rules:
- category must be one of the supplied researchable section keys.
- Move a story when its current_category is wrong.
- section_fit is low|medium|high.
- attention/importance/visual_potential/uniqueness are low|medium|high.
- confidence is rumor|reported|confirmed.
- freshness is current|followup|stale.
- score is 0-10; decision is include|maybe|skip.
- Apply each section's mission/include/exclude/evidence rules strictly.
- Do not force every section to contain news. A weak story should be skipped.
- Trends is reserved for a genuinely conversation-driving lead story, not every new trailer.
- Box Office is for chart/ranking/milestone coverage; a lead film's box-office data can remain in Trends when it is part of the week's dominant story.
- Celebrity/Viral/Toxic social evidence: a person's/studio's own public X/TikTok post can support what that account itself posted. Do not assume an account is official solely from a search result.
- Reddit is discovery/community reaction, not sole factual verification unless the story itself is explicitly about Reddit reaction.
- If reddit_only=true and the story makes an external factual claim, confidence cannot be confirmed and decision should normally be maybe/skip pending corroboration.
- Reject unsupported health/appearance speculation and anonymous gossip.
- Never invent facts."""
    user = json.dumps({
        "project": {
            "channel": project.get("channel"),
            "content_type": project.get("content_type"),
            "language": project.get("language"),
            "date_start": project.get("date_start"),
            "date_end": project.get("date_end"),
            "geographic_focus": project.get("geographic_focus"),
            "editorial_focus": project.get("editorial_focus"),
        },
        "section_contracts": [
            section for section in format_packet()
            if section.get("research")
        ],
        "stories": compact,
    }, ensure_ascii=False)
    text, actual_provider, actual_model = generate_text(provider, model, system, user)
    ranked = _parse_json_array(text)
    by_id = {str(item.get("id")): item for item in ranked if isinstance(item, dict)}
    for story in stories:
        item = by_id.get(story["id"])
        if not item:
            continue
        category = str(item.get("category") or "").strip()
        if category in FORMAT_BY_KEY and FORMAT_BY_KEY[category].get("research"):
            story["category"] = category
        section_fit = str(item.get("section_fit") or "").strip().lower()
        if section_fit in {"low", "medium", "high"}:
            story["section_fit"] = section_fit
        for key in ("attention", "importance", "freshness", "confidence", "visual_potential", "uniqueness", "decision", "rationale"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                story[key] = value.strip().lower() if key != "rationale" else value.strip()
        if story.get("section_fit") == "low" and story.get("decision") == "include":
            story["decision"] = "maybe"
        try:
            story["score"] = max(0.0, min(10.0, float(item.get("score"))))
        except Exception:
            pass
    stories.sort(key=lambda x: x["score"], reverse=True)
    return stories, actual_provider, actual_model


def _parse_json_array(text: str) -> list:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except Exception:
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            try:
                value = json.loads(raw[start:end+1])
                return value if isinstance(value, list) else []
            except Exception:
                return []
        return []
