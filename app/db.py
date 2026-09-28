from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "ytnews.db"

PIPELINE = [
    (1, "research", "Format Research"),
    (2, "pick-news", "Section Selection"),
    (3, "narration", "Narration Writer"),
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
                section_fit TEXT NOT NULL DEFAULT 'medium',
                article_ids_json TEXT NOT NULL DEFAULT '[]',
                source_count INTEGER NOT NULL DEFAULT 0,
                source_platforms_json TEXT NOT NULL DEFAULT '[]',
                source_kinds_json TEXT NOT NULL DEFAULT '[]',
                reddit_only INTEGER NOT NULL DEFAULT 0,
                primary_social_count INTEGER NOT NULL DEFAULT 0,
                news_hook TEXT NOT NULL DEFAULT '',
                news_hook_date TEXT NOT NULL DEFAULT '',
                verification_status TEXT NOT NULL DEFAULT 'needs_verification',
                verification_notes TEXT NOT NULL DEFAULT '',
                temporal_gate TEXT NOT NULL DEFAULT 'warning',
                verification_gate TEXT NOT NULL DEFAULT 'fail',
                in_window_source_count INTEGER NOT NULL DEFAULT 0,
                background_source_count INTEGER NOT NULL DEFAULT 0,
                undated_source_count INTEGER NOT NULL DEFAULT 0,
                independent_source_count INTEGER NOT NULL DEFAULT 0,
                current_non_reddit_source_count INTEGER NOT NULL DEFAULT 0,
                current_primary_social_count INTEGER NOT NULL DEFAULT 0,
                familiarity_needed INTEGER NOT NULL DEFAULT 0,
                familiarity_anchor TEXT NOT NULL DEFAULT '',
                search_subject TEXT NOT NULL DEFAULT '',
                spice_json TEXT NOT NULL DEFAULT '[]',
                spice_source_ids_json TEXT NOT NULL DEFAULT '[]',
                visual_context_json TEXT NOT NULL DEFAULT '[]',
                context_searched_at TEXT NOT NULL DEFAULT '',
                context_search_count INTEGER NOT NULL DEFAULT 0,
                context_search_error TEXT NOT NULL DEFAULT '',
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
                fact_check_status TEXT NOT NULL DEFAULT 'not_run',
                fact_check_issue_count INTEGER NOT NULL DEFAULT 0,
                fact_check_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(project_id, version_number),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS style_transcripts (
                id TEXT PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT 'cinema',
                content_type TEXT NOT NULL DEFAULT 'weekly_news',
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                char_count INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_style_transcripts_format
                ON style_transcripts(channel, content_type, enabled);

            CREATE TABLE IF NOT EXISTS style_profiles (
                id TEXT PRIMARY KEY,
                channel TEXT NOT NULL DEFAULT 'cinema',
                content_type TEXT NOT NULL DEFAULT 'weekly_news',
                corpus_hash TEXT NOT NULL DEFAULT '',
                profile_text TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                transcript_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(channel, content_type)
            );

            CREATE INDEX IF NOT EXISTS idx_style_profiles_format
                ON style_profiles(channel, content_type);

            CREATE TABLE IF NOT EXISTS narration_reviews (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                narration_id TEXT NOT NULL,
                review_number INTEGER NOT NULL,
                content TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                gate_status TEXT NOT NULL DEFAULT 'revision_required',
                blocking_count INTEGER NOT NULL DEFAULT 0,
                major_count INTEGER NOT NULL DEFAULT 0,
                minor_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(narration_id, review_number),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(narration_id) REFERENCES narrations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_narration_reviews_project
                ON narration_reviews(project_id, created_at);

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
                coverage_label TEXT NOT NULL DEFAULT '',
                coverage_kind TEXT NOT NULL DEFAULT '',
                coverage_group TEXT NOT NULL DEFAULT '',
                coverage_cue TEXT NOT NULL DEFAULT '',
                coverage_reason TEXT NOT NULL DEFAULT '',
                layout_hint TEXT NOT NULL DEFAULT 'single',
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
        if not _column_exists(conn, "stories", "visual_context_json"):
            conn.execute("ALTER TABLE stories ADD COLUMN visual_context_json TEXT NOT NULL DEFAULT '[]'")
        if not _column_exists(conn, "stories", "context_searched_at"):
            conn.execute("ALTER TABLE stories ADD COLUMN context_searched_at TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "stories", "context_search_count"):
            conn.execute("ALTER TABLE stories ADD COLUMN context_search_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "context_search_error"):
            conn.execute("ALTER TABLE stories ADD COLUMN context_search_error TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "stories", "search_subject"):
            conn.execute("ALTER TABLE stories ADD COLUMN search_subject TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "stories", "spice_json"):
            conn.execute("ALTER TABLE stories ADD COLUMN spice_json TEXT NOT NULL DEFAULT '[]'")
        if not _column_exists(conn, "stories", "spice_source_ids_json"):
            conn.execute("ALTER TABLE stories ADD COLUMN spice_source_ids_json TEXT NOT NULL DEFAULT '[]'")
        if not _column_exists(conn, "stories", "familiarity_needed"):
            conn.execute("ALTER TABLE stories ADD COLUMN familiarity_needed INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "familiarity_anchor"):
            conn.execute("ALTER TABLE stories ADD COLUMN familiarity_anchor TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "stories", "news_hook"):
            conn.execute("ALTER TABLE stories ADD COLUMN news_hook TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "stories", "news_hook_date"):
            conn.execute("ALTER TABLE stories ADD COLUMN news_hook_date TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "stories", "verification_status"):
            conn.execute("ALTER TABLE stories ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'needs_verification'")
        if not _column_exists(conn, "stories", "verification_notes"):
            conn.execute("ALTER TABLE stories ADD COLUMN verification_notes TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "stories", "temporal_gate"):
            conn.execute("ALTER TABLE stories ADD COLUMN temporal_gate TEXT NOT NULL DEFAULT 'warning'")
        if not _column_exists(conn, "stories", "verification_gate"):
            conn.execute("ALTER TABLE stories ADD COLUMN verification_gate TEXT NOT NULL DEFAULT 'fail'")
        if not _column_exists(conn, "stories", "in_window_source_count"):
            conn.execute("ALTER TABLE stories ADD COLUMN in_window_source_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "background_source_count"):
            conn.execute("ALTER TABLE stories ADD COLUMN background_source_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "undated_source_count"):
            conn.execute("ALTER TABLE stories ADD COLUMN undated_source_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "independent_source_count"):
            conn.execute("ALTER TABLE stories ADD COLUMN independent_source_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "current_non_reddit_source_count"):
            conn.execute("ALTER TABLE stories ADD COLUMN current_non_reddit_source_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "current_primary_social_count"):
            conn.execute("ALTER TABLE stories ADD COLUMN current_primary_social_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "section_fit"):
            conn.execute("ALTER TABLE stories ADD COLUMN section_fit TEXT NOT NULL DEFAULT 'medium'")
        if not _column_exists(conn, "stories", "source_platforms_json"):
            conn.execute("ALTER TABLE stories ADD COLUMN source_platforms_json TEXT NOT NULL DEFAULT '[]'")
        if not _column_exists(conn, "stories", "source_kinds_json"):
            conn.execute("ALTER TABLE stories ADD COLUMN source_kinds_json TEXT NOT NULL DEFAULT '[]'")
        if not _column_exists(conn, "stories", "reddit_only"):
            conn.execute("ALTER TABLE stories ADD COLUMN reddit_only INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "stories", "primary_social_count"):
            conn.execute("ALTER TABLE stories ADD COLUMN primary_social_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "narrations", "fact_check_status"):
            conn.execute("ALTER TABLE narrations ADD COLUMN fact_check_status TEXT NOT NULL DEFAULT 'not_run'")
        if not _column_exists(conn, "narrations", "fact_check_issue_count"):
            conn.execute("ALTER TABLE narrations ADD COLUMN fact_check_issue_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "narrations", "fact_check_json"):
            conn.execute("ALTER TABLE narrations ADD COLUMN fact_check_json TEXT NOT NULL DEFAULT '{}'")
        if not _column_exists(conn, "narrations", "parent_narration_id"):
            conn.execute("ALTER TABLE narrations ADD COLUMN parent_narration_id TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "narrations", "revision_review_id"):
            conn.execute("ALTER TABLE narrations ADD COLUMN revision_review_id TEXT NOT NULL DEFAULT ''")
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
        if not _column_exists(conn, "media_candidates", "coverage_label"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN coverage_label TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "media_candidates", "coverage_kind"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN coverage_kind TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "media_candidates", "coverage_group"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN coverage_group TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "media_candidates", "coverage_cue"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN coverage_cue TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "media_candidates", "coverage_reason"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN coverage_reason TEXT NOT NULL DEFAULT ''")
        if not _column_exists(conn, "media_candidates", "layout_hint"):
            conn.execute("ALTER TABLE media_candidates ADD COLUMN layout_hint TEXT NOT NULL DEFAULT 'single'")
