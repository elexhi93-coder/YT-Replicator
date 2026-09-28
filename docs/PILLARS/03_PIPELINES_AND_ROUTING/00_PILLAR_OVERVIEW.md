# 00 — Pillar Overview & The Pipeline Candidate Universe

**Pillar:** 3 · Pipelines & Routing · **Chapter:** Pillar Overview · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/03` §2  
**Invariants touched:** INV-5, INV-6, INV-9, INV-11, INV-12  

---

## 1. Mission

Pillar 3 is the **decision brain** of the replication system. It binds catalog sources
(Pillar 1) to authorized YouTube destinations (Pillar 2), applies quality and filtering
policies, and produces a deterministic, fully explainable candidate queue.

It answers with complete transparency:
- *"Which video should be replicated next?"*
- *"Which destination channels should receive it?"*
- *"Why was video X skipped?"*

It enforces that already-delivered pairs are never re-enqueued (`INV-5`), ensures that
a single source can feed multiple independent pipelines without interference (`INV-9`),
and stores declarative retention policies so storage cleanup is completely reproducible
from the database alone (`INV-6`).

---

## 2. Owns vs. Does Not Own

### 2.1 What This Pillar Owns
- **The `pipeline` entity**: Lifecycle states (`DRAFT`, `ACTIVE`, `PAUSED`, `ARCHIVED`),
  execution schedule cadences, and pipeline-level defaults.
- **`pipeline_source`**: M:N association binding sources to pipelines, tracking synchronization
  mode (`BACKFILL`, `MONITOR`, `BOTH`), priority weights, daily throughput caps, and
  the persistent **backfill cursor** (`backfill_cursor_published_at`).
- **`pipeline_destination`**: Binding of destination channels with active toggles and
  channel-specific privacy overrides (`public`, `unlisted`, `private`).
- **`download_profile`**: Declarative media specs: max resolution (e.g. `1080p`), container
  format (`mp4`), subtitle language preferences, and exclusion toggles (`skip_shorts`,
  `skip_live_streams`, `min_duration_seconds`, `max_duration_seconds`).
- **Missing Candidate Engine**: Cross-referencing catalog inventory against the Pillar 6
  ledger to produce actionable replication pairs.
- **Explainability Registry**: Canonical classification of skipped candidates (`ALREADY_DELIVERED`,
  `SHORTS_FILTERED`, `LIVE_FILTERED`, `DURATION_OUT_OF_BOUNDS`, `SOURCE_UNAVAILABLE`, `DESTINATION_QUOTA_FULL`).

### 2.2 What This Pillar Does NOT Own

| Responsibility | Owning Pillar | Reason for Boundary |
|---|---|---|
| Executing downloads or media rendering | **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Pillar 3 defines policy; Pillar 5 runs yt-dlp/ffmpeg. |
| Executing YouTube video uploads | **Pillar 2** (`02_DESTINATIONS_AND_AUTH`) | Pillar 2 owns OAuth tokens and upload chunking. |
| Enqueueing worker jobs and retries | **Pillar 4** (`04_JOB_ENGINE`) | Pillar 4 manages PostgreSQL `jobs` queue and concurrency. |
| Recording delivery receipts | **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Pillar 6 is the sole authority on what was delivered. |
| Source crawling and catalog indexing | **Pillar 1** (`01_SOURCES_AND_CATALOG`) | Pillar 1 discovers videos from external channels. |

---

## 3. The Pipeline Candidate Universe (Leaf-Level Registry)

All attributes governing replication decisions, profile constraints, and explainability:

| Attribute Name | Entity / Context | Data Type | Default / Allowed Values | UI Placement | Notes |
|---|---|---|---|---|---|
| `pipeline_name` | `pipeline` | `str(120)` | Required | Pipeline List / Header | Human-readable pipeline identifier. |
| `status` | `pipeline` | `enum` | `'DRAFT'`, `'ACTIVE'`, `'PAUSED'`, `'ARCHIVED'` | Status Pill | Only `'ACTIVE'` generates work for the Job Engine. |
| `sync_mode` | `pipeline_source` | `enum` | `'BACKFILL'`, `'MONITOR'`, `'BOTH'` | Source Row in Pipeline | `BACKFILL`: Oldest-first from cursor. `MONITOR`: Newest-first. |
| `backfill_cursor` | `pipeline_source` | `TIMESTAMPTZ` | Source oldest `published_at` | Candidate Inspector | Cursor advances as oldest videos deliver (`INV-9`). |
| `max_resolution` | `download_profile`| `enum` | `'720p'`, `'1080p'`, `'1440p'`, `'2160p'` | Profile Settings | Capped during ffmpeg/yt-dlp download in Pillar 5. |
| `skip_shorts` | `download_profile`| `bool` | `True` | Filter Toggles | Excludes videos with duration < 60s or marked short. |
| `skip_live_streams`| `download_profile`| `bool` | `True` | Filter Toggles | Excludes live broadcasts or live recordings. |
| `min_duration_s` | `download_profile`| `int` | `0` (None) | Filter Sliders | Minimum acceptable runtime in seconds. |
| `max_duration_s` | `download_profile`| `int` | `14400` (4 hours) | Filter Sliders | Maximum acceptable runtime in seconds. |
| `retention_policy`| `pipeline` | `enum` | `'KEEP'`, `'DELETE_AFTER_UPLOAD'` | Pipeline Settings | Declarative policy executed by Pillar 5 (`INV-6`). |
| `destination_privacy`| `pipeline_dest`| `enum` | `'inherit'`, `'public'`, `'unlisted'`, `'private'` | Destination Row | Overrides channel default privacy. |

---

## 4. Candidate Skip Reason Taxonomy

Every video evaluated by a pipeline is classified into exactly one state:
1. **`ACTIONABLE`**: Passes all filters, not delivered to destination, quota available.
2. **`ALREADY_DELIVERED`**: Delivery receipt confirmed in Pillar 6 ledger (`INV-5`).
3. **`SHORTS_FILTERED`**: Profile has `skip_shorts=True` and video is under 60 seconds.
4. **`LIVE_FILTERED`**: Profile has `skip_live_streams=True` and video was a broadcast.
5. **`DURATION_OUT_OF_BOUNDS`**: Runtime outside `[min_duration_s, max_duration_s]`.
6. **`SOURCE_UNAVAILABLE`**: Source catalog record is marked `UNAVAILABLE` or private.
7. **`DESTINATION_QUOTA_FULL`**: Target YouTube client has < 1,600 units remaining today.
