# FEATURE — Catalog, Manual Upload & Backfill

> Status: **Blueprint / RFC** — not implemented yet.
> Owner: dashboard team.
> Related: [FEATURE_DOWNLOAD_SETTINGS.md](FEATURE_DOWNLOAD_SETTINGS.md)
> Created: 2026-04-26.

## 0. Architectural framing

project003 today has **one** way for a video to enter the system:
RSS-triggered cron on a watched channel. Adding manual upload is not
a "new page" — it's a second *input mode* on top of the same downloader,
queue, and uploader. Before this feature ships, the architecture
becomes:

```
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Auto Pipelines  │   │ Catalog/Backfill │   │  Ad-hoc URL      │
│  (RSS-triggered) │   │  (human-curated) │   │  (paste & go,    │
└────────┬─────────┘   └────────┬─────────┘   │   future)        │
         │                      │             └────────┬─────────┘
         └──────────┬───────────┴──────────────────────┘
                    ▼
         ┌────────────────────────┐
         │  Upload Queue          │
         │  (quota / throttle /   │
         │   heartbeat / retry)   │
         └────────────┬───────────┘
                      │
                      ▼
         ┌────────────────────────┐
         │  Upload Ledger         │
         │  (dedup source-of-     │
         │  truth, all paths      │
         │  read & write)         │
         └────────────────────────┘
```

Three input modes, one queue, **one ledger**. The cron pipeline must be
migrated to write to the same ledger or the dedup guarantee is empty.

## 1. Scope (decided)

### v1 ships

1. **Sources** — first-class entity (channel URL or playlist URL).
2. **Catalog** — two-tier metadata (flat scan + lazy hydrate) per source.
3. **Filters** — the "free" filter set (status, duration, date, title,
   live-status, personal flags).
4. **Manual cherry-pick enqueue** — pick rows + destination → queue.
5. **Upload ledger** — global table, per-`(video_id, destination_id)`.
6. **Cron pipeline migration** — existing flow writes to the ledger.
7. **Per-destination daily upload budget** — quota counter, queue
   respects it.
8. **Diff view** — "what's new since last scan".
9. **CSV export** of selected rows.
10. **Personal flags** — star, ignore.
11. **"Mark as already uploaded"** bulk action.

### v2 (deferred — separate RFC when v1 is stable)

- Auto-with-rules backfill (pace mode, sort rules, scheduled drain).
- Hydrate-required filters (view count, tags, has-chapters).
- Smart playlists / saved filter views.
- AI dry-run preview.
- Notes column.
- Per-source default destination override.

### Explicit non-goals (forever or until a real need surfaces)

- Inline video player in the catalog.
- Multi-user / permissions.
- Drag-and-drop queue reordering.
- Editing destination metadata per-row inside the catalog (belongs in
  the queue/preview step).
- "AI picks the interesting ones for you" auto-curation.

## 2. Data model

### 2.1 New table: `sources`

```sql
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT    NOT NULL CHECK (kind IN ('channel','playlist')),
    url             TEXT    NOT NULL,
    external_id     TEXT,           -- UCxxxx or PLxxxx (extracted at create time)
    name            TEXT    NOT NULL,
    pipeline_id     INTEGER REFERENCES pipelines(id) ON DELETE SET NULL,
    last_scanned_at TEXT,
    last_scan_error TEXT,
    total_known     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(external_id)
);
```

Sources can optionally be attached to a pipeline so cron-watched
channels appear as sources too (they share the same catalog UI).

### 2.2 New table: `catalog_videos`

The flat-scan cache. One row per `(source_id, video_id)`.

```sql
CREATE TABLE IF NOT EXISTS catalog_videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    video_id        TEXT    NOT NULL,        -- 11-char YouTube ID
    title           TEXT    NOT NULL,
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
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    unavailable_at  TEXT,                     -- set when a re-scan can't find it

    UNIQUE(source_id, video_id)
);

CREATE INDEX IF NOT EXISTS ix_catalog_source_uploaddate ON catalog_videos(source_id, upload_date DESC);
CREATE INDEX IF NOT EXISTS ix_catalog_video             ON catalog_videos(video_id);
```

**Why a row per (source, video) rather than one global row:** the same
video legitimately appears in multiple sources (channel + a curated
playlist). We want to track per-source first-seen / last-seen, but the
ledger is global on `video_id` — so dedup still works.

### 2.3 New table: `upload_ledger`

The single source of truth for "did we upload this anywhere?"

```sql
CREATE TABLE IF NOT EXISTS upload_ledger (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id           TEXT    NOT NULL,
    destination_id     INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    job_id             INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    status             TEXT    NOT NULL CHECK (status IN
                          ('queued','uploading','uploaded','failed','removed')),
    destination_video_id TEXT,                -- e.g. uploaded YouTube videoId
    destination_url      TEXT,
    uploaded_at        TEXT,
    error_message      TEXT,
    source_id          INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    triggered_by       TEXT NOT NULL CHECK (triggered_by IN
                          ('cron','manual','backfill')),
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(video_id, destination_id)
);

CREATE INDEX IF NOT EXISTS ix_ledger_video ON upload_ledger(video_id);
CREATE INDEX IF NOT EXISTS ix_ledger_dest_uploaded
    ON upload_ledger(destination_id, uploaded_at DESC);
```

The `UNIQUE(video_id, destination_id)` is the dedup guarantee.
Re-trying a failed upload → UPDATE the existing row, never INSERT.

### 2.4 New table: `destination_quota`

```sql
CREATE TABLE IF NOT EXISTS destination_quota (
    destination_id     INTEGER PRIMARY KEY REFERENCES destinations(id) ON DELETE CASCADE,
    daily_max          INTEGER NOT NULL DEFAULT 6,
    rolling_24h_count  INTEGER NOT NULL DEFAULT 0,  -- maintained by trigger or queue worker
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`rolling_24h_count` is recomputed on demand from
`upload_ledger WHERE destination_id=? AND uploaded_at > now-24h`. The
column is just a cache; truth is the ledger.

### 2.5 Existing `destinations` table — add columns

```sql
ALTER TABLE destinations ADD COLUMN color_tag TEXT;     -- '#7c3aed', UI hint
ALTER TABLE destinations ADD COLUMN display_name TEXT;  -- already covered by `label`?
```

(If `label` already exists and is sufficient, skip `display_name`.)

### 2.6 Migration plan

1. `models.py::init_db()` adds the four `CREATE TABLE IF NOT EXISTS` blocks.
2. **Backfill the ledger from existing data:**
   ```sql
   INSERT OR IGNORE INTO upload_ledger
       (video_id, destination_id, job_id, status, destination_video_id,
        destination_url, uploaded_at, error_message, triggered_by)
   SELECT j.video_id, ur.destination_id, j.id,
          CASE WHEN ur.success=1 THEN 'uploaded' ELSE 'failed' END,
          ur.destination_video_id, ur.destination_url,
          ur.created_at, ur.error_message, 'cron'
   FROM upload_results ur
   JOIN jobs j ON j.id = ur.job_id;
   ```
3. The cron uploader path gets one extra call after a successful
   `upload_results` insert: `_record_ledger(...)`. Idempotent because
   of the UNIQUE constraint.

## 3. Catalog scan flow

### 3.1 Flat scan (cheap)

```python
# pseudocode
def scan_source(source_id: int) -> ScanResult:
    src = db.get_source(source_id)
    opts = {"extract_flat": True, "skip_download": True, "quiet": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(src.url, download=False)
    seen_ids = []
    for entry in info.get("entries", []):
        seen_ids.append(entry["id"])
        upsert_catalog_video(source_id, entry)   # title/duration/upload_date/live_status/thumb
    mark_unavailable(source_id, exclude_ids=seen_ids)
    db.update_source_scan(source_id, ok=True, total=len(seen_ids))
    return ScanResult(new_count, updated_count, removed_count)
```

- One yt-dlp call regardless of channel size.
- Returns within seconds for ~150 videos.
- `mark_unavailable` sets `unavailable_at = now()` on rows missing from
  the latest scan but keeps them around (the ledger may reference them).

### 3.2 Hydrate (expensive, on-demand)

```python
def hydrate_videos(catalog_ids: list[int]) -> None:
    # Runs in a background thread; one yt-dlp call per video.
    # Updates description/tags/view_count/etc and sets hydrated_at.
    # Skips rows hydrated within the last 24h.
```

Triggered by:
- "Hydrate selected" toolbar button.
- Implicit hydrate on row click (single video).
- Future: scheduled hydrate for starred rows.

Hard cap: 1 worker thread, 1 second between requests, 30s timeout per
video. Refuses to run if quota.recent_429s > 0 within the last 5 minutes.

## 4. Upload Queue & Quota

### 4.1 Enqueue

```python
def enqueue_upload(video_id: str, destination_id: int,
                   source_id: int|None, triggered_by: str) -> str:
    # Validate
    if ledger.has_uploaded(video_id, destination_id):
        raise AlreadyUploadedError(...)
    if quota.would_exceed(destination_id, planned_count=1):
        raise QuotaExceededError(...)
    # Insert ledger row in 'queued' state
    ledger.insert(video_id, destination_id, status='queued',
                  triggered_by=triggered_by, source_id=source_id)
    # Insert/update jobs row that the existing watcher loop picks up
    return job_id
```

### 4.2 Soft-undo window

Catalog enqueues land in `status='queued'` and are not eligible for the
watcher to claim until `created_at + 30s`. The UI shows a yellow row
with an "Undo" button. After 30s the row is claimable; the badge turns
to "queued for upload".

Implementation: the watcher's job-claim query already filters; add
`AND datetime(created_at) <= datetime('now','-30 seconds')` for jobs
where `triggered_by='manual'`.

### 4.3 Quota enforcement

- On every enqueue: recompute `rolling_24h_count` from the ledger,
  compare to `daily_max`, refuse if exceeding.
- The bulk-enqueue endpoint computes the *planned total* against the
  remaining budget and returns a structured error showing how many
  would fit: *"Quota allows 4 more uploads to channel X today. You
  selected 7. Enqueue 4 now and skip 3, or cancel?"*
- A nightly housekeeping job clears quota cache rows older than 48h.

## 5. HTTP API

| Method | Path | Purpose |
|---|---|---|
| POST   | `/api/sources`                                | Create source from URL (auto-detect kind) |
| GET    | `/api/sources`                                | List sources |
| DELETE | `/api/sources/<id>`                           | Delete source + its catalog rows |
| POST   | `/api/sources/<id>/scan`                      | Trigger flat scan; returns diff stats |
| GET    | `/api/sources/<id>/diff`                      | Rows added since last scan |
| GET    | `/api/sources/<id>/catalog`                   | Paginated, filtered, sorted catalog |
| POST   | `/api/catalog/hydrate`                        | Body: `{ids: [...]}`. Background hydrate |
| POST   | `/api/catalog/star`                           | Body: `{ids, value}`. Bulk star/unstar |
| POST   | `/api/catalog/ignore`                         | Bulk ignore/unignore |
| POST   | `/api/catalog/mark_uploaded`                  | Body: `{ids, destination_id}`. Writes ledger only |
| POST   | `/api/catalog/enqueue`                        | Body: `{ids, destination_id}`. The big one |
| GET    | `/api/catalog/export.csv`                     | CSV export of current filter |
| GET    | `/api/ledger?video_id=...`                    | Full upload history for a video |
| GET    | `/api/destinations/<id>/quota`                | `{daily_max, used_24h, remaining}` |
| PUT    | `/api/destinations/<id>/quota`                | Update daily_max |

### 5.1 Catalog query parameters

```
?source_id=N
&q=text              (title contains, case-insensitive)
&status=never|queued|uploading|uploaded|failed
&min_duration=60     (seconds)
&max_duration=3600
&from_date=YYYY-MM-DD
&to_date=YYYY-MM-DD
&live_status=not_live|was_live|...
&starred=1
&ignored=0           (default)
&unavailable=0       (default)
&sort=upload_date|duration|title|status
&order=asc|desc
&page=1
&per_page=50
```

Response includes `{rows, total, has_more, applied_filters}`.

## 6. UI

### 6.1 Source list (new top-level page)

```
┌─ Sources ───────────────────────────[+ Add source]─┐
│ ManhuaNova channel    150 / 24 uploaded   ⚠ 3 new │
│ Curated lectures      72 / 72 uploaded            │
│ ChannelB playlist     18 / 18 uploaded   ✓ synced │
└────────────────────────────────────────────────────┘
```

Each row links to the catalog view for that source.

### 6.2 Catalog view

```
┌─ ManhuaNova — 150 videos ──────[Re-scan] [Hydrate sel.]─┐
│ Filters: [Status ▼] [Duration ▼] [Date ▼] [Search 🔍]   │
│ Sort:    Upload date ↓                                  │
│                                                         │
│ ☐ ⭐  Title              Length  Date       Status      │
│ ☐ ⭐  Episode 12 — ...   18:24   2026-04-20 ✓ Uploaded │
│ ☑     Episode 11 — ...   17:50   2026-04-13 — Never    │
│ ☑ ⭐  Episode 10 — ...   19:02   2026-04-06 ✗ Failed   │
│ ☐     Episode 9  — ...   18:11   2026-03-30 ✓ Uploaded │
│ ...                                                     │
│                                                         │
│ Selected: 2     Toolbar: [Enqueue ▼] [Star] [Ignore]   │
│                          [Mark uploaded] [Export CSV]   │
└─────────────────────────────────────────────────────────┘
```

- Enqueue dropdown lists destinations with their color tag and
  remaining-quota badge: `🟣 ManhuaNova (4/6 used today)`.
- Confirm dialog before enqueue: shows count, destination, privacy.
- Status column tooltips show per-destination ledger status.

### 6.3 Diff view

After `Re-scan`, an inline banner shows: *"3 new videos found since
last scan ([show only new])"*. Clicking the link applies a virtual
filter `first_seen_at > last_scan_started_at`.

### 6.4 Quota indicator

Global header strip shows per-destination quota:
`🟣 ManhuaNova 4/6   🔵 ShortsAlt 0/12`
Click → opens quota settings for that destination.

## 7. Security / safety

1. **URL validation on source creation:** must parse to a YouTube
   `channel/`, `@handle`, `playlist?list=` or `youtu.be/` form. Reject
   anything else (SSRF guardrail).
2. **Bulk action confirmation threshold:** > 10 rows → require typing
   the count to confirm.
3. **CSRF:** all POST/PUT/DELETE go through HTMX with the existing
   header convention.
4. **Ledger immutability:** `uploaded_at` and `destination_video_id` are
   write-once. Subsequent UPDATEs only allowed if `status='failed'` →
   `'queued'` (a retry).
5. **Quota cannot be bypassed** via the API; only the quota update
   endpoint can change `daily_max`.

## 8. Testing

| Layer | Tests |
|---|---|
| `scan_source` | Flat scan parses entries; second scan with one removed → marks `unavailable_at`; idempotent |
| `hydrate_videos` | Skips rows hydrated < 24h ago; respects 1s throttle; gives up cleanly on 429 |
| Ledger UNIQUE | Re-enqueueing the same `(video_id, dest_id)` raises `AlreadyUploadedError`; failed → retried updates in place |
| Quota | `would_exceed` returns true at boundary; bulk enqueue partials respect remaining budget |
| Soft-undo | A manual job is not claimable in the first 30s; cancellable |
| Cron migration | After a successful cron upload, the ledger row exists with `triggered_by='cron'` |
| HTTP | Filter combinations return correct counts; CSV export matches filtered set |
| Source URL validation | Rejects non-YouTube hosts |

## 9. Phasing / build order

| Phase | Scope | Effort |
|---|---|---|
| **P0 — schema** | All 4 tables + migration that backfills ledger from `upload_results` | S |
| **P1 — sources & flat scan** | Add source CRUD, flat-scan endpoint, basic catalog list (no filters yet) | M |
| **P2 — ledger wiring** | Cron uploader writes to ledger; existing dashboard reads upload status from ledger | M |
| **P3 — catalog UI v1** | Filter bar (free filters), sort, pagination, status column | M |
| **P4 — manual enqueue** | Enqueue endpoint + soft-undo + per-destination quota + confirm dialog | M |
| **P5 — polish** | Diff view, CSV export, star/ignore, mark-uploaded, color tags | S |
| **P6 — hydrate** | Background hydrate worker + lazy column population | S |

Recommended first PR: **P0 + P1** (schema + scan + bare catalog). Ship
nothing user-facing until P0 migration is verified on a backup of the
real DB.

## 10. Risks & open questions

1. **Ledger backfill correctness.** The migration in §2.6 assumes
   `upload_results` cleanly maps 1:1 to ledger rows. If duplicates
   exist (a job retried and produced two `upload_results`), the
   `INSERT OR IGNORE` keeps the first. **Mitigation:** run the
   migration in a transaction with a dry-run count first.
2. **Race on quota.** Two concurrent bulk enqueues could each pass the
   `would_exceed` check and together exceed budget by ≤ 1. **Mitigation:**
   wrap enqueue in a serialized SQL transaction (`BEGIN IMMEDIATE`).
   Acceptable: cap is a soft guideline, ±1 is fine; if it ever
   matters we'll move to a proper lock.
3. **`extract_flat` accuracy.** YouTube's tab API sometimes returns
   uploads in non-strict order or omits very recent videos. **Mitigation:**
   run a second scan with `playlistreverse=False, dateafter=...` for
   the most recent week if missing-video reports surface. Not a v1
   concern.
4. **Channel handle vs UC ID.** Handles (`@channel`) need extra
   resolution to a UC ID for `external_id`. yt-dlp does this for us;
   store both `url` (as user typed) and `external_id` (canonical).
5. **Catalog growth.** 50 sources × 500 videos = 25k rows. Tiny.
   `description` column hydrated on demand keeps DB size manageable.
6. **Per-row destination is *not* configurable in v1.** All selected
   rows in one bulk action go to one destination. Curated multi-channel
   uploads are deferred — workflow: filter → enqueue to dest A → filter
   again → enqueue to dest B.
7. **Personal flags don't sync across sources.** Star on `(sourceA, vidX)`
   doesn't star `(sourceB, vidX)`. Acceptable; the same video in two
   sources usually means different curatorial intent anyway.

## 11. Out-of-scope (parking lot)

- Auto-with-rules backfill (pace mode, sort rules, scheduled drain).
- Hydrate-required filters (view count, tags, has-chapters, has-subs).
- Smart playlists / saved filter views.
- Notes column (free-text per row).
- AI dry-run preview.
- Per-row destination override in bulk enqueue.
- Inline player.
- Multi-user / permissions.
- Conflict detection across sources.
- Per-source default destination override.
