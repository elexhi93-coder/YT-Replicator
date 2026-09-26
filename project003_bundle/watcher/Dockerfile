# project003 — Watcher container
# Build context: project root (so we can COPY dashboard/models.py)
# Build:  docker build -f watcher/Dockerfile -t project003-watcher .
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY watcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# bgutil POT provider plugin — lets yt-dlp auto-generate YouTube PO Tokens
# so downloads work without cookies even on flagged IPs.
# The plugin talks to the bgutil-provider sidecar at http://bgutil-provider:4416
RUN pip install --no-cache-dir bgutil-ytdlp-pot-provider

# Source files
COPY headless_watcher.py .
COPY dashboard/__init__.py        ./dashboard/__init__.py
COPY dashboard/models.py          ./dashboard/models.py
COPY dashboard/download_profile.py ./dashboard/download_profile.py

# Non-root user; ensure data + downloads dirs exist and are writable
RUN useradd -m -u 1000 watcher \
 && mkdir -p /data /downloads \
 && chown -R watcher:watcher /app /data /downloads

USER watcher

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/data/app.db \
    DOWNLOAD_DIR=/downloads

CMD ["python", "-u", "headless_watcher.py"]
