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


def _video_rank(item: dict, base: str) -> tuple[int, int, int]:
    title = str(item.get("title") or "").lower()
    source = str(item.get("channel") or item.get("uploader") or "").lower()
    description = str(item.get("description") or "").lower()
    haystack = f"{title} {source} {description}"

    score = 0
    priority_terms = {
        "official trailer": 24,
        "official teaser": 22,
        "official clip": 20,
        "official": 14,
        "trailer": 12,
        "teaser": 11,
        "clip": 10,
        "interview": 9,
        "featurette": 8,
        "behind the scenes": 8,
        "press conference": 7,
        "press": 6,
        "red carpet": 6,
        "news": 4,
    }
    for term, weight in priority_terms.items():
        if term in haystack:
            score += weight

    story_terms = [x.lower() for x in re.findall(r"[A-Za-z0-9]+", base) if len(x) >= 4]
    overlap = sum(1 for term in story_terms[:10] if term in haystack)
    score += overlap * 3

    height = _max_video_height(item) or 0
    if height >= 2160:
        score += 30
    elif height >= 1440:
        score += 24
    elif height >= 1080:
        score += 20
    elif height >= 720:
        score += 14
    elif height:
        score -= 4

    views = _as_int(item.get("view_count")) or 0
    return score, height, views


def _youtube_search_query(story: dict) -> str:
    base = clean_story_query(story.get("canonical_title", ""))
    category = str(story.get("category") or "").lower()
    if category in {"industry", "celebrities"}:
        return f'{base} video interview news'
    if category in {"trend", "upcoming_films", "tv_series"}:
        return f'{base} official trailer clip interview'
    return f'{base} official video interview'


def _search_youtube_videos(story: dict, max_videos: int) -> tuple[list[dict], list[str]]:
    from yt_dlp import YoutubeDL

    base = clean_story_query(story.get("canonical_title", ""))
    query = _youtube_search_query(story)
    search_count = min(max(max_videos * 2, 12), 30)
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 20,
    }

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch{search_count}:{query}", download=False)
    except Exception as exc:
        return [], [f"YouTube video search failed: {exc}"]

    raw = [dict(x) for x in (info or {}).get("entries") or [] if x]
    raw.sort(key=lambda item: _video_rank(item, base), reverse=True)

    results: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        video_id = str(item.get("id") or "").strip()
        page_url = str(item.get("webpage_url") or item.get("original_url") or "").strip()
        if not page_url and video_id:
            page_url = f"https://www.youtube.com/watch?v={video_id}"
        if not page_url or page_url in seen:
            continue
        seen.add(page_url)

        height = _max_video_height(item)
        results.append({
            "id": str(uuid.uuid4()),
            "media_type": "video",
            "title": str(item.get("title") or base).strip(),
            "page_url": page_url,
            "asset_url": page_url,
            "thumbnail_url": _youtube_thumbnail(item),
            "source": str(item.get("channel") or item.get("uploader") or "YouTube").strip(),
            "provider": "YouTube",
            "duration": str(item.get("duration_string") or item.get("duration") or "").strip(),
            "published_at": str(item.get("upload_date") or item.get("release_date") or "").strip(),
            "width": _as_int(item.get("width")),
            "height": height,
            "search_query": query,
        })
        if len(results) >= max_videos:
            break

    return results, []


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
        "format": "best[ext=mp4]/best",
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
