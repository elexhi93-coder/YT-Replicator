# 06 — Feature Roadmap

**Project:** YT-Replicator · **Status:** Draft · **Depends on:** `01`, `02`, `04`

Every feature found in the legacy has a home here. §4 is the coverage table: a
row from `01`'s disposition matrix that is missing from this document would mean
a feature was silently dropped.

**Phases:** `v1` — built now. `v2` — parked with a reason. `rejected` — dropped
with a reason.

---

## 1. v1 — the first working system

Grouped by module, because **one module is one work unit** (INV-11).

### `core`
Settings with documented defaults · the YouTube quota-day clock (Pacific) ·
typed error hierarchy · structured logging · media path-safety guard ·
SSRF allow-list validator.

### `accounts`
Login on every page · CSRF on every mutation · one workspace access helper ·
roles declared (`owner`/`operator`/`viewer`), only `owner` active · a single
default workspace created at install.

### `credentials`
Google Cloud client CRUD with an encrypted secret · OAuth connect and reconnect
· token health states · automatic refresh before expiry · per-client daily cap ·
explicit client → channel binding.

### `sources`
Add a source (channel or playlist; `@handle`, `/channel/UC…`, `/c/…`, `/user/…`,
`playlist?list=`) · flat scan, metadata only · lazy hydrate with rate-limit
discipline · catalog grid with filters (status, duration, date, title,
live-status, starred, ignored) · star · ignore · **mark as already uploaded** ·
CSV export and import · *n new since last scan* diff · availability tracking ·
scan status and error surfaced per source.

### `pipelines`
Pipeline CRUD with `draft → active → paused` · sources per pipeline (mode,
priority, daily cap, backfill cursor) · destinations per pipeline (enabled,
priority, privacy override) · reusable download profile · **missing-videos
preview before any download** · retention settings defaulting to `keep` ·
provenance-marker toggle · default privacy.

### `jobs`
Enqueue with a dedup check · atomic claim (`FOR UPDATE SKIP LOCKED`) · the full
state machine · transient versus permanent classification · backoff with jitter ·
**skip reasons visible on every row** · failure buckets · pause and resume ·
per-row retry and cancel · bulk enqueue with quota badge and the 10-row
confirmation · a 30-second soft-undo · worker heartbeat and staleness.

### `youtube`
Token refresh · destination inventory sync · resumable upload in 1 MB chunks ·
thumbnail set with WebP→JPEG conversion · quota accounting per `quota_date` ·
error translation to typed errors · provenance marker injection.

### `delivery`
`delivery` records with both-sided snapshots · `delivery_attempt` history ·
**reconciliation and its four outcomes** · mark-as-removed · provenance marker
format and parsing · marker and ledger matching, fingerprint as suggestion only.

### `media`
Storage roots (hot and cold, mounted state, free-space floor) · download through
the pipeline's profile · verification of size and `sha256` · atomic rename ·
**the retention evaluator in all four modes with dry run** · two-phase deletion ·
hygiene for partials and orphans · rehydrate · pin and unpin · `media_event`
audit · `archive_offline` handling.

### `worker`
Run loop · dispatch by intent · restart-recovery pass · gate evaluation for
quota, disk and operator pauses.

### `ops`
`audit_event` · worker heartbeats · log tail without the Docker socket · dry-run
retention view · explicit purge command · the backup rule.

### `ui`
The ten pages of `04` §8.4 · data-driven navigation · header context slot ·
named routes only · HTMX fragment-per-mutation · SSE on the queue only · empty
states and skip reasons · quota badges.

---

## 2. v2 — parked, with a reason

| Feature | Why not now |
|---|---|
| Multi-tenant UI: switcher, membership management, administration tab | Deferred by decision (D11). The shell already reserves the slots. |
| Routing rules (per-source → destination overrides) | D14 keeps one rule in v1; add it when a real case appears. |
| AI metadata rewriting | D10. Removes an external dependency from v1. |
| Upload scheduling (`publishAt`) | Needs a scheduler, and is not needed to prove the pipeline. |
| Cold-archive workflow and bulk rehydrate with size and time estimates | Single and bulk rehydrate exist; the planner is convenience. |
| Per-channel download overrides | One profile per pipeline is enough for v1. |
| Notifications, email, outbound webhooks | The Home page and heartbeats cover observability first. |
| Format probe endpoint (`extract_info`, no download) | 3–10 s per call and another SSRF surface, with no consumer yet. |
| Saved filter views and smart playlists | Grid filters cover the need. |
| Per-destination AI prompt overrides | Depends on AI, which is itself parked. |
| Per-video overrides and playlist-as-Library views | Deferred with their parents. |
| 2FA, API tokens, self-service signup, billing | Not part of a first deployment. |

---

## 3. Rejected — and why

| Feature | Reason |
|---|---|
| Multi-platform uploaders (Dailymotion, Facebook, TikTok, Instagram, X) | The scope this rewrite exists to remove. |
| n8n and webhook orchestration | D-06 loses upload results permanently; you asked for an in-house solution. |
| FFmpeg pipeline, per-destination transforms, GPU/NVENC | D15. The source file is uploaded as-is. |
| Desktop tkinter GUI, clipboard monitor, portable exe, PyInstaller builds | Gen-1 desktop product. |
| Plugin framework | An explicit non-goal; a generic extension layer is a project by itself. |
| Reading container logs through the Docker socket | D-05: turns a web compromise into host Docker access. |
| Exporting OAuth tokens with configuration | D-22: secrets must never be a downloadable file. |
| JSON state (`videos_seen`, `backfill_queue`) | F-04 and F-05: unqueryable, untrustworthy, unbounded. |
| Global credential rotation | D-23: the legacy's own manual warns against it. |
| Marking a video as seen when the download fails | D-07: discards recoverable work. |
| "Clean and rescan" and "wipe files" as routine operations | D-15: they existed because state was not trustworthy. |
| Two fragment prefixes (`/fragments` *and* `/partials`) | D-01: one prefix, always. |
| MP3 conversion, FFmpeg auto-install, 32-bit Win7 packaging | Gen-1 desktop concerns. |
| Bandwidth limiter and parallel-download toggles | Worker concurrency and priority are the real controls. |

---

## 4. Coverage table — every legacy row accounted for

`v1` = built now · `v2` = parked in §2 · `rejected` = declined in §3.

| Row | Feature | Phase |
|---|---|---|
| F-01 | Pipeline as the top configuration unit | v1 |
| F-02 | A source reusable across pipelines (D-02 fix) | v1 |
| F-03 | Two modes: backfill oldest-first, then monitor | v1 |
| F-04 | Backfill progress as a cursor, not a JSON array | v1 |
| F-05 | `videos_seen` JSON dedup list | rejected |
| F-06 | Per-channel daily cap with a resettable counter | v1 |
| F-07 | Per-destination quota, rotating only across dedicated projects | v1 |
| F-08 | Flat scan plus lazy hydrate | v1 |
| F-09 | Manual cherry-pick enqueue with a 30-second soft undo | v1 |
| F-10 | Filters: status, duration, date, title, live, starred, ignored | v1 |
| F-11 | CSV export and import of history | v1 |
| F-12 | Mark as already uploaded, bulk | v1 |
| F-13 | *What is new since last scan* diff view | v1 |
| F-14 | Download profiles | v1 |
| F-14b | Per-channel download overrides | v2 |
| F-15 | Format probe endpoint | v2 |
| F-16 | Queue ordering: oldest or newest | v1 |
| F-17 | Batch windows with a next-batch action | v1 |
| F-18 | Global pause and resume of downloads | v1 |
| F-19 | Failure buckets: transient versus permanent | v1 |
| F-20 | Integrity and storage gate before handoff | v1 |
| F-21 | Dedup reason shown on the row | v1 |
| F-22 | Job state machine | v1 |
| F-23 | Restart recovery for stuck jobs | v1 |
| F-24 | Chunked upload progress with live updates | v1 |
| F-25 | Thumbnail upload with WebP→JPEG conversion | v1 |
| F-26 | Per-destination upload defaults | v1 |
| F-27 | Destination health probe (as token health) | v1 |
| F-28 | Routing rules | v2 |
| F-29 | Worker heartbeat registry | v1 |
| F-30 | Log viewer reading files, not the Docker socket | v1 |
| F-31 | AI metadata enrichment | v2 |
| F-32 | Per-destination AI prompt overrides | v2 |
| F-33 | Multi-niche separation by duplicating credentials | rejected |
| F-34 | Configurable storage root plus a second root | v1 |
| F-35 | NTFS-folder mounting to survive drive-letter changes | rejected |
| F-36 | Cookies file and PO-token sidecar | v1 |
| F-37 | Multi-platform uploaders | rejected |
| F-38 | FFmpeg transformation pipeline | rejected |
| F-39 | GPU / NVENC encoding | rejected |
| F-40 | Scheduled uploads (`publishAt`) | v2 |
| F-41 | Compliance fields (kids, AI, paid promotion, licence) | v1 |
| F-42 | Persistent upload queue with priority | v1 |
| F-43 | Clipboard URL auto-detection | rejected |
| F-44 | Filename and path template system | v1 |
| F-45 | Playlist as a source kind | v1 |
| F-46 | Channel URL forms and normalisation | v1 |
| F-47 | Video-plus-playlist disambiguation | v1 |
| F-48 | Partial-failure tolerance (skip and continue) | v1 |
| F-49 | Plugin framework | rejected |
| F-50 | Configuration export and import | v2 |
| F-51 | Container-log streaming through the Docker socket | rejected |
| F-52 | `archive_offline` for detached drives | v1 |
| F-53 | Selective reset that preserves history | v1 |
| F-54 | Back up before any maintenance | v1 |
| F-55 | `processor/assets` for watermarks and intro clips | rejected |
| F-56 | `channels.source_id` backfill migration | not applicable |

**Reading the table:** every `rejected` row has a reason in §3, every `v2` row has
one in §2, and every `v1` row names a module in §1. Nothing is unowned, and the
counts in `01` (56 features) match this table.

Two rows are exceptions worth naming: **F-56** is a legacy data migration that has
no meaning for a fresh schema, and **F-14b** is deliberately split from F-14 so
the part that is needed is not delayed by the part that is not.