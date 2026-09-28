from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from .media import duration_seconds
from .shot_planner import analyze_video_shots, choose_video_shot

RESOLVE_WIDTH = 3840
RESOLVE_HEIGHT = 2160
DEFAULT_FPS = 30
DEFAULT_VIDEO_CUT = 5.5
DEFAULT_IMAGE_HOLD = 3.0
MIN_NARRATION_BEAT = 2.4
TARGET_NARRATION_BEAT = 4.2
MAX_NARRATION_BEAT = 5.8
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



def _compose_image_panel(root: Path, images: list[dict], layout_hint: str, group_label: str) -> dict | None:
    usable = []
    for item in images[:3]:
        path = _safe_path(root, str(item.get("stored_path") or ""))
        if path is not None:
            usable.append((item, path))
    if len(usable) < 2:
        return None

    count = min(3, len(usable))
    layout = layout_hint if layout_hint in {"two_up", "three_up", "person_plus_title", "collage"} else ("three_up" if count >= 3 else "two_up")
    if count == 2:
        boxes = [(0, 0, 1912, RESOLVE_HEIGHT), (1928, 0, RESOLVE_WIDTH, RESOLVE_HEIGHT)]
    else:
        boxes = [
            (0, 0, 1269, RESOLVE_HEIGHT),
            (1285, 0, 2555, RESOLVE_HEIGHT),
            (2571, 0, RESOLVE_WIDTH, RESOLVE_HEIGHT),
        ]

    key_payload = "|".join(
        [layout, group_label, *[str(path.resolve()) for _, path in usable[:count]]]
    )
    digest = hashlib.sha1(key_payload.encode("utf-8")).hexdigest()[:12]
    folder = root / "media" / "composites"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{layout}_{digest}.jpg"

    if not target.exists():
        canvas = Image.new("RGB", (RESOLVE_WIDTH, RESOLVE_HEIGHT), (14, 16, 20))
        for (item, path), box in zip(usable[:count], boxes):
            left, top, right, bottom = box
            size = (right - left, bottom - top)
            with Image.open(path) as source:
                source = source.convert("RGB")
                panel = ImageOps.fit(source, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
                canvas.paste(panel, (left, top))
        canvas.save(target, "JPEG", quality=95, subsampling=0)

    labels = [str(item.get("coverage_label") or item.get("title") or "").strip() for item, _ in usable[:count]]
    group = str(usable[0][0].get("coverage_group") or "")
    cue = next((str(item.get("coverage_cue") or "").strip() for item, _ in usable[:count] if str(item.get("coverage_cue") or "").strip()), "")
    reason = next((str(item.get("coverage_reason") or "").strip() for item, _ in usable[:count] if str(item.get("coverage_reason") or "").strip()), "")
    return {
        "id": f"composite:{digest}",
        "story_id": usable[0][0].get("story_id") or "",
        "media_type": "image",
        "title": f"{layout.replace('_', ' ')} · " + " + ".join(label for label in labels if label),
        "source": "YT News Studio composite",
        "page_url": "",
        "stored_path": target.relative_to(root).as_posix(),
        "width": RESOLVE_WIDTH,
        "height": RESOLVE_HEIGHT,
        "coverage_label": group_label or " + ".join(labels),
        "coverage_kind": "multi_panel",
        "coverage_group": group,
        "coverage_cue": cue,
        "coverage_reason": reason,
        "layout_hint": layout,
        "_narration_ratio": min(
            [float(item.get("_narration_ratio")) for item, _ in usable[:count] if item.get("_narration_ratio") is not None] or [0.5]
        ),
        "_composite_source_ids": [str(item.get("id") or "") for item, _ in usable[:count]],
    }


def _semantic_composite_candidates(root: Path | None, images: list[dict]) -> list[dict]:
    if root is None:
        return []
    grouped: dict[str, list[dict]] = {}
    for item in images:
        group = str(item.get("coverage_group") or "").strip()
        layout = str(item.get("layout_hint") or "single")
        if not group or layout not in {"two_up", "three_up", "person_plus_title", "collage"}:
            continue
        grouped.setdefault(group, []).append(item)

    composites: list[dict] = []
    for group, members in grouped.items():
        unique_labels = []
        chosen = []
        for item in sorted(members, key=lambda x: (float(x.get("_narration_ratio") or 1.0), str(x.get("coverage_label") or ""))):
            label = str(item.get("coverage_label") or "").strip().casefold()
            if label and label in unique_labels:
                continue
            if label:
                unique_labels.append(label)
            chosen.append(item)
            if len(chosen) >= 3:
                break
        if len(chosen) < 2:
            continue
        layout = str(chosen[0].get("layout_hint") or ("three_up" if len(chosen) >= 3 else "two_up"))
        composite = _compose_image_panel(
            root,
            chosen,
            layout,
            " + ".join(str(item.get("coverage_label") or "").strip() for item in chosen),
        )
        if composite:
            composites.append(composite)
    return composites


def _semantic_position(item: dict, narration_text: str) -> float | None:
    text = (narration_text or "").casefold()
    if not text:
        return None
    needles = [
        str(item.get("coverage_cue") or "").strip().casefold(),
        str(item.get("coverage_label") or "").strip().casefold(),
    ]
    best: int | None = None
    for needle in needles:
        if not needle:
            continue
        pos = text.find(needle)
        if pos >= 0 and (best is None or pos < best):
            best = pos
    if best is None:
        # Exact Persian/English cue matching can fail after punctuation/style
        # changes. A distinctive coverage label token still gives a useful
        # approximate spoken position.
        tokens = [token for token in re.findall(r"[\w\u0600-\u06FF]+", needles[-1]) if len(token) >= 4]
        positions = [text.find(token) for token in tokens if text.find(token) >= 0]
        if positions:
            best = min(positions)
    if best is None:
        return None
    return max(0.0, min(1.0, best / max(1, len(text))))


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
            "reserved_tail_seconds": max(0.0, float(row.get("reserved_tail_seconds") or 0)),
            "reserved_tail_kind": str(row.get("reserved_tail_kind") or ""),
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


def _alignment_visual_beat_offsets(segment: dict, usable_duration: float | None = None) -> list[float]:
    """Choose visual cut points from the actual spoken rhythm.

    Strong punctuation is preferred, then commas/pauses, then the nearest
    aligned word end. This keeps visual changes tied to narration phrases
    instead of a fixed timer.
    """
    duration = max(
        0.0,
        min(
            float(segment.get("duration") or 0),
            float(usable_duration) if usable_duration is not None else float(segment.get("duration") or 0),
        ),
    )
    if duration <= 0:
        return []

    alignment = segment.get("alignment") or {}
    raw_words = alignment.get("words") or []
    words: list[tuple[str, float, float]] = []
    for item in raw_words:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        if not text.strip():
            continue
        try:
            start = max(0.0, float(item.get("start") or 0))
            end = max(start, float(item.get("end") or start))
        except (TypeError, ValueError):
            continue
        if start >= duration + 0.05:
            continue
        words.append((text.strip(), min(end, duration), start))

    if not words:
        points: list[float] = []
        cursor = TARGET_NARRATION_BEAT
        while cursor < duration - MIN_NARRATION_BEAT:
            points.append(round(cursor, 6))
            cursor += TARGET_NARRATION_BEAT
        return points

    candidates: list[tuple[float, int]] = []
    all_word_ends: list[float] = []
    previous_end: float | None = None
    for text, end, start in words:
        if end <= 0.05 or end >= duration - 0.12:
            previous_end = end
            continue
        all_word_ends.append(end)
        strength = 0
        if re.search(r"[.!?؟؛;:]$", text):
            strength = 4
        elif re.search(r"[,،]$", text):
            strength = 3
        if previous_end is not None and start - previous_end >= 0.34:
            strength = max(strength, 2)
        if strength:
            candidates.append((end, strength))
        previous_end = end

    cuts: list[float] = []
    cursor = 0.0
    while duration - cursor > MAX_NARRATION_BEAT + 0.35:
        low = cursor + MIN_NARRATION_BEAT
        high = min(duration - 0.8, cursor + MAX_NARRATION_BEAT)
        target = min(high, cursor + TARGET_NARRATION_BEAT)

        eligible = [(t, strength) for t, strength in candidates if low <= t <= high]
        if eligible:
            chosen = max(
                eligible,
                key=lambda row: (
                    row[1],
                    -abs(row[0] - target),
                ),
            )[0]
        else:
            fallback = [t for t in all_word_ends if low <= t <= high]
            if fallback:
                chosen = min(fallback, key=lambda t: abs(t - target))
            else:
                chosen = target

        if chosen - cursor < MIN_NARRATION_BEAT - 0.1:
            break
        cuts.append(round(chosen, 6))
        cursor = chosen

    # Avoid an awkward sub-second final beat by folding it into the previous
    # visual rather than forcing a flash cut.
    if cuts and duration - cuts[-1] < 1.25:
        cuts.pop()
    return cuts


def _next_visual_beat_duration(window: dict, cursor: float, end: float) -> float:
    remaining = max(0.0, end - cursor)
    boundaries = [
        float(value)
        for value in (window.get("visual_boundaries") or [])
        if cursor + 0.08 < float(value) < end - 0.02
    ]
    if boundaries:
        return max(0.5, min(remaining, boundaries[0] - cursor))
    if remaining <= MAX_NARRATION_BEAT + 0.45:
        return remaining
    return min(remaining, DEFAULT_VIDEO_CUT)


def story_windows(voice: list[dict]) -> list[dict]:
    windows: list[dict] = []

    def add_window(
        story_id: str,
        start: float,
        end: float,
        segment_id,
        kind: str = "",
        visual_boundaries: list[float] | None = None,
    ) -> None:
        if end <= start:
            return
        visual_boundaries = [
            round(float(value), 6)
            for value in (visual_boundaries or [])
            if start + 0.05 < float(value) < end - 0.05
        ]
        if (
            windows
            and windows[-1]["story_id"] == story_id
            and windows[-1].get("reserved_kind", "") == kind
            and abs(float(windows[-1]["end"]) - float(start)) < 0.001
        ):
            windows[-1]["end"] = round(end, 6)
            windows[-1]["duration"] = round(float(end) - float(windows[-1]["start"]), 6)
            windows[-1]["segment_ids"].append(segment_id)
            windows[-1]["visual_boundaries"] = sorted(set(
                (windows[-1].get("visual_boundaries") or []) + visual_boundaries
            ))
            return
        windows.append({
            "story_id": story_id,
            "start": round(start, 6),
            "end": round(end, 6),
            "duration": round(end - start, 6),
            "segment_ids": [segment_id],
            "reserved_kind": kind,
            "visual_boundaries": visual_boundaries,
        })

    for segment in voice:
        story_id = segment.get("story_id") or ""
        start = float(segment["start"])
        end = float(segment["end"])
        reserved_tail = min(
            max(0.0, float(segment.get("reserved_tail_seconds") or 0)),
            max(0.0, end - start),
        )
        if story_id and reserved_tail > 0.05:
            story_duration = max(0.0, (end - start) - reserved_tail)
            offsets = _alignment_visual_beat_offsets(segment, story_duration)
            boundaries = [start + offset for offset in offsets]
            story_end = end - reserved_tail
            add_window(story_id, start, story_end, segment["id"], visual_boundaries=boundaries)
            add_window("", story_end, end, segment["id"], segment.get("reserved_tail_kind") or "outro")
        else:
            kind = segment.get("reserved_tail_kind") if not story_id else ""
            offsets = _alignment_visual_beat_offsets(segment) if story_id else []
            boundaries = [start + offset for offset in offsets]
            add_window(story_id, start, end, segment["id"], kind or "", boundaries)
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
    return max(0.0, latest)


def _range_overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def _next_unused_source_window(
    available: float | None,
    wanted: float,
    used_ranges: list[tuple[float, float]],
    *,
    preferred_start: float = 0.0,
) -> tuple[float, float] | None:
    if available is None or available <= 0:
        start = max(0.0, preferred_start)
        return start, start + max(0.5, wanted)

    wanted = max(0.5, min(float(wanted or 0.5), available))
    # Avoid the common trailer logo/title-card edges when the source is long
    # enough, but relax those guards if necessary to cover narration.
    guards = [(3.0, 2.0), (1.0, 0.5), (0.0, 0.0)]
    for head_guard, tail_guard in guards:
        usable_start = min(max(0.0, head_guard), max(0.0, available - 0.5))
        usable_end = max(usable_start, available - tail_guard)
        cursor = max(usable_start, min(preferred_start, usable_end))
        ordered_starts = [cursor, usable_start]
        step = max(1.5, min(4.0, wanted * 0.65))
        probe = usable_start
        while probe < usable_end - 0.4:
            ordered_starts.append(probe)
            probe += step

        seen: set[float] = set()
        for raw_start in ordered_starts:
            start = round(max(usable_start, raw_start), 6)
            if start in seen:
                continue
            seen.add(start)
            end = min(usable_end, start + wanted)
            if end - start < 0.5:
                continue
            selected = (start, end)
            overlap = sum(_range_overlap(selected, used) for used in used_ranges)
            if overlap <= 0.08:
                return selected

    return None


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
) -> dict | None:
    source = _candidate_source_path(root, candidate)
    analysis = None
    if source is not None:
        try:
            analysis = analyze_video_shots(source, cache_dir=cache_dir)
            chosen = choose_video_shot(
                analysis,
                wanted=wanted,
                used_ranges=used_ranges,
                hint_start=(float(candidate.get("clip_start_sec") or 0) if not used_ranges else None),
            )
            if chosen:
                chosen["source_media_duration"] = analysis.get("duration")
                return chosen
        except Exception:
            analysis = None

    available = (
        float(analysis.get("duration"))
        if isinstance(analysis, dict) and analysis.get("duration")
        else _candidate_available_seconds(candidate)
    )
    preferred = _video_source_start(candidate, use_index, wanted)
    unused = _next_unused_source_window(
        available,
        wanted,
        used_ranges,
        preferred_start=preferred,
    )
    if not unused:
        return None
    start, end = unused
    return {
        "start": round(start, 6),
        "end": round(end, 6),
        "duration": round(end - start, 6),
        "shot_index": None,
        "scene_start": None,
        "scene_end": None,
        "score": -5.0,
        "analysis_mode": "unused_range_fallback",
        "reason": "unused non-overlapping source range",
        "source_media_duration": available,
    }


def _low_variety_video(candidate: dict) -> bool:
    title = str(candidate.get("title") or "").casefold()
    return any(term in title for term in (
        "logo", "fanfare", "ident", "title announcement", "studio intro",
    ))



def _image_candidate(
    images: list[dict],
    used_image_ids: set[str],
    cursor: int,
    current_ratio: float | None = None,
) -> dict | None:
    if not images:
        return None
    unused = [
        item for item in images
        if str(item.get("id") or "") and str(item.get("id") or "") not in used_image_ids
    ]
    if not unused:
        return None
    if current_ratio is not None:
        semantic = [item for item in unused if item.get("_narration_ratio") is not None]
        if semantic:
            return min(
                semantic,
                key=lambda item: (
                    abs(float(item.get("_narration_ratio") or 0) - current_ratio),
                    0 if str(item.get("coverage_kind") or "") == "fun_fact" else 1,
                ),
            )
    # Preserve the original deterministic round-robin order when no semantic
    # cue exists; tests and existing projects rely on i1 -> i2 -> i3.
    for offset in range(len(images)):
        item = images[(cursor + offset) % len(images)]
        candidate_id = str(item.get("id") or "")
        if candidate_id and candidate_id not in used_image_ids:
            return item
    return None


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
        key=lambda item: (
            float(item.get("_narration_ratio")) if item.get("_narration_ratio") is not None else 2.0,
            str(item.get("title") or ""),
        ),
    )
    base_images = sorted(
        [item for item in candidates if item.get("media_type") == "image"],
        key=lambda item: (
            float(item.get("_narration_ratio")) if item.get("_narration_ratio") is not None else 2.0,
            str(item.get("title") or ""),
        ),
    )
    composites = _semantic_composite_candidates(root, base_images)
    images = sorted(
        composites + base_images,
        key=lambda item: (
            float(item.get("_narration_ratio")) if item.get("_narration_ratio") is not None else 2.0,
            0 if str(item.get("coverage_kind") or "") == "multi_panel" else 1,
            str(item.get("title") or ""),
        ),
    )

    slices: list[dict] = []
    cursor = float(window["start"])
    end = float(window["end"])
    uses: dict[str, int] = {}
    used_ranges: dict[str, list[tuple[float, float]]] = {}
    last_candidate_id: str | None = None
    consecutive_video = 0
    image_cursor = 0
    used_image_ids: set[str] = set()

    while cursor < end - 0.02:
        remaining = end - cursor
        current_ratio = max(0.0, min(1.0, (cursor - float(window["start"])) / max(0.001, duration)))

        # Prefer moving footage. Use a selected still as a visual reset only
        # after two consecutive video cuts, or when no usable video exists.
        unused_images_exist = any(str(item.get("id") or "") not in used_image_ids for item in images)
        choose_image = unused_images_exist and (not videos or consecutive_video >= 2)
        item = None
        smart = None

        if not choose_image and videos:
            best_score = -10_000.0
            best = None
            for video in videos:
                key = str(video.get("page_url") or video.get("id") or "")
                use_index = uses.get(key, 0)
                wanted = min(_next_visual_beat_duration(window, cursor, end), remaining)
                proposal = _smart_video_choice(
                    video,
                    root=root,
                    cache_dir=cache_dir,
                    wanted=wanted,
                    used_ranges=used_ranges.get(key, []),
                    use_index=use_index,
                )
                if proposal is None:
                    continue
                score = float(proposal.get("score") or 0)
                semantic_ratio = video.get("_narration_ratio")
                if semantic_ratio is not None:
                    distance = abs(float(semantic_ratio) - current_ratio)
                    score += max(-20.0, 34.0 - distance * 70.0)
                    if str(video.get("coverage_kind") or "") == "fun_fact" and distance <= 0.16:
                        score += 18.0
                if str(video.get("id") or "") == str(last_candidate_id or ""):
                    score -= 18
                if use_index >= 1:
                    score -= use_index * 4
                # Logo/fanfare/title-announcement footage is poor repeat
                # material, but a different unused range is still better than
                # leaving a narrated news section black when it is the only
                # selected moving source.
                if _low_variety_video(video) and use_index >= 1:
                    score -= 55
                if score > best_score:
                    best_score = score
                    best = (video, proposal, key, use_index)
            if best:
                item, smart, key, use_index = best
                uses[key] = use_index + 1
                used_ranges.setdefault(key, []).append((float(smart["start"]), float(smart["end"])))
        if item is None and unused_images_exist:
            item = _image_candidate(images, used_image_ids, image_cursor, current_ratio)
            if item is not None:
                image_cursor += 1
                used_image_ids.add(str(item.get("id") or ""))
            smart = None
            consecutive_video = 0
        elif item is not None:
            consecutive_video += 1

        if item is None:
            break

        media_type = item.get("media_type") or ""
        if media_type == "image":
            hold = min(DEFAULT_IMAGE_HOLD, _next_visual_beat_duration(window, cursor, end), remaining)
            source_in = 0.0
            source_out = None
            available = None
            use_index = image_cursor - 1
            selection_reason = "unique still · three-second max"
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
            "coverage_label": item.get("coverage_label") or "",
            "coverage_kind": item.get("coverage_kind") or "",
            "coverage_group": item.get("coverage_group") or "",
            "coverage_cue": item.get("coverage_cue") or "",
            "layout_hint": item.get("layout_hint") or "single",
            "composite_source_ids": item.get("_composite_source_ids") or [],
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



def _media_quality_warnings(
    story_id: str,
    candidates: list[dict],
    story_duration: float = 0.0,
) -> list[str]:
    warnings: list[str] = []
    for item in candidates:
        title = str(item.get("title") or item.get("id") or "media")
        media_type = str(item.get("media_type") or "")
        try:
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
        except (TypeError, ValueError):
            width = height = 0

        if media_type == "video" and height and height < 720:
            warnings.append(
                f"Story {story_id} selected video is below HD ({width}x{height}): {title}. "
                "Regenerate Media Sources and prefer 1080p/4K footage when available."
            )
        elif media_type == "video" and height and height < 1080:
            warnings.append(
                f"Story {story_id} selected video is only {width}x{height}: {title}. "
                "A 1080p/4K alternative is preferable for the UHD timeline."
            )

        if media_type == "image" and width and height:
            aspect = width / height
            if aspect < 1.2:
                warnings.append(
                    f"Story {story_id} selected still is portrait/square ({width}x{height}): {title}. "
                    "Prefer a landscape 16:9/high-resolution still."
                )
            elif width < 1920 or height < 900:
                warnings.append(
                    f"Story {story_id} selected still is below preferred landscape HD ({width}x{height}): {title}."
                )

        coverage_kind = str(item.get("coverage_kind") or "")
        if coverage_kind and coverage_kind not in ("current", "supporting image"):
            warnings.append(
                f"Story {story_id} uses contextual {coverage_kind} footage: {title}. "
                "It is not footage from the current title/story."
            )
    videos = [item for item in candidates if item.get("media_type") == "video"]
    images = [item for item in candidates if item.get("media_type") == "image"]
    known_video_seconds = [
        float(value)
        for value in (duration_seconds(item.get("duration")) for item in videos)
        if value is not None and value > 0
    ]
    if story_duration > 0 and videos and not images and known_video_seconds:
        total_unique_video = sum(known_video_seconds)
        if total_unique_video + 0.5 < story_duration:
            warnings.append(
                f"Story {story_id} has {story_duration:.2f}s narration but only about "
                f"{total_unique_video:.2f}s of selected video source duration. Regenerate B-roll and "
                "select/download a longer official trailer or additional relevant footage."
            )

    return list(dict.fromkeys(warnings))


def build_edit_plan(project: dict, voice_segments: list[dict], candidates: list[dict], fps: int = DEFAULT_FPS) -> dict:
    fps = max(1, min(60, int(fps or DEFAULT_FPS)))
    voice, total_duration = voice_timeline(voice_segments)
    windows = story_windows(voice)

    narration_by_story: dict[str, str] = {}
    for segment in voice:
        story_id = str(segment.get("story_id") or "")
        if story_id:
            narration_by_story[story_id] = (
                narration_by_story.get(story_id, "") + " " + str(segment.get("source_text") or "")
            ).strip()

    selected_by_story: dict[str, list[dict]] = {}
    for item in candidates:
        if not item.get("selected") or item.get("download_status") != "downloaded" or not item.get("stored_path"):
            continue
        enriched = dict(item)
        story_id = str(enriched.get("story_id") or "")
        enriched["_narration_ratio"] = _semantic_position(enriched, narration_by_story.get(story_id, ""))
        selected_by_story.setdefault(story_id, []).append(enriched)

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
        warnings.extend(_media_quality_warnings(story_id, story_candidates, float(window.get("duration") or 0)))
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
            if distinct_images < needed:
                warnings.append(
                    f"Story {story_id} is image-only for {window['duration']:.2f}s and ideally needs "
                    f"{needed} distinct images for ~3s visual changes, but only {distinct_images} are selected."
                )
        covered = sum(float(clip.get("timeline_duration") or 0) for clip in story_clips)
        missing = max(0.0, float(window.get("duration") or 0) - covered)
        if missing > 0.10:
            warnings.append(
                f"Story {story_id} has {missing:.2f}s intentionally left without news B-roll because unique "
                "usable media was exhausted. Select more distinct video/image sources to fill it."
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
            "shot_selection": "scene-aware + narration-beat aligned",
            "image_hold_seconds": DEFAULT_IMAGE_HOLD,
            "image_reuse": "never",
            "transition_policy": "prefer narration phrase boundaries + trailer scene boundaries; short dissolves for still/media/story changes",
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
        "shot_selection": "cached keyframe-first scene-boundary analysis",
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
stills are shown once only and for at most three seconds. Short SMPTE dissolves are inserted only when
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
