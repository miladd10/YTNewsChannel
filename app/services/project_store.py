from __future__ import annotations

from ..version import APP_VERSION

import json
import platform
import re
import subprocess
from pathlib import Path

PROJECT_SCHEMA_VERSION = 13
PROJECT_DIRS = [
    "research/raw",
    "research/stories",
    "narration",
    "narration/plans",
    "narration/reviews",
    "narration/fact-checks",
    "narration/claims",
    "audio/narration",
    "timing",
    "media-plan",
    "media/candidates",
    "media/selected",
    "media/composites",
    "resolve",
    "exports",
]


def clean_folder_name(name: str) -> str:
    value = re.sub(r'[\\/:*?\"<>|]+', "-", name).strip().strip(".")
    value = re.sub(r"\s+", " ", value)
    return value or "YT News Project"


def ensure_project_structure(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for relative in PROJECT_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def create_project_folder(parent: Path, project_name: str) -> Path:
    parent = parent.expanduser().resolve()
    if not parent.exists() or not parent.is_dir():
        raise ValueError("The selected save location does not exist.")
    base = clean_folder_name(project_name)
    candidate = parent / base
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{base} {suffix}"
        suffix += 1
    ensure_project_structure(candidate)
    return candidate


def choose_folder(prompt: str = "Choose a folder") -> str | None:
    system = platform.system()
    if system == "Darwin":
        escaped = prompt.replace("\\", "\\\\").replace('"', '\\"')
        result = subprocess.run(
            ["osascript", "-e", f'POSIX path of (choose folder with prompt "{escaped}")'],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            if "user canceled" in (result.stderr or "").lower() or "-128" in (result.stderr or ""):
                return None
            raise RuntimeError(result.stderr.strip() or "Could not open folder picker.")
        return str(Path(result.stdout.strip()).expanduser().resolve())
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title=prompt)
        root.destroy()
        return str(Path(selected).expanduser().resolve()) if selected else None
    except Exception as exc:
        raise RuntimeError("A native folder picker is not available on this computer.") from exc


def reveal_in_file_manager(path: Path) -> None:
    target = path.expanduser().resolve()
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(target)])
    elif system == "Windows":
        subprocess.Popen(["explorer", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


def save_manifest(conn, project_id: str) -> Path:
    project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not project:
        raise ValueError("Project not found")
    root = Path(project["root_path"]).expanduser().resolve()
    ensure_project_structure(root)
    latest_run = conn.execute(
        "SELECT * FROM research_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)
    ).fetchone()
    # Only the latest run's stories plus any older story still referenced by
    # voice segments or media. Every run's full story list is already saved
    # under research/stories/<run_id>.json, so nothing is lost; this keeps
    # project.json small instead of repeating every run.
    referenced = {
        str(row[0]) for row in conn.execute(
            """SELECT story_id FROM voice_segments WHERE project_id=? AND story_id<>''
               UNION SELECT story_id FROM media_candidates WHERE project_id=?""",
            (project_id, project_id),
        ).fetchall()
    }
    latest_run_id = latest_run["id"] if latest_run else ""
    stories = [dict(row) for row in conn.execute(
        "SELECT * FROM stories WHERE project_id=? ORDER BY score DESC, created_at", (project_id,)
    ).fetchall() if row["run_id"] == latest_run_id or row["id"] in referenced]
    narrations = [dict(row) for row in conn.execute(
        "SELECT * FROM narrations WHERE project_id=? ORDER BY version_number", (project_id,)
    ).fetchall()]
    narration_reviews = [dict(row) for row in conn.execute(
        "SELECT * FROM narration_reviews WHERE project_id=? ORDER BY created_at", (project_id,)
    ).fetchall()]
    claim_ledger = [dict(row) for row in conn.execute(
        "SELECT * FROM claim_ledger WHERE project_id=? ORDER BY narration_id,created_at,id", (project_id,)
    ).fetchall()]
    narration_claim_checks = [dict(row) for row in conn.execute(
        "SELECT * FROM narration_claim_checks WHERE project_id=? ORDER BY narration_id,created_at,id", (project_id,)
    ).fetchall()]
    voice_settings = conn.execute(
        "SELECT * FROM voice_settings WHERE project_id=?", (project_id,)
    ).fetchone()
    voice_segments = [dict(row) for row in conn.execute(
        "SELECT * FROM voice_segments WHERE project_id=? ORDER BY segment_index", (project_id,)
    ).fetchall()]
    media_plans = [dict(row) for row in conn.execute(
        "SELECT * FROM media_plans WHERE project_id=? ORDER BY created_at", (project_id,)
    ).fetchall()]
    media_candidates = [dict(row) for row in conn.execute(
        "SELECT * FROM media_candidates WHERE project_id=? ORDER BY story_id,media_type,created_at", (project_id,)
    ).fetchall()]
    payload = {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "project": dict(project),
        "latest_research_run": dict(latest_run) if latest_run else None,
        "stories": stories,
        "narrations": narrations,
        "narration_reviews": narration_reviews,
        "claim_ledger": claim_ledger,
        "narration_claim_checks": narration_claim_checks,
        "voice_settings": dict(voice_settings) if voice_settings else None,
        "voice_segments": voice_segments,
        "media_plans": media_plans,
        "media_candidates": media_candidates,
    }
    path = root / "project.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
