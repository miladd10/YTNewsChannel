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
    "fandom entertainment",
)

OFFICIAL_CHANNEL_TERMS = (
    "official", "pictures", "studios", "entertainment", "films",
    "netflix", "warner bros", "warnerbrospictures", "paramount pictures",
    "universal pictures", "sony pictures", "marvel entertainment",
    "dc", "disney", "hbo", "apple tv", "prime video", "amazon mgm",
    "lionsgate", "a24", "neon", "searchlight pictures", "20th century studios",
    "focus features", "dreamworks", "pixar", "lucasfilm", "peacock", "hulu",
    "max", "mubi", "criterion",
)

SPOKEN_SOURCE_TERMS = (
    "interview", "podcast", "conversation with", "talks with", "talks to",
    "speaks with", "speaks to", "sit-down", "sit down",
)


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


def _video_rejection_reason(item: dict, story: dict) -> str | None:
    title = str(item.get("title") or "").lower()
    source = str(item.get("channel") or item.get("uploader") or "").lower()
    description = str(item.get("description") or "").lower()
    haystack = f"{title} {source} {description}"
    allow_spoken = story_allows_interview_or_podcast(story)

    if any(term in haystack for term in COMMENTARY_TITLE_TERMS):
        return "commentary/reaction/review"

    spoken = any(term in title for term in SPOKEN_SOURCE_TERMS) or "podcast" in source
    if spoken and not allow_spoken:
        return "interview/podcast not relevant to this story"

    # News packages and presenter/commentator channels are not B-roll. They are
    # only considered for an interview/podcast story, and even then the result
    # itself must actually be an interview/podcast clip.
    if _is_news_or_commentary_channel(source):
        if not allow_spoken or not spoken:
            return "news/commentary channel"

    return None


def _official_broll_strength(item: dict, story: dict) -> tuple[int, str]:
    title = str(item.get("title") or "").lower()
    source = str(item.get("channel") or item.get("uploader") or "").lower()
    verified = bool(item.get("channel_is_verified"))
    allow_spoken = story_allows_interview_or_podcast(story)

    if allow_spoken and any(term in title for term in SPOKEN_SOURCE_TERMS):
        # For interview/podcast news, require signs that this is the original
        # conversation source rather than a re-upload or commentary recap.
        original_spoken_source = (
            verified
            or "official" in source
            or "podcast" in source
            or "podcast" in title
        )
        if original_spoken_source:
            return 5, "original interview/podcast"

    if any(term in title for term in BROLL_TITLE_TERMS):
        if _looks_like_official_channel(source) or verified:
            return 5, "official B-roll"
        return 2, "unverified B-roll asset"

    if any(term in title for term in GENERIC_BROLL_TERMS):
        if _looks_like_official_channel(source):
            return 4, "studio/distributor B-roll"
        if verified:
            return 2, "verified-source B-roll"

    return 0, ""


def video_is_usable_broll(item: dict, story: dict) -> bool:
    if _video_rejection_reason(item, story):
        return False
    strength, _ = _official_broll_strength(item, story)
    return strength >= 3


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
    found = re.findall(r"[\"'‘’“”]([^\"'‘’“”]{2,80})[\"'‘’“”]", text or "")
    return list(dict.fromkeys(x.strip() for x in found if x.strip()))[:3]


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


def _youtube_search_queries(story: dict) -> list[str]:
    base = clean_story_query(story.get("canonical_title", ""))
    quoted = _quoted_subjects(base)
    entities = _known_entities(base)
    compact = _compact_subject(base)

    subjects = list(dict.fromkeys(quoted + ([compact] if compact else [])))
    queries: list[str] = []
    for subject in subjects[:3]:
        queries.extend([
            f'{subject} official trailer',
            f'{subject} official clip',
            f'{subject} official featurette behind the scenes',
        ])

    # Corporate/merger/legal stories often do not have event-specific footage.
    # Pull clean corporate/studio B-roll from the companies involved instead.
    for entity in entities:
        queries.extend([
            f'{entity} official studio tour',
            f'{entity} official sizzle reel',
            f'{entity} official trailer',
        ])

    if story_allows_interview_or_podcast(story):
        queries.extend([
            f'{base} full interview',
            f'{base} podcast interview',
        ])

    return list(dict.fromkeys(q.strip() for q in queries if q.strip()))


def _search_youtube_videos(story: dict, max_videos: int) -> tuple[list[dict], list[str]]:
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
    with YoutubeDL(options) as ydl:
        for query in queries:
            try:
                info = ydl.extract_info(f"ytsearch{search_count}:{query}", download=False)
                for entry in (info or {}).get("entries") or []:
                    if entry:
                        item = dict(entry)
                        item["_search_query"] = query
                        raw.append(item)
            except Exception as exc:
                errors.append(f"YouTube B-roll search failed for '{query}': {exc}")

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


def _image_fallback(base: str, max_images: int) -> tuple[list[dict], list[str]]:
    from ddgs import DDGS

    image_query = f'{base} official still poster press photo'
    results: list[dict] = []
    try:
        for item in DDGS().images(image_query, max_results=max(max_images * 2, 6)) or []:
            page_url = str(item.get("url") or "").strip()
            asset_url = str(item.get("image") or "").strip()
            if not (page_url or asset_url):
                continue
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
                "search_query": image_query,
            })
            if len(results) >= max_images:
                break
        return results, []
    except Exception as exc:
        return [], [f"Image fallback search failed: {exc}"]


def search_story_media(story: dict, max_images: int = 3, max_videos: int = 12) -> tuple[list[dict], list[str]]:
    base = clean_story_query(story.get("canonical_title", ""))
    if not base:
        return [], ["Story title is empty."]

    videos, errors = _search_youtube_videos(story, max_videos)
    has_hd_video = any((_as_int(item.get("height")) or 0) >= 720 for item in videos)

    # Images are a true fallback: do not clutter the picker when HD/4K video exists.
    images: list[dict] = []
    if not has_hd_video:
        images, image_errors = _image_fallback(base, max_images)
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
