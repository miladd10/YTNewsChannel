from __future__ import annotations

import hashlib
import json
import re
import uuid
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import BASE_DIR, PIPELINE, db, init_db
from .services.ai import generate_text
from .services.local_cli import all_statuses, launch_login
from .services.media import _coverage_balanced_results, download_candidate, search_story_media, story_media_key, story_visual_plan, suggested_clip_range
from .services.elevenlabs_client import ElevenLabsError, MODEL_ID as ELEVEN_MODEL_ID, forced_alignment, list_voices, mp3_duration_seconds, text_to_speech
from .services.voice_pipeline import extract_narration_segments, performance_text_is_safe, prepare_performance
from .services.voice_takes import approve_take as approve_voice_take_service, clear_segment_files, generate_take as generate_voice_take_service
from .services.project_store import choose_folder, create_project_folder, reveal_in_file_manager, save_manifest
from .services.prompts import MEDIA_PLAN_SYSTEM
from .services.cinema_format import (
    CINEMA_WEEKLY_FORMAT,
    CONTENT_PLAN_SYSTEM,
    ENRICHMENT_REWRITE_SYSTEM,
    REVISION_SYSTEM,
    REVIEWER_SYSTEM,
    SECTION_ORDER,
    STYLE_PROFILE_SYSTEM,
    WRITER_SYSTEM,
    build_style_packet,
    format_packet,
    parse_review_gate,
    style_corpus_hash,
)
from .services.research import (
    ai_enrich_story_spice,
    ai_rank_stories,
    annotate_source_window,
    cluster_articles,
    fetch_google_news,
    fetch_social_sources,
    fetch_story_spice_sources,
)
from .services.resolve_plan import build_edit_plan, write_resolve_package
from .services.secrets import delete_api_key, get_api_key, masked_status, save_ai_settings, set_api_key
from .version import APP_RELEASE_NAME, APP_VERSION

STATIC_DIR = BASE_DIR / "static"
app = FastAPI(title="YT News Studio", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_week() -> tuple[str, str]:
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


def _resolve_input_signature(voice_rows: list[dict], candidates: list[dict]) -> str:
    voice = [
        {
            "id": row.get("id"),
            "audio_path": row.get("audio_path"),
            "duration_seconds": round(float(row.get("duration_seconds") or 0), 6),
            "selected_take": int(row.get("selected_take") or 0),
            "approval_status": row.get("approval_status") or "",
            "audio_status": row.get("audio_status") or "",
            "story_id": row.get("story_id") or "",
            "reserved_tail_seconds": round(float(row.get("reserved_tail_seconds") or 0), 6),
            "reserved_tail_kind": row.get("reserved_tail_kind") or "",
        }
        for row in sorted(voice_rows, key=lambda x: int(x.get("segment_index") or 0))
    ]
    media = [
        {
            "id": row.get("id"),
            "story_id": row.get("story_id"),
            "stored_path": row.get("stored_path"),
            "download_status": row.get("download_status") or "",
            "selected": int(row.get("selected") or 0),
        }
        for row in sorted(candidates, key=lambda x: (str(x.get("story_id") or ""), str(x.get("id") or "")))
    ]
    payload = json.dumps({"voice": voice, "media": media}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()



def _story_url_set(story: dict) -> set[str]:
    return {
        str(article.get("url") or "").strip().lower()
        for article in story.get("articles") or []
        if str(article.get("url") or "").strip()
    }


RESOLVE_TITLE_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "from", "new", "movie", "film", "series", "trailer", "teaser", "official",
    "first", "look", "release", "date", "details", "news",
}


def _resolve_title_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").casefold())
        if len(token) >= 3 and token not in RESOLVE_TITLE_STOPWORDS
    ]


def _resolve_story_match_score(historical: dict, current: dict) -> int:
    """Score whether an old narration story is the same current Included story."""
    if not historical or not current:
        return 0
    if str(historical.get("id") or "") == str(current.get("id") or ""):
        return 10_000

    score = 0
    old_title = " ".join(str(historical.get("canonical_title") or "").casefold().split())
    new_title = " ".join(str(current.get("canonical_title") or "").casefold().split())
    if old_title and old_title == new_title:
        score += 500
    elif old_title and new_title:
        ratio = SequenceMatcher(None, old_title, new_title).ratio()
        old_tokens = set(_resolve_title_tokens(old_title))
        new_tokens = set(_resolve_title_tokens(new_title))
        if old_tokens and new_tokens:
            shared_count = len(old_tokens & new_tokens)
            overlap_ratio = shared_count / max(1, min(len(old_tokens), len(new_tokens)))
            if shared_count >= 3 and overlap_ratio >= 0.5:
                score += 360 + min(80, shared_count * 10)
            elif overlap_ratio >= 0.75:
                score += int(260 * overlap_ratio)
            elif overlap_ratio >= 0.5 and ratio >= 0.55:
                score += int(180 * overlap_ratio)
        if ratio >= 0.72:
            score += int(180 * ratio)

    try:
        old_key = story_media_key(historical)
        new_key = story_media_key(current)
    except Exception:
        old_key = new_key = ""
    if old_key and old_key == new_key:
        score += 350

    overlap = _story_url_set(historical) & _story_url_set(current)
    if overlap:
        score += 1_000 + len(overlap) * 50

    if historical.get("category") and historical.get("category") == current.get("category"):
        score += 10
    return score


def _resolve_voice_text_match_score(source_text: str, current: dict) -> int:
    """Fallback match when an old story row/title is unavailable or changed."""
    text = " ".join((source_text or "").casefold().split())
    if not text:
        return 0
    title = str(current.get("canonical_title") or "")
    tokens = _resolve_title_tokens(title)
    if not tokens:
        return 0
    hits = sum(1 for token in tokens[:8] if token in text)
    # Require at least one distinctive proper/title term. Two or more is strong.
    if hits >= 3:
        return 420 + hits * 20
    if hits == 2:
        return 360
    if hits == 1 and len(tokens) == 1 and len(tokens[0]) >= 5:
        return 355

    # Article titles sometimes preserve a cleaner movie/show name than the
    # clustered canonical title, so let them provide the same safe fallback.
    best = 0
    for article in current.get("articles") or []:
        article_tokens = _resolve_title_tokens(str(article.get("title") or ""))
        if not article_tokens:
            continue
        article_hits = sum(1 for token in article_tokens[:8] if token in text)
        if article_hits >= 3:
            best = max(best, 400 + article_hits * 20)
        elif article_hits == 2:
            best = max(best, 350)
    return best


def _reconcile_voice_story_rows(
    voice_rows: list[dict],
    current_stories: list[dict],
    historical_stories: list[dict],
) -> tuple[list[dict], dict]:
    """Map stale narration story IDs to the current Included-story IDs.

    Research can be regenerated after voice has already been approved. Voice
    audio remains valid, but its STORY markers can then point at story rows from
    an older research run. Resolve needs the current story IDs because selected
    media is stored against those rows.
    """
    current_by_id = {
        str(story.get("id") or ""): story
        for story in current_stories
        if str(story.get("id") or "")
    }
    historical_by_id = {
        str(story.get("id") or ""): story
        for story in historical_stories
        if str(story.get("id") or "")
    }

    mapping: dict[str, str] = {}
    unresolved: list[str] = []
    referenced_ids = list(dict.fromkeys(
        str(row.get("story_id") or "")
        for row in voice_rows
        if str(row.get("story_id") or "")
    ))

    voice_text_by_story: dict[str, str] = {}
    for row in voice_rows:
        story_id = str(row.get("story_id") or "")
        if not story_id:
            continue
        voice_text_by_story[story_id] = (
            voice_text_by_story.get(story_id, "") + " " + str(row.get("source_text") or "")
        ).strip()

    match_details: dict[str, dict] = {}
    for story_id in referenced_ids:
        if story_id in current_by_id:
            mapping[story_id] = story_id
            match_details[story_id] = {
                "resolved_story_id": story_id,
                "method": "current-id",
                "score": 10_000,
            }
            continue
        historical = historical_by_id.get(story_id)
        narration_text = voice_text_by_story.get(story_id, "")

        scored = []
        for current_id, current in current_by_id.items():
            historical_score = _resolve_story_match_score(historical, current) if historical else 0
            voice_score = _resolve_voice_text_match_score(narration_text, current)
            scored.append((max(historical_score, voice_score), current_id, historical_score, voice_score))
        scored.sort(reverse=True)

        if not scored or scored[0][0] < 350:
            unresolved.append(story_id)
            match_details[story_id] = {
                "resolved_story_id": "",
                "method": "unresolved",
                "score": scored[0][0] if scored else 0,
            }
            continue

        top_score, top_id, historical_score, voice_score = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else -1
        # Never guess across indistinguishable duplicate current stories.
        if top_score > second_score:
            mapping[story_id] = top_id
            match_details[story_id] = {
                "resolved_story_id": top_id,
                "method": "historical-story" if historical_score >= voice_score else "narration-text",
                "score": top_score,
            }
        else:
            unresolved.append(story_id)
            match_details[story_id] = {
                "resolved_story_id": "",
                "method": "ambiguous",
                "score": top_score,
            }

    resolved_rows: list[dict] = []
    remapped_count = 0
    for row in voice_rows:
        item = dict(row)
        original = str(item.get("story_id") or "")
        resolved = mapping.get(original, original)
        if original and resolved != original:
            item["original_story_id"] = original
            item["story_id"] = resolved
            remapped_count += 1
        resolved_rows.append(item)

    unresolved_details = []
    for story_id in unresolved:
        rows = [row for row in voice_rows if str(row.get("story_id") or "") == story_id]
        historical = historical_by_id.get(story_id) or {}
        unresolved_details.append({
            "story_id": story_id,
            "historical_title": str(historical.get("canonical_title") or ""),
            "segment_indexes": [int(row.get("segment_index") or 0) for row in rows],
            "narration_excerpt": " ".join(
                str(row.get("source_text") or "") for row in rows
            )[:280],
            "match": match_details.get(story_id, {}),
        })

    return resolved_rows, {
        "story_id_map": mapping,
        "remapped_segment_count": remapped_count,
        "unresolved_story_ids": unresolved,
        "unresolved_details": unresolved_details,
        "match_details": match_details,
    }


def _load_historical_voice_stories(conn, project_id: str, voice_rows: list[dict]) -> list[dict]:
    ids = list(dict.fromkeys(
        str(row.get("story_id") or "")
        for row in voice_rows
        if str(row.get("story_id") or "")
    ))
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM stories WHERE project_id=? AND id IN ({placeholders})",
        [project_id, *ids],
    ).fetchall()
    output: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            article_ids = json.loads(item.get("article_ids_json") or "[]")
        except Exception:
            article_ids = []
        articles = []
        if article_ids:
            article_placeholders = ",".join("?" for _ in article_ids)
            articles = [
                dict(article) for article in conn.execute(
                    f"""SELECT title,url,source,published_at,snippet
                        FROM research_articles
                        WHERE id IN ({article_placeholders})""",
                    article_ids,
                ).fetchall()
            ]
        item["articles"] = articles
        output.append(item)
    return output


def _resolve_missing_story_details(
    missing_story_ids: list[str],
    resolved_voice_rows: list[dict],
    current_stories: list[dict],
    historical_stories: list[dict],
    reconciliation: dict,
) -> list[dict]:
    current_by_id = {str(item.get("id") or ""): item for item in current_stories}
    historical_by_id = {str(item.get("id") or ""): item for item in historical_stories}
    unresolved_by_id = {
        str(item.get("story_id") or ""): item
        for item in reconciliation.get("unresolved_details") or []
    }
    details = []
    for story_id in missing_story_ids:
        story = current_by_id.get(story_id) or historical_by_id.get(story_id) or {}
        rows = [
            row for row in resolved_voice_rows
            if str(row.get("story_id") or "") == story_id
        ]
        unresolved = unresolved_by_id.get(story_id) or {}
        details.append({
            "story_id": story_id,
            "title": str(story.get("canonical_title") or unresolved.get("historical_title") or ""),
            "segment_indexes": unresolved.get("segment_indexes") or [
                int(row.get("segment_index") or 0) for row in rows
            ],
            "narration_excerpt": str(
                unresolved.get("narration_excerpt")
                or " ".join(str(row.get("source_text") or "") for row in rows)[:280]
            ),
            "mapping_status": str((unresolved.get("match") or {}).get("method") or (
                "current-story-no-downloaded-media" if story_id in current_by_id else "unresolved-story-id"
            )),
        })
    return details


def _spoken_tokens(value: str) -> list[str]:
    return [
        token.casefold().replace("’", "'")
        for token in re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", value or "", flags=re.UNICODE)
    ]


def _alignment_phrase_start(alignment_value, phrase: str) -> float | None:
    try:
        alignment = alignment_value if isinstance(alignment_value, dict) else json.loads(alignment_value or "{}")
    except Exception:
        return None
    flattened: list[tuple[str, float]] = []
    for item in alignment.get("words") or []:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start"))
        except (TypeError, ValueError):
            continue
        for token in _spoken_tokens(str(item.get("text") or "")):
            flattened.append((token, start))
    target = _spoken_tokens(phrase)
    if not target or len(flattened) < len(target):
        return None
    # Search from the end because this repair is specifically for reserved
    # intro/outro text that leaked into an adjacent story segment.
    values = [token for token, _ in flattened]
    for offset in range(len(values) - len(target), -1, -1):
        if values[offset:offset + len(target)] == target:
            return flattened[offset][1]
    return None


def _apply_reserved_narration_tails(conn, voice_rows: list[dict]) -> list[dict]:
    rows = [dict(row) for row in voice_rows]
    narration_id = next((str(row.get("narration_id") or "") for row in rows if row.get("narration_id")), "")
    if not narration_id:
        return rows
    narration = conn.execute("SELECT content FROM narrations WHERE id=?", (narration_id,)).fetchone()
    if not narration:
        return rows

    # The current extractor deliberately returns intro/outro with blank
    # story_id. This also repairs projects created before that rule existed.
    reserved_segments = [
        segment for segment in extract_narration_segments(str(narration["content"] or ""))
        if not str(segment.get("story_id") or "") and str(segment.get("source_text") or "").strip()
    ]
    if not reserved_segments:
        return rows

    for row in rows:
        if not str(row.get("story_id") or ""):
            continue
        source_text = str(row.get("source_text") or "").strip()
        if not source_text:
            continue
        for reserved in reversed(reserved_segments):
            reserved_text = str(reserved.get("source_text") or "").strip()
            if not reserved_text or reserved_text == source_text or not source_text.endswith(reserved_text):
                continue
            start = _alignment_phrase_start(row.get("alignment_json"), reserved_text)
            duration = float(row.get("duration_seconds") or 0)
            if start is None or start <= 0 or start >= duration:
                continue
            row["reserved_tail_seconds"] = round(duration - start, 6)
            row["reserved_tail_kind"] = "outro"
            break
    return rows


def _resolve_prerequisites(voice_rows: list[dict], candidates: list[dict]) -> dict:
    pending_voice = [
        row for row in voice_rows
        if row.get("approval_status") != "approved"
        or row.get("audio_status") != "aligned"
        or not row.get("audio_path")
        or not row.get("duration_seconds")
    ]
    downloaded_by_story: dict[str, int] = {}
    selected_downloaded = []
    for row in candidates:
        if not row.get("selected"):
            continue
        if row.get("download_status") != "downloaded" or not row.get("stored_path"):
            continue
        selected_downloaded.append(row)
        story_id = str(row.get("story_id") or "")
        downloaded_by_story[story_id] = downloaded_by_story.get(story_id, 0) + 1

    narrated_story_ids = sorted({
        str(row.get("story_id") or "")
        for row in voice_rows
        if str(row.get("story_id") or "")
    })
    missing_story_media = [story_id for story_id in narrated_story_ids if not downloaded_by_story.get(story_id)]
    return {
        "voice_total": len(voice_rows),
        "voice_pending": len(pending_voice),
        "selected_downloaded": len(selected_downloaded),
        "narrated_story_count": len(narrated_story_ids),
        "stories_missing_downloaded_media": missing_story_media,
        "ready": bool(voice_rows) and not pending_voice and bool(selected_downloaded) and not missing_story_media,
    }


def project_or_404(conn, project_id: str) -> dict:
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def latest_run_id(conn, project_id: str) -> str | None:
    row = conn.execute("SELECT id FROM research_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
    return row["id"] if row else None


def project_payload(conn, project_id: str) -> dict:
    project = project_or_404(conn, project_id)
    run_id = latest_run_id(conn, project_id)
    counts = {"articles": 0, "stories": 0, "included": 0, "narrations": 0, "voice_segments": 0, "voice_generated": 0, "voice_aligned": 0, "voice_seconds": 0.0, "media_plans": 0, "media_candidates": 0, "media_selected": 0, "media_downloaded": 0}
    if run_id:
        counts["articles"] = conn.execute("SELECT COUNT(*) c FROM research_articles WHERE run_id=?", (run_id,)).fetchone()["c"]
        counts["stories"] = conn.execute("SELECT COUNT(*) c FROM stories WHERE run_id=?", (run_id,)).fetchone()["c"]
        counts["included"] = conn.execute("SELECT COUNT(*) c FROM stories WHERE run_id=? AND decision='include'", (run_id,)).fetchone()["c"]
    counts["narrations"] = conn.execute("SELECT COUNT(*) c FROM narrations WHERE project_id=?", (project_id,)).fetchone()["c"]
    counts["voice_segments"] = conn.execute("SELECT COUNT(*) c FROM voice_segments WHERE project_id=?", (project_id,)).fetchone()["c"]
    counts["voice_generated"] = conn.execute("SELECT COUNT(*) c FROM voice_segments WHERE project_id=? AND audio_status IN ('generated','aligned')", (project_id,)).fetchone()["c"]
    counts["voice_aligned"] = conn.execute("SELECT COUNT(*) c FROM voice_segments WHERE project_id=? AND audio_status='aligned' AND approval_status='approved'", (project_id,)).fetchone()["c"]
    counts["voice_seconds"] = round(float(conn.execute("SELECT COALESCE(SUM(duration_seconds),0) s FROM voice_segments WHERE project_id=?", (project_id,)).fetchone()["s"] or 0), 3)
    counts["media_plans"] = conn.execute("SELECT COUNT(*) c FROM media_plans WHERE project_id=?", (project_id,)).fetchone()["c"]
    counts["media_candidates"] = conn.execute("SELECT COUNT(*) c FROM media_candidates WHERE project_id=?", (project_id,)).fetchone()["c"]
    counts["media_selected"] = conn.execute("SELECT COUNT(*) c FROM media_candidates WHERE project_id=? AND selected=1", (project_id,)).fetchone()["c"]
    counts["media_downloaded"] = conn.execute("SELECT COUNT(*) c FROM media_candidates WHERE project_id=? AND download_status='downloaded'", (project_id,)).fetchone()["c"]
    project["latest_run_id"] = run_id
    project["counts"] = counts
    project["pipeline"] = PIPELINE
    return project


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/meta")
def meta():
    return {
        "name": "YT News Studio",
        "version": APP_VERSION,
        "release_name": APP_RELEASE_NAME,
        "pipeline": PIPELINE,
        "cinema_weekly_sections": CINEMA_WEEKLY_SECTIONS,
        "port": 8787,
    }


@app.post("/api/system/pick-folder")
def pick_folder():
    try:
        selected = choose_folder("Choose where YT News Studio should save projects")
        return {"path": selected, "cancelled": selected is None}
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel: str = "cinema"
    content_type: str = "weekly_news"
    language: str = "Persian"
    target_minutes: int = Field(default=15, ge=1, le=180)
    media_chunk_minutes: float = Field(default=1.0, ge=0.25, le=10)
    date_start: str = ""
    date_end: str = ""
    geographic_focus: str = "Worldwide"
    editorial_focus: str = "Balanced"
    notes: str = ""
    parent_path: str = Field(min_length=1)


class ProjectUpdate(BaseModel):
    name: str | None = None
    language: str | None = None
    target_minutes: int | None = Field(default=None, ge=1, le=180)
    media_chunk_minutes: float | None = Field(default=None, ge=0.25, le=10)
    date_start: str | None = None
    date_end: str | None = None
    geographic_focus: str | None = None
    editorial_focus: str | None = None
    notes: str | None = None


@app.get("/api/projects")
def list_projects():
    with db() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()]


@app.post("/api/projects")
def create_project(body: ProjectCreate):
    if body.channel != "cinema" or body.content_type != "weekly_news":
        raise HTTPException(400, "The MVP currently supports Cinema → Weekly News only.")
    start, end = default_week()
    try:
        root = create_project_folder(Path(body.parent_path), body.name.strip())
    except Exception as exc:
        raise HTTPException(400, f"Could not create project folder: {exc}") from exc
    project_id = str(uuid.uuid4())
    stamp = now()
    with db() as conn:
        conn.execute(
            """INSERT INTO projects(
                id,name,channel,content_type,language,target_minutes,media_chunk_minutes,date_start,date_end,
                geographic_focus,editorial_focus,notes,root_path,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                project_id, body.name.strip(), body.channel, body.content_type, body.language,
                body.target_minutes, body.media_chunk_minutes, body.date_start or start, body.date_end or end,
                body.geographic_focus, body.editorial_focus, body.notes, str(root), stamp, stamp,
            ),
        )
        save_manifest(conn, project_id)
        return project_payload(conn, project_id)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    with db() as conn:
        return project_payload(conn, project_id)


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, body: ProjectUpdate):
    values = body.model_dump(exclude_none=True)
    if not values:
        with db() as conn:
            return project_payload(conn, project_id)
    allowed = {"name","language","target_minutes","media_chunk_minutes","date_start","date_end","geographic_focus","editorial_focus","notes"}
    values = {k:v for k,v in values.items() if k in allowed}
    with db() as conn:
        project_or_404(conn, project_id)
        sets = ",".join(f"{key}=?" for key in values) + ",updated_at=?"
        conn.execute(f"UPDATE projects SET {sets} WHERE id=?", (*values.values(), now(), project_id))
        save_manifest(conn, project_id)
        return project_payload(conn, project_id)


@app.post("/api/projects/{project_id}/open-folder")
def open_project_folder(project_id: str):
    with db() as conn:
        project = project_or_404(conn, project_id)
    reveal_in_file_manager(Path(project["root_path"]))
    return {"ok": True}


class ResearchBody(BaseModel):
    provider: str | None = None
    model: str | None = None
    ai_rank: bool = True


@app.post("/api/projects/{project_id}/research")
def run_research(project_id: str, body: ResearchBody):
    with db() as conn:
        project = project_or_404(conn, project_id)

    news_articles, news_diagnostics = fetch_google_news(project["date_start"], project["date_end"])
    social_articles, social_diagnostics = fetch_social_sources(project["date_start"], project["date_end"])
    diagnostics = news_diagnostics + social_diagnostics

    articles = []
    seen_urls: set[str] = set()
    for article in [*news_articles, *social_articles]:
        url = str(article.get("url") or "").strip()
        dedupe_key = url.casefold()
        if dedupe_key and dedupe_key in seen_urls:
            continue
        if dedupe_key:
            seen_urls.add(dedupe_key)
        articles.append(annotate_source_window(article, project["date_start"], project["date_end"]))

    if not articles:
        errors = "; ".join(x.get("error", "") for x in diagnostics if not x.get("ok"))
        raise HTTPException(502, f"Research returned no articles or public social posts. {errors}".strip())

    stories = cluster_articles(articles, project["date_start"], project["date_end"])
    provider = body.provider or masked_status().get("research_provider", "codex_local")
    model = body.model or masked_status().get("research_model", "default")
    ai_error = ""
    actual_provider, actual_model = provider, model
    context_articles: list[dict] = []
    context_diagnostics: list[dict] = []
    spice_error = ""
    if body.ai_rank:
        try:
            stories, actual_provider, actual_model = ai_rank_stories(stories, project, provider, model)
        except Exception as exc:
            ai_error = str(exc)

    run_id = str(uuid.uuid4())
    stamp = now()
    query_config = {
        "diagnostics": diagnostics,
        "ai_rank_requested": body.ai_rank,
        "ai_rank_error": ai_error,
        "news_article_count": len(news_articles),
        "social_article_count": len(social_articles),
        "story_context_article_count": len(context_articles),
        "story_context_error": spice_error,
    }
    with db() as conn:
        project = project_or_404(conn, project_id)
        conn.execute(
            "INSERT INTO research_runs(id,project_id,provider,model,query_config_json,article_count,story_count,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, project_id, actual_provider, actual_model, json.dumps(query_config), len(articles), len(stories), stamp),
        )
        for article in articles:
            conn.execute(
                """INSERT INTO research_articles(id,project_id,run_id,title,url,source,published_at,category,snippet,query_key,raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    article["id"], project_id, run_id, article["title"], article["url"], article["source"],
                    article["published_at"], article["category"], article["snippet"], article["query_key"],
                    json.dumps(article.get("raw") or {}),
                ),
            )
        for story in stories:
            conn.execute(
                """INSERT INTO stories(
                    id,project_id,run_id,canonical_title,summary,category,attention,importance,freshness,
                    confidence,visual_potential,uniqueness,rationale,score,decision,section_fit,article_ids_json,source_count,
                    source_platforms_json,source_kinds_json,reddit_only,primary_social_count,
                    news_hook,news_hook_date,verification_status,verification_notes,temporal_gate,verification_gate,
                    in_window_source_count,background_source_count,undated_source_count,independent_source_count,
                    current_non_reddit_source_count,current_primary_social_count,familiarity_needed,familiarity_anchor,
                    search_subject,spice_json,spice_source_ids_json,context_searched_at,context_search_count,context_search_error,
                    created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    story["id"], project_id, run_id, story["canonical_title"], story["summary"], story["category"],
                    story["attention"], story["importance"], story["freshness"], story["confidence"],
                    story["visual_potential"], story["uniqueness"], story["rationale"], story["score"], story["decision"],
                    story.get("section_fit") or "medium", json.dumps(story["article_ids"]), story["source_count"],
                    json.dumps(story.get("source_platforms") or []), json.dumps(story.get("source_kinds") or []),
                    1 if story.get("reddit_only") else 0, int(story.get("primary_social_count") or 0),
                    story.get("news_hook") or "", story.get("news_hook_date") or "",
                    story.get("verification_status") or "needs_verification", story.get("verification_notes") or "",
                    story.get("temporal_gate") or "warning", story.get("verification_gate") or "fail",
                    int(story.get("in_window_source_count") or 0), int(story.get("background_source_count") or 0),
                    int(story.get("undated_source_count") or 0), int(story.get("independent_source_count") or 0),
                    int(story.get("current_non_reddit_source_count") or 0),
                    int(story.get("current_primary_social_count") or 0),
                    1 if story.get("familiarity_needed") else 0,
                    story.get("familiarity_anchor") or "",
                    story.get("search_subject") or "",
                    json.dumps(story.get("spice_angles") or [], ensure_ascii=False),
                    json.dumps(story.get("spice_source_ids") or []),
                    "", 0, "",
                    stamp, stamp,
                ),
            )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        root = Path(project["root_path"])
        raw_file = root / "research" / "raw" / f"{run_id}.json"
        raw_file.write_text(json.dumps({"articles": articles, "diagnostics": diagnostics}, indent=2, ensure_ascii=False), encoding="utf-8")
        story_file = root / "research" / "stories" / f"{run_id}.json"
        story_file.write_text(json.dumps(stories, indent=2, ensure_ascii=False), encoding="utf-8")
        save_manifest(conn, project_id)

    return {
        "run_id": run_id,
        "article_count": len(articles),
        "story_count": len(stories),
        "current_story_count": sum(1 for story in stories if story.get("freshness") in {"current", "followup"}),
        "verified_story_count": sum(1 for story in stories if story.get("verification_gate") == "pass"),
        "stale_story_count": sum(1 for story in stories if story.get("freshness") == "stale"),
        "spice_story_count": 0,
        "spice_angle_count": 0,
        "ai_rank_error": ai_error,
        "spice_error": spice_error,
        "provider": actual_provider,
        "model": actual_model,
    }


@app.get("/api/projects/{project_id}/stories")
def get_stories(project_id: str):
    with db() as conn:
        project_or_404(conn, project_id)
        run_id = latest_run_id(conn, project_id)
        if not run_id:
            return []
        rows = conn.execute("SELECT * FROM stories WHERE run_id=? ORDER BY score DESC, source_count DESC", (run_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            ids = json.loads(item.pop("article_ids_json") or "[]")
            item["source_platforms"] = json.loads(item.pop("source_platforms_json") or "[]")
            item["source_kinds"] = json.loads(item.pop("source_kinds_json") or "[]")
            item["reddit_only"] = bool(item.get("reddit_only"))
            item["familiarity_needed"] = bool(item.get("familiarity_needed"))
            item["spice_angles"] = json.loads(item.pop("spice_json") or "[]")
            spice_ids = json.loads(item.pop("spice_source_ids_json") or "[]")
            item["spice_sources"] = []
            if spice_ids:
                spice_placeholders = ",".join("?" for _ in spice_ids)
                spice_rows = conn.execute(
                    f"""SELECT id,title,url,source,published_at,snippet,raw_json
                        FROM research_articles WHERE id IN ({spice_placeholders})""", spice_ids
                ).fetchall()
                for spice_row in spice_rows:
                    spice_source = dict(spice_row)
                    try:
                        raw = json.loads(spice_source.pop("raw_json") or "{}")
                    except Exception:
                        raw = {}
                    spice_source["source_kind"] = str(raw.get("source_kind") or "story_context")
                    spice_source["platform"] = str(raw.get("platform") or "")
                    spice_source["context_kind"] = str(raw.get("context_kind") or "")
                    spice_source["temporal_role"] = str(raw.get("temporal_role") or "")
                    item["spice_sources"].append(spice_source)
            if ids:
                placeholders = ",".join("?" for _ in ids)
                article_rows = conn.execute(
                    f"""SELECT id,title,url,source,published_at,category,snippet,query_key,raw_json
                        FROM research_articles WHERE id IN ({placeholders}) ORDER BY published_at DESC""", ids
                ).fetchall()
                article_items = []
                for article_row in article_rows:
                    article = dict(article_row)
                    try:
                        raw = json.loads(article.pop("raw_json") or "{}")
                    except Exception:
                        raw = {}
                    article["source_kind"] = str(raw.get("source_kind") or "news")
                    article["platform"] = str(raw.get("platform") or "")
                    article["trust_role"] = str(raw.get("trust_role") or "")
                    article["temporal_role"] = str(raw.get("temporal_role") or "")
                    article_items.append(article)
                item["articles"] = article_items
            else:
                item["articles"] = []
            result.append(item)
        return result


class DecisionBody(BaseModel):
    decision: str


@app.patch("/api/projects/{project_id}/stories/{story_id}")
def update_story_decision(project_id: str, story_id: str, body: DecisionBody):
    decision = body.decision.strip().lower()
    if decision not in {"include", "maybe", "skip"}:
        raise HTTPException(400, "Decision must be include, maybe, or skip.")
    with db() as conn:
        project = project_or_404(conn, project_id)
        row = conn.execute("SELECT * FROM stories WHERE id=? AND project_id=?", (story_id, project_id)).fetchone()
        if not row:
            raise HTTPException(404, "Story not found")
        if decision == "include":
            freshness = str(row["freshness"] or "")
            temporal_gate = str(row["temporal_gate"] or "")
            verification_gate = str(row["verification_gate"] or "")
            news_hook = str(row["news_hook"] or "").strip()
            if (
                freshness not in {"current", "followup"}
                or temporal_gate != "pass"
                or verification_gate != "pass"
                or not news_hook
                or int(row["in_window_source_count"] or 0) <= 0
            ):
                raise HTTPException(
                    400,
                    "This story cannot be Included yet. It needs a verified current-window news hook. "
                    "Check Freshness/Verification in Step 2 or rerun Format Research.",
                )
        conn.execute("UPDATE stories SET decision=?,updated_at=? WHERE id=?", (decision, now(), story_id))
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        save_manifest(conn, project_id)
    return {"ok": True, "decision": decision}


class StoryContextSearchBody(BaseModel):
    provider: str | None = None
    model: str | None = None


@app.post("/api/projects/{project_id}/stories/{story_id}/context-search")
def search_story_context(project_id: str, story_id: str, body: StoryContextSearchBody):
    settings = masked_status()
    provider = body.provider or settings.get("research_provider", "codex_local")
    model = body.model or settings.get("research_model", "default")

    with db() as conn:
        project = project_or_404(conn, project_id)
        draft = conn.execute(
            "SELECT id FROM narrations WHERE project_id=? ORDER BY version_number DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if not draft:
            raise HTTPException(400, "Generate the first narration draft before running story enrichment.")
        run_id = latest_run_id(conn, project_id)
        if not run_id:
            raise HTTPException(400, "Run Format Research first.")
        row = conn.execute(
            "SELECT * FROM stories WHERE id=? AND project_id=? AND run_id=?",
            (story_id, project_id, run_id),
        ).fetchone()
        if not row or str(row["decision"] or "") != "include":
            raise HTTPException(404, "Included story not found in the current research run.")
        stories = selected_story_packet(conn, project_id)
        story = next((item for item in stories if item["id"] == story_id), None)
        if not story:
            raise HTTPException(400, "This story no longer passes the current selection/verification gates.")

        previous_ids = json.loads(row["spice_source_ids_json"] or "[]")
        previous_sources: list[dict] = []
        if previous_ids:
            placeholders = ",".join("?" for _ in previous_ids)
            for source_row in conn.execute(
                f"""SELECT id,title,url,source,published_at,category,snippet,query_key,raw_json
                    FROM research_articles WHERE id IN ({placeholders})""",
                previous_ids,
            ).fetchall():
                source = dict(source_row)
                try:
                    source["raw"] = json.loads(source.pop("raw_json") or "{}")
                except Exception:
                    source["raw"] = {}
                previous_sources.append(source)

    stamp = now()
    search_error = ""
    new_sources: list[dict] = []
    diagnostics: list[dict] = []
    actual_provider, actual_model = provider, model
    try:
        new_sources, sources_by_story, diagnostics = fetch_story_spice_sources(
            [story],
            project["date_start"],
            project["date_end"],
            max_stories=1,
            per_query_limit=6,
        )

        combined_by_url: dict[str, dict] = {}
        for source in [*previous_sources, *new_sources]:
            url = str(source.get("url") or "").strip()
            if not url:
                continue
            combined_by_url[url.casefold()] = source
        combined_sources = list(combined_by_url.values())

        enriched, actual_provider, actual_model = ai_enrich_story_spice(
            [story],
            {story_id: combined_sources},
            project,
            provider,
            model,
        )
        story = enriched[0]
    except Exception as exc:
        search_error = str(exc)
        combined_sources = previous_sources
        story["spice_angles"] = json.loads(row["spice_json"] or "[]")

    with db() as conn:
        project = project_or_404(conn, project_id)
        # Persist only newly discovered source rows. Existing rows keep their IDs.
        existing_urls = {
            str(source.get("url") or "").strip().casefold(): str(source.get("id") or "")
            for source in previous_sources
            if str(source.get("url") or "").strip()
        }
        persisted_ids = [source_id for source_id in existing_urls.values() if source_id]
        for source in new_sources:
            url = str(source.get("url") or "").strip()
            key = url.casefold()
            if not url or key in existing_urls:
                continue
            source_id = str(source.get("id") or uuid.uuid4())
            source["id"] = source_id
            conn.execute(
                """INSERT INTO research_articles(
                    id,project_id,run_id,title,url,source,published_at,category,snippet,query_key,raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    source_id, project_id, run_id, source.get("title") or "", url,
                    source.get("source") or "", source.get("published_at") or "",
                    source.get("category") or story.get("category") or "",
                    source.get("snippet") or "", source.get("query_key") or "",
                    json.dumps(source.get("raw") or {}, ensure_ascii=False),
                ),
            )
            existing_urls[key] = source_id
            persisted_ids.append(source_id)

        # ai_enrich_story_spice works with the search packet IDs. Remap by URL so
        # repeated searches accumulate one persistent source set.
        all_source_ids = list(dict.fromkeys(persisted_ids))
        count = int(row["context_search_count"] or 0) + 1
        conn.execute(
            """UPDATE stories
               SET spice_json=?,spice_source_ids_json=?,context_searched_at=?,
                   context_search_count=?,context_search_error=?,updated_at=?
               WHERE id=? AND project_id=?""",
            (
                json.dumps(story.get("spice_angles") or [], ensure_ascii=False),
                json.dumps(all_source_ids),
                stamp, count, search_error, stamp, story_id, project_id,
            ),
        )
        root = Path(project["root_path"]) / "research" / "stories"
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{story_id}_context_{count:02d}.json").write_text(
            json.dumps({
                "story_id": story_id,
                "searched_at": stamp,
                "provider": actual_provider,
                "model": actual_model,
                "angles": story.get("spice_angles") or [],
                "sources": combined_sources,
                "diagnostics": diagnostics,
                "error": search_error,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        save_manifest(conn, project_id)

    if search_error and not previous_sources:
        raise HTTPException(400, search_error)
    return {
        "story_id": story_id,
        "searched_at": stamp,
        "search_count": int(row["context_search_count"] or 0) + 1,
        "angle_count": len(story.get("spice_angles") or []),
        "safe_angle_count": sum(1 for angle in story.get("spice_angles") or [] if angle.get("safe_to_narrate")),
        "source_count": len(combined_sources),
        "angles": story.get("spice_angles") or [],
        "error": search_error,
        "provider": actual_provider,
        "model": actual_model,
    }


class GenerateBody(BaseModel):
    provider: str | None = None
    model: str | None = None
    instructions: str = ""


def selected_story_packet(conn, project_id: str) -> list[dict]:
    run_id = latest_run_id(conn, project_id)
    if not run_id:
        return []
    stories = []
    for row in conn.execute("SELECT * FROM stories WHERE run_id=? AND decision='include'", (run_id,)).fetchall():
        item = dict(row)
        if (
            str(item.get("freshness") or "") not in {"current", "followup"}
            or str(item.get("temporal_gate") or "") != "pass"
            or str(item.get("verification_gate") or "") != "pass"
            or not str(item.get("news_hook") or "").strip()
            or int(item.get("in_window_source_count") or 0) <= 0
        ):
            continue
        article_ids = json.loads(item.pop("article_ids_json") or "[]")
        item["source_platforms"] = json.loads(item.pop("source_platforms_json") or "[]")
        item["source_kinds"] = json.loads(item.pop("source_kinds_json") or "[]")
        item["reddit_only"] = bool(item.get("reddit_only"))
        item["familiarity_needed"] = bool(item.get("familiarity_needed"))
        item["spice_angles"] = json.loads(item.pop("spice_json") or "[]")
        spice_ids = json.loads(item.pop("spice_source_ids_json") or "[]")
        item["spice_sources"] = []
        if spice_ids:
            spice_placeholders = ",".join("?" for _ in spice_ids)
            spice_rows = conn.execute(
                f"""SELECT title,url,source,published_at,snippet,raw_json
                    FROM research_articles WHERE id IN ({spice_placeholders})""", spice_ids
            ).fetchall()
            for spice_row in spice_rows:
                spice_source = dict(spice_row)
                try:
                    raw = json.loads(spice_source.pop("raw_json") or "{}")
                except Exception:
                    raw = {}
                spice_source["source_kind"] = str(raw.get("source_kind") or "story_context")
                spice_source["platform"] = str(raw.get("platform") or "")
                spice_source["context_kind"] = str(raw.get("context_kind") or "")
                spice_source["temporal_role"] = str(raw.get("temporal_role") or "")
                item["spice_sources"].append(spice_source)
        articles = []
        if article_ids:
            placeholders = ",".join("?" for _ in article_ids)
            article_rows = conn.execute(
                f"""SELECT title,url,source,published_at,snippet,category,query_key,raw_json
                    FROM research_articles WHERE id IN ({placeholders})""", article_ids
            ).fetchall()
            for article_row in article_rows:
                article = dict(article_row)
                try:
                    raw = json.loads(article.pop("raw_json") or "{}")
                except Exception:
                    raw = {}
                article["source_kind"] = str(raw.get("source_kind") or "news")
                article["platform"] = str(raw.get("platform") or "")
                article["trust_role"] = str(raw.get("trust_role") or "")
                article["temporal_role"] = str(raw.get("temporal_role") or "")
                articles.append(article)
        item["articles"] = articles
        stories.append(item)
    stories.sort(key=lambda item: (
        SECTION_ORDER.get(str(item.get("category") or ""), 999),
        -float(item.get("score") or 0),
    ))
    return stories


def _style_transcripts(conn, channel: str = "cinema", content_type: str = "weekly_news") -> list[dict]:
    return [dict(row) for row in conn.execute(
        """SELECT * FROM style_transcripts
           WHERE channel=? AND content_type=?
           ORDER BY enabled DESC, created_at""",
        (channel, content_type),
    ).fetchall()]


def _parse_json_object_text(value: str) -> dict:
    raw = str(value or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
    first = raw.find("{")
    last = raw.rfind("}")
    if first < 0 or last < first:
        raise ValueError("AI response did not contain a JSON object.")
    parsed = json.loads(raw[first:last + 1])
    if not isinstance(parsed, dict):
        raise ValueError("AI response JSON was not an object.")
    return parsed


def _style_profile_status(conn, channel: str, content_type: str, style_rows: list[dict]) -> dict:
    enabled = [row for row in style_rows if int(row.get("enabled") or 0) and str(row.get("content") or "").strip()]
    current_hash = style_corpus_hash(enabled)
    row = conn.execute(
        "SELECT * FROM style_profiles WHERE channel=? AND content_type=?",
        (channel, content_type),
    ).fetchone()
    item = dict(row) if row else {
        "id": "",
        "channel": channel,
        "content_type": content_type,
        "corpus_hash": "",
        "profile_text": "",
        "provider": "",
        "model": "",
        "transcript_count": 0,
        "created_at": "",
        "updated_at": "",
    }
    item["current_corpus_hash"] = current_hash
    item["enabled_transcript_count"] = len(enabled)
    item["current"] = bool(item.get("profile_text")) and item.get("corpus_hash") == current_hash
    item["stale"] = bool(item.get("profile_text")) and not item["current"]
    return item


def _ensure_style_profile(
    channel: str,
    content_type: str,
    style_rows: list[dict],
    provider: str,
    model: str,
    *,
    force: bool = False,
) -> dict:
    enabled = [row for row in style_rows if int(row.get("enabled") or 0) and str(row.get("content") or "").strip()]
    if not enabled:
        return {
            "id": "",
            "channel": channel,
            "content_type": content_type,
            "corpus_hash": "",
            "profile_text": "No imported style transcripts are enabled. Use the built-in spoken-writing rules only.",
            "provider": "builtin",
            "model": "builtin",
            "transcript_count": 0,
            "created_at": "",
            "updated_at": "",
            "current": True,
            "stale": False,
            "enabled_transcript_count": 0,
        }

    with db() as conn:
        status = _style_profile_status(conn, channel, content_type, enabled)
    if status["current"] and not force:
        return status

    style_packet = build_style_packet(enabled, max_chars=120000)
    try:
        profile_text, actual_provider, actual_model = generate_text(
            provider,
            model,
            STYLE_PROFILE_SYSTEM,
            style_packet,
        )
    except Exception as exc:
        raise HTTPException(400, f"Could not build style blueprint: {exc}") from exc

    stamp = now()
    profile_id = status.get("id") or str(uuid.uuid4())
    corpus_hash = style_corpus_hash(enabled)
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM style_profiles WHERE channel=? AND content_type=?",
            (channel, content_type),
        ).fetchone()
        if existing:
            profile_id = existing["id"]
            conn.execute(
                """UPDATE style_profiles
                   SET corpus_hash=?,profile_text=?,provider=?,model=?,transcript_count=?,updated_at=?
                   WHERE channel=? AND content_type=?""",
                (
                    corpus_hash, profile_text, actual_provider, actual_model, len(enabled), stamp,
                    channel, content_type,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO style_profiles(
                    id,channel,content_type,corpus_hash,profile_text,provider,model,
                    transcript_count,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    profile_id, channel, content_type, corpus_hash, profile_text,
                    actual_provider, actual_model, len(enabled), stamp, stamp,
                ),
            )
        status = _style_profile_status(conn, channel, content_type, enabled)
    return status


def _sectioned_story_packet(stories: list[dict]) -> list[dict]:
    result = []
    for section in CINEMA_WEEKLY_FORMAT:
        items = [story for story in stories if story.get("category") == section["key"]]
        result.append({
            "section": section["key"],
            "label": section["label"],
            "writer_role": section.get("writer_role") or "",
            "mission": section.get("mission") or "",
            "verification_policy": section.get("verification_policy") or {},
            "freshness_policy": section.get("freshness_policy") or {},
            "stories": items,
        })
    return result


def _narration_version(conn, project_id: str) -> int:
    return int(conn.execute(
        "SELECT COALESCE(MAX(version_number),0)+1 v FROM narrations WHERE project_id=?",
        (project_id,),
    ).fetchone()["v"])


def _write_narration_file(project: dict, version: int, content: str) -> None:
    root = Path(project["root_path"])
    folder = root / "narration"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"v{version:02d}.md").write_text(content, encoding="utf-8")


@app.post("/api/projects/{project_id}/narration")
def generate_narration(project_id: str, body: GenerateBody):
    settings = masked_status()
    provider = body.provider or settings.get("writer_provider", "codex_local")
    model = body.model or settings.get("writer_model", "default")
    with db() as conn:
        project = project_or_404(conn, project_id)
        stories = selected_story_packet(conn, project_id)
        style_rows = _style_transcripts(conn, project.get("channel") or "cinema", project.get("content_type") or "weekly_news")
    if not stories:
        raise HTTPException(400, "Include at least one story before generating narration.")

    # Fresh Draft is intentionally the baseline pass. Post-draft related-context
    # searches are applied only by the dedicated Enrichment Rewrite step.
    baseline_stories = []
    for source_story in stories:
        item = dict(source_story)
        item["spice_angles"] = []
        item["spice_sources"] = []
        baseline_stories.append(item)

    packet = {
        "project": {
            "name": project.get("name"),
            "channel": project.get("channel"),
            "content_type": project.get("content_type"),
            "language": project.get("language"),
            "target_minutes": project.get("target_minutes"),
            "date_start": project.get("date_start"),
            "date_end": project.get("date_end"),
            "geographic_focus": project.get("geographic_focus"),
            "editorial_focus": project.get("editorial_focus"),
        },
        "format_blueprint": format_packet(),
        "approved_sections": _sectioned_story_packet(baseline_stories),
        "additional_instructions": body.instructions,
    }
    channel = project.get("channel") or "cinema"
    content_type = project.get("content_type") or "weekly_news"
    style_profile = _ensure_style_profile(
        channel,
        content_type,
        style_rows,
        provider,
        model,
    )

    content_plan_error = ""
    try:
        plan_text, _, _ = generate_text(
            provider,
            model,
            CONTENT_PLAN_SYSTEM,
            json.dumps(packet, ensure_ascii=False),
        )
        content_plan = _parse_json_object_text(plan_text)
    except Exception as exc:
        # Do not silently replace the facts with made-up planning. The writer
        # still gets the complete authoritative packet and an explicit planner
        # error so it can keep thin stories short.
        content_plan_error = str(exc)
        content_plan = {
            "intro_hooks": [],
            "sections": [],
            "planner_error": content_plan_error,
        }

    user = "\n".join([
        "<current_week_authoritative_packet>",
        json.dumps(packet, ensure_ascii=False),
        "</current_week_authoritative_packet>",
        "",
        "<content_plan>",
        json.dumps(content_plan, ensure_ascii=False),
        "</content_plan>",
        "",
        "<style_blueprint>",
        style_profile.get("profile_text") or "",
        "</style_blueprint>",
        "",
        build_style_packet(style_rows, max_chars=80000),
    ])
    try:
        text, actual_provider, actual_model = generate_text(provider, model, WRITER_SYSTEM, user)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

    narration_id = str(uuid.uuid4())
    stamp = now()
    with db() as conn:
        project = project_or_404(conn, project_id)
        version = _narration_version(conn, project_id)
        conn.execute(
            """INSERT INTO narrations(
                id,project_id,version_number,content,provider,model,story_ids_json,
                created_at,approved,parent_narration_id,revision_review_id
            ) VALUES (?,?,?,?,?,?,?,?,0,'','')""",
            (
                narration_id, project_id, version, text, actual_provider, actual_model,
                json.dumps([story["id"] for story in stories]), stamp,
            ),
        )
        _write_narration_file(project, version, text)
        plan_folder = Path(project["root_path"]) / "narration" / "plans"
        plan_folder.mkdir(parents=True, exist_ok=True)
        (plan_folder / f"v{version:02d}_content_plan.json").write_text(
            json.dumps(content_plan, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        save_manifest(conn, project_id)
    return {
        "id": narration_id,
        "version_number": version,
        "content": text,
        "provider": actual_provider,
        "model": actual_model,
        "style_transcript_count": sum(1 for row in style_rows if int(row.get("enabled") or 0)),
        "style_profile_current": bool(style_profile.get("current")),
        "style_profile_transcript_count": int(style_profile.get("enabled_transcript_count") or 0),
        "content_plan_error": content_plan_error,
    }


@app.get("/api/projects/{project_id}/narrations")
def list_narrations(project_id: str):
    with db() as conn:
        project_or_404(conn, project_id)
        return [dict(row) for row in conn.execute("SELECT * FROM narrations WHERE project_id=? ORDER BY version_number DESC", (project_id,)).fetchall()]


class StyleTranscriptBody(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1)
    channel: str = "cinema"
    content_type: str = "weekly_news"
    enabled: bool = True


class StyleTranscriptToggleBody(BaseModel):
    enabled: bool


class StyleProfileRebuildBody(BaseModel):
    provider: str | None = None
    model: str | None = None


class NarrationEnrichmentRewriteBody(BaseModel):
    provider: str | None = None
    model: str | None = None


class NarrationReviewBody(BaseModel):
    provider: str | None = None
    model: str | None = None


class NarrationRevisionBody(BaseModel):
    review_id: str = ""
    provider: str | None = None
    model: str | None = None


@app.post("/api/projects/{project_id}/style-profile/rebuild")
def rebuild_style_profile(project_id: str, body: StyleProfileRebuildBody):
    settings = masked_status()
    provider = body.provider or settings.get("writer_provider", "codex_local")
    model = body.model or settings.get("writer_model", "default")
    with db() as conn:
        project = project_or_404(conn, project_id)
        channel = project.get("channel") or "cinema"
        content_type = project.get("content_type") or "weekly_news"
        styles = _style_transcripts(conn, channel, content_type)
    profile = _ensure_style_profile(channel, content_type, styles, provider, model, force=True)
    return {
        "id": profile.get("id") or "",
        "current": bool(profile.get("current")),
        "transcript_count": int(profile.get("enabled_transcript_count") or 0),
        "profile_text": profile.get("profile_text") or "",
        "provider": profile.get("provider") or "",
        "model": profile.get("model") or "",
        "updated_at": profile.get("updated_at") or "",
    }


@app.get("/api/style-transcripts")
def list_style_transcripts(channel: str = "cinema", content_type: str = "weekly_news"):
    with db() as conn:
        return _style_transcripts(conn, channel, content_type)


@app.post("/api/style-transcripts")
def add_style_transcript(body: StyleTranscriptBody):
    transcript_id = str(uuid.uuid4())
    stamp = now()
    with db() as conn:
        conn.execute(
            """INSERT INTO style_transcripts(
                id,channel,content_type,name,content,char_count,enabled,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                transcript_id, body.channel.strip() or "cinema",
                body.content_type.strip() or "weekly_news", body.name.strip(),
                body.content, len(body.content), 1 if body.enabled else 0, stamp, stamp,
            ),
        )
        row = conn.execute("SELECT * FROM style_transcripts WHERE id=?", (transcript_id,)).fetchone()
        return dict(row)


@app.patch("/api/style-transcripts/{transcript_id}")
def toggle_style_transcript(transcript_id: str, body: StyleTranscriptToggleBody):
    with db() as conn:
        row = conn.execute("SELECT 1 FROM style_transcripts WHERE id=?", (transcript_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Style transcript not found")
        conn.execute(
            "UPDATE style_transcripts SET enabled=?,updated_at=? WHERE id=?",
            (1 if body.enabled else 0, now(), transcript_id),
        )
    return {"ok": True, "enabled": body.enabled}


@app.delete("/api/style-transcripts/{transcript_id}")
def delete_style_transcript(transcript_id: str):
    with db() as conn:
        conn.execute("DELETE FROM style_transcripts WHERE id=?", (transcript_id,))
    return {"ok": True}


@app.get("/api/projects/{project_id}/narration-workspace")
def narration_workspace(project_id: str):
    with db() as conn:
        project = project_or_404(conn, project_id)
        stories = selected_story_packet(conn, project_id)
        narrations = [dict(row) for row in conn.execute(
            "SELECT * FROM narrations WHERE project_id=? ORDER BY version_number DESC",
            (project_id,),
        ).fetchall()]
        reviews = [dict(row) for row in conn.execute(
            "SELECT * FROM narration_reviews WHERE project_id=? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()]
        channel = project.get("channel") or "cinema"
        content_type = project.get("content_type") or "weekly_news"
        styles = _style_transcripts(conn, channel, content_type)
        style_profile = _style_profile_status(conn, channel, content_type, styles)
    return {
        "format_blueprint": format_packet(),
        "sections": _sectioned_story_packet(stories),
        "narrations": narrations,
        "reviews": reviews,
        "style_transcripts": styles,
        "style_profile": style_profile,
    }


@app.post("/api/projects/{project_id}/narrations/{narration_id}/enrich-rewrite")
def rewrite_narration_with_enrichment(project_id: str, narration_id: str, body: NarrationEnrichmentRewriteBody):
    settings = masked_status()
    provider = body.provider or settings.get("writer_provider", "codex_local")
    model = body.model or settings.get("writer_model", "default")
    with db() as conn:
        project = project_or_404(conn, project_id)
        draft = conn.execute(
            "SELECT * FROM narrations WHERE id=? AND project_id=?",
            (narration_id, project_id),
        ).fetchone()
        if not draft:
            raise HTTPException(404, "Narration draft not found")
        stories = selected_story_packet(conn, project_id)
        searched = [story for story in stories if str(story.get("context_searched_at") or "")]
        if not searched:
            raise HTTPException(400, "Search at least one story for related context before rewriting.")
        styles = _style_transcripts(
            conn,
            project.get("channel") or "cinema",
            project.get("content_type") or "weekly_news",
        )

    user = "\n".join([
        "<current_week_authoritative_packet>",
        json.dumps({
            "project": {
                "language": project.get("language"),
                "date_start": project.get("date_start"),
                "date_end": project.get("date_end"),
            },
            "format_blueprint": format_packet(),
            "approved_sections": _sectioned_story_packet(stories),
        }, ensure_ascii=False),
        "</current_week_authoritative_packet>",
        "",
        build_style_packet(styles),
        "",
        "<existing_first_draft>",
        draft["content"],
        "</existing_first_draft>",
    ])
    try:
        rewritten_text, actual_provider, actual_model = generate_text(
            provider,
            model,
            ENRICHMENT_REWRITE_SYSTEM,
            user,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

    new_id = str(uuid.uuid4())
    stamp = now()
    with db() as conn:
        project = project_or_404(conn, project_id)
        version = _narration_version(conn, project_id)
        conn.execute(
            """INSERT INTO narrations(
                id,project_id,version_number,content,provider,model,story_ids_json,
                created_at,approved,parent_narration_id,revision_review_id
            ) VALUES (?,?,?,?,?,?,?,?,0,?,'')""",
            (
                new_id, project_id, version, rewritten_text, actual_provider, actual_model,
                draft["story_ids_json"], stamp, narration_id,
            ),
        )
        _write_narration_file(project, version, rewritten_text)
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        save_manifest(conn, project_id)
    return {
        "id": new_id,
        "version_number": version,
        "content": rewritten_text,
        "provider": actual_provider,
        "model": actual_model,
        "parent_narration_id": narration_id,
        "searched_story_count": len(searched),
        "safe_angle_count": sum(
            1
            for story in searched
            for angle in story.get("spice_angles") or []
            if angle.get("safe_to_narrate")
        ),
    }


@app.post("/api/projects/{project_id}/narrations/{narration_id}/review")
def review_narration(project_id: str, narration_id: str, body: NarrationReviewBody):
    settings = masked_status()
    provider = body.provider or settings.get("reviewer_provider", "claude_local")
    model = body.model or settings.get("reviewer_model", "default")
    with db() as conn:
        project = project_or_404(conn, project_id)
        draft = conn.execute(
            "SELECT * FROM narrations WHERE id=? AND project_id=?",
            (narration_id, project_id),
        ).fetchone()
        if not draft:
            raise HTTPException(404, "Narration draft not found")
        stories = selected_story_packet(conn, project_id)
        styles = _style_transcripts(conn, project.get("channel") or "cinema", project.get("content_type") or "weekly_news")

    user = "\n".join([
        "<current_week_authoritative_packet>",
        json.dumps({
            "project": {
                "language": project.get("language"),
                "target_minutes": project.get("target_minutes"),
                "date_start": project.get("date_start"),
                "date_end": project.get("date_end"),
            },
            "format_blueprint": format_packet(),
            "approved_sections": _sectioned_story_packet(stories),
        }, ensure_ascii=False),
        "</current_week_authoritative_packet>",
        "",
        build_style_packet(styles),
        "",
        "<draft_to_review>",
        draft["content"],
        "</draft_to_review>",
    ])
    try:
        review_text, actual_provider, actual_model = generate_text(provider, model, REVIEWER_SYSTEM, user)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    gate = parse_review_gate(review_text)
    review_id = str(uuid.uuid4())
    stamp = now()
    with db() as conn:
        review_number = int(conn.execute(
            "SELECT COALESCE(MAX(review_number),0)+1 v FROM narration_reviews WHERE narration_id=?",
            (narration_id,),
        ).fetchone()["v"])
        conn.execute(
            """INSERT INTO narration_reviews(
                id,project_id,narration_id,review_number,content,provider,model,gate_status,
                blocking_count,major_count,minor_count,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                review_id, project_id, narration_id, review_number, review_text,
                actual_provider, actual_model, gate["gate_status"],
                gate["blocking_count"], gate["major_count"], gate["minor_count"], stamp,
            ),
        )
        root = Path(project["root_path"]) / "narration" / "reviews"
        root.mkdir(parents=True, exist_ok=True)
        (root / f"v{int(draft['version_number']):02d}_r{review_number:02d}.md").write_text(review_text, encoding="utf-8")
        save_manifest(conn, project_id)
    return {
        "id": review_id,
        "narration_id": narration_id,
        "project_id": project_id,
        "review_number": review_number,
        "content": review_text,
        **gate,
    }


@app.post("/api/projects/{project_id}/narrations/{narration_id}/revise")
def revise_narration(project_id: str, narration_id: str, body: NarrationRevisionBody):
    settings = masked_status()
    provider = body.provider or settings.get("writer_provider", "codex_local")
    model = body.model or settings.get("writer_model", "default")
    with db() as conn:
        project = project_or_404(conn, project_id)
        draft = conn.execute(
            "SELECT * FROM narrations WHERE id=? AND project_id=?",
            (narration_id, project_id),
        ).fetchone()
        if not draft:
            raise HTTPException(404, "Narration draft not found")
        if body.review_id:
            review = conn.execute(
                "SELECT * FROM narration_reviews WHERE id=? AND narration_id=?",
                (body.review_id, narration_id),
            ).fetchone()
        else:
            review = conn.execute(
                "SELECT * FROM narration_reviews WHERE narration_id=? ORDER BY review_number DESC LIMIT 1",
                (narration_id,),
            ).fetchone()
        if not review:
            raise HTTPException(400, "Run a reviewer pass on this draft first.")
        stories = selected_story_packet(conn, project_id)

    user = "\n".join([
        "<current_week_authoritative_packet>",
        json.dumps({
            "format_blueprint": format_packet(),
            "approved_sections": _sectioned_story_packet(stories),
        }, ensure_ascii=False),
        "</current_week_authoritative_packet>",
        "",
        "<existing_narration>",
        draft["content"],
        "</existing_narration>",
        "",
        "<review_change_list>",
        review["content"],
        "</review_change_list>",
    ])
    try:
        revised_text, actual_provider, actual_model = generate_text(provider, model, REVISION_SYSTEM, user)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

    new_id = str(uuid.uuid4())
    stamp = now()
    with db() as conn:
        project = project_or_404(conn, project_id)
        version = _narration_version(conn, project_id)
        conn.execute(
            """INSERT INTO narrations(
                id,project_id,version_number,content,provider,model,story_ids_json,
                created_at,approved,parent_narration_id,revision_review_id
            ) VALUES (?,?,?,?,?,?,?,?,0,?,?)""",
            (
                new_id, project_id, version, revised_text, actual_provider, actual_model,
                draft["story_ids_json"], stamp, narration_id, review["id"],
            ),
        )
        _write_narration_file(project, version, revised_text)
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        save_manifest(conn, project_id)
    return {
        "id": new_id,
        "version_number": version,
        "content": revised_text,
        "provider": actual_provider,
        "model": actual_model,
        "parent_narration_id": narration_id,
        "revision_review_id": review["id"],
    }


@app.post("/api/projects/{project_id}/narrations/{narration_id}/approve")
def approve_narration(project_id: str, narration_id: str):
    with db() as conn:
        project_or_404(conn, project_id)
        draft = conn.execute(
            "SELECT * FROM narrations WHERE id=? AND project_id=?",
            (narration_id, project_id),
        ).fetchone()
        if not draft:
            raise HTTPException(404, "Narration draft not found")
        review = conn.execute(
            "SELECT * FROM narration_reviews WHERE narration_id=? ORDER BY review_number DESC LIMIT 1",
            (narration_id,),
        ).fetchone()
        if not review:
            raise HTTPException(400, "Run Reviewer before approving this narration.")
        if review["gate_status"] == "revision_required":
            raise HTTPException(400, "Reviewer still requires revision. Revise this draft and review the new version first.")
        conn.execute("UPDATE narrations SET approved=0 WHERE project_id=?", (project_id,))
        conn.execute("UPDATE narrations SET approved=1 WHERE id=?", (narration_id,))
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        save_manifest(conn, project_id)
    return {"ok": True, "approved_narration_id": narration_id}


class ElevenLabsKeyBody(BaseModel):
    api_key: str = Field(min_length=8)


class NarratorVoiceBody(BaseModel):
    voice_id: str = Field(min_length=1)
    voice_name: str = ""


class PerformanceTextBody(BaseModel):
    performance_text: str = Field(min_length=1)


def _latest_narration(conn, project_id: str):
    return conn.execute(
        "SELECT * FROM narrations WHERE project_id=? ORDER BY approved DESC, version_number DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def _voice_payload(conn, project_id: str) -> dict:
    project = project_or_404(conn, project_id)
    narration = _latest_narration(conn, project_id)
    settings = conn.execute(
        "SELECT * FROM voice_settings WHERE project_id=?",
        (project_id,),
    ).fetchone()
    segments = [dict(row) for row in conn.execute(
        """SELECT * FROM voice_segments
           WHERE project_id=? ORDER BY segment_index""",
        (project_id,),
    ).fetchall()]
    story_rows = conn.execute(
        """SELECT story_id,
                  ROUND(COALESCE(SUM(duration_seconds),0),3) AS duration_seconds,
                  COUNT(*) AS segment_count
           FROM voice_segments
           WHERE project_id=? AND story_id<>''
           GROUP BY story_id""",
        (project_id,),
    ).fetchall()
    story_durations = {
        row["story_id"]: {
            "duration_seconds": float(row["duration_seconds"] or 0),
            "segment_count": int(row["segment_count"] or 0),
        }
        for row in story_rows
    }
    return {
        "project_id": project_id,
        "narration": dict(narration) if narration else None,
        "settings": dict(settings) if settings else {
            "voice_id": "",
            "voice_name": "",
            "model_id": ELEVEN_MODEL_ID,
            "output_format": "mp3_44100_128",
            "prepared_narration_id": "",
        },
        "segments": segments,
        "story_durations": story_durations,
        "total_duration_seconds": round(sum(float(x.get("duration_seconds") or 0) for x in segments), 3),
        "generated_count": sum(1 for x in segments if x.get("take1_path") or x.get("take2_path")),
        "approved_count": sum(1 for x in segments if x.get("approval_status") == "approved"),
        "aligned_count": sum(1 for x in segments if x.get("audio_status") == "aligned"),
    }


@app.get("/api/voice/connection")
def voice_connection():
    configured = bool(get_api_key("elevenlabs"))
    voices, error = [], ""
    if configured:
        try:
            voices = list_voices()
        except ElevenLabsError as exc:
            error = str(exc)
    return {
        "configured": configured,
        "connected": configured and not error,
        "voice_count": len(voices),
        "voices": voices,
        "error": error,
        "model_id": ELEVEN_MODEL_ID,
    }


@app.put("/api/voice/connection")
def save_voice_connection(body: ElevenLabsKeyBody):
    set_api_key("elevenlabs", body.api_key)
    try:
        voices = list_voices()
    except ElevenLabsError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "voice_count": len(voices), "voices": voices}


@app.delete("/api/voice/connection")
def clear_voice_connection():
    delete_api_key("elevenlabs")
    return {"ok": True}


@app.get("/api/projects/{project_id}/voice")
def get_voice_workspace(project_id: str):
    with db() as conn:
        return _voice_payload(conn, project_id)


@app.put("/api/projects/{project_id}/voice/settings")
def save_narrator_voice(project_id: str, body: NarratorVoiceBody):
    stamp = now()
    with db() as conn:
        project_or_404(conn, project_id)
        current = conn.execute(
            "SELECT voice_id FROM voice_settings WHERE project_id=?",
            (project_id,),
        ).fetchone()
        voice_changed = bool(current and current["voice_id"] and current["voice_id"] != body.voice_id)
        conn.execute(
            """INSERT INTO voice_settings(
                   project_id,voice_id,voice_name,model_id,output_format,prepared_narration_id,updated_at
               ) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET
                   voice_id=excluded.voice_id,
                   voice_name=excluded.voice_name,
                   model_id=excluded.model_id,
                   output_format=excluded.output_format,
                   updated_at=excluded.updated_at""",
            (
                project_id, body.voice_id, body.voice_name, ELEVEN_MODEL_ID,
                "mp3_44100_128", "", stamp,
            ),
        )
        if voice_changed:
            conn.execute(
                """UPDATE voice_segments
                   SET voice_id=?,audio_path='',duration_seconds=NULL,alignment_json='{}',
                       audio_status='pending',take1_path='',take2_path='',selected_take=0,
                       approval_status='pending',updated_at=?
                   WHERE project_id=?""",
                (body.voice_id, stamp, project_id),
            )
        save_manifest(conn, project_id)
        return _voice_payload(conn, project_id)


@app.post("/api/projects/{project_id}/voice/prepare")
def prepare_narrator_voice(project_id: str):
    stamp = now()
    with db() as conn:
        project = project_or_404(conn, project_id)
        narration = _latest_narration(conn, project_id)
        settings = conn.execute("SELECT * FROM voice_settings WHERE project_id=?", (project_id,)).fetchone()
    if not narration:
        raise HTTPException(400, "Generate narration first.")
    if not int(narration["approved"] or 0):
        raise HTTPException(400, "Review and approve a narration draft in Step 3 before preparing voice.")
    if not settings or not settings["voice_id"]:
        raise HTTPException(400, "Choose one ElevenLabs narrator voice first.")

    raw_segments = extract_narration_segments(narration["content"])
    if not raw_segments:
        raise HTTPException(400, "No spoken narration could be extracted from the latest narration.")
    performance, warnings, provider, model = prepare_performance(raw_segments)

    root = Path(project["root_path"])
    audio_dir = root / "audio" / "narration"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for path in audio_dir.glob("*.mp3"):
        try:
            path.unlink()
        except Exception:
            pass

    with db() as conn:
        conn.execute("DELETE FROM voice_segments WHERE project_id=?", (project_id,))
        for segment in raw_segments:
            conn.execute(
                """INSERT INTO voice_segments(
                    id,project_id,narration_id,story_id,segment_index,source_text,performance_text,
                    voice_id,audio_path,duration_seconds,alignment_json,audio_status,
                    take1_path,take2_path,selected_take,approval_status,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    segment["id"], project_id, narration["id"], segment.get("story_id", ""),
                    segment["segment_index"], segment["source_text"],
                    performance.get(segment["id"], segment["source_text"]),
                    settings["voice_id"], "", None, "{}", "prepared", "", "", 0, "pending", stamp, stamp,
                ),
            )
        conn.execute(
            """UPDATE voice_settings
               SET prepared_narration_id=?,updated_at=? WHERE project_id=?""",
            (narration["id"], stamp, project_id),
        )
        save_manifest(conn, project_id)
        payload = _voice_payload(conn, project_id)
    payload.update({"warnings": warnings, "performance_provider": provider, "performance_model": model})
    return payload


@app.post("/api/projects/{project_id}/voice/generate")
def generate_narrator_voice(project_id: str):
    if not get_api_key("elevenlabs"):
        raise HTTPException(400, "Connect ElevenLabs first.")
    with db() as conn:
        project = project_or_404(conn, project_id)
        narration = _latest_narration(conn, project_id)
        settings = conn.execute("SELECT * FROM voice_settings WHERE project_id=?", (project_id,)).fetchone()
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM voice_segments WHERE project_id=? ORDER BY segment_index",
            (project_id,),
        ).fetchall()]
    if not narration:
        raise HTTPException(400, "Generate narration first.")
    if not settings or not settings["voice_id"]:
        raise HTTPException(400, "Choose one ElevenLabs narrator voice first.")
    if not rows or any(row["narration_id"] != narration["id"] for row in rows):
        raise HTTPException(400, "Prepare the latest narration for voice first.")

    root = Path(project["root_path"])
    audio_dir = root / "audio" / "narration"
    audio_dir.mkdir(parents=True, exist_ok=True)
    generated = 0
    aligned = 0
    reused_audio = 0
    errors = []
    output_format = settings["output_format"] or "mp3_44100_192"

    for row in rows:
        if row.get("audio_status") == "aligned" and row.get("audio_path"):
            continue

        filename = f"{int(row['segment_index']):04d}_narration.mp3"
        expected_path = audio_dir / filename
        stored_path = str(row.get("audio_path") or "")
        existing_path = (root / stored_path).resolve() if stored_path else expected_path.resolve()
        can_reuse_audio = bool(
            existing_path.exists()
            and existing_path.is_file()
            and root.resolve() in existing_path.parents
            and row.get("duration_seconds")
        )

        try:
            if can_reuse_audio:
                path = existing_path
                duration = float(row["duration_seconds"])
                reused_audio += 1
            else:
                audio = text_to_speech(
                    settings["voice_id"],
                    row["performance_text"] or row["source_text"],
                )
                output_format = "mp3_44100_128"
                path = expected_path
                path.write_bytes(audio)
                duration = mp3_duration_seconds(path)
                if duration is None:
                    raise RuntimeError("Could not measure generated MP3 duration.")
                rel = path.relative_to(root).as_posix()
                with db() as conn:
                    conn.execute(
                        """UPDATE voice_segments
                           SET voice_id=?,audio_path=?,duration_seconds=?,alignment_json='{}',
                               audio_status='generated',updated_at=? WHERE id=?""",
                        (
                            settings["voice_id"], rel, float(duration),
                            now(), row["id"],
                        ),
                    )
                generated += 1

            # Alignment is a separate phase. A failure here leaves the paid
            # generated MP3 and measured duration intact, so retrying does not
            # synthesize the voice again.
            alignment = forced_alignment(path, row["source_text"])
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
                raise RuntimeError("ElevenLabs Forced Alignment returned no word timestamps.")

            rel = path.relative_to(root).as_posix()
            with db() as conn:
                conn.execute(
                    """UPDATE voice_segments
                       SET voice_id=?,audio_path=?,duration_seconds=?,alignment_json=?,
                           audio_status='aligned',updated_at=? WHERE id=?""",
                    (
                        settings["voice_id"], rel, float(duration),
                        json.dumps({"words": words, "loss": alignment.get("loss")}, ensure_ascii=False),
                        now(), row["id"],
                    ),
                )
            aligned += 1
        except Exception as exc:
            errors.append({
                "segment_id": row["id"],
                "segment_index": row["segment_index"],
                "error": str(exc),
            })
            # Keep a successfully generated source file reusable even when only
            # alignment failed. Never convert it back to a state that forces TTS.
            with db() as conn:
                current = conn.execute(
                    "SELECT audio_path,duration_seconds FROM voice_segments WHERE id=?",
                    (row["id"],),
                ).fetchone()
                keep_generated = bool(
                    current
                    and current["audio_path"]
                    and current["duration_seconds"]
                    and (root / current["audio_path"]).exists()
                )
                conn.execute(
                    "UPDATE voice_segments SET audio_status=?,updated_at=? WHERE id=?",
                    ("generated" if keep_generated else "failed", now(), row["id"]),
                )

    with db() as conn:
        conn.execute(
            "UPDATE voice_settings SET output_format=?,updated_at=? WHERE project_id=?",
            (output_format, now(), project_id),
        )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        save_manifest(conn, project_id)
        payload = _voice_payload(conn, project_id)
    payload.update({
        "generated_this_run": generated,
        "aligned_this_run": aligned,
        "reused_audio_for_alignment": reused_audio,
        "errors": errors,
    })
    return payload


@app.get("/api/projects/{project_id}/voice/{segment_id}/audio")
def narration_audio(project_id: str, segment_id: str):
    with db() as conn:
        project = project_or_404(conn, project_id)
        row = conn.execute(
            "SELECT audio_path FROM voice_segments WHERE project_id=? AND id=?",
            (project_id, segment_id),
        ).fetchone()
    if not row or not row["audio_path"]:
        raise HTTPException(404, "Narration audio has not been generated.")
    root = Path(project["root_path"]).resolve()
    path = (root / row["audio_path"]).resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(404, "Narration audio file is missing.")
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)



@app.put("/api/projects/{project_id}/voice/{segment_id}/performance")
def update_voice_performance(project_id: str, segment_id: str, body: PerformanceTextBody):
    candidate = body.performance_text.strip()
    with db() as conn:
        project = project_or_404(conn, project_id)
        row = conn.execute(
            "SELECT * FROM voice_segments WHERE project_id=? AND id=?",
            (project_id, segment_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Voice segment not found.")
        row = dict(row)
    if not performance_text_is_safe(row["source_text"], candidate):
        raise HTTPException(
            400,
            "Performance text may change Eleven v3 tags, punctuation, pauses, capitalization, and spacing, "
            "but it must keep the exact same spoken words in the same order.",
        )
    if candidate == (row.get("performance_text") or "").strip():
        return {"ok": True, "changed": False}
    clear_segment_files(Path(project["root_path"]), row)
    with db() as conn:
        conn.execute(
            """UPDATE voice_segments
               SET performance_text=?,audio_path='',duration_seconds=NULL,alignment_json='{}',
                   audio_status='prepared',take1_path='',take2_path='',selected_take=0,
                   approval_status='pending',updated_at=? WHERE id=?""",
            (candidate, now(), segment_id),
        )
        save_manifest(conn, project_id)
    return {"ok": True, "changed": True}


@app.post("/api/projects/{project_id}/voice/{segment_id}/takes/{take_number}/generate")
def generate_voice_take(project_id: str, segment_id: str, take_number: int):
    try:
        result = generate_voice_take_service(project_id, segment_id, take_number, now())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with db() as conn:
        save_manifest(conn, project_id)
    return result


@app.post("/api/projects/{project_id}/voice/{segment_id}/takes/{take_number}/approve")
def approve_voice_take(project_id: str, segment_id: str, take_number: int):
    try:
        result = approve_voice_take_service(project_id, segment_id, take_number, now())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with db() as conn:
        save_manifest(conn, project_id)
        result["workspace"] = _voice_payload(conn, project_id)
    return result


@app.get("/api/projects/{project_id}/voice/{segment_id}/takes/{take_number}/audio")
def voice_take_audio(project_id: str, segment_id: str, take_number: int):
    if take_number not in (1, 2):
        raise HTTPException(400, "Take number must be 1 or 2.")
    column = "take1_path" if take_number == 1 else "take2_path"
    with db() as conn:
        project = project_or_404(conn, project_id)
        row = conn.execute(
            f"SELECT {column} AS take_path FROM voice_segments WHERE project_id=? AND id=?",
            (project_id, segment_id),
        ).fetchone()
    if not row or not row["take_path"]:
        raise HTTPException(404, f"Take {take_number} has not been generated.")
    root = Path(project["root_path"]).resolve()
    path = (root / row["take_path"]).resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(404, "Audio file is missing.")
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)


def _automatic_media_plan(stories: list[dict], narration_text: str = "") -> dict:
    beats = []
    for index, story in enumerate(stories, start=1):
        title = story.get("canonical_title", "")
        beats.append({
            "id": f"M{index:03d}",
            "story_id": story.get("id", ""),
            "story_title": title,
            "narration_excerpt": "",
            "visuals": [
                {
                    "type": "video",
                    "search_intent": f"{title} official trailer clip featurette behind the scenes",
                    "preferred_source": "original studio / distributor / official production channel",
                    "why": "Primary source: use clean official B-roll, not a news recap, reaction, review, or commentator video.",
                },
                {
                    "type": "image",
                    "search_intent": f"{title} official still poster press photo",
                    "preferred_source": "official studio / press photography / reputable publication",
                    "why": "Supporting source only when a still, poster, event photo, or announcement image is useful.",
                },
            ],
        })
    return {"beats": beats, "source": "automatic_included_story_plan", "has_narration": bool(narration_text.strip())}


@app.post("/api/projects/{project_id}/media-plan")
def generate_media_plan(project_id: str, body: GenerateBody):
    """Build a reliable plan from Included stories.

    AI enrichment is optional. A valid deterministic plan is always produced, so
    media discovery never depends on a provider returning perfectly formatted JSON.
    """
    settings = masked_status()
    provider = body.provider or settings.get("reviewer_provider", "claude_local")
    model = body.model or settings.get("reviewer_model", "default")
    with db() as conn:
        project = project_or_404(conn, project_id)
        narration = conn.execute("SELECT * FROM narrations WHERE project_id=? ORDER BY version_number DESC LIMIT 1", (project_id,)).fetchone()
        stories = selected_story_packet(conn, project_id)
    if not stories:
        raise HTTPException(400, "Include at least one story before building media sources.")

    narration_text = narration["content"] if narration else ""
    plan = _automatic_media_plan(stories, narration_text)
    actual_provider, actual_model = "automatic", "included-stories"
    ai_error = ""
    if narration and body.instructions.strip():
        packet = {"narration": narration_text, "stories": stories, "instructions": body.instructions}
        try:
            text, actual_provider, actual_model = generate_text(provider, model, MEDIA_PLAN_SYSTEM, json.dumps(packet, ensure_ascii=False))
            raw = text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            ai_plan = json.loads(raw)
            if isinstance(ai_plan, dict) and isinstance(ai_plan.get("beats"), list):
                plan = ai_plan
        except Exception as exc:
            ai_error = str(exc)

    plan_id = str(uuid.uuid4())
    stamp = now()
    narration_id = narration["id"] if narration else ""
    with db() as conn:
        # Legacy table requires a narration FK. Store on disk only when narration
        # does not exist yet; the media-search workflow itself does not require it.
        if narration_id:
            conn.execute(
                "INSERT INTO media_plans(id,project_id,narration_id,content_json,provider,model,created_at) VALUES (?,?,?,?,?,?,?)",
                (plan_id, project_id, narration_id, json.dumps(plan, ensure_ascii=False), actual_provider, actual_model, stamp),
            )
        root = Path(project["root_path"])
        (root / "media-plan" / f"{plan_id}.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        save_manifest(conn, project_id)
    return {"id": plan_id, "plan": plan, "provider": actual_provider, "model": actual_model, "ai_error": ai_error}


@app.get("/api/projects/{project_id}/media-plan")
def latest_media_plan(project_id: str):
    with db() as conn:
        project_or_404(conn, project_id)
        stories = selected_story_packet(conn, project_id)
        row = conn.execute("SELECT * FROM media_plans WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
        if row:
            item = dict(row)
            item["plan"] = json.loads(item.pop("content_json") or "{}")
        elif stories:
            item = {"id": "automatic", "provider": "automatic", "model": "included-stories", "plan": _automatic_media_plan(stories)}
        else:
            return None
        for beat in item["plan"].get("beats", []):
            for visual in beat.get("visuals", []):
                q = visual.get("search_intent", "")
                visual["search_links"] = {
                    "youtube": f"https://www.youtube.com/results?search_query={quote_plus(q)}",
                    "google_images": f"https://www.google.com/search?tbm=isch&q={quote_plus(q)}",
                    "reddit": f"https://www.reddit.com/search/?q={quote_plus(q)}",
                }
        return item



def _chunk_story_durations(
    ordered_stories: list[tuple[str, float]],
    target_seconds: float,
) -> list[list[tuple[str, float]]]:
    target_seconds = max(15.0, float(target_seconds or 60.0))
    chunks: list[list[tuple[str, float]]] = []
    current: list[tuple[str, float]] = []
    current_seconds = 0.0
    for story_id, raw_duration in ordered_stories:
        duration = max(0.0, float(raw_duration or 0.0))
        if current and current_seconds + duration > target_seconds:
            chunks.append(current)
            current = []
            current_seconds = 0.0
        current.append((story_id, duration))
        current_seconds += duration
        if current_seconds >= target_seconds:
            chunks.append(current)
            current = []
            current_seconds = 0.0
    if current:
        chunks.append(current)
    return chunks


def _build_media_search_chunks(conn, project_id: str, chunk_minutes: float | None = None) -> dict:
    project = project_or_404(conn, project_id)
    target_minutes = float(chunk_minutes if chunk_minutes is not None else project.get("media_chunk_minutes") or 1.0)
    target_minutes = max(0.25, min(10.0, target_minutes))
    target_seconds = target_minutes * 60.0

    stories = selected_story_packet(conn, project_id)
    story_by_id = {story["id"]: story for story in stories}
    duration_rows = conn.execute(
        """SELECT story_id,
                  COALESCE(SUM(duration_seconds),0) AS duration_seconds,
                  MIN(segment_index) AS first_segment
           FROM voice_segments
           WHERE project_id=? AND story_id<>''
           GROUP BY story_id
           ORDER BY first_segment""",
        (project_id,),
    ).fetchall()
    durations = {
        row["story_id"]: float(row["duration_seconds"] or 0)
        for row in duration_rows
        if row["story_id"] in story_by_id
    }

    ordered_ids = [row["story_id"] for row in duration_rows if row["story_id"] in story_by_id]
    ordered_set = set(ordered_ids)
    ordered_ids.extend(story["id"] for story in stories if story["id"] not in ordered_set)

    # Older projects can contain approved narration whose STORY ids came from a
    # previous research run. Do not collapse those current stories to 0 seconds:
    # distribute the remaining real approved voice duration across stories that
    # have no direct duration match. If no usable voice duration exists, use the
    # configured target episode duration as the final planning fallback.
    approved_voice_seconds = float(conn.execute(
        """SELECT COALESCE(SUM(duration_seconds),0) s
           FROM voice_segments
           WHERE project_id=? AND audio_status='aligned' AND approval_status='approved'""",
        (project_id,),
    ).fetchone()["s"] or 0)
    known_seconds = sum(max(0.0, durations.get(story_id, 0.0)) for story_id in ordered_ids)
    missing_duration_ids = [story_id for story_id in ordered_ids if durations.get(story_id, 0.0) <= 0]
    if missing_duration_ids:
        remaining_voice = max(0.0, approved_voice_seconds - known_seconds)
        if remaining_voice > 0:
            fallback_each = remaining_voice / len(missing_duration_ids)
        else:
            fallback_total = approved_voice_seconds or float(project.get("target_minutes") or 0) * 60.0
            fallback_each = fallback_total / max(1, len(ordered_ids))
        for story_id in missing_duration_ids:
            durations[story_id] = max(0.0, fallback_each)

    chunks: list[dict] = []
    timeline_cursor = 0.0
    grouped = _chunk_story_durations(
        [(story_id, durations.get(story_id, 0.0)) for story_id in ordered_ids],
        target_seconds,
    )
    for group in grouped:
        story_ids = [story_id for story_id, _ in group]
        group_seconds = sum(duration for _, duration in group)
        chunks.append({
            "index": len(chunks) + 1,
            "story_ids": story_ids,
            "story_count": len(story_ids),
            "duration_seconds": round(group_seconds, 3),
            "timeline_start_seconds": round(timeline_cursor, 3),
            "timeline_end_seconds": round(timeline_cursor + group_seconds, 3),
            "titles": [story_by_id[story_id]["canonical_title"] for story_id in story_ids],
        })
        timeline_cursor += group_seconds

    total_story_seconds = round(sum(durations.get(story_id, 0.0) for story_id in ordered_ids), 3)
    duration_source = "story_voice"
    if any(story_id in missing_duration_ids for story_id in ordered_ids):
        duration_source = "approved_voice_fallback" if approved_voice_seconds > 0 else "target_duration_fallback"
    return {
        "chunk_minutes": target_minutes,
        "chunk_seconds": target_seconds,
        "target_episode_minutes": int(project.get("target_minutes") or 0),
        "actual_story_voice_seconds": total_story_seconds,
        "approved_voice_seconds": round(approved_voice_seconds, 3),
        "duration_source": duration_source,
        "total_chunks": len(chunks),
        "total_stories": len(ordered_ids),
        "chunks": chunks,
    }


@app.get("/api/projects/{project_id}/media/search-plan")
def media_search_plan(project_id: str, chunk_minutes: float | None = None):
    if chunk_minutes is not None and not 0.25 <= chunk_minutes <= 10:
        raise HTTPException(400, "B-roll search chunk must be between 0.25 and 10 minutes.")
    with db() as conn:
        return _build_media_search_chunks(conn, project_id, chunk_minutes)


class MediaSearchBody(BaseModel):
    refresh: bool = True
    max_images_per_story: int = Field(default=3, ge=1, le=8)
    max_videos_per_story: int = Field(default=8, ge=1, le=16)
    story_ids: list[str] | None = None


@app.post("/api/projects/{project_id}/media/search")
def search_included_story_media(project_id: str, body: MediaSearchBody):
    with db() as conn:
        project = project_or_404(conn, project_id)
        all_stories = selected_story_packet(conn, project_id)
    if not all_stories:
        raise HTTPException(400, "Include at least one story before searching for media.")

    stories = all_stories
    if body.story_ids is not None:
        requested = list(dict.fromkeys(body.story_ids))
        allowed_ids = {story["id"] for story in all_stories}
        invalid = [story_id for story_id in requested if story_id not in allowed_ids]
        if invalid:
            raise HTTPException(400, "Media search chunk contains a story that is no longer Included.")
        story_by_id = {story["id"]: story for story in all_stories}
        stories = [story_by_id[story_id] for story_id in requested]
        if not stories:
            raise HTTPException(400, "Media search chunk is empty.")
    with db() as conn:
        voice_total = conn.execute(
            "SELECT COUNT(*) c FROM voice_segments WHERE project_id=?",
            (project_id,),
        ).fetchone()["c"]
        voice_aligned = conn.execute(
            "SELECT COUNT(*) c FROM voice_segments WHERE project_id=? AND audio_status='aligned' AND approval_status='approved'",
            (project_id,),
        ).fetchone()["c"]
        narration_rows = conn.execute(
            """SELECT story_id,source_text,duration_seconds
               FROM voice_segments
               WHERE project_id=? AND story_id<>''
               ORDER BY segment_index""",
            (project_id,),
        ).fetchall()
    narration_by_story: dict[str, list[str]] = {}
    voice_seconds_by_story: dict[str, float] = {}
    for row in narration_rows:
        narration_by_story.setdefault(row["story_id"], []).append(str(row["source_text"] or ""))
        voice_seconds_by_story[row["story_id"]] = voice_seconds_by_story.get(row["story_id"], 0.0) + float(row["duration_seconds"] or 0)
    for story in all_stories:
        story["_narration_text"] = " ".join(narration_by_story.get(story["id"], [])).strip()
        story["_voice_duration_seconds"] = voice_seconds_by_story.get(story["id"], 0.0)
    if not voice_total or voice_aligned != voice_total:
        raise HTTPException(
            400,
            "Generate and align the complete narrator voice in Step 4 before searching media. "
            "Media timing is based on the real ElevenLabs audio duration.",
        )

    diagnostics = []
    total_added = 0
    stamp = now()
    youtube_query_cache: dict[str, list[dict]] = {}
    reference_page_cache: dict[str, tuple[str, str]] = {}
    web_video_cache: dict[str, list[dict]] = {}

    # Search this narration-time chunk only. Reuse high-quality videos already
    # saved for duplicate subjects in earlier chunks.
    searched: list[dict] = []
    videos_by_subject: dict[str, list[dict]] = {}
    current_story_ids = {story["id"] for story in stories}
    with db() as conn:
        for existing_story in all_stories:
            if body.refresh and existing_story["id"] in current_story_ids:
                continue
            subject_key = story_media_key(existing_story)
            rows = conn.execute(
                """SELECT * FROM media_candidates
                   WHERE project_id=? AND story_id=? AND media_type='video'
                   ORDER BY selected DESC, height DESC, created_at DESC""",
                (project_id, existing_story["id"]),
            ).fetchall()
            bucket = videos_by_subject.setdefault(subject_key, [])
            for row in rows:
                item = dict(row)
                if not any(existing.get("page_url") == item.get("page_url") for existing in bucket):
                    bucket.append(item)
    for story in stories:
        candidates, errors = search_story_media(
            story,
            max_images=body.max_images_per_story,
            max_videos=body.max_videos_per_story,
            query_cache=youtube_query_cache,
            reference_page_cache=reference_page_cache,
            web_video_cache=web_video_cache,
        )
        key = story_media_key(story)
        searched.append({
            "story": story,
            "key": key,
            "candidates": candidates,
            "errors": errors,
        })
        for item in candidates:
            if item.get("media_type") != "video":
                continue
            bucket = videos_by_subject.setdefault(key, [])
            if not any(existing.get("page_url") == item.get("page_url") for existing in bucket):
                bucket.append(dict(item))

    subject_story_counts: dict[str, int] = {}
    for included_story in all_stories:
        subject_key = story_media_key(included_story)
        subject_story_counts[subject_key] = subject_story_counts.get(subject_key, 0) + 1
    with db() as conn:
        voice_duration_rows = conn.execute(
            """SELECT story_id,COALESCE(SUM(duration_seconds),0) AS duration_seconds
               FROM voice_segments
               WHERE project_id=? AND story_id<>''
               GROUP BY story_id""",
            (project_id,),
        ).fetchall()
    story_voice_durations = {
        row["story_id"]: float(row["duration_seconds"] or 0)
        for row in voice_duration_rows
    }
    clip_usage_counts: dict[tuple[str, str], int] = {}

    for result in searched:
        story = result["story"]
        candidates = list(result["candidates"])
        sibling_videos = videos_by_subject.get(result["key"], [])

        # A valid video discovered for any duplicate headline should prevent
        # another headline about the same title from falling back to images.
        if sibling_videos:
            own_video_urls = {
                item.get("page_url")
                for item in candidates
                if item.get("media_type") == "video"
            }
            merged_videos = [
                item for item in candidates if item.get("media_type") == "video"
            ]
            for sibling in sibling_videos:
                if sibling.get("page_url") in own_video_urls:
                    continue
                cloned = dict(sibling)
                cloned["id"] = str(uuid.uuid4())
                merged_videos.append(cloned)
                own_video_urls.add(cloned.get("page_url"))
            merged_videos = _coverage_balanced_results(
                merged_videos,
                story,
                body.max_videos_per_story,
            )
            candidates = merged_videos + [
                item for item in candidates if item.get("media_type") == "image"
            ]

        story_voice_duration = float(story_voice_durations.get(story["id"], 0) or 0)
        for item in candidates:
            item["target_duration_sec"] = story_voice_duration or None
            if item.get("media_type") != "video":
                item["clip_start_sec"] = None
                item["clip_end_sec"] = None
                item["shared_source"] = 0
                continue
            usage_key = (result["key"], item.get("page_url") or "")
            usage_index = clip_usage_counts.get(usage_key, 0)
            # Keep candidate previews concise for now; the later edit-plan stage
            # will divide the full story narration across all selected assets.
            preview_len = 12 if story_voice_duration <= 0 else max(8, min(24, int(round(story_voice_duration))))
            start_sec, end_sec = suggested_clip_range(item.get("duration"), usage_index, clip_seconds=preview_len)
            item["clip_start_sec"] = start_sec
            item["clip_end_sec"] = end_sec
            item["shared_source"] = 1 if subject_story_counts.get(result["key"], 0) > 1 else 0
            clip_usage_counts[usage_key] = usage_index + 1

        with db() as conn:
            if body.refresh:
                conn.execute(
                    """DELETE FROM media_candidates
                       WHERE project_id=? AND story_id=? AND download_status<>'downloaded'""",
                    (project_id, story["id"]),
                )
            existing = {
                (row["media_type"], row["page_url"])
                for row in conn.execute(
                    "SELECT media_type,page_url FROM media_candidates WHERE project_id=? AND story_id=?",
                    (project_id, story["id"]),
                ).fetchall()
            }
            added = 0
            for item in candidates:
                key = (item["media_type"], item["page_url"])
                if key in existing:
                    continue
                conn.execute(
                    """INSERT INTO media_candidates(
                        id,project_id,story_id,media_type,title,page_url,asset_url,thumbnail_url,source,provider,
                        duration,published_at,width,height,search_query,clip_start_sec,clip_end_sec,target_duration_sec,shared_source,
                        coverage_label,coverage_kind,selected,download_status,stored_path,error,rights_status,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        item["id"], project_id, story["id"], item["media_type"], item["title"], item["page_url"],
                        item["asset_url"], item["thumbnail_url"], item["source"], item["provider"], item["duration"],
                        item["published_at"], item["width"], item["height"], item["search_query"],
                        item.get("clip_start_sec"), item.get("clip_end_sec"), item.get("target_duration_sec"), item.get("shared_source", 0),
                        item.get("coverage_label", ""), item.get("coverage_kind", ""),
                        0, "not_downloaded", "", "", "unverified", stamp, stamp,
                    ),
                )
                existing.add(key)
                added += 1
            total_added += added
        with db() as conn:
            result_count = conn.execute(
                "SELECT COUNT(*) c FROM media_candidates WHERE project_id=? AND story_id=?",
                (project_id, story["id"]),
            ).fetchone()["c"]
        diagnostics.append({
            "story_id": story["id"],
            "story_title": story["canonical_title"],
            "subject_key": result["key"],
            "found": len(candidates),
            "added": added,
            "result_count": int(result_count or 0),
            "reused_subject_videos": max(
                0,
                len([x for x in candidates if x.get("media_type") == "video"])
                - len([x for x in result["candidates"] if x.get("media_type") == "video"]),
            ),
            "errors": result["errors"],
        })

    with db() as conn:
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        save_manifest(conn, project_id)
    stories_with_results = sum(1 for item in diagnostics if int(item.get("result_count") or 0) > 0)
    return {
        "ok": True,
        "stories": len(stories),
        "story_ids": [story["id"] for story in stories],
        "added": total_added,
        "stories_with_results": stories_with_results,
        "stories_without_results": len(stories) - stories_with_results,
        "diagnostics": diagnostics,
    }


@app.get("/api/projects/{project_id}/media/candidates")
def media_candidates(project_id: str):
    with db() as conn:
        project_or_404(conn, project_id)
        stories = selected_story_packet(conn, project_id)
        output = []
        for story in stories:
            rows = conn.execute(
                """SELECT * FROM media_candidates
                   WHERE project_id=? AND story_id=?
                   ORDER BY media_type, selected DESC, created_at""",
                (project_id, story["id"]),
            ).fetchall()
            candidates = []
            for row in rows:
                item = dict(row)
                item["selected"] = bool(item["selected"])
                candidates.append(item)
            voice_rows = conn.execute(
                """SELECT source_text,duration_seconds
                   FROM voice_segments
                   WHERE project_id=? AND story_id=?
                   ORDER BY segment_index""",
                (project_id, story["id"]),
            ).fetchall()
            voice_duration = sum(float(row["duration_seconds"] or 0) for row in voice_rows)
            story_for_plan = dict(story)
            story_for_plan["_narration_text"] = " ".join(str(row["source_text"] or "") for row in voice_rows).strip()
            story_for_plan["_voice_duration_seconds"] = voice_duration
            output.append({
                "story": {
                    "id": story["id"],
                    "title": story["canonical_title"],
                    "summary": story.get("summary", ""),
                    "category": story.get("category", ""),
                    "articles": story.get("articles", []),
                    "voice_duration_seconds": voice_duration,
                    "visual_coverage": story_visual_plan(story_for_plan),
                },
                "candidates": candidates,
            })
        return output


class MediaSelectionBody(BaseModel):
    selected: bool


@app.patch("/api/projects/{project_id}/media/candidates/{candidate_id}")
def set_media_candidate_selected(project_id: str, candidate_id: str, body: MediaSelectionBody):
    with db() as conn:
        project_or_404(conn, project_id)
        row = conn.execute(
            "SELECT 1 FROM media_candidates WHERE id=? AND project_id=?",
            (candidate_id, project_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Media candidate not found")
        conn.execute(
            "UPDATE media_candidates SET selected=?,updated_at=? WHERE id=?",
            (1 if body.selected else 0, now(), candidate_id),
        )
        save_manifest(conn, project_id)
    return {"ok": True, "selected": body.selected}


@app.post("/api/projects/{project_id}/media/download-selected")
def download_selected_media(project_id: str):
    with db() as conn:
        project = project_or_404(conn, project_id)
        rows = conn.execute(
            """SELECT c.*,s.canonical_title AS story_title
               FROM media_candidates c
               JOIN stories s ON s.id=c.story_id
               WHERE c.project_id=? AND c.selected=1
               ORDER BY c.story_id,c.media_type,c.created_at""",
            (project_id,),
        ).fetchall()
        candidates = [dict(row) for row in rows]
    if not candidates:
        raise HTTPException(400, "Select at least one image or video first.")

    results = []
    root = Path(project["root_path"])
    downloaded_by_url: dict[str, str] = {}
    with db() as conn:
        reusable = conn.execute(
            """SELECT page_url,stored_path FROM media_candidates
               WHERE project_id=? AND download_status='downloaded' AND stored_path<>''""",
            (project_id,),
        ).fetchall()
    for row in reusable:
        stored = str(row["stored_path"] or "")
        if stored and (root / stored).exists():
            downloaded_by_url[str(row["page_url"])] = stored

    for candidate in candidates:
        if candidate.get("download_status") == "downloaded" and candidate.get("stored_path"):
            downloaded_by_url[candidate.get("page_url") or ""] = candidate["stored_path"]
            results.append({"id": candidate["id"], "ok": True, "stored_path": candidate["stored_path"], "already_downloaded": True})
            continue

        page_url = candidate.get("page_url") or ""
        reused_path = downloaded_by_url.get(page_url)
        if reused_path:
            with db() as conn:
                conn.execute(
                    "UPDATE media_candidates SET download_status='downloaded',stored_path=?,error='',updated_at=? WHERE id=?",
                    (reused_path, now(), candidate["id"]),
                )
            results.append({
                "id": candidate["id"],
                "ok": True,
                "stored_path": reused_path,
                "reused_source_file": True,
                "clip_start_sec": candidate.get("clip_start_sec"),
                "clip_end_sec": candidate.get("clip_end_sec"),
            })
            continue

        try:
            path = download_candidate(candidate, root, candidate["story_title"])
            relative = path.resolve().relative_to(root.resolve()).as_posix()
            with db() as conn:
                conn.execute(
                    "UPDATE media_candidates SET download_status='downloaded',stored_path=?,error='',updated_at=? WHERE id=?",
                    (relative, now(), candidate["id"]),
                )
            downloaded_by_url[page_url] = relative
            results.append({
                "id": candidate["id"],
                "ok": True,
                "stored_path": relative,
                "clip_start_sec": candidate.get("clip_start_sec"),
                "clip_end_sec": candidate.get("clip_end_sec"),
            })
        except Exception as exc:
            message = str(exc)
            with db() as conn:
                conn.execute(
                    "UPDATE media_candidates SET download_status='failed',error=?,updated_at=? WHERE id=?",
                    (message[:1200], now(), candidate["id"]),
                )
            results.append({"id": candidate["id"], "ok": False, "error": message})

    with db() as conn:
        save_manifest(conn, project_id)
    return {
        "ok": all(item["ok"] for item in results),
        "downloaded": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "results": results,
        "rights_note": "Downloaded files keep an unverified rights status. Verify permission/licensing before publishing reused media.",
    }


@app.get("/api/projects/{project_id}/resolve-plan")
def get_resolve_plan(project_id: str):
    with db() as conn:
        project = project_or_404(conn, project_id)
        voice_rows = [dict(row) for row in conn.execute(
            "SELECT * FROM voice_segments WHERE project_id=? ORDER BY segment_index",
            (project_id,),
        ).fetchall()]
        candidates = [dict(row) for row in conn.execute(
            """SELECT * FROM media_candidates
               WHERE project_id=? AND selected=1
               ORDER BY story_id,media_type,created_at""",
            (project_id,),
        ).fetchall()]
        current_stories = selected_story_packet(conn, project_id)
        historical_stories = _load_historical_voice_stories(conn, project_id, voice_rows)
        resolved_voice_rows, reconciliation = _reconcile_voice_story_rows(
            voice_rows,
            current_stories,
            historical_stories,
        )
        resolved_voice_rows = _apply_reserved_narration_tails(conn, resolved_voice_rows)

    prerequisites = _resolve_prerequisites(resolved_voice_rows, candidates)
    prerequisites["story_id_reconciliation"] = reconciliation
    prerequisites["missing_story_details"] = _resolve_missing_story_details(
        prerequisites["stories_missing_downloaded_media"],
        resolved_voice_rows,
        current_stories,
        historical_stories,
        reconciliation,
    )
    current_signature = _resolve_input_signature(resolved_voice_rows, candidates)
    root = Path(project["root_path"])
    plan_path = root / "timing" / "resolve_plan.json"
    manifest_path = root / "resolve" / "package_manifest.json"

    if not plan_path.exists():
        return {
            "ready": False,
            "stale": False,
            "plan": None,
            "files": [],
            "prerequisites": prerequisites,
            "message": "Generate the Resolve Plan after approved voice timing and downloaded selected media are ready.",
        }

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:
        plan = None

    files = []
    for relative in (
        "resolve/news_timeline.otio",
        "resolve/voice_timing.csv",
        "resolve/media_timing.csv",
        "resolve/package_manifest.json",
        "resolve/README.md",
        "timing/resolve_plan.json",
    ):
        path = root / relative
        files.append({
            "name": Path(relative).name,
            "relative_path": relative,
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() else 0,
        })

    package_signature = str((plan or {}).get("input_signature") or "")
    stale = not package_signature or package_signature != current_signature
    files_complete = bool(plan and manifest_path.exists() and all(item["exists"] for item in files))
    ready = bool(files_complete and prerequisites["ready"] and not stale)

    message = ""
    if prerequisites["voice_pending"]:
        message = f"{prerequisites['voice_pending']} voice segment(s) still need an approved aligned take in Step 4."
    elif prerequisites["stories_missing_downloaded_media"]:
        details = prerequisites.get("missing_story_details") or []
        missing_name = str((details[0] if details else {}).get("title") or "").strip()
        suffix = f" Missing: {missing_name}." if missing_name else ""
        message = (
            f"{len(prerequisites['stories_missing_downloaded_media'])} narrated story/stories could not be matched to downloaded selected media."
            + suffix
        )
    elif not prerequisites["selected_downloaded"]:
        message = "Select and download media in Steps 5–6 before Resolve planning."
    elif stale:
        message = "The existing Resolve package is from an older voice/media state. Regenerate it before importing into Resolve."
    elif not files_complete:
        message = "The Resolve package is incomplete. Regenerate it."

    return {
        "ready": ready,
        "stale": stale,
        "plan": plan if ready else None,
        "files": files,
        "prerequisites": prerequisites,
        "resolve_folder": str(root / "resolve"),
        "message": message,
    }


@app.post("/api/projects/{project_id}/resolve-plan/generate")
def generate_resolve_plan(project_id: str):
    with db() as conn:
        project = project_or_404(conn, project_id)
        voice_rows = [dict(row) for row in conn.execute(
            """SELECT * FROM voice_segments
               WHERE project_id=? ORDER BY segment_index""",
            (project_id,),
        ).fetchall()]
        candidates = [dict(row) for row in conn.execute(
            """SELECT * FROM media_candidates
               WHERE project_id=? AND selected=1
               ORDER BY story_id,media_type,created_at""",
            (project_id,),
        ).fetchall()]
        current_stories = selected_story_packet(conn, project_id)
        historical_stories = _load_historical_voice_stories(conn, project_id, voice_rows)
        resolved_voice_rows, reconciliation = _reconcile_voice_story_rows(
            voice_rows,
            current_stories,
            historical_stories,
        )
        resolved_voice_rows = _apply_reserved_narration_tails(conn, resolved_voice_rows)

    prerequisites = _resolve_prerequisites(resolved_voice_rows, candidates)
    prerequisites["story_id_reconciliation"] = reconciliation
    prerequisites["missing_story_details"] = _resolve_missing_story_details(
        prerequisites["stories_missing_downloaded_media"],
        resolved_voice_rows,
        current_stories,
        historical_stories,
        reconciliation,
    )
    if not voice_rows:
        raise HTTPException(400, "Generate the narrator voice first.")
    if prerequisites["voice_pending"]:
        raise HTTPException(
            400,
            f"{prerequisites['voice_pending']} voice segment(s) still need an approved aligned take in Step 4.",
        )
    if not candidates:
        raise HTTPException(400, "Select and download media before generating the Resolve Plan.")

    missing_media = [
        row for row in candidates
        if row.get("download_status") != "downloaded" or not row.get("stored_path")
    ]
    if missing_media:
        raise HTTPException(
            400,
            f"{len(missing_media)} selected media item(s) have not been downloaded yet.",
        )
    if prerequisites["stories_missing_downloaded_media"]:
        details = prerequisites.get("missing_story_details") or []
        first = details[0] if details else {}
        label = str(first.get("title") or first.get("story_id") or "unknown story")
        segments = ", ".join(str(x) for x in first.get("segment_indexes") or [])
        segment_note = f" (voice segment(s) {segments})" if segments else ""
        raise HTTPException(
            400,
            f"{len(prerequisites['stories_missing_downloaded_media'])} narrated story/stories could not be matched to downloaded selected media. "
            f"Missing mapping: {label}{segment_note}.",
        )

    try:
        plan = build_edit_plan(project, resolved_voice_rows, candidates, fps=30)
        if not plan.get("visual_clips"):
            raise RuntimeError(
                "No visual clips were planned. Return to Media Sources and Downloads before generating Resolve."
            )
        plan["input_signature"] = _resolve_input_signature(resolved_voice_rows, candidates)
        plan["story_id_reconciliation"] = reconciliation
        files = write_resolve_package(Path(project["root_path"]), plan)
    except Exception as exc:
        raise HTTPException(400, f"Could not build Resolve package: {exc}") from exc

    with db() as conn:
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        save_manifest(conn, project_id)
    return {
        "ok": True,
        "plan": plan,
        "files": files,
        "warning_count": len(plan.get("warnings") or []),
    }


@app.post("/api/projects/{project_id}/resolve-plan/open-folder")
def open_resolve_plan_folder(project_id: str):
    with db() as conn:
        project = project_or_404(conn, project_id)
    resolve_dir = Path(project["root_path"]) / "resolve"
    resolve_dir.mkdir(parents=True, exist_ok=True)
    reveal_in_file_manager(resolve_dir)
    return {"ok": True, "path": str(resolve_dir)}


@app.get("/api/settings")
def get_settings():
    return {"ai": masked_status(), "local_providers": all_statuses()}


class SettingsBody(BaseModel):
    research_provider: str = "codex_local"
    research_model: str = "default"
    writer_provider: str = "codex_local"
    writer_model: str = "default"
    reviewer_provider: str = "claude_local"
    reviewer_model: str = "default"
    prefer_api_providers: bool = False


@app.put("/api/settings")
def put_settings(body: SettingsBody):
    return save_ai_settings(body.model_dump())


class KeyBody(BaseModel):
    provider: str
    key: str


@app.post("/api/settings/api-key")
def save_key(body: KeyBody):
    try:
        set_api_key(body.provider, body.key)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/settings/api-key/{provider}")
def remove_key(provider: str):
    delete_api_key(provider)
    return {"ok": True}


class ProviderBody(BaseModel):
    provider: str


@app.post("/api/local-providers/login")
def login_provider(body: ProviderBody):
    try:
        return launch_login(body.provider)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/local-providers/test")
def test_provider(body: ProviderBody):
    try:
        text, provider, model = generate_text(body.provider, "default", "Reply with only OK.", "Connection test")
        return {"ok": True, "provider": provider, "model": model, "response": text[:80]}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
