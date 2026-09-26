# Database Schema
## project003 — SQLite (WAL Mode)

**File:** `./db/app.db`  
**Engine:** SQLite 3, WAL journal mode enabled  
**Accessed by:** dashboard, watcher, processor  
**Status:** LOCKED — schema changes require a migration script + updating this document

---

## 1. Schema Initialization Rules

- All tables use `INTEGER PRIMARY KEY` (auto-increment rowid alias)
- All timestamps stored as ISO-8601 strings: `YYYY-MM-DDTHH:MM:SS` (UTC)
- Boolean values stored as `INTEGER` (0 = false, 1 = true)
- JSON blobs stored as `TEXT` (valid JSON string)
- Foreign keys enforced with `PRAGMA foreign_keys = ON` on every connection open
- WAL mode set with `PRAGMA journal_mode = WAL` on first connection
- All string columns use `TEXT NOT NULL DEFAULT ''` unless nullable is explicitly required

---

## 2. Table: `pipelines`

A pipeline is the top-level configuration unit. Channels feed into it; processing steps transform the video; destinations receive the output.

```sql
CREATE TABLE pipelines (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,   -- 0=paused, 1=running
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
```

| Column      | Type    | Notes                                          |
|-------------|---------|------------------------------------------------|
| id          | INTEGER | Auto PK                                        |
| name        | TEXT    | User-defined label e.g. "Manhwa → Multi"       |
| description | TEXT    | Optional notes                                 |
| active      | INTEGER | 1 = watcher processes this pipeline's channels |
| created_at  | TEXT    | ISO-8601 UTC                                   |

---

## 3. Table: `channels`

Each channel belongs to exactly one pipeline. A pipeline can have many channels.

```sql
CREATE TABLE channels (
    id                  INTEGER PRIMARY KEY,
    pipeline_id         INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    name                TEXT    NOT NULL,                  -- display name e.g. "Manhwa Fresh"
    channel_id          TEXT    NOT NULL,                  -- YouTube channel ID: UCxxx... or @handle
    url                 TEXT    NOT NULL,                  -- full YouTube URL
    mode                TEXT    NOT NULL DEFAULT 'monitor', -- 'backfill' | 'monitor'
    backfill_complete   INTEGER NOT NULL DEFAULT 0,        -- 0=still backfilling, 1=done
    backfill_queue      TEXT    NOT NULL DEFAULT '[]',     -- JSON array of video IDs remaining
    backfill_entry_map  TEXT    NOT NULL DEFAULT '{}',     -- JSON map: video_id → yt-dlp entry
    daily_limit         INTEGER NOT NULL DEFAULT 10,       -- max downloads per day
    uploads_today       INTEGER NOT NULL DEFAULT 0,        -- counter (resets at midnight)
    uploads_today_date  TEXT    NOT NULL DEFAULT '',       -- YYYY-MM-DD of last reset
    last_check          TEXT    NOT NULL DEFAULT '1970-01-01T00:00:00',  -- ISO-8601
    active              INTEGER NOT NULL DEFAULT 1,        -- 0=paused, 1=enabled
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX idx_channels_pipeline ON channels(pipeline_id);
CREATE UNIQUE INDEX idx_channels_channel_id ON channels(channel_id);
```

| Column             | Type    | Notes                                                   |
|--------------------|---------|------------------------------------------------------|
| pipeline_id        | FK      | Cascade delete: removing pipeline removes all channels  |
| channel_id         | TEXT    | Unique — same channel cannot be in two pipelines        |
| mode               | TEXT    | `backfill` = full history first; `monitor` = new only   |
| backfill_complete  | INTEGER | Set to 1 by watcher when backfill_queue is emptied      |
| backfill_queue     | TEXT    | JSON `["videoId1", "videoId2", ...]` sorted oldest-first|
| backfill_entry_map | TEXT    | JSON `{"videoId1": {title, url, ...}, ...}` from yt-dlp |
| daily_limit        | INTEGER | Watcher enforces this — resets at midnight UTC          |
| uploads_today      | INTEGER | Incremented by watcher after each download              |
| uploads_today_date | TEXT    | YYYY-MM-DD — watcher resets `uploads_today` when date changes |
| last_check         | TEXT    | Updated by watcher after each monitor-mode poll         |
| active             | INTEGER | Dashboard can pause/resume channels                     |

---

## 4. Table: `destinations`

Each pipeline has one or more destinations (upload targets). A destination specifies which platform and which n8n webhook to trigger.

```sql
CREATE TABLE destinations (
    id              INTEGER PRIMARY KEY,
    pipeline_id     INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    platform        TEXT    NOT NULL,  -- 'youtube' | 'dailymotion' | 'facebook' | 'tiktok'
    label           TEXT    NOT NULL DEFAULT '',  -- optional: "My YT Channel", "Brand TikTok"
    n8n_webhook_url TEXT    NOT NULL,  -- e.g. http://n8n:5678/webhook/pipeline1-youtube
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX idx_destinations_pipeline ON destinations(pipeline_id);
```

| Column          | Type    | Notes                                             |
|-----------------|---------|---------------------------------------------------|
| pipeline_id     | FK      | Cascade delete                                    |
| platform        | TEXT    | Constrained to known platform slugs               |
| label           | TEXT    | Human label for the destination account           |
| n8n_webhook_url | TEXT    | Watcher POSTs to this URL after download          |
| enabled         | INTEGER | Disabled destinations are skipped by watcher      |

**Note on n8n_webhook_url:** Each destination has its own n8n webhook path. This allows different n8n workflows per platform (e.g., YouTube workflow vs TikTok workflow with different AI prompts and upload nodes).

---

## 5. Table: `processing_steps`

Defines the FFmpeg transformation pipeline for a given pipeline+destination combination. Steps are applied in `step_order` sequence.

```sql
CREATE TABLE processing_steps (
    id          INTEGER PRIMARY KEY,
    pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    destination_id INTEGER REFERENCES destinations(id) ON DELETE CASCADE,
    -- NULL destination_id = global step (applied for ALL destinations)
    -- Non-NULL destination_id = per-destination step (applied only for that destination)
    step_order  INTEGER NOT NULL DEFAULT 0,
    step_type   TEXT    NOT NULL,  -- see step types below
    params      TEXT    NOT NULL DEFAULT '{}',  -- JSON params for this step
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX idx_steps_pipeline ON processing_steps(pipeline_id);
CREATE INDEX idx_steps_destination ON processing_steps(destination_id);
```

| Column         | Type    | Notes                                                       |
|----------------|---------|-------------------------------------------------------------|
| pipeline_id    | FK      | Which pipeline this step belongs to                         |
| destination_id | FK/NULL | NULL = applies to all destinations; non-NULL = specific only|
| step_order     | INTEGER | Lower number = applied first (0, 1, 2, ...)                 |
| step_type      | TEXT    | One of the step type slugs defined in PROCESSING_PIPELINE.md|
| params         | TEXT    | JSON object; keys vary by step_type                         |
| enabled        | INTEGER | Can disable steps without deleting them                     |

**Step execution order:** Global steps (destination_id IS NULL) are applied first. Then destination-specific steps are applied on top, in step_order sequence.

---

## 6. Table: `videos`

One record per unique YouTube video encountered by the watcher. Stores original + AI-enriched metadata.

```sql
CREATE TABLE videos (
    id                  INTEGER PRIMARY KEY,
    channel_id          INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    youtube_video_id    TEXT    NOT NULL,  -- YouTube video ID e.g. "dQw4w9WgXcQ"
    original_title      TEXT    NOT NULL DEFAULT '',
    original_description TEXT   NOT NULL DEFAULT '',
    duration            INTEGER NOT NULL DEFAULT 0,  -- seconds
    source_url          TEXT    NOT NULL DEFAULT '',
    thumbnail_url       TEXT    NOT NULL DEFAULT '',
    published_at        TEXT    NOT NULL DEFAULT '',  -- ISO-8601, from YouTube
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE UNIQUE INDEX idx_videos_youtube_id ON videos(youtube_video_id);
CREATE INDEX idx_videos_channel ON videos(channel_id);
```

| Column              | Type    | Notes                                              |
|---------------------|---------|----------------------------------------------------|
| youtube_video_id    | TEXT    | Unique — prevents duplicate processing             |
| original_title      | TEXT    | As downloaded from YouTube, before AI rewrite      |
| original_description| TEXT    | As downloaded from YouTube                         |
| duration            | INTEGER | Seconds, from yt-dlp                               |
| published_at        | TEXT    | YouTube publication date                           |

---

## 7. Table: `jobs`

One row per video × pipeline processing run. Tracks the full lifecycle from download to upload completion.

```sql
CREATE TABLE jobs (
    id              INTEGER PRIMARY KEY,
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    pipeline_id     INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    status          TEXT    NOT NULL DEFAULT 'pending',
    -- Status values (lifecycle order):
    -- 'pending'      → created, waiting for watcher to download
    -- 'downloading'  → watcher is currently downloading
    -- 'downloaded'   → file on disk, ready for processor
    -- 'processing'   → processor is running FFmpeg
    -- 'processed'    → all output files created, ready for n8n
    -- 'uploading'    → n8n has been triggered, upload in progress
    -- 'done'         → all destinations uploaded successfully
    -- 'failed'       → terminal failure, see error_message
    -- 'partial'      → at least one destination succeeded, at least one failed
    source_file_path TEXT   NOT NULL DEFAULT '',  -- /downloads/job_{id}/source.mp4
    error_message   TEXT    NOT NULL DEFAULT '',
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_pipeline ON jobs(pipeline_id);
CREATE INDEX idx_jobs_video ON jobs(video_id);
```

| Column           | Type    | Notes                                                    |
|------------------|---------|----------------------------------------------------------|
| status           | TEXT    | Single lifecycle field — see state machine in DATA_FLOW.md|
| source_file_path | TEXT    | Absolute path inside container to the downloaded file    |
| error_message    | TEXT    | Last error text, set on `failed` transitions             |
| retry_count      | INTEGER | Incremented on each retry attempt                        |
| updated_at       | TEXT    | Updated on every status change — use for queue ordering  |

**Trigger to update `updated_at` automatically:**
```sql
CREATE TRIGGER jobs_updated_at
AFTER UPDATE ON jobs
BEGIN
    UPDATE jobs SET updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')
    WHERE id = NEW.id;
END;
```

---

## 8. Table: `job_outputs`

One row per job × destination output file. Created by the processor after FFmpeg completes.

```sql
CREATE TABLE job_outputs (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    file_path       TEXT    NOT NULL,  -- /downloads/job_{id}/{platform}.mp4
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX idx_job_outputs_job ON job_outputs(job_id);
```

| Column          | Type    | Notes                                                  |
|-----------------|---------|--------------------------------------------------------|
| destination_id  | FK      | Links to which destination this file was built for     |
| file_path       | TEXT    | Absolute path inside container                         |
| file_size_bytes | INTEGER | Set after FFmpeg completes                             |

---

## 9. Table: `upload_results`

One row per job × destination upload attempt. Written by the dashboard when it receives `/api/callback` from n8n.

```sql
CREATE TABLE upload_results (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    destination_id  INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    platform        TEXT    NOT NULL,  -- denormalized for query convenience
    status          TEXT    NOT NULL,  -- 'success' | 'failed'
    upload_url      TEXT    NOT NULL DEFAULT '',  -- e.g. https://youtu.be/xxx
    error_message   TEXT    NOT NULL DEFAULT '',
    ai_used         INTEGER NOT NULL DEFAULT 0,   -- 1 if OpenRouter was used
    ai_title        TEXT    NOT NULL DEFAULT '',
    ai_description  TEXT    NOT NULL DEFAULT '',
    ai_tags         TEXT    NOT NULL DEFAULT '[]', -- JSON array
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);

CREATE INDEX idx_upload_results_job ON upload_results(job_id);
CREATE INDEX idx_upload_results_status ON upload_results(status);
```

| Column        | Type    | Notes                                                    |
|---------------|---------|----------------------------------------------------------|
| platform      | TEXT    | Denormalized copy of destination.platform for easy query |
| upload_url    | TEXT    | Empty string on failure                                  |
| ai_used       | INTEGER | Boolean — was AI metadata used for this upload?          |
| ai_title      | TEXT    | The AI-generated title actually used                     |
| ai_tags       | TEXT    | JSON array of tags used                                  |

---

## 10. Schema Diagram

```
pipelines
    │
    ├──< channels (pipeline_id)
    │
    ├──< destinations (pipeline_id)
    │
    └──< processing_steps (pipeline_id, destination_id nullable)

channels
    └──< videos (channel_id)
            └──< jobs (video_id, pipeline_id)
                    ├──< job_outputs (job_id, destination_id)
                    └──< upload_results (job_id, destination_id)
```

---

## 11. Initialization SQL (models.py output)

The `models.py` file will run all CREATE TABLE statements with `IF NOT EXISTS`, then:
1. `PRAGMA foreign_keys = ON`
2. `PRAGMA journal_mode = WAL`
3. `PRAGMA synchronous = NORMAL` (safe with WAL, improves write throughput)

This runs on every container startup. Idempotent — safe to run on an existing database.

---

## 12. Migration Strategy

Since this is pre-launch, migrations are not yet needed. When the schema changes in the future:
1. Create a `migrations/` folder
2. Each migration file: `migration_001_add_column.sql`
3. Track applied migrations in a `schema_version` table
4. `models.py` applies pending migrations on startup

---

*Next: [API_CONTRACTS.md](API_CONTRACTS.md)*
