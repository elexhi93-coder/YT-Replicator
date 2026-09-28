# 05 — Data Model & Schema: Destinations & Auth

**Pillar:** 2 · Destinations & Auth · **Chapter:** Data Model & Schema · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §6  
**Depends on:** `docs/PILLARS/02_DESTINATIONS_AND_AUTH/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-4  

---

## 1. Schema Overview

Pillar 2 owns three relational tables in PostgreSQL 16:
1. `google_client`: Stores Google Cloud OAuth 2.0 application credentials.
2. `authorized_channel`: Stores authorized YouTube target channels and encrypted tokens.
3. `quota_usage`: Stores daily quota unit consumption per client keyed by Pacific calendar date.

---

## 2. PostgreSQL 16 DDL Specification

```sql
-- Schema DDL for Pillar 2 (Destinations & Auth)

CREATE TABLE IF NOT EXISTS google_client (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    project_name VARCHAR(120) NOT NULL,
    client_id VARCHAR(255) NOT NULL UNIQUE,
    client_secret_encrypted TEXT NOT NULL,         -- INV-1: AES-256-GCM ciphertext
    daily_quota_limit INTEGER NOT NULL DEFAULT 10000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_quota_limit_positive CHECK (daily_quota_limit > 0)
);

CREATE TABLE IF NOT EXISTS authorized_channel (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    client_id UUID NOT NULL REFERENCES google_client(id) ON DELETE RESTRICT,
    canonical_id VARCHAR(64) NOT NULL UNIQUE,     -- YouTube UC... channel ID
    title VARCHAR(255) NOT NULL,
    avatar_url TEXT,
    refresh_token_encrypted TEXT NOT NULL,        -- INV-1: AES-256-GCM ciphertext
    access_token_cached TEXT,                     -- Ephemeral cache
    token_expires_at TIMESTAMPTZ,
    token_health VARCHAR(24) NOT NULL DEFAULT 'VALID',
    default_privacy VARCHAR(16) NOT NULL DEFAULT 'unlisted',
    default_category_id VARCHAR(16) NOT NULL DEFAULT '22',
    made_for_kids BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_token_health CHECK (token_health IN ('VALID', 'EXPIRING', 'EXPIRED', 'REVOKED')),
    CONSTRAINT ck_default_privacy CHECK (default_privacy IN ('public', 'unlisted', 'private'))
);

CREATE TABLE IF NOT EXISTS quota_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL REFERENCES google_client(id) ON DELETE CASCADE,
    pacific_date DATE NOT NULL,                   -- INV-2: America/Los_Angeles calendar date
    consumed_units INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_client_pacific_date UNIQUE (client_id, pacific_date),
    CONSTRAINT ck_consumed_non_negative CHECK (consumed_units >= 0)
);

-- Performance & Isolation Indexes
CREATE INDEX IF NOT EXISTS idx_authorized_channel_client ON authorized_channel(client_id);
CREATE INDEX IF NOT EXISTS idx_authorized_channel_health ON authorized_channel(token_health);
CREATE INDEX IF NOT EXISTS idx_quota_usage_lookup ON quota_usage(client_id, pacific_date);
```

---

## 3. Cryptographic Storage Guarantees (`INV-1`)

- Columns `client_secret_encrypted` and `refresh_token_encrypted` store base64-encoded
  payloads formatted as: `iv:ciphertext:tag` produced by AES-256-GCM.
- Encryption and decryption operations are performed exclusively in memory inside the
  `src.destinations` service layer using the platform master secret.
- Plaintext credentials are NEVER exposed to logs, error traces, or cross-pillar DTOs.
