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


def _video_thumbnail(item: dict) -> str:
    images = item.get("images")
    if isinstance(images, dict):
        return str(images.get("large") or images.get("medium") or images.get("small") or "")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            return str(first.get("url") or first.get("image") or "")
        return str(first)
    return str(item.get("thumbnail") or "")


def search_story_media(story: dict, max_images: int = 10, max_videos: int = 8) -> tuple[list[dict], list[str]]:
    from ddgs import DDGS

    base = clean_story_query(story.get("canonical_title", ""))
    if not base:
        return [], ["Story title is empty."]

    image_query = f'{base} movie official still poster'
    video_query = f'{base} movie official trailer interview'
    results: list[dict] = []
    errors: list[str] = []

    try:
        for item in DDGS().images(image_query, max_results=max_images) or []:
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
    except Exception as exc:
        errors.append(f"Image search failed: {exc}")

    try:
        for item in DDGS().videos(video_query, max_results=max_videos) or []:
            page_url = str(item.get("content") or item.get("url") or item.get("href") or "").strip()
            if not page_url:
                continue
            results.append({
                "id": str(uuid.uuid4()),
                "media_type": "video",
                "title": str(item.get("title") or base).strip(),
                "page_url": page_url,
                "asset_url": page_url,
                "thumbnail_url": _video_thumbnail(item),
                "source": str(item.get("uploader") or item.get("publisher") or "").strip(),
                "provider": str(item.get("provider") or "DDGS").strip(),
                "duration": str(item.get("duration") or "").strip(),
                "published_at": str(item.get("published") or "").strip(),
                "width": None,
                "height": None,
                "search_query": video_query,
            })
    except Exception as exc:
        errors.append(f"Video search failed: {exc}")

    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for item in results:
        key = (item["media_type"], item["page_url"] or item["asset_url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped, errors


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
