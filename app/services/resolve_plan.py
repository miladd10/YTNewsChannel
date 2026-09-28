from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from .media import duration_seconds
from .shot_planner import analyze_video_shots, choose_video_shot

RESOLVE_WIDTH = 3840
RESOLVE_HEIGHT = 2160
DEFAULT_FPS = 30
DEFAULT_VIDEO_CUT = 5.5
DEFAULT_IMAGE_HOLD = 5.0
DEFAULT_DISSOLVE_FRAMES = 6
IMAGE_DISSOLVE_FRAMES = 8


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


def _transition(in_frames: int, out_frames: int, fps: int, name: str = "Dissolve") -> dict:
    return {
        "OTIO_SCHEMA": "Transition.1",
        "metadata": {"yt_news_studio": {"type": "smart_dissolve"}},
        "name": name,
        "transition_type": "SMPTE_Dissolve",
        "parameters": {},
        "in_offset": _rt(max(0, in_frames), fps),
        "out_offset": _rt(max(0, out_frames), fps),
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


def _candidate_source_path(root: Path | None, candidate: dict) -> Path | None:
    if root is None:
        return None
    return _safe_path(root, str(candidate.get("stored_path") or ""))


def _smart_video_choice(
    candidate: dict,
    *,
    root: Path | None,
    cache_dir: Path | None,
    wanted: float,
    used_ranges: list[tuple[float, float]],
    use_index: int,
) -> dict:
    source = _candidate_source_path(root, candidate)
    if source is not None:
        try:
            analysis = analyze_video_shots(source, cache_dir=cache_dir)
            chosen = choose_video_shot(
                analysis,
                wanted=wanted,
                used_ranges=used_ranges,
                hint_start=float(candidate.get("clip_start_sec") or 0),
            )
            if chosen:
                chosen["source_media_duration"] = analysis.get("duration")
                return chosen
        except Exception:
            pass

    start = _video_source_start(candidate, use_index, wanted)
    available = _candidate_available_seconds(candidate)
    hold = wanted
    if available is not None:
        hold = min(hold, max(0.05, available - start))
    return {
        "start": round(start, 6),
        "end": round(start + hold, 6),
        "duration": round(hold, 6),
        "shot_index": None,
        "scene_start": None,
        "scene_end": None,
        "score": 0.0,
        "analysis_mode": "legacy_fallback",
        "reason": "timing-safe fallback source range",
        "source_media_duration": available,
    }


def _image_candidate(images: list[dict], last_candidate_id: str | None, cursor: int) -> dict | None:
    if not images:
        return None
    for offset in range(len(images)):
        item = images[(cursor + offset) % len(images)]
        if str(item.get("id") or "") != str(last_candidate_id or "") or len(images) == 1:
            return item
    return images[cursor % len(images)]


def _visual_slices(
    window: dict,
    candidates: list[dict],
    *,
    root: Path | None = None,
    cache_dir: Path | None = None,
) -> list[dict]:
    duration = max(0.0, float(window.get("duration") or 0))
    if duration <= 0 or not candidates:
        return []

    videos = sorted(
        [item for item in candidates if item.get("media_type") == "video"],
        key=lambda item: str(item.get("title") or ""),
    )
    images = sorted(
        [item for item in candidates if item.get("media_type") == "image"],
        key=lambda item: str(item.get("title") or ""),
    )

    slices: list[dict] = []
    cursor = float(window["start"])
    end = float(window["end"])
    uses: dict[str, int] = {}
    used_ranges: dict[str, list[tuple[float, float]]] = {}
    last_candidate_id: str | None = None
    consecutive_video = 0
    image_cursor = 0

    while cursor < end - 0.02:
        remaining = end - cursor

        # Prefer moving footage. Use a selected still as a visual reset only
        # after two consecutive video cuts, or when no usable video exists.
        choose_image = bool(images) and (not videos or consecutive_video >= 2)
        item = None
        smart = None

        if not choose_image and videos:
            best_score = -10_000.0
            best = None
            for video in videos:
                key = str(video.get("page_url") or video.get("id") or "")
                use_index = uses.get(key, 0)
                wanted = min(DEFAULT_VIDEO_CUT, remaining)
                proposal = _smart_video_choice(
                    video,
                    root=root,
                    cache_dir=cache_dir,
                    wanted=wanted,
                    used_ranges=used_ranges.get(key, []),
                    use_index=use_index,
                )
                score = float(proposal.get("score") or 0)
                if str(video.get("id") or "") == str(last_candidate_id or ""):
                    score -= 18
                if use_index >= 2:
                    score -= use_index * 4
                if score > best_score:
                    best_score = score
                    best = (video, proposal, key, use_index)
            if best:
                item, smart, key, use_index = best
                uses[key] = use_index + 1
                used_ranges.setdefault(key, []).append((float(smart["start"]), float(smart["end"])))
        if item is None and images:
            item = _image_candidate(images, last_candidate_id, image_cursor)
            image_cursor += 1
            smart = None
            consecutive_video = 0
        elif item is not None:
            consecutive_video += 1

        if item is None:
            break

        media_type = item.get("media_type") or ""
        if media_type == "image":
            hold = min(DEFAULT_IMAGE_HOLD, remaining)
            # A still should not sit for a long tail. Keep image cadence at
            # roughly five seconds even when there is only one image available.
            if remaining > DEFAULT_IMAGE_HOLD and remaining - DEFAULT_IMAGE_HOLD < 1.25:
                hold = min(remaining, DEFAULT_IMAGE_HOLD)
            source_in = 0.0
            source_out = None
            available = None
            use_index = image_cursor - 1
            selection_reason = "five-second still cadence"
            shot_index = None
            scene_start = None
            scene_end = None
            analysis_mode = "still"
        else:
            hold = min(remaining, max(0.05, float((smart or {}).get("duration") or DEFAULT_VIDEO_CUT)))
            source_in = float((smart or {}).get("start") or 0)
            source_out = source_in + hold
            available = (smart or {}).get("source_media_duration")
            use_index = uses.get(str(item.get("page_url") or item.get("id") or ""), 1) - 1
            selection_reason = str((smart or {}).get("reason") or "scene-aware video shot")
            shot_index = (smart or {}).get("shot_index")
            scene_start = (smart or {}).get("scene_start")
            scene_end = (smart or {}).get("scene_end")
            analysis_mode = (smart or {}).get("analysis_mode")

        timeline_end = min(end, cursor + hold)
        actual_hold = timeline_end - cursor
        slices.append({
            "story_id": window.get("story_id") or "",
            "candidate_id": item.get("id") or "",
            "media_type": media_type,
            "title": item.get("title") or "",
            "source": item.get("source") or "",
            "page_url": item.get("page_url") or "",
            "stored_path": item.get("stored_path") or "",
            "timeline_start": round(cursor, 6),
            "timeline_end": round(timeline_end, 6),
            "timeline_duration": round(actual_hold, 6),
            "source_in": round(source_in, 6),
            "source_out": round(source_in + actual_hold, 6) if source_out is not None else None,
            "source_media_duration": available,
            "source_audio": "muted",
            "playback_speed": 1.0,
            "crop": crop_instruction(item.get("width"), item.get("height")),
            "shared_source": bool(item.get("shared_source")),
            "use_index": use_index,
            "shot_index": shot_index,
            "scene_start": scene_start,
            "scene_end": scene_end,
            "shot_analysis_mode": analysis_mode,
            "selection_reason": selection_reason,
            "transition_in_frames": 0,
            "transition_out_frames": 0,
            "transition_type": "cut",
        })
        last_candidate_id = str(item.get("id") or "")
        cursor = timeline_end

        if media_type == "image":
            consecutive_video = 0
        if actual_hold <= 0.05 and remaining > 0.05:
            break

    return slices


def _assign_transitions(clips: list[dict], fps: int) -> None:
    for clip in clips:
        clip["transition_in_frames"] = 0
        clip["transition_out_frames"] = 0
        clip["transition_type"] = "cut"

    for index in range(len(clips) - 1):
        left = clips[index]
        right = clips[index + 1]
        if abs(float(left.get("timeline_end") or 0) - float(right.get("timeline_start") or 0)) > 0.02:
            continue

        same_story = str(left.get("story_id") or "") == str(right.get("story_id") or "")
        same_candidate = str(left.get("candidate_id") or "") == str(right.get("candidate_id") or "")
        both_video = left.get("media_type") == "video" and right.get("media_type") == "video"

        # Trailer scenes cut cleanly on detected shot boundaries. Dissolves are
        # reserved for asset/type changes and story boundaries.
        if same_story and same_candidate and both_video:
            continue
        if same_story and both_video:
            continue

        total = IMAGE_DISSOLVE_FRAMES if (
            left.get("media_type") == "image" or right.get("media_type") == "image"
        ) else DEFAULT_DISSOLVE_FRAMES
        if not same_story:
            total = max(total, DEFAULT_DISSOLVE_FRAMES)

        left_frames = max(1, int(round(float(left.get("timeline_duration") or 0) * fps)))
        right_frames = max(1, int(round(float(right.get("timeline_duration") or 0) * fps)))
        total = min(total, max(0, left_frames // 4), max(0, right_frames // 4))
        if total < 2:
            continue
        before = total // 2
        after = total - before
        left["transition_out_frames"] = before
        right["transition_in_frames"] = after
        left["transition_type"] = "dissolve"
        right["transition_type"] = "dissolve"



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
        root_value = project.get("root_path")
        root = Path(root_value) if root_value else None
        cache_dir = (root / "media" / "analysis") if root else None
        visuals.extend(_visual_slices(window, story_candidates, root=root, cache_dir=cache_dir))

    _assign_transitions(visuals, fps)

    for window in windows:
        story_id = str(window.get("story_id") or "")
        if not story_id:
            continue
        story_clips = [clip for clip in visuals if str(clip.get("story_id") or "") == story_id]
        if story_clips and all(clip.get("media_type") == "image" for clip in story_clips):
            distinct_images = len({str(clip.get("candidate_id") or "") for clip in story_clips})
            needed = max(1, int(math.ceil(float(window.get("duration") or 0) / DEFAULT_IMAGE_HOLD)))
            if distinct_images < min(needed, 2):
                warnings.append(
                    f"Story {story_id} is image-only for {window['duration']:.2f}s but has only "
                    f"{distinct_images} distinct selected image(s). Select more images for ~5s visual changes."
                )

    return {
        "version": 2,
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
            "shot_selection": "scene-aware",
            "image_hold_seconds": DEFAULT_IMAGE_HOLD,
            "transition_policy": "hard cuts on trailer scene boundaries; short dissolves for still/media/story changes",
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
    clips = plan.get("visual_clips") or []

    for index, item in enumerate(clips):
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
            source_start_frames=source_start,
            available_frames=available_frames,
            metadata={
                "story_id": item.get("story_id"),
                "candidate_id": item.get("candidate_id"),
                "source_in_seconds": item.get("source_in"),
                "source_out_seconds": item.get("source_out"),
                "playback_speed": 1.0,
                "source_audio": "muted",
                "crop": item.get("crop"),
                "selection_reason": item.get("selection_reason"),
                "shot_index": item.get("shot_index"),
                "shot_analysis_mode": item.get("shot_analysis_mode"),
                "transition_type": item.get("transition_type") or "cut",
            },
        ))
        cursor = start + duration

        if index < len(clips) - 1:
            next_item = clips[index + 1]
            contiguous = abs(
                float(item.get("timeline_end") or 0) - float(next_item.get("timeline_start") or 0)
            ) <= 0.02
            out_frames = int(item.get("transition_out_frames") or 0)
            in_frames = int(next_item.get("transition_in_frames") or 0)
            if contiguous and out_frames > 0 and in_frames > 0:
                children.append(_transition(out_frames, in_frames, fps))

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


def _stage_resolve_image_hold(
    source: Path,
    target: Path,
    *,
    duration: float,
    fps: int,
) -> dict:
    """Render a still image as an exact-duration CFR H.264 hold clip.

    Resolve's OTIO importer treats a still image as essentially one source
    frame. Giving a PNG a multi-second OTIO source_range can therefore display
    the first frame and mark the remainder Offline. Rendering the hold to MP4
    makes the source duration explicit and deterministic.
    """
    ffmpeg = _require_ffmpeg()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)

    duration = max(0.05, float(duration or 0.05))
    fps = max(1, int(fps or DEFAULT_FPS))
    frame_count = max(1, int(round(duration * fps)))
    staged_duration = frame_count / fps
    common = [
        ffmpeg, "-y", "-v", "error",
        "-loop", "1",
        "-framerate", str(fps),
        "-i", str(source),
        "-an", "-sn", "-dn",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-frames:v", str(frame_count),
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-tag:v", "avc1",
        "-movflags", "+faststart",
    ]
    attempts = [
        common + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(target)],
        common + ["-c:v", "h264_videotoolbox", "-b:v", "12M", str(target)],
    ]
    errors: list[str] = []
    for command in attempts:
        try:
            _run_ffmpeg(command)
            if not target.exists() or target.stat().st_size <= 0:
                raise RuntimeError("FFmpeg returned success but no usable still-hold MP4 was written.")
            measured = _probe_media_duration(target)
            tolerance = max(0.12, 2.0 / fps)
            if measured is None or measured + tolerance < staged_duration:
                raise RuntimeError(
                    f"Staged still-hold MP4 is shorter than planned: expected {staged_duration:.3f}s, "
                    f"got {measured if measured is not None else 'unknown'}."
                )
            return {
                "frame_count": frame_count,
                "staged_duration": staged_duration,
                "measured_duration": measured,
            }
        except Exception as exc:
            errors.append(str(exc))
            target.unlink(missing_ok=True)
    raise RuntimeError(
        f"Could not create a validated H.264 still-hold from {source.name}: "
        + " | ".join(errors[-2:])
    )


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
    image_stage_meta: dict[str, dict] = {}
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

        in_handle_frames = max(0, int(item.get("transition_in_frames") or 0))
        out_handle_frames = max(0, int(item.get("transition_out_frames") or 0))
        in_handle = in_handle_frames / fps
        out_handle = out_handle_frames / fps

        if media_type == "video":
            source_key = str(source)
            if source_key not in source_duration_cache:
                source_duration_cache[source_key] = _probe_media_duration(source)
            actual_source_duration = source_duration_cache[source_key]

            # Clamp the chosen content range first, then stage transition handles
            # around it. This preserves the scene-aware shot while ensuring OTIO
            # dissolves have real frames on both sides.
            content_source_in = _clamp_video_source_in(
                original_source_in,
                duration,
                actual_source_duration,
            )
            stage_source_in = max(0.0, content_source_in - in_handle)
            actual_pre_handle = content_source_in - stage_source_in
            staged_requested_duration = actual_pre_handle + duration + out_handle
            stage_source_in = _clamp_video_source_in(
                stage_source_in,
                staged_requested_duration,
                actual_source_duration,
            )
            actual_pre_handle = max(0.0, content_source_in - stage_source_in)

            frame_count = max(1, int(round(staged_requested_duration * fps)))
            planned_stage_duration = frame_count / fps
            key = (
                f"video-cut|{source}|{stage_source_in:.6f}|"
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
                    source_in=stage_source_in,
                    duration=planned_stage_duration,
                    fps=fps,
                    source_duration=actual_source_duration,
                )
                relative = target.relative_to(root).as_posix()
                cache[key] = relative
                video_stage_meta[key] = stage_meta

            actual_stage_start = float((stage_meta or {}).get("adjusted_source_in", stage_source_in))
            source_range_start = max(0.0, content_source_in - actual_stage_start)
            item["source_stored_path"] = original_stored_path
            item["original_source_in"] = original_source_in
            item["original_source_out"] = original_source_out
            item["actual_source_duration"] = actual_source_duration
            item["adjusted_source_in"] = content_source_in
            item["staged_source_in"] = actual_stage_start
            item["stored_path"] = relative
            item["source_in"] = round(source_range_start, 6)
            item["source_out"] = round(source_range_start + duration, 6)
            item["source_media_duration"] = planned_stage_duration
            item["timeline_duration"] = duration
            item["resolve_frame_count"] = max(1, int(round(duration * fps)))
            item["resolve_staged_frame_count"] = frame_count
            item["resolve_measured_duration"] = (stage_meta or {}).get("measured_duration")
            item["resolve_media_format"] = "H.264 MP4 · yuv420p · CFR · validated frames + transition handles"
        else:
            content_frames = max(1, int(round(duration * fps)))
            staged_frames = in_handle_frames + content_frames + out_handle_frames
            planned_stage_duration = staged_frames / fps
            key = f"image-hold|{source}|{staged_frames}|{fps}"
            relative = cache.get(key)
            stage_meta = image_stage_meta.get(key)
            if not relative:
                visual_count += 1
                target = resolve_media / _safe_stage_name("visual", visual_count, source, ".mp4")
                stage_meta = _stage_resolve_image_hold(
                    source,
                    target,
                    duration=planned_stage_duration,
                    fps=fps,
                )
                relative = target.relative_to(root).as_posix()
                cache[key] = relative
                image_stage_meta[key] = stage_meta
            item["source_stored_path"] = original_stored_path
            item["stored_path"] = relative
            item["source_in"] = round(in_handle, 6)
            item["source_out"] = round(in_handle + duration, 6)
            item["source_media_duration"] = planned_stage_duration
            item["timeline_duration"] = duration
            item["resolve_frame_count"] = content_frames
            item["resolve_staged_frame_count"] = staged_frames
            item["resolve_measured_duration"] = (stage_meta or {}).get("measured_duration")
            item["resolve_media_format"] = "H.264 MP4 still hold · yuv420p · CFR · validated frames + transition handles"


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
            "crop_mode", "crop_axis", "crop_fraction", "selection_reason", "shot_index",
            "shot_analysis_mode", "transition_type", "transition_in_frames", "transition_out_frames",
            "stored_path",
        ])
        for item in staged_plan.get("visual_clips") or []:
            crop = item.get("crop") or {}
            writer.writerow([
                item.get("story_id"), item.get("candidate_id"), item.get("media_type"),
                item.get("timeline_start"), item.get("timeline_end"), item.get("timeline_duration"),
                item.get("source_in"), item.get("source_out"), item.get("playback_speed"),
                item.get("source_audio"), crop.get("mode"), crop.get("crop_axis"),
                crop.get("crop_fraction"), item.get("selection_reason"), item.get("shot_index"),
                item.get("shot_analysis_mode"), item.get("transition_type"),
                item.get("transition_in_frames"), item.get("transition_out_frames"),
                item.get("stored_path"),
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
        "image_stage_format": "H.264 MP4 still hold · yuv420p · CFR exact frames",
        "shot_selection": "cached FFmpeg scene-boundary analysis",
        "image_cadence_seconds": DEFAULT_IMAGE_HOLD,
        "transitions": "hard cuts inside trailers; short SMPTE dissolves for still/media/story changes",
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
and still-image holds are rendered to **H.264 MP4 / yuv420p / CFR exact frames**, so Resolve does not depend on the
original YouTube codec/container or web-image format. Source-in values are clamped against the
actual downloaded-file duration, and every staged MP4 is probed before the OTIO is written.
Do not import
an older package after changing/approving voice takes; regenerate this Resolve package first.

The OTIO source ranges trim each downloaded video to the planned source in/out range.
Still images are pre-rendered as exact-duration MP4 hold clips for their assigned narration interval.
For source media that is not already 16:9, **media_timing.csv** contains the calculated
crop axis/fraction with a center focal point. Resolve should use the project/input scaling
equivalent of **Scale full frame with crop**.

The planner now performs cached FFmpeg scene-boundary analysis on downloaded trailers/clips,
avoids the typical trailer intro/outro area when possible, prefers non-overlapping 2.5–6 second
shots, and uses hard cuts when moving between detected scenes from the same trailer. Selected
stills change at roughly five-second cadence. Short SMPTE dissolves are inserted only when
switching between still/media types or story boundaries; staged files include transition handles.
This is shot-aware visual editing, not full semantic vision matching to every spoken sentence.
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
