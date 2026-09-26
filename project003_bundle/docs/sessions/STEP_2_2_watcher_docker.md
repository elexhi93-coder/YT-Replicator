# SESSION TASK — Step 2.2: Watcher Dockerfile

## Your job in this session
Create `watcher/Dockerfile` and `watcher/requirements.txt`. The watcher container is already working — this step just dockerizes it properly.

## Read these files first:
1. `docs/CONTAINER_SPECS.md` — section: "Watcher Container Spec"
2. `headless_watcher.py` — to verify what packages it imports

## Hard constraints:
- Base image: `python:3.11-slim`
- Must install `ffmpeg` via `apt-get` (needed by yt-dlp)
- Must install `yt-dlp` via pip (latest)
- Must install `requests` via pip
- Working dir: `/app`
- Copy `headless_watcher.py` and `dashboard/models.py` into the image
- CMD: `["python", "headless_watcher.py", "--mode", "monitor"]`
- No root user — add `RUN useradd -m watcher` and `USER watcher` before CMD
- Keep the image minimal — no dev tools, no test packages

## Files to create:

### `watcher/Dockerfile`
```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY headless_watcher.py .
COPY dashboard/models.py ./dashboard/models.py

RUN useradd -m watcher
USER watcher

CMD ["python", "headless_watcher.py", "--mode", "monitor"]
```

### `watcher/requirements.txt`
```
yt-dlp
requests
```

## Test / pass criteria:
```bash
docker build -t watcher-test ./watcher
```
Build must succeed with no errors.
Then:
```bash
docker run --rm -e DB_PATH=/data/app.db -v ./db:/data watcher-test python -c "from dashboard.models import get_db; print('OK')"
```
Must print `OK`.

## When done:
- Show both files
- Show docker build output (last 10 lines)
- Do NOT build anything else in this session
