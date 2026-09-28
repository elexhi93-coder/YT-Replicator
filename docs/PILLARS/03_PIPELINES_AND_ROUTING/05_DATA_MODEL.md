# 05 — Data Model & Schema: Pipelines & Routing

**Pillar:** 3 · Pipelines & Routing · **Chapter:** Data Model & Schema · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §6  
**Depends on:** `docs/PILLARS/03_PIPELINES_AND_ROUTING/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-6, INV-9, INV-11  

---

## 1. Schema Overview

Pillar 3 owns four relational tables in PostgreSQL 16:
1. `download_profile`: Reusable media quality constraints and content exclusion filters.
2. `pipeline`: Pipeline definitions, execution status, and media retention policy.
3. `pipeline_source`: Association table linking sources to pipelines with independent backfill cursors.
4. `pipeline_destination`: Association table linking destination channels to pipelines with privacy overrides.

---

## 2. PostgreSQL 16 DDL Specification

```sql
-- Schema DDL for Pillar 3 (Pipelines & Routing)

CREATE TABLE IF NOT EXISTS download_profile (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    profile_name VARCHAR(120) NOT NULL,
    max_resolution VARCHAR(16) NOT NULL DEFAULT '1080p',
    preferred_container VARCHAR(8) NOT NULL DEFAULT 'mp4',
    skip_shorts BOOLEAN NOT NULL DEFAULT TRUE,
    skip_live_streams BOOLEAN NOT NULL DEFAULT TRUE,
    min_duration_seconds INTEGER NOT NULL DEFAULT 0,
    max_duration_seconds INTEGER NOT NULL DEFAULT 14400,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_resolution CHECK (max_resolution IN ('720p', '1080p', '1440p', '2160p')),
    CONSTRAINT ck_duration_range CHECK (max_duration_seconds >= min_duration_seconds)
);

CREATE TABLE IF NOT EXISTS pipeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    pipeline_name VARCHAR(120) NOT NULL,
    download_profile_id UUID NOT NULL REFERENCES download_profile(id) ON DELETE RESTRICT,
    status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
    retention_policy VARCHAR(32) NOT NULL DEFAULT 'KEEP',  -- INV-6: 'KEEP' | 'DELETE_AFTER_UPLOAD'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_pipeline_status CHECK (status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'ARCHIVED')),
    CONSTRAINT ck_retention CHECK (retention_policy IN ('KEEP', 'DELETE_AFTER_UPLOAD'))
);

CREATE TABLE IF NOT EXISTS pipeline_source (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL REFERENCES pipeline(id) ON DELETE CASCADE,
    source_id UUID NOT NULL,                             -- Refers to Pillar 1 sources(id)
    sync_mode VARCHAR(24) NOT NULL DEFAULT 'BACKFILL',
    backfill_cursor_published_at TIMESTAMPTZ,            -- INV-9: Per-pipeline cursor
    daily_cap INTEGER,                                   -- Optional daily video limit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_pipeline_source UNIQUE (pipeline_id, source_id),
    CONSTRAINT ck_sync_mode CHECK (sync_mode IN ('BACKFILL', 'MONITOR', 'BOTH'))
);

CREATE TABLE IF NOT EXISTS pipeline_destination (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID NOT NULL REFERENCES pipeline(id) ON DELETE CASCADE,
    destination_channel_id UUID NOT NULL,                -- Refers to Pillar 2 authorized_channel(id)
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    privacy_override VARCHAR(16),                        -- NULL (inherit) | 'public' | 'unlisted' | 'private'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_pipeline_dest UNIQUE (pipeline_id, destination_channel_id),
    CONSTRAINT ck_privacy_override CHECK (privacy_override IS NULL OR privacy_override IN ('public', 'unlisted', 'private'))
);

-- Query Indexes for Fast Candidate Processing
CREATE INDEX IF NOT EXISTS idx_pipeline_status ON pipeline(status);
CREATE INDEX IF NOT EXISTS idx_pipe_source_cursor ON pipeline_source(pipeline_id, backfill_cursor_published_at);
CREATE INDEX IF NOT EXISTS idx_pipe_dest_enabled ON pipeline_destination(pipeline_id, is_enabled);
```
