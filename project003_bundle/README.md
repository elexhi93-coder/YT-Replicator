# project003 — YouTube Channel Replicator

Automatically mirrors a YouTube channel to multiple platforms (YouTube, TikTok, Facebook, Instagram, X/Twitter, Dailymotion) using a headless Docker service and n8n for upload automation.

---

## How It Works

```
Source YouTube Channel
        │
        ▼
  headless_watcher  ──► downloads video ──► fires webhook
        │
        ▼
       n8n
        │
        ├──► YouTube Upload
        ├──► TikTok Upload
        ├──► Facebook Upload
        ├──► Instagram Upload
        ├──► X / Twitter Upload
        └──► Dailymotion Upload
```

The watcher runs in two modes automatically:

| Mode | When | What it does |
|---|---|---|
| **BACKFILL** | First run, until history is fully uploaded | Uploads all existing channel videos oldest-first, up to `DAILY_UPLOAD_LIMIT` per day |
| **MONITOR** | After backfill is done | Polls every 15 min for new uploads |

---

## Quick Start

### 1. Configure channels

Edit `channel_monitor_config.json` (copy from `config/channels.example.json`):

```json
{
  "channels": {
    "UCxxxxxxxxxxxxxxxxxx": {
      "name": "Source Channel Name",
      "url": "https://youtube.com/@YourSourceChannel",
      "auto_download": true,
      "daily_upload_limit": 10,
      "backfill_complete": false,
      "videos_seen": []
    }
  }
}
```

To find a channel ID, go to the YouTube channel page and check the URL — it starts with `UC`.

### 2. Configure webhook routing (optional per-channel)

Edit or create `n8n_webhook_config.json` (copy from `config/webhooks.example.json`):

```json
{
  "global_webhook_url": "http://n8n:5678/webhook/idm-yt-download",
  "channels": {
    "UCxxxxxxxxxxxxxxxxxx": "http://n8n:5678/webhook/channel-specific-path"
  }
}
```

### 3. Copy the environment file

```bash
cp .env.example .env
# Edit .env with your values
```

### 4. Start the stack

```bash
# Stop standalone n8n container if running
docker stop n8n && docker rm n8n

# Build and start
docker compose up -d --build

# View logs
docker compose logs -f watcher
```

### 5. Set up n8n

1. Open http://localhost:5678
2. Create your account
3. Go to **Workflows → Import** → select `n8n/workflow.json`
4. Add credentials for each platform (YouTube OAuth, Facebook App, etc.)
5. Activate the workflow

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values.

| Variable | Default | Description |
|---|---|---|
| `DAILY_UPLOAD_LIMIT` | `10` | Max uploads per channel per day |
| `CHECK_INTERVAL` | `15` | Minutes between monitor-mode polls |
| `CLEANUP_TTL_HOURS` | `24` | Hours before temp video files are deleted |
| `N8N_WEBHOOK_URL` | — | Global n8n webhook URL (used if no per-channel URL set) |
| `LOG_LEVEL` | `INFO` | `DEBUG` for verbose yt-dlp output |

Per-channel `daily_upload_limit` in the config JSON overrides the env var.

---

## YouTube Upload Quota

YouTube Data API v3 gives **10,000 units/day** free.

| Setting | Safe for |
|---|---|
| `DAILY_UPLOAD_LIMIT=6` | Free tier (conservative) |
| `DAILY_UPLOAD_LIMIT=10` | After requesting quota increase |
| `DAILY_UPLOAD_LIMIT=50+` | Verified/production OAuth apps |

Request a quota increase at: https://console.cloud.google.com/apis/api/youtube.googleapis.com

---

## Skipping Backfill

To only mirror future uploads (skip existing history), set `backfill_complete: true` in the channel config:

```json
{
  "backfill_complete": true,
  "videos_seen": []
}
```

---

## Resuming After a Restart

Backfill progress is saved to `channel_monitor_config.json` automatically. If the container restarts mid-backfill, it picks up exactly where it left off — no re-fetching or duplicate uploads.

---

## Running the GUI (Desktop App)

A full GUI downloader is included for manual use:

```bash
# Windows
run_idm.bat

# Or directly
python run_app.py
```

---

## Project Structure

```
project003/
├── headless_watcher.py      # Main Docker service — two-mode backfill + monitor
├── n8n_webhook.py           # Webhook sender module
├── app.py                   # GUI entry point
├── channel_monitor.py       # GUI channel monitor window
├── video_downloader.py      # GUI video downloader
├── Dockerfile               # Docker image for headless watcher
├── docker-compose.yml       # Full stack: watcher + n8n
├── channel_monitor_config.json  # Channel list + backfill state
├── n8n/
│   └── workflow.json        # Import this into n8n
├── config/
│   ├── channels.example.json    # Channel config template
│   └── webhooks.example.json    # Webhook routing template
├── core/                    # Core business logic
├── controllers/             # MVC controllers
├── views/                   # MVC views
├── plugins/                 # Download plugins
├── uploaders/               # Platform upload modules
└── docs/                    # Full documentation
```

---

## Documentation

| File | Description |
|---|---|
| [docs/PHASE1_BACKFILL_MONITOR.md](docs/PHASE1_BACKFILL_MONITOR.md) | Two-mode workflow blueprint with flowchart |
| [docs/WORKFLOW_BLUEPRINT.md](docs/WORKFLOW_BLUEPRINT.md) | Full system architecture |
| [docs/MANHWA_KDRAMA_BLUEPRINT.md](docs/MANHWA_KDRAMA_BLUEPRINT.md) | Multi-niche pipeline example |
