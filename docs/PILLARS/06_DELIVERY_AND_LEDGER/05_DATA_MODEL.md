# 05 — Data Model & Schema: Delivery & Ledger

**Pillar:** 6 · Delivery & Ledger · **Chapter:** Data Model & Schema · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §6  
**Depends on:** `docs/PILLARS/06_DELIVERY_AND_LEDGER/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-4, INV-8  

---

## 1. Schema Overview

Pillar 6 owns three relational tables in PostgreSQL 16:
1. `delivery`: Current state of video replication pairs.
2. `delivery_attempt`: Append-only history of every upload attempt.
3. `destination_inventory`: Cached remote videos discovered during reconciliation.

---

## 2. PostgreSQL 16 DDL Specification

```sql
-- Schema DDL for Pillar 6 (Delivery & Ledger)

CREATE TABLE IF NOT EXISTS delivery (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    catalog_video_id UUID NOT NULL REFERENCES catalog_video(id) ON DELETE RESTRICT,       -- INV-4
    destination_channel_id UUID NOT NULL REFERENCES authorized_channel(id) ON DELETE RESTRICT, -- INV-4
    pipeline_id UUID REFERENCES pipeline(id) ON DELETE SET NULL,                        -- INV-4
    destination_video_id VARCHAR(32),                                                   -- Remote YouTube ID
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    reconciliation_state VARCHAR(32) NOT NULL DEFAULT 'UNRECONCILED',
    marker_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_delivery_status CHECK (status IN (
        'PENDING', 'IN_FLIGHT', 'DELIVERED_SUCCESS', 'FAILED_PERMANENT', 'REMOVED'
    )),
    CONSTRAINT ck_recon_state CHECK (reconciliation_state IN (
        'UNRECONCILED', 'CLAIMED_OK', 'UNCLAIMED_PRESENT', 'MISSING_EXPECTED', 'MARKER_MISMATCH'
    ))
);

-- INV-1: Exactly one successful delivery per video x destination pair
CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_successful_pair 
    ON delivery(catalog_video_id, destination_channel_id) 
    WHERE status = 'DELIVERED_SUCCESS';

CREATE TABLE IF NOT EXISTS delivery_attempt (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_id UUID NOT NULL REFERENCES delivery(id) ON DELETE RESTRICT,               -- INV-4
    attempt_number INTEGER NOT NULL DEFAULT 1,
    status_code INTEGER,
    duration_ms INTEGER,
    error_code VARCHAR(64),
    error_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS destination_inventory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    destination_channel_id UUID NOT NULL REFERENCES authorized_channel(id) ON DELETE CASCADE,
    remote_video_id VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    parsed_source_id UUID,
    parsed_video_id VARCHAR(64),
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_dest_remote_video UNIQUE (destination_channel_id, remote_video_id)
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_delivery_lookup ON delivery(catalog_video_id, destination_channel_id);
CREATE INDEX IF NOT EXISTS idx_delivery_status ON delivery(status);
CREATE INDEX IF NOT EXISTS idx_attempt_delivery ON delivery_attempt(delivery_id, created_at DESC);
```
