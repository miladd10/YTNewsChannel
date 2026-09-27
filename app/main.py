from __future__ import annotations

import json
import uuid
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
from .services.media import download_candidate, search_story_media
from .services.project_store import choose_folder, create_project_folder, reveal_in_file_manager, save_manifest
from .services.prompts import CINEMA_WEEKLY_SECTIONS, MEDIA_PLAN_SYSTEM, NARRATION_SYSTEM
from .services.research import ai_rank_stories, cluster_articles, fetch_google_news
from .services.secrets import delete_api_key, masked_status, save_ai_settings, set_api_key
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
    counts = {"articles": 0, "stories": 0, "included": 0, "narrations": 0, "media_plans": 0, "media_candidates": 0, "media_selected": 0, "media_downloaded": 0}
    if run_id:
        counts["articles"] = conn.execute("SELECT COUNT(*) c FROM research_articles WHERE run_id=?", (run_id,)).fetchone()["c"]
        counts["stories"] = conn.execute("SELECT COUNT(*) c FROM stories WHERE run_id=?", (run_id,)).fetchone()["c"]
        counts["included"] = conn.execute("SELECT COUNT(*) c FROM stories WHERE run_id=? AND decision='include'", (run_id,)).fetchone()["c"]
    counts["narrations"] = conn.execute("SELECT COUNT(*) c FROM narrations WHERE project_id=?", (project_id,)).fetchone()["c"]
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
                id,name,channel,content_type,language,target_minutes,date_start,date_end,
                geographic_focus,editorial_focus,notes,root_path,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                project_id, body.name.strip(), body.channel, body.content_type, body.language,
                body.target_minutes, body.date_start or start, body.date_end or end,
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
    allowed = {"name","language","target_minutes","date_start","date_end","geographic_focus","editorial_focus","notes"}
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

    articles, diagnostics = fetch_google_news(project["date_start"], project["date_end"])
    if not articles:
        errors = "; ".join(x.get("error", "") for x in diagnostics if not x.get("ok"))
        raise HTTPException(502, f"Research returned no articles. {errors}".strip())

    stories = cluster_articles(articles)
    provider = body.provider or masked_status().get("research_provider", "codex_local")
    model = body.model or masked_status().get("research_model", "default")
    ai_error = ""
    actual_provider, actual_model = provider, model
    if body.ai_rank:
        try:
            stories, actual_provider, actual_model = ai_rank_stories(stories, project, provider, model)
        except Exception as exc:
            ai_error = str(exc)

    run_id = str(uuid.uuid4())
    stamp = now()
    query_config = {"diagnostics": diagnostics, "ai_rank_requested": body.ai_rank, "ai_rank_error": ai_error}
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
                    confidence,visual_potential,uniqueness,rationale,score,decision,article_ids_json,source_count,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    story["id"], project_id, run_id, story["canonical_title"], story["summary"], story["category"],
                    story["attention"], story["importance"], story["freshness"], story["confidence"],
                    story["visual_potential"], story["uniqueness"], story["rationale"], story["score"], story["decision"],
                    json.dumps(story["article_ids"]), story["source_count"], stamp, stamp,
                ),
            )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        root = Path(project["root_path"])
        raw_file = root / "research" / "raw" / f"{run_id}.json"
        raw_file.write_text(json.dumps({"articles": articles, "diagnostics": diagnostics}, indent=2, ensure_ascii=False), encoding="utf-8")
        story_file = root / "research" / "stories" / f"{run_id}.json"
        story_file.write_text(json.dumps(stories, indent=2, ensure_ascii=False), encoding="utf-8")
        save_manifest(conn, project_id)

    return {"run_id": run_id, "article_count": len(articles), "story_count": len(stories), "ai_rank_error": ai_error, "provider": actual_provider, "model": actual_model}


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
            if ids:
                placeholders = ",".join("?" for _ in ids)
                article_rows = conn.execute(
                    f"SELECT id,title,url,source,published_at,category FROM research_articles WHERE id IN ({placeholders}) ORDER BY published_at DESC", ids
                ).fetchall()
                item["articles"] = [dict(x) for x in article_rows]
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
        row = conn.execute("SELECT 1 FROM stories WHERE id=? AND project_id=?", (story_id, project_id)).fetchone()
        if not row:
            raise HTTPException(404, "Story not found")
        conn.execute("UPDATE stories SET decision=?,updated_at=? WHERE id=?", (decision, now(), story_id))
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        save_manifest(conn, project_id)
    return {"ok": True, "decision": decision}


class GenerateBody(BaseModel):
    provider: str | None = None
    model: str | None = None
    instructions: str = ""


def selected_story_packet(conn, project_id: str) -> list[dict]:
    run_id = latest_run_id(conn, project_id)
    if not run_id:
        return []
    stories = []
    for row in conn.execute("SELECT * FROM stories WHERE run_id=? AND decision='include' ORDER BY score DESC", (run_id,)).fetchall():
        item = dict(row)
        article_ids = json.loads(item.pop("article_ids_json") or "[]")
        articles = []
        if article_ids:
            placeholders = ",".join("?" for _ in article_ids)
            articles = [dict(x) for x in conn.execute(
                f"SELECT title,url,source,published_at,snippet FROM research_articles WHERE id IN ({placeholders})", article_ids
            ).fetchall()]
        item["articles"] = articles
        stories.append(item)
    return stories


@app.post("/api/projects/{project_id}/narration")
def generate_narration(project_id: str, body: GenerateBody):
    settings = masked_status()
    provider = body.provider or settings.get("writer_provider", "codex_local")
    model = body.model or settings.get("writer_model", "default")
    with db() as conn:
        project = project_or_404(conn, project_id)
        stories = selected_story_packet(conn, project_id)
    if not stories:
        raise HTTPException(400, "Include at least one story before generating narration.")
    packet = {
        "project": project,
        "weekly_section_template": CINEMA_WEEKLY_SECTIONS,
        "selected_stories": stories,
        "additional_instructions": body.instructions,
    }
    try:
        text, actual_provider, actual_model = generate_text(provider, model, NARRATION_SYSTEM, json.dumps(packet, ensure_ascii=False))
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    narration_id = str(uuid.uuid4())
    stamp = now()
    with db() as conn:
        version = conn.execute("SELECT COALESCE(MAX(version_number),0)+1 v FROM narrations WHERE project_id=?", (project_id,)).fetchone()["v"]
        conn.execute(
            "INSERT INTO narrations(id,project_id,version_number,content,provider,model,story_ids_json,created_at,approved) VALUES (?,?,?,?,?,?,?,?,0)",
            (narration_id, project_id, version, text, actual_provider, actual_model, json.dumps([s["id"] for s in stories]), stamp),
        )
        root = Path(project["root_path"])
        (root / "narration" / f"v{version:02d}.md").write_text(text, encoding="utf-8")
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        save_manifest(conn, project_id)
    return {"id": narration_id, "version_number": version, "content": text, "provider": actual_provider, "model": actual_model}


@app.get("/api/projects/{project_id}/narrations")
def list_narrations(project_id: str):
    with db() as conn:
        project_or_404(conn, project_id)
        return [dict(row) for row in conn.execute("SELECT * FROM narrations WHERE project_id=? ORDER BY version_number DESC", (project_id,)).fetchall()]


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


class MediaSearchBody(BaseModel):
    refresh: bool = True
    max_images_per_story: int = Field(default=3, ge=1, le=8)
    max_videos_per_story: int = Field(default=8, ge=1, le=16)


@app.post("/api/projects/{project_id}/media/search")
def search_included_story_media(project_id: str, body: MediaSearchBody):
    with db() as conn:
        project = project_or_404(conn, project_id)
        stories = selected_story_packet(conn, project_id)
    if not stories:
        raise HTTPException(400, "Include at least one story before searching for media.")

    diagnostics = []
    total_added = 0
    stamp = now()
    youtube_query_cache: dict[str, list[dict]] = {}
    for story in stories:
        candidates, errors = search_story_media(
            story,
            max_images=body.max_images_per_story,
            max_videos=body.max_videos_per_story,
            query_cache=youtube_query_cache,
        )
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
                        duration,published_at,width,height,search_query,selected,download_status,stored_path,error,
                        rights_status,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        item["id"], project_id, story["id"], item["media_type"], item["title"], item["page_url"],
                        item["asset_url"], item["thumbnail_url"], item["source"], item["provider"], item["duration"],
                        item["published_at"], item["width"], item["height"], item["search_query"], 0, "not_downloaded",
                        "", "", "unverified", stamp, stamp,
                    ),
                )
                existing.add(key)
                added += 1
            total_added += added
        diagnostics.append({
            "story_id": story["id"],
            "story_title": story["canonical_title"],
            "found": len(candidates),
            "added": added,
            "errors": errors,
        })

    with db() as conn:
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        save_manifest(conn, project_id)
    return {"ok": True, "stories": len(stories), "added": total_added, "diagnostics": diagnostics}


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
            output.append({
                "story": {
                    "id": story["id"],
                    "title": story["canonical_title"],
                    "summary": story.get("summary", ""),
                    "category": story.get("category", ""),
                    "articles": story.get("articles", []),
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
    for candidate in candidates:
        if candidate.get("download_status") == "downloaded" and candidate.get("stored_path"):
            results.append({"id": candidate["id"], "ok": True, "stored_path": candidate["stored_path"], "already_downloaded": True})
            continue
        try:
            path = download_candidate(candidate, root, candidate["story_title"])
            relative = path.resolve().relative_to(root.resolve()).as_posix()
            with db() as conn:
                conn.execute(
                    "UPDATE media_candidates SET download_status='downloaded',stored_path=?,error='',updated_at=? WHERE id=?",
                    (relative, now(), candidate["id"]),
                )
            results.append({"id": candidate["id"], "ok": True, "stored_path": relative})
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
