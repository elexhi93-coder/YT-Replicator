# SESSION TASK — Step 3.1: Flask App Skeleton + All API Routes

## Your job in this session
Rebuild `dashboard/app.py` from scratch. Create a Flask app with all API routes defined (but returning stub responses for routes whose business logic is in later steps).

## Read these files first (in this order):
1. `docs/API_CONTRACTS.md` — every endpoint, method, request body, response format
2. `docs/DATABASE_SCHEMA.md` — tables you will query
3. `dashboard/models.py` — `get_db()` to use in every route
4. Current `dashboard/app.py` — what exists now (note what to keep vs replace)

## Hard constraints:
- Flask only. No FastAPI, no Django.
- No Flask-SQLAlchemy, no marshmallow — raw `sqlite3` via `get_db()` only
- All JSON responses use `flask.jsonify()`
- All DB connections must be opened and closed per-request (no persistent connection)
- Use `g` from Flask for per-request DB: `g.db = get_db()` in `before_request`, close in `teardown_request`
- SSE endpoint at `GET /api/events` using `text/event-stream` content type
- App must read `PORT` env var (default 8080) and `DB_PATH` env var
- `init_db()` must be called on startup before the first request

## File to rebuild:
`dashboard/app.py`

## Required routes (from API_CONTRACTS.md):

### Pipelines
- `GET /api/pipelines` — list all pipelines with source/dest counts
- `POST /api/pipelines` — create pipeline
- `GET /api/pipelines/<id>` — get single pipeline with full detail
- `PUT /api/pipelines/<id>` — update pipeline name/status
- `DELETE /api/pipelines/<id>` — soft delete (set status='deleted')
- `POST /api/pipelines/<id>/run` — queue a manual run

### Sources
- `GET /api/pipelines/<id>/sources` — list sources for pipeline
- `POST /api/pipelines/<id>/sources` — add source
- `PUT /api/sources/<id>` — update source
- `DELETE /api/sources/<id>` — delete source

### Destinations
- `GET /api/pipelines/<id>/destinations` — list destinations
- `POST /api/pipelines/<id>/destinations` — add destination
- `PUT /api/destinations/<id>` — update destination
- `DELETE /api/destinations/<id>` — delete destination

### Queue / Jobs
- `GET /api/queue` — active jobs (status in queued, downloading, processing, uploading)
- `GET /api/history` — completed/failed jobs with pagination (?page=1&limit=50)
- `POST /api/jobs/<id>/retry` — re-queue a failed job
- `DELETE /api/jobs/<id>` — cancel a queued job

### Callback (called by n8n)
- `POST /api/callback` — update job status from n8n (see API_CONTRACTS.md for payload)

### SSE
- `GET /api/events` — Server-Sent Events stream; yields queue state every 2 seconds

### Pages (serve HTML templates)
- `GET /` — redirect to `/pipelines`
- `GET /pipelines` — render `pipelines.html`
- `GET /queue` — render `queue.html`
- `GET /history` — render `history.html`
- `GET /logs` — render `logs.html`

## For this step, stub responses are OK for:
- All page routes (return `render_template('soon.html')` with a simple placeholder)
- `POST /api/pipelines/<id>/run` (return `{"status": "queued"}`)
- `/api/events` SSE stub (just yield a heartbeat comment every 2s)

## Full implementation required for:
- All CRUD routes (pipelines, sources, destinations) — must actually query the DB
- `GET /api/queue` and `GET /api/history` — must query `download_jobs`
- `POST /api/callback` — must update job status in DB

## Test / pass criteria:
```bash
cd dashboard && DB_PATH=./test.db python app.py
```
Then in another terminal:
```bash
curl http://localhost:8080/api/pipelines
# Must return: {"pipelines": []}

curl -X POST http://localhost:8080/api/pipelines \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Pipeline"}'
# Must return: {"id": 1, "name": "Test Pipeline", "status": "active"}

curl http://localhost:8080/api/pipelines
# Must return: {"pipelines": [{"id": 1, "name": "Test Pipeline", ...}]}
```

## When done:
- Show the full `dashboard/app.py`
- Show the curl test outputs
- Do NOT build anything else in this session
