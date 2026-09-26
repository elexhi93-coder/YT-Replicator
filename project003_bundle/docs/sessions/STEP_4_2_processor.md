# SESSION TASK — Step 4.2: Processor — FFmpeg Job Runner

## Your job in this session
Implement the full `processor/processor.py` — the job runner that polls for downloaded videos and applies FFmpeg processing steps.

## Read these files first (in this order):
1. `docs/PROCESSING_PIPELINE.md` — ALL 9 step types with exact FFmpeg command templates
2. `docs/DATABASE_SCHEMA.md` — `process_jobs`, `pipeline_steps`, `download_jobs` tables
3. `docs/DATA_FLOW.md` — section: "Processing Flow"
4. `processor/processor.py` — the skeleton from Step 4.1 that you will fill in

## Hard constraints:
- All FFmpeg calls via `subprocess.run()` — never `os.system()`, never shell=True with user input
- Validate all file paths before passing to FFmpeg (must start with `DOWNLOADS_PATH`)
- Status transitions: `queued → downloading → downloaded → processing → processed → uploading`
- If any FFmpeg step fails (non-zero exit code), set job status to `failed` and log stderr
- Poll interval: 5 seconds (from `POLL_INTERVAL` env var)
- After processing, call `POST /api/callback` on the dashboard to update job status
- Never delete original downloaded files — output to a new file with suffix e.g. `_processed.mp4`

## What to implement:

### `poll_jobs()` function
```python
def poll_jobs():
    db = get_db()
    jobs = db.execute(
        "SELECT dj.*, s.pipeline_id FROM download_jobs dj "
        "JOIN sources s ON dj.source_id = s.id "
        "WHERE dj.status = 'downloaded'"
    ).fetchall()
    for job in jobs:
        process_job(job)
    db.close()
```

### `process_job(job)` function
1. Set job status to `processing`
2. Load `pipeline_steps` for `job['pipeline_id']` ordered by `step_order`
3. For each step, call the appropriate step handler
4. If all steps succeed, set status to `processed` and notify dashboard
5. If any step fails, set status to `failed`, log error

### Step handlers — one function per step type:
(All FFmpeg command templates are in `PROCESSING_PIPELINE.md`)

| Function | Step type | What it does |
|----------|-----------|-------------|
| `step_trim(job, step)` | `trim` | Cut to start_time/end_time |
| `step_watermark(job, step)` | `watermark` | Overlay image at position |
| `step_crop(job, step)` | `crop` | Crop to aspect ratio (e.g. 9:16 for TikTok) |
| `step_resize(job, step)` | `resize` | Scale to target resolution |
| `step_add_intro(job, step)` | `add_intro` | Prepend intro video |
| `step_add_outro(job, step)` | `add_outro` | Append outro video |
| `step_subtitle(job, step)` | `subtitle` | Burn in subtitle file |
| `step_audio_normalize(job, step)` | `audio_normalize` | Normalize audio loudness |
| `step_thumbnail(job, step)` | `thumbnail` | Extract frame as thumbnail |

Each step receives `job` (dict from DB) and `step` (dict with `params` JSON column parsed).

### `run_ffmpeg(args_list)` helper
```python
def run_ffmpeg(args):
    result = subprocess.run(['ffmpeg', '-y'] + args,
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-500:]}")
    return result
```

### `notify_dashboard(job_id, status, output_path=None)` function
```python
import requests
def notify_dashboard(job_id, status, output_path=None):
    requests.post(f"{DASHBOARD_URL}/api/callback", json={
        "job_id": job_id,
        "status": status,
        "output_path": output_path
    }, timeout=5)
```

## Test / pass criteria:
1. Insert a test `download_jobs` row with `status='downloaded'` and a real video file path
2. Run the processor: `python processor/processor.py`
3. Within one poll cycle, the job status changes to `processing` then `processed`
4. A new output file exists at `<original>_processed.mp4`

## When done:
- Show the full `processor/processor.py`
- Show a test run output with at least one job processed
- Do NOT build anything else in this session
