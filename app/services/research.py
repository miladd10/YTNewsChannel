from __future__ import annotations

import html
import json
import math
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

import xml.etree.ElementTree as ET
import httpx
from ddgs import DDGS

from .ai import generate_text
from .cinema_format import FORMAT_BY_KEY, research_query_groups, section_label, format_packet

CINEMA_QUERY_GROUPS = research_query_groups()
CATEGORY_LABELS = {key: section_label(key) for key in FORMAT_BY_KEY}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _search_after_date_for_inclusive_start(date_start: str) -> str:
    if not date_start:
        return ""
    try:
        return (datetime.fromisoformat(date_start).date() - timedelta(days=1)).isoformat()
    except Exception:
        return date_start


def google_news_rss_url(query: str, date_start: str, date_end: str, locale: str = "CA") -> str:
    dated = query.strip()
    if date_start:
        dated += f" after:{_search_after_date_for_inclusive_start(date_start)}"
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


def _parse_source_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        pass
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except Exception:
            return None
    return None


def _window_bounds(date_start: str, date_end: str) -> tuple[datetime | None, datetime | None]:
    start = _parse_source_datetime(f"{date_start}T00:00:00+00:00") if date_start else None
    end = _parse_source_datetime(f"{date_end}T00:00:00+00:00") if date_end else None
    return start, end


def source_temporal_role(published_at: str, date_start: str, date_end: str) -> str:
    published = _parse_source_datetime(published_at)
    if published is None:
        return "undated"
    start, end = _window_bounds(date_start, date_end)
    if start is not None and published < start:
        return "background"
    if end is not None and published >= end:
        return "out_of_window"
    return "current"


def _source_identity(article: dict) -> str:
    source = str(article.get("source") or "").strip().casefold()
    try:
        host = (urlparse(str(article.get("url") or "")).hostname or "").casefold()
    except Exception:
        host = ""
    if source and source not in {"google news", "news"}:
        return source
    return host or str(article.get("url") or "").strip().casefold()


def annotate_source_window(article: dict, date_start: str, date_end: str) -> dict:
    item = dict(article)
    raw = dict(item.get("raw") or {})
    role = source_temporal_role(str(item.get("published_at") or ""), date_start, date_end)
    raw["temporal_role"] = role
    raw["selected_window_start"] = date_start
    raw["selected_window_end_exclusive"] = date_end
    item["raw"] = raw
    return item


def _evidence_metrics(cluster: list[dict]) -> dict:
    current = [item for item in cluster if str((item.get("raw") or {}).get("temporal_role") or "") == "current"]
    background = [item for item in cluster if str((item.get("raw") or {}).get("temporal_role") or "") == "background"]
    out_of_window = [item for item in cluster if str((item.get("raw") or {}).get("temporal_role") or "") == "out_of_window"]
    undated = [item for item in cluster if str((item.get("raw") or {}).get("temporal_role") or "") == "undated"]
    current_non_reddit = [
        item for item in current
        if str((item.get("raw") or {}).get("platform") or "") != "reddit"
    ]
    independent_current = {
        _source_identity(item)
        for item in current_non_reddit
        if _source_identity(item)
    }
    primary_social_current = [
        item for item in current
        if str((item.get("raw") or {}).get("trust_role") or "") == "primary_post_candidate"
    ]
    if len(independent_current) >= 2:
        verification_status = "verified"
        verification_notes = "At least two independent current-window non-Reddit sources were discovered."
    elif len(independent_current) == 1:
        verification_status = "reported"
        verification_notes = "One current-window non-Reddit source was discovered; treat as reported unless a primary/second source confirms it."
    elif primary_social_current:
        verification_status = "needs_verification"
        verification_notes = "Only public social-post candidates currently support the hook; account authenticity/corroboration is still required."
    else:
        verification_status = "needs_verification"
        verification_notes = "No current-window non-Reddit evidence is available."

    if current:
        freshness = "current"
    elif background or out_of_window:
        freshness = "stale"
    else:
        freshness = "date_unknown"

    return {
        "in_window_source_count": len(current),
        "background_source_count": len(background) + len(out_of_window),
        "undated_source_count": len(undated),
        "independent_source_count": len(independent_current),
        "current_non_reddit_source_count": len(current_non_reddit),
        "current_primary_social_count": len(primary_social_current),
        "verification_status": verification_status,
        "verification_notes": verification_notes,
        "freshness": freshness,
    }


def _apply_story_quality_gates(story: dict, project: dict) -> dict:
    date_start = str(project.get("date_start") or "")
    date_end = str(project.get("date_end") or "")
    in_window = int(story.get("in_window_source_count") or 0)
    background = int(story.get("background_source_count") or 0)
    undated = int(story.get("undated_source_count") or 0)
    freshness = str(story.get("freshness") or "").strip().lower()
    hook = str(story.get("news_hook") or "").strip()
    hook_date = str(story.get("news_hook_date") or "").strip()
    verification = str(story.get("verification_status") or "needs_verification").strip().lower()

    deterministic_temporal = "pass"
    if in_window <= 0:
        deterministic_temporal = "fail" if background > 0 else "warning"
        freshness = "stale" if background > 0 else "date_unknown"

    if hook_date:
        hook_dt = _parse_source_datetime(hook_date)
        start, end = _window_bounds(date_start, date_end)
        if hook_dt is not None:
            if (start is not None and hook_dt < start) or (end is not None and hook_dt >= end):
                freshness = "stale"
                deterministic_temporal = "fail"

    if freshness == "stale":
        deterministic_temporal = "fail"
    elif freshness not in {"current", "followup"}:
        deterministic_temporal = "warning"

    if not hook:
        deterministic_temporal = "warning" if deterministic_temporal != "fail" else "fail"

    if bool(story.get("reddit_only")):
        verification = "needs_verification"
        story["confidence"] = "reported"

    # Deterministic evidence can cap, but not inflate, the AI verification call.
    current_non_reddit = int(story.get("current_non_reddit_source_count") or 0)
    independent = int(story.get("independent_source_count") or 0)
    if current_non_reddit <= 0:
        verification = "needs_verification"
    elif independent < 2 and verification == "verified":
        verification = "reported"

    story["freshness"] = freshness
    story["verification_status"] = verification
    story["temporal_gate"] = deterministic_temporal
    story["verification_gate"] = (
        "pass" if verification in {"verified", "reported"} else "fail"
    )

    can_include = (
        deterministic_temporal == "pass"
        and bool(hook)
        and freshness in {"current", "followup"}
        and verification in {"verified", "reported"}
        and in_window > 0
    )
    if not can_include and story.get("decision") == "include":
        story["decision"] = "maybe" if deterministic_temporal != "fail" else "skip"
    if deterministic_temporal == "fail":
        story["decision"] = "skip"
        story["score"] = min(float(story.get("score") or 0), 3.5)
    elif verification == "needs_verification":
        story["decision"] = "maybe" if story.get("decision") != "skip" else "skip"
        story["score"] = min(float(story.get("score") or 0), 6.5)

    return story


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


def _host_matches(host: str, domain: str) -> bool:
    host = (host or "").casefold().strip(".")
    domain = (domain or "").casefold().strip(".")
    return host == domain or host.endswith("." + domain)


def _social_platform_for_url(url: str) -> str:
    try:
        host = (urlparse(url or "").hostname or "").casefold()
    except Exception:
        host = ""
    if _host_matches(host, "reddit.com"):
        return "reddit"
    if _host_matches(host, "x.com") or _host_matches(host, "twitter.com"):
        return "x"
    if _host_matches(host, "tiktok.com"):
        return "tiktok"
    if _host_matches(host, "instagram.com"):
        return "instagram"
    if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
        return "youtube"
    return ""


def _social_source_label(platform: str) -> str:
    return {
        "reddit": "Reddit",
        "x": "X / Twitter",
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "youtube": "YouTube",
    }.get(platform, platform.title())


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
                    query += f" after:{_search_after_date_for_inclusive_start(date_start)}"
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


def cluster_articles(
    articles: list[dict],
    date_start: str = "",
    date_end: str = "",
) -> list[dict]:
    annotated = [annotate_source_window(article, date_start, date_end) for article in articles]
    clusters: list[list[dict]] = []
    for article in sorted(annotated, key=lambda x: x.get("published_at", ""), reverse=True):
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
        evidence = _evidence_metrics(cluster)
        source_evidence = [
            {
                "title": item.get("title") or "",
                "source": item.get("source") or "",
                "published_at": item.get("published_at") or "",
                "temporal_role": str((item.get("raw") or {}).get("temporal_role") or ""),
                "source_kind": str((item.get("raw") or {}).get("source_kind") or "news"),
                "platform": str((item.get("raw") or {}).get("platform") or ""),
                "trust_role": str((item.get("raw") or {}).get("trust_role") or ""),
                "snippet": str(item.get("snippet") or "")[:500],
            }
            for item in cluster[:8]
        ]
        score = heuristic_score(cluster, source_count)
        stories.append({
            "id": str(uuid.uuid4()),
            "canonical_title": cluster[0]["title"],
            "summary": snippets[0][:700] if snippets else "",
            "category": category,
            "attention": _bucket(score, 7.5, 4.5),
            "importance": "medium",
            "freshness": evidence["freshness"],
            "confidence": "confirmed" if evidence["independent_source_count"] >= 2 else "reported",
            "visual_potential": "high" if category in {"trend", "upcoming_films", "celebrities"} else "medium",
            "uniqueness": "medium",
            "rationale": f"Found across {source_count} source{'s' if source_count != 1 else ''} in the selected week.",
            "score": score,
            "decision": "skip" if evidence["freshness"] == "stale" else ("maybe" if score >= 4.0 else "skip"),
            "article_ids": [x["id"] for x in cluster],
            "source_count": source_count,
            "source_platforms": platforms,
            "source_kinds": source_kinds,
            "reddit_only": reddit_only,
            "primary_social_count": primary_social_count,
            "source_evidence": source_evidence,
            "news_hook": "",
            "news_hook_date": "",
            "familiarity_needed": False,
            "familiarity_anchor": "",
            "search_subject": "",
            "spice_angles": [],
            "spice_source_ids": [],
            "temporal_gate": "pass" if evidence["freshness"] == "current" else ("fail" if evidence["freshness"] == "stale" else "warning"),
            "verification_gate": "pass" if evidence["verification_status"] in {"verified", "reported"} else "fail",
            **evidence,
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
            "in_window_source_count": int(s.get("in_window_source_count") or 0),
            "background_source_count": int(s.get("background_source_count") or 0),
            "undated_source_count": int(s.get("undated_source_count") or 0),
            "independent_source_count": int(s.get("independent_source_count") or 0),
            "source_evidence": s.get("source_evidence") or [],
            "heuristic_score": s["score"],
        }
        for s in stories[:100]
    ]
    system = """You are the section editor and ranking editor for a weekly cinema-news show.

You receive strict SECTION CONTRACTS and discovered stories. Classify each story by MEANING, not by the query that happened to find it.

Return ONLY valid JSON: one object per supplied story using exactly these keys:
id, category, section_fit, attention, importance, freshness, news_hook, news_hook_date, verification_status, verification_notes, search_subject, familiarity_needed, familiarity_anchor, confidence, visual_potential, uniqueness, score, decision, rationale.

Rules:
- category must be one of the supplied researchable section keys.
- Move a story when its current_category is wrong.
- section_fit is low|medium|high.
- attention/importance/visual_potential/uniqueness are low|medium|high.
- confidence is rumor|reported|confirmed.
- freshness is current|followup|stale|date_unknown.
- news_hook must name the SPECIFIC new development that occurred in the selected project window; do not merely restate the subject/movie.
- news_hook_date should be YYYY-MM-DD only when the supplied evidence supports that date; otherwise return an empty string.
- verification_status is verified|reported|needs_verification|rejected.
- verification_notes briefly explain which evidence verifies the hook and any remaining limitation.
- search_subject is a concise searchable subject for the story (movie title, person, company/deal, series title, etc.), not the whole headline. Use only names/titles supported by the supplied evidence.
- familiarity_needed is true|false. Set true only when a central director/actor/creator/company is important to the story but a casual movie audience may not immediately recognize the name.
- familiarity_anchor is ONE very short recognition cue supported by supplied current/background evidence, ideally a single famous work or clear identity (for example: "director of The Incredibles"). Leave it empty for household names, obvious companies/platforms, or when the supplied evidence does not support a safe anchor.
- Never invent a filmography credit or company association to fill familiarity_anchor.
- A newly published recap of an old event is STALE unless it contains a genuinely new development inside the selected window.
- Older/background sources may explain context but do NOT make the story current.
- At least one source with temporal_role=current is required for current/followup eligibility.
- Undated sources alone cannot establish freshness.
- score is 0-10; decision is include|maybe|skip.
- Apply each section's mission/include/exclude/evidence rules strictly.
- Do not force every section to contain news. A weak story should be skipped.
- Trends is reserved for a genuinely conversation-driving lead story, not every new trailer.
- Box Office is for chart/ranking/milestone coverage; a lead film's box-office data can remain in Trends when it is part of the week's dominant story.
- Celebrity/Viral/Toxic social evidence: a person's/studio's own public X/TikTok post can support what that account itself posted. Do not assume an account is official solely from a search result.
- Reddit is discovery/community reaction, not sole factual verification unless the story itself is explicitly about Reddit reaction.
- If reddit_only=true and the story makes an external factual claim, confidence cannot be confirmed and decision should normally be maybe/skip pending corroboration.
- Reject unsupported health/appearance speculation and anonymous gossip.
- Never invent facts.
- The selected date window is date_start inclusive and date_end exclusive."""
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
        for key in ("attention", "importance", "freshness", "confidence", "visual_potential", "uniqueness", "decision"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                story[key] = value.strip().lower()
        for key in ("rationale", "news_hook", "news_hook_date", "verification_notes", "search_subject", "familiarity_anchor"):
            value = item.get(key)
            if isinstance(value, str):
                story[key] = value.strip()
        familiarity_needed = item.get("familiarity_needed")
        if isinstance(familiarity_needed, bool):
            story["familiarity_needed"] = familiarity_needed
        elif isinstance(familiarity_needed, str):
            story["familiarity_needed"] = familiarity_needed.strip().lower() in {"true", "yes", "1"}
        verification_status = str(item.get("verification_status") or "").strip().lower()
        if verification_status in {"verified", "reported", "needs_verification", "rejected"}:
            story["verification_status"] = verification_status
        if story.get("section_fit") == "low" and story.get("decision") == "include":
            story["decision"] = "maybe"
        try:
            story["score"] = max(0.0, min(10.0, float(item.get("score"))))
        except Exception:
            pass
        _apply_story_quality_gates(story, project)
    stories.sort(key=lambda x: x["score"], reverse=True)
    return stories, actual_provider, actual_model



SPICE_TYPES = {
    "rumor",
    "controversy",
    "critic_reaction",
    "social_buzz",
    "cool_fact",
    "surprising_comparison",
    "production_context",
}


VISUAL_CONTEXT_KINDS = {
    "person",
    "people_group",
    "related_title",
    "behind_the_scenes",
    "interview",
    "fun_fact",
    "comparison",
    "event_photo",
}

VISUAL_LAYOUT_HINTS = {
    "single",
    "two_up",
    "three_up",
    "person_plus_title",
    "collage",
    "stacked_two",
    "stacked_three",
}


def _validated_visual_context(raw_context: object, sources: list[dict]) -> list[dict]:
    if not isinstance(raw_context, list):
        return []
    source_by_url = {
        str(source.get("url") or "").strip(): source
        for source in sources
        if str(source.get("url") or "").strip()
    }
    cleaned: list[dict] = []
    for index, raw in enumerate(raw_context[:10]):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in VISUAL_CONTEXT_KINDS:
            continue
        label = str(raw.get("label") or "").strip()
        subjects = [
            str(value).strip()
            for value in (raw.get("subjects") or [])
            if str(value).strip()
        ][:3]
        if label and label not in subjects:
            subjects = [label, *subjects][:3]
        if not subjects:
            continue
        urls = [
            str(url).strip()
            for url in (raw.get("source_urls") or [])
            if str(url).strip() in source_by_url
        ]
        # Contextual visual claims need the same source grounding as narration
        # enrichment. Current-title promo is handled independently by Media.
        if not urls:
            continue
        layout = str(raw.get("layout_hint") or "single").strip().lower()
        if layout not in VISUAL_LAYOUT_HINTS:
            layout = "single"
        if kind == "people_group":
            if len(subjects) >= 3:
                layout = "three_up"
            elif len(subjects) == 2:
                layout = "two_up"
        cleaned.append({
            "kind": kind,
            "label": label or " + ".join(subjects),
            "subjects": subjects,
            "related_title": str(raw.get("related_title") or "").strip()[:160],
            "narration_cue": str(raw.get("narration_cue") or "").strip()[:280],
            "why": str(raw.get("why") or "").strip()[:500],
            "preferred_media": [
                str(value).strip()
                for value in (raw.get("preferred_media") or [])
                if str(value).strip()
            ][:5],
            "layout_hint": layout,
            "source_urls": urls[:4],
            "source_labels": [
                str(source_by_url[url].get("source") or "") for url in urls[:4]
            ],
            "order": index,
        })
    return cleaned


def _story_context_subject(story: dict) -> str:
    subject = str(story.get("search_subject") or "").strip()
    if subject:
        return subject[:140]
    title = str(story.get("canonical_title") or "").strip()
    title = re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip()
    return title[:140]



FACT_CHECK_PREFERRED_DOMAINS = (
    "apnews.com", "reuters.com", "variety.com", "deadline.com",
    "hollywoodreporter.com", "thewrap.com", "boxofficemojo.com",
    "the-numbers.com", "netflix.com", "tudum.com", "sonypictures.com",
    "sonypictures.ca", "nbcuniversal.com", "warnerbros.com",
    "paramount.com", "disney.com", "marvel.com", "filmlinc.org",
    "ft.com", "wsj.com", "washingtonpost.com", "nytimes.com",
)


def _fact_check_trust_tier(url: str) -> str:
    try:
        host = (urlparse(url or "").hostname or "").casefold().replace("www.", "")
    except Exception:
        host = ""
    if any(host == domain or host.endswith("." + domain) for domain in FACT_CHECK_PREFERRED_DOMAINS):
        return "preferred"
    return "supplemental"


def _fact_check_queries(story: dict, date_start: str, date_end: str) -> list[str]:
    """Queries aimed at claims that can become stale inside a weekly script."""
    subject = _story_context_subject(story)
    if not subject:
        return []
    quoted = f'"{subject}"'
    category = str(story.get("category") or "")
    date_bits = ""
    if date_start:
        date_bits += f" after:{_search_after_date_for_inclusive_start(date_start)}"
    if date_end:
        date_bits += f" before:{date_end}"

    queries = [f"{quoted} latest update{date_bits}"]
    story_text = " ".join([
        str(story.get("canonical_title") or ""),
        str(story.get("summary") or ""),
        str(story.get("news_hook") or ""),
    ]).casefold()

    if category in {"box_office", "trend"} or any(
        token in story_text for token in ("box office", "gross", "opening", "million", "billion", "گیشه")
    ):
        queries = [
            f"{quoted} latest box office worldwide total domestic international weekend{date_bits}",
            f"{quoted} box office second weekend cumulative total{date_bits}",
        ]
    elif category == "industry":
        queries = [
            f"{quoted} latest deal settlement acquisition value terms{date_bits}",
            f"{quoted} official settlement agreement value latest{date_bits}",
        ]
    elif category == "upcoming_films":
        queries = [
            f"{quoted} official trailer release date theatrical limited wide latest{date_bits}",
            f"{quoted} studio release date official latest{date_bits}",
        ]
    elif category == "tv_series":
        queries = [
            f"{quoted} Netflix official title cast premiere latest{date_bits}",
            f"{quoted} official series announcement latest{date_bits}",
        ]
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))


def fetch_narration_fact_check_sources(
    stories: list[dict],
    date_start: str,
    date_end: str,
    *,
    per_query_limit: int = 5,
) -> dict[str, list[dict]]:
    """Collect a small fresh verification supplement for narration fact-checking.

    This does not change story inclusion. It exists to catch volatile values
    (box-office totals/rankings, release scopes/dates, deal values) that can be
    correctly mentioned by an older article but become stale before narration.
    """
    by_story: dict[str, list[dict]] = defaultdict(list)
    for story in stories:
        story_id = str(story.get("id") or "")
        if not story_id:
            continue
        seen: set[str] = set()
        for query in _fact_check_queries(story, date_start, date_end):
            try:
                results = list(DDGS().text(query, max_results=per_query_limit) or [])
            except Exception:
                continue
            for result in results:
                url = str(result.get("href") or result.get("url") or "").strip()
                if not url or url.casefold() in seen:
                    continue
                title = _plain(str(result.get("title") or ""))
                snippet = _plain(str(result.get("body") or result.get("snippet") or ""))
                if not title and not snippet:
                    continue
                seen.add(url.casefold())
                raw_date = str(result.get("date") or result.get("published") or "")
                annotated = annotate_source_window({
                    "title": title,
                    "url": url,
                    "source": _plain(str(result.get("source") or "")) or (urlparse(url).hostname or "Web"),
                    "published_at": raw_date,
                    "snippet": snippet[:1200],
                    "query": query,
                    "raw": {
                        "source_kind": "fact_check",
                        "context_story_id": story_id,
                    },
                }, date_start, date_end)
                by_story[story_id].append({
                    "title": annotated.get("title") or "",
                    "url": annotated.get("url") or "",
                    "source": annotated.get("source") or "",
                    "published_at": annotated.get("published_at") or "",
                    "temporal_role": str((annotated.get("raw") or {}).get("temporal_role") or ""),
                    "snippet": annotated.get("snippet") or "",
                    "query": query,
                    "trust_tier": _fact_check_trust_tier(url),
                })
                if len(by_story[story_id]) >= per_query_limit * 2:
                    break
        by_story[story_id].sort(key=lambda item: (
            0 if item.get("trust_tier") == "preferred" else 1,
            0 if item.get("temporal_role") == "current" else 1,
            str(item.get("published_at") or ""),
        ))
    return by_story


def _spice_queries(story: dict, date_start: str, date_end: str) -> list[tuple[str, str]]:
    subject = _story_context_subject(story)
    if not subject:
        return []
    quoted = f'"{subject}"'
    date_bits = ""
    if date_start:
        date_bits += f" after:{_search_after_date_for_inclusive_start(date_start)}"
    if date_end:
        date_bits += f" before:{date_end}"
    return [
        ("web_news", f"{quoted} latest news interview report update{date_bits}"),
        ("rumor_drama", f"{quoted} rumor rumour controversy backlash dispute drama alleged report{date_bits}"),
        ("critics", f"{quoted} critics review reaction Rotten Tomatoes Metacritic review scores{date_bits}"),
        ("social_reddit", f"site:reddit.com {quoted} reaction discussion theory{date_bits}"),
        ("social_x", f"(site:x.com OR site:twitter.com) {quoted} reaction discussion{date_bits}"),
        ("social_tiktok", f"site:tiktok.com {quoted} reaction discussion{date_bits}"),
        ("social_instagram", f"site:instagram.com {quoted} post reaction{date_bits}"),
        ("youtube", f"site:youtube.com {quoted} interview press conference behind the scenes official{date_bits}"),
        # These two are intentionally broader than the news window: an older
        # production fact or comparison can be useful context as long as the
        # enrichment AI labels it as background rather than this week's event.
        ("cool_context", f"{quoted} interview behind the scenes production fact director cast history"),
        ("comparison", f"{quoted} box office budget record comparison previous film franchise"),
    ]


def fetch_story_spice_sources(
    stories: list[dict],
    date_start: str,
    date_end: str,
    *,
    max_stories: int = 18,
    per_query_limit: int = 4,
) -> tuple[list[dict], dict[str, list[dict]], list[dict]]:
    """Search around strong current stories for optional narrative angles.

    These results do NOT change the story's verification/freshness gate.
    They are optional context that must be separately validated before narration.
    """
    candidates = [
        story for story in stories
        if str(story.get("freshness") or "") in {"current", "followup"}
        and str(story.get("verification_gate") or "") == "pass"
        and str(story.get("section_fit") or "medium") != "low"
    ][:max_stories]

    all_articles: list[dict] = []
    by_story: dict[str, list[dict]] = defaultdict(list)
    diagnostics: list[dict] = []

    for story in candidates:
        story_id = str(story["id"])
        seen_urls: set[str] = set()
        for context_kind, query in _spice_queries(story, date_start, date_end):
            found = 0
            try:
                results = list(DDGS().text(query, max_results=per_query_limit) or [])
                for result in results:
                    url = str(result.get("href") or result.get("url") or "").strip()
                    if not url or url.casefold() in seen_urls:
                        continue
                    title = _plain(str(result.get("title") or ""))
                    body = _plain(str(result.get("body") or result.get("snippet") or ""))
                    if not title and not body:
                        continue
                    seen_urls.add(url.casefold())
                    platform = _social_platform_for_url(url)
                    raw_date = str(result.get("date") or result.get("published") or "")
                    article = annotate_source_window({
                        "id": str(uuid.uuid4()),
                        "title": title or body[:180],
                        "url": url,
                        "source": _social_source_label(platform) if platform else _plain(str(result.get("source") or "")) or (urlparse(url).hostname or "Web"),
                        "published_at": raw_date,
                        "category": str(story.get("category") or ""),
                        "snippet": body[:1200],
                        "query_key": query,
                        "raw": {
                            "source_kind": "social" if platform else "story_context",
                            "platform": platform,
                            "context_kind": context_kind,
                            "context_story_id": story_id,
                            "trust_role": (
                                "community_signal" if platform == "reddit"
                                else "primary_post_candidate" if platform in {"x", "tiktok"}
                                else "context_candidate"
                            ),
                        },
                    }, date_start, date_end)
                    all_articles.append(article)
                    by_story[story_id].append(article)
                    found += 1
                diagnostics.append({
                    "story_id": story_id,
                    "context_kind": context_kind,
                    "query": query,
                    "count": found,
                    "ok": True,
                    "source_kind": "story_context",
                })
            except Exception as exc:
                diagnostics.append({
                    "story_id": story_id,
                    "context_kind": context_kind,
                    "query": query,
                    "count": 0,
                    "ok": False,
                    "error": str(exc),
                    "source_kind": "story_context",
                })
    return all_articles, by_story, diagnostics


def _validated_spice_angles(raw_angles: object, sources: list[dict]) -> list[dict]:
    if not isinstance(raw_angles, list):
        return []
    source_by_url = {
        str(source.get("url") or "").strip(): source
        for source in sources
        if str(source.get("url") or "").strip()
    }
    cleaned: list[dict] = []
    for angle in raw_angles[:6]:
        if not isinstance(angle, dict):
            continue
        kind = str(angle.get("type") or "").strip().lower()
        text = str(angle.get("text") or "").strip()
        if kind not in SPICE_TYPES or not text:
            continue
        urls = [
            str(url).strip() for url in (angle.get("source_urls") or [])
            if str(url).strip() in source_by_url
        ]
        # No evidence URL from the supplied search packet = not narratable.
        if not urls:
            continue
        evidence_status = str(angle.get("evidence_status") or "weak").strip().lower()
        if evidence_status not in {"strong", "supported", "weak", "social_only"}:
            evidence_status = "weak"
        safe_raw = angle.get("safe_to_narrate")
        safe = (
            safe_raw is True
            or (isinstance(safe_raw, str) and safe_raw.strip().lower() in {"true", "yes", "1"})
        )
        source_rows = [source_by_url[url] for url in urls]
        social_rows = [
            source for source in source_rows
            if str((source.get("raw") or {}).get("platform") or "")
        ]
        non_social_rows = [source for source in source_rows if source not in social_rows]
        if evidence_status == "weak":
            safe = False
        if kind == "rumor" and (evidence_status == "social_only" or not non_social_rows):
            # Social chatter alone never becomes a narratable "there is a rumor".
            safe = False
        if kind == "social_buzz" and not non_social_rows and len(social_rows) < 2:
            # One isolated social result is not a pattern or buzz.
            safe = False
        cleaned.append({
            "type": kind,
            "text": text,
            "evidence_status": evidence_status,
            "safe_to_narrate": safe,
            "source_urls": urls[:4],
            "source_labels": [
                str(source_by_url[url].get("source") or "") for url in urls[:4]
            ],
            "usage_note": str(angle.get("usage_note") or "").strip()[:500],
        })
    # Put usable angles first without inventing an ordering score.
    cleaned.sort(key=lambda item: (not item["safe_to_narrate"], item["type"]))
    return cleaned


def ai_enrich_story_spice(
    stories: list[dict],
    sources_by_story: dict[str, list[dict]],
    project: dict,
    provider: str,
    model: str,
) -> tuple[list[dict], str, str]:
    packets = []
    for story in stories:
        sources = sources_by_story.get(str(story.get("id"))) or []
        if not sources:
            continue
        packets.append({
            "id": story["id"],
            "title": story.get("canonical_title") or "",
            "search_subject": _story_context_subject(story),
            "category": story.get("category") or "",
            "news_hook": story.get("news_hook") or "",
            "news_hook_date": story.get("news_hook_date") or "",
            "familiarity_anchor": story.get("familiarity_anchor") or "",
            "narration_text": str(story.get("_narration_text") or "")[:5000],
            "sources": [
                {
                    "title": source.get("title") or "",
                    "url": source.get("url") or "",
                    "source": source.get("source") or "",
                    "published_at": source.get("published_at") or "",
                    "temporal_role": str((source.get("raw") or {}).get("temporal_role") or ""),
                    "source_kind": str((source.get("raw") or {}).get("source_kind") or ""),
                    "platform": str((source.get("raw") or {}).get("platform") or ""),
                    "context_kind": str((source.get("raw") or {}).get("context_kind") or ""),
                    "snippet": str(source.get("snippet") or "")[:900],
                }
                for source in sources[:20]
            ],
        })
    if not packets:
        return stories, provider, model

    system = """You are the related-context editor for a weekly cinema news show.
For each CURRENT verified story, inspect ONLY the supplied related search evidence and extract OPTIONAL angles that can make narration richer.

Return ONLY JSON: an array of objects:
{"id":"...",
 "spice_angles":[
  {"type":"rumor|controversy|critic_reaction|social_buzz|cool_fact|surprising_comparison|production_context",
   "text":"concise factual angle",
   "evidence_status":"strong|supported|weak|social_only",
   "safe_to_narrate":true|false,
   "source_urls":["exact supplied URL"],
   "usage_note":"how to frame it without overstating"}
 ],
 "visual_context":[
  {"kind":"person|people_group|related_title|behind_the_scenes|interview|fun_fact|comparison|event_photo",
   "label":"short visual label",
   "subjects":["one to three exact people/titles/entities supported by evidence"],
   "related_title":"movie/show title when relevant, otherwise empty",
   "narration_cue":"short phrase/idea in the supplied narration this visual should cover",
   "why":"why this visual directly helps the narration",
   "preferred_media":["official BTS","official interview","press photo","poster","official still","official trailer/clip"],
   "layout_hint":"single|two_up|three_up|stacked_two|stacked_three|person_plus_title|collage",
   "source_urls":["exact supplied URL"]}
 ]}

STRICT RULES:
- It is perfectly valid to return an empty spice_angles array. NEVER manufacture spice.
- RUMOR: only create type=rumor when a supplied source explicitly reports/describes a rumor, report, speculation, or unconfirmed claim. Never infer a rumor because something would be dramatic. Keep it explicitly labeled as rumor/unconfirmed in text and usage_note.
- A rumor is safe_to_narrate only when a reputable report/direct named source supports that the rumor exists. Reddit-only or random social speculation is NOT enough to say "there is a rumor"; keep that unsafe or classify genuinely notable discussion as social_buzz.
- CONTROVERSY: needs a concrete dispute/backlash/legal/creative conflict supported by evidence. Ordinary disagreement is not automatically controversy.
- CRITIC_REACTION: use actual critic/review evidence. Do not turn fan comments into critics.
- SOCIAL_BUZZ: summarize only a pattern actually visible in the supplied evidence. One isolated comment/post is not "people are saying".
- PLATFORM ATTRIBUTION IS REQUIRED for social_buzz. If evidence is Reddit, say Reddit/redditors; if X/Twitter, say X/Twitter users/posts; if TikTok, say TikTok; if multiple platforms genuinely support the same pattern, name those platforms. Do NOT use vague wording like "people on social media say" when the supplied evidence is platform-specific.
- COOL_FACT / PRODUCTION_CONTEXT: may use older/background evidence if directly relevant and well supported, but clearly treat it as context rather than this week's event.
- SURPRISING_COMPARISON: only when the supplied evidence gives the numbers/facts needed for the comparison.
- Do not diagnose health, infer private life, repeat abusive claims, or convert anonymous gossip into fact.
- Do not use outside knowledge or memory.
- source_urls MUST be copied exactly from the supplied source list.
- Prefer 0-3 strong angles over many weak ones.
- VISUAL CONTEXT is for professional B-roll planning from the narration, not extra narration facts.
- Read narration_text. Identify named people, related films/shows, previous credits, interviews, BTS/production references, comparisons, events, and one strong cool fact that deserves its own visual beat.
- If the narration says a creator is known for another title, create related_title context for that title only when the supplied evidence supports the connection.
- If 2-3 people are discussed together, prefer one people_group item with subjects in spoken order and two_up/three_up layout.
- For a cool_fact that is safe_to_narrate and visually concrete, create one kind=fun_fact visual_context item so Media/Resolve can give that fact one dedicated shot.
- Do not force visual context. Never create a person/title relationship from memory.
- narration_cue must describe the actual supplied narration beat to cover, not a new claim.
"""
    user = json.dumps({
        "project_window": {
            "date_start": project.get("date_start"),
            "date_end_exclusive": project.get("date_end"),
        },
        "stories": packets,
    }, ensure_ascii=False)
    text, actual_provider, actual_model = generate_text(provider, model, system, user)
    parsed = _parse_json_array(text)
    by_id = {str(item.get("id") or ""): item for item in parsed if isinstance(item, dict)}
    for story in stories:
        story_id = str(story.get("id") or "")
        item = by_id.get(story_id) or {}
        sources = sources_by_story.get(story_id) or []
        story["spice_angles"] = _validated_spice_angles(item.get("spice_angles"), sources)
        story["visual_context"] = _validated_visual_context(item.get("visual_context"), sources)
        story["spice_source_ids"] = [str(source.get("id")) for source in sources if source.get("id")]
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
