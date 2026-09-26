# 01 — Legacy Reverse Engineering (project003)

**Purpose:** guarantee we neither lose a feature nor inherit a defect. Every
behaviour found in `project003_bundle/` gets an explicit disposition.
**Method:** the **code is the evidence**; the docs are corroboration. Where they
disagree, the code wins and the disagreement is recorded as a defect. Anything
claimed but not confirmed is marked `UNVERIFIED` rather than assumed.
**Status:** in progress. The coverage log at the end tracks which files are read.

---

## Disposition legend

| Tag | Meaning |
|---|---|
| `KEEP` | Behaviour we want, essentially unchanged. |
| `ADAPT` | Behaviour we want, redesigned to fit our rules. |
| `DROP` | Out of v1 scope, or not worth carrying. |
| `DEFECT` | Implemented and wrong. Never port it; record why. |
| `UNVERIFIED` | Claimed in a doc, not confirmed in code. |

---

## 1. Component inventory

Three generations of the same product coexist in one tree. Anything referencing
Gen 1 is desktop-era and does not survive into a VPS web service.

### Gen 1 — desktop GUI (tkinter)

`video_downloader.py` (108 KB), `video_uploader.py` (98 KB),
`advanced_playlist_manager.py` (281 KB), `playlist_manager.py`,
`channel_monitor.py`, `channel_content_downloader.py`, `video_window.py`,
`cli_downloader.py`, `app.py`, `main_window.py`; `core/` (13 modules: DI
container, events, state machine, download queue/manager, progress tracker,
settings, config, url/format parser, clipboard monitor, video fetcher, logging,
exceptions, enums); `controllers/` (4), `views/` (3), `plugins/` (7 plugins +
manager), `uploaders/` (base, auth manager, 4 platform uploaders, upload manager,
upload window), `tests/` (5 files, all targeting `core/`).

**Disposition: `DROP` as code.** `CLEANUP_SUMMARY.md` claims most of this was
deleted; it is all still present, so the bundle is a pre-cleanup snapshot. Treat
it as an archive, not a codebase. Individual behaviours worth rescuing are listed
in section 4.

### Gen 2 — headless Docker + n8n

`headless_watcher.py` (88 KB), `n8n_webhook.py`, `channel_monitor_config.json`
(JSON state, not a database), `n8n/` (7 overlapping workflow JSONs),
`processor/processor.py` (FFmpeg step runner), `watcher/Dockerfile`,
root `Dockerfile`, `docker-compose.yml` (n8n, dashboard, bgutil-provider,
watcher, processor + `n8n_data` volume).

### Gen 3 — Flask dashboard + SQLite (the real product)

`dashboard/`: `app.py` (384 KB), `models.py` (41 KB), `uploader.py` (53 KB),
`oauth_youtube.py`, `sources.py`, `router.py`, `projects.py`,
`youtube_channels.py`, `ai_enricher.py`, `download_profile.py`,
`migrate_config.py`, 61 Jinja templates; `db/app.db` (860 KB of real data).

### Documentation set

62 markdown files, 475 KB, plus 81 Python files (1.93 MB). Three quarters of the
docs describe Gen 1 or Gen 2. Several contradict the code (see defect D-01).

---

## 2. Feature disposition matrix

Every behaviour found so far, with what happens to it. `PARK` = real idea,
deliberately deferred.

| # | Feature / behaviour | Where | Disposition | Note for our design |
|---|---|---|---|---|
| F-01 | Pipeline as the top config unit (sources + destinations + settings) | `models.pipelines` | `KEEP` | already our core entity |
| F-02 | Source channel belongs to one pipeline; `channel_id` globally unique | `models.channels` unique index | `DEFECT` → fix | see D-02; a source must be reusable |
| F-03 | Two-mode per channel: backfill oldest-first with a daily cap, then monitor | `PHASE1_BACKFILL_MONITOR.md` | `KEEP` | becomes our Stage 1 / Stage 2 |
| F-04 | Backfill queue stored as a JSON array in a column | `channels.backfill_queue` | `ADAPT` | make it rows; JSON arrays cannot be queried safely |
| F-05 | Unbounded `videos_seen` JSON list as the dedup record | `channel_monitor_config.json` | `DROP` | replaced by catalog + ledger |
| F-06 | Per-channel daily cap with a resettable counter | `channels.daily_limit`, `uploads_today` | `KEEP` | but note D-03 on the reset boundary |
| F-07 | Per-destination daily quota, rotated across Google Cloud projects | `destination_quota`, `youtube_projects.daily_cap` | `KEEP` | essential at ~1 600 units per upload |
| F-08 | Catalog: flat scan (metadata only) plus lazy hydrate | `sources.scan_source` / `hydrate_catalog` | `KEEP` | exactly our Stage 1 discovery |
| F-09 | Manual cherry-pick enqueue with a soft-undo window | `FEATURE_CATALOG_AND_BACKFILL.md` | `KEEP` | core operator UX |
| F-10 | Filters: status, duration, date, title, live-status, starred, ignored | `catalog_videos` | `KEEP` | starred doubles as our pin flag |
| F-11 | CSV export and import of upload history | `/api/history/export.csv`, `/api/history/import` | `KEEP` | doubles as the migration path |
| F-12 | "Mark as already uploaded", bulk | `FEATURE_CATALOG_AND_BACKFILL.md` | `KEEP` | required to adopt an existing channel |
| F-13 | Diff view: what is new since the last scan | `FEATURE_CATALOG_AND_BACKFILL.md` | `KEEP` | |
| F-14 | Per-pipeline download profiles: resolution cap, container, codecs, subtitles, thumbnail, info.json, skip shorts/live | `download_profiles` | `ADAPT` | keep the knobs, drop the per-channel override sprawl |
| F-15 | Probe a URL to list available formats | `/api/yt/probe` (RFC, unverified) | `ADAPT` | 3–10 s latency; needs a timeout, later |
| F-16 | Explicit ordering per queue action: oldest / newest | `FEATURE_DOWNLOADS_EXECUTION_SPEC.md` D-02 | `KEEP` | |
| F-17 | Batch windows with `batch_id` / index / total and "next batch" | same, D-03 | `ADAPT` | our queue plus worker covers the behaviour; keep the UI idea |
| F-18 | Global pause and resume of downloads | `/api/downloads/pause`, `/resume` | `KEEP` | |
| F-19 | Failure buckets: transient versus permanent | same, D-09 | `KEEP` | drives the retry policy |
| F-20 | Integrity and storage gate before upload handoff | same, D-10 `blocked_storage`, `blocked_integrity` | `KEEP` | this is our INV-3 plus the free-space guard |
| F-21 | Dedup reason shown to the operator | same, D-07 | `KEEP` | the team reached this conclusion independently |
| F-22 | Job state machine `pending → … → done / partial / failed` | `DATA_FLOW.md` | `ADAPT` | add `queued` and rehydrate; remove n8n-era states |
| F-23 | Restart recovery: reset jobs stuck in downloading or processing | `DATA_FLOW.md` §6 | `KEEP` | we need the same |
| F-24 | Per-chunk upload progress with live SSE updates | `upload_progress` table | `KEEP` | |
| F-25 | Thumbnail upload after the video, with WebP→JPEG conversion | `uploader._find_sibling_thumbnail` | `KEEP` | |
| F-26 | Per-destination upload defaults (privacy, options) | `destinations.default_privacy`, options form | `KEEP` | |
| F-27 | Destination health probe rendered as a status strip | `/api/destinations/<id>/test` | `ADAPT` | becomes an OAuth-token and quota check |
| F-28 | Routing rules: (source, filters) → destination, first match by priority | `routing_rules`, `router.py` | `KEEP` | strong feature; simplify the UI, keep the model |
| F-29 | Worker heartbeat registry for visibility | `worker_state` | `KEEP` | |
| F-30 | Container log viewer in the UI: tail N, level colours, auto-refresh | `DASHBOARD_SPEC.md` §5 | `ADAPT` | read log files, not the docker socket (D-05) |
| F-31 | AI metadata enrichment with fallback to the original on failure | n8n nodes, `ai_enricher.py` | `ADAPT` | off by default in v1; keep the fallback rule |
| F-32 | Per-destination AI prompt overrides | `destination_ai_form` | `PARK` | v2 |
| F-33 | Multi-niche separation by duplicating workflows and credentials | `MANHWA_KDRAMA_BLUEPRINT.md` | `DROP` | replaced by the pipeline and workspace model |
| F-34 | Configurable storage root, plus an optional second root for an external drive | `EXTERNAL_STORAGE_GUIDE.md` | `ADAPT` | keep the concept, add a capacity guard |
| F-35 | Stable NTFS-folder mounting so a drive-letter change is survivable | same, option A | `ADAPT` | deployment note; irrelevant on a Linux VPS |
| F-36 | YouTube cookie file plus a PO-token sidecar against bot detection | `docker-compose.yml`, watcher | `KEEP` | effectively mandatory on datacenter IPs |
| F-37 | Multi-platform uploaders: YouTube, Dailymotion, TikTok, Facebook, Instagram, X | `uploaders/`, n8n nodes | `DROP` v1 | the scope this rewrite exists to remove |
| F-38 | FFmpeg transformation pipeline: trim, crop, watermark, normalize, resize, reencode; global and per destination | `PROCESSING_PIPELINE.md`, `processor.py` | `DROP` v1 | keep the spec for a later platform project |
| F-39 | GPU NVENC encoding with CPU fallback | `processor.py`, `USE_GPU` | `DROP` v1 | |
| F-40 | Scheduled uploads (publish at a chosen time) | uploaders, YouTube `publishAt` | `PARK` | |
| F-41 | Compliance fields: made for kids, AI disclosure, paid promotion, license, embeddable, public stats, localizations, recording date and location | `UPLOADER_README.md` v2.1.0 | `KEEP` (subset) | this is the real YouTube uploader field list |
| F-42 | Persistent upload queue with priority and per-upload pause/resume | `uploaders/upload_manager.py` | `ADAPT` | our job table provides this |
| F-43 | Clipboard URL auto-detection | `FEATURE_1_CLIPBOARD_MONITOR.md` | `DROP` | desktop-only; the web equivalent is a paste box |
| F-44 | Filename and path template system with presets | `FEATURES.md` | `ADAPT` | reuse for storage layout naming |
| F-45 | Playlist as a source kind | `FEATURE_2_*`, `sources.kind` | `KEEP` | already in the schema |
| F-46 | Source URL forms: `@handle`, `/channel/UC…`, `/c/name`, `/user/name` | `FEATURE_2_UPDATE_OPTIONAL_PLAYLIST.md` | `KEEP` | resolution rules for adding a source |
| F-47 | Disambiguation when a URL is both a video and a playlist | same | `KEEP` | the same ambiguity exists in "add source" |
| F-48 | Partial-failure tolerance: skip unavailable items, continue the rest | `FEATURE_2_PLAYLIST_SUPPORT.md` | `KEEP` | applies to catalog scans and batches |
| F-49 | Plugin system for post-processing: chapters, comments, SponsorBlock, metadata, thumbnail variants, playlist index | `plugins/`, `plugin_manager.py` | `DROP` | generic extension frameworks are explicitly out of v1 |
| F-50 | Admin export and import of YouTube projects, channels and tokens | `Export-Import/` | `ADAPT` | export configuration only, never tokens |
| F-51 | Reading container logs through a mounted docker socket | `docker-compose.yml`, `app.py` | `DEFECT` | see D-05 |
| F-52 | A removed drive must not make its files look "missing" | inferred from `EXTERNAL_STORAGE_GUIDE.md` | `KEEP` | becomes our `archive_offline` state |

---

## 3. Defect register

Implemented and wrong. None of these are ported; each is listed so we do not
re-discover it later. Evidence is in the cited file.

| # | Defect | Evidence |
|---|---|---|
| D-01 | Docs contradict code. The container spec says the dashboard needs only `flask`; the real image installs six packages. Route prefixes differ too (`/fragments/*` versus `/partials/*`). | `CONTAINER_SPECS.md` vs `dashboard/Dockerfile`, `API_CONTRACTS.md` |
| D-02 | `channels.channel_id` is globally UNIQUE, so one source can never feed two pipelines. | `DATABASE_SCHEMA.md`, `models.py` |
| D-03 | The daily cap resets at midnight **UTC** while YouTube quota resets at midnight **Pacific**, and the counter is incremented on download while being named and reported as uploads. | `DATABASE_SCHEMA.md`, `channels.uploads_today` |
| D-04 | `DELETE /api/pipelines/<id>` cascades jobs and `upload_results`, destroying upload history. Violates INV-4. | `API_CONTRACTS.md` §1.1 |
| D-05 | The dashboard mounts `/var/run/docker.sock` to read container logs. On a shared VPS this turns a web-app compromise into host Docker access. | `docker-compose.yml` |
| D-06 | Upload results arrive via an n8n HTTP callback. The doc states that if the dashboard is down the result is lost permanently — the video is live and the app never learns it. | `N8N_WORKFLOW.md` §2 |
| D-07 | A failed download still marks the video as seen, so it is never retried and the failure is not visible. | `WORKFLOW_BLUEPRINT.md` §10, `ARCHITECTURE.md` |
| D-08 | Media deletion has seven owners, and the only automated one cannot see per-job folders, so it deletes nothing. | `headless_watcher._cleanup_old_downloads`, `uploader.py`, 6 sites in `app.py` |
| D-09 | Four storage layouts exist simultaneously: `<root>/<Channel>/<video_id>/<title>.mp4`, `/downloads/job_{id}/source.mp4`, per-destination outputs, and flat files. | `EXTERNAL_STORAGE_GUIDE.md`, `DATA_FLOW.md`, `PROCESSING_PIPELINE.md` |
| D-10 | Media state lives on the filesystem, so once a file is deleted the UI can no longer show it existed. | `partials/downloads_files.html`, `partial_downloads_files` |
| D-11 | OAuth access and refresh tokens and Google client secrets are plaintext `TEXT` columns; Gen 1 kept them in `~/.idm_tokens.json`. | `models.py` `oauth_tokens`, `youtube_projects` |
| D-12 | Live secrets sit in the working tree (`.env`, 2.6 KB) and there is no `.gitignore` anywhere in the project. | repo root, `git status` |
| D-13 | No destination inventory sync exists at all, so reconciliation is impossible: the app cannot see what is actually on the destination. | grep for `playlistItems` / `uploads_playlist` returns only our own docs |
| D-14 | Fuzzy title and date similarity is proposed as a dedup mechanism. It can silently suppress a legitimate upload. | `PIPELINE_WORKFLOW.md` §1 (legacy), `FEATURE_CATALOG_AND_BACKFILL.md` |
| D-15 | "Clean and rescan", "wipe files" and "cleanup stuck" escape hatches exist because the state was not trustworthy. A symptom, not a feature. | `app.py` routes |
| D-16 | Catalog scan and download are coupled inside the watcher, contrary to the rule that scanning must not download. | `headless_watcher.py` |
| D-17 | Backfill queue and seen-state live as JSON blobs in columns and a config file: not queryable, not transactional, unbounded. | `channels.backfill_queue`, `videos_seen` |
| D-18 | Seven overlapping n8n workflow JSONs with no single source of truth. | `n8n/` |
| D-19 | Four processes share one SQLite file over a bind mount, and the database sits inside the repository working tree. | `docker-compose.yml`, `db/app.db` |
| D-20 | The bundle ships real data, backups and an archive with no ignore rules: `db/app.db`, `.bak`, `.json-backup`, `project003_source.zip`. | repo tree |
| D-21 | `CLEANUP_SUMMARY.md` claims files were deleted that are still present, so its described structure is fiction. The bundle is a pre-cleanup snapshot. | `CLEANUP_SUMMARY.md` vs tree |
| D-22 | The admin export writes OAuth tokens into a downloadable JSON file. | `Export-Import/PROJECTS_EXPORT_IMPORT.md` |
| D-23 | Global credential rotation is implemented, and the project's own manual then warns "avoid global rotation for multiple channel owners". A built feature documented as unsafe. | `PROJECT003_USER_MANUAL.md` §21.1 |
| D-24 | Several RFC documents are titled `IMPLEMENTED` or describe endpoints that may not exist. Treat every such claim as `UNVERIFIED` until the code confirms it. | `features/*` |

---

## 4. Behaviour worth preserving

The mechanics, stripped of the platform mess. These are the details that cost
him the most time to learn.

### 4.1 Discovery and download (yt-dlp)

- Discovery is **one** `extract_flat` call per source and returns the whole
  channel in seconds (~150 videos). Fields used: `id`, `title`, `duration`,
  `upload_date`, `url`, `thumbnail`.
- Download options he settled on: `format =
  bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best`,
  `merge_output_format=mp4`, `writesubtitles`, `writeautomaticsub`,
  `subtitleslangs`, `writethumbnail`, `convert_thumbnails=jpg`,
  `writeinfojson`.
- Channel URLs: append `/videos` unless the path already ends in
  `/videos`, `/streams` or `/shorts`; `playlistend=None` to fetch everything;
  `ignoreerrors=True` so unavailable items are skipped and the rest continue.
- yt-dlp returns **newest first**; oldest-first backfill requires an explicit
  reverse.
- Bot detection is real: a cookies file plus the `bgutil` PO-token provider
  sidecar were both needed. `DOWNLOAD_WORKERS=5`, `FRAGMENT_WORKERS=4`.
- Hydrate discipline: 1 worker thread, 1 s between requests, ~30 s timeout,
  skip anything hydrated within 24 h, and refuse to run while a 429 seen in the
  last 5 minutes is unresolved.

### 4.2 Upload (YouTube)

- Resumable upload in 1 MB chunks, with a progress row written per chunk.
- Thumbnail is set after the video, WebP converted to JPEG in memory, 2 MB cap.
- Field set worth supporting: title, description, tags, category, privacy,
  made-for-kids, license, embeddable, public stats visibility, localisations,
  recording date and location, and `publishAt`.
- OAuth is the authorisation-code flow with a redirect URI of the form
  `.../oauth/callback`, scope `youtube.upload`, and refresh handling. The
  encryption key must be stored **outside** the database and backed up with it
  (n8n behaved this way: lose the key and the vault is unreadable).
- Quota: ~1 600 units per upload plus ~50 for metadata and thumbnail, so
  ~1 650 per video against 10 000/day → about **6 safe uploads per day** per
  Google project. Track a rolling 24 h count per destination.

### 4.3 States

Legacy job lifecycle: `pending → downloading → downloaded → processing →
processed → uploading → done | partial | failed`.
Ours: `queued → claimed → downloading → downloaded → uploading → uploaded |
failed_transient | failed_permanent`, with no FFmpeg states and a `rehydrate`
intent added.

### 4.4 Concurrency and claims

- Claim work with an atomic conditional update (`UPDATE … WHERE status = ?`),
  never a read-then-write.
- Restart recovery resets stuck states by age (downloading > 30 min,
  processing > 10 min).
- Manual enqueues get a 30 s soft-undo window, implemented as a claim filter
  (`created_at <= now - 30 s`).

### 4.5 API and UI patterns

- HTMX plus Tailwind, SSE for the queue, 4–6 s polling for live panels and
  logs. One fragment prefix only — the legacy shipped two.
- Bulk actions affecting more than 10 rows require typing the count.
- Every skipped item shows **why** it was skipped.

### 4.6 AI enrichment, if ever enabled

OpenRouter chat completions with a strict-JSON system prompt
(`youtube_title` ≤ 100 chars, `youtube_description` 150–300 chars,
`youtube_tags` 10–15 strings), temperature 0.7, `max_tokens` 600, 30 s
timeout, markdown fences stripped before parsing, and a hard fallback to the
original metadata with an `ai_used` flag on failure.

### 4.7 Security patterns to keep

- SSRF guard on every URL we accept (source creation, format probe):
  allow-list YouTube hosts only.
- CSRF on all state-changing requests.
- Ledger's identifying fields are write-once.
- Quota is enforced server-side; the UI cannot bypass it.

---

## 5. Late findings from the final sweep

| # | Finding | Disposition |
|---|---|---|
| F-53 | `scripts/maintenance/wipe_runtime_data.py` truncates `download_queue`, `jobs`, `job_outputs`, `videos` and non-setting `worker_state`, while **preserving** `upload_ledger`, sources, channels, pipelines and destinations — a deliberate "clean slate without losing upload history" tool. | `ADAPT` — we want exactly this, and it is only safe because the ledger really is the durable record. |
| F-54 | Backup-before-maintenance convention: copy the database file with a date suffix before running any one-shot script. | `KEEP` as an operational rule. |
| F-55 | `processor/assets/` for watermark images and intro/outro clips, bind-mounted into the processor. | `DROP` v1 (no FFmpeg), `PARK` with the transformation spec. |
| F-56 | `migrate_channels_source_fk.py` backfills `channels.source_id` for databases that predate the column. | `KEEP` — the pattern, not the script. It also proves he was mid-migration from channel-owned to source-owned catalogs when he stopped. |

Two more defects, both root causes rather than symptoms:

| # | Defect | Evidence |
|---|---|---|
| D-25 | The build order explicitly instructed adding `.env` and `./db/*.db` to `.gitignore`. It was never done, so secrets and live data sit in the tree today. | `BUILD_ORDER.md` step 1.4 |
| D-26 | The build order offered "register all API blueprints **or** put all routes in `app.py` for simplicity". The parenthetical was taken, which is the documented decision that produced the 384 KB, 100+ route monolith. | `BUILD_ORDER.md` step 3.1 |
| D-27 | Two incompatible schemas were specified and only one shipped: the session briefs describe 8 tables (`pipelines`, `sources`, `destinations`, `pipeline_steps`, `download_jobs`, `process_jobs`, `upload_jobs`, `event_log`); the code has 20 different ones. "LOCKED" carried no weight. | `sessions/STEP_1_1_models.md` vs `dashboard/models.py` |

---

## 6. Coverage log

**Documents: all 62 read.** Nothing in `project003_bundle/**/*.md` was skipped.

- `docs/` root (18): `README`, `ARCHITECTURE`, `API_CONTRACTS`, `BUILD_ORDER`,
  `CLEANUP_SUMMARY`, `CONTAINER_SPECS`, `DASHBOARD_SPEC`, `DATA_FLOW`,
  `DATABASE_SCHEMA`, `EXTERNAL_STORAGE_GUIDE`, `MANHWA_KDRAMA_BLUEPRINT`,
  `N8N_CREDENTIAL_SETUP`, `N8N_WORKFLOW`, `PHASE1_BACKFILL_MONITOR`,
  `PROCESSING_PIPELINE`, `PROJECT_SUMMARY`, `SUGGESTED_IMPROVEMENTS`,
  `UPLOADER_README`, `WORKFLOW_BLUEPRINT`.
- `docs/features/` (7), `docs/fixes/` (5), `docs/guides/` (6, one of which is a
  0-byte file), `docs/sessions/` (19), `docs/Export-Import/` (1),
  `docs/ADVANCED_PLAYLIST_MANAGER_DOCUMENTATION.md`.
- Bundle root `README.md`, `scripts/maintenance/README.md`,
  `.pytest_cache/README.md`.

**Known limitation, stated honestly:** for three very large files
(`ADVANCED_PLAYLIST_MANAGER_DOCUMENTATION.md`, and the middle sections of
`ARCHITECTURE.md` and `PROJECT003_USER_MANUAL.md`) the middle portions were
skimmed rather than read line by line, because they document the Gen-1 desktop
application in exhaustive UI detail while its disposition is already settled as
`DROP`. Every section that carries architectural weight was read in full.

**Code read:** `dashboard/models.py` (full schema and migration blocks),
`dashboard/app.py` selectively but deliberately — every deletion site, the
retention toggle, the upload entry points, the downloads/sources/routing
routes; `dashboard/uploader.py` (upload, thumbnail, cleanup);
`headless_watcher.py` (cleanup sweep, webhook firing, config handling);
`processor/processor.py` (poll, claim, step execution, cleanup); both
Dockerfiles; `docker-compose.yml`; `.env.example`; `requirements.txt`;
`dashboard/templates/downloads.html` and two partials.

**Code not read:** roughly 1.8 MB of the 1.93 MB of Python — the Gen-1 desktop
modules (`advanced_playlist_manager.py`, `video_downloader.py`,
`video_uploader.py`), `uploaders/*`, `core/*`, `views/*`, `controllers/*`,
`plugins/*`, most of the 384 KB `app.py`, most of the 88 KB
`headless_watcher.py`, 59 of 61 templates, and the n8n workflow JSONs. Their
dispositions are settled by the documents and the code already read; no open
question in `02`–`06` depends on them.
