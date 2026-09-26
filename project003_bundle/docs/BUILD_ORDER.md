# Build Order
## project003 — Ordered Implementation Plan

**Status:** ACTIVE — follow this order strictly. Do not skip steps.  
**Rule:** Each step must be working and tested before starting the next.  
**Rule:** Every code file written must have a corresponding entry in this doc updated to DONE.

---

## Build Phases Overview

```
Phase 1 — Foundation     (SQLite + Docker plumbing)
Phase 2 — Watcher        (migrate from JSON to SQLite)
Phase 3 — Dashboard      (rebuild UI around SQLite)
Phase 4 — Processor      (new container, FFmpeg pipeline)
Phase 5 — n8n            (workflow update + AI + callback)
Phase 6 — Integration    (end-to-end test, full system)
```

---

## Phase 1 — Foundation

These steps have no dependencies and must be done first. Everything else builds on this.

### Step 1.1 — SQLite Schema (`dashboard/models.py`)
**Status:** TODO  
**File:** `dashboard/models.py`  
**What:** Create the SQLite schema module:
- All 8 CREATE TABLE statements with IF NOT EXISTS
- `init_db()` function that runs all tables + PRAGMA statements
- `get_db()` connection helper (WAL mode, foreign keys, row_factory)
- `updated_at` trigger for `jobs` table
- Run `init_db()` on Flask app startup

**Reference:** [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)  
**Test:** Run `python models.py` standalone → `app.db` created with all tables, no errors.

---

### Step 1.2 — Migrate `channel_monitor_config.json` → SQLite
**Status:** TODO  
**File:** `dashboard/migrate_config.py` (one-time migration script)  
**What:**
- Read existing `channel_monitor_config.json`
- Create a default pipeline: "Imported Channels"
- Insert each channel from JSON into `channels` table
- Preserve: mode, backfill_complete, backfill_queue, daily_limit, uploads_today, last_check
- Print summary of what was migrated

**Test:** Run script → check `app.db` has the Manhwa Fresh channel imported correctly.

---

### Step 1.3 — Update `docker-compose.yml`
**Status:** TODO  
**File:** `docker-compose.yml`  
**What:**
- Replace `./channel_monitor_config.json` volume mounts with `./db:/data`
- Add `processor` service (CPU-only for now, GPU later)
- Add `.env` file support with `DOWNLOADS_PATH` variable
- Create `./db/` directory if it doesn't exist (or let Docker create it)

**Reference:** [CONTAINER_SPECS.md](CONTAINER_SPECS.md) Section 5  
**Test:** `docker compose config` — no YAML errors.

---

### Step 1.4 — Create `./db/` directory and `.env` file
**Status:** TODO  
**Files:** `./db/.gitkeep`, `.env`, `.env.example`  
**What:**
- Create `./db/` directory
- Create `.env.example` with all variables and comments
- Create `.env` with local values (not committed to git)
- Add `.env` and `./db/*.db` to `.gitignore`

---

## Phase 2 — Watcher Migration

### Step 2.1 — Update `headless_watcher.py` to read SQLite
**Status:** TODO  
**File:** `headless_watcher.py`  
**What (replace JSON config reads):**
- Remove all JSON file reads/writes
- Add SQLite connection using `DB_PATH` env var
- Replace `_load_channel_config()` → `SELECT * FROM channels WHERE active=1`
- Replace `_save_channel_config()` → `UPDATE channels SET ...`
- Replace `backfill_queue` JSON read/write → DB column read/write
- Replace `daily_limit` / `uploads_today` JSON read/write → DB column read/write

**What (add job tracking):**
- Before download: `INSERT INTO videos` if not exists, then `INSERT INTO jobs (status='pending')`
- On download start: `UPDATE jobs SET status='downloading'`
- On download success: `UPDATE jobs SET status='downloaded', source_file_path=...`
- On download failure: `UPDATE jobs SET status='failed', error_message=...`
- Increment `channels.uploads_today` after each successful download

**What (fire webhooks per destination):**
- After status=`downloaded`: query destinations for this job's pipeline
- For each enabled destination: fire webhook to `destination.n8n_webhook_url`
  - Payload includes `job_id`, `destination_id`, `file_path` (now pointing to source, not processed)
- Update job status to `uploading` after all webhooks fired
  - NOTE: This changes once processor is built (watcher will set `downloaded`, processor sets `uploading`)

**Reference:** [DATA_FLOW.md](DATA_FLOW.md) Section 2  
**Test:**
- Add test channel via DB (INSERT directly)
- Run watcher
- Verify job record created in `jobs` table with correct status transitions

---

### Step 2.2 — Remove JSON config dependencies from Dockerfile
**Status:** TODO  
**File:** `Dockerfile` (watcher)  
**What:**
- Remove any COPY of `channel_monitor_config.json` or `n8n_webhook_config.json`
- Ensure only `headless_watcher.py` is copied into image

---

## Phase 3 — Dashboard Rebuild

### Step 3.1 — Flask app skeleton with SQLite
**Status:** TODO  
**File:** `dashboard/app.py`  
**What:**
- Create new `app.py` from scratch (keep the Docker log reader utility)
- Import `models.py` and call `init_db()` on startup
- Register all API blueprints (or put all routes in app.py for simplicity)
- Add `/api/callback` route
- Add `/api/queue/stream` SSE route
- Keep the Docker log reader (`_read_docker_logs`) function unchanged

**Reference:** [API_CONTRACTS.md](API_CONTRACTS.md)  
**Test:** `python app.py` runs without errors, `curl http://localhost:8080/api/pipelines` returns `[]`.

---

### Step 3.2 — Base template and navigation
**Status:** TODO  
**File:** `dashboard/templates/base.html`  
**What:**
- Dark theme layout
- TailwindCSS via CDN
- HTMX + HTMX SSE extension via CDN
- Navigation bar with 4 links (Pipelines, Queue, History, Logs)
- Flash message area

---

### Step 3.3 — Pipelines page
**Status:** TODO  
**Files:** `dashboard/templates/pipelines.html`, pipeline API routes  
**What:**
- Pipeline accordion list
- Create pipeline form (inline, HTMX)
- Channel management per pipeline (add/delete/toggle/edit)
- Destination management per pipeline
- Processing steps management per pipeline (with step-type-aware params form)

**Reference:** [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md) Section 2  

---

### Step 3.4 — Queue page with SSE
**Status:** TODO  
**Files:** `dashboard/templates/queue.html`, SSE endpoint  
**What:**
- Job table with status badges
- SSE connection via HTMX SSE extension
- Manual trigger form
- Status color coding

**Reference:** [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md) Section 3  

---

### Step 3.5 — History page
**Status:** TODO  
**Files:** `dashboard/templates/history.html`  
**What:**
- Upload results table
- Platform/status/pipeline filters (HTMX)
- Row expand for AI metadata details

---

### Step 3.6 — Logs page
**Status:** TODO  
**Files:** `dashboard/templates/logs.html`  
**What:**
- Log viewer with auto-refresh (5s polling)
- Container selector (watcher / processor / both)
- Color-coded log levels
- Auto-scroll to bottom

---

### Step 3.7 — Dashboard `requirements.txt` update
**Status:** TODO  
**File:** `dashboard/requirements.txt`  
**What:** `flask==3.1.0` only. No other dependencies.

---

## Phase 4 — Processor Container

### Step 4.1 — Create `processor/` folder and Dockerfile
**Status:** TODO  
**Files:** `processor/Dockerfile`, `processor/requirements.txt`  
**What:**
- Python 3.11-slim base
- FFmpeg from apt (CPU-only first, GPU in Step 4.3)
- requirements.txt: only `requests`

---

### Step 4.2 — Create `processor/processor.py`
**Status:** TODO  
**File:** `processor/processor.py`  
**What:**
- Poll loop: `SELECT * FROM jobs WHERE status='downloaded' LIMIT 1` every POLL_INTERVAL seconds
- Job locking: `UPDATE jobs SET status='processing' WHERE id=? AND status='downloaded'` (atomic)
- Load pipeline's processing_steps from DB (global + destination-specific)
- Execute step chain per destination (see Phase 4 step logic below)
- Write output files to `/downloads/job_{id}/{platform}.mp4`
- Insert rows into `job_outputs`
- Update job status to `processed`
- Fire webhooks to n8n (per destination)
- Update job status to `uploading`
- Error handling: set status=`failed` with stderr message

**Step execution logic:**
```
For each job:
  1. Get global steps (destination_id IS NULL), sorted by step_order
  2. Apply global steps to source.mp4 → intermediate.mp4
  3. For each destination:
     a. Get destination-specific steps, sorted by step_order
     b. Apply to intermediate.mp4 → {platform}.mp4
     c. INSERT job_outputs row
  4. Fire webhook to n8n for each destination
  5. UPDATE jobs SET status='uploading'
```

**Reference:** [PROCESSING_PIPELINE.md](PROCESSING_PIPELINE.md), [DATA_FLOW.md](DATA_FLOW.md)  

---

### Step 4.3 — Add GPU support (optional, after CPU works)
**Status:** TODO (after 4.2 is working)  
**File:** `processor/Dockerfile`, `docker-compose.yml`  
**What:**
- Switch to static FFmpeg build with NVENC support
- Add GPU device reservation to docker-compose.yml processor service
- Test `h264_nvenc` availability, auto-fallback to `libx264`

---

### Step 4.4 — Create `processor/assets/` folder
**Status:** TODO  
**Files:** `processor/assets/.gitkeep`  
**What:**
- Empty folder for watermark images, intro/outro clips
- Bind-mounted into processor container at `/app/assets/`
- Add `processor/assets/*.mp4` to `.gitignore` (large files)

---

## Phase 5 — n8n Workflow Update

### Step 5.1 — Update workflow: add destination_id to callback
**Status:** TODO (partial — workflow.json already has OpenRouter node)  
**File:** `n8n/workflow.json`  
**What:**
- Verify Node 2 (Prepare Video Data) passes through `destination_id` correctly
- Verify Node 7 (Callback) includes `destination_id` in POST body
- Verify callback URL points to `http://dashboard:8080/api/callback`
- Test workflow with a sample payload using n8n's manual trigger

**Reference:** [N8N_WORKFLOW.md](N8N_WORKFLOW.md)  

---

### Step 5.2 — Configure n8n credentials
**Status:** TODO  
**What:**
- Add OpenRouter API key credential
- Add YouTube OAuth2 credential (requires Google Cloud project setup)
- Activate the workflow

**Reference:** [N8N_WORKFLOW.md](N8N_WORKFLOW.md) Section 3  

---

### Step 5.3 — Test n8n end-to-end with a mock webhook
**Status:** TODO  
**What:**
- Use n8n's built-in "Test Workflow" to send a sample payload
- Verify AI enrichment works (check execution details)
- Verify YouTube upload succeeds with test video
- Verify callback is received by dashboard

---

## Phase 6 — Integration Test

### Step 6.1 — Full system smoke test
**Status:** TODO  
**What:**
1. `docker compose up -d --build`
2. Open `http://localhost:8080/pipelines`
3. Create a test pipeline
4. Add the Manhwa Fresh channel (monitor mode)
5. Add YouTube destination
6. Add one processing step: trim (0–10s) for testing
7. Navigate to Queue page
8. Use Manual Trigger with a known video URL
9. Watch job progress through all status transitions in real time
10. Verify upload appears in History with AI-enriched title

**Pass criteria:**
- [ ] Job reaches `done` status
- [ ] Upload appears in History page
- [ ] AI title is different from original title
- [ ] Callback was received (check upload_results table)
- [ ] Log viewer shows watcher and processor logs

---

### Step 6.2 — Monitor mode smoke test
**Status:** TODO  
**What:**
1. Set channel to monitor mode
2. Wait one CHECK_INTERVAL cycle (or reduce to 1 minute temporarily)
3. Verify a new video is detected, job created, processed, uploaded
4. Verify `channels.last_check` is updated

---

### Step 6.3 — Backfill smoke test
**Status:** TODO  
**What:**
1. Add a channel in backfill mode with `daily_limit=3`
2. Verify backfill_queue is populated
3. Verify exactly 3 videos are downloaded
4. Stop watcher, restart — verify it resumes from where it left off

---

## Dependency Graph

```
1.1 (models.py)
├── 1.2 (migrate config)
├── 1.3 (docker-compose.yml)
├── 2.1 (watcher SQLite migration) ← depends on 1.1
│   └── 2.2 (watcher Dockerfile cleanup)
├── 3.1 (Flask app skeleton) ← depends on 1.1
│   ├── 3.2 (base template)
│   ├── 3.3 (pipelines page) ← depends on 3.2
│   ├── 3.4 (queue + SSE) ← depends on 3.2
│   ├── 3.5 (history page) ← depends on 3.2
│   └── 3.6 (logs page) ← depends on 3.2
└── 4.1 (processor Dockerfile) ← depends on 1.3
    └── 4.2 (processor.py) ← depends on 1.1, 4.1
        └── 4.3 (GPU support) ← depends on 4.2
            └── 5.1 (n8n workflow update) ← depends on 3.1, 4.2
                └── 5.2 (n8n credentials)
                    └── 5.3 (n8n test)
                        └── 6.1 (full integration test)
```

---

## File Creation Checklist

| File                              | Phase | Status |
|-----------------------------------|-------|--------|
| `dashboard/models.py`             | 1.1   | TODO   |
| `dashboard/migrate_config.py`     | 1.2   | TODO   |
| `docker-compose.yml` (update)     | 1.3   | TODO   |
| `db/.gitkeep`                     | 1.4   | TODO   |
| `.env.example`                    | 1.4   | TODO   |
| `headless_watcher.py` (update)    | 2.1   | TODO   |
| `Dockerfile` (update)             | 2.2   | TODO   |
| `dashboard/app.py` (rebuild)      | 3.1   | TODO   |
| `dashboard/templates/base.html`   | 3.2   | TODO   |
| `dashboard/templates/pipelines.html` | 3.3 | TODO  |
| `dashboard/templates/queue.html`  | 3.4   | TODO   |
| `dashboard/templates/history.html`| 3.5   | TODO   |
| `dashboard/templates/logs.html`   | 3.6   | TODO   |
| `dashboard/requirements.txt` (update) | 3.7 | TODO |
| `processor/Dockerfile`            | 4.1   | TODO   |
| `processor/requirements.txt`      | 4.1   | TODO   |
| `processor/processor.py`          | 4.2   | TODO   |
| `processor/assets/.gitkeep`       | 4.4   | TODO   |
| `n8n/workflow.json` (update)      | 5.1   | TODO   |

---

*Start with Step 1.1: `dashboard/models.py`*
