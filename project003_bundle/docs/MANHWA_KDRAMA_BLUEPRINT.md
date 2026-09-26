# Content Replication Blueprint
## Manhwa Recap & KDrama Recap — Full Workflow Documentation

**Last updated: April 18, 2026**

---

## 1. Overview

Two independent content pipelines run in parallel inside the same Docker stack.
Each niche has its own source channels, its own n8n workflow, and its own destination accounts.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  idm-yt-watcher (single service, watches ALL 4 channels)                 │
│                                                                          │
│   ┌──────────────────────────┐   ┌──────────────────────────┐           │
│   │  MANHWA RECAP            │   │  KDRAMA RECAP             │           │
│   │  Source Channel 1        │   │  Source Channel 1         │           │
│   │  Source Channel 2        │   │  Source Channel 2         │           │
│   └────────────┬─────────────┘   └────────────┬──────────────┘           │
│                │ webhook A                     │ webhook B                │
└────────────────┼──────────────────────────────┼──────────────────────────┘
                 │                              │
                 ▼                              ▼
    ┌────────────────────────┐     ┌────────────────────────┐
    │  n8n Workflow A        │     │  n8n Workflow B        │
    │  "Manhwa Upload"       │     │  "KDrama Upload"       │
    │  /webhook/manhwa       │     │  /webhook/kdrama       │
    └────────────┬───────────┘     └────────────┬───────────┘
                 │                              │
        ┌────────┴────────┐           ┌─────────┴────────┐
        ▼                 ▼           ▼                   ▼
  [Manhwa Accounts]             [KDrama Accounts]
  YouTube Manhwa          YouTube KDrama
  Dailymotion Manhwa      Dailymotion KDrama
  Facebook Manhwa Page    Facebook KDrama Page
  TikTok Manhwa           TikTok KDrama
  Instagram Manhwa        Instagram KDrama
  Twitter Manhwa          Twitter KDrama
```

---

## 2. Manhwa Recap Pipeline

### 2.1 Flowchart

```mermaid
flowchart TD
    subgraph SOURCES["📥 Source Channels (YouTube)"]
        MWS1["Manhwa Source Channel 1\n@ManhwaChannel_A"]
        MWS2["Manhwa Source Channel 2\n@ManhwaChannel_B"]
    end

    subgraph WATCHER["🐳 idm-yt-watcher (Docker)"]
        W1["Poll channels\nevery 15 min"]
        W2{"New video\ndetected?"}
        W3["Download video\n→ /shared/downloads/\nvideo.mp4"]
        W4["Mark video as seen\nSave to config"]
        W5["Fire webhook\n→ n8n /webhook/manhwa"]
        W6["Sleep until\nnext cycle"]
    end

    subgraph N8N_MW["⚙️ n8n — Manhwa Upload Workflow"]
        N1["Webhook Trigger\nPOST /webhook/manhwa"]
        N2["Prepare Metadata\ntitle, description,\ntags: manhwa, recap"]
        N3["Read Video File\nfrom /shared/downloads"]
        N4["YouTube Upload\n@ManhwaYouTubeChannel"]
        N5["Dailymotion Upload\nManhwa DM Account"]
        N6["Facebook Upload\nManhwa FB Page"]
        N7["TikTok Upload\nManhwa TikTok"]
        N8["Instagram Reels\nManhwa IG"]
        N9["X / Twitter Post\nManhwa Twitter"]
        N10["Log Results"]
    end

    subgraph CLEANUP["🧹 Cleanup"]
        C1["Delete files older\nthan 24 hours"]
    end

    MWS1 --> W1
    MWS2 --> W1
    W1 --> W2
    W2 -- No --> W6
    W2 -- Yes --> W3
    W3 --> W4
    W4 --> W5
    W5 --> N1
    W6 --> W1

    N1 --> N2
    N2 --> N3
    N3 --> N4
    N3 --> N5
    N3 --> N6
    N3 --> N7
    N3 --> N8
    N3 --> N9
    N4 & N5 & N6 & N7 & N8 & N9 --> N10
    N10 --> C1
```

### 2.2 Channel Configuration

```json
// channel_monitor_config.json — Manhwa entries
{
  "channels": {
    "UC_manhwa_source_A": {
      "name": "Manhwa Source Channel 1",
      "url": "https://youtube.com/@ManhwaChannel_A",
      "auto_download": true,
      "videos_seen": [],
      "last_check": null
    },
    "UC_manhwa_source_B": {
      "name": "Manhwa Source Channel 2",
      "url": "https://youtube.com/@ManhwaChannel_B",
      "auto_download": true,
      "videos_seen": [],
      "last_check": null
    }
  }
}
```

### 2.3 Webhook Routing

```json
// n8n_webhook_config.json — Manhwa routing
{
  "channel_urls": {
    "UC_manhwa_source_A": "http://n8n:5678/webhook/manhwa",
    "UC_manhwa_source_B": "http://n8n:5678/webhook/manhwa"
  }
}
```

### 2.4 n8n Credential Set — Manhwa

| Platform | Credential Name (n8n) | Account |
|---|---|---|
| YouTube | `YouTube OAuth2 — Manhwa` | @ManhwaYouTubeChannel |
| Dailymotion | `Dailymotion OAuth2 — Manhwa` | Manhwa DM account |
| Facebook | `Facebook Graph API — Manhwa` | Manhwa Page token |
| TikTok | `TikTok OAuth2 — Manhwa` | Manhwa TikTok account |
| Instagram | `Instagram OAuth2 — Manhwa` | Manhwa IG account |
| X / Twitter | `Twitter OAuth2 — Manhwa` | Manhwa Twitter account |

---

## 3. KDrama Recap Pipeline

### 3.1 Flowchart

```mermaid
flowchart TD
    subgraph SOURCES["📥 Source Channels (YouTube)"]
        KDS1["KDrama Source Channel 1\n@KDramaChannel_A"]
        KDS2["KDrama Source Channel 2\n@KDramaChannel_B"]
    end

    subgraph WATCHER["🐳 idm-yt-watcher (Docker)"]
        W1["Poll channels\nevery 15 min"]
        W2{"New video\ndetected?"}
        W3["Download video\n→ /shared/downloads/\nvideo.mp4"]
        W4["Mark video as seen\nSave to config"]
        W5["Fire webhook\n→ n8n /webhook/kdrama"]
        W6["Sleep until\nnext cycle"]
    end

    subgraph N8N_KD["⚙️ n8n — KDrama Upload Workflow"]
        N1["Webhook Trigger\nPOST /webhook/kdrama"]
        N2["Prepare Metadata\ntitle, description,\ntags: kdrama, recap"]
        N3["Read Video File\nfrom /shared/downloads"]
        N4["YouTube Upload\n@KDramaYouTubeChannel"]
        N5["Dailymotion Upload\nKDrama DM Account"]
        N6["Facebook Upload\nKDrama FB Page"]
        N7["TikTok Upload\nKDrama TikTok"]
        N8["Instagram Reels\nKDrama IG"]
        N9["X / Twitter Post\nKDrama Twitter"]
        N10["Log Results"]
    end

    subgraph CLEANUP["🧹 Cleanup"]
        C1["Delete files older\nthan 24 hours"]
    end

    KDS1 --> W1
    KDS2 --> W1
    W1 --> W2
    W2 -- No --> W6
    W2 -- Yes --> W3
    W3 --> W4
    W4 --> W5
    W5 --> N1
    W6 --> W1

    N1 --> N2
    N2 --> N3
    N3 --> N4
    N3 --> N5
    N3 --> N6
    N3 --> N7
    N3 --> N8
    N3 --> N9
    N4 & N5 & N6 & N7 & N8 & N9 --> N10
    N10 --> C1
```

### 3.2 Channel Configuration

```json
// channel_monitor_config.json — KDrama entries
{
  "channels": {
    "UC_kdrama_source_A": {
      "name": "KDrama Source Channel 1",
      "url": "https://youtube.com/@KDramaChannel_A",
      "auto_download": true,
      "videos_seen": [],
      "last_check": null
    },
    "UC_kdrama_source_B": {
      "name": "KDrama Source Channel 2",
      "url": "https://youtube.com/@KDramaChannel_B",
      "auto_download": true,
      "videos_seen": [],
      "last_check": null
    }
  }
}
```

### 3.3 Webhook Routing

```json
// n8n_webhook_config.json — KDrama routing
{
  "channel_urls": {
    "UC_kdrama_source_A": "http://n8n:5678/webhook/kdrama",
    "UC_kdrama_source_B": "http://n8n:5678/webhook/kdrama"
  }
}
```

### 3.4 n8n Credential Set — KDrama

| Platform | Credential Name (n8n) | Account |
|---|---|---|
| YouTube | `YouTube OAuth2 — KDrama` | @KDramaYouTubeChannel |
| Dailymotion | `Dailymotion OAuth2 — KDrama` | KDrama DM account |
| Facebook | `Facebook Graph API — KDrama` | KDrama Page token |
| TikTok | `TikTok OAuth2 — KDrama` | KDrama TikTok account |
| Instagram | `Instagram OAuth2 — KDrama` | KDrama IG account |
| X / Twitter | `Twitter OAuth2 — KDrama` | KDrama Twitter account |

---

## 4. Combined System Map

```mermaid
flowchart LR
    subgraph SRC["📥 Source Channels (4 total)"]
        MW1["@ManhwaChannel_A"]
        MW2["@ManhwaChannel_B"]
        KD1["@KDramaChannel_A"]
        KD2["@KDramaChannel_B"]
    end

    subgraph DOCKER["🐳 Docker Stack (local machine)"]
        W["idm-yt-watcher\n(all 4 channels)"]
        VOL["/shared/downloads"]
        N8N["n8n :5678"]
    end

    subgraph WF["n8n Workflows"]
        WFA["Workflow A\n/webhook/manhwa"]
        WFB["Workflow B\n/webhook/kdrama"]
    end

    subgraph MW_DEST["🎌 Manhwa Destinations"]
        MYT["YouTube\n@ManhwaChannel"]
        MDM["Dailymotion\nManhwa"]
        MFB["Facebook\nManhwa Page"]
        MTK["TikTok\nManhwa"]
        MIG["Instagram\nManhwa"]
        MTW["Twitter\nManhwa"]
    end

    subgraph KD_DEST["🎭 KDrama Destinations"]
        KYT["YouTube\n@KDramaChannel"]
        KDM["Dailymotion\nKDrama"]
        KFB["Facebook\nKDrama Page"]
        KTK["TikTok\nKDrama"]
        KIG["Instagram\nKDrama"]
        KTW["Twitter\nKDrama"]
    end

    MW1 & MW2 --> W
    KD1 & KD2 --> W
    W --> VOL
    W -- "POST /webhook/manhwa" --> WFA
    W -- "POST /webhook/kdrama" --> WFB
    WFA & WFB --> VOL
    WFA --> MYT & MDM & MFB & MTK & MIG & MTW
    WFB --> KYT & KDM & KFB & KTK & KIG & KTW
    N8N --- WFA
    N8N --- WFB
```

---

## 5. Complete Config File (Both Niches)

```json
// channel_monitor_config.json
{
  "channels": {
    "UC_manhwa_source_A": {
      "name": "Manhwa Source Channel 1",
      "url": "https://youtube.com/@ManhwaChannel_A",
      "auto_download": true,
      "videos_seen": [],
      "last_check": null
    },
    "UC_manhwa_source_B": {
      "name": "Manhwa Source Channel 2",
      "url": "https://youtube.com/@ManhwaChannel_B",
      "auto_download": true,
      "videos_seen": [],
      "last_check": null
    },
    "UC_kdrama_source_A": {
      "name": "KDrama Source Channel 1",
      "url": "https://youtube.com/@KDramaChannel_A",
      "auto_download": true,
      "videos_seen": [],
      "last_check": null
    },
    "UC_kdrama_source_B": {
      "name": "KDrama Source Channel 2",
      "url": "https://youtube.com/@KDramaChannel_B",
      "auto_download": true,
      "videos_seen": [],
      "last_check": null
    }
  }
}
```

```json
// n8n_webhook_config.json
{
  "global_url": "",
  "enabled": true,
  "channel_urls": {
    "UC_manhwa_source_A": "http://n8n:5678/webhook/manhwa",
    "UC_manhwa_source_B": "http://n8n:5678/webhook/manhwa",
    "UC_kdrama_source_A": "http://n8n:5678/webhook/kdrama",
    "UC_kdrama_source_B": "http://n8n:5678/webhook/kdrama"
  }
}
```

---

## 6. n8n Setup Checklist

### Workflows to create (2 total)
- [ ] Import `n8n_workflow.json` → rename to **"Manhwa Upload"** → set webhook path to `manhwa`
- [ ] Duplicate workflow → rename to **"KDrama Upload"** → set webhook path to `kdrama`

### Credentials to create in n8n (12 total — 6 per niche)

**Manhwa set:**
- [ ] YouTube OAuth2 — Manhwa
- [ ] Dailymotion OAuth2 — Manhwa
- [ ] Facebook Graph API — Manhwa
- [ ] TikTok OAuth2 — Manhwa
- [ ] Instagram OAuth2 — Manhwa
- [ ] Twitter OAuth2 — Manhwa

**KDrama set:**
- [ ] YouTube OAuth2 — KDrama
- [ ] Dailymotion OAuth2 — KDrama
- [ ] Facebook Graph API — KDrama
- [ ] TikTok OAuth2 — KDrama
- [ ] Instagram OAuth2 — KDrama
- [ ] Twitter OAuth2 — KDrama

---

## 7. What Happens Step by Step (Example)

```
14:00  watcher wakes up
       checks @ManhwaChannel_A  → 2 new videos found
       checks @ManhwaChannel_B  → 0 new videos
       checks @KDramaChannel_A  → 1 new video found
       checks @KDramaChannel_B  → 0 new videos

14:01  downloads Manhwa video 1 → /shared/downloads/Title_1.mp4
       fires POST → http://n8n:5678/webhook/manhwa
       n8n uploads Title_1.mp4 to all 6 Manhwa accounts

14:04  downloads Manhwa video 2 → /shared/downloads/Title_2.mp4
       fires POST → http://n8n:5678/webhook/manhwa
       n8n uploads Title_2.mp4 to all 6 Manhwa accounts

14:07  downloads KDrama video 1 → /shared/downloads/Title_3.mp4
       fires POST → http://n8n:5678/webhook/kdrama
       n8n uploads Title_3.mp4 to all 6 KDrama accounts

14:10  all downloads complete
       watcher saves updated videos_seen lists to config
       watcher sleeps 15 minutes

14:25  next cycle begins...

38:00  cleanup runs: deletes files older than 24h
```

---

## 8. Next Steps

| Step | Action | Who |
|---|---|---|
| 1 | Replace placeholder channel IDs/URLs with real ones in config | You |
| 2 | `docker compose up -d --build` | You |
| 3 | Import `n8n_workflow.json`, duplicate for KDrama | You (n8n UI) |
| 4 | Create 12 credentials in n8n (one per platform per niche) | You (n8n UI) |
| 5 | Activate both workflows | You (n8n UI) |
| 6 | Monitor first cycle with `docker compose logs -f watcher` | You |
| 7 | Build local dashboard UI (Phase 4) | To be built |
