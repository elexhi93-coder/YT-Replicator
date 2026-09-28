# 04 — Logic and Business Rules: Sources & Catalog

**Pillar:** 1 · Sources & Catalog · **Chapter:** Logic and Business Rules · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/01_SOURCES_AND_CATALOG/00_PILLAR_OVERVIEW.md` · `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`  
**Invariants enforced:** INV-5, INV-7, INV-9, INV-11, F-48  

---

## 1. Domain Workflows & State Machines

Pillar 1 governs three primary background execution workflows:
1. **Source Registration & Canonicalization Flow**: Resolves user inputs to canonical IDs safely.
2. **Channel Scan Workflow (Tier 2 Flat Scan & Tier 1 RSS)**: Discovers media items without downloading bytes.
3. **Lazy Hydration Workflow (Tier 3 Enrichment)**: Enriches discovered items under strict rate limits.

---

### 1.1 Source Registration & Canonicalization Flow

When an operator registers a source URL or handle:

```
[ Operator Input: URL / @handle ]
                │
                ▼
[ Step 1: SSRF Firewall Check ] ──(Invalid / Non-YT)──► [ Raise InvalidSourceUrlError ]
                │
                ▼ (Valid YouTube Domain)
[ Step 2: Canonical ID Resolution (yt-dlp extract_flat) ]
                │
                ├──(Channel/Playlist Not Found)──────► [ Raise SourceNotFoundError ]
                │
                ▼ (Resolved UC... or PL...)
[ Step 3: Normalization & /videos suffix enforcement ]
                │
                ▼
[ Step 4: Duplicate Check in sources table (INV-9) ]
                │
                ├──(Already exists in workspace)─────► [ Return Existing Source ID ]
                │
                ▼ (New Source)
[ Step 5: Insert sources row with sync_status='IDLE' ]
                │
                ▼
[ Step 6: Dispatch Initial Discovery Scan to jobs.api ]
```


---

### 1.2 Source Synchronization State Machine

A tracked `source` transitions through the following discrete states:

```
       ┌───────────────────┐
       │       IDLE        │◄─────────────────────────────┐
       └─────────┬─────────┘                              │
                 │                                        │
           (Scan Triggered)                               │
                 │                                        │
                 ▼                                        │
       ┌───────────────────┐                              │
       │     SCANNING      │                              │
       └────┬─────────┬────┘                              │
            │         │                                   │
   (Scan Success)  (Partial Skip F-48)                    │
            │         │                                   │
            │         ▼                                   │
            │   ┌───────────────┐                         │
            │   │PARTIAL_WARNING│                         │
            │   └───────┬───────┘                         │
            │           │                                 │
            ▼           ▼                                 │
     (Update last_scanned_at)                             │
            │                                             │
            └─────────────────────────────────────────────┘
                 │
            (Fatal Network / Bot Ban / HTTP 429)
                 │
                 ▼
       ┌───────────────────┐
       │      FAILED       │
       └───────────────────┘
```

#### State Definitions & Transition Triggers:
- **`IDLE`**: Source is quiescent, waiting for manual scan or next scheduled RSS poll tick.
- **`SCANNING`**: A scan job is active in the worker queue. **Per-source concurrency lock is active** (`ADJ-P1-01`).
- **`PARTIAL_WARNING`**: Scan finished, but one or more videos raised `ItemUnavailableError` or `ItemPrivateError` (`F-48`). Catalog is successfully updated with reachable items.
- **`FAILED`**: Channel was deleted, terminated, geo-blocked as an entity, or hit consecutive YouTube bot blocks (HTTP 429). Retry backoff kicks in.
- **`PAUSED`**: Automated monitor cadence disabled by operator.

---

## 2. Invariant Enforcement & Boundary Defense

### 2.1 Enforcement of INV-7 (Scanning Never Downloads)
To guarantee that Pillar 1 never downloads media bytes:
1. **yt-dlp Execution Parameters**:
   - `extract_flat = "in_playlist"` or `True`.
   - `skip_download = True`.
   - `writeinfojson = False` (all metadata captured in-memory).
   - `outtmpl = None` (no local filesystem writes permitted).
2. **Static Boundary Guard**:
   - Architecture test `test_sources_cannot_import_media()` verifies that no file in `sources/` imports `media/` or references download tools (`ffmpeg`, `aria2c`).

### 2.2 Enforcement of F-48 (Partial Failure Resilience)
During a channel or playlist scan containing hundreds of items:
- A channel may contain deleted videos, private videos, or region-blocked clips.
- **Legacy Defect Fixed**: In the legacy codebase, an unhandled `ExtractorError` on item 42 aborted the entire batch, leaving items 43 to 500 undiscovered.
- **Pillar 1 Rule**:
  ```python
  for item in raw_playlist_entries:
      try:
          parsed_dto = parse_flat_entry(item)
          persist_catalog_item(parsed_dto)
      except (UnavailableVideoError, PrivateVideoError) as ex:
          log_scan_warning(source_id, item.get("id"), str(ex))
          record_skipped_item(source_id, item.get("id"), reason=ex.code)
          continue  # NEVER ABORT SCAN
  ```
- The scan completes and updates `last_scanned_at`.

---

## 3. Rate Discipline, Budgets & Limits

| Operation | Extraction Tier | Concurrency Limit | Rate Delay | Timeout | Retry Policy |
|---|---|---|---|---|---|
| **URL Validation** | Flat Scan | 5 global | None | 15s | 1 retry (5s backoff) |
| **Monitor Poll** | Tier 1 (RSS) | 10 global | None (HTTP GET) | 10s | 2 retries (10s backoff) |
| **Discovery Scan** | Tier 2 (Flat Scan) | 1 per source (max 3 global) | 1s between pages | 300s (5m) | 3 retries (exponential 10s, 30s, 60s) |
| **Lazy Hydration** | Tier 3 (Full Dump) | 1 global worker thread | 2.5s jittered delay | 30s / video | 2 retries (exponential 30s, 60s) |

---

## 4. SSRF & URL Validation Rules

Every input URL must strictly satisfy:
1. Scheme must be `https`.
2. Host must match regex: `^(www\.)?(youtube\.com|youtu\.be)$`.
3. Forbidden hosts: Any IP literal (e.g. `127.0.0.1`, `169.254.169.254`, `::1`), `localhost`, `0.0.0.0`.
4. No redirection to non-allowed domains: yt-dlp option `--no-check-certificate` is strictly **forbidden**.

#### Canonicalization Rules:
1. **Handle Resolution**: If URL matches `youtube.com/@([A-Za-z0-9_.-]+)`, resolve to the canonical channel ID (`UC...`) via yt-dlp metadata query.
2. **Playlist URLs**: If URL contains `list=([A-Za-z0-9_-]+)`, record `source_type = 'PLAYLIST'` and `canonical_id = playlist_id`.

---

## 5. Background Hydration Protocol

Discovered videos are written to `catalog_video` in a "lightweight" state with `is_hydrated = FALSE`.
Hydration is governed by the following rules:

1. **Hydration Trigger Modes**:
   - **On-Demand**: An operator clicks on a catalog item or opens the Video Inspector drawer. An immediate priority hydration request is dispatched.
   - **Pre-Replication Handshake**: When Pillar 3 prepares to queue an item for pipeline transfer, it requires complete tags, category, and full description.
   - **Lazy Background Sweep**: Low-priority background sweep enqueuing non-hydrated catalog videos at a strictly metered rate (1 item per 3 seconds max).
2. **Rate-Limit & Bot Protection Shield**:
   - Hydration jobs must inject randomized jitter (`delay = 2.5s + uniform(0.5s, 1.5s)`).
   - If YouTube returns HTTP 429 ("Too Many Requests") or bot check challenge:
     - Worker halts the hydration queue for a cooling-off period of 15 minutes.
     - Logs warning event: `EVENT_SOURCES_RATE_LIMITED`.

---

## 6. Duplicate Detection & Idempotency Rules

1. **Per-Source Natural Key**: `(source_id, video_id)` is strictly unique. An upsert clause `ON CONFLICT (source_id, video_id) DO UPDATE` updates mutable counters (`view_count`, `title`) without altering primary keys or manual flags.
2. **Workspace-Level Uniqueness**: Handled via `(workspace_id, video_id)` partial indexes to allow cross-pipeline queries without data pollution.

---

## 7. Change Log

- **2026-09-28:** Authored `04_LOGIC_AND_RULES.md` documenting registration workflows, synchronization state machine, SSRF firewall, rate discipline budgets, F-48 partial-failure loop, and lazy hydration triggers.

3. **Tab Normalization**: Channel URLs append `/videos` internally to avoid scraping shorts or live streams inadvertently if the channel layout changes.
