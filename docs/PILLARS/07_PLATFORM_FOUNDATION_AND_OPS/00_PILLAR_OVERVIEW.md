# 00 — Pillar Overview & The Platform Operations Universe

**Pillar:** 7 · Platform Foundation & Operations · **Chapter:** Pillar Overview · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/04` §2-§9  
**Invariants touched:** INV-1, INV-2, INV-7, INV-10, INV-11, INV-12  

---

## 1. Mission

Pillar 7 owns the foundational bedrock upon which all domain pillars operate. It provides
the shared cryptographic primitives (`core.crypto`), the authoritative Pacific Time quota clock
(`core.clock`), the authenticated workspace tenancy model (`accounts`), the generic worker
dispatch loop (`worker`), the centralized audit ledger and log viewer (`ops`), and the universal
UI application shell (`ui`).

It ensures that the system is structurally defended against architectural rot through
automated AST import boundary enforcement (`INV-11`), strict 600-line per-file limits,
and centralized security validation (SSRF, path traversal, authenticated encryption).

---

## 2. The Five Platform Modules & Boundaries

Pillar 7 brings formal ownership to the five foundational modules defined in `docs/04` §2:

| Module | Core Responsibility | Boundaries & Strict Defense |
|---|---|---|
| `core` | AES-256-GCM cipher (`ADJ-P2-01`), Pacific Time clock (`INV-2`), SSRF IP firewall (`INV-7`), base errors, and structured JSON logger. | **Imports NOTHING** from other modules (`docs/04` §3). |
| `accounts` | Django auth integration, `workspace`, `workspace_member`, session management, CSRF enforcement, and the single access helper (`current_workspace()`). | Owns user sessions; no multi-tenant routing logic in v1 (D11). |
| `worker` | The execution runner (`run_once()` / `run_forever()`), dispatching claimed tasks by intent, evaluating admission gates, and executing restart recovery. | **Orchestration only — no business rules**. Never mutates queue state directly. |
| `ops` | Centralized `audit_event` persistent ledger, worker heartbeat tracking, `/healthz` liveness probes, log file streaming (never Docker socket, `D-05`), and maintenance commands. | Provides observability to domain pillars; never modifies domain data. |
| `ui` | Universal HTML shell (`base.html`), data-driven navigation bar, workspace context slot, flash/toast messages, and the 4 platform pages: `/`, `/login`, `/settings`, `/ops/logs`. | Shell and platform pages only; domain pages belong to Pillars 1–6. |

---

## 3. What This Pillar Does NOT Own

| Responsibility | Owning Pillar | Reason for Boundary |
|---|---|---|
| YouTube API calls & OAuth tokens | **Pillar 2** (`02_DESTINATIONS_AND_AUTH`) | YouTube is an external adapter concern. |
| Downloading and hashing media files | **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Physical file I/O is owned exclusively by Pillar 5. |
| Deciding which videos replicate | **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Replication routing belongs to pipelines. |
| Database queue locking & claim queries | **Pillar 4** (`04_JOB_ENGINE`) | PostgreSQL `SKIP LOCKED` queries live in `jobs`. |
| Delivery receipts & reconciliation | **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Ledger truth is owned by Delivery. |

---

## 4. The Platform Universe (Leaf-Level Registry)

All attributes governing platform configuration, credentials, workspace tenancy, and audit:

| Attribute Name | Entity / Context | Data Type | Default / Constraints | Notes |
|---|---|---|---|---|
| `workspace_id` | `workspace` | `UUID` | Primary Key | Canonical workspace UUID. |
| `workspace_name` | `workspace` | `str(120)` | Unique | Display name of the operating workspace. |
| `user_id` | `auth_user` | `int` | Django standard | Authenticated operator account. |
| `role` | `workspace_member` | `enum` | `'ADMIN'`, `'OPERATOR'`, `'VIEWER'` | Role-based authorization guard. |
| `event_id` | `audit_event` | `UUID` | Primary Key | Canonical audit log entry UUID. |
| `event_name` | `audit_event` | `str(64)` | Required | e.g. `auth.login`, `settings.updated`, `ops.purge`. |
| `actor_id` | `audit_event` | `str(64)` | User / Worker | Entity initiating the event. |
| `payload` | `audit_event` | `JSONB` | Default `{}` | Sanitized event parameters (secrets redacted). |
| `master_key` | Environment | `str(64)` | Required in ENV | 256-bit AES platform master key (`INV-1`). |
| `pacific_tz` | `core.clock` | `ZoneInfo` | `America/Los_Angeles` | Authoritative timezone for daily quotas (`INV-2`). |
| `ssrf_allowlist` | `core.security` | `tuple[str]` | `youtube.com`, `googleapis.com` | Allowed outbound domains (`INV-7`). |
