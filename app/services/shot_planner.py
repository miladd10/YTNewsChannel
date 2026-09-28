from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

DEFAULT_SCENE_THRESHOLD = 0.30
MIN_USEFUL_SHOT = 1.15
IDEAL_SHOT_MIN = 2.5
IDEAL_SHOT_MAX = 6.0
MAX_SCENE_PIECE = 6.0


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        check=False,
    )


def _probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = _run([
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    if result.returncode != 0:
        return None
    try:
        value = float((result.stdout or "").strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _cache_key(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _scene_boundaries(path: Path, duration: float, threshold: float) -> list[float]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return []
    filt = f"scale=320:-2,select='gt(scene,{threshold:.3f})',showinfo"
    result = _run([
        ffmpeg, "-hide_banner", "-loglevel", "info",
        "-i", str(path),
        "-an", "-vf", filt,
        "-f", "null", "-",
    ])
    text = "\n".join([result.stdout or "", result.stderr or ""])
    values: list[float] = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", text):
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        if 0.05 < value < duration - 0.05:
            values.append(value)
    out: list[float] = []
    for value in sorted(values):
        if not out or value - out[-1] > 0.12:
            out.append(value)
    return out


def _split_long_range(start: float, end: float) -> list[tuple[float, float]]:
    if end - start <= MAX_SCENE_PIECE + 0.4:
        return [(start, end)]
    pieces: list[tuple[float, float]] = []
    cursor = start
    while cursor < end - 0.05:
        remaining = end - cursor
        if remaining <= MAX_SCENE_PIECE + 0.8:
            pieces.append((cursor, end))
            break
        piece = min(MAX_SCENE_PIECE, remaining)
        pieces.append((cursor, cursor + piece))
        cursor += piece
    return pieces


def _score_range(start: float, end: float, duration: float) -> float:
    length = end - start
    mid = (start + end) / 2.0
    ratio = mid / max(duration, 0.01)
    score = 0.0
    if IDEAL_SHOT_MIN <= length <= IDEAL_SHOT_MAX:
        score += 35
    elif 1.6 <= length <= 7.5:
        score += 20
    else:
        score += 5
    if duration >= 20:
        if start < 3.5:
            score -= 45
        if end > duration - 2.5:
            score -= 35
    elif duration >= 12:
        if start < 1.5:
            score -= 22
        if end > duration - 1.2:
            score -= 16
    if 0.12 <= ratio <= 0.86:
        score += 18
    if 0.25 <= ratio <= 0.75:
        score += 8
    return score


def analyze_video_shots(
    path: Path,
    *,
    cache_dir: Path | None = None,
    threshold: float = DEFAULT_SCENE_THRESHOLD,
) -> dict:
    duration = _probe_duration(path)
    if duration is None:
        return {"duration": None, "shots": [], "mode": "unavailable"}

    cache_path = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{_cache_key(path)}.json"
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data.get("version") == 1:
                    return data
            except Exception:
                pass

    boundaries = _scene_boundaries(path, duration, threshold)
    points = [0.0, *boundaries, duration]
    raw_ranges: list[tuple[float, float]] = []
    for left, right in zip(points, points[1:]):
        if right - left >= MIN_USEFUL_SHOT:
            raw_ranges.extend(_split_long_range(left, right))

    if len(raw_ranges) < 3:
        guard_in = 3.5 if duration >= 20 else (1.5 if duration >= 12 else 0.0)
        guard_out = 2.5 if duration >= 20 else (1.0 if duration >= 12 else 0.0)
        start = min(guard_in, max(0.0, duration - 1.0))
        stop = max(start + 0.5, duration - guard_out)
        raw_ranges = []
        cursor = start
        while cursor < stop - 0.5:
            end = min(stop, cursor + 5.0)
            raw_ranges.append((cursor, end))
            cursor = end

    shots = []
    for index, (start, end) in enumerate(raw_ranges):
        if end - start < MIN_USEFUL_SHOT:
            continue
        shots.append({
            "index": index,
            "start": round(start, 6),
            "end": round(end, 6),
            "duration": round(end - start, 6),
            "score": round(_score_range(start, end, duration), 3),
            "scene_boundary": True,
        })
    shots.sort(key=lambda x: (-float(x["score"]), float(x["start"])))

    data = {
        "version": 1,
        "duration": round(duration, 6),
        "threshold": threshold,
        "mode": "scene_detection" if boundaries else "fallback_windows",
        "boundary_count": len(boundaries),
        "shots": shots,
    }
    if cache_path is not None:
        try:
            cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
    return data


def _overlap_seconds(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def choose_video_shot(
    analysis: dict,
    *,
    wanted: float,
    used_ranges: list[tuple[float, float]] | None = None,
    hint_start: float | None = None,
) -> dict | None:
    used_ranges = used_ranges or []
    wanted = max(0.5, float(wanted or 0.5))
    best = None
    best_score = -10_000.0
    for shot in analysis.get("shots") or []:
        start = float(shot["start"])
        end = float(shot["end"])
        available = end - start
        if available < 0.7:
            continue
        take = min(wanted, available)
        selected_start = start + (available - take) * 0.42 if available > take + 1.0 else start
        selected_end = min(end, selected_start + take)

        score = float(shot.get("score") or 0)
        selected = (selected_start, selected_end)
        for used in used_ranges:
            overlap = _overlap_seconds(selected, used)
            if overlap > 0:
                ratio = overlap / max(0.01, selected_end - selected_start)
                score -= 90 * ratio
                if ratio > 0.65:
                    score -= 80
        if hint_start is not None:
            distance = abs(selected_start - float(hint_start))
            score += max(0.0, 12.0 - min(12.0, distance / 3.0))
        score += min(12.0, (selected_end - selected_start) * 2.0)

        if score > best_score:
            best_score = score
            best = {
                "start": round(selected_start, 6),
                "end": round(selected_end, 6),
                "duration": round(selected_end - selected_start, 6),
                "shot_index": shot.get("index"),
                "scene_start": shot.get("start"),
                "scene_end": shot.get("end"),
                "score": round(score, 3),
                "analysis_mode": analysis.get("mode"),
                "reason": "scene-aware non-overlapping trailer shot",
            }
    return best
