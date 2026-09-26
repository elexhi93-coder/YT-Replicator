# Container Specifications
## project003 — Dockerfile, Environment, Volumes, Ports

**Status:** LOCKED — container specs define what gets built  
**All containers run Linux (Debian Slim) inside Docker Desktop on Windows**

---

## 1. `n8n` — Workflow Automation Engine

### Image
```
docker.n8n.io/n8nio/n8n:latest
```
Official pre-built image. No custom Dockerfile needed.

### Ports
| Host   | Container | Protocol |
|--------|-----------|----------|
| 5678   | 5678      | HTTP     |

Accessible from LAN at `http://<server-ip>:5678`

### Volumes
| Host Path                              | Container Path           | Access |
|----------------------------------------|--------------------------|--------|
| `n8n_data` (named Docker volume)       | `/home/node/.n8n`        | RW     |
| `./downloads/`                         | `/shared/downloads/`     | RO     |

**Why read-only for downloads?** n8n only reads files to upload them. It never writes to the downloads folder. Principle of least privilege.

### Environment Variables
```yaml
environment:
  N8N_HOST: 0.0.0.0
  N8N_PORT: 5678
  N8N_PROTOCOL: http
  WEBHOOK_URL: http://localhost:5678/
  GENERIC_TIMEZONE: Europe/Paris        # change to your timezone
  N8N_LOG_LEVEL: info
  N8N_BASIC_AUTH_ACTIVE: false          # set true + credentials if exposing to network
```

### Credentials (managed inside n8n UI — NOT in env vars or files)
- YouTube OAuth2 (Google account)
- Dailymotion OAuth2
- Facebook Page token
- TikTok (via HTTP Request node — no native node available)
- OpenRouter API key (HTTP Header auth)

### Health Check
```yaml
healthcheck:
  test: ["CMD", "wget", "-qO-", "http://localhost:5678/healthz"]
  interval: 30s
  timeout: 10s
  retries: 5
```

### Restart Policy
```yaml
restart: unless-stopped
```

### Dependencies
None — n8n starts independently. Watcher waits for n8n to be healthy before starting.

---

## 2. `dashboard` — Flask Web UI

### Dockerfile
```dockerfile
# dashboard/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install only what's needed — no dev tools
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "app.py"]
```

### requirements.txt (dashboard)
```
flask==3.1.0
```
No additional packages needed. SQLite3 is part of Python stdlib. Docker socket reads use stdlib `http.client` and `socket`.

### Ports
| Host   | Container | Protocol |
|--------|-----------|----------|
| 8080   | 8080      | HTTP     |

Accessible from LAN at `http://<server-ip>:8080`

### Volumes
| Host Path                  | Container Path   | Access |
|----------------------------|------------------|--------|
| `./db/`                    | `/data/`         | RW     |
| `/var/run/docker.sock`     | `/var/run/docker.sock` | RO |

**Docker socket (read-only):** Used only for `GET /containers/{name}/logs` calls. Read-only mount prevents dashboard from starting, stopping, or modifying containers.

### Environment Variables
```yaml
environment:
  DB_PATH: /data/app.db
  DOCKER_SOCKET: /var/run/docker.sock
  WATCHER_CONTAINER: idm-yt-watcher
  PROCESSOR_CONTAINER: project003-processor
  FLASK_ENV: production
  PORT: 8080
```

### Restart Policy
```yaml
restart: unless-stopped
```

### Dependencies
```yaml
depends_on:
  - n8n   # not strictly needed but ensures n8n is up before dashboard shows its URL
```

---

## 3. `watcher` — Channel Monitor + Downloader

### Dockerfile
```dockerfile
# Dockerfile (project root)
FROM python:3.11-slim

# FFmpeg from apt — standard build, no GPU needed for download phase
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.watcher.txt .
RUN pip install --no-cache-dir -r requirements.watcher.txt

COPY headless_watcher.py .

CMD ["python", "headless_watcher.py"]
```

### requirements.watcher.txt
```
yt-dlp==2025.3.31
requests==2.32.3
```

### Volumes
| Host Path          | Container Path           | Access |
|--------------------|--------------------------|--------|
| `./db/`            | `/data/`                 | RW     |
| `./downloads/`     | `/downloads/`            | RW     |

### Environment Variables
```yaml
environment:
  DB_PATH: /data/app.db
  DOWNLOAD_DIR: /downloads
  CHECK_INTERVAL: 15           # minutes between monitor-mode polls
  DAILY_UPLOAD_LIMIT: 10       # global fallback (overridden per channel in DB)
  CLEANUP_TTL_HOURS: 24        # hours before processed files are deleted
  LOG_LEVEL: INFO
  SUBTITLE_LANGS: en           # comma-separated language codes
```

### Ports
None. Watcher makes outbound HTTP calls only.

### Restart Policy
```yaml
restart: unless-stopped
```

### Dependencies
```yaml
depends_on:
  n8n:
    condition: service_healthy
```
Watcher waits for n8n to be healthy before starting. This prevents webhook failures on first boot.

### What it does NOT need
- FFmpeg GPU support (only downloading, no encoding)
- Docker socket (no log reading)
- The dashboard or processor (fully independent after DB is initialized)

---

## 4. `processor` — FFmpeg Video Transformer

### Dockerfile
```dockerfile
# processor/Dockerfile
FROM python:3.11-slim

# FFmpeg with NVENC support
# We install from the official static build to get GPU support
RUN apt-get update && apt-get install -y \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Download static FFmpeg build with NVENC support
RUN wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
    && tar -xf ffmpeg-release-amd64-static.tar.xz \
    && mv ffmpeg-*-static/ffmpeg /usr/local/bin/ffmpeg \
    && mv ffmpeg-*-static/ffprobe /usr/local/bin/ffprobe \
    && rm -rf ffmpeg-*

WORKDIR /app

COPY requirements.processor.txt .
RUN pip install --no-cache-dir -r requirements.processor.txt

COPY processor.py .

CMD ["python", "processor.py"]
```

**Alternative (if GPU is not available or NVENC causes issues):** Use `FROM python:3.11-slim` + `apt install ffmpeg` for CPU-only encoding. GPU is optional — the processor falls back to CPU encoding if NVENC is not available.

### requirements.processor.txt
```
requests==2.32.3
```
Only `requests` needed for webhook firing. SQLite3 is stdlib. FFmpeg is called via `subprocess`.

### Volumes
| Host Path       | Container Path | Access |
|-----------------|----------------|--------|
| `./db/`         | `/data/`       | RW     |
| `./downloads/`  | `/downloads/`  | RW     |

### Environment Variables
```yaml
environment:
  DB_PATH: /data/app.db
  DOWNLOAD_DIR: /downloads
  POLL_INTERVAL: 5          # seconds between DB polls for new jobs
  USE_GPU: true             # set false to force CPU encoding
  GPU_CODEC: h264_nvenc     # or hevc_nvenc for HEVC
  CPU_CODEC: libx264        # fallback if USE_GPU=false or NVENC unavailable
  N8N_INTERNAL_HOST: http://n8n:5678
  LOG_LEVEL: INFO
```

### GPU Passthrough (NVIDIA Container Toolkit)
To enable GPU inside the processor container:
```yaml
# docker-compose.yml — processor service
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

**Prerequisites on host:**
1. NVIDIA driver installed on Windows host
2. NVIDIA Container Toolkit installed in Docker Desktop WSL2 backend
3. `docker run --gpus all nvidia/cuda:12.0-base nvidia-smi` must return GPU info

**If GPU passthrough is not configured:** Processor automatically detects NVENC unavailability and falls back to `libx264` (CPU). System still works, just slower.

### Ports
None. Processor is headless — makes outbound HTTP calls to n8n webhooks and reads/writes SQLite.

### Restart Policy
```yaml
restart: unless-stopped
```

### Dependencies
```yaml
depends_on:
  - dashboard   # ensures DB is initialized before processor starts polling
```

---

## 5. docker-compose.yml — Full Specification

```yaml
# project003/docker-compose.yml
# ================================
# Multi-platform content replication pipeline
# Start: docker compose up -d --build
# Stop:  docker compose down

name: project003

services:

  n8n:
    image: docker.n8n.io/n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    volumes:
      - n8n_data:/home/node/.n8n
      - ${DOWNLOADS_PATH:-./downloads}:/shared/downloads:ro
    env_file:
      - path: .env
        required: false
    environment:
      - N8N_HOST=0.0.0.0
      - N8N_PORT=5678
      - N8N_PROTOCOL=http
      - WEBHOOK_URL=http://localhost:5678/
      - GENERIC_TIMEZONE=${TIMEZONE:-Europe/Paris}
      - N8N_LOG_LEVEL=info
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:5678/healthz"]
      interval: 30s
      timeout: 10s
      retries: 5

  dashboard:
    build:
      context: ./dashboard
      dockerfile: Dockerfile
    image: project003-dashboard
    container_name: project003-dashboard
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./db:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - DB_PATH=/data/app.db
      - DOCKER_SOCKET=/var/run/docker.sock
      - WATCHER_CONTAINER=idm-yt-watcher
      - PROCESSOR_CONTAINER=project003-processor

  watcher:
    build:
      context: .
      dockerfile: Dockerfile
    image: idm-yt-watcher
    container_name: idm-yt-watcher
    restart: unless-stopped
    volumes:
      - ./db:/data
      - ${DOWNLOADS_PATH:-./downloads}:/downloads
    env_file:
      - path: .env
        required: false
    environment:
      - DB_PATH=/data/app.db
      - DOWNLOAD_DIR=/downloads
      - CHECK_INTERVAL=${CHECK_INTERVAL:-15}
      - DAILY_UPLOAD_LIMIT=${DAILY_UPLOAD_LIMIT:-10}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    depends_on:
      n8n:
        condition: service_healthy

  processor:
    build:
      context: ./processor
      dockerfile: Dockerfile
    image: project003-processor
    container_name: project003-processor
    restart: unless-stopped
    volumes:
      - ./db:/data
      - ${DOWNLOADS_PATH:-./downloads}:/downloads
    environment:
      - DB_PATH=/data/app.db
      - DOWNLOAD_DIR=/downloads
      - POLL_INTERVAL=${PROCESSOR_POLL_INTERVAL:-5}
      - USE_GPU=${USE_GPU:-false}
      - N8N_INTERNAL_HOST=http://n8n:5678
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    depends_on:
      - dashboard
    # Uncomment for GPU support:
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1
    #           capabilities: [gpu]

volumes:
  n8n_data:
    driver: local
```

---

## 6. .env File (Configuration)

```bash
# project003/.env
# Copy this file and fill in your values
# This file is NEVER committed to git

# === Storage ===
# Path to downloads folder on host.
# Use internal SSD for development, external HDD for production.
DOWNLOADS_PATH=./downloads
# Example for external drive:
# DOWNLOADS_PATH=E:/project003/downloads

# === Timezone ===
TIMEZONE=Europe/Paris

# === Watcher settings ===
CHECK_INTERVAL=15          # minutes between monitor-mode polls
DAILY_UPLOAD_LIMIT=10      # global daily download limit per channel
LOG_LEVEL=INFO             # INFO | DEBUG | WARNING

# === Processor settings ===
PROCESSOR_POLL_INTERVAL=5  # seconds between DB polls
USE_GPU=false              # true = use NVENC, false = use libx264

# === n8n settings ===
# NOTE: API keys and OAuth tokens are stored INSIDE n8n, not here.
# Only add infrastructure-level config here.
```

---

## 7. Folder Structure After Full Build

```
project003/
├── docker-compose.yml
├── .env
├── Dockerfile                    ← watcher image
├── headless_watcher.py           ← watcher entrypoint
├── db/
│   └── app.db                    ← SQLite database (created on first run)
├── downloads/                    ← video files (or symlink to external drive)
│   └── job_{id}/
│       ├── source.mp4
│       ├── youtube.mp4
│       ├── tiktok.mp4
│       └── thumbnail.jpg
├── dashboard/
│   ├── Dockerfile
│   ├── app.py                    ← Flask application
│   ├── models.py                 ← SQLite schema + DB connection helper
│   ├── requirements.txt
│   └── templates/
│       ├── base.html             ← layout with nav
│       ├── pipelines.html
│       ├── channels.html
│       ├── queue.html
│       ├── history.html
│       └── logs.html
├── processor/
│   ├── Dockerfile
│   ├── processor.py              ← FFmpeg job runner
│   └── requirements.txt
├── n8n/
│   └── workflow.json             ← exported n8n workflow (for import)
└── docs/
    ├── ARCHITECTURE.md
    ├── DATABASE_SCHEMA.md
    ├── API_CONTRACTS.md
    ├── DATA_FLOW.md
    ├── CONTAINER_SPECS.md        ← this file
    ├── PROCESSING_PIPELINE.md
    ├── N8N_WORKFLOW.md
    ├── DASHBOARD_SPEC.md
    └── BUILD_ORDER.md
```

---

*Next: [PROCESSING_PIPELINE.md](PROCESSING_PIPELINE.md)*
