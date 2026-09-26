"""
project003 — SQLite database initialization module.

Schema source of truth: docs/DATABASE_SCHEMA.md
This module is imported by dashboard, watcher, and processor.

Conventions (from DATABASE_SCHEMA.md):
- WAL journal mode
- Foreign keys ON
- Synchronous = NORMAL (safe with WAL)
- All timestamps stored as ISO-8601 UTC strings
- Booleans stored as INTEGER (0/1)
- JSON stored as TEXT
"""
from __future__ import annotations

import os
import sqlite3
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "/data/app.db")


# ---------------------------------------------------------------------------
# Schema DDL — keep in sync with docs/DATABASE_SCHEMA.md
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipelines (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    download_profile_id INTEGER REFERENCES download_profiles(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS download_profiles (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    -- Per-field knobs (NULL/empty/0 means "use yt-dlp default"):
    max_height      INTEGER NOT NULL DEFAULT 0,        -- e.g. 1080; 0 = no cap
    container       TEXT    NOT NULL DEFAULT 'mp4',    -- mp4/webm/mkv/best
    video_codec     TEXT    NOT NULL DEFAULT 'avc1',   -- avc1/vp9/av01/any
    audio_codec     TEXT    NOT NULL DEFAULT 'm4a',    -- m4a/opus/mp3/any
    audio_only      INTEGER NOT NULL DEFAULT 0,
    write_subs      INTEGER NOT NULL DEFAULT 1,
    write_auto_subs INTEGER NOT NULL DEFAULT 1,
    sub_langs       TEXT    NOT NULL DEFAULT 'en',     -- comma-separated
    embed_subs      INTEGER NOT NULL DEFAULT 0,
    write_thumbnail INTEGER NOT NULL DEFAULT 1,
    embed_thumbnail INTEGER NOT NULL DEFAULT 0,
    embed_chapters  INTEGER NOT NULL DEFAULT 0,
    skip_shorts     INTEGER NOT NULL DEFAULT 0,        -- skip videos < shorts_max_seconds
    shorts_max_seconds INTEGER NOT NULL DEFAULT 60,
    skip_live       INTEGER NOT NULL DEFAULT 1,        -- skip live streams + premieres
    custom_format   TEXT    NOT NULL DEFAULT '',       -- escape hatch: raw yt-dlp -f string
    is_default      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS channels (
    id                  INTEGER PRIMARY KEY,
    pipeline_id         INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    name                TEXT    NOT NULL,
    channel_id          TEXT    NOT NULL,
    url                 TEXT    NOT NULL,
    mode                TEXT    NOT NULL DEFAULT 'monitor',
    backfill_complete   INTEGER NOT NULL DEFAULT 0,
    backfill_queue      TEXT    NOT NULL DEFAULT '[]',
    backfill_entry_map  TEXT    NOT NULL DEFAULT '{}',
    daily_limit         INTEGER NOT NULL DEFAULT 10,
    download_priority   INTEGER NOT NULL DEFAULT 100,
    uploads_today       INTEGER NOT NULL DEFAULT 0,
    uploads_today_date  TEXT    NOT NULL DEFAULT '',
    last_check          TEXT    NOT NULL DEFAULT '1970-01-01T00:00:00',
    active              INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_channels_pipeline ON channels(pipeline_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_channel_id ON channels(channel_id);

CREATE TABLE IF NOT EXISTS destinations (
    id              INTEGER PRIMARY KEY,
    pipeline_id     INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    platform        TEXT    NOT NULL,
    label           TEXT    NOT NULL DEFAULT '',
    n8n_webhook_url TEXT    NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    default_privacy TEXT    NOT NULL DEFAULT 'unlisted',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_destinations_pipeline ON destinations(pipeline_id);

CREATE TABLE IF NOT EXISTS processing_steps (
    id             INTEGER PRIMARY KEY,
    pipeline_id    INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    destination_id INTEGER REFERENCES destinations(id) ON DELETE CASCADE,
    step_order     INTEGER NOT NULL DEFAULT 0,
    step_type      TEXT    NOT NULL,
    params         TEXT    NOT NULL DEFAULT '{}',
    enabled        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_steps_pipeline ON processing_steps(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_steps_destination ON processing_steps(destination_id);

CREATE TABLE IF NOT EXISTS videos (
    id                   INTEGER PRIMARY KEY,
    channel_id           INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    youtube_video_id     TEXT    NOT NULL,
    original_title       TEXT    NOT NULL DEFAULT '',
    original_description TEXT    NOT NULL DEFAULT '',
    duration             INTEGER NOT NULL DEFAULT 0,
    source_url           TEXT    NOT NULL DEFAULT '',
    thumbnail_url        TEXT    NOT NULL DEFAULT '',
    published_at         TEXT    NOT NULL DEFAULT '',
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_youtube_id ON videos(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);

CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY,
    video_id         INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    pipeline_id      INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    status           TEXT    NOT NULL DEFAULT 'pending',
    source_file_path TEXT    NOT NULL DEFAULT '',
    error_message    TEXT    NOT NULL DEFAULT '',
    retry_count      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_pipeline ON jobs(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_jobs_video ON jobs(video_id);

CREATE TRIGGER IF NOT EXISTS jobs_updated_at
AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')
    WHERE id = NEW.id;
END;

CREATE TABLE IF NOT EXISTS job_outputs (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    file_path       TEXT    NOT NULL,
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_job_outputs_job ON job_outputs(job_id);

CREATE TABLE IF NOT EXISTS upload_results (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    platform        TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    upload_url      TEXT    NOT NULL DEFAULT '',
    error_message   TEXT    NOT NULL DEFAULT '',
    ai_used         INTEGER NOT NULL DEFAULT 0,
    ai_title        TEXT    NOT NULL DEFAULT '',
    ai_description  TEXT    NOT NULL DEFAULT '',
    ai_tags         TEXT    NOT NULL DEFAULT '[]',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_upload_results_job ON upload_results(job_id);
CREATE INDEX IF NOT EXISTS idx_upload_results_status ON upload_results(status);

-- ----------------------------------------------------------------------
-- Real-time upload progress (one row per active upload).
-- Updated by the dashboard uploader thread on every chunk.
-- Removed when upload finishes (terminal row goes to upload_results).
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS upload_progress (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    platform        TEXT    NOT NULL DEFAULT 'youtube',
    title           TEXT    NOT NULL DEFAULT '',
    file_path       TEXT    NOT NULL DEFAULT '',
    bytes_total     INTEGER NOT NULL DEFAULT 0,
    bytes_uploaded  INTEGER NOT NULL DEFAULT 0,
    speed_bps       INTEGER NOT NULL DEFAULT 0,   -- bytes per second (rolling avg)
    eta_seconds     INTEGER NOT NULL DEFAULT 0,
    stage           TEXT    NOT NULL DEFAULT 'starting',
        -- starting | uploading | processing | done | failed | canceled
    youtube_video_id TEXT   NOT NULL DEFAULT '',
    error_message   TEXT    NOT NULL DEFAULT '',
    started_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_upload_progress_job_dest
    ON upload_progress(job_id, destination_id);

-- ----------------------------------------------------------------------
-- OAuth token storage (one row per platform/account).
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id            INTEGER PRIMARY KEY,
    platform      TEXT    NOT NULL,
    account_label TEXT    NOT NULL DEFAULT '',
    access_token  TEXT    NOT NULL,
    refresh_token TEXT    NOT NULL DEFAULT '',
    token_expiry  TEXT    NOT NULL DEFAULT '',
    scopes        TEXT    NOT NULL DEFAULT '',
    extra         TEXT    NOT NULL DEFAULT '{}',
    project_id    INTEGER,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
-- NOTE: legacy index idx_oauth_platform (UNIQUE on platform alone) is dropped
-- by the migration block below so we can store one token per (platform, project).
CREATE UNIQUE INDEX IF NOT EXISTS idx_oauth_platform_project
    ON oauth_tokens(platform, COALESCE(project_id, 0));

-- ----------------------------------------------------------------------
-- YouTube projects (Google Cloud OAuth clients) for quota rotation.
-- Each row is one client_id/client_secret pair. We rotate uploads across
-- active projects: when one hits its daily cap (default 6 uploads) the
-- next active project is used.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS youtube_projects (
    id              INTEGER PRIMARY KEY,
    label           TEXT    NOT NULL,
    client_id       TEXT    NOT NULL,
    client_secret   TEXT    NOT NULL,
    daily_cap       INTEGER NOT NULL DEFAULT 6,
    uploads_today   INTEGER NOT NULL DEFAULT 0,
    counter_date    TEXT    NOT NULL DEFAULT '',   -- YYYY-MM-DD (UTC)
    last_used_at    TEXT    NOT NULL DEFAULT '',
    quota_resets_at TEXT    NOT NULL DEFAULT '',   -- set when project hit quota
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_projects_client
    ON youtube_projects(client_id);

-- ----------------------------------------------------------------------
-- YouTube channels (UPLOAD TARGETS — distinct from `channels` which is
-- source channels we scrape). Each row represents a YouTube channel that
-- one or more youtube_projects rows are authorized to upload to. A single
-- Google account (Brand Account) may own multiple of these rows; one row
-- may be served by many projects (rotation pool).
--
-- Populated by oauth_youtube.exchange_code() after a successful auth and
-- by the one-shot startup backfill for legacy tokens.
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS youtube_channels (
    id                  INTEGER PRIMARY KEY,
    channel_id          TEXT    NOT NULL,            -- UCxxx (canonical)
    title               TEXT    NOT NULL DEFAULT '',
    thumbnail_url       TEXT    NOT NULL DEFAULT '',
    owner_email         TEXT    NOT NULL DEFAULT '', -- denormalized from userinfo
    owner_display_name  TEXT    NOT NULL DEFAULT '',
    default_privacy     TEXT    NOT NULL DEFAULT 'unlisted',
    default_category_id INTEGER NOT NULL DEFAULT 22,
    active              INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_channels_channel_id
    ON youtube_channels(channel_id);

-- ----------------------------------------------------------------------
-- Catalog & Backfill (FEATURE_CATALOG_AND_BACKFILL.md)
-- A "source" is a YouTube channel or playlist URL frozen as a curation
-- target. Catalog rows are the lazy-hydrated listing per source. The
-- ledger is the single global source of truth for "did we upload it?".
-- ----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY,
    kind            TEXT    NOT NULL CHECK (kind IN ('channel','playlist')),
    url             TEXT    NOT NULL,
    external_id     TEXT,                    -- UCxxxx or PLxxxx (canonical)
    name            TEXT    NOT NULL,
    pipeline_id     INTEGER REFERENCES pipelines(id) ON DELETE SET NULL,
    last_scanned_at TEXT,
    last_scan_error TEXT    NOT NULL DEFAULT '',
    total_known     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_external_id
    ON sources(external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS catalog_videos (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    video_id        TEXT    NOT NULL,        -- 11-char YouTube ID
    title           TEXT    NOT NULL DEFAULT '',
    duration_sec    INTEGER,
    upload_date     TEXT,                    -- 'YYYY-MM-DD'
    live_status     TEXT,                    -- not_live | was_live | is_upcoming | is_live
    thumbnail_url   TEXT,
    -- Hydrated lazily (NULL = not yet hydrated)
    description     TEXT,
    tags_json       TEXT,
    view_count      INTEGER,
    like_count      INTEGER,
    chapters_json   TEXT,
    age_limit       INTEGER,
    hydrated_at     TEXT,
    -- Personal flags
    starred         INTEGER NOT NULL DEFAULT 0,
    ignored         INTEGER NOT NULL DEFAULT 0,
    -- Lifecycle
    first_seen_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    last_seen_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    unavailable_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_source_video
    ON catalog_videos(source_id, video_id);
CREATE INDEX IF NOT EXISTS idx_catalog_source_uploaddate
    ON catalog_videos(source_id, upload_date DESC);
CREATE INDEX IF NOT EXISTS idx_catalog_video_id
    ON catalog_videos(video_id);

CREATE TABLE IF NOT EXISTS upload_ledger (
    id                   INTEGER PRIMARY KEY,
    video_id             TEXT    NOT NULL,        -- 11-char YouTube ID
    destination_id       INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    job_id               INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    status               TEXT    NOT NULL CHECK (status IN
                            ('queued','uploading','uploaded','failed','removed')),
    destination_video_id TEXT    NOT NULL DEFAULT '',
    destination_url      TEXT    NOT NULL DEFAULT '',
    uploaded_at          TEXT,
    error_message        TEXT    NOT NULL DEFAULT '',
    source_id            INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    triggered_by         TEXT    NOT NULL CHECK (triggered_by IN
                            ('cron','manual','backfill')),
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_video_dest
    ON upload_ledger(video_id, destination_id);
CREATE INDEX IF NOT EXISTS idx_ledger_video      ON upload_ledger(video_id);
CREATE INDEX IF NOT EXISTS idx_ledger_dest_when
    ON upload_ledger(destination_id, uploaded_at DESC);

CREATE TABLE IF NOT EXISTS destination_quota (
    destination_id     INTEGER PRIMARY KEY REFERENCES destinations(id) ON DELETE CASCADE,
    daily_max          INTEGER NOT NULL DEFAULT 6,
    quota_exceeded_at  TEXT,
    quota_resets_at    TEXT,
    updated_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

-- ----------------------------------------------------------------------
-- Routing rules: which (source, conditions) -> which destination/profile.
-- The router consults these to decide what to enqueue. First-match-wins
-- per (source, destination) when ordered by `priority` ASC.
-- A NULL source_id means the rule applies to ALL sources (global rule).
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS routing_rules (
    id             INTEGER PRIMARY KEY,
    source_id      INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    destination_id INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    profile_id     INTEGER REFERENCES download_profiles(id) ON DELETE SET NULL,
    priority       INTEGER NOT NULL DEFAULT 100,
    enabled        INTEGER NOT NULL DEFAULT 1,
    -- match conditions (NULL/empty/0 = "any"; all conditions AND'd)
    title_regex    TEXT    NOT NULL DEFAULT '',
    title_excludes TEXT    NOT NULL DEFAULT '',
    min_duration   INTEGER NOT NULL DEFAULT 0,
    max_duration   INTEGER NOT NULL DEFAULT 0,
    skip_shorts    INTEGER NOT NULL DEFAULT 0,
    skip_live      INTEGER NOT NULL DEFAULT 1,
    tags_any       TEXT    NOT NULL DEFAULT '',  -- JSON array; '' = no tag filter
    label          TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_rules_source_priority
    ON routing_rules(source_id, priority);
CREATE INDEX IF NOT EXISTS idx_rules_destination
    ON routing_rules(destination_id);

-- ---------------------------------------------------------------------------
-- worker_state: heartbeat / status registry for background workers
-- ---------------------------------------------------------------------------
-- Each row = one logical worker (uploader, downloader, scanner, dashboard, ...).
-- Workers upsert their row periodically. The dashboard header reads this
-- table to display "alive / idle / busy / stale" status. Strict CHECK on
-- status keeps the table tidy.
CREATE TABLE IF NOT EXISTS worker_state (
    worker_id   TEXT    PRIMARY KEY,           -- e.g. 'dashboard', 'uploader-1'
    kind        TEXT    NOT NULL DEFAULT '',   -- e.g. 'uploader', 'scanner'
    status      TEXT    NOT NULL DEFAULT 'idle'
                CHECK (status IN ('idle', 'busy', 'error', 'stopped')),
    detail      TEXT    NOT NULL DEFAULT '',   -- short human-readable note
    last_beat   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    started_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    pid         INTEGER NOT NULL DEFAULT 0,
    host        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_worker_state_kind ON worker_state(kind);

-- ---------------------------------------------------------------------------
-- download_queue: one row per video that needs to be downloaded.
-- ---------------------------------------------------------------------------
-- Decoupled from upload_ledger so a video destined for N platforms is
-- downloaded ONCE and reused. The router writes one download_queue row
-- (UNIQUE on video_id) alongside N upload_ledger rows. A future hydrator
-- consumes 'pending' rows, materializes a `jobs` row that the watcher
-- picks up, and on success marks the queue row 'complete'.
--
-- This is *additive* — existing pipelines keep working. Slice 4a only
-- writes to the table; downstream wiring lands in slice 4b.
CREATE TABLE IF NOT EXISTS download_queue (
    id           INTEGER PRIMARY KEY,
    video_id     TEXT    NOT NULL UNIQUE,        -- 11-char YouTube ID
    source_id    INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    profile_id   INTEGER REFERENCES download_profiles(id) ON DELETE SET NULL,
    job_id       INTEGER REFERENCES jobs(id) ON DELETE SET NULL,  -- set on hydrate
    status       TEXT    NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','hydrated','downloading',
                                   'complete','failed','cancelled')),
    triggered_by TEXT    NOT NULL DEFAULT 'cron'
                 CHECK (triggered_by IN ('cron','manual','backfill')),
    error_message TEXT   NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_dlq_status   ON download_queue(status);
CREATE INDEX IF NOT EXISTS idx_dlq_source   ON download_queue(source_id);
"""


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def get_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a SQLite connection with project conventions applied.

    - row_factory = sqlite3.Row (rows behave like dicts)
    - PRAGMA journal_mode = WAL
    - PRAGMA foreign_keys = ON
    - PRAGMA synchronous = NORMAL
    """
    path = db_path or DB_PATH
    # Make sure the directory exists when running locally (not /data in container)
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; we use explicit BEGIN where needed
    conn.row_factory = sqlite3.Row
    # WAL gives best concurrency on Linux but its -shm shared-memory file
    # cannot be mmap'd on Docker Desktop bind mounts (Windows hosts), causing
    # "unable to open database file" intermittently. We default to journal
    # mode DELETE for portability; bump synchronous to NORMAL.
    try:
        conn.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError:
        pass
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Create all tables, indexes, and triggers if they do not already exist.

    Idempotent — safe to call on every container startup.
    """
    conn = get_db(db_path)
    try:
        try:
            conn.executescript(SCHEMA_SQL)
        except sqlite3.OperationalError as e:
            # If the schema already exists and the DB is open by other writers,
            # executescript can fail on Docker Desktop bind mounts. Verify the
            # schema is present; only re-raise if a critical table is missing.
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
            if not row:
                raise RuntimeError(f"init_db failed and 'jobs' table missing: {e}") from e

        # ---- Lightweight column migrations (idempotent) -------------------
        # Add new columns to existing tables when older schemas are present.
        _ensure_column(
            conn, "destinations", "default_privacy",
            "TEXT NOT NULL DEFAULT 'unlisted'",
        )
        _ensure_column(
            conn, "destinations", "color_tag",
            "TEXT NOT NULL DEFAULT ''",
        )
        # Per-destination AI metadata enrichment (OpenRouter prompt overrides).
        # When ai_enabled=1, the n8n workflow uses these fields to drive the
        # OpenRouter "AI: Enrich Metadata" call; empty values fall back to
        # the workflow's built-in defaults so existing destinations keep
        # working unchanged.
        _ensure_column(
            conn, "destinations", "ai_enabled",
            "INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            conn, "destinations", "ai_model",
            "TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn, "destinations", "ai_system_prompt",
            "TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn, "destinations", "ai_user_template",
            "TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn, "pipelines", "download_profile_id",
            "INTEGER REFERENCES download_profiles(id) ON DELETE SET NULL",
        )
        _ensure_column(
            conn, "destination_quota", "quota_exceeded_at", "TEXT",
        )
        _ensure_column(
            conn, "destination_quota", "quota_resets_at", "TEXT",
        )
        # ---- Multi-project YouTube rotation ------------------------------
        _ensure_column(conn, "oauth_tokens", "project_id", "INTEGER")
        # ---- Multi-channel YouTube routing (PR1) -------------------------
        # Every token/project/destination can now be bound to one row in
        # youtube_channels. NULL means "legacy / not yet detected" — picker
        # falls back to the global rotation when channel is unset.
        _ensure_column(conn, "oauth_tokens",     "youtube_channel_id", "INTEGER")
        _ensure_column(conn, "oauth_tokens",     "last_refreshed_at",  "TEXT NOT NULL DEFAULT ''")
        # ---- Token health flags (PR3) ----
        # Set to 1 when we detect the refresh_token is dead (invalid_grant
        # or invalid_client). Cleared back to 0 on a successful refresh
        # so a re-auth via /oauth/youtube/start automatically heals the row.
        _ensure_column(conn, "oauth_tokens",     "needs_reauth",       "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "oauth_tokens",     "last_error",         "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "youtube_projects", "youtube_channel_id", "INTEGER")
        _ensure_column(conn, "destinations",     "youtube_channel_id", "INTEGER")
        # ---- Per-channel "ignore daily cap" toggle -----------------------
        # When 1, the watcher drains the entire backfill queue each cycle
        # without honouring channels.daily_limit. Switch is exposed on the
        # Downloads tab channel card.
        _ensure_column(conn, "channels", "download_unlimited",
                       "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "channels", "download_priority",
                   "INTEGER NOT NULL DEFAULT 100")
        # ---- channels <-> sources FK -------------------------------------
        # Explicit relationship between the monitor-state table (channels)
        # and the catalog-state table (sources). Prior to this column the
        # link was looked up at request time by URL/external_id, which
        # caused multiple subtle bugs when the URL drifted (e.g. a bare
        # @handle vs. canonical @handle/videos). Migration script
        # ``scripts/maintenance/migrate_channels_source_fk.py`` backfills
        # the FK for existing installs; this line ensures the column
        # exists for fresh DBs.
        _ensure_column(conn, "channels", "source_id",
                       "INTEGER REFERENCES sources(id) ON DELETE SET NULL")
        # ---- Rich video metadata captured at download time ---------------
        # Watcher fills these from yt-dlp's `info` dict so the dashboard can
        # show views / likes / tags without an extra catalog hydration pass.
        _ensure_column(conn, "videos", "view_count",       "INTEGER")
        _ensure_column(conn, "videos", "like_count",       "INTEGER")
        _ensure_column(conn, "videos", "comment_count",    "INTEGER")
        _ensure_column(conn, "videos", "tags_json",        "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "videos", "categories_json",  "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "videos", "language",         "TEXT NOT NULL DEFAULT ''")
        # ---- Live download progress (yt-dlp hook → dashboard bar) --------
        # Watcher updates these on each progress callback (throttled to ~1Hz)
        # so the Downloads tab can render an accurate percentage instead of
        # a generic indeterminate animation.
        _ensure_column(conn, "download_queue", "progress_pct",
                       "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "download_queue", "progress_detail",
                       "TEXT NOT NULL DEFAULT ''")
        # ---- PR6: per-pipeline auto-delete + video archive ----------------
        # When pipelines.auto_delete_after_upload = 1, the local file
        # (and its sibling thumbnail/info.json/subs/folder) is removed
        # AFTER every enabled destination of the pipeline has produced an
        # 'uploaded' upload_results row. videos.archived_at is set in the
        # same transaction, so the watcher (and manual /downloads paste)
        # can warn / skip — preventing a re-download loop.
        _ensure_column(conn, "pipelines", "auto_delete_after_upload",
                       "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "videos",    "archived_at",
                       "TEXT NOT NULL DEFAULT ''")
        # ---- PR7: per-destination upload defaults (YouTube Data API v3) --
        # These defaults are merged into each upload_results row's request
        # body. They mirror the most-asked YouTube videos.insert knobs and
        # default to YouTube's own platform defaults so existing rows keep
        # behaving identically until the user opts in.
        _ensure_column(conn, "destinations", "default_comments_enabled",
                       "INTEGER NOT NULL DEFAULT 1")  # disable to lock comments
        _ensure_column(conn, "destinations", "default_made_for_kids",
                       "INTEGER NOT NULL DEFAULT 0")  # COPPA flag
        _ensure_column(conn, "destinations", "default_tags",
                       "TEXT NOT NULL DEFAULT ''")    # comma-separated
        _ensure_column(conn, "destinations", "default_category_id",
                       "TEXT NOT NULL DEFAULT ''")    # YouTube category id (e.g. '22')
        _ensure_column(conn, "destinations", "default_embeddable",
                       "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "destinations", "default_notify_subscribers",
                       "INTEGER NOT NULL DEFAULT 1")
        # Drop legacy unique-on-platform index so we can store one token
        # per (platform, project_id). The replacement index is created by
        # SCHEMA_SQL above.
        try:
            conn.execute("DROP INDEX IF EXISTS idx_oauth_platform")
        except sqlite3.OperationalError:
            pass

        # ---- Seed default download profile (idempotent) -------------------
        _seed_default_download_profile(conn)

        # ---- One-shot ledger backfill from existing upload_results --------
        # Safe to call repeatedly: INSERT OR IGNORE on UNIQUE(video_id,dest).
        # Only runs when ledger is empty AND upload_results has data.
        _backfill_upload_ledger(conn)

        # ---- One-shot routing-rules backfill from existing pipeline links -
        # For every (source -> pipeline -> destination) connection that
        # already exists, create a default permissive rule so legacy
        # automation keeps working under the new router. Idempotent.
        _backfill_routing_rules(conn)

        # ---- Performance indexes (idempotent) ----------------------------
        # Hot-path queries that grew without coverage:
        #   * _ready_to_upload_rows: EXISTS on (job_id, destination_id, status)
        #   * partial_uploads_recent: GROUP BY (job_id, destination_id), MAX(id)
        #   * api_activity in-flight scan: WHERE stage IN (...)
        #   * _retry_stranded_uploads: WHERE status / updated_at filters
        #   * queue active rows: ORDER BY status / updated_at
        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_upload_results_job_dest "
            "  ON upload_results(job_id, destination_id)",
            "CREATE INDEX IF NOT EXISTS idx_upload_progress_stage "
            "  ON upload_progress(stage)",
            "CREATE INDEX IF NOT EXISTS idx_ledger_status_updated "
            "  ON upload_ledger(status, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_updated "
            "  ON jobs(status, updated_at DESC)",
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()


def _backfill_upload_ledger(conn) -> None:
    """Seed `upload_ledger` from historical `upload_results` + `videos`+`jobs`.

    Runs only when the ledger is empty. Idempotent thanks to the
    UNIQUE(video_id, destination_id) constraint.
    """
    try:
        ledger_count = conn.execute(
            "SELECT COUNT(*) FROM upload_ledger"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        return
    if ledger_count > 0:
        return
    try:
        conn.execute("""
            INSERT OR IGNORE INTO upload_ledger
                (video_id, destination_id, job_id, status,
                 destination_video_id, destination_url, uploaded_at,
                 error_message, triggered_by, created_at, updated_at)
            SELECT
                v.youtube_video_id,
                ur.destination_id,
                ur.job_id,
                CASE WHEN ur.status IN ('success','uploaded') THEN 'uploaded'
                     ELSE 'failed' END,
                '',                              -- destination_video_id (not stored historically)
                COALESCE(ur.upload_url, ''),
                ur.created_at,
                COALESCE(ur.error_message, ''),
                'cron',
                ur.created_at,
                ur.created_at
            FROM upload_results ur
            JOIN jobs j   ON j.id = ur.job_id
            JOIN videos v ON v.id = j.video_id
            WHERE v.youtube_video_id <> ''
        """)
    except sqlite3.OperationalError:
        # Older DB may lack one of the joined tables; skip silently.
        pass


def _backfill_routing_rules(conn) -> None:
    """Seed `routing_rules` from existing pipeline -> destination links.

    For every (source, destination) pair connected via a shared pipeline,
    create one default permissive rule (no filters, default priority) if
    no rule already exists for that pair. Existing automation keeps
    working unchanged once the router is enabled.

    Idempotent: skips pairs that already have any rule.
    """
    try:
        # Detect existing pairs that already have at least one rule so we
        # can skip them. (source_id IS NULL rules don't count -- they're
        # global and not specific to any source.)
        existing = {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT source_id, destination_id FROM routing_rules "
                "WHERE source_id IS NOT NULL"
            ).fetchall()
        }
        rows = conn.execute(
            """SELECT s.id AS source_id, d.id AS destination_id
                 FROM sources s
                 JOIN destinations d ON d.pipeline_id = s.pipeline_id
                WHERE s.pipeline_id IS NOT NULL AND d.enabled = 1"""
        ).fetchall()
    except sqlite3.OperationalError:
        # Schema may not yet have all referenced tables on a fresh DB.
        return
    inserted = 0
    for r in rows:
        pair = (r["source_id"], r["destination_id"])
        if pair in existing:
            continue
        conn.execute(
            """INSERT INTO routing_rules
                    (source_id, destination_id, profile_id, priority,
                     enabled, label)
               VALUES (?, ?, NULL, 100, 1, 'auto-migrated from pipeline')""",
            (r["source_id"], r["destination_id"]),
        )
        inserted += 1
    if inserted:
        conn.commit()
        print(f"[migrate] seeded {inserted} routing_rules from pipeline links")


def _ensure_column(conn, table: str, column: str, decl: str) -> None:
    """Add `column` to `table` with declaration `decl` if it does not exist."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        conn.commit()


def _seed_default_download_profile(conn) -> None:
    """Insert a 'Default' download_profiles row if the table is empty.

    Mirrors the historical hard-coded yt-dlp behavior in headless_watcher.py
    so existing pipelines see no behavior change after this migration.
    """
    try:
        n = conn.execute("SELECT COUNT(*) FROM download_profiles").fetchone()[0]
    except sqlite3.OperationalError:
        return
    if n > 0:
        return
    conn.execute(
        """INSERT INTO download_profiles
               (name, description, max_height, container, video_codec,
                audio_codec, audio_only, write_subs, write_auto_subs,
                sub_langs, embed_subs, write_thumbnail, embed_thumbnail,
                embed_chapters, skip_shorts, shorts_max_seconds, skip_live,
                custom_format, is_default)
           VALUES ('Default', 'Mirrors legacy hard-coded watcher behavior',
                   0, 'mp4', 'any', 'm4a', 0, 1, 1, 'en', 0, 1, 0, 0, 0, 60, 1, '', 1)"""
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Inline self-test — run with: python dashboard/models.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_path = os.environ.get("DB_PATH", "./db/app.db")
    print(f"Initializing database at: {test_path}")
    init_db(test_path)
    print("Schema applied.")

    conn = get_db(test_path)

    # Insert
    cur = conn.execute(
        "INSERT INTO pipelines (name, description, active) VALUES (?, ?, ?)",
        ("Test Pipeline", "self-test row", 1),
    )
    new_id = cur.lastrowid
    print(f"Inserted pipeline id={new_id}")

    # Read back
    row = conn.execute("SELECT * FROM pipelines WHERE id = ?", (new_id,)).fetchone()
    print("Row fetched:", dict(row))

    # Verify pragmas applied
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    print(f"PRAGMA journal_mode = {journal}")
    print(f"PRAGMA foreign_keys = {fk}")

    # Verify all expected tables exist
    expected_tables = {
        "pipelines", "channels", "destinations", "processing_steps",
        "videos", "jobs", "job_outputs", "upload_results",
    }
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    actual = {r[0] for r in rows}
    missing = expected_tables - actual
    if missing:
        print(f"MISSING TABLES: {missing}")
        raise SystemExit(1)
    print(f"All {len(expected_tables)} tables present.")

    # Cleanup
    conn.execute("DELETE FROM pipelines WHERE id = ?", (new_id,))
    conn.close()
    print("OK")
