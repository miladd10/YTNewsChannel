from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from .media import duration_seconds

RESOLVE_WIDTH = 3840
RESOLVE_HEIGHT = 2160
DEFAULT_FPS = 30
DEFAULT_VIDEO_CUT = 7.0
DEFAULT_IMAGE_HOLD = 5.0


def _rt(value: int | float, fps: int) -> dict:
    return {
        "OTIO_SCHEMA": "RationalTime.1",
        "rate": fps,
        "value": int(round(value)),
    }


def _range(start: int, duration: int, fps: int) -> dict:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "duration": _rt(max(0, duration), fps),
        "start_time": _rt(max(0, start), fps),
    }


def _gap(duration: int, fps: int, name: str = "Gap") -> dict:
    return {
        "OTIO_SCHEMA": "Gap.1",
        "effects": [],
        "markers": [],
        "enabled": True,
        "metadata": {},
        "name": name,
        "source_range": _range(0, max(0, duration), fps),
    }


def _clip(
    name: str,
    path: Path,
    duration_frames: int,
    fps: int,
    *,
    media_kind: str,
    source_start_frames: int = 0,
    available_frames: int | None = None,
    metadata: dict | None = None,
) -> dict:
    duration_frames = max(1, int(duration_frames))
    source_start_frames = max(0, int(source_start_frames))
    available_frames = max(
        source_start_frames + duration_frames,
        int(available_frames) if available_frames is not None else source_start_frames + duration_frames,
    )
    meta = {
        "yt_news_studio": {
            "media_kind": media_kind,
            **(metadata or {}),
        }
    }
    return {
        "OTIO_SCHEMA": "Clip.1",
        "effects": [],
        "markers": [],
        "enabled": True,
        "media_reference": {
            "OTIO_SCHEMA": "ExternalReference.1",
            "available_range": _range(0, available_frames, fps),
            "metadata": meta,
            "name": path.name,
            # Resolve 20/21 is more reliable with a raw absolute filesystem
            # path here than a file:// URI. The Resolve package stages every
            # referenced asset under resolve/media before this is written.
            "target_url": str(path.resolve()),
        },
        "metadata": meta,
        "name": name,
        "source_range": _range(source_start_frames, duration_frames, fps),
    }


def _track(name: str, kind: str, children: list[dict]) -> dict:
    return {
        "OTIO_SCHEMA": "Track.1",
        "children": children,
        "effects": [],
        "kind": kind,
        "markers": [],
        "enabled": True,
        "metadata": {},
        "name": name,
        "source_range": None,
    }


def _safe_path(root: Path, stored: str) -> Path | None:
    if not stored:
        return None
    path = (root / stored).resolve()
    if root.resolve() not in path.parents or not path.exists() or not path.is_file():
        return None
    return path


def crop_instruction(width: int | None, height: int | None) -> dict:
    try:
        width = int(width or 0)
        height = int(height or 0)
    except (TypeError, ValueError):
        width = height = 0
    if width <= 0 or height <= 0:
        return {
            "mode": "scale_full_frame_with_crop",
            "target": [RESOLVE_WIDTH, RESOLVE_HEIGHT],
            "source_aspect": None,
            "crop_axis": "unknown",
            "crop_fraction": None,
            "position": [0.5, 0.5],
        }

    source_aspect = width / height
    target_aspect = RESOLVE_WIDTH / RESOLVE_HEIGHT
    if abs(source_aspect - target_aspect) < 0.002:
        axis = "none"
        fraction = 0.0
    elif source_aspect > target_aspect:
        kept_width = height * target_aspect
        axis = "horizontal"
        fraction = max(0.0, min(1.0, 1.0 - kept_width / width))
    else:
        kept_height = width / target_aspect
        axis = "vertical"
        fraction = max(0.0, min(1.0, 1.0 - kept_height / height))

    return {
        "mode": "scale_full_frame_with_crop",
        "target": [RESOLVE_WIDTH, RESOLVE_HEIGHT],
        "source_aspect": round(source_aspect, 6),
        "crop_axis": axis,
        "crop_fraction": round(fraction, 6),
        "position": [0.5, 0.5],
    }


def voice_timeline(voice_segments: list[dict]) -> tuple[list[dict], float]:
    result = []
    cursor = 0.0
    for row in sorted(voice_segments, key=lambda x: int(x.get("segment_index") or 0)):
        duration = max(0.0, float(row.get("duration_seconds") or 0))
        if duration <= 0 or not row.get("audio_path"):
            continue
        start = cursor
        end = start + duration
        result.append({
            "id": row.get("id"),
            "segment_index": int(row.get("segment_index") or 0),
            "story_id": str(row.get("story_id") or ""),
            "source_text": row.get("source_text") or "",
            "audio_path": row.get("audio_path") or "",
            "start": round(start, 6),
            "end": round(end, 6),
            "duration": round(duration, 6),
            "alignment": _loads_alignment(row.get("alignment_json")),
        })
        cursor = end
    return result, round(cursor, 6)


def _loads_alignment(value) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def story_windows(voice: list[dict]) -> list[dict]:
    windows: list[dict] = []
    for segment in voice:
        story_id = segment.get("story_id") or ""
        if (
            windows
            and windows[-1]["story_id"] == story_id
            and abs(float(windows[-1]["end"]) - float(segment["start"])) < 0.001
        ):
            windows[-1]["end"] = segment["end"]
            windows[-1]["duration"] = round(float(windows[-1]["end"]) - float(windows[-1]["start"]), 6)
            windows[-1]["segment_ids"].append(segment["id"])
        else:
            windows.append({
                "story_id": story_id,
                "start": segment["start"],
                "end": segment["end"],
                "duration": segment["duration"],
                "segment_ids": [segment["id"]],
            })
    return windows


def _candidate_available_seconds(candidate: dict) -> float | None:
    total = duration_seconds(candidate.get("duration"))
    return float(total) if total is not None else None


def _video_source_start(candidate: dict, use_index: int, wanted: float) -> float:
    available = _candidate_available_seconds(candidate)
    base = float(candidate.get("clip_start_sec") or 0)
    stride = max(DEFAULT_VIDEO_CUT + 2.0, wanted + 2.0)
    start = base + use_index * stride
    if available is None:
        return max(0.0, start)
    latest = max(0.0, available - max(1.0, wanted))
    if start <= latest:
        return start
    if latest <= 0:
        return 0.0
    return (base + use_index * stride) % max(1.0, latest)


def _visual_slices(window: dict, candidates: list[dict]) -> list[dict]:
    duration = max(0.0, float(window.get("duration") or 0))
    if duration <= 0 or not candidates:
        return []

    # Favor video, but keep selected stills useful as short visual resets.
    ordered = sorted(
        candidates,
        key=lambda item: (
            0 if item.get("media_type") == "video" else 1,
            str(item.get("title") or ""),
        ),
    )

    slices = []
    cursor = float(window["start"])
    end = float(window["end"])
    uses: dict[str, int] = {}
    asset_index = 0

    while cursor < end - 0.02:
        item = ordered[asset_index % len(ordered)]
        asset_index += 1
        media_type = item.get("media_type") or ""
        remaining = end - cursor
        default_hold = DEFAULT_VIDEO_CUT if media_type == "video" else DEFAULT_IMAGE_HOLD
        # Avoid a tiny tail cut when one slightly longer final hold is cleaner.
        hold = min(default_hold, remaining)
        if remaining > default_hold and remaining - default_hold < 2.5:
            hold = remaining
        hold = max(0.05, hold)

        key = str(item.get("page_url") or item.get("id") or "")
        use_index = uses.get(key, 0)
        uses[key] = use_index + 1

        source_in = 0.0
        source_out = None
        available = _candidate_available_seconds(item)
        if media_type == "video":
            source_in = _video_source_start(item, use_index, hold)
            if available is not None:
                hold = min(hold, max(0.05, available - source_in))
            source_out = source_in + hold

        slices.append({
            "story_id": window.get("story_id") or "",
            "candidate_id": item.get("id") or "",
            "media_type": media_type,
            "title": item.get("title") or "",
            "source": item.get("source") or "",
            "page_url": item.get("page_url") or "",
            "stored_path": item.get("stored_path") or "",
            "timeline_start": round(cursor, 6),
            "timeline_end": round(min(end, cursor + hold), 6),
            "timeline_duration": round(min(end, cursor + hold) - cursor, 6),
            "source_in": round(source_in, 6),
            "source_out": round(source_out, 6) if source_out is not None else None,
            "source_media_duration": available,
            "source_audio": "muted",
            "playback_speed": 1.0,
            "crop": crop_instruction(item.get("width"), item.get("height")),
            "shared_source": bool(item.get("shared_source")),
            "use_index": use_index,
        })
        cursor += hold
        if hold <= 0.05 and remaining > 0.05:
            break

    return slices


def build_edit_plan(project: dict, voice_segments: list[dict], candidates: list[dict], fps: int = DEFAULT_FPS) -> dict:
    fps = max(1, min(60, int(fps or DEFAULT_FPS)))
    voice, total_duration = voice_timeline(voice_segments)
    windows = story_windows(voice)

    selected_by_story: dict[str, list[dict]] = {}
    for item in candidates:
        if not item.get("selected") or item.get("download_status") != "downloaded" or not item.get("stored_path"):
            continue
        selected_by_story.setdefault(str(item.get("story_id") or ""), []).append(item)

    visuals = []
    warnings = []
    for window in windows:
        story_id = str(window.get("story_id") or "")
        story_candidates = selected_by_story.get(story_id, [])
        if not story_candidates:
            warnings.append(
                "No downloaded selected media for "
                + (f"story {story_id}" if story_id else "intro/transition/outro narration")
                + f" ({window['duration']:.2f}s)."
            )
            continue
        visuals.extend(_visual_slices(window, story_candidates))

    return {
        "version": 1,
        "generator": "YT News Studio",
        "project_id": project.get("id"),
        "project_name": project.get("name"),
        "fps": fps,
        "timeline": {
            "width": RESOLVE_WIDTH,
            "height": RESOLVE_HEIGHT,
            "duration_seconds": total_duration,
            "total_frames": int(math.ceil(total_duration * fps)),
            "video_scaling": "Scale full frame with crop",
            "video_source_audio": "muted",
            "voice_master_timing": True,
        },
        "voice_segments": voice,
        "story_windows": windows,
        "visual_clips": visuals,
        "warnings": warnings,
    }


def _video_track(root: Path, plan: dict) -> dict:
    fps = int(plan["fps"])
    total_frames = int(plan["timeline"]["total_frames"])
    children = []
    cursor = 0
    for item in plan.get("visual_clips") or []:
        start = int(round(float(item["timeline_start"]) * fps))
        duration = max(1, int(round(float(item["timeline_duration"]) * fps)))
        start = max(cursor, start)
        if start > cursor:
            children.append(_gap(start - cursor, fps, "Visual gap"))
        path = _safe_path(root, item.get("stored_path") or "")
        if not path:
            raise RuntimeError(f"Resolve media is missing: {item.get('stored_path')}")
        source_start = int(round(float(item.get("source_in") or 0) * fps))
        available = item.get("source_media_duration")
        available_frames = (
            max(source_start + duration, int(round(float(available) * fps)))
            if available is not None
            else source_start + duration
        )
        children.append(_clip(
            item.get("title") or path.name,
            path,
            duration,
            fps,
            media_kind=item.get("media_type") or "video",
            source_start_frames=source_start if item.get("media_type") == "video" else 0,
            available_frames=available_frames,
            metadata={
                "story_id": item.get("story_id"),
                "candidate_id": item.get("candidate_id"),
                "source_in_seconds": item.get("source_in"),
                "source_out_seconds": item.get("source_out"),
                "playback_speed": 1.0,
                "source_audio": "muted",
                "crop": item.get("crop"),
            },
        ))
        cursor = start + duration
    if cursor < total_frames:
        children.append(_gap(total_frames - cursor, fps, "Visual tail gap"))
    return _track("V1 - News B-roll / Stills", "Video", children)


def _audio_track(root: Path, plan: dict) -> dict:
    fps = int(plan["fps"])
    total_frames = int(plan["timeline"]["total_frames"])
    children = []
    cursor = 0
    for item in plan.get("voice_segments") or []:
        start = int(round(float(item["start"]) * fps))
        duration = max(1, int(round(float(item["duration"]) * fps)))
        if start > cursor:
            children.append(_gap(start - cursor, fps, "Voice gap"))
        path = _safe_path(root, item.get("audio_path") or "")
        if not path:
            raise RuntimeError(f"Narration audio is missing: {item.get('audio_path')}")
        children.append(_clip(
            f"{int(item.get('segment_index') or 0):03d} - Narration",
            path,
            duration,
            fps,
            media_kind="audio",
            source_start_frames=0,
            available_frames=duration,
            metadata={
                "segment_id": item.get("id"),
                "story_id": item.get("story_id"),
                "alignment_mode": "elevenlabs_forced_alignment",
            },
        ))
        cursor = max(cursor, start + duration)
    if cursor < total_frames:
        children.append(_gap(total_frames - cursor, fps, "Voice tail gap"))
    return _track("A1 - ElevenLabs Narration", "Audio", children)


def build_otio(root: Path, plan: dict) -> dict:
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "metadata": {
            "yt_news_studio": {
                "generator": "YT News Studio",
                "fps": plan["fps"],
                "target_resolution": [RESOLVE_WIDTH, RESOLVE_HEIGHT],
                "voice_master_timing": True,
                "video_source_audio": "muted",
                "scaling": "Scale full frame with crop",
            }
        },
        "name": f"{plan.get('project_name') or 'YT News'} - News Edit",
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "children": [
                _video_track(root, plan),
                _audio_track(root, plan),
            ],
            "effects": [],
            "markers": [],
            "enabled": True,
            "metadata": {},
            "name": "tracks",
            "source_range": None,
        },
    }


def _stage_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
    except Exception:
        shutil.copy2(source, target)


def _safe_stage_name(prefix: str, index: int, source: Path, suffix: str | None = None) -> str:
    final_suffix = (suffix or source.suffix or "").lower()
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in source.stem).strip("_")
    stem = stem[:72] or "media"
    return f"{prefix}_{index:03d}_{stem}{final_suffix}"


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg is required to build Resolve-safe media. Install ffmpeg, restart YT News Studio, "
            "and regenerate the Resolve package."
        )
    return ffmpeg


def _require_ffprobe() -> str:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError(
            "FFprobe is required to validate Resolve-safe media. Install ffmpeg, restart YT News Studio, "
            "and regenerate the Resolve package."
        )
    return ffprobe


def _probe_media_duration(path: Path) -> float | None:
    ffprobe = _require_ffprobe()
    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        value = float((result.stdout or "").strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _clamp_video_source_in(source_in: float, requested_duration: float, source_duration: float | None) -> float:
    source_in = max(0.0, float(source_in or 0))
    requested_duration = max(0.0, float(requested_duration or 0))
    if source_duration is None or source_duration <= 0:
        return source_in
    # Keep at least one source frame available. If the requested cut is longer
    # than the source, start at zero and the staging filter will hold the final
    # frame to fill the requested timeline duration.
    latest = max(0.0, float(source_duration) - min(requested_duration, float(source_duration)))
    return min(source_in, latest)


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = "\n".join((result.stderr or "").splitlines()[-10:])
        raise RuntimeError(f"FFmpeg could not create Resolve-safe media. {tail}".strip())


def _stage_resolve_image(source: Path, target: Path) -> None:
    ffmpeg = _require_ffmpeg()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    _run_ffmpeg([
        ffmpeg, "-y", "-v", "error",
        "-i", str(source),
        "-frames:v", "1",
        str(target),
    ])
    if not target.exists() or target.stat().st_size <= 0:
        raise RuntimeError(f"Resolve-safe image was not created: {target.name}")


def _stage_resolve_video_cut(
    source: Path,
    target: Path,
    *,
    source_in: float,
    duration: float,
    fps: int,
    source_duration: float | None = None,
) -> dict:
    ffmpeg = _require_ffmpeg()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)

    duration = max(0.05, float(duration or 0.05))
    fps = max(1, int(fps or DEFAULT_FPS))
    source_duration = source_duration if source_duration is not None else _probe_media_duration(source)
    adjusted_source_in = _clamp_video_source_in(source_in, duration, source_duration)

    # Resolve/OTIO works in frames. Render an exact number of CFR frames instead
    # of trusting a fractional -t duration. tpad clones the final frame if the
    # source ends before the requested narration window.
    frame_count = max(1, int(round(duration * fps)))
    staged_duration = frame_count / fps
    filter_chain = (
        f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        f"fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={staged_duration + 1.0:.6f}"
    )
    common = [
        ffmpeg, "-y", "-v", "error",
        "-i", str(source),
        "-ss", f"{adjusted_source_in:.6f}",
        "-map", "0:v:0",
        "-an", "-sn", "-dn",
        "-vf", filter_chain,
        "-frames:v", str(frame_count),
        "-pix_fmt", "yuv420p",
        "-tag:v", "avc1",
        "-movflags", "+faststart",
    ]
    attempts = [
        common + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(target)],
        common + ["-c:v", "h264_videotoolbox", "-b:v", "20M", str(target)],
    ]
    errors: list[str] = []
    for command in attempts:
        try:
            _run_ffmpeg(command)
            if not target.exists() or target.stat().st_size <= 0:
                raise RuntimeError("FFmpeg returned success but no usable MP4 was written.")
            measured = _probe_media_duration(target)
            tolerance = max(0.12, 2.0 / fps)
            if measured is None or measured + tolerance < staged_duration:
                raise RuntimeError(
                    f"Staged MP4 is shorter than planned: expected {staged_duration:.3f}s, "
                    f"got {measured if measured is not None else 'unknown'}."
                )
            return {
                "source_duration": source_duration,
                "requested_source_in": max(0.0, float(source_in or 0)),
                "adjusted_source_in": adjusted_source_in,
                "frame_count": frame_count,
                "staged_duration": staged_duration,
                "measured_duration": measured,
            }
        except Exception as exc:
            errors.append(str(exc))
            target.unlink(missing_ok=True)
    raise RuntimeError(
        f"Could not create a validated H.264 Resolve-safe cut from {source.name}: "
        + " | ".join(errors[-2:])
    )



def _stage_resolve_media(root: Path, plan: dict) -> tuple[dict, dict]:
    """Create a Resolve-local media folder and rewrite plan paths to it.

    Resolve's OTIO importer can ignore/lose file:// targets and then search only
    by filename. Keeping every referenced file together under resolve/media and
    emitting raw absolute paths makes the handoff deterministic.
    """
    resolve_media = root / "resolve" / "media"
    if resolve_media.exists():
        shutil.rmtree(resolve_media)
    resolve_media.mkdir(parents=True, exist_ok=True)

    staged = json.loads(json.dumps(plan))
    cache: dict[str, str] = {}
    video_stage_meta: dict[str, dict] = {}
    source_duration_cache: dict[str, float | None] = {}
    voice_count = 0
    visual_count = 0

    for item in staged.get("voice_segments") or []:
        source = _safe_path(root, item.get("audio_path") or "")
        if not source:
            raise RuntimeError(f"Narration audio is missing: {item.get('audio_path')}")
        key = str(source)
        relative = cache.get(key)
        if not relative:
            voice_count += 1
            target = resolve_media / _safe_stage_name("voice", int(item.get("segment_index") or voice_count), source)
            _stage_file(source, target)
            relative = target.relative_to(root).as_posix()
            cache[key] = relative
        item["source_audio_path"] = item.get("audio_path") or ""
        item["audio_path"] = relative

    fps = int(staged.get("fps") or DEFAULT_FPS)
    for item in staged.get("visual_clips") or []:
        source = _safe_path(root, item.get("stored_path") or "")
        if not source:
            raise RuntimeError(f"Resolve media is missing: {item.get('stored_path')}")

        media_type = str(item.get("media_type") or "")
        original_stored_path = item.get("stored_path") or ""
        original_source_in = float(item.get("source_in") or 0)
        original_source_out = item.get("source_out")
        duration = max(0.05, float(item.get("timeline_duration") or 0.05))

        if media_type == "video":
            # Use the duration of the file that was actually downloaded, not
            # discovery metadata. Some providers report trailer durations that
            # differ from the downloaded asset; unbounded source-in values can
            # otherwise create header-only MP4s that Resolve shows as Offline.
            source_key = str(source)
            if source_key not in source_duration_cache:
                source_duration_cache[source_key] = _probe_media_duration(source)
            actual_source_duration = source_duration_cache[source_key]
            adjusted_source_in = _clamp_video_source_in(
                original_source_in,
                duration,
                actual_source_duration,
            )
            frame_count = max(1, int(round(duration * fps)))
            planned_stage_duration = frame_count / fps
            key = (
                f"video-cut|{source}|{adjusted_source_in:.6f}|"
                f"{frame_count}|{fps}"
            )
            relative = cache.get(key)
            stage_meta = video_stage_meta.get(key)
            if not relative:
                visual_count += 1
                target = resolve_media / _safe_stage_name("visual", visual_count, source, ".mp4")
                stage_meta = _stage_resolve_video_cut(
                    source,
                    target,
                    source_in=adjusted_source_in,
                    duration=planned_stage_duration,
                    fps=fps,
                    source_duration=actual_source_duration,
                )
                relative = target.relative_to(root).as_posix()
                cache[key] = relative
                video_stage_meta[key] = stage_meta
            item["source_stored_path"] = original_stored_path
            item["original_source_in"] = original_source_in
            item["original_source_out"] = original_source_out
            item["actual_source_duration"] = actual_source_duration
            item["adjusted_source_in"] = (stage_meta or {}).get("adjusted_source_in", adjusted_source_in)
            item["stored_path"] = relative
            item["source_in"] = 0.0
            item["source_out"] = planned_stage_duration
            item["source_media_duration"] = planned_stage_duration
            item["timeline_duration"] = planned_stage_duration
            item["resolve_frame_count"] = frame_count
            item["resolve_measured_duration"] = (stage_meta or {}).get("measured_duration")
            item["resolve_media_format"] = "H.264 MP4 · yuv420p · CFR · validated frames"
        else:
            # Normalize every still to PNG. Resolve can be inconsistent with
            # WebP/AVIF and with images whose URL extension did not match bytes.
            key = f"image|{source}"
            relative = cache.get(key)
            if not relative:
                visual_count += 1
                target = resolve_media / _safe_stage_name("visual", visual_count, source, ".png")
                _stage_resolve_image(source, target)
                relative = target.relative_to(root).as_posix()
                cache[key] = relative
            item["source_stored_path"] = original_stored_path
            item["stored_path"] = relative
            item["source_in"] = 0.0
            item["source_out"] = None
            item["source_media_duration"] = None
            item["resolve_media_format"] = "PNG still"

    return staged, {
        "media_folder": str(resolve_media),
        "staged_unique_files": len(cache),
        "staged_voice_files": voice_count,
        "staged_visual_files": visual_count,
        "resolve_safe_media": True,
    }


def write_resolve_package(root: Path, plan: dict) -> dict:
    resolve_dir = root / "resolve"
    resolve_dir.mkdir(parents=True, exist_ok=True)
    staged_plan, staged_info = _stage_resolve_media(root, plan)

    plan_path = root / "timing" / "resolve_plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(staged_plan, indent=2, ensure_ascii=False), encoding="utf-8")

    otio = build_otio(root, staged_plan)
    otio_path = resolve_dir / "news_timeline.otio"
    otio_path.write_text(json.dumps(otio, indent=2, ensure_ascii=False), encoding="utf-8")

    with (resolve_dir / "voice_timing.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "segment_index", "story_id", "start_seconds", "end_seconds",
            "duration_seconds", "audio_path", "alignment_mode",
        ])
        for item in staged_plan.get("voice_segments") or []:
            writer.writerow([
                item.get("segment_index"), item.get("story_id"), item.get("start"),
                item.get("end"), item.get("duration"), item.get("audio_path"),
                "elevenlabs_forced_alignment",
            ])

    with (resolve_dir / "media_timing.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "story_id", "candidate_id", "media_type", "timeline_start", "timeline_end",
            "duration", "source_in", "source_out", "playback_speed", "source_audio",
            "crop_mode", "crop_axis", "crop_fraction", "stored_path",
        ])
        for item in staged_plan.get("visual_clips") or []:
            crop = item.get("crop") or {}
            writer.writerow([
                item.get("story_id"), item.get("candidate_id"), item.get("media_type"),
                item.get("timeline_start"), item.get("timeline_end"), item.get("timeline_duration"),
                item.get("source_in"), item.get("source_out"), item.get("playback_speed"),
                item.get("source_audio"), crop.get("mode"), crop.get("crop_axis"),
                crop.get("crop_fraction"), item.get("stored_path"),
            ])

    manifest = {
        "version": 1,
        "generator": "YT News Studio",
        "timeline_file": "resolve/news_timeline.otio",
        "edit_plan_file": "timing/resolve_plan.json",
        "voice_timing_file": "resolve/voice_timing.csv",
        "media_timing_file": "resolve/media_timing.csv",
        "compatibility": {
            "application": "DaVinci Resolve 21",
            "edition": "Free",
            "timeline_resolution": [RESOLVE_WIDTH, RESOLVE_HEIGHT],
            "fps": plan["fps"],
            "external_scripting_required": False,
        },
        "media_folder": "resolve/media",
        "staged_unique_files": staged_info["staged_unique_files"],
        "resolve_safe_media": True,
        "video_stage_format": "H.264 MP4 · yuv420p · CFR exact frames · avc1 · no source audio",
        "image_stage_format": "PNG",
        "warnings": staged_plan.get("warnings") or [],
    }
    manifest_path = resolve_dir / "package_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    readme = f"""# {plan.get('project_name') or 'YT News'} - DaVinci Resolve Handoff

This package uses the generated ElevenLabs narration as the master timeline.

- Timeline: {RESOLVE_WIDTH} x {RESOLVE_HEIGHT} UHD
- Frame rate: {staged_plan['fps']} fps
- Voice playback speed: unchanged
- Video playback speed: unchanged
- Source video audio: muted
- Scaling target: Scale full frame with crop

Import **news_timeline.otio** through File > Import > Timeline.

All media referenced by the OTIO is staged under **resolve/media/** and the OTIO
uses raw absolute filesystem paths for DaVinci Resolve compatibility. Video cuts
are normalized to **H.264 MP4 / yuv420p / CFR exact frames** with source audio removed,
and still images are normalized to **PNG**, so Resolve does not depend on the
original YouTube codec/container or web-image format. Source-in values are clamped against the
actual downloaded-file duration, and every staged MP4 is probed before the OTIO is written.
Do not import
an older package after changing/approving voice takes; regenerate this Resolve package first.

The OTIO source ranges trim each downloaded video to the planned source in/out range.
Still images are held only for their assigned narration interval.
For source media that is not already 16:9, **media_timing.csv** contains the calculated
crop axis/fraction with a center focal point. Resolve should use the project/input scaling
equivalent of **Scale full frame with crop**.

The current planner chooses timing-safe source ranges from the curated official B-roll.
It does not yet perform semantic frame analysis inside a trailer; refine source in/out or
focal position in Resolve when a more specific visual moment is desired.
"""
    (resolve_dir / "README.md").write_text(readme, encoding="utf-8")

    return {
        "resolve_folder": str(resolve_dir),
        "timeline_path": str(otio_path),
        "plan_path": str(plan_path),
        "manifest_path": str(manifest_path),
        "voice_timing_path": str(resolve_dir / "voice_timing.csv"),
        "media_timing_path": str(resolve_dir / "media_timing.csv"),
        "media_folder": staged_info["media_folder"],
        "staged_unique_files": staged_info["staged_unique_files"],
    }
