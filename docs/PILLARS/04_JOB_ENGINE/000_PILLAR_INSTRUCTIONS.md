# 000 — Pillar 4 Instructions & Working Frontier (Job Engine)

**Pillar:** 4 — Job Engine  
**Status:** `drafting`  
**Authority:** Local domain directive for Pillar 4. Governed by `docs/000_*` and `docs/PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md`.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
Hand out background work safely, exactly once, in a way that survives crashes, restarts, and concurrent multi-worker environments using PostgreSQL `FOR UPDATE SKIP LOCKED` — while knowing absolutely nothing about YouTube, media files, or business rules.

### What This Pillar Owns
- The `job` entity and queue operations: `enqueue`, atomic `claim`, `heartbeat`, `complete`, `fail`, `cancel`, `retry`.
- The multi-stage pipeline state machine: `queued → claimed → downloading → downloaded → uploading → uploaded`, plus terminal states (`completed`, `failed_permanent`, `skipped`, `cancelled`).
- Atomic row claiming via PostgreSQL 16 `FOR UPDATE SKIP LOCKED`.
- Worker heartbeats (`worker_heartbeat`), dead worker detection, and zombie job lease reclamation.
- Granular error classification into the 3 canonical buckets: **Transient** (exponential backoff with jitter), **Permanent** (dead-letter queue), and **Skip** (explained non-execution).
- Per-entity concurrency locking (`ADJ-P1-01`: lock key mechanism ensuring e.g. at most 1 scrape per source simultaneously).
- Pause and resume as scheduler state without mutating pending job records.

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- ❌ **NEVER knows YouTube API, schemas, or tokens**: YouTube is an implementation detail of Pillars 1 & 2.
- ❌ **NEVER downloads, inspects, or deletes media files**: Pillar 5 (`05_MEDIA_AND_STORAGE`) owns all file I/O.
- ❌ **NEVER writes to the delivery ledger**: Pillar 6 (`06_DELIVERY_AND_LEDGER`) owns the ledger.
- ❌ **NEVER decides which videos replicate to which destinations**: Pillar 3 (`03_PIPELINES_AND_ROUTING`) creates the work candidates.

---

## 2. Invariants & Non-Negotiable Guards

| Invariant | Rule | Enforcement Mechanism |
|---|---|---|
| **INV-5** | **Zero re-enqueue of delivered items** | In addition to Pillar 3 filtering, `job` deduplication keys (`idempotency_key`) prevent duplicate in-flight jobs. |
| **INV-6** | **Deterministic recovery** | Stale jobs whose worker heartbeat lapsed (> 60s) are cleanly reclaimed by lease reaper without data corruption. |
| **INV-10** | **Crash-safe atomic claiming** | Only `FOR UPDATE SKIP LOCKED` is permitted for claiming. SQLite or in-memory queues are strictly prohibited in production. |
| **INV-11** | **Port & Adapter encapsulation** | External consumers interact with the queue exclusively through `<jobs>.api` using frozen DTOs (`INV-12`). |

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `00` | `00_PILLAR_OVERVIEW.md` | `locked` | Mission, boundaries, State Machine & Job Universe |
| `01` | `01_FRONTEND_SPEC.md` | `locked` | Live queue console, error inspector drawer, pause bar |
| `02` | `02_WORKSPACE_AND_TENANCY_SLOT.md` | `scaffolded` | Multi-tenancy scoping |
| `03` | `03_INTERFACE_CONTRACT.md` | `locked` | Published `<jobs>.api`, ClaimedJobDTO, EnqueueJobRequest |
| `04` | `04_LOGIC_AND_RULES.md` | `locked` | SKIP LOCKED claim query, entity lock keys (ADJ-P1-01), backoff + jitter, reaper |
| `05` | `05_DATA_MODEL.md` | `locked` | PostgreSQL schema (`job`, `worker_heartbeat`) |
| `06` | `06_FAILURES_AND_ERRORS.md` | `locked` | 3-bucket error classification, crash recovery |
| `07` | `07_OBSERVABILITY_AND_AUDIT.md` | `locked` | Prometheus queue metrics, domain events, worker telemetry |
| `08` | `08_TESTS_AND_DOD.md` | `locked` | Concurrency claim stress tests, entity lock tests, AST isolation |
| `09` | `09_LEGACY_TRACEABILITY.md` | `scaffolded` | Anchors: F-09, F-18, F-19, F-21, F-22, F-23, F-29, F-42; defect D-07 |
| `10` | `10_OPEN_QUESTIONS.md` | `scaffolded` | Local design questions |
| `11` | `11_DECISIONS.md` | `scaffolded` | Local architectural decisions (P4-D##) |

**Current Active Frontier:** Authoring chapters `00` through `08`.
