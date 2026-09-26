# SESSION TASK — Step 4.1: Processor Dockerfile + Requirements

## Your job in this session
Create the processor container: `processor/Dockerfile`, `processor/requirements.txt`, and the entry-point skeleton `processor/processor.py` (skeleton only — full logic is Step 4.2).

## Read these files first:
1. `docs/CONTAINER_SPECS.md` — section: "Processor Container Spec"
2. `docs/PROCESSING_PIPELINE.md` — read the full list of FFmpeg step types to understand what packages are needed

## Hard constraints:
- Base image: `python:3.11-slim`
- Must install `ffmpeg` via apt-get
- Must NOT install CUDA/GPU drivers in the image — GPU support is handled via Docker `--gpus` flag and the host driver (Step 4.3)
- Python packages: `requests` only (FFmpeg called via subprocess, not a Python wrapper)
- No `imageio-ffmpeg`, no `moviepy` — raw `subprocess` calls to `ffmpeg` binary
- Working dir: `/app`
- Non-root user: `RUN useradd -m processor && USER processor`
- CMD: `["python", "processor.py"]`

## Files to create:

### `processor/Dockerfile`
Standard pattern: install ffmpeg, copy requirements, pip install, copy source, set user, CMD.

### `processor/requirements.txt`
```
requests
```

### `processor/processor.py` (skeleton only)
```python
"""
Processor — polls download_jobs for status='downloaded' and runs FFmpeg pipeline steps.
Full implementation in Step 4.2.
"""
import os
import sys
import time
import sqlite3

DB_PATH = os.environ.get('DB_PATH', '/data/app.db')
DOWNLOADS_PATH = os.environ.get('DOWNLOADS_PATH', '/downloads')
DASHBOARD_URL = os.environ.get('DASHBOARD_URL', 'http://dashboard:8080')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '5'))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def main():
    print(f"Processor started. DB: {DB_PATH}, Downloads: {DOWNLOADS_PATH}")
    while True:
        # TODO: Step 4.2 will fill this in
        print("Polling for jobs... (stub)")
        time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    main()
```

## Test / pass criteria:
```bash
docker build -t processor-test ./processor
docker run --rm -e DB_PATH=/data/app.db processor-test
```
Must output:
```
Processor started. DB: /data/app.db, Downloads: /downloads
Polling for jobs... (stub)
```
And keep running (Ctrl+C to stop).

Also verify FFmpeg is available in the container:
```bash
docker run --rm processor-test ffmpeg -version
```
Must print the FFmpeg version string.

## When done:
- Show all 3 files
- Show `docker build` and `docker run` output
- Do NOT build anything else in this session
