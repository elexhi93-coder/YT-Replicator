# 03 — Interface Contract: Sources & Catalog

**Pillar:** 1 · Sources & Catalog · **Chapter:** Interface Contract · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/04_ARCHITECTURE.md` §5  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/PILLARS/01_SOURCES_AND_CATALOG/05_DATA_MODEL.md`  
**Invariants enforced:** INV-7, INV-9, INV-11, INV-12  

---

## 1. Published Surface Overview

In strict conformance with **INV-11** (boundary isolation) and **INV-12** (DTO boundaries),
all access to Pillar 1 from outside the module (UI, background workers, or sibling pillars)
must flow through the published module boundary:

```python
from sources import api as sources_api
```

Direct queries against `sources` or `catalog_video` SQL tables by other modules are
prohibited and blocked by static boundary tests.

### 1.1 Sibling Access Matrix

| Caller | Permitted Functions | Forbidden Functions | Reason |
|---|---|---|---|
| **UI Layer** | All `get_*`, `list_*`, `register_source`, `trigger_scan` | Internal parsing or direct scraper invocation | UI only commands actions; doesn't execute scans. |
| **Pillar 3 (Pipelines)** | `get_catalog_items_for_pipeline`, `get_source_by_id` | `register_source`, `delete_source` | Pipelines inspect candidate videos; don't manage source lifecycle. |
| **Pillar 4 (Jobs)** | `execute_source_scan`, `execute_item_hydration` | All UI helper queries | Worker engine invokes execution units only. |
| **Pillar 5 (Media)** | `get_item_materialization_target` | Any catalog mutation | Media queries the canonical URL to download; never writes catalog. |
| **Pillar 6 (Ledger)** | None (Ledger is called by sources, not vice-versa) | All | Pillar 6 does not depend on Pillar 1. |

---

## 2. Published Functions (`sources.api`)

### 2.1 Source Management

#### `sources_api.register_source(workspace_id: UUID, url_or_handle: str, scan_depth: str = "RECENT_50", monitor_interval_sec: int = 900) -> SourceDTO`
- **Purpose**: Validates input string against SSRF firewall, resolves canonical YouTube ID, checks workspace uniqueness (`INV-9`), and persists the `sources` record.
- **Inputs**:
  - `workspace_id`: Tenant workspace scope.
  - `url_or_handle`: Raw operator input string (`https://youtube.com/@handle`, channel URL, playlist URL).
  - `scan_depth`: Enum string (`"RECENT_50"`, `"FULL"`, `"MONITOR_ONLY"`).
  - `monitor_interval_sec`: Polling cadence in seconds (minimum `300`).
- **Outputs**: Frozen `SourceDTO`.
- **Raises**: `InvalidSourceUrlError`, `SourceNotFoundError`, `DuplicateSourceError`.
- **Side Effects**: Writes 1 row to `sources` table; enqueues initial scan job if `scan_depth != "MONITOR_ONLY"`.

#### `sources_api.get_source(workspace_id: UUID, source_id: UUID) -> SourceDTO`
- **Purpose**: Retrieves a single source record by UUID.
- **Raises**: `SourceNotFoundError`.

#### `sources_api.list_sources(workspace_id: UUID, sync_status: str | None = None) -> tuple[SourceDTO, ...]`
- **Purpose**: Lists all active sources in workspace, optionally filtered by status.
- **Outputs**: Immutable tuple of `SourceDTO`s.

---

### 2.2 Discovery & Execution (Invoked by Worker / Job Engine)

#### `sources_api.execute_source_scan(source_id: UUID, scan_mode: str = "flat") -> ScanResultDTO`
- **Purpose**: Executes discovery scan using `extract_flat=True` (`INV-7`) or RSS XML parsing without downloading media bytes.
- **Inputs**: `source_id`, `scan_mode` (`"flat"` or `"rss"`).
- **Outputs**: `ScanResultDTO(items_discovered: int, items_upserted: int, items_skipped: int, errors: tuple[str, ...])`.
- **Guarantees**: Fully resilient to `F-48` (partial skips logged, scan completes).

#### `sources_api.execute_item_hydration(catalog_video_id: UUID) -> CatalogVideoDetailDTO`
- **Purpose**: Background deep extraction of rich tags, full description, chapters, and formats for a single video.
- **Side Effects**: Sets `is_hydrated = TRUE` and populates `catalog_video` fields.
- **Raises**: `ItemUnavailableError`, `RateLimitExceededError`.

---

### 2.3 Cross-Pillar Query APIs

#### `sources_api.get_catalog_items_for_pipeline(pipeline_id: UUID, limit: int = 100, cursor: datetime | None = None) -> tuple[SourceItem, ...]`
- **Purpose**: Called by **Pillar 3** to find candidate videos eligible for replication across all sources attached to the pipeline.
- **Outputs**: Immutable tuple of `SourceItem` DTOs (from Pillar 0 contracts).

#### `sources_api.get_item_materialization_target(catalog_video_id: UUID) -> tuple[str, str]`
- **Purpose**: Called by **Pillar 5** to retrieve canonical YouTube URL and video ID for download execution.
- **Outputs**: `(canonical_url, video_id)`.
- **Guarantees**: Zero media bytes touched (`INV-7`).

---

## 3. Data Transfer Objects (DTOs)

Conforming to `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/05_DATA_MODEL.md`, all DTOs are frozen dataclasses:

```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass(frozen=True)
class SourceDTO:
    id: UUID
    workspace_id: UUID
    source_type: str  # 'CHANNEL' | 'PLAYLIST'
    canonical_id: str
    title: str
    url: str
    thumbnail_url: str | None
    sync_status: str
    monitor_interval_sec: int
    scan_depth: str
    last_scanned_at: datetime | None
    last_error_message: str | None
    created_at: datetime

@dataclass(frozen=True)
class ScanResultDTO:
    source_id: UUID
    items_discovered: int
    items_upserted: int
    items_skipped: int
    errors: tuple[str, ...]
```

---

## 4. Change Log

- **2026-09-28:** Authored `03_INTERFACE_CONTRACT.md` detailing published functions, DTO definitions, sibling access matrix, and boundary enforcement rules.
