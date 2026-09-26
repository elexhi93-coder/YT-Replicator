# SESSION TASK — Step 2.1: Watcher — Migrate JSON → SQLite

## Your job in this session
Rewrite `headless_watcher.py` to use SQLite instead of `channel_monitor_config.json`.

## Read these files first (in this order):
1. `docs/DATABASE_SCHEMA.md` — focus on `sources`, `download_jobs`, `event_log` tables
2. `docs/DATA_FLOW.md` — sections: "Monitor Flow", "Backfill Flow", "Failure Handling"
3. `dashboard/models.py` — `get_db()` function you must import and use
4. Current `headless_watcher.py` — the existing working code you are migrating

## Hard constraints:
- Keep ALL existing functionality: monitor mode, backfill mode, webhook firing
- Replace ALL reads/writes to `channel_monitor_config.json` with SQLite queries
- Import `get_db` from `dashboard.models` (adjust import path if needed: `sys.path`)
- Use `DB_PATH` env var (already used in `get_db()`)
- All job status updates must write to `download_jobs` table
- All significant events must write to `event_log` table
- No new external packages — `sqlite3`, `requests`, `yt-dlp` only
- Maintain backward compatibility with the n8n webhook payload format

## What must change (line by line mapping):

### REMOVE:
- All code that reads `channel_monitor_config.json`
- All code that writes back to `channel_monitor_config.json`
- The `load_config()` / `save_config()` functions

### ADD:
- `get_active_sources()` — query `SELECT * FROM sources WHERE enabled=1`
- `create_download_job(source_id, video_id, title, url)` — inserts into `download_jobs` with `status='queued'`
- `update_job_status(job_id, status, error=None)` — updates `download_jobs` status + `updated_at`
- `log_event(source_id, event_type, message)` — inserts into `event_log`
- `video_already_downloaded(source_id, video_id)` — checks `download_jobs` for existing complete record

### KEEP (no change needed):
- `check_for_new_videos(source)` — same yt-dlp logic, just feed it `source['channel_id']`
- `fire_webhook(payload)` — same requests.post logic
- Main loop with `--mode monitor` / `--mode backfill` CLI args
- Sleep interval logic

## Webhook payload format (must not change):
```json
{
  "job_id": 123,
  "source_id": 1,
  "video_id": "abc123",
  "title": "Video Title",
  "url": "https://www.youtube.com/watch?v=abc123",
  "channel_name": "Channel Name",
  "mode": "monitor"
}
```

## Test / pass criteria:
```bash
DB_PATH=./db/app.db python headless_watcher.py --mode backfill --dry-run
```
Output must show:
- "Loaded X active source(s) from database"
- For each source: "Checking [channel_name]..."
- No JSON file reads (grep the code for `open(` to verify)

## When done:
- Show the full updated `headless_watcher.py`
- Show a dry-run output
- Do NOT build anything else in this session
