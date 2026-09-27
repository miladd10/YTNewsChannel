from __future__ import annotations

import html as html_lib
import ipaddress
import mimetypes
import re
import socket
import uuid
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

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


def duration_seconds(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return max(0, int(float(text)))
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return None
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return None


def suggested_clip_range(duration, usage_index: int = 0, clip_seconds: int = 12) -> tuple[int | None, int | None]:
    """Give repeated uses of one source distinct, editor-friendly time ranges."""
    total = duration_seconds(duration)
    if total is None:
        # Most trailers/interviews are long enough for these conservative
        # offsets; the editor can refine them later.
        start = 5 + max(0, usage_index) * 17
        return start, start + clip_seconds
    if total <= 3:
        return 0, total
    length = min(clip_seconds, max(4, total - 2))
    usable_start = 2 if total <= 20 else 5
    stride = length + 5
    latest_start = max(0, total - length - 2)
    start = usable_start + max(0, usage_index) * stride
    if start > latest_start:
        span = max(1, latest_start - usable_start + 1)
        start = usable_start + ((max(0, usage_index) * stride) % span)
        start = min(start, latest_start)
    return int(start), int(min(total, start + length))


def _story_context_text(story: dict) -> str:
    parts = [
        str(story.get("canonical_title") or ""),
        str(story.get("summary") or ""),
        str(story.get("_narration_text") or ""),
    ]
    for article in story.get("articles") or []:
        parts.append(str(article.get("title") or ""))
    return " ".join(parts)


def _story_text(story: dict) -> str:
    return _story_context_text(story).lower()


PERSON_BROLL_TERMS = (
    "interview", "press junket", "press conference", "red carpet",
    "world premiere", "premiere", "conversation with", "talks with",
    "talks to", "speaks with", "speaks to", "behind the scenes",
)


def story_allows_interview_or_podcast(story: dict) -> bool:
    """Permit spoken/event footage only for a story or contextual fallback that calls for it."""
    if story.get("_allow_spoken_broll"):
        return True
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
    override = str(story.get("_media_subject_override") or "").strip()
    if override:
        return [override]
    base = clean_story_query(story.get("canonical_title", ""))

    # Prefer a quoted phrase that behaves like an actual title. Entertainment
    # headlines often open with a quoted slogan and mention the movie title
    # later, e.g. “Feed upon the flesh...” ... “Werwulf” trailer.
    quoted_matches: list[tuple[int, str, str]] = []
    quote_patterns = (
        r"“([^”]{2,80})”",
        r"‘([^’]{2,80})’",
        r'"([^"]{2,80})"',
        r"(?<!\\w)'([^']{2,80})'(?!\\w)",
    )
    for pattern in quote_patterns:
        for match in re.finditer(pattern, base):
            after = base[match.end():match.end() + 32].lower()
            quoted_matches.append((match.start(), match.group(1).strip(), after))
    if quoted_matches:
        title_context_terms = (" trailer", " teaser", " movie", " film", " series", " first look", " clip")
        contextual = [row for row in quoted_matches if any(term in row[2] for term in title_context_terms)]
        chosen = (contextual or quoted_matches)[0][1]
        if chosen:
            return [chosen]

    # Remove common headline prefixes that describe coverage rather than the
    # visual subject itself.
    normalized = re.sub(
        r"^(?:weekend\s+box\s+office|box\s+office)\s*:\s*",
        "",
        base,
        flags=re.IGNORECASE,
    )

    # Keep a title + subtitle together, but remove trailing credit/news clauses.
    normalized = re.split(
        r",\s*(?:directed\s+by|starring|from\s+director|from\s+filmmaker|"
        r"release\s+date|cast\b|gets\b|set\s+for\b)",
        normalized,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()

    compact = _compact_subject(normalized)
    # Strip generic leading/trailing news words so "New Resident Evil film"
    # becomes a useful subject rather than matching unrelated videos.
    words = compact.split()
    while words and words[0].lower().strip("’'") in {"new", "the", "a", "an"}:
        words.pop(0)
    while words and words[-1].lower().strip("’'") in {"film", "movie", "series", "show"}:
        words.pop()
    subject = " ".join(words).strip(" :-–—")
    return [subject] if subject else [normalized or base]



COMPARISON_VISUAL_VERBS = (
    " beats ", " vs ", " vs. ", " versus ", " tops ", " edges ",
    " outgrosses ", " overtakes ", " trails ",
)


def _clean_visual_subject(value: str) -> str:
    value = re.sub(
        r"\s+(?:in|during|over|for|after|before|with)\s+(?:week|weekend|week\s+\w+|"
        r"its\s+\w+\s+week|the\s+weekend|box\s+office).*$",
        "",
        value or "",
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+-\s+[^-]{2,80}$", "", value).strip(" ,:;–—-")
    words = value.split()
    if len(words) > 8:
        value = " ".join(words[:8])
    return value.strip()


def _comparison_visual_subjects(story: dict) -> list[str]:
    title = clean_story_query(story.get("canonical_title", ""))
    title = re.sub(
        r"^(?:weekend\s+box\s+office|box\s+office)\s*:\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    lowered = f" {title.lower()} "
    split_at: tuple[int, str] | None = None
    for verb in COMPARISON_VISUAL_VERBS:
        pos = lowered.find(verb)
        if pos >= 0 and (split_at is None or pos < split_at[0]):
            split_at = (pos, verb)
    if split_at is None:
        return []
    pos, verb = split_at
    left = _clean_visual_subject(title[: max(0, pos - 1)])
    right_start = max(0, pos - 1) + len(verb)
    right = _clean_visual_subject(title[right_start:])
    results: list[str] = []
    for value in (left, right):
        if not value:
            continue
        # Reuse the normal title cleaner for each half without recursively
        # treating the entire comparison headline as one subject.
        variant = dict(story)
        variant["canonical_title"] = value
        variant.pop("_media_subject_override", None)
        parsed = (_story_subjects(variant) or [value])[0]
        if parsed and parsed not in results:
            results.append(parsed)
    return results[:3]


def _story_visual_subjects(story: dict) -> list[str]:
    """Distinct movie/show subjects that deserve their own visual coverage."""
    primary = (_story_subjects(story) or [""])[0]
    subjects: list[str] = [primary] if primary else []

    for subject in _comparison_visual_subjects(story):
        if subject and subject not in subjects:
            subjects.append(subject)

    # Secondary quoted titles are only promoted when they are also supported by
    # the summary/narration, which avoids turning incidental headline references
    # into unnecessary B-roll targets.
    context_without_title = " ".join([
        str(story.get("summary") or ""),
        str(story.get("_narration_text") or ""),
    ])
    for quoted in _quoted_subjects(clean_story_query(story.get("canonical_title", ""))):
        if quoted in subjects:
            continue
        if _subject_matches(quoted, context_without_title):
            subjects.append(quoted)

    return subjects[:4]


def story_visual_plan(story: dict) -> dict:
    """Estimate how many distinct visual beats the narration needs."""
    subjects = _story_visual_subjects(story)
    duration = float(story.get("_voice_duration_seconds") or 0)
    narration = str(story.get("_narration_text") or "").strip()

    duration_target = 1
    if duration > 18:
        duration_target = 2
    if duration > 38:
        duration_target = 3
    if duration > 60:
        duration_target = 4

    sentence_count = len([
        part for part in re.split(r"(?<=[.!?؟])\s+", narration)
        if part.strip()
    ])
    sentence_target = 1
    if sentence_count >= 3:
        sentence_target = 2
    if sentence_count >= 6:
        sentence_target = 3

    people = _story_people(story) if _story_has_quote_or_person_context(story) else []
    target_count = max(1, len(subjects), duration_target, sentence_target)
    if people:
        target_count = max(target_count, 2)
    target_count = min(4, target_count)

    beats = [{"label": subject, "kind": "title"} for subject in subjects]
    for person in people:
        if len(beats) >= target_count:
            break
        if person not in {beat["label"] for beat in beats}:
            beats.append({"label": person, "kind": "cast/director"})

    return {
        "target_count": target_count,
        "subjects": subjects,
        "people": people,
        "beats": beats,
        "duration_seconds": duration,
    }


def _tag_coverage(items: list[dict], label: str, kind: str) -> list[dict]:
    output: list[dict] = []
    for item in items:
        cloned = dict(item)
        cloned["coverage_label"] = label
        cloned["coverage_kind"] = kind
        output.append(cloned)
    return output


def _coverage_label_for_item(item: dict, subjects: list[str]) -> str:
    haystack = f"{item.get('title') or ''} {item.get('search_query') or ''}"
    for subject in subjects:
        if _subject_matches(subject, haystack):
            return subject
    return subjects[0] if subjects else ""


def _coverage_balanced_results(items: list[dict], story: dict, limit: int) -> list[dict]:
    ranked = _dedupe_quality_first_results(items, story, max(limit * 2, limit))
    groups: dict[str, list[dict]] = {}
    for item in ranked:
        label = str(item.get("coverage_label") or "")
        groups.setdefault(label, []).append(item)

    first_pass: list[dict] = []
    used_urls: set[str] = set()
    for label in [x for x in _story_visual_subjects(story) if x in groups] + [
        key for key in groups if key not in _story_visual_subjects(story)
    ]:
        bucket = groups.get(label) or []
        if not bucket:
            continue
        item = bucket[0]
        url = str(item.get("page_url") or "")
        if url and url not in used_urls:
            used_urls.add(url)
            first_pass.append(item)

    extras = [
        item for item in ranked
        if str(item.get("page_url") or "") not in used_urls
    ]
    return (first_pass + extras)[:limit]


def _distinct_video_choice_count(items: list[dict], story: dict) -> int:
    identities = {
        _video_identity_key(item, story)
        for item in items
        if item.get("media_type") == "video"
        and (_as_int(item.get("height")) or 0) >= 720
    }
    return len(identities)


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
    if story.get("_allow_archive_media"):
        return False
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

    if item.get("_reference_direct_asset"):
        article_title = str(item.get("_reference_article_title") or "")
        if any(_subject_matches(subject, article_title) for subject in _story_subjects(story)):
            return True

    if item.get("_reference_page_url"):
        # A reference article can embed an official trailer for one concrete
        # title mentioned in a broader/multi-title news headline. Accept that
        # only when the meaningful video-title words are visibly part of the
        # supplied story packet; source authenticity is checked separately.
        video_words = _distinctive_subject_words(title)
        story_words = set(_normalized_words(_story_text(story)))
        meaningful = video_words[:4]
        if meaningful and all(word in story_words for word in meaningful):
            if len(meaningful) >= 2 or len(meaningful[0]) >= 6:
                return True

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

    if _reference_direct_asset_is_official(item, story):
        return True

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
        spoken = any(term in title for term in PERSON_BROLL_TERMS) or "podcast" in source
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

    if allow_spoken and (any(term in title for term in PERSON_BROLL_TERMS) or "podcast" in source):
        return 5, "original interview/podcast"

    if _reference_direct_asset_is_official(item, story):
        return 5, "official reference-page video"

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


def _video_quality_tier(height) -> int:
    value = _as_int(height) or 0
    if value >= 2160:
        return 5
    if value >= 1440:
        return 4
    if value >= 1080:
        return 3
    if value >= 720:
        return 2
    if value > 0:
        return 1
    return 0


def _video_source_cleanliness(item: dict, story: dict) -> int:
    """Metadata-level proxy for clean/original footage.

    We cannot reliably detect a burned-in visual watermark without decoding and
    inspecting frames, so discovery prefers original studio/distributor uploads
    and direct official assets. Those are the sources most likely to be clean or
    carry only their own official branding.
    """
    if _reference_direct_asset_is_official(item, story):
        return 5
    source = str(item.get("channel") or item.get("uploader") or "")
    if _looks_like_official_channel(source):
        return 5
    if bool(item.get("channel_is_verified")) and _is_original_visual_source(item, story):
        return 4
    if _is_original_visual_source(item, story):
        return 3
    return 0


def _video_rank(item: dict, story: dict, base: str) -> tuple[int, int, int, int, int]:
    """Quality-first ranking across all accepted source locations."""
    strength, _ = _official_broll_strength(item, story)
    title = str(item.get("title") or "").lower()
    source = str(item.get("channel") or item.get("uploader") or "").lower()
    description = str(item.get("description") or "").lower()
    haystack = f"{title} {source} {description}"

    height = _max_video_height(item) or 0
    quality_tier = _video_quality_tier(height)
    cleanliness = _video_source_cleanliness(item, story)

    relevance = strength * 50
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
            relevance += weight

    story_terms = [x.lower() for x in re.findall(r"[A-Za-z0-9]+", base) if len(x) >= 4]
    relevance += sum(1 for term in story_terms[:10] if term in haystack) * 4

    views = _as_int(item.get("view_count")) or 0
    # Resolution is intentionally first. Among equally good copies, prefer the
    # cleanest/original source, then exact official/relevance signals.
    return quality_tier, height, cleanliness, relevance, views


def _video_kind_key(title: str) -> str:
    value = (title or "").lower()
    kinds = (
        ("teaser", ("teaser",)),
        ("trailer", ("trailer",)),
        ("clip", ("clip", "scene")),
        ("featurette", ("featurette", "behind the scenes", "making of")),
        ("first-look", ("first look", "sneak peek")),
        ("interview", ("interview", "podcast")),
        ("corporate", CORPORATE_BROLL_TERMS),
    )
    for key, terms in kinds:
        if any(term in value for term in terms):
            return key
    return "video"


def _result_duration_seconds(item: dict) -> int | None:
    return duration_seconds(item.get("duration"))


def _video_identity_key(item: dict, story: dict) -> str:
    """Group likely copies of the same trailer/clip across different hosts."""
    coverage_subject = str(item.get("coverage_label") or "").strip()
    subjects = _story_subjects(story)
    subject = coverage_subject or (subjects[0] if subjects else clean_story_query(story.get("canonical_title", "")))
    subject_key = " ".join(_distinctive_subject_words(subject)[:5])
    kind = _video_kind_key(str(item.get("title") or ""))
    duration = _result_duration_seconds(item)
    # Same official trailer mirrored across regions/hosts is normally within a
    # couple seconds. Five-second buckets avoid collapsing genuinely different
    # trailer cuts while deduplicating localized mirrors.
    duration_bucket = "unknown" if duration is None else str(int(round(duration / 5.0) * 5))
    return f"{subject_key}|{kind}|{duration_bucket}"


def _result_quality_rank(item: dict, story: dict) -> tuple[int, int, int, int]:
    height = _as_int(item.get("height")) or 0
    provider = str(item.get("provider") or "").lower()
    source = str(item.get("source") or "").lower()
    title = str(item.get("title") or "").lower()
    clean = 0
    if any(term in source for term in OFFICIAL_CHANNEL_TERMS):
        clean = 5
    elif "official" in provider or "studio/distributor" in provider:
        clean = 4
    elif "reference page" in provider:
        clean = 3
    official_title = 1 if "official" in title else 0
    return _video_quality_tier(height), height, clean, official_title


def _dedupe_quality_first_results(items: list[dict], story: dict, limit: int) -> list[dict]:
    """Keep the best-quality copy of a likely-identical video, then rank all."""
    best_by_identity: dict[str, dict] = {}
    extras: list[dict] = []
    for item in items:
        key = _video_identity_key(item, story)
        current = best_by_identity.get(key)
        if current is None:
            best_by_identity[key] = item
            continue
        if _result_quality_rank(item, story) > _result_quality_rank(current, story):
            extras.append(current)
            best_by_identity[key] = item
        else:
            extras.append(item)

    primary = list(best_by_identity.values())
    primary.sort(key=lambda item: _result_quality_rank(item, story), reverse=True)

    # Keep alternate copies after the best variant so users can still choose a
    # different official source when needed.
    extras.sort(key=lambda item: _result_quality_rank(item, story), reverse=True)
    seen: set[str] = set()
    output: list[dict] = []
    for item in primary + extras:
        url = str(item.get("page_url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        output.append(item)
        if len(output) >= limit:
            break
    return output


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
    " takes ", " beats ", " unveils ", " debuts ", " drops ", " releases ",
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




PERSON_ROLE_PATTERN = re.compile(
    r"\b(?:directed\s+by|director|filmmaker|actor|actress|star|starring|creator|showrunner)\s+"
    r"([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,3})"
)
PERSON_SPEECH_PATTERN = re.compile(
    r"\b([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,2})\s+"
    r"(?:says|said|tells|reveals|explains|discusses|talks|speaks)\b"
)


def _story_people(story: dict) -> list[str]:
    text = _story_context_text(story)
    found: list[str] = []
    for pattern in (PERSON_ROLE_PATTERN, PERSON_SPEECH_PATTERN):
        for match in pattern.finditer(text):
            name = re.sub(r"\s+", " ", match.group(1)).strip(" ,:-")
            name = re.sub(
                r"^(?:director|filmmaker|actor|actress|star|creator|showrunner)\s+",
                "",
                name,
                flags=re.IGNORECASE,
            ).strip()
            if len(name.split()) >= 2 and name not in found:
                found.append(name)
    return found[:3]


def _story_has_quote_or_person_context(story: dict) -> bool:
    narration = str(story.get("_narration_text") or "")
    text = _story_text(story)
    quote_in_narration = bool(re.search(r'["“”‘’][^"“”‘’]{4,}["“”‘’]', narration))
    role_or_speech = bool(re.search(
        r"\b(director|filmmaker|actor|actress|star|cast|creator|showrunner|"
        r"says|said|tells|reveals|explains|discusses|quote|quoted)\b",
        text,
    ))
    return quote_in_narration or role_or_speech


def _franchise_subject(subject: str) -> str:
    value = re.sub(r"\s+", " ", subject or "").strip(" :-–—")
    if not value:
        return ""
    if ":" in value:
        prefix = value.split(":", 1)[0].strip()
        if len(_distinctive_subject_words(prefix)) >= 1:
            return prefix
    # Common numbered/sequel suffixes can still use the franchise name.
    value = re.sub(r"\s+(?:part|chapter|volume|season)\s+[ivx0-9]+.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+[2-9]\d*\s*$", "", value)
    return value.strip()


def _contextual_fallback_stories(story: dict) -> list[tuple[dict, str]]:
    """Build controlled fallback searches without weakening exact-title rules."""
    variants: list[tuple[dict, str]] = []

    if _story_has_quote_or_person_context(story):
        for person in _story_people(story):
            variant = dict(story)
            variant["_media_subject_override"] = person
            variant["_allow_spoken_broll"] = True
            variant["_allow_archive_media"] = True
            variant["_contextual_kind"] = "cast/director"
            variant["category"] = "celebrities"
            variants.append((variant, "cast/director"))

    subject = (_story_subjects(story) or [""])[0]
    franchise = _franchise_subject(subject)
    if franchise and not _is_corporate_story(story):
        variant = dict(story)
        variant["_media_subject_override"] = franchise
        variant["_allow_archive_media"] = True
        variant["_contextual_kind"] = "previous installment/franchise"
        variants.append((variant, "previous installment/franchise"))

    # Deduplicate equivalent subject+kind fallbacks.
    seen: set[tuple[str, str]] = set()
    output: list[tuple[dict, str]] = []
    for variant, kind in variants:
        key = (str(variant.get("_media_subject_override") or "").lower(), kind)
        if key in seen:
            continue
        seen.add(key)
        output.append((variant, kind))
    return output


REFERENCE_VIDEO_HOSTS = (
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "vimeo.com", "player.vimeo.com", "dailymotion.com", "dai.ly",
)


class _ReferenceVideoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[tuple[str, bool]] = []

    def _add(self, value: str, primary: bool) -> None:
        value = html_lib.unescape((value or "").strip())
        if value:
            self.urls.append((value, primary))

    def handle_starttag(self, tag: str, attrs) -> None:
        data = {str(k).lower(): str(v or "") for k, v in attrs}
        tag = tag.lower()
        if tag in {"iframe", "video", "source"}:
            self._add(data.get("src", ""), True)
        elif tag == "meta":
            key = (data.get("property") or data.get("name") or "").lower()
            if key in {
                "og:video", "og:video:url", "og:video:secure_url",
                "twitter:player", "twitter:player:stream",
            }:
                self._add(data.get("content", ""), True)
        elif tag == "a":
            href = data.get("href", "")
            host = (urlparse(href).hostname or "").lower()
            if any(term in host for term in REFERENCE_VIDEO_HOSTS):
                self._add(href, False)


def _normalize_reference_video_url(value: str, page_url: str) -> str:
    value = html_lib.unescape((value or "").replace("\\/", "/").strip())
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    value = urljoin(page_url, value)
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()

    if "youtube.com" in host or "youtube-nocookie.com" in host:
        match = re.search(r"/(?:embed|shorts)/([A-Za-z0-9_-]{6,})", parsed.path)
        if match:
            return f"https://www.youtube.com/watch?v={match.group(1)}"
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    return value


def _extract_reference_video_urls(html_text: str, page_url: str) -> list[tuple[str, bool]]:
    parser = _ReferenceVideoParser()
    try:
        parser.feed(html_text or "")
    except Exception:
        pass

    # Many publishers embed player metadata inside JSON-LD / JavaScript rather
    # than literal iframe/video tags.
    for key in ("embedUrl", "contentUrl"):
        pattern = rf'["\\\']{key}["\\\']\s*:\s*["\\\']([^"\\\']+)'
        for match in re.finditer(pattern, html_text or "", flags=re.IGNORECASE):
            parser.urls.append((match.group(1), True))

    # Catch escaped YouTube/Vimeo player URLs in script payloads.
    script_patterns = (
        r'https?:\\?/\\?/(?:www\\.)?youtube(?:-nocookie)?\.com\\?/(?:embed|watch)[^"\\\'<>\s]+',
        r'https?:\\?/\\?/youtu\.be\\?/[^"\\\'<>\s]+',
        r'https?:\\?/\\?/(?:player\\.)?vimeo\.com\\?/[^"\\\'<>\s]+',
    )
    for pattern in script_patterns:
        for match in re.finditer(pattern, html_text or "", flags=re.IGNORECASE):
            parser.urls.append((match.group(0), True))

    out: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for raw, primary in parser.urls:
        normalized = _normalize_reference_video_url(raw, page_url)
        if not normalized or normalized in seen:
            continue
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        seen.add(normalized)
        out.append((normalized, primary))
    return out[:16]


def _source_domain_hint(source: str) -> list[str]:
    words = [
        word for word in re.findall(r"[A-Za-z0-9]+", source or "")
        if len(word) >= 4 and word.lower() not in {"news", "daily", "weekly", "magazine", "online"}
    ]
    return words[:3]


def _resolve_reference_article_url(article: dict, client: httpx.Client) -> tuple[str, str]:
    original = str(article.get("url") or "").strip()
    if not original:
        return "", ""
    try:
        _assert_public_http_url(original)
        response = client.get(original)
        response.raise_for_status()
        final_url = str(response.url)
        final_host = (urlparse(final_url).hostname or "").lower()

        # Google News often returns a Google page rather than the publisher page.
        # Resolve it by exact article title/source through DDGS when necessary.
        if "news.google.com" not in final_host:
            return final_url, response.text
    except Exception:
        pass

    try:
        from ddgs import DDGS

        title = str(article.get("title") or "").strip()
        source = str(article.get("source") or "").strip()
        query = f'"{title}" {source}'.strip()
        hints = [x.lower() for x in _source_domain_hint(source)]
        results = DDGS().text(query, max_results=8) or []
        ranked: list[tuple[int, str]] = []
        for item in results:
            candidate = str(item.get("href") or item.get("url") or "").strip()
            host = (urlparse(candidate).hostname or "").lower()
            if not candidate or not host or "news.google.com" in host:
                continue
            score = sum(10 for hint in hints if hint in host)
            result_title = str(item.get("title") or "")
            score += sum(2 for word in _distinctive_subject_words(title)[:6] if word in result_title.lower())
            ranked.append((score, candidate))
        for _, candidate in sorted(ranked, reverse=True):
            try:
                _assert_public_http_url(candidate)
                response = client.get(candidate)
                response.raise_for_status()
                return str(response.url), response.text
            except Exception:
                continue
    except Exception:
        pass
    return "", ""


def _reference_direct_asset_is_official(item: dict, story: dict) -> bool:
    if not item.get("_reference_direct_asset"):
        return False
    article_source = str(item.get("_reference_article_source") or "")
    if _looks_like_official_channel(article_source):
        return True
    if _is_corporate_story(story):
        return any(_subject_matches(entity, article_source) for entity in _known_entities(_story_text(story)))
    return False


def _search_reference_page_videos(
    story: dict,
    max_videos: int,
    page_cache: dict[str, tuple[str, str]] | None = None,
) -> tuple[list[dict], list[str]]:
    from yt_dlp import YoutubeDL

    articles = story.get("articles") or []
    if not articles:
        return [], []

    page_cache = page_cache if page_cache is not None else {}
    errors: list[str] = []
    discovered: list[tuple[str, bool, dict, str]] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 Chrome/124 Safari/537.36 YTNewsStudio/0.3"
    }

    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        for article in articles[:4]:
            article_url = str(article.get("url") or "").strip()
            if not article_url:
                continue
            cached = page_cache.get(article_url)
            if cached is None:
                resolved_url, html_text = _resolve_reference_article_url(article, client)
                page_cache[article_url] = (resolved_url, html_text)
            else:
                resolved_url, html_text = cached
            if not resolved_url or not html_text:
                errors.append(f"Could not inspect reference page: {article.get('source') or article.get('title') or article_url}")
                continue

            for video_url, primary in _extract_reference_video_urls(html_text, resolved_url):
                discovered.append((video_url, primary, article, resolved_url))

    if not discovered:
        return [], errors

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 20,
    }
    raw: list[dict] = []
    seen_urls: set[str] = set()
    with YoutubeDL(options) as ydl:
        for video_url, primary, article, resolved_url in discovered[:20]:
            if video_url in seen_urls:
                continue
            seen_urls.add(video_url)
            try:
                info = ydl.extract_info(video_url, download=False)
                entries = (info or {}).get("entries") if isinstance(info, dict) else None
                items = [x for x in entries or [] if x] if entries else [info]
                for source_item in items:
                    if not isinstance(source_item, dict):
                        continue
                    item = dict(source_item)
                    item["_search_query"] = f"Reference page: {article.get('title') or ''}"
                    item["_reference_page_url"] = resolved_url
                    item["_reference_article_source"] = str(article.get("source") or "")
                    item["_reference_article_title"] = str(article.get("title") or "")
                    direct_host = (urlparse(video_url).hostname or "").lower()
                    item["_reference_direct_asset"] = bool(
                        primary and not any(term in direct_host for term in REFERENCE_VIDEO_HOSTS)
                    )
                    if item["_reference_direct_asset"]:
                        # Generic direct MP4/HLS metadata is often meaningless.
                        # The publisher page is the provenance for this asset.
                        item["channel"] = item.get("channel") or str(article.get("source") or "")
                        item["uploader"] = item.get("uploader") or str(article.get("source") or "")
                        item["description"] = (
                            str(item.get("description") or "") + " " + str(article.get("title") or "")
                        ).strip()
                    raw.append(item)
            except Exception as exc:
                errors.append(f"Reference video could not be inspected: {video_url} · {exc}")

    base = clean_story_query(story.get("canonical_title", ""))
    usable = [item for item in raw if video_is_usable_broll(item, story)]
    usable.sort(key=lambda item: _video_rank(item, story, base), reverse=True)

    results: list[dict] = []
    seen_pages: set[str] = set()
    for item in usable:
        video_id = str(item.get("id") or "").strip()
        page_url = str(item.get("webpage_url") or item.get("original_url") or item.get("url") or "").strip()
        if not page_url and video_id:
            page_url = f"https://www.youtube.com/watch?v={video_id}"
        if not page_url or page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        height = _max_video_height(item)
        _, source_kind = _official_broll_strength(item, story)
        results.append({
            "id": str(uuid.uuid4()),
            "media_type": "video",
            "title": str(item.get("title") or item.get("_reference_article_title") or base).strip(),
            "page_url": page_url,
            "asset_url": page_url,
            "thumbnail_url": _youtube_thumbnail(item),
            "source": str(
                item.get("channel") or item.get("uploader")
                or item.get("_reference_article_source") or "Reference page"
            ).strip(),
            "provider": f"Reference page · {source_kind or 'official/original video'}",
            "duration": str(item.get("duration_string") or item.get("duration") or "").strip(),
            "published_at": str(item.get("upload_date") or item.get("release_date") or "").strip(),
            "width": _as_int(item.get("width")),
            "height": height,
            "search_query": str(item.get("_search_query") or ""),
        })
        if len(results) >= max_videos:
            break
    return results, errors



OFFICIAL_WEB_DOMAIN_TERMS = (
    "netflix.com", "warnerbros.com", "warnerbros.co.uk", "paramount.com",
    "paramountpictures.com", "sonypictures.com", "marvel.com", "disney.com",
    "universalpictures.com", "focusfeatures.com", "a24films.com", "lionsgate.com",
    "20thcenturystudios.com", "searchlightpictures.com", "dreamworks.com",
    "pixar.com", "lucasfilm.com", "max.com", "hbomax.com", "primevideo.com",
    "amazon.com", "apple.com", "tv.apple.com", "imax.com",
)


def _web_video_search_queries(story: dict) -> list[str]:
    contextual_kind = str(story.get("_contextual_kind") or "")
    contextual_subject = (_story_subjects(story) or [clean_story_query(story.get("canonical_title", ""))])[0]
    if contextual_kind == "cast/director":
        return list(dict.fromkeys([
            f'"{contextual_subject}" interview 4K',
            f'"{contextual_subject}" press junket 1080p',
            f'"{contextual_subject}" red carpet premiere',
            f'"{contextual_subject}" behind the scenes',
        ]))
    if contextual_kind == "previous installment/franchise":
        return list(dict.fromkeys([
            f'"{contextual_subject}" "official trailer" 4K',
            f'"{contextual_subject}" "official clip" 4K',
            f'"{contextual_subject}" official featurette',
            f'"{contextual_subject}" official trailer site:vimeo.com',
        ]))

    if _is_corporate_story(story):
        queries: list[str] = []
        for entity in _known_entities(_story_text(story)):
            queries.extend([
                f'"{entity}" official studio video 4K',
                f'"{entity}" official company video 1080p',
            ])
        return list(dict.fromkeys(queries))

    subject = (_story_subjects(story) or [clean_story_query(story.get("canonical_title", ""))])[0]
    queries = [
        f'"{subject}" "official trailer" 4K',
        f'"{subject}" "official trailer" 1080p',
        f'"{subject}" "official clip" 4K',
        f'"{subject}" official video',
        f'"{subject}" official trailer site:vimeo.com',
        f'"{subject}" official trailer site:dailymotion.com',
    ]
    for distributor in _story_distributors(story):
        queries.insert(0, f'"{subject}" "{distributor}" official trailer 4K')
    if story_allows_interview_or_podcast(story):
        queries.extend([
            f'"{subject}" full interview 4K',
            f'"{subject}" full interview 1080p',
        ])
    return list(dict.fromkeys(q.strip() for q in queries if q.strip()))


def _web_result_might_be_video(url: str, title: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if any(term in host for term in REFERENCE_VIDEO_HOSTS):
        return True
    if any(term in host for term in OFFICIAL_WEB_DOMAIN_TERMS):
        lowered = (title or "").lower()
        return any(term in lowered for term in GENERIC_BROLL_TERMS + BROLL_TITLE_TERMS)
    return False


def _search_web_video_sources(
    story: dict,
    max_videos: int,
    search_cache: dict[str, list[dict]] | None = None,
) -> tuple[list[dict], list[str]]:
    """Search beyond YouTube/reference pages, then let yt-dlp inspect candidates."""
    from ddgs import DDGS
    from yt_dlp import YoutubeDL

    search_cache = search_cache if search_cache is not None else {}
    urls: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for query in _web_video_search_queries(story):
        cached = search_cache.get(query)
        if cached is None:
            try:
                cached = [dict(x) for x in (DDGS().text(query, max_results=10) or [])]
                search_cache[query] = [dict(x) for x in cached]
            except Exception as exc:
                errors.append(f"Web video search failed for '{query}': {exc}")
                continue
        for result in cached:
            url = str(result.get("href") or result.get("url") or "").strip()
            title = str(result.get("title") or "").strip()
            if not url or not _web_result_might_be_video(url, title):
                continue
            urls.append((url, title, query))

    if not urls:
        return [], errors

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 20,
    }
    raw: list[dict] = []
    seen_urls: set[str] = set()
    with YoutubeDL(options) as ydl:
        for url, result_title, query in urls[:24]:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                info = ydl.extract_info(url, download=False)
                entries = (info or {}).get("entries") if isinstance(info, dict) else None
                items = [x for x in entries or [] if x] if entries else [info]
                for source_item in items:
                    if not isinstance(source_item, dict):
                        continue
                    item = dict(source_item)
                    item["_search_query"] = query
                    item["_web_discovery"] = True
                    if not item.get("title"):
                        item["title"] = result_title
                    raw.append(item)
            except Exception as exc:
                errors.append(f"Web video candidate could not be inspected: {url} · {exc}")

    base = clean_story_query(story.get("canonical_title", ""))
    usable = [item for item in raw if video_is_usable_broll(item, story)]
    usable.sort(key=lambda item: _video_rank(item, story, base), reverse=True)

    results: list[dict] = []
    seen_pages: set[str] = set()
    for item in usable:
        video_id = str(item.get("id") or "").strip()
        page_url = str(item.get("webpage_url") or item.get("original_url") or item.get("url") or "").strip()
        if not page_url and video_id:
            page_url = f"https://www.youtube.com/watch?v={video_id}"
        if not page_url or page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        height = _max_video_height(item)
        _, source_kind = _official_broll_strength(item, story)
        host = (urlparse(page_url).hostname or "web").replace("www.", "")
        results.append({
            "id": str(uuid.uuid4()),
            "media_type": "video",
            "title": str(item.get("title") or base).strip(),
            "page_url": page_url,
            "asset_url": page_url,
            "thumbnail_url": _youtube_thumbnail(item),
            "source": str(item.get("channel") or item.get("uploader") or host).strip(),
            "provider": f"Web video · {source_kind or 'official/original source'}",
            "duration": str(item.get("duration_string") or item.get("duration") or "").strip(),
            "published_at": str(item.get("upload_date") or item.get("release_date") or "").strip(),
            "width": _as_int(item.get("width")),
            "height": height,
            "search_query": str(item.get("_search_query") or ""),
        })
        if len(results) >= max_videos:
            break
    return results, errors


def _youtube_search_queries(story: dict) -> list[str]:
    base = clean_story_query(story.get("canonical_title", ""))

    contextual_kind = str(story.get("_contextual_kind") or "")
    contextual_subject = (_story_subjects(story) or [base])[0]
    if contextual_kind == "cast/director":
        return list(dict.fromkeys([
            f'{contextual_subject} interview',
            f'{contextual_subject} press junket',
            f'{contextual_subject} press conference',
            f'{contextual_subject} red carpet premiere',
            f'{contextual_subject} behind the scenes',
        ]))
    if contextual_kind == "previous installment/franchise":
        return list(dict.fromkeys([
            f'{contextual_subject} official trailer 4K',
            f'{contextual_subject} official trailer',
            f'{contextual_subject} official clip',
            f'{contextual_subject} official featurette',
        ]))

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
    reference_page_cache: dict[str, tuple[str, str]] | None = None,
    web_video_cache: dict[str, list[dict]] | None = None,
) -> tuple[list[dict], list[str]]:
    base = clean_story_query(story.get("canonical_title", ""))
    if not base:
        return [], ["Story title is empty."]

    reference_videos, reference_errors = _search_reference_page_videos(
        story,
        max_videos=max_videos,
        page_cache=reference_page_cache,
    )
    youtube_videos, youtube_errors = _search_youtube_videos(
        story,
        max_videos,
        query_cache=query_cache,
    )
    web_videos, web_errors = _search_web_video_sources(
        story,
        max_videos=max_videos,
        search_cache=web_video_cache,
    )
    errors = reference_errors + youtube_errors + web_errors

    # Source location is not priority. Compare every accepted copy globally and
    # rank by resolution first: 4K > 1440p > 1080p > 720p. For likely mirrors of
    # the same trailer/clip, keep the highest-quality/original copy first.
    videos = _dedupe_quality_first_results(
        reference_videos + youtube_videos + web_videos,
        story,
        max_videos,
    )

    has_hd_video = any((_as_int(item.get("height")) or 0) >= 720 for item in videos)

    # If the exact/current-title pass finds no HD footage, broaden carefully.
    # This is intentionally a second pass so archive footage can never outrank
    # real footage from the newly announced movie/show.
    contextual_videos: list[dict] = []
    if not has_hd_video:
        for fallback_story, fallback_kind in _contextual_fallback_stories(story):
            fallback_youtube, fallback_youtube_errors = _search_youtube_videos(
                fallback_story,
                max_videos,
                query_cache=query_cache,
            )
            fallback_web, fallback_web_errors = _search_web_video_sources(
                fallback_story,
                max_videos=max_videos,
                search_cache=web_video_cache,
            )
            errors.extend(fallback_youtube_errors)
            errors.extend(fallback_web_errors)
            for item in fallback_youtube + fallback_web:
                cloned = dict(item)
                cloned["provider"] = f"Contextual B-roll · {fallback_kind}"
                contextual_videos.append(cloned)

        if contextual_videos:
            contextual_videos = _dedupe_quality_first_results(
                contextual_videos,
                story,
                max_videos,
            )
            videos = contextual_videos
            has_hd_video = any((_as_int(item.get("height")) or 0) >= 720 for item in videos)

    # Images are the final fallback after current-title and contextual video.
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
        "format": "bestvideo+bestaudio/best",
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
