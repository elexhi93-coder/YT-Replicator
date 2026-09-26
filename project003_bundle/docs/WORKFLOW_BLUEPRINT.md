# IDM-YT Automation Platform — Workflow Blueprint
**Last updated: April 18, 2026**

---

## 1. What This System Does

A fully automated content replication pipeline that:
1. **Watches** one or more source channels (YouTube, Dailymotion) for new uploads
2. **Downloads** each new video temporarily to local storage
3. **Distributes** each video to multiple destination social media accounts via n8n
4. **Cleans up** the local file after upload is complete

No manual intervention is needed once configured. The system runs 24/7 in Docker.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         YOUR MACHINE (Docker)                       │
│                                                                     │
│  ┌──────────────────────┐      ┌──────────────────────────────────┐ │
│  │  idm-yt-watcher      │      │  n8n  (localhost:5678)           │ │
│  │  (headless Python)   │      │                                  │ │
│  │                      │      │  ┌─────────────────────────────┐ │ │
│  │  1. Poll channels    │      │  │  Webhook Trigger             │ │ │
│  │  2. Detect new video │ POST │  │  ↓                           │ │ │
│  │  3. Download video ──┼─────▶│  │  Prepare Data               │ │ │
│  │  4. Fire webhook     │      │  │  ↓                           │ │ │
│  │  5. Cleanup files    │      │  │  Read Video File             │ │ │
│  │                      │      │  │  ↓         ↓         ↓      │ │ │
│  └──────────────────────┘      │  │  YouTube  Facebook  TikTok  │ │ │
│                                │  │  Daily.   Instagram Twitter │ │ │
│  ┌──────────────────────┐      │  └─────────────────────────────┘ │ │
│  │  /shared/downloads   │◀─────┼──────────────────────────────────┘ │
│  │  (Docker volume)     │      │                                     │
│  └──────────────────────┘      │                                     │
│                                │                                     │
│  ┌──────────────────────┐      │                                     │
│  │  dashboard           │      │                                     │
│  │  (localhost:3000)    │      │                                     │
│  │  browser-based UI    │      │                                     │
│  └──────────────────────┘      │                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Components

| Component | Technology | Role | Port |
|---|---|---|---|
| `idm-yt-watcher` | Python + yt-dlp | Polls sources, downloads videos, fires webhooks | — |
| `n8n` | Node.js (Docker image) | Receives webhooks, uploads to social platforms | 5678 |
| `dashboard` | Node.js + Express | Web UI for managing channels and viewing logs | 3000 |
| `/shared/downloads` | Docker volume | Temp file storage shared between watcher and n8n | — |

---

## 4. Phases

---

### Phase 1 — Single YouTube Source → All Platforms

**Scenario:** You have one YouTube channel you want to replicate everywhere.

```
Source:
  YouTube Channel A  (@SomeChannel)

Destinations:
  → Your YouTube account
  → Your Dailymotion account
  → Your Facebook Page
  → Your TikTok account
  → Your Instagram Reels
  → Your X / Twitter

Trigger: New video detected on @SomeChannel
Result:  Video auto-published on all 6 destinations within minutes
```

**Config required:**
```json
// channel_monitor_config.json
{
  "channels": {
    "UCxxxxxxxxxxxxxxxx": {
      "name": "Some Channel",
      "url": "https://youtube.com/@SomeChannel",
      "auto_download": true,
      "videos_seen": []
    }
  }
}
```

**Status:** ✅ Fully built and ready

---

### Phase 2 — Multiple YouTube Sources → All Platforms

**Scenario:** You watch 3+ YouTube channels and replicate all of them.

```
Sources:
  YouTube Channel A  (@ChannelA)
  YouTube Channel B  (@ChannelB)
  YouTube Channel C  (@ChannelC)

Destinations (same for all):
  → YouTube / Dailymotion / Facebook / TikTok / Instagram / Twitter

Trigger: New video on ANY of the 3 channels
Result:  That video is replicated to all destinations
```

**Optional: Route channels to different destinations**

If Channel A should only go to YouTube + Facebook, and Channel B to TikTok only:
- Each channel gets its own n8n webhook URL in `n8n_webhook_config.json`
- Each webhook URL points to a different n8n workflow

```json
// n8n_webhook_config.json
{
  "global_url": "http://n8n:5678/webhook/idm-yt-download",
  "enabled": true,
  "channel_urls": {
    "UCchannel_A": "http://n8n:5678/webhook/workflow-youtube-facebook",
    "UCchannel_B": "http://n8n:5678/webhook/workflow-tiktok-only"
  }
}
```

**Config required:** Add more entries to `channel_monitor_config.json` (see Phase 1 format).

**Status:** ✅ Fully built and ready — just add channels to config

---

### Phase 3 — Dailymotion as Source → All Platforms

**Scenario:** You also have a Dailymotion channel whose content you want to replicate.

```
Source:
  Dailymotion Channel  (dailymotion.com/user/myusername)

Destinations:
  → YouTube
  → Facebook
  → TikTok
  → Instagram
  → Twitter

Trigger: New video on the Dailymotion channel
Result:  Video replicated to all destinations
```

yt-dlp supports Dailymotion natively — the watcher treats it identically to YouTube.

**Config required:**
```json
// channel_monitor_config.json
{
  "channels": {
    "dm_myusername": {
      "name": "My Dailymotion",
      "url": "https://www.dailymotion.com/user/myusername/videos",
      "auto_download": true,
      "videos_seen": []
    }
  }
}
```

**Status:** ✅ Fully built and ready — just add channel to config

---

### Phase 4 (Planned) — Local Web Dashboard

**Scenario:** Manage everything from a browser instead of editing JSON files.

```
You open http://localhost:3000

Dashboard shows:
  ├── Channels tab        → add/remove/pause channels, set destinations
  ├── Activity log tab    → see every download and upload event
  ├── Webhook config tab  → set n8n URLs per channel
  └── System status tab   → watcher running? n8n healthy?
```

**Status:** 🔲 Planned — ready to build

---

## 5. Data Flow (Detailed)

```
Step 1 — DETECT
  watcher wakes up every CHECK_INTERVAL minutes (default: 15)
  for each channel with auto_download = true:
    fetch last 15 video IDs from channel feed (no download, fast)
    compare against videos_seen list in config
    new = videos not in videos_seen

Step 2 — DOWNLOAD
  for each new video:
    yt-dlp downloads best quality MP4 to /shared/downloads/
    captures actual saved file path
    marks video ID as seen (saves to config immediately)

Step 3 — WEBHOOK
  POST http://n8n:5678/webhook/idm-yt-download
  payload: {
    event:        "download_completed",
    title:        "Video Title",
    file_path:    "/shared/downloads/Video Title.mp4",
    source_url:   "https://youtube.com/watch?v=xxxxx",
    channel_name: "Channel Name",
    channel_id:   "UCxxxxxxxx",
    channel_url:  "https://youtube.com/@Channel",
    duration:     847,
    timestamp:    "2026-04-18T14:30:00Z"
  }

Step 4 — UPLOAD (n8n handles this)
  Webhook received
  Read video file from /shared/downloads/
  Fan out in parallel to all configured platforms:
    → YouTube  (native n8n node, OAuth2)
    → Facebook (native n8n node, Graph API)
    → TikTok   (HTTP, 2-step upload API)
    → Instagram Reels (HTTP, Graph API)
    → X/Twitter (HTTP, OAuth2)
    → Dailymotion (HTTP, 2-step upload API)

Step 5 — CLEANUP
  watcher deletes files older than CLEANUP_TTL_HOURS (default: 24h)
  ensures disk space doesn't fill up
```

---

## 6. File Reference

```
IDM-YT/
├── headless_watcher.py          Core service — channel polling + download + webhook
├── Dockerfile                   Builds the watcher Docker image
├── docker-compose.yml           Runs watcher + n8n together
├── n8n_workflow.json            Import this into n8n — ready-made upload workflow
├── n8n_webhook.py               Webhook sender module (used by desktop app)
├── channel_monitor_config.json  YOUR CHANNEL LIST — edit this to add channels
├── n8n_webhook_config.json      Webhook URLs (global + per-channel routing)
└── dashboard/                   (Phase 4 — not yet built)
    ├── server.js
    └── public/
        └── index.html
```

---

## 7. Environment Variables (watcher)

| Variable | Default | Description |
|---|---|---|
| `CHECK_INTERVAL` | `15` | Minutes between channel checks |
| `CLEANUP_TTL_HOURS` | `24` | Hours before temp files are deleted (0 = never) |
| `N8N_WEBHOOK_URL` | `""` | Global fallback webhook URL |
| `DOWNLOAD_DIR` | `/shared/downloads` | Where videos are saved |
| `LOG_LEVEL` | `INFO` | `DEBUG` for verbose yt-dlp output |

---

## 8. n8n Credentials Needed

| Platform | Credential Type | Where to get it |
|---|---|---|
| YouTube | OAuth2 | [Google Cloud Console](https://console.cloud.google.com) → YouTube Data API v3 |
| Facebook | Graph API token | [Meta for Developers](https://developers.facebook.com) |
| TikTok | OAuth2 | [TikTok for Developers](https://developers.tiktok.com) |
| Instagram | OAuth2 | Same Meta App as Facebook (Instagram Graph API) |
| X / Twitter | OAuth2 | [Twitter Developer Portal](https://developer.twitter.com) |
| Dailymotion | OAuth2 | [Dailymotion API](https://developer.dailymotion.com) — scope: `manage_videos` |

---

## 9. Quick Start

```bash
# 1. Stop existing standalone n8n (if running)
docker stop n8n && docker rm n8n

# 2. Start full stack
cd C:\Users\T490s\Documents\IDM-YT\IDM-YT
docker compose up -d --build

# 3. Open n8n and import workflow
#    http://localhost:5678
#    New Workflow → Import from file → n8n_workflow.json

# 4. Add credentials in n8n for each platform

# 5. Add your channels to channel_monitor_config.json

# 6. Watch it run
docker compose logs -f watcher
```

---

## 10. Limitations & Notes

- **Download speed** depends on your internet connection and YouTube's rate limits
- **TikTok + Instagram** do not accept local file paths — they require either a public URL or their specific chunked upload API. n8n handles this via HTTP nodes
- **YouTube quota** — YouTube Data API has a daily quota (10,000 units). Each video upload costs ~1,600 units, so you can upload ~6 videos/day on a free quota. Request a quota increase in Google Cloud Console if needed
- **Copyright** — ensure you have rights to the content you are replicating
- **Rate limiting** — yt-dlp automatically handles YouTube 429 errors with exponential backoff
- The watcher marks a video as **seen even if download fails** — this prevents infinite retry loops on broken videos
