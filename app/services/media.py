from __future__ import annotations

import ipaddress
import mimetypes
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx


def clean_story_query(title: str) -> str:
    text = re.sub(r"\s+-\s+[^-]{2,80}$", "", title or "").strip()
    return re.sub(r"\s+", " ", text)


BROLL_TITLE_TERMS = (
    "official trailer", "official teaser", "official clip", "official featurette",
    "behind the scenes", "making of", "first look", "sneak peek",
    "deleted scene", "red carpet", "world premiere", "premiere footage",
    "press conference", "official announcement", "official reveal",
)

GENERIC_BROLL_TERMS = (
    "trailer", "teaser", "clip", "featurette", "behind the scenes", "making of",
    "first look", "sneak peek", "deleted scene", "red carpet", "premiere",
    "press conference", "announcement", "reveal", "studio tour", "sizzle reel",
    "showreel", "anniversary", "studio logo",
)

COMMENTARY_TITLE_TERMS = (
    "reaction", "reacts", "review", "breakdown", "explained", "analysis",
    "commentary", "my thoughts", "what we know", "everything we know",
    "latest news", "news update", "rumor", "rumour", "theory", "recap",
    "watchalong", "watch along", "trailer reaction", "ending explained",
    "fan trailer", "concept trailer", "concept teaser", "ai trailer",
    "ai concept", "parody trailer",
)

NEWS_CHANNEL_TERMS = (
    "abc news", "nbc news", "cbs news", "cnn", "fox news", "bbc news",
    "sky news", "reuters", "associated press", "ap archive", "cnbc",
    "bloomberg", "newsnation", "msnbc", "global news", "euronews",
    "the independent", "forbes", "deadline hollywood", "variety",
    "hollywood reporter", "entertainment tonight", "access hollywood",
)

AGGREGATOR_CHANNEL_TERMS = (
    "screen rant", "collider", "ign", "watchmojo", "looper", "movieclips",
    "rotten tomatoes trailers", "joblo", "emergency awesome", "heavy spoilers",
    "new rockstars", "john campea", "beyond the trailer", "comicbook.com",
    "fandom entertainment", "kinocheck", "one media", "rapid trailer",
    "filmspot trailer", "moviegasm", "stream wars",
)

OFFICIAL_CHANNEL_TERMS = (
    "netflix", "warner bros", "warnerbrospictures", "paramount pictures",
    "universal pictures", "sony pictures", "marvel entertainment",
    "dc", "disney", "hbo", "apple tv", "prime video", "amazon mgm",
    "lionsgate", "a24", "neon", "searchlight pictures", "20th century studios",
    "focus features", "dreamworks", "pixar", "lucasfilm", "peacock", "hulu",
    "max", "mubi", "criterion", "imax",
)

SPOKEN_SOURCE_TERMS = (
    "interview", "podcast", "conversation with", "talks with", "talks to",
    "speaks with", "speaks to", "sit-down", "sit down",
)

CORPORATE_STORY_TERMS = (
    "merger", "acquisition", "acquire", "deal", "lawsuit", "sues", "settle",
    "settlement", "antitrust", "attorney general", "bid", "shareholder",
    "investor", "regulator", "regulatory", "states over", "close merger",
)

CORPORATE_BROLL_TERMS = (
    "studio lot", "headquarters", "logo", "brand film",
    "company reel", "sizzle reel", "centennial", "100 years", "anniversary",
    "campus", "backlot", "soundstage", "sound stage", "official intro",
)

SUBJECT_STOPWORDS = {
    "official", "trailer", "teaser", "clip", "featurette", "behind", "scenes",
    "making", "first", "look", "sneak", "peek", "film", "movie", "series",
    "season", "video", "news", "new", "the", "and", "with", "from", "gets",
    "sets", "release", "date", "details", "breaks", "records", "massive",
    "opening", "box", "office",
}


def _youtube_thumbnail(item: dict) -> str:
    thumbnail = str(item.get("thumbnail") or "").strip()
    if thumbnail:
        return thumbnail
    thumbs = item.get("thumbnails") or []
    if isinstance(thumbs, list):
        for entry in reversed(thumbs):
            if isinstance(entry, dict) and entry.get("url"):
                return str(entry["url"])
    return ""


def _max_video_height(item: dict) -> int | None:
    heights: list[int] = []
    direct = _as_int(item.get("height"))
    if direct:
        heights.append(direct)
    for fmt in item.get("formats") or []:
        if isinstance(fmt, dict):
            height = _as_int(fmt.get("height"))
            if height:
                heights.append(height)
    return max(heights) if heights else None


def _story_text(story: dict) -> str:
    parts = [
        str(story.get("canonical_title") or ""),
        str(story.get("summary") or ""),
    ]
    for article in story.get("articles") or []:
        parts.append(str(article.get("title") or ""))
    return " ".join(parts).lower()


def story_allows_interview_or_podcast(story: dict) -> bool:
    """Only permit spoken-source footage when the news itself is sourced from it."""
    text = _story_text(story)
    return any(term in text for term in SPOKEN_SOURCE_TERMS)


def _is_news_or_commentary_channel(source: str) -> bool:
    value = (source or "").lower()
    if re.search(r"\bnews\b", value):
        return True
    return any(term in value for term in NEWS_CHANNEL_TERMS + AGGREGATOR_CHANNEL_TERMS)


def _looks_like_official_channel(source: str) -> bool:
    value = (source or "").lower()
    return any(re.search(rf"\b{re.escape(term)}\b", value) for term in OFFICIAL_CHANNEL_TERMS)


def _is_corporate_story(story: dict) -> bool:
    text = _story_text(story)
    return str(story.get("category") or "").lower() == "industry" and any(term in text for term in CORPORATE_STORY_TERMS)


def _normalized_words(value: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", value or "")
        if len(token) >= 2
    ]


def _query_subject(query: str) -> str:
    value = (query or "").strip()
    suffixes = (
        " official featurette behind the scenes", " official studio tour",
        " official company reel", " official studio lot", " official logo",
        " official trailer", " official clip", " full interview",
        " podcast interview",
    )
    lowered = value.lower()
    for suffix in suffixes:
        if lowered.endswith(suffix):
            value = value[: -len(suffix)].strip()
            break
    # Search queries may include the current year to steer YouTube toward the
    # latest installment. The year is validated separately from upload/release
    # metadata and is not required to appear in the video title itself.
    return re.sub(r"\s+20\d{2}$", "", value).strip()


def _distinctive_subject_words(value: str) -> list[str]:
    words = _normalized_words(value)
    return [w for w in words if w not in SUBJECT_STOPWORDS and len(w) >= 3]


def _subject_matches(value: str, target_text: str) -> bool:
    words = _distinctive_subject_words(value)
    if not words:
        return False
    target_words = set(_normalized_words(target_text))
    if len(words) == 1:
        return words[0] in target_words
    # Require all meaningful words for short title/entity names such as
    # "Ray Gunn", "Resident Evil" and "Avengers Doomsday".
    required = words[:4]
    return all(word in target_words for word in required)


def _story_subjects(story: dict) -> list[str]:
    base = clean_story_query(story.get("canonical_title", ""))
    quoted = _quoted_subjects(base)
    if quoted:
        # The first quoted title is the primary subject of the headline.
        # Do not let a secondary title mentioned later (for example Endgame
        # Encore in an Avengers: Doomsday headline) replace the main B-roll.
        return [quoted[0]]
    compact = _compact_subject(base)
    # Strip generic leading/trailing news words so "New Resident Evil film"
    # becomes a useful subject rather than matching unrelated videos.
    words = compact.split()
    while words and words[0].lower().strip("’'") in {"new", "the", "a", "an"}:
        words.pop(0)
    while words and words[-1].lower().strip("’'") in {"film", "movie", "series", "show"}:
        words.pop()
    subject = " ".join(words).strip()
    return [subject] if subject else [base]


def _story_reference_year(story: dict) -> int | None:
    years: list[int] = []
    for value in [str(story.get("canonical_title") or "")] + [
        str(article.get("published_at") or "") for article in story.get("articles") or []
    ]:
        for match in re.findall(r"\b(20\d{2})\b", value):
            years.append(int(match))
    return max(years) if years else None


def _item_year(item: dict) -> int | None:
    for key in ("upload_date", "release_date", "timestamp", "release_timestamp"):
        value = item.get(key)
        if value is None:
            continue
        text = str(value)
        match = re.search(r"\b(20\d{2})", text)
        if match:
            return int(match.group(1))
        try:
            number = int(float(value))
            if number > 1_000_000_000:
                from datetime import datetime, timezone
                return datetime.fromtimestamp(number, tz=timezone.utc).year
        except (TypeError, ValueError, OSError):
            pass
    return None


def _requires_recent_media(story: dict) -> bool:
    if _is_corporate_story(story):
        return False
    return str(story.get("category") or "").lower() in {
        "trend", "upcoming_films", "tv_series", "celebrities",
    }


def _is_recent_enough_for_story(item: dict, story: dict) -> bool:
    if not _requires_recent_media(story):
        return True
    story_year = _story_reference_year(story)
    item_year = _item_year(item)
    if not story_year or not item_year:
        return True
    # A trailer/teaser can legitimately arrive the year before release/news.
    return item_year >= story_year - 1


def _matches_actual_story_subject(item: dict, story: dict) -> bool:
    title = str(item.get("title") or "")
    description = str(item.get("description") or "")
    source = str(item.get("channel") or item.get("uploader") or "")
    query_subject = _query_subject(str(item.get("_search_query") or ""))

    if _is_corporate_story(story):
        entities = _known_entities(_story_text(story))
        if not entities:
            return False
        # Corporate B-roll may identify the company in either the title or its
        # actual official channel, but it must still be corporate/studio footage.
        entity_match = any(
            _subject_matches(entity, f"{title} {source}")
            for entity in entities
        )
        corporate_visual = any(term in title.lower() for term in CORPORATE_BROLL_TERMS)
        return entity_match and corporate_visual

    # Search queries may add a year or distributor name to improve discovery,
    # but acceptance is always based on the actual primary story subject.
    return any(_subject_matches(subject, f"{title} {description}") for subject in _story_subjects(story))


def _is_original_visual_source(item: dict, story: dict) -> bool:
    source = str(item.get("channel") or item.get("uploader") or "")
    source_lower = source.lower()
    verified = bool(item.get("channel_is_verified"))

    if _is_news_or_commentary_channel(source):
        return False

    if _is_corporate_story(story):
        entities = _known_entities(_story_text(story))
        return any(_subject_matches(entity, source) for entity in entities)

    # Known studios/distributors are acceptable. For less-famous companies,
    # require verification plus an explicit production-company style name.
    if _looks_like_official_channel(source):
        return True
    if verified and any(_subject_matches(subject, source) for subject in _story_subjects(story)):
        return True
    production_name = bool(re.search(r"\b(pictures|studios|films|filmworks|productions|releasing|distribution)\b", source_lower))
    return verified and production_name


def _video_rejection_reason(item: dict, story: dict) -> str | None:
    title = str(item.get("title") or "").lower()
    source = str(item.get("channel") or item.get("uploader") or "").lower()
    description = str(item.get("description") or "").lower()
    haystack = f"{title} {source} {description}"
    allow_spoken = story_allows_interview_or_podcast(story)

    if any(term in haystack for term in COMMENTARY_TITLE_TERMS):
        return "commentary/reaction/review"

    if _is_news_or_commentary_channel(source):
        # A verified publication can be the original interview source, but only
        # when this story is explicitly about that interview/podcast.
        spoken = any(term in title for term in SPOKEN_SOURCE_TERMS) or "podcast" in source
        if not (allow_spoken and spoken and bool(item.get("channel_is_verified"))):
            return "news/commentary/aggregator channel"

    spoken = any(term in title for term in SPOKEN_SOURCE_TERMS) or "podcast" in source
    if spoken and not allow_spoken:
        return "interview/podcast not relevant to this story"

    if not _matches_actual_story_subject(item, story):
        return "wrong movie/company/story"

    if not _is_recent_enough_for_story(item, story):
        return "older franchise/installment footage"

    if _is_corporate_story(story):
        if any(term in title for term in ("trailer", "teaser", "movie clip", "featurette")):
            return "movie promo is not corporate B-roll"
        if not _is_original_visual_source(item, story):
            return "not an original company source"
        return None

    if allow_spoken and spoken:
        return None if bool(item.get("channel_is_verified")) else "interview is not from an original/verified source"

    if not _is_original_visual_source(item, story):
        return "not an original studio/distributor source"

    return None


def _official_broll_strength(item: dict, story: dict) -> tuple[int, str]:
    title = str(item.get("title") or "").lower()
    source = str(item.get("channel") or item.get("uploader") or "").lower()
    allow_spoken = story_allows_interview_or_podcast(story)

    if _is_corporate_story(story):
        if any(term in title for term in CORPORATE_BROLL_TERMS):
            return 5, "official company B-roll"
        return 0, ""

    if allow_spoken and (any(term in title for term in SPOKEN_SOURCE_TERMS) or "podcast" in source):
        return 5, "original interview/podcast"

    if any(term in title for term in BROLL_TITLE_TERMS):
        return 5, "official B-roll"

    if any(term in title for term in GENERIC_BROLL_TERMS):
        return 4, "studio/distributor B-roll"

    return 0, ""


def video_is_usable_broll(item: dict, story: dict) -> bool:
    if _video_rejection_reason(item, story):
        return False
    strength, _ = _official_broll_strength(item, story)
    return strength >= 4


def _video_rank(item: dict, story: dict, base: str) -> tuple[int, int, int, int]:
    strength, _ = _official_broll_strength(item, story)
    title = str(item.get("title") or "").lower()
    source = str(item.get("channel") or item.get("uploader") or "").lower()
    description = str(item.get("description") or "").lower()
    haystack = f"{title} {source} {description}"

    score = strength * 50
    priority_terms = {
        "official trailer": 30,
        "official teaser": 28,
        "official clip": 26,
        "official featurette": 24,
        "behind the scenes": 20,
        "making of": 18,
        "first look": 16,
        "sneak peek": 16,
        "deleted scene": 14,
        "red carpet": 12,
        "world premiere": 12,
        "press conference": 10,
    }
    for term, weight in priority_terms.items():
        if term in haystack:
            score += weight

    story_terms = [x.lower() for x in re.findall(r"[A-Za-z0-9]+", base) if len(x) >= 4]
    overlap = sum(1 for term in story_terms[:10] if term in haystack)
    score += overlap * 4

    height = _max_video_height(item) or 0
    if height >= 2160:
        score += 35
    elif height >= 1440:
        score += 28
    elif height >= 1080:
        score += 22
    elif height >= 720:
        score += 15
    elif height:
        score -= 8

    views = _as_int(item.get("view_count")) or 0
    return strength, score, height, views


def _quoted_subjects(text: str) -> list[str]:
    # Match real quote pairs. Treating every curly apostrophe as both an
    # opener and closer breaks headlines such as "Brad Bird’s ‘Ray Gunn’".
    patterns = (
        r"“([^”]{2,80})”",
        r"‘([^’]{2,80})’",
        r'"([^"]{2,80})"',
        r"(?<!\\w)'([^']{2,80})'(?!\\w)",
    )
    matches: list[tuple[int, str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            value = match.group(1).strip()
            if value:
                matches.append((match.start(), value))
    matches.sort(key=lambda row: row[0])

    found: list[str] = []
    for _, value in matches:
        if value not in found:
            found.append(value)
    return found[:3]

NEWS_VERBS = (
    " gets ", " get ", " sets ", " set ", " breaks ", " reaches ", " settles ",
    " sues ", " rejects ", " reveals ", " announces ", " adds ", " casts ",
    " opens ", " wins ", " has ", " faces ", " plans ", " agrees ", " says ",
)


def _known_entities(text: str) -> list[str]:
    lowered = (text or "").lower()
    aliases = {
        "paramount": "Paramount Pictures",
        "warner": "Warner Bros",
        "netflix": "Netflix",
        "disney": "Disney",
        "marvel": "Marvel",
        "dc": "DC Studios",
        "universal": "Universal Pictures",
        "sony": "Sony Pictures",
        "amazon mgm": "Amazon MGM",
        "apple tv": "Apple TV",
        "hbo": "HBO",
        "a24": "A24",
        "lionsgate": "Lionsgate",
        "20th century": "20th Century Studios",
        "searchlight": "Searchlight Pictures",
        "focus features": "Focus Features",
        "dreamworks": "DreamWorks",
        "pixar": "Pixar",
        "lucasfilm": "Lucasfilm",
        "neon": "Neon",
    }
    found = []
    for needle, canonical in aliases.items():
        if re.search(rf"\b{re.escape(needle)}\b", lowered):
            found.append(canonical)
    return list(dict.fromkeys(found))[:3]


def _compact_subject(text: str) -> str:
    value = clean_story_query(text)
    lower = f" {value.lower()} "
    cut = len(value)
    for verb in NEWS_VERBS:
        index = lower.find(verb)
        if index >= 0:
            cut = min(cut, max(0, index - 1))
    candidate = value[:cut].strip(" :-–—")
    words = candidate.split()
    if len(words) >= 2:
        return " ".join(words[:8])
    return value


def story_media_key(story: dict) -> str:
    """Stable key for duplicate headlines covering the same visual subject."""
    if _is_corporate_story(story):
        entities = _known_entities(_story_text(story))
        return "corporate:" + "|".join(sorted(x.lower() for x in entities))
    subjects = _story_subjects(story)
    subject = subjects[0] if subjects else clean_story_query(story.get("canonical_title", ""))
    words = _distinctive_subject_words(subject)
    return "title:" + " ".join(words or _normalized_words(subject))


def _story_distributors(story: dict) -> list[str]:
    """Known studio/distributor names mentioned anywhere in the story packet."""
    if _is_corporate_story(story):
        return []
    subject_words = set(_distinctive_subject_words((_story_subjects(story) or [""])[0]))
    distributors = []
    for entity in _known_entities(_story_text(story)):
        # Do not treat a title word that happens to resemble a company as a
        # distributor unless the entity contributes something beyond the title.
        entity_words = set(_distinctive_subject_words(entity))
        if entity_words and entity_words != subject_words:
            distributors.append(entity)
    return list(dict.fromkeys(distributors))[:3]


def _youtube_search_queries(story: dict) -> list[str]:
    base = clean_story_query(story.get("canonical_title", ""))

    if _is_corporate_story(story):
        queries: list[str] = []
        for entity in _known_entities(_story_text(story)):
            queries.extend([
                f'{entity} official studio lot',
                f'{entity} official logo',
                f'{entity} official company reel',
            ])
        return list(dict.fromkeys(queries))

    subjects = _story_subjects(story)
    story_year = _story_reference_year(story)
    queries: list[str] = []
    distributors = _story_distributors(story)
    for subject in subjects[:2]:
        if story_year:
            queries.append(f'{subject} {story_year} official trailer')
        for distributor in distributors:
            queries.append(f'{subject} {distributor} official trailer')
            queries.append(f'{subject} {distributor} official clip')
        queries.extend([
            f'{subject} official trailer',
            f'{subject} official clip',
            f'{subject} official featurette behind the scenes',
        ])

    if story_allows_interview_or_podcast(story):
        interview_subject = subjects[0] if subjects else base
        if story_year:
            queries.append(f'{interview_subject} {story_year} full interview')
        queries.extend([
            f'{interview_subject} full interview',
            f'{interview_subject} podcast interview',
        ])

    return list(dict.fromkeys(q.strip() for q in queries if q.strip()))


def _search_youtube_videos(
    story: dict,
    max_videos: int,
    query_cache: dict[str, list[dict]] | None = None,
) -> tuple[list[dict], list[str]]:
    from yt_dlp import YoutubeDL

    base = clean_story_query(story.get("canonical_title", ""))
    queries = _youtube_search_queries(story)
    search_count = min(max(max_videos, 8), 16)
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 20,
    }

    raw: list[dict] = []
    errors: list[str] = []
    query_cache = query_cache if query_cache is not None else {}
    with YoutubeDL(options) as ydl:
        for query in queries:
            cached = query_cache.get(query)
            if cached is not None:
                entries = [dict(item) for item in cached]
            else:
                entries = []
                last_error: Exception | None = None
                for _attempt in range(2):
                    try:
                        info = ydl.extract_info(f"ytsearch{search_count}:{query}", download=False)
                        entries = [dict(entry) for entry in (info or {}).get("entries") or [] if entry]
                        query_cache[query] = [dict(item) for item in entries]
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                if last_error is not None:
                    errors.append(f"YouTube B-roll search failed for '{query}': {last_error}")
                    continue

            for entry in entries:
                item = dict(entry)
                item["_search_query"] = query
                raw.append(item)

    usable = [item for item in raw if video_is_usable_broll(item, story)]
    usable.sort(key=lambda item: _video_rank(item, story, base), reverse=True)

    results: list[dict] = []
    seen: set[str] = set()
    for item in usable:
        video_id = str(item.get("id") or "").strip()
        page_url = str(item.get("webpage_url") or item.get("original_url") or "").strip()
        if not page_url and video_id:
            page_url = f"https://www.youtube.com/watch?v={video_id}"
        if not page_url or page_url in seen:
            continue
        seen.add(page_url)

        height = _max_video_height(item)
        _, source_kind = _official_broll_strength(item, story)
        results.append({
            "id": str(uuid.uuid4()),
            "media_type": "video",
            "title": str(item.get("title") or base).strip(),
            "page_url": page_url,
            "asset_url": page_url,
            "thumbnail_url": _youtube_thumbnail(item),
            "source": str(item.get("channel") or item.get("uploader") or "YouTube").strip(),
            "provider": f"YouTube · {source_kind}",
            "duration": str(item.get("duration_string") or item.get("duration") or "").strip(),
            "published_at": str(item.get("upload_date") or item.get("release_date") or "").strip(),
            "width": _as_int(item.get("width")),
            "height": height,
            "search_query": str(item.get("_search_query") or ""),
        })
        if len(results) >= max_videos:
            break

    return results, errors


BANNED_IMAGE_HOST_TERMS = (
    "facebook.com", "youtube.com", "youtu.be", "pinterest.", "instagram.com",
    "tiktok.com", "twitter.com", "x.com", "reddit.com", "memesita.com",
)

PREFERRED_IMAGE_SOURCE_TERMS = (
    "reuters", "apnews", "associated press", "getty", "deadline", "variety",
    "hollywoodreporter", "thewrap", "netflix", "warnerbros", "paramount",
    "sony", "marvel", "disney", "universal", "lionsgate", "a24",
)


def _image_search_queries(story: dict) -> list[str]:
    if _is_corporate_story(story):
        queries: list[str] = []
        for entity in _known_entities(_story_text(story)):
            queries.extend([
                f'{entity} official logo press kit',
                f'{entity} studio lot official photo',
            ])
        return list(dict.fromkeys(queries))

    subject = (_story_subjects(story) or [clean_story_query(story.get("canonical_title", ""))])[0]
    year = _story_reference_year(story)
    queries = []
    if year:
        queries.append(f'{subject} {year} official still press photo poster')
    queries.append(f'{subject} official still press photo poster')
    return list(dict.fromkeys(queries))


def _image_candidate_score(item: dict, story: dict) -> int:
    title = str(item.get("title") or "")
    source = str(item.get("source") or "")
    page_url = str(item.get("url") or "")
    asset_url = str(item.get("image") or "")
    host = (urlparse(page_url).hostname or "").lower()
    haystack = f"{title} {source} {host}".lower()

    if any(term in host for term in BANNED_IMAGE_HOST_TERMS):
        return -10_000

    if _is_corporate_story(story):
        entities = _known_entities(_story_text(story))
        if entities and not any(_subject_matches(entity, haystack) for entity in entities):
            return -5_000
        score = 25
    else:
        subjects = _story_subjects(story)
        if subjects and not any(_subject_matches(subject, title) for subject in subjects):
            return -5_000
        score = 30

    if any(term in haystack for term in PREFERRED_IMAGE_SOURCE_TERMS):
        score += 30
    if any(term in haystack for term in ("official", "press", "studio", "poster", "first look")):
        score += 15

    width = _as_int(item.get("width")) or 0
    height = _as_int(item.get("height")) or 0
    if max(width, height) >= 1600:
        score += 12
    elif max(width, height) >= 1000:
        score += 8

    if not asset_url:
        score -= 20
    return score


def _image_fallback(story: dict, max_images: int) -> tuple[list[dict], list[str]]:
    from ddgs import DDGS

    candidates: list[dict] = []
    errors: list[str] = []
    for image_query in _image_search_queries(story):
        try:
            for item in DDGS().images(image_query, max_results=max(max_images * 4, 10)) or []:
                item = dict(item)
                item["_search_query"] = image_query
                if _image_candidate_score(item, story) <= -5_000:
                    continue
                candidates.append(item)
        except Exception as exc:
            errors.append(f"Image fallback search failed for '{image_query}': {exc}")

    candidates.sort(key=lambda item: _image_candidate_score(item, story), reverse=True)
    results: list[dict] = []
    seen: set[str] = set()
    base = clean_story_query(story.get("canonical_title", ""))
    for item in candidates:
        page_url = str(item.get("url") or "").strip()
        asset_url = str(item.get("image") or "").strip()
        key = asset_url or page_url
        if not key or key in seen:
            continue
        seen.add(key)
        results.append({
            "id": str(uuid.uuid4()),
            "media_type": "image",
            "title": str(item.get("title") or base).strip(),
            "page_url": page_url or asset_url,
            "asset_url": asset_url,
            "thumbnail_url": str(item.get("thumbnail") or asset_url).strip(),
            "source": str(item.get("source") or "").strip(),
            "provider": str(item.get("provider") or "DDGS").strip(),
            "duration": "",
            "published_at": "",
            "width": _as_int(item.get("width")),
            "height": _as_int(item.get("height")),
            "search_query": str(item.get("_search_query") or ""),
        })
        if len(results) >= max_images:
            break

    return results, errors


def search_story_media(
    story: dict,
    max_images: int = 3,
    max_videos: int = 12,
    query_cache: dict[str, list[dict]] | None = None,
) -> tuple[list[dict], list[str]]:
    base = clean_story_query(story.get("canonical_title", ""))
    if not base:
        return [], ["Story title is empty."]

    videos, errors = _search_youtube_videos(story, max_videos, query_cache=query_cache)
    has_hd_video = any((_as_int(item.get("height")) or 0) >= 720 for item in videos)

    # Images are a true fallback: do not clutter the picker when HD/4K video exists.
    images: list[dict] = []
    if not has_hd_video:
        images, image_errors = _image_fallback(story, max_images)
        errors.extend(image_errors)

    return videos + images, errors


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_slug(value: str, limit: int = 72) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-._")
    return (text[:limit] or "media").strip("-._") or "media"


def _assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("Only public http/https media URLs can be downloaded.")
    host = parsed.hostname
    try:
        direct = ipaddress.ip_address(host)
        addresses = [direct]
    except ValueError:
        try:
            info = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            addresses = [ipaddress.ip_address(row[4][0]) for row in info]
        except Exception as exc:
            raise RuntimeError(f"Could not resolve media host: {host}") from exc
    for address in addresses:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            raise RuntimeError("Refusing to download media from a local or private network address.")


def _extension_from_response(url: str, content_type: str, fallback: str = ".bin") -> str:
    clean_type = (content_type or "").split(";", 1)[0].strip().lower()
    ext = mimetypes.guess_extension(clean_type) if clean_type else None
    if ext == ".jpe":
        ext = ".jpg"
    if ext:
        return ext
    suffix = Path(urlparse(url).path).suffix.lower()
    if 1 < len(suffix) <= 8:
        return suffix
    return fallback


def download_image(url: str, target_stem: Path, max_bytes: int = 80 * 1024 * 1024) -> Path:
    current = url
    headers = {"User-Agent": "Mozilla/5.0 YTNewsStudio/0.2"}
    with httpx.Client(timeout=45, follow_redirects=False, headers=headers) as client:
        for _ in range(6):
            _assert_public_http_url(current)
            with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("Media server redirected without a location.")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if content_type and not content_type.lower().startswith("image/"):
                    raise RuntimeError(f"Selected URL is not an image ({content_type}).")
                ext = _extension_from_response(str(response.url), content_type, ".jpg")
                target = target_stem.with_suffix(ext)
                target.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            handle.close()
                            target.unlink(missing_ok=True)
                            raise RuntimeError("Image is larger than the 80 MB safety limit.")
                        handle.write(chunk)
                return target
        raise RuntimeError("Too many redirects while downloading image.")


def download_video(url: str, target_stem: Path) -> Path:
    _assert_public_http_url(url)
    from yt_dlp import YoutubeDL

    target_stem.parent.mkdir(parents=True, exist_ok=True)
    output_template = str(target_stem.parent / f"{target_stem.name}.%(ext)s")
    options = {
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
    }
    before = set(target_stem.parent.glob(f"{target_stem.name}.*"))
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        prepared = Path(ydl.prepare_filename(info))
    if prepared.exists():
        return prepared
    created = [p for p in target_stem.parent.glob(f"{target_stem.name}.*") if p not in before and p.is_file()]
    if created:
        return max(created, key=lambda p: p.stat().st_mtime)
    raise RuntimeError("Video downloader completed but no media file was created.")


def download_candidate(candidate: dict, project_root: Path, story_title: str) -> Path:
    story_folder = project_root / "media" / "selected" / _safe_slug(story_title)
    stem = story_folder / _safe_slug(candidate.get("id", "media"))
    if candidate.get("media_type") == "image":
        url = candidate.get("asset_url") or candidate.get("page_url") or ""
        return download_image(url, stem)
    if candidate.get("media_type") == "video":
        url = candidate.get("page_url") or candidate.get("asset_url") or ""
        return download_video(url, stem)
    raise RuntimeError("Unsupported media type.")
