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

from .ai import generate_text

CINEMA_QUERY_GROUPS = [
    ("trend", "movie film box office opening weekend trailer"),
    ("industry", "Hollywood studio streaming merger acquisition lawsuit cinema business"),
    ("upcoming_films", "upcoming movie casting director release date first look trailer"),
    ("tv_series", "TV series streaming renewal cancellation HBO Netflix Apple TV Disney Marvel"),
    ("celebrities", "actor actress director filmmaker interview award cinema celebrity"),
    ("ai_tech", "AI artificial intelligence film movie actor VFX Hollywood"),
]

CATEGORY_LABELS = {
    "trend": "Trends",
    "industry": "Industry & Business",
    "upcoming_films": "Upcoming Films",
    "tv_series": "TV Series",
    "celebrities": "Celebrities",
    "ai_tech": "AI & Tech",
}


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
            "category": s["category"],
            "summary": s["summary"][:450],
            "source_count": s["source_count"],
            "heuristic_score": s["score"],
        }
        for s in stories[:80]
    ]
    system = """You are the research editor for a weekly cinema-news YouTube show. Evaluate only the supplied stories. Do not invent facts. Return ONLY valid JSON: an array with one object per supplied story using exactly these keys: id, attention, importance, freshness, confidence, visual_potential, uniqueness, score, decision, rationale. Allowed signal values are low|medium|high except confidence is rumor|reported|confirmed and freshness is current|followup|stale. score is 0-10. decision is include|maybe|skip. Favor stories that are genuinely important, widely discussed, fresh in the selected week, well-supported, and visually useful. A rumor can still be included only when it is itself newsworthy and clearly labelled as rumor. Avoid filling categories for the sake of a template."""
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
        "stories": compact,
    }, ensure_ascii=False)
    text, actual_provider, actual_model = generate_text(provider, model, system, user)
    ranked = _parse_json_array(text)
    by_id = {str(item.get("id")): item for item in ranked if isinstance(item, dict)}
    for story in stories:
        item = by_id.get(story["id"])
        if not item:
            continue
        for key in ("attention", "importance", "freshness", "confidence", "visual_potential", "uniqueness", "decision", "rationale"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                story[key] = value.strip().lower() if key != "rationale" else value.strip()
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
