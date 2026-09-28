# 05 — Data Model: Sources & Catalog

**Pillar:** 1 · Sources & Catalog · **Chapter:** Data Model · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/01_SOURCES_AND_CATALOG/00_PILLAR_OVERVIEW.md` · `docs/03_DATA_MODEL.md`  
**Invariants enforced:** INV-9, INV-11, INV-12  

---

## 1. Relational Topology & Lifecycle

Pillar 1 owns exactly two persistent relational tables in PostgreSQL 16:
1. **`sources`**: Tracks registered external content channels and playlists.
2. **`catalog_video`**: Stores discovered media items and their extracted metadata.

```
┌─────────────────────────────────┐
│             sources             │
│ (Primary key: id - UUID)        │
│ Tracks external channel/playlist│
└────────────────┬────────────────┘
                 │ 1
                 │
                 │ N
                 ▼
┌─────────────────────────────────┐
│          catalog_video          │
│ (Primary key: id - UUID)        │
│ Discovered videos from a source │
└─────────────────────────────────┘
```

### Table Lifecycles:
- **`sources`**: Created via operator action (`Add Source`). Soft-deleted (`deleted_at IS NOT NULL`) when removed to preserve historical pipeline associations and ledger lineage.
- **`catalog_video`**: Created during discovery scans (Tier 1 RSS or Tier 2 Flat Scan). Upserted when mutable metrics (views, titles) change. Hard-deletes are strictly forbidden; if a video is removed on YouTube, `availability` is updated to `'deleted'`.

---

## 2. Table Specifications

### 2.1 Table: `sources`

Tracks YouTube channels or playlists configured for ingestion.

```sql
CREATE TABLE sources (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id            UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source_type             VARCHAR(20) NOT NULL, -- 'CHANNEL' or 'PLAYLIST'
    canonical_id            VARCHAR(64) NOT NULL, -- YouTube channel ID (UC...) or playlist ID (PL...)
    title                   TEXT NOT NULL,
    url                     TEXT NOT NULL,
    thumbnail_url           TEXT,
    sync_status             VARCHAR(20) NOT NULL DEFAULT 'IDLE',
    monitor_interval_sec    INTEGER NOT NULL DEFAULT 900, -- 15 mins default
    scan_depth              VARCHAR(20) NOT NULL DEFAULT 'RECENT_50', -- 'RECENT_50', 'FULL', 'MONITOR_ONLY'
    last_scanned_at         TIMESTAMPTZ,
    last_error_message      TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

---

### 2.2 Table: `catalog_video`

Stores discovered video metadata harvested from sources across all 4 tiers.

```sql
CREATE TABLE catalog_video (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id               UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    workspace_id            UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    video_id                VARCHAR(11) NOT NULL, -- YouTube 11-char alphanumeric ID
    title                   TEXT NOT NULL,
    published_at            TIMESTAMPTZ NOT NULL,
    duration_seconds        INTEGER,
    thumbnail_url           TEXT,
    view_count              BIGINT,
    description             TEXT,
    tags                    JSONB NOT NULL DEFAULT '[]'::jsonb, -- Array of string tags
    live_status             VARCHAR(20) NOT NULL DEFAULT 'not_live',
    availability            VARCHAR(20) NOT NULL DEFAULT 'public',
    is_hydrated             BOOLEAN NOT NULL DEFAULT FALSE,
    hydrated_at             TIMESTAMPTZ,
    raw_metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT chk_video_id_format CHECK (video_id ~ '^[A-Za-z0-9_-]{11}$'),
    CONSTRAINT chk_live_status CHECK (live_status IN ('not_live', 'live', 'was_live')),
    CONSTRAINT chk_availability CHECK (availability IN ('public', 'unlisted', 'private', 'deleted', 'unknown')),
    CONSTRAINT uq_source_video UNIQUE (source_id, video_id)
);
```

#### Key Indexes on `catalog_video`:
- `CREATE INDEX idx_catalog_workspace_video ON catalog_video(workspace_id, video_id);`  
  *Serves multi-source deduplication queries and workspace lookups.*
- `CREATE INDEX idx_catalog_source_published ON catalog_video(source_id, published_at DESC);`  
  *Serves Catalog Explorer ordering and backfill cursor pagination.*
- `CREATE INDEX idx_catalog_hydration_queue ON catalog_video(is_hydrated, created_at) WHERE is_hydrated = FALSE;`  
  *Serves the background lazy hydration worker sweep.*
- `CREATE INDEX idx_catalog_gin_tags ON catalog_video USING GIN (tags);`  
  *Enables fast tag-based searches and topic filtering in the UI.*

    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ,

    -- Constraints
    CONSTRAINT chk_source_type CHECK (source_type IN ('CHANNEL', 'PLAYLIST')),
    CONSTRAINT chk_sync_status CHECK (sync_status IN ('IDLE', 'SCANNING', 'PARTIAL_WARNING', 'FAILED', 'PAUSED')),
    CONSTRAINT chk_scan_depth CHECK (scan_depth IN ('RECENT_50', 'FULL', 'MONITOR_ONLY')),
    CONSTRAINT uq_workspace_canonical_source UNIQUE (workspace_id, canonical_id)
);
```

#### Key Indexes on `sources`:
- `CREATE INDEX idx_sources_workspace_status ON sources(workspace_id, sync_status) WHERE deleted_at IS NULL;`  
  *Serves the Sources Management UI listing and filter queries.*
- `CREATE INDEX idx_sources_active_monitors ON sources(sync_status, last_scanned_at) WHERE deleted_at IS NULL AND sync_status != 'PAUSED';`  

---

## 3. Data Integrity & Boundary Rules

1. **Strict Ownership Boundary**:
   - Only code inside the `sources/` module may perform `INSERT`, `UPDATE`, or `DELETE` on `sources` and `catalog_video`.
   - Other modules (such as `pipelines/`) must query items through the published surface (`sources.api`), never via direct SQL joins to internal tables (`INV-11`).
2. **Immutability of Historical Sync**:
   - If a source is deleted by the operator, `deleted_at` is set. Hard deletes (`DELETE FROM sources`) are prohibited so that existing delivery records in Pillar 6 retain unbroken relational integrity.
3. **Upsert Idempotency**:
   - Discovery scans execute PostgreSQL `INSERT INTO catalog_video (...) ON CONFLICT (source_id, video_id) DO UPDATE SET title = EXCLUDED.title, view_count = EXCLUDED.view_count, updated_at = NOW()`.
   - The `is_hydrated` flag is **never** reset to `FALSE` by an upsert if it was already `TRUE`.

---

## 4. Change Log

- **2026-09-28:** Authored `05_DATA_MODEL.md` specifying relational schemas for `sources` and `catalog_video`, check constraints, GIN indexes, and boundary access rules.

  *Serves the background polling scheduler checking for cadence expiration.*
