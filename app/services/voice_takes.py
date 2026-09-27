from __future__ import annotations

import json
from pathlib import Path

from ..db import db
from .elevenlabs_client import ElevenLabsError, forced_alignment, mp3_duration_seconds, text_to_speech
from .secrets import get_api_key


def _project_row(conn, project_id: str) -> dict:
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise ValueError("Project not found.")
    return dict(row)


def _settings_row(conn, project_id: str) -> dict:
    row = conn.execute("SELECT * FROM voice_settings WHERE project_id=?", (project_id,)).fetchone()
    if not row or not row["voice_id"]:
        raise ValueError("Choose one ElevenLabs narrator voice first.")
    return dict(row)


def _segment_row(conn, project_id: str, segment_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM voice_segments WHERE project_id=? AND id=?",
        (project_id, segment_id),
    ).fetchone()
    if not row:
        raise ValueError("Voice segment not found.")
    return dict(row)


def clear_segment_files(project_root: Path, row: dict) -> None:
    root = Path(project_root).resolve()
    for key in ("take1_path", "take2_path", "audio_path"):
        stored = str(row.get(key) or "")
        if not stored:
            continue
        try:
            path = (root / stored).resolve()
            if root in path.parents and path.exists():
                path.unlink()
        except Exception:
            pass


def generate_take(project_id: str, segment_id: str, take_number: int, stamp: str) -> dict:
    if take_number not in (1, 2):
        raise ValueError("Take number must be 1 or 2.")
    if not get_api_key("elevenlabs"):
        raise ValueError("Connect ElevenLabs first.")

    with db() as conn:
        project = _project_row(conn, project_id)
        settings = _settings_row(conn, project_id)
        row = _segment_row(conn, project_id, segment_id)
        previous_row = conn.execute(
            """SELECT performance_text,source_text FROM voice_segments
               WHERE project_id=? AND segment_index<?
               ORDER BY segment_index DESC LIMIT 1""",
            (project_id, row["segment_index"]),
        ).fetchone()
        next_row = conn.execute(
            """SELECT performance_text,source_text FROM voice_segments
               WHERE project_id=? AND segment_index>?
               ORDER BY segment_index ASC LIMIT 1""",
            (project_id, row["segment_index"]),
        ).fetchone()

    performance_text = (row.get("performance_text") or "").strip()
    if not performance_text:
        raise ValueError("Prepare Eleven v3 performance text before generating audio.")

    previous_text = (
        (previous_row["performance_text"] or previous_row["source_text"] or "").strip()
        if previous_row else None
    )
    next_text = (
        (next_row["performance_text"] or next_row["source_text"] or "").strip()
        if next_row else None
    )

    try:
        audio = text_to_speech(
            settings["voice_id"],
            performance_text,
            previous_text=previous_text,
            next_text=next_text,
            ensure_end_guard=False,
        )
    except ElevenLabsError as exc:
        raise ValueError(str(exc)) from exc

    root = Path(project["root_path"])
    audio_dir = root / "audio" / "narration"
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"{int(row['segment_index']):04d}_narration_take{take_number}.mp3"
    path.write_bytes(audio)
    rel = path.relative_to(root).as_posix()
    column = "take1_path" if take_number == 1 else "take2_path"

    with db() as conn:
        conn.execute(
            f"""UPDATE voice_segments
                SET voice_id=?,{column}=?,audio_path='',duration_seconds=NULL,alignment_json='{{}}',
                    audio_status='generated',selected_take=0,approval_status='pending',updated_at=?
                WHERE id=?""",
            (settings["voice_id"], rel, stamp, segment_id),
        )

    return {
        "ok": True,
        "take_number": take_number,
        "audio_path": rel,
        "segment_index": row["segment_index"],
    }


def approve_take(project_id: str, segment_id: str, take_number: int, stamp: str) -> dict:
    if take_number not in (1, 2):
        raise ValueError("Take number must be 1 or 2.")
    column = "take1_path" if take_number == 1 else "take2_path"

    with db() as conn:
        project = _project_row(conn, project_id)
        row = _segment_row(conn, project_id, segment_id)

    stored = str(row.get(column) or "")
    if not stored:
        raise ValueError(f"Generate Take {take_number} first.")

    root = Path(project["root_path"]).resolve()
    path = (root / stored).resolve()
    if root not in path.parents or not path.exists():
        raise ValueError(f"Take {take_number} audio file is missing.")

    duration = mp3_duration_seconds(path)
    if duration is None:
        raise ValueError("Could not measure generated MP3 duration.")

    try:
        alignment = forced_alignment(path, row["source_text"])
    except ElevenLabsError as exc:
        raise ValueError(str(exc)) from exc

    words = []
    for item in alignment.get("words") or []:
        if not isinstance(item, dict):
            continue
        try:
            word_start = float(item.get("start"))
            word_end = float(item.get("end"))
        except Exception:
            continue
        if word_end < word_start:
            continue
        words.append({
            "text": str(item.get("text") or ""),
            "start": word_start,
            "end": word_end,
            "loss": item.get("loss"),
        })
    if not words:
        raise ValueError("ElevenLabs Forced Alignment returned no word timestamps.")

    with db() as conn:
        conn.execute(
            """UPDATE voice_segments
               SET selected_take=?,audio_path=?,duration_seconds=?,alignment_json=?,
                   audio_status='aligned',approval_status='approved',updated_at=?
               WHERE project_id=? AND id=?""",
            (
                take_number,
                stored,
                float(duration),
                json.dumps({"words": words, "loss": alignment.get("loss")}, ensure_ascii=False),
                stamp,
                project_id,
                segment_id,
            ),
        )

    return {
        "ok": True,
        "selected_take": take_number,
        "duration_seconds": float(duration),
        "audio_path": stored,
    }
