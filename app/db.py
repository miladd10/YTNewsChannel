from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "ytnews.db"

PIPELINE = [
    (1, "research", "Research"),
    (2, "pick-news", "Pick News"),
    (3, "narration", "Narration"),
    (4, "media-sources", "Media Sources"),
    (5, "downloads", "Downloads"),
]


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'cinema',
                content_type TEXT NOT NULL DEFAULT 'weekly_news',
                language TEXT NOT NULL DEFAULT 'Persian',
                target_minutes INTEGER NOT NULL DEFAULT 15,
                date_start TEXT NOT NULL DEFAULT '',
                date_end TEXT NOT NULL DEFAULT '',
                geographic_focus TEXT NOT NULL DEFAULT 'Worldwide',
                editorial_focus TEXT NOT NULL DEFAULT 'Balanced',
                notes TEXT NOT NULL DEFAULT '',
                root_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                query_config_json TEXT NOT NULL DEFAULT '{}',
                article_count INTEGER NOT NULL DEFAULT 0,
                story_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS research_articles (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                snippet TEXT NOT NULL DEFAULT '',
                query_key TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(run_id) REFERENCES research_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS stories (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                canonical_title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                attention TEXT NOT NULL DEFAULT 'medium',
                importance TEXT NOT NULL DEFAULT 'medium',
                freshness TEXT NOT NULL DEFAULT 'current',
                confidence TEXT NOT NULL DEFAULT 'reported',
                visual_potential TEXT NOT NULL DEFAULT 'medium',
                uniqueness TEXT NOT NULL DEFAULT 'medium',
                rationale TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL DEFAULT 0,
                decision TEXT NOT NULL DEFAULT 'maybe',
                article_ids_json TEXT NOT NULL DEFAULT '[]',
                source_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(run_id) REFERENCES research_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS narrations (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                content TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                story_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                UNIQUE(project_id, version_number),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS media_plans (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                narration_id TEXT NOT NULL,
                content_json TEXT NOT NULL DEFAULT '{}',
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(narration_id) REFERENCES narrations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS media_candidates (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                story_id TEXT NOT NULL,
                media_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                page_url TEXT NOT NULL,
                asset_url TEXT NOT NULL DEFAULT '',
                thumbnail_url TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                duration TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                width INTEGER,
                height INTEGER,
                search_query TEXT NOT NULL DEFAULT '',
                clip_start_sec INTEGER,
                clip_end_sec INTEGER,
                shared_source INTEGER NOT NULL DEFAULT 0,
                selected INTEGER NOT NULL DEFAULT 0,
                download_status TEXT NOT NULL DEFAULT 'not_downloaded',
                stored_path TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                rights_status TEXT NOT NULL DEFAULT 'unverified',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(story_id) REFERENCES stories(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_articles_project_run ON research_articles(project_id, run_id);
            CREATE INDEX IF NOT EXISTS idx_stories_project_run ON stories(project_id, run_id);
            CREATE INDEX IF NOT EXISTS idx_stories_project_decision ON stories(project_id, decision);
            CREATE INDEX IF NOT EXISTS idx_media_candidates_story ON media_candidates(project_id, story_id, media_type);
            CREATE INDEX IF NOT EXISTS idx_media_candidates_selected ON media_candidates(project_id, selected);
            """
        )
        if not _column_exists(conn, "media_candidates", "clip_start_sec"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN clip_start_sec INTEGER")
        if not _column_exists(conn, "media_candidates", "clip_end_sec"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN clip_end_sec INTEGER")
        if not _column_exists(conn, "media_candidates", "shared_source"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN shared_source INTEGER NOT NULL DEFAULT 0")
