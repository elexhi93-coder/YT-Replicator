# Data Flow
## project003 — Step-by-Step Scenarios

**Status:** LOCKED — reflects the agreed architecture  
**Reference:** See [ARCHITECTURE.md](ARCHITECTURE.md) for container overview, [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for table details

---

## 1. Job Status State Machine

Every job follows exactly this lifecycle. No other status transitions are valid.

```
                    ┌──────────┐
              ┌────▶│  failed  │◀──────────────────────┐
              │     └──────────┘                        │
              │                                         │
[created] ───▶ pending ──▶ downloading ──▶ downloaded ──▶ processing ──▶ processed ──▶ uploading ──▶ done
                                                                                                   │
                                                                                              partial
```

| Status       | Set by    | Meaning                                                  |
|--------------|-----------|----------------------------------------------------------|
| `pending`    | dashboard (manual trigger) or watcher (before download)  | Job exists, download not started yet |
| `downloading`| watcher   | yt-dlp is currently downloading the video               |
| `downloaded` | watcher   | Source file on disk, ready for processor                |
| `processing` | processor | FFmpeg is running                                       |
| `processed`  | processor | All output files created                                |
| `uploading`  | watcher (after firing last webhook) | n8n triggered for all destinations |
| `done`       | dashboard (via /api/callback) | All destinations successfully uploaded |
| `partial`    | dashboard (via /api/callback) | At least one success + at least one failure |
| `failed`     | watcher or processor | Terminal error, see `error_message` field |

---

## 2. Scenario A — Monitor Mode: New Video Detected

This is the primary 24/7 flow. A channel is in monitor mode (backfill complete).

### Step-by-Step:

**Every 15 minutes (watcher loop):**

```
Step 1: Watcher reads SQLite
────────────────────────────
  SELECT * FROM channels WHERE active=1 AND mode='monitor'
  For each channel:
    IF (now - last_check) >= CHECK_INTERVAL minutes → check this channel

Step 2: Watcher fetches YouTube RSS feed
─────────────────────────────────────────
  URL: https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}
  Parse XML for video IDs and published dates
  Compare against videos.youtube_video_id (already seen)
  Result: list of NEW video IDs not yet in DB

Step 3: Watcher creates job records (one per new video × pipeline destinations)
─────────────────────────────────────────────────────────────────────────────────
  For each new video:
    INSERT INTO videos (channel_id, youtube_video_id, original_title, ...)
    INSERT INTO jobs (video_id, pipeline_id, status='pending', ...)
  UPDATE channels SET last_check=now WHERE id={id}

Step 4: Watcher downloads the video
─────────────────────────────────────
  UPDATE jobs SET status='downloading' WHERE id={job_id}
  Run yt-dlp:
    Output template: /downloads/job_{job_id}/source.%(ext)s
    Format: bestvideo[height<=1080]+bestaudio/best
    Write thumbnail
  UPDATE jobs SET status='downloaded', source_file_path='/downloads/job_{job_id}/source.mp4'
  Increment channels.uploads_today

  ┌─ IF yt-dlp fails:
  │   UPDATE jobs SET status='failed', error_message='{error}'
  └─ END

Step 5: Processor picks up the job (polling every 5 seconds)
──────────────────────────────────────────────────────────────
  SELECT jobs.* FROM jobs WHERE status='downloaded' ORDER BY created_at ASC LIMIT 1
  UPDATE jobs SET status='processing'
  Read pipeline processing_steps (global + destination-specific)
  Run FFmpeg steps in order (see PROCESSING_PIPELINE.md)
  For each destination:
    Write output file: /downloads/job_{job_id}/{platform}.mp4
    INSERT INTO job_outputs (job_id, destination_id, file_path, file_size_bytes)
  UPDATE jobs SET status='processed'

  ┌─ IF FFmpeg fails:
  │   UPDATE jobs SET status='failed', error_message='{ffmpeg_stderr}'
  └─ END

Step 6: Watcher (or processor) fires webhooks to n8n
──────────────────────────────────────────────────────
  NOTE: This is triggered by polling. Either the watcher polls for 'processed' jobs,
        OR the processor fires the webhook directly after step 5.
  *** DECISION: Processor fires the webhook directly. ***
  
  For each destination (from job_outputs):
    POST http://n8n:5678/webhook/{destination.webhook_path}
    Body: see API_CONTRACTS.md Section 2
  UPDATE jobs SET status='uploading'

Step 7: n8n workflow executes
──────────────────────────────
  1. Webhook trigger received
  2. Prepare Video Data node: validate file_path, extract fields
  3. AI: Enrich Metadata node: POST to OpenRouter (Mistral 7B free)
     Input:  original_title + channel_name
     Output: youtube_title, youtube_description, youtube_tags
  4. AI: Parse & Fallback node: handle AI failure gracefully
  5. Read File node: read video file bytes from /shared/downloads/job_{id}/{platform}.mp4
  6. Platform Upload node: upload to YouTube / Dailymotion / Facebook / TikTok
  7. Callback node: POST http://dashboard:8080/api/callback
     Body: job_id, destination_id, platform, status, upload_url, ai_title, ai_description

Step 8: Dashboard receives callback
─────────────────────────────────────
  POST /api/callback received
  INSERT INTO upload_results (job_id, destination_id, platform, status, upload_url, ai_*)
  Count upload_results for this job:
    IF all destinations have a result:
      IF all succeeded → UPDATE jobs SET status='done'
      IF any failed    → UPDATE jobs SET status='partial'
  Broadcast SSE event: {"job_id": 42, "status": "done"}

Step 9: Dashboard UI updates
──────────────────────────────
  HTMX SSE listener receives job_update event
  Fires hx-get="/fragments/queue" → refreshes queue table row
  Upload appears in History page on next navigation
```

---

## 3. Scenario B — Backfill Mode: Full Channel History

This flow is the same as Scenario A except Step 2. Backfill is triggered when a channel is first added with `mode=backfill`.

### Differences from Scenario A:

**Step 2 (replacement):**
```
Step 2b: Watcher builds backfill queue (FIRST TIME ONLY)
──────────────────────────────────────────────────────────
  IF channels.backfill_queue = '[]' AND backfill_complete = 0:
    Run yt-dlp flat extraction on channel URL (no download)
    Get full list of all video IDs: oldest-first (reversed from yt-dlp default)
    UPDATE channels SET backfill_queue = '["id1","id2",...]', backfill_entry_map = '{...}'
  
  Pop next N videos from queue (N = daily_limit - uploads_today):
    Pop video IDs from front of backfill_queue
    UPDATE channels SET backfill_queue = remaining_queue
  
  For each popped video:
    Continue with Step 3 (create job records, download, etc.)
  
  After loop:
    IF backfill_queue = '[]':
      UPDATE channels SET backfill_complete=1, mode='monitor'
      LOG: "Backfill complete for {channel_name}, switching to monitor mode"
```

**Daily limit behavior:**
- Watcher checks `channels.daily_limit` and `channels.uploads_today` at start of each loop
- If `uploads_today >= daily_limit`: skip this channel entirely, log "Daily limit reached"
- At midnight UTC: `uploads_today` is reset to 0 by watcher before processing

---

## 4. Scenario C — Manual Single-Video Trigger

User pastes a YouTube URL in the dashboard and clicks "Download Now".

```
Step 1: User submits form on dashboard
───────────────────────────────────────
  POST /api/jobs
  Body: {"url": "https://youtube.com/watch?v=xxx", "pipeline_id": 1}

Step 2: Dashboard validates and creates job
─────────────────────────────────────────────
  Extract video metadata (yt-dlp flat extraction, no download — just get title/duration)
  INSERT INTO videos (youtube_video_id, original_title, ...)
  INSERT INTO jobs (video_id, pipeline_id, status='pending')
  Response 202: {job_id: 43, status: 'pending'}

Step 3: Queue page shows pending job immediately
──────────────────────────────────────────────────
  SSE broadcast: {"job_id": 43, "status": "pending"}
  HTMX refreshes queue table

Step 4: Watcher picks up pending jobs
───────────────────────────────────────
  On next watcher loop iteration:
    SELECT * FROM jobs WHERE status='pending' ORDER BY created_at ASC
  Downloads, processes, fires webhook — same as Scenario A Steps 4–8
```

---

## 5. Scenario D — Upload Failure and Retry

n8n fails to upload to a platform (API error, token expired, rate limit).

```
Step 1: n8n upload node fails
───────────────────────────────
  n8n continueOnFail=true (does not crash the workflow)
  Callback node fires with:
    {"job_id": 42, "status": "failed", "error_message": "HTTP 429 Rate limited"}

Step 2: Dashboard records failure
───────────────────────────────────
  INSERT INTO upload_results (..., status='failed', error_message='HTTP 429 Rate limited')
  UPDATE jobs SET status='partial' or 'failed' (depending on other destinations)
  SSE broadcast: {"job_id": 42, "status": "partial"}

Step 3: User sees failure in History page
───────────────────────────────────────────
  Red status badge, error message shown, output file path still visible

Step 4: User retries manually (future feature — not in v1)
────────────────────────────────────────────────────────────
  POST /api/jobs/<id>/retry  → re-fires webhook to n8n for failed destinations only
  UPDATE jobs SET status='uploading', retry_count += 1
```

**Note for v1:** Automatic retry is handled by n8n's built-in retry node. Manual retry from dashboard is a v2 feature.

---

## 6. Scenario E — Container Restart Recovery

Docker restarts a container (crash, server reboot, `docker compose restart`).

### Watcher restarts:
- Reads SQLite on startup — no config lost
- Any job stuck in `downloading` status is re-queued: watcher checks for jobs with `status='downloading'` older than 30 minutes and resets them to `pending`
- Backfill queue is persisted in SQLite — picks up exactly where it left off

### Processor restarts:
- Any job stuck in `processing` status is re-queued: processor checks for jobs with `status='processing'` older than 10 minutes and resets to `downloaded`
- Output files that were partially written are deleted and re-created

### n8n restarts:
- n8n has its own persistent storage (`n8n_data` volume)
- Webhook URLs remain the same after restart
- In-progress workflow executions are lost — jobs stuck in `uploading` need manual inspection

### Dashboard restarts:
- Stateless (all state in SQLite) — restarts in seconds with no data loss
- SSE connections drop and clients reconnect automatically

---

## 7. Concurrency and Locking

### SQLite WAL Mode
With WAL (Write-Ahead Logging) enabled, SQLite allows:
- Multiple simultaneous readers
- One writer at a time (no blocking for reads during a write)

### Watcher concurrency:
- One download at a time per channel (serial per-channel loop)
- Multiple channels can download simultaneously in separate threads
- Each thread holds its SQLite write lock for < 50ms per job status update

### Processor concurrency:
- Processes one job at a time (single FFmpeg process)
- FFmpeg uses multiple CPU cores internally (`-threads 0`)
- GPU encoding via `h264_nvenc` is single-instance (GTX 1080 limitation)

### Dashboard concurrency:
- Flask serves requests concurrently via threading
- All DB reads are SELECT only — no write contention with watcher/processor during page loads

---

*Next: [CONTAINER_SPECS.md](CONTAINER_SPECS.md)*
