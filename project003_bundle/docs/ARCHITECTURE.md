# System Architecture
## project003 — Multi-Platform Content Replication Engine

**Version:** 1.0-pre-build  
**Date:** 2026-04-22  
**Author:** Software Architect  
**Status:** LOCKED — no architecture changes without updating this document first

---

## 1. Purpose

project003 is a fully automated, self-hosted content replication pipeline. It:

1. Monitors source YouTube channels 24/7
2. Downloads new (and backfilled historical) videos
3. Transforms each video for each target platform (trim, crop, watermark, etc.)
4. Rewrites metadata with AI (title, description, tags) per platform
5. Uploads transformed videos to YouTube, Dailymotion, Facebook, TikTok
6. Tracks everything in a web dashboard accessible from any device on the network

The system runs entirely on a Lenovo C30 server (Dual Xeon E5-2680 V2, 128GB RAM, GTX 1080) via Docker Compose. No cloud services are required except the target upload platforms.

---

## 2. Container Map

```
┌──────────────────────────────────────────────────────────────────┐
│                     Docker Compose Stack                         │
│                      (Lenovo C30 Server)                         │
│                                                                  │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐  ┌──────────┐ │
│  │  dashboard │   │  watcher   │   │ processor  │  │   n8n    │ │
│  │  :8080     │   │ (headless) │   │ (headless) │  │  :5678   │ │
│  │  Flask UI  │   │  yt-dlp    │   │  FFmpeg    │  │ Workflow │ │
│  └─────┬──────┘   └─────┬──────┘   └─────┬──────┘  └────┬─────┘ │
│        │                │                │               │       │
│        └────────────────┴────────────────┴───────────────┘       │
│                         │                         │              │
│              ┌──────────▼──────────┐   ┌──────────▼──────────┐  │
│              │   ./db/app.db       │   │   ./downloads/      │  │
│              │   (SQLite)          │   │   (video files)     │  │
│              └─────────────────────┘   └─────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │                                         │
    browser (LAN)                             internet
    http://C30-IP:8080                   YouTube / TikTok / etc.
    http://C30-IP:5678 (n8n)
```

---

## 3. Container Responsibilities

### 3.1 `dashboard` — Web Management UI
- **Image:** Custom Python 3.11-slim + Flask
- **Port:** 8080 (accessible from any LAN device via browser)
- **Role:** The control plane. Manages all configuration. Shows live status.
- **Does:**
  - CRUD for Pipelines, Channels, Destinations, Processing Steps
  - Live job queue with SSE progress updates
  - Upload history with links to results
  - Docker log viewer (watcher + processor)
  - Manual single-video download trigger
  - Receives `/api/callback` from n8n when uploads complete
- **Does NOT:** Download videos, run FFmpeg, upload to platforms

### 3.2 `watcher` — Channel Monitor + Downloader
- **Image:** Custom Python 3.11-slim + yt-dlp + FFmpeg
- **Port:** None (headless, outbound only)
- **Role:** The ingestion engine. Discovers and downloads video content.
- **Does:**
  - Polls SQLite `channels` table every 15 minutes (configurable)
  - For channels in **BACKFILL mode**: downloads full channel history oldest-first, respects daily download limit
  - For channels in **MONITOR mode**: polls YouTube RSS feed for new uploads, downloads only new videos
  - Saves each video to `/downloads/{job_id}/video.mp4`
  - Creates a `job` record in SQLite with status `downloaded`
  - Fires HTTP webhook to n8n with video metadata + file path
- **Does NOT:** Run FFmpeg transforms, upload to platforms, serve UI

### 3.3 `processor` — FFmpeg Video Transformer
- **Image:** Custom Python 3.11-slim + FFmpeg (with NVENC support)
- **Port:** None (headless, polls DB)
- **Role:** The transformation engine. Converts source videos into platform-ready outputs.
- **Does:**
  - Polls SQLite `jobs` table every 5 seconds for jobs with status `downloaded`
  - Reads the pipeline's `processing_steps` for the job
  - Executes FFmpeg steps in order (trim → crop → watermark → normalize → reencode)
  - Produces one output file per destination (e.g., `job_42_youtube.mp4`, `job_42_tiktok.mp4`)
  - Updates job status to `processed`, writes output paths to `job_outputs` table
  - Supports GPU acceleration via NVIDIA Container Toolkit (`h264_nvenc`)
- **Does NOT:** Download anything, upload anything, serve UI, call n8n

### 3.4 `n8n` — Orchestration + Upload Engine
- **Image:** `docker.n8n.io/n8nio/n8n:latest`
- **Port:** 5678 (UI accessible from browser)
- **Role:** The execution engine. Receives triggers, enriches metadata, uploads to platforms.
- **Does:**
  - Receives webhook from `watcher` when a video is downloaded
  - Calls OpenRouter API (free Mistral 7B model) to rewrite title, description, tags for YouTube
  - Reads processed video files from `/shared/downloads/`
  - Uploads to YouTube, Dailymotion, Facebook, TikTok using credential nodes (OAuth managed inside n8n)
  - Sends callback POST to `dashboard:8080/api/callback` with upload results
  - Handles retry logic natively
- **Does NOT:** Touch SQLite directly, run FFmpeg, serve custom UI

---

## 4. Shared Volumes

Two bind-mount volumes are shared across containers:

### 4.1 `./db/` → SQLite database
```
Host path:  C:/Users/T490s/Documents/project003/db/app.db
Container:  /data/app.db  (dashboard, watcher, processor)
```
- Read/write access for: dashboard, watcher, processor
- No access for: n8n (n8n triggers via webhook, not DB queries)
- Contains all config, job state, channel history, upload results

### 4.2 `./downloads/` → Video files
```
Host path:  C:/Users/T490s/Documents/project003/downloads/
            (or external drive: E:/project003/downloads/)
Container:  /downloads/  (watcher, processor)
            /shared/downloads/  (n8n)
```
- Write access: watcher (creates files), processor (creates transformed files)
- Read access: n8n (reads files for upload)
- Structure inside:
```
downloads/
  job_{id}/
    source.mp4           ← raw download from yt-dlp
    youtube.mp4          ← processed output for YouTube destination
    tiktok.mp4           ← processed output for TikTok destination
    dailymotion.mp4      ← processed output for Dailymotion destination
    thumbnail.jpg        ← thumbnail extracted from source
```

---

## 5. Inter-Container Communication

### 5.1 Docker Internal Network
Docker Compose creates a private bridge network. Containers reference each other by service name:
- `http://n8n:5678` — reachable by watcher and dashboard
- `http://dashboard:8080` — reachable by n8n
- No container is reachable from the internet (only LAN via host port binding)

### 5.2 SQLite File (Shared State)
```
dashboard ──read/write──▶  app.db
watcher   ──read/write──▶  app.db
processor ──read/write──▶  app.db
```
Used for slow-state (config, job tracking, history). SQLite WAL mode is enabled to allow concurrent reads from multiple containers without locking.

### 5.3 HTTP Webhooks (Real-Time Signals)
```
watcher   ──POST /webhook/idm-yt-download──▶  n8n:5678    (video downloaded)
n8n       ──POST /api/callback             ──▶  dashboard:8080  (upload done)
```
The webhook payload from watcher includes `job_id` so n8n can include it in the callback, allowing the dashboard to update the exact job record.

### 5.4 Communication Summary Table

| From      | To        | Method           | Trigger                     |
|-----------|-----------|------------------|-----------------------------|
| watcher   | n8n       | HTTP POST        | After each video download   |
| watcher   | app.db    | SQLite write     | Create job, update status   |
| processor | app.db    | SQLite read/write| Poll for jobs, update status|
| dashboard | app.db    | SQLite read/write| All UI reads and writes     |
| n8n       | dashboard | HTTP POST        | After each upload completes |
| n8n       | downloads/| File read (volume)| Reads mp4 to upload        |
| processor | downloads/| File read/write  | Read source, write outputs  |
| watcher   | downloads/| File write       | Write downloaded video      |

---

## 6. Pipeline Concept

A **Pipeline** is the central configuration unit. Everything is organized around pipelines.

```
Pipeline
├── name: "Manhwa Fresh → Multi-Platform"
├── Channels (sources)
│   ├── Channel A: UCz3IjVYoX... (backfill mode, 10/day)
│   └── Channel B: @freshmanhwa (monitor mode)
├── Processing Steps (transforms, in order)
│   ├── Step 1: trim (0s → 180s)
│   ├── Step 2: crop (9:16 for vertical)
│   ├── Step 3: watermark (logo.png, bottom-right)
│   └── Step 4: normalize_audio (-14 LUFS)
└── Destinations (outputs)
    ├── YouTube (with separate processing steps for 16:9)
    ├── TikTok (uses the 9:16 output)
    └── Dailymotion (uses the 16:9 output)
```

Processing steps can be **per-destination** (different crop for YouTube vs TikTok) or **global** (same watermark for all). See [PROCESSING_PIPELINE.md](PROCESSING_PIPELINE.md) for full step specifications.

---

## 7. Technology Stack

| Layer          | Technology          | Reason                                              |
|----------------|---------------------|-----------------------------------------------------|
| Containerization| Docker + Compose   | Portable, single-command start, isolated services   |
| Download engine| yt-dlp              | Best-in-class YouTube downloader, actively maintained|
| Video processing| FFmpeg             | Industry standard, GPU support (NVENC)              |
| Workflow engine| n8n                 | Visual pipelines, native credential mgmt, free tier |
| AI enrichment  | OpenRouter (Mistral 7B free) | Free model, good metadata quality          |
| Web framework  | Flask               | Lightweight Python, no build step needed            |
| UI interactivity| HTMX               | Server-side HTML fragments, no JS framework         |
| UI styling     | TailwindCSS (CDN)   | Zero build step, utility-first, dark mode ready     |
| Database       | SQLite (WAL mode)   | Zero config, file-based, sufficient for this scale  |
| OS             | Windows + Docker Desktop | C30 server, containers run Linux inside        |

---

## 8. Hardware Context

**Server:** Lenovo C30  
**CPU:** Dual Intel Xeon E5-2680 V2 (20 cores / 40 threads total)  
**RAM:** 128 GB  
**GPU:** NVIDIA GTX 1080 (or Quadro K4200)  
**Storage:** Internal SSD (for OS, Docker, app.db) + External USB HDDs (for downloads/)  
**Network:** Local area network only (no public internet exposure)  

Docker Desktop is configured to use most CPU/RAM. GPU passthrough via NVIDIA Container Toolkit enables hardware-accelerated FFmpeg encoding in the processor container (`h264_nvenc` codec).

---

## 9. External Storage Strategy

Downloads volume can be pointed at any external drive:

```yaml
# docker-compose.yml
volumes:
  - E:/project003/downloads:/downloads   # external HDD
```

**Rules:**
- `./db/app.db` MUST stay on internal SSD (frequent random I/O)
- `./downloads/` CAN be on external HDD (sequential large files)
- If external drive is disconnected, watcher/processor fail gracefully; dashboard and n8n remain running
- Drive letter is configurable in `.env` file — no code changes needed to swap drives

---

## 10. Security Considerations

- All containers run on a private LAN only — no ports exposed to internet
- n8n credentials (YouTube OAuth, Facebook token) stored in n8n's encrypted credential store, never in code or config files
- OpenRouter API key stored in n8n credential store, never hardcoded
- SQLite file is bind-mounted inside the project folder — not accessible outside Docker without physical server access
- Docker socket (`/var/run/docker.sock`) mounted read-only in dashboard container (for log reading only)
- No user authentication on dashboard (LAN-only deployment assumption — add reverse proxy + basic auth if needed)

---

*Next: [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)*
