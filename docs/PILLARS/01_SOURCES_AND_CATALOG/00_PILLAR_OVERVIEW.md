# 00 — Pillar Overview & The YouTube Field Universe

**Pillar:** 1 · Sources & Catalog · **Chapter:** Pillar Overview & Field Universe · **Status:** `drafting`
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/00` §2 · `docs/02` §4 · `docs/03` §2, §3 · `docs/04` §2, §9 · `docs/000_AI_DEEP_SPEC_STANDARD.md`
**Invariants touched:** INV-5, INV-7, INV-9, INV-11, INV-12

---

## 1. Mission

Pillar 1 discovers, ingests, and catalogs all metadata exposed by external content
sources (YouTube channels and playlists) and provides the operator browsing,
filtering, tagging, and backfill capabilities — **without ever downloading media bytes**.

It acts as the system's "Observatory" on the external content universe. It guarantees
that the application maintains a rich, searchable inventory of source media while
keeping media storage, routing, and job execution completely decoupled.

---

## 2. Owns vs. Does Not Own

### 2.1 What This Pillar Owns
- **The `source` entity**: Registration, canonicalization, and lifecycle of tracked
  external sources (channels, playlists).
- **The `catalog_video` entity**: The persistent metadata catalog of discovered media.
- **URL Resolution & SSRF Firewall**: Parsing input strings, verifying them against the
  SSRF allow-list, resolving handles (`@handle`) to canonical IDs (`UC...`), and
  normalizing URLs (`/videos` enforcement).
- **Discovery Scanning (Tier 2 Flat Scan)**: Executing fast, zero-quota batch catalog
  synchronization via `extract_flat=True`.
- **Monitor Cadence Polling (Tier 1 RSS)**: Fast, zero-quota polling of RSS feeds
  (`feeds/videos.xml?channel_id=...`) for near-real-time detection of newly published items.
- **Lazy Hydration Discipline (Tier 3 Hydration)**: Background, rate-controlled enrichment
  of expensive metadata (full descriptions, tags, chapter markers, view/like counts).
- **Partial Failure Resilience (F-48)**: Recording and skipping unavailable, private, or
  geo-blocked videos without crashing or failing a catalog scan batch.
- **Catalog Operator Interface**: Grid browsing, search/filter controls, starring,
  ignoring, marking as already-uploaded, and CSV export/import.

### 2.2 What This Pillar Does NOT Own

| Responsibility | Owning Pillar | Reason for Boundary |
|---|---|---|
| Downloading video/audio bytes | **Pillar 5** (`05_MEDIA_AND_STORAGE`) | **INV-7**: Scanning never downloads media. Source cataloging must never consume disk storage. |
| Deciding which video gets replicated | **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Sources are shared libraries (`INV-9`); routing rules belong to pipelines. |
| Work queueing, claims, & retries | **Pillar 4** (`04_JOB_ENGINE`) | Background scans and hydration jobs are executed by the queue worker. |
| Destination OAuth & quota tracking | **Pillar 2** (`02_DESTINATIONS_AND_AUTH`) | Destination credentials and upload quotas belong to the upload platform. |
| Recording upload history & ledger | **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Permanent delivery records live in the ledger, never in source catalogs. |
| HTTP cookies & PO-token storage | **Pillar 2** / **Pillar 7** | Bot detection bypass tokens are credential-shaped platform secrets. |

---

## 3. Dependencies & Invariants

### 3.1 Dependency Topology
- **Inbound Calls**: Called by **Pillar 3** (`pipelines` inspects catalog videos to compute
  unreplicated candidates) and **Pillar 7 / UI** (operator queries).
- **Outbound Calls**: Reads from **Pillar 0** (`SourceProvider` port contracts and DTOs).
  Never imports or invokes Pillars 3, 4, 5, or 6.

### 3.2 Invariants Enforced
- **INV-7 (Scanning Never Downloads)**: The `sources` module has zero dependencies on
  download engines or filesystem media writers.
- **INV-9 (Source Reusability)**: A single `source` row can be mapped to multiple
  independent replication pipelines via `pipeline_source` join records (`D-02`).
- **INV-5 (Deduplication Defense)**: Discovered items verify existing delivery history
  before presenting items for routing.
- **INV-11 & INV-12 (Boundary Isolation)**: Access to sources and catalog videos outside
  this pillar is permitted exclusively via `<sources>.api`.

---

## 4. Glossary Slice

| Term | Strict Architectural Definition |
|---|---|
| **Source** | A YouTube channel or playlist registered for tracking. Read-only entity. |

---

## 5. The YouTube Field Universe (Leaf-Level Registry)

Conforming to `docs/000_AI_DEEP_SPEC_STANDARD.md`, this section establishes the complete
field universe for YouTube video and channel attributes across all four acquisition tiers.

### 5.1 The Four Acquisition Tiers Explained

```
┌────────────────────────────────────────────────────────────────────────┐
│ TIER 1: RSS XML Feed                                                   │
│ URL: https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}  │
│ Latency: ~100-200ms | Quota Cost: 0 | Auth: None                       │
│ Coverage: Newest 15 videos only | Purpose: Fast monitor cadence        │
├────────────────────────────────────────────────────────────────────────┤
│ TIER 2: Fast Flat Scan (yt-dlp extract_flat=True)                      │
│ Latency: ~1-5s per 100 items | Quota Cost: 0 | Auth: None             │
│ Coverage: Full playlist/channel (thousands of items)                   │
│ Purpose: Initial channel scan, backfill candidate indexing             │
├────────────────────────────────────────────────────────────────────────┤
│ TIER 3: Hydrated Metadata (yt-dlp full dump / InnerTube)               │
│ Latency: ~1-3s per video | Quota Cost: 0 | Rate Limit: 1/sec           │
│ Coverage: Exhaustive (tags, full description, chapters, formats)       │
│ Purpose: On-demand hydration, operator inspection, pre-upload prep     │
├────────────────────────────────────────────────────────────────────────┤
│ TIER 4: Official YouTube Data API v3 (videos.list)                     │
│ Latency: ~300ms | Quota Cost: 1 unit/call (max 50 IDs)                 │
│ Auth: API Key or Channel OAuth | Purpose: Destination verification     │
└────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Video Metadata Field Universe

| Field Name | Extraction Tier | Visibility | Python Type | PostgreSQL Destination | UI Destination | Notes & Behavior |
|---|---|---|---|---|---|---|
| `video_id` | Tier 1, 2, 3, 4 | Public | `str` (11 chars) | `catalog_video.video_id` | Catalog Col: ID, Link | Matches `^[A-Za-z0-9_-]{11}$`. Unique per source. |
| `title` | Tier 1, 2, 3, 4 | Public | `str` | `catalog_video.title` | Catalog Col: Title | HTML entities unescaped (`&amp;` ➔ `&`). |
| `published_at` | Tier 1, 2, 3, 4 | Public | `datetime` (UTC) | `catalog_video.published_at` | Catalog Col: Date | Parsed to UTC `timestamptz`. Basis for backfill cursor. |
| `duration_sec` | Tier 2, 3, 4 | Public | `int \| None` | `catalog_video.duration_seconds` | Catalog Col: Duration | Absent in Tier 1 RSS. Formatted as `HH:MM:SS` in UI. |
| `thumbnail_url` | Tier 1, 2, 3, 4 | Public | `str \| None` | `catalog_video.thumbnail_url` | Catalog Col: Thumb | Default to `hqdefault.jpg` or `maxresdefault.jpg`. |
| `view_count` | Tier 2, 3, 4 | Public | `int \| None` | `catalog_video.view_count` | Catalog Col: Views | Flat scan provides approximate; Hydration provides exact. |
| `like_count` | Tier 3, 4 | Public | `int \| None` | `raw_metadata->'like_count'` | Inspector Drawer | Dislike counts are deprecated by YouTube API. |
| `description` | Tier 1 (snippet), Tier 3, 4 | Public | `str \| None` | `catalog_video.description` | Inspector Drawer, Previews | Tier 1 truncates to ~500 chars; Tier 3 fetches full text. |
| `tags` | Tier 3, 4 (owner) | Public / Mixed | `tuple[str, ...]` | `catalog_video.tags` (`jsonb`) | Inspector Drawer | Extracted from page HTML in Tier 3; Data API v3 only gives to owner. |
| `category_id` | Tier 3, 4 | Public | `str \| None` | `raw_metadata->'category_id'` | Inspector Drawer | Numeric string (e.g. `'22'` People & Blogs). |
| `channel_id` | Tier 1, 2, 3, 4 | Public | `str` | `sources.channel_id` | Source Header | Standard canonical `UC...` ID. |
| `channel_title` | Tier 1, 2, 3, 4 | Public | `str \| None` | `sources.title` | Source Header | Display name of the source channel. |
| `live_status` | Tier 2, 3, 4 | Public | `str` | `catalog_video.live_status` | Filter Bar, Status Badge | `'not_live'`, `'live'`, `'was_live'`. Live streams filtered out. |
| `availability` | Tier 2, 3, 4 | Public | `str` | `catalog_video.availability` | Status Badge | `'public'`, `'unlisted'`, `'private'`, `'unknown'`. |
| `aspect_ratio` | Tier 3 | Public | `float \| None` | `raw_metadata->'aspect_ratio'` | Inspector Drawer | Used to detect YouTube Shorts (`ratio < 1.0`). |
| `chapters` | Tier 3 | Public | `list[dict]` | `raw_metadata->'chapters'` | Inspector Drawer | Chapter timestamps and titles extracted from description/markers. |
| `raw_metadata` | Tier 2, 3 | Public | `dict` | `catalog_video.raw_metadata` | JSON Inspector Tab | Complete unaltered payload for debugging and forward-compatibility. |

| **Catalog Video** | A discrete video discovered from a source, holding metadata and sync state. |
| **Flat Scan** | A fast, batch metadata harvest (`yt-dlp --flat-playlist`) returning basic attributes without hitting YouTube API quotas. |
| **Hydration** | Deep retrieval of expensive metadata (full description, tags, categories) performed lazily or on demand. |
| **Backfill Cursor** | A timestamp tracking the oldest processed video during historical backfill. |
| **Monitor Cadence** | The periodic poll interval (e.g., 15 minutes) using RSS feeds to detect new uploads. |

---

## 6. End-to-End Data Lineage & Extraction Path

To adhere to `docs/000_AI_DEEP_SPEC_STANDARD.md` §4, the transformation of data from the
external world into the system is traced below:

```
[Tier 1: RSS / Tier 2: yt-dlp Flat Scan / Tier 3: yt-dlp Hydrated]
                           │
                           ▼
          [Pillar 0 Frozen DTO: SourceItem / SourceItemDetail]
                           │
                           ▼
       [Pillar 1 Ingestion Logic: sources.api.record_scan_items]
                           │
                           ▼
          [PostgreSQL 16: catalog_video & sources tables]
                           │
                           ▼
          [Pillar 1 Catalog UI: Catalog Grid & Video Drawer]
```

### 6.1 Transformation & Sanitization Rules
1. **Title Sanitization**: Strips control characters, normalizes Unicode NFC, and unescapes HTML entities.
2. **Tags Normalization**: Duplicates removed, lowercase normalized, converted to immutable tuple.
3. **UTC Normalization**: All publication dates parsed with explicit timezone conversion to UTC `timestamptz`.

---

## 7. Open Questions

Open questions: none. All definitions align with `docs/00`, `docs/02`, `docs/03`,
and `docs/000_AI_DEEP_SPEC_STANDARD.md`.

---

## 8. Change Log

- **2026-09-28:** Authored `00_PILLAR_OVERVIEW.md` establishing the mission, boundaries,
  invariants, and the exhaustive 4-tier YouTube Field Universe registry.

