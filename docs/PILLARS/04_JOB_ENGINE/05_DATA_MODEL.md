# 05 — Data Model & Schema: Job Engine

**Pillar:** 4 · Job Engine · **Chapter:** Data Model & Schema · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §6  
**Depends on:** `docs/PILLARS/04_JOB_ENGINE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-10, INV-11  

---

## 1. Schema Overview

Pillar 4 owns two relational tables in PostgreSQL 16:
1. `job`: The durable task queue storing state, payload, scheduling, and error history.
2. `worker_heartbeat`: Worker process registration and liveness telemetry.

---

## 2. PostgreSQL 16 DDL Specification

```sql
-- Schema DDL for Pillar 4 (Job Engine)

CREATE TABLE IF NOT EXISTS job (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    task_type VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'queued',
    idempotency_key VARCHAR(255) UNIQUE,         -- INV-5: Deduplication key
    entity_lock_key VARCHAR(128),                -- ADJ-P1-01: Concurrency serialization
    priority INTEGER NOT NULL DEFAULT 100,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    claimed_by_worker VARCHAR(64),
    claimed_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    scheduled_for TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error_code VARCHAR(64),
    last_error_detail TEXT,
    skip_reason VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_job_state CHECK (state IN (
        'queued', 'claimed', 'downloading', 'downloaded',
        'uploading', 'uploaded', 'completed', 'failed_permanent',
        'skipped', 'cancelled'
    )),
    CONSTRAINT ck_attempt_count CHECK (attempt_count >= 0)
);

CREATE TABLE IF NOT EXISTS worker_heartbeat (
    worker_id VARCHAR(64) PRIMARY KEY,
    hostname VARCHAR(128) NOT NULL,
    pid INTEGER NOT NULL,
    supported_task_types TEXT[] NOT NULL,
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Crucial Performance & SKIP LOCKED Indexes
CREATE INDEX IF NOT EXISTS idx_job_claim_queue 
    ON job(scheduled_for, priority DESC, created_at ASC) 
    WHERE state = 'queued';

CREATE INDEX IF NOT EXISTS idx_job_active_locks 
    ON job(entity_lock_key) 
    WHERE state IN ('claimed', 'downloading', 'downloaded', 'uploading', 'uploaded') 
      AND entity_lock_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_job_heartbeat_reaper 
    ON job(heartbeat_at) 
    WHERE state IN ('claimed', 'downloading', 'downloaded', 'uploading', 'uploaded');
```
