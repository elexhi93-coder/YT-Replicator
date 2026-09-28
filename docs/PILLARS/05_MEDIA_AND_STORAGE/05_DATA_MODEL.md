# 05 — Data Model & Schema: Media & Storage

**Pillar:** 5 · Media & Storage · **Chapter:** Data Model & Schema · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §6  
**Depends on:** `docs/PILLARS/05_MEDIA_AND_STORAGE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-2, INV-3, INV-6, INV-7, INV-10  

---

## 1. Schema Overview

Pillar 5 owns three relational tables in PostgreSQL 16:
1. `storage_root`: Registered filesystem volumes and space thresholds.
2. `media_asset`: Physical files on disk, verification hashes, and lifecycles.
3. `media_event`: Append-only audit ledger of every file operation.

---

## 2. PostgreSQL 16 DDL Specification

```sql
-- Schema DDL for Pillar 5 (Media & Storage)

CREATE TABLE IF NOT EXISTS storage_root (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    root_name VARCHAR(64) NOT NULL,
    base_path VARCHAR(512) NOT NULL UNIQUE,
    min_free_floor_bytes BIGINT NOT NULL DEFAULT 10737418240, -- 10 GB floor
    is_mounted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS media_asset (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    storage_root_id UUID NOT NULL REFERENCES storage_root(id) ON DELETE RESTRICT,
    catalog_video_id UUID NOT NULL UNIQUE,       -- Refers to Pillar 1 catalog_video(id)
    relative_path VARCHAR(512) NOT NULL,         -- INV-7: relative path within storage root
    container VARCHAR(8) NOT NULL DEFAULT 'mp4',
    byte_size BIGINT NOT NULL DEFAULT 0,
    sha256 VARCHAR(64),                          -- INV-3: verified SHA-256 hex digest
    state VARCHAR(32) NOT NULL DEFAULT 'EXPECTED',
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_asset_state CHECK (state IN (
        'EXPECTED', 'DOWNLOADING', 'ON_DISK', 'DELETED', 'ARCHIVE_OFFLINE'
    )),
    CONSTRAINT ck_asset_size_valid CHECK (
        (state = 'ON_DISK' AND byte_size > 0 AND sha256 IS NOT NULL) OR
        (state != 'ON_DISK')
    )
);

CREATE TABLE IF NOT EXISTS media_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES media_asset(id) ON DELETE CASCADE,
    event_type VARCHAR(48) NOT NULL,             -- 'DOWNLOAD_STARTED', 'VERIFIED', 'PRUNED', 'REHYDRATED'
    operator_id VARCHAR(64),
    bytes_affected BIGINT NOT NULL DEFAULT 0,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Crucial Query Indexes
CREATE INDEX IF NOT EXISTS idx_media_asset_lookup ON media_asset(catalog_video_id);
CREATE INDEX IF NOT EXISTS idx_media_asset_retention 
    ON media_asset(state, is_pinned) 
    WHERE state = 'ON_DISK' AND is_pinned = FALSE;
CREATE INDEX IF NOT EXISTS idx_media_event_asset ON media_event(asset_id, created_at DESC);
```
