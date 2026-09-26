# IDM-YT Headless Watcher — Docker Image
# ----------------------------------------
# Python 3.11 slim + FFmpeg + yt-dlp + requests
# Designed to run alongside n8n via docker-compose.yml

FROM python:3.11-slim

# Install FFmpeg (required for video merging/conversion)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir yt-dlp requests

# Copy the headless watcher service
COPY headless_watcher.py .

# Default empty config (will be overridden by volume mount)
RUN echo '{"channels":{}}' > /app/channel_monitor_config.json \
    && echo '{"global_url":"","enabled":true,"channel_urls":{}}' > /app/n8n_webhook_config.json

# Shared downloads directory
RUN mkdir -p /shared/downloads

# Unbuffered Python output — logs appear immediately in `docker logs`
ENV PYTHONUNBUFFERED=1

# Default environment (override in docker-compose.yml or `docker run -e`)
ENV CONFIG_FILE=/app/channel_monitor_config.json
ENV WEBHOOK_CONFIG_FILE=/app/n8n_webhook_config.json
ENV DOWNLOAD_DIR=/shared/downloads
ENV N8N_WEBHOOK_URL=""
ENV CHECK_INTERVAL=15
ENV CLEANUP_TTL_HOURS=24
ENV LOG_LEVEL=INFO

CMD ["python", "headless_watcher.py"]
