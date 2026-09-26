# API Contracts
## project003 — All HTTP Endpoints and Payload Specifications

**Status:** LOCKED — all changes require updating this document first  
**Base URL (dashboard):** `http://dashboard:8080` (internal) / `http://<server-ip>:8080` (LAN)  
**Base URL (n8n):** `http://n8n:5678` (internal) / `http://<server-ip>:5678` (LAN)

---

## 1. Dashboard REST API

All dashboard endpoints return JSON unless noted. All POST/PUT bodies are JSON unless noted as `application/x-www-form-urlencoded` (HTMX form submissions).

### Error Response Format (all endpoints)
```json
{
  "error": "Human-readable message",
  "code": "MACHINE_READABLE_CODE"
}
```

---

### 1.1 Pipelines

#### `GET /api/pipelines`
Returns all pipelines with summary stats.

**Response 200:**
```json
[
  {
    "id": 1,
    "name": "Manhwa Fresh → Multi-Platform",
    "description": "Manhwa channel backfill and monitor",
    "active": true,
    "created_at": "2026-04-22T10:00:00",
    "channel_count": 2,
    "destination_count": 3,
    "jobs_pending": 5,
    "jobs_done_today": 12
  }
]
```

---

#### `POST /api/pipelines`
Create a new pipeline.

**Request body (JSON):**
```json
{
  "name": "My Pipeline",
  "description": "Optional notes"
}
```

**Response 201:**
```json
{
  "id": 2,
  "name": "My Pipeline",
  "description": "Optional notes",
  "active": true,
  "created_at": "2026-04-22T10:05:00"
}
```

**Errors:**
- `400 MISSING_NAME` — name field is empty or missing

---

#### `PUT /api/pipelines/<id>`
Update a pipeline's name, description, or active state.

**Request body (JSON, all fields optional):**
```json
{
  "name": "Updated Name",
  "description": "New description",
  "active": false
}
```

**Response 200:** Updated pipeline object (same shape as GET)

**Errors:**
- `404 NOT_FOUND` — pipeline id does not exist

---

#### `DELETE /api/pipelines/<id>`
Delete a pipeline and all its channels, destinations, steps, jobs, and results (CASCADE).

**Response 204:** No body

**Errors:**
- `404 NOT_FOUND`

---

### 1.2 Channels

#### `GET /api/channels`
Returns all channels. Optional query params: `?pipeline_id=1`

**Response 200:**
```json
[
  {
    "id": 1,
    "pipeline_id": 1,
    "pipeline_name": "Manhwa Fresh → Multi-Platform",
    "name": "Manhwa Fresh",
    "channel_id": "UCz3IjVYoX-tmmPPTedhXQEQ",
    "url": "https://www.youtube.com/@ManhwaFresh",
    "mode": "backfill",
    "backfill_complete": false,
    "backfill_queue_size": 234,
    "daily_limit": 10,
    "uploads_today": 4,
    "last_check": "2026-04-22T09:00:00",
    "active": true,
    "created_at": "2026-04-22T10:00:00"
  }
]
```

---

#### `POST /api/channels`
Add a channel to a pipeline.

**Request body (JSON):**
```json
{
  "pipeline_id": 1,
  "name": "Manhwa Fresh",
  "url": "https://www.youtube.com/@ManhwaFresh",
  "mode": "backfill",
  "daily_limit": 10
}
```

**Field rules:**
- `mode`: `"backfill"` or `"monitor"` — required
- `daily_limit`: integer 1–100, default 10
- `url`: Must be a valid YouTube channel URL (channel ID, handle, or `/channel/UC...` format)

**Response 201:**
```json
{
  "id": 3,
  "channel_id": "UCz3IjVYoX-tmmPPTedhXQEQ",
  ...
}
```

**Errors:**
- `400 INVALID_URL` — cannot extract channel ID from URL
- `400 DUPLICATE_CHANNEL` — channel already exists in any pipeline
- `404 PIPELINE_NOT_FOUND`

---

#### `PUT /api/channels/<id>`
Update channel config (mode, daily_limit, active).

**Request body (JSON, all optional):**
```json
{
  "mode": "monitor",
  "daily_limit": 20,
  "active": false
}
```

**Response 200:** Updated channel object

---

#### `DELETE /api/channels/<id>`
Remove a channel from a pipeline.

**Response 204:** No body

---

### 1.3 Destinations

#### `GET /api/destinations?pipeline_id=<id>`
Returns all destinations for a pipeline.

**Response 200:**
```json
[
  {
    "id": 1,
    "pipeline_id": 1,
    "platform": "youtube",
    "label": "Main YouTube Channel",
    "n8n_webhook_url": "http://n8n:5678/webhook/pipeline1-youtube",
    "enabled": true,
    "created_at": "2026-04-22T10:00:00"
  }
]
```

---

#### `POST /api/destinations`
Add a destination to a pipeline.

**Request body (JSON):**
```json
{
  "pipeline_id": 1,
  "platform": "youtube",
  "label": "Main YouTube Channel",
  "n8n_webhook_url": "http://n8n:5678/webhook/pipeline1-youtube"
}
```

**Allowed platforms:** `youtube`, `dailymotion`, `facebook`, `tiktok`

**Response 201:** Created destination object

**Errors:**
- `400 INVALID_PLATFORM`
- `400 INVALID_WEBHOOK_URL`
- `404 PIPELINE_NOT_FOUND`

---

#### `PUT /api/destinations/<id>`
Update destination (label, webhook URL, enabled).

**Response 200:** Updated destination object

---

#### `DELETE /api/destinations/<id>`
Remove a destination.

**Response 204:** No body

---

### 1.4 Processing Steps

#### `GET /api/steps?pipeline_id=<id>`
Returns all processing steps for a pipeline, ordered by `step_order`.

**Response 200:**
```json
[
  {
    "id": 1,
    "pipeline_id": 1,
    "destination_id": null,
    "destination_label": null,
    "step_order": 0,
    "step_type": "trim",
    "params": {"start": 0, "end": 180},
    "enabled": true
  },
  {
    "id": 2,
    "pipeline_id": 1,
    "destination_id": 2,
    "destination_label": "TikTok",
    "step_order": 1,
    "step_type": "crop",
    "params": {"aspect_ratio": "9:16", "method": "center"},
    "enabled": true
  }
]
```

---

#### `POST /api/steps`
Add a processing step.

**Request body (JSON):**
```json
{
  "pipeline_id": 1,
  "destination_id": null,
  "step_order": 0,
  "step_type": "trim",
  "params": {"start": 0, "end": 180}
}
```

**`step_type` allowed values and their `params` shapes are defined in [PROCESSING_PIPELINE.md](PROCESSING_PIPELINE.md)**

**Response 201:** Created step object

---

#### `PUT /api/steps/<id>`
Update a step's order, params, or enabled state.

**Response 200:** Updated step object

---

#### `DELETE /api/steps/<id>`

**Response 204:** No body

---

### 1.5 Jobs

#### `GET /api/jobs`
Returns jobs with optional filters.

**Query params:**
- `?status=downloading` — filter by status
- `?pipeline_id=1` — filter by pipeline
- `?limit=50` — max rows (default 50, max 200)
- `?offset=0` — pagination offset

**Response 200:**
```json
[
  {
    "id": 42,
    "video_id": 15,
    "youtube_video_id": "dQw4w9WgXcQ",
    "original_title": "Chapter 47 - The Final Battle",
    "pipeline_id": 1,
    "pipeline_name": "Manhwa Fresh → Multi-Platform",
    "status": "processing",
    "source_file_path": "/downloads/job_42/source.mp4",
    "error_message": "",
    "retry_count": 0,
    "created_at": "2026-04-22T10:00:00",
    "updated_at": "2026-04-22T10:01:30",
    "outputs": [
      {"destination_id": 1, "platform": "youtube", "file_path": "/downloads/job_42/youtube.mp4"}
    ],
    "upload_results": []
  }
]
```

---

#### `GET /api/jobs/<id>`
Returns a single job with full detail (outputs + upload results).

**Response 200:** Full job object (same shape as above)

**Errors:**
- `404 NOT_FOUND`

---

#### `POST /api/jobs`
Manually trigger a download+process+upload job for a single video URL.

**Request body (JSON):**
```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "pipeline_id": 1
}
```

**Response 202:**
```json
{
  "job_id": 43,
  "status": "pending",
  "message": "Job created. Watcher will process it shortly."
}
```

**Errors:**
- `400 INVALID_URL`
- `404 PIPELINE_NOT_FOUND`

---

### 1.6 History

#### `GET /api/history`
Returns completed upload results for the history page.

**Query params:**
- `?platform=youtube` — filter by platform
- `?status=success` — filter by status
- `?limit=50` — max rows (default 50, max 500)
- `?offset=0`

**Response 200:**
```json
[
  {
    "id": 1,
    "job_id": 42,
    "destination_id": 1,
    "platform": "youtube",
    "status": "success",
    "upload_url": "https://youtube.com/watch?v=xxx",
    "ai_used": true,
    "ai_title": "Epic Final Battle - Chapter 47 [Must Watch]",
    "ai_description": "Watch the most epic battle...",
    "ai_tags": ["manhwa", "anime", "chapter47"],
    "original_title": "Chapter 47 - The Final Battle",
    "channel_name": "Manhwa Fresh",
    "created_at": "2026-04-22T10:05:00"
  }
]
```

---

### 1.7 Logs

#### `GET /api/logs`
Returns recent log lines from watcher and processor containers via Docker socket.

**Query params:**
- `?container=watcher` — `watcher` | `processor` | `all` (default: `all`)
- `?tail=120` — number of lines (default 120, max 500)

**Response 200:**
```json
{
  "lines": [
    {"container": "watcher", "text": "2026-04-22 10:00:00 [INFO] Checking channel UCz3..."},
    {"container": "processor", "text": "2026-04-22 10:01:00 [INFO] Processing job 42..."}
  ]
}
```

---

### 1.8 SSE: Live Queue Stream

#### `GET /api/queue/stream`
Server-Sent Events endpoint. Pushes job status updates to the browser in real time.

**Response:** `Content-Type: text/event-stream`

**Event format:**
```
event: job_update
data: {"job_id": 42, "status": "processing", "updated_at": "2026-04-22T10:01:30"}

event: job_update
data: {"job_id": 42, "status": "done", "updated_at": "2026-04-22T10:03:00"}

event: heartbeat
data: {"ts": "2026-04-22T10:03:05"}
```

Heartbeat is sent every 15 seconds to keep the connection alive. Client reconnects automatically on disconnect.

---

### 1.9 Internal: Upload Callback

#### `POST /api/callback`
Called by n8n after each upload completes (success or failure). This is an internal endpoint — not user-facing.

**Caller:** n8n (HTTP Request node at end of workflow)

**Request body (JSON):**
```json
{
  "job_id": 42,
  "destination_id": 1,
  "platform": "youtube",
  "status": "success",
  "upload_url": "https://youtube.com/watch?v=xxx",
  "error_message": "",
  "ai_used": true,
  "ai_title": "Epic Final Battle - Chapter 47",
  "ai_description": "Watch the most epic...",
  "ai_tags": ["manhwa", "chapter47"]
}
```

**Response 200:**
```json
{"ok": true}
```

**Side effects:**
1. Inserts a row into `upload_results`
2. If ALL destinations for the job have a result, updates `jobs.status` to `done` or `partial`
3. SSE stream broadcasts `job_update` event

**Errors:**
- `400 MISSING_JOB_ID`
- `404 JOB_NOT_FOUND`
- `404 DESTINATION_NOT_FOUND`

---

## 2. n8n Webhook (Watcher → n8n)

### `POST http://n8n:5678/webhook/{webhook-path}`

This is the webhook fired by the watcher after each video download. The `webhook-path` is the value stored in `destinations.n8n_webhook_url`.

**Fired by:** `watcher` container  
**Received by:** n8n Webhook Trigger node

**Request body:**
```json
{
  "job_id": 42,
  "pipeline_id": 1,
  "destination_id": 1,
  "video_id": "dQw4w9WgXcQ",
  "original_title": "Chapter 47 - The Final Battle",
  "original_description": "Full episode. Chapter 47...",
  "channel_id": "UCz3IjVYoX-tmmPPTedhXQEQ",
  "channel_name": "Manhwa Fresh",
  "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "file_path": "/shared/downloads/job_42/youtube.mp4",
  "duration": 243,
  "thumbnail_path": "/shared/downloads/job_42/thumbnail.jpg",
  "platform": "youtube",
  "timestamp": "2026-04-22T10:00:00Z"
}
```

**Key field notes:**
- `file_path` uses the n8n-internal path (`/shared/downloads/`) not the processor-internal path (`/downloads/`)
- `file_path` points to the PROCESSED output file, not the source file
- One webhook is fired **per destination** per job. If a job has 3 destinations, 3 webhooks are fired.
- `job_id` must be included in n8n's callback to the dashboard

---

## 3. HTMX Endpoints (Server-Side HTML Fragments)

These endpoints are called by HTMX `hx-get`/`hx-post` attributes and return HTML fragments, not JSON.

| Method | Path                        | Returns                        | Triggered by              |
|--------|-----------------------------|--------------------------------|---------------------------|
| GET    | /fragments/pipeline-row/<id>| `<tr>` for pipeline table     | After create/edit pipeline|
| GET    | /fragments/channel-row/<id> | `<tr>` for channel table      | After add channel         |
| GET    | /fragments/queue            | Queue table body `<tbody>`    | SSE job update event      |
| GET    | /fragments/history          | History table body `<tbody>`  | Page load + filter change |
| GET    | /fragments/log-lines        | `<div>` with log lines        | Log poll interval         |

These are implementation-level endpoints. They do not need to be consumed by anything other than HTMX in the browser.

---

*Next: [DATA_FLOW.md](DATA_FLOW.md)*
