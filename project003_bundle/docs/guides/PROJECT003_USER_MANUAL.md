# project003 — Detailed User Manual

## 1. Introduction

`project003` is a YouTube content automation suite built for personal workflow automation. It is designed to monitor YouTube sources, download video content, apply routing rules, and upload to YouTube using account/project-aware credentials.

This manual is detailed and intended for a complete workflow guide. It includes architecture, setup, dashboard usage, page-by-page walkthrough, upload flow details, troubleshooting, and screenshot support.

---

## 2. What This Project Solves

This project is intended for creators or operators who need:

- multiple source channels or playlists monitored automatically
- separate pipelines for different content workflows
- destination-specific upload handling
- account-aware YouTube upload routing
- a dashboard for uploads, queue, history, and logs
- clear troubleshooting and token management

It is a full automation stack, not just a downloader.

---

## 3. Architecture and Workflow

### 3.1 High-level workflow

```text
Source channels/playlists
        │
        ▼
headless_watcher.py
        │
        ▼
Downloaded videos + metadata
        │
        ▼
Pipeline routing + destinations
        │
        ▼
Upload orchestration (dashboard / n8n)
        │
        ▼
YouTube / webhook targets
```

### 3.2 Core stages

1. **Source monitoring and download**
   - `headless_watcher.py` polls configured YouTube sources.
   - It downloads videos and records source state.
   - It runs in `BACKFILL` mode for history, then `MONITOR` mode for new uploads.

2. **Pipeline routing and destination assignment**
   - Downloaded videos are attached to pipelines.
   - Destinations define where each video should be delivered.
   - Routing rules determine destination selection.

3. **Upload orchestration**
   - Uploads are processed by the dashboard and/or n8n.
   - YouTube uploads use project- and token-aware credential selection.
   - Bound destinations are uploaded via the correct account.

---

## 4. Installation and Setup

### 4.1 Repository setup

```bash
git clone https://github.com/yourusername/project003.git
cd project003
```

### 4.2 Environment configuration

Copy the environment template and edit it:

```bash
cp .env.example .env
```

Populate values such as:
- `N8N_WEBHOOK_URL`
- `LOG_LEVEL`
- upload limits and ports

### 4.3 Source channel configuration

Copy the example source config:

```bash
cp config/channels.example.json config/channels.json
```

Example source entry:

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

Field meanings:
- `auto_download`: whether the watcher should download content.
- `daily_upload_limit`: maximum uploads per day for that source.
- `backfill_complete`: if `true`, the watcher starts in monitoring-only mode.
- `videos_seen`: automatically managed by the watcher.

### 4.4 Webhook routing configuration

Copy the webhook example:

```bash
cp config/webhooks.example.json config/webhooks.json
```

Example:

```json
{
  "global_webhook_url": "http://n8n:5678/webhook/idm-yt-download",
  "channels": {
    "UCxxxxxxxxxxxxxxxxxx": "http://n8n:5678/webhook/channel-specific-path"
  }
}
```

If a source channel has no dedicated webhook, the watcher uses the global webhook.

### 4.5 Start the stack

Start the full service:

```bash
docker compose up -d --build
```

Monitor watcher logs:

```bash
docker compose logs -f watcher
```

### 4.6 Desktop GUI (optional)

If you want the local GUI for manual downloads:

```bash
python run_app.py
```

On Windows, run:

```bash
run_idm.bat
```

---

## 5. Dashboard Overview

The dashboard is the main management interface. It exposes the following pages:

- **Pipelines**
- **Sources**
- **Profiles**
- **Routing**
- **Uploads**
- **Projects**
- **Queue**
- **History**
- **Logs**
- **Admin**

### 5.1 Dashboard URL

Open the dashboard in your browser at:

```
http://localhost:8080
```

---

## 6. Screenshot Integration

This manual is designed to include screenshots. To attach screenshots:

1. Create `docs/guides/screenshots/`.
2. Save images with descriptive names.
3. Insert Markdown links in the relevant sections.

Example:

```md
![Pipelines page](screenshots/pipelines_tab.png)
```

### Suggested screenshot filenames

- `pipelines_tab.png`
- `pipeline_panel.png`
- `sources_tab.png`
- `profiles_tab.png`
- `routing_tab.png`
- `uploads_tab.png`
- `projects_tab.png`
- `queue_tab.png`
- `history_tab.png`
- `logs_tab.png`
- `admin_tab.png`

> Add one screenshot per major feature or workflow section.

---

## 7. Pipelines Page

The Pipelines page is the workflow control center.

### 7.1 What a pipeline is

A pipeline defines a content workflow by combining sources and destinations.

- **Source**: where content originates
- **Destination**: where content is uploaded or sent
- **Pipeline**: the set of rules and attachments linking sources to destinations

### 7.2 What you can do

- create new pipelines
- enable/disable pipelines
- add destinations
- bind destinations to YouTube channels
- configure upload privacy by destination

### 7.3 How to use it

1. Open **Pipelines**.
2. Click **New pipeline**.
3. Enter a name and optional description.
4. Save the pipeline.
5. Open the pipeline card.
6. Add destinations to the pipeline.
7. For YouTube destinations, add owner/channel binding if needed.

### 7.4 YouTube destination binding

Binding a destination to a specific channel is the safest option.

- select the owner account
- filter channels by owner
- bind the destination to a specific `youtube_channel_id`
- if left blank, the destination uses global project rotation

### 7.5 Screenshot placeholder

```md
![Pipelines page](screenshots/pipelines_tab.png)
```

---

## 8. Sources Page

The Sources page lists configured source feeds and their state.

### 8.1 What it shows

- source channel name and URL
- monitoring status
- source-specific metadata and catalog

### 8.2 How to use it

1. Go to **Sources**.
2. Review the source list.
3. Click a source item to open its catalog.
4. Inspect the video list and metadata for that source.

### 8.3 Screenshot placeholder

```md
![Sources page](screenshots/sources_tab.png)
```

---

## 9. Profiles Page

Profiles define download settings for pipelines.

### 9.1 What profiles control

- download quality
- audio/video codec selection
- subtitle and thumbnail settings
- format and container options

### 9.2 How to use it

1. Open **Profiles**.
2. Click **New profile**.
3. Configure the profile fields.
4. Save the profile.
5. Assign the profile to a pipeline in the pipeline settings.

### 9.3 Screenshot placeholder

```md
![Profiles page](screenshots/profiles_tab.png)
```

---

## 10. Routing Page

The Routing page manages destination selection rules.

### 10.1 What routing rules do

Rules determine whether a video matches a destination.

Common conditions:
- title regex
- title exclusions
- minimum/maximum duration
- skip shorts
- skip live
- tag matching

### 10.2 How to use it

1. Open **Routing**.
2. Review the routing matrix.
3. Create or edit rules.
4. Set rule conditions and destination assignments.
5. Preview and test rules.

### 10.3 Screenshot placeholder

```md
![Routing page](screenshots/routing_tab.png)
```

---

## 11. Uploads Page

The Uploads page shows active and recent uploads.

### 11.1 What it shows

- live upload progress
- recent upload history
- upload status and duration
- cancel buttons for active uploads

### 11.2 How to use it

1. Open **Uploads**.
2. Watch live progress bars.
3. Cancel uploads if necessary.
4. Review recent uploads to verify success.

### 11.3 Screenshot placeholder

```md
![Uploads page](screenshots/uploads_tab.png)
```

---

## 12. Projects Page

The Projects page manages YouTube upload credentials.

### 12.1 What it controls

- OAuth authorization for YouTube upload projects
- channel/project associations
- token health and reauthorization status

### 12.2 How to use it

1. Open **Projects**.
2. Add or edit a project.
3. Authorize the YouTube token.
4. Confirm the project is active.

### 12.3 Screenshot placeholder

```md
![Projects page](screenshots/projects_tab.png)
```

---

## 13. Queue Page

The Queue page shows in-flight work and manual queue controls.

### 13.1 What it shows

- queued jobs
- uploading jobs
- manual enqueue options
- queue ledger activity

### 13.2 How to use it

1. Open **Queue**.
2. Review the current job list.
3. Use manual queue actions if needed.
4. Inspect ledger activity for details.

### 13.3 Screenshot placeholder

```md
![Queue page](screenshots/queue_tab.png)
```

---

## 14. History Page

The History page is a searchable archive of completed work.

### 14.1 What it shows

- completed uploads and downloads
- status and timestamps
- searchable job history

### 14.2 How to use it

1. Open **History**.
2. Apply filters or search terms.
3. Review completed job details.

### 14.3 Screenshot placeholder

```md
![History page](screenshots/history_tab.png)
```

---

## 15. Logs Page

Logs are the primary troubleshooting tool.

### 15.1 What it shows

- runtime log entries
- errors and warnings
- search/filter controls

### 15.2 How to use it

1. Open **Logs**.
2. Search or filter queries.
3. Review errors and upload failures.

### 15.3 Screenshot placeholder

```md
![Logs page](screenshots/logs_tab.png)
```

---

## 16. Admin Page

The Admin page shows worker health.

### 16.1 What it shows

- connected background workers
- heartbeat status
- worker health indicators

### 16.2 How to use it

1. Open **Admin**.
2. Confirm worker connectivity.
3. Investigate stale or disconnected workers.

### 16.3 Screenshot placeholder

```md
![Admin page](screenshots/admin_tab.png)
```

---

## 17. YouTube Upload Flow

### 17.1 Project selection

The upload system selects a YouTube project before each upload.

- If the destination is bound to a channel, it uses channel-scoped rotation.
- Otherwise it uses global rotation.
- This is important to ensure uploads go to the correct account.

### 17.2 Credential loading

The upload worker loads credentials from stored OAuth tokens.

- Project-bound tokens use the correct OAuth client.
- Legacy tokens may fall back to environment credentials.
- If refresh fails, the token is marked for reauth.

### 17.3 Reauthorization handling

When a token cannot refresh, it is excluded from uploads until reauthorized.

### 17.4 Channel binding safety

Binding `youtube_channel_id` on a destination ensures uploads only use projects authorized for that channel.

---

## 18. Configuration Reference

### 18.1 `.env`

The `.env.example` file contains environment variables used across the stack.

Important values:
- `N8N_WEBHOOK_URL`
- `LOG_LEVEL`
- `DAILY_UPLOAD_LIMIT`
- `CHECK_INTERVAL`

### 18.2 `config/channels.json`

Defines source channels and monitor behavior.

### 18.3 `config/webhooks.json`

Maps sources to webhook endpoints.

### 18.4 `channel_monitor_config.json`

Stores watcher state:
- backfill progress
- seen videos
- source polling state

---

## 19. Common Tasks

### 19.1 Add a new source channel
1. Add a new entry in `config/channels.json`.
2. Restart the watcher.
3. Confirm the source appears in the dashboard.

### 19.2 Add or update a pipeline
1. Create the pipeline in the dashboard.
2. Add destinations.
3. Configure upload settings.

### 19.3 Add a new YouTube project
1. Open **Projects**.
2. Add the project.
3. Authorize OAuth.
4. Confirm it is active.

### 19.4 Reauthorize a token
1. Open **Projects**.
2. Reconnect stale projects.
3. Confirm the token is healthy.

### 19.5 Switch to monitor-only mode
- Set `backfill_complete` to `true` in the source config.
- Restart the watcher.

---

## 20. Troubleshooting

### 20.1 Upload failures
- Check **Uploads**.
- Inspect **Logs**.
- Confirm webhook paths and YouTube tokens.
- Verify the upload worker file paths.

### 20.2 Wrong account uploads
- Confirm destination channel binding.
- Check project-channel mappings.
- Make sure valid tokens exist for the channel.

### 20.3 Thumbnail issues
- Confirm the source has a valid thumbnail.
- Review upload logs for file path errors.

### 20.4 Reauth needed
- Reconnect the project in **Projects**.
- Verify the OAuth credentials.

### 20.5 Watcher inactivity
- Check `docker compose logs -f watcher`.
- Validate the source config.
- Review `channel_monitor_config.json`.

---

## 21. Advanced Notes

### 21.1 Multi-account safety
- Use destination-level channel binding when possible.
- Avoid global rotation for multiple channel owners.
- Prefer dedicated projects per channel or owner.

### 21.2 SaaS readiness
- Use persistent storage for downloads and database state.
- Secure the dashboard with authentication.
- Keep secrets in environment variables.
- Use separate projects for separate customers.

---

## 22. Project Structure

```
project003/
├── config/                     # config templates and examples
├── dashboard/                  # dashboard app, templates, and upload code
│   ├── templates/              # UI templates and partials
│   ├── app.py                  # dashboard routes and APIs
│   ├── projects.py             # YouTube project rotation logic
│   ├── uploader.py             # upload worker and credentials
│   └── oauth_youtube.py        # OAuth handling
├── docs/                       # documentation
│   ├── guides/                 # user and build guides
│   ├── features/               # feature docs
│   ├── fixes/                  # troubleshooting docs
│   └── README.md               # docs index
├── n8n/                        # n8n workflow definitions
├── Dockerfile                  # watcher image definition
├── docker-compose.yml          # full stack orchestration
├── headless_watcher.py         # source watcher and downloader
├── n8n_webhook.py              # webhook sender module
├── channel_monitor_config.json # watcher state file
└── .env.example                # environment variable template
```

---

## 23. Final Notes

This manual is meant to be expanded with screenshots and real workflow examples. Add images to `docs/guides/screenshots/` and replace placeholder links with your actual files.

Use this guide as the baseline documentation for development, operation, and future SaaS planning.

---

*Last updated: May 2026*
