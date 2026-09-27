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
    (4, "voice", "Voice"),
    (5, "media-sources", "Media Sources"),
    (6, "downloads", "Downloads"),
    (7, "resolve-plan", "Resolve Plan"),
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
                media_chunk_minutes REAL NOT NULL DEFAULT 1.0,
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

            CREATE TABLE IF NOT EXISTS voice_settings (
                project_id TEXT PRIMARY KEY,
                voice_id TEXT NOT NULL DEFAULT '',
                voice_name TEXT NOT NULL DEFAULT '',
                model_id TEXT NOT NULL DEFAULT 'eleven_v3',
                output_format TEXT NOT NULL DEFAULT 'mp3_44100_192',
                prepared_narration_id TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS voice_segments (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                narration_id TEXT NOT NULL,
                story_id TEXT NOT NULL DEFAULT '',
                segment_index INTEGER NOT NULL,
                source_text TEXT NOT NULL,
                performance_text TEXT NOT NULL DEFAULT '',
                voice_id TEXT NOT NULL DEFAULT '',
                audio_path TEXT NOT NULL DEFAULT '',
                duration_seconds REAL,
                alignment_json TEXT NOT NULL DEFAULT '{}',
                audio_status TEXT NOT NULL DEFAULT 'pending',
                take1_path TEXT NOT NULL DEFAULT '',
                take2_path TEXT NOT NULL DEFAULT '',
                selected_take INTEGER NOT NULL DEFAULT 0,
                approval_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(narration_id) REFERENCES narrations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_voice_segments_project ON voice_segments(project_id, segment_index);
            CREATE INDEX IF NOT EXISTS idx_voice_segments_story ON voice_segments(project_id, story_id);

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
                target_duration_sec REAL,
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
        if not _column_exists(conn, "projects", "media_chunk_minutes"):
            conn.execute("ALTER TABLE projects ADD COLUMN media_chunk_minutes REAL NOT NULL DEFAULT 1.0")
        if not _column_exists(conn, "voice_segments", "take1_path"):
            conn.execute("ALTER TABLE voice_segments ADD COLUMN take1_path TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "voice_segments", "take2_path"):
            conn.execute("ALTER TABLE voice_segments ADD COLUMN take2_path TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "voice_segments", "selected_take"):
            conn.execute("ALTER TABLE voice_segments ADD COLUMN selected_take INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "voice_segments", "approval_status"):
            conn.execute("ALTER TABLE voice_segments ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'pending'")
        # v0.3.1 introduced explicit Take 1 / Take 2 approval. Preserve
        # previously generated + aligned narration instead of forcing users to
        # spend ElevenLabs credits again. Only promote legacy audio when the
        # actual project file still exists.
        legacy_rows = conn.execute(
            """SELECT v.id,v.audio_path,p.root_path
               FROM voice_segments v
               JOIN projects p ON p.id=v.project_id
               WHERE v.audio_status='aligned'
                 AND v.audio_path<>''
                 AND COALESCE(v.approval_status,'pending')<>'approved'
                 AND COALESCE(v.take1_path,'')=''"""
        ).fetchall()
        for row in legacy_rows:
            try:
                audio_file = (Path(row["root_path"]) / row["audio_path"]).resolve()
                project_root = Path(row["root_path"]).resolve()
                if project_root in audio_file.parents and audio_file.exists() and audio_file.is_file():
                    conn.execute(
                        """UPDATE voice_segments
                           SET take1_path=audio_path,selected_take=1,approval_status='approved'
                           WHERE id=?""",
                        (row["id"],),
                    )
            except Exception:
                pass

        if not _column_exists(conn, "media_candidates", "clip_start_sec"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN clip_start_sec INTEGER")
        if not _column_exists(conn, "media_candidates", "clip_end_sec"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN clip_end_sec INTEGER")
        if not _column_exists(conn, "media_candidates", "target_duration_sec"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN target_duration_sec REAL")
        if not _column_exists(conn, "media_candidates", "shared_source"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN shared_source INTEGER NOT NULL DEFAULT 0")
