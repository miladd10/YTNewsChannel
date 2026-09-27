from __future__ import annotations

import csv
import json
import math
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
            "target_url": path.resolve().as_uri(),
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


def write_resolve_package(root: Path, plan: dict) -> dict:
    resolve_dir = root / "resolve"
    resolve_dir.mkdir(parents=True, exist_ok=True)

    plan_path = root / "timing" / "resolve_plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    otio = build_otio(root, plan)
    otio_path = resolve_dir / "news_timeline.otio"
    otio_path.write_text(json.dumps(otio, indent=2, ensure_ascii=False), encoding="utf-8")

    with (resolve_dir / "voice_timing.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "segment_index", "story_id", "start_seconds", "end_seconds",
            "duration_seconds", "audio_path", "alignment_mode",
        ])
        for item in plan.get("voice_segments") or []:
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
        for item in plan.get("visual_clips") or []:
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
        "warnings": plan.get("warnings") or [],
    }
    manifest_path = resolve_dir / "package_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    readme = f"""# {plan.get('project_name') or 'YT News'} - DaVinci Resolve Handoff

This package uses the generated ElevenLabs narration as the master timeline.

- Timeline: {RESOLVE_WIDTH} x {RESOLVE_HEIGHT} UHD
- Frame rate: {plan['fps']} fps
- Voice playback speed: unchanged
- Video playback speed: unchanged
- Source video audio: muted
- Scaling target: Scale full frame with crop

Import **news_timeline.otio** through File > Import > Timeline.

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
    }
