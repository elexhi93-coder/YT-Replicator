# 05 — Data Model & Schema: Platform Foundation & Ops

**Pillar:** 7 · Platform Foundation & Operations · **Chapter:** Data Model & Schema · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §6  
**Depends on:** `docs/PILLARS/07_PLATFORM_FOUNDATION_AND_OPS/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-10, INV-11  

---

## 1. Schema Overview

Pillar 7 owns the core platform tenancy, application configuration, and audit tables:
1. `workspace`: Scoping boundary for all domain entities.
2. `workspace_member`: Associating authenticated users with access roles.
3. `app_setting`: Key-value registry for system-wide flags (e.g. global scheduler pause).
4. `audit_event`: Append-only immutable log of security and administrative operations.

---

## 2. PostgreSQL 16 DDL Specification

```sql
-- Schema DDL for Pillar 7 (Platform Foundation & Ops)

CREATE TABLE IF NOT EXISTS workspace (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(120) NOT NULL UNIQUE,
    slug VARCHAR(64) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspace_member (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,                            -- Django auth_user.id
    role VARCHAR(32) NOT NULL DEFAULT 'OPERATOR',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_workspace_user UNIQUE (workspace_id, user_id),
    CONSTRAINT ck_member_role CHECK (role IN ('ADMIN', 'OPERATOR', 'VIEWER'))
);

CREATE TABLE IF NOT EXISTS app_setting (
    key VARCHAR(64) PRIMARY KEY,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    description TEXT,
    updated_by VARCHAR(64),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_name VARCHAR(64) NOT NULL,                     -- e.g. 'auth.login', 'settings.updated'
    actor_id VARCHAR(64) NOT NULL,
    workspace_id UUID REFERENCES workspace(id) ON DELETE SET NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address INET,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Crucial Performance Indexes
CREATE INDEX IF NOT EXISTS idx_audit_event_name ON audit_event(event_name, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_workspace ON audit_event(workspace_id, occurred_at DESC);
```
