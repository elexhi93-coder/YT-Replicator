# 00 — Pillar Overview & The Job Engine State Machine Universe

**Pillar:** 4 · Job Engine · **Chapter:** Pillar Overview · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/04` §2 · `docs/05` §9  
**Invariants touched:** INV-5, INV-6, INV-10, INV-11, INV-12  

---

## 1. Mission

Pillar 4 provides the reliable, atomic, crash-resilient queue infrastructure for all
background work across YT-Replicator. It hands out work safely, exactly once, in a way
that survives crashes, process restarts, and multi-worker contention — while knowing
**absolutely nothing about YouTube or files**.

By enforcing strict PostgreSQL 16 row locking (`FOR UPDATE SKIP LOCKED`, `INV-10`),
entity concurrency serialization (`ADJ-P1-01`), and automatic zombie lease reclamation,
it ensures that work never drops, double-runs, or hangs indefinitely.

---

## 2. Owns vs. Does Not Own

### 2.1 What This Pillar Owns
- **The `job` entity**: Central persistent record of background tasks, tracking phase,
  worker ownership, attempts, backoff schedules, and idempotency deduplication keys (`INV-5`).
- **Atomic Claim Protocol**: PostgreSQL `FOR UPDATE SKIP LOCKED` query selecting eligible
  jobs without contention or deadlocks (`INV-10`).
- **The Pipeline Task State Machine**:
  `queued → claimed → downloading → downloaded → uploading → uploaded → completed`,
  plus failure states (`retry_scheduled`, `failed_permanent`, `skipped`, `cancelled`).
- **Error Classification Engine**: Dividing all task failures into **Transient**,
  **Permanent**, and **Skip** buckets with exponential backoff and jitter.
- **Worker Heartbeat & Lease Reaper**: `worker_heartbeat` tracking and zombie recovery:
  if a worker fails to send a heartbeat for > 60 seconds, its claimed jobs are cleanly
  reset to `queued` with attempt increment.
- **Entity Concurrency Locking (`ADJ-P1-01`)**: Locking mechanism guaranteeing at most
  1 active job per `entity_lock_key` (e.g., `source:{id}` for scans).

### 2.2 What This Pillar Does NOT Own

| Responsibility | Owning Pillar | Reason for Boundary |
|---|---|---|
| Downloading or hashing media files | **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Job Engine tracks phases; Pillar 5 runs yt-dlp/ffmpeg. |
| YouTube API calls or token refreshes | **Pillar 2** (`02_DESTINATIONS_AND_AUTH`) | Pillar 2 implements the upload adapter. |
| Deciding which videos replicate | **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Pillar 3 defines candidate policies and enqueues jobs. |
| Recording delivery receipts | **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Pillar 6 is the sole authority on the delivery ledger. |

---

## 3. The Job Task Universe (Leaf-Level Registry)

All attributes defining background job state, execution, and locking:

| Field Name | Entity / Context | Data Type | Default / Constraints | Notes |
|---|---|---|---|---|
| `job_id` | `job` | `UUID` | Primary Key | Canonical job identifier. |
| `task_type` | `job` | `str(64)` | Required | e.g. `replicate_video`, `sources.scan`, `sources.hydrate`. |
| `state` | `job` | `enum` | `'queued'` | State machine phase (see §4). |
| `idempotency_key` | `job` | `str(255)` | UNIQUE | Nullable for unconstrained tasks; prevents duplicate jobs (`INV-5`). |
| `entity_lock_key` | `job` | `str(128)` | Nullable | e.g. `source:{uuid}`; limits concurrent work per entity (`ADJ-P1-01`). |
| `priority` | `job` | `int` | `100` | Higher number claimed first (`ORDER BY priority DESC, created_at ASC`). |
| `payload` | `job` | `JSONB` | Required | Task parameters (source ID, video ID, pipeline config). |
| `claimed_by_worker` | `job` | `str(64)` | Nullable | Worker instance ID currently holding lease. |
| `claimed_at` | `job` | `TIMESTAMPTZ`| Nullable | Timestamp of last claim. |
| `heartbeat_at` | `job` | `TIMESTAMPTZ`| Nullable | Timestamp of worker's last active tick. |
| `attempt_count` | `job` | `int` | `0` | Incremented only on transient retry attempts. |
| `max_attempts` | `job` | `int` | `5` | Maximum transient retry attempts before permanent failure. |
| `scheduled_for` | `job` | `TIMESTAMPTZ`| `NOW()` | Next execution time; used for backoff delays. |
| `last_error_code` | `job` | `str(64)` | Nullable | Canonical error identifier. |
| `last_error_detail` | `job` | `TEXT` | Nullable | Redacted error traceback or message. |
| `skip_reason` | `job` | `str(64)` | Nullable | Populated if state transitions to `skipped`. |

---

## 4. The Canonical Job State Machine

```
               [ ENQUEUE ]
                    │
                    ▼
               ┌──────────┐
      ┌───────▶│  QUEUED  │◀────────────────┐
      │        └──────────┘                 │
      │             │                       │
      │        atomic claim                 │ (zombie lease reaper
      │             │                       │  or transient backoff)
      │             ▼                       │
      │        ┌──────────┐                 │
      │        │ CLAIMED  │─────────────────┤
      │        └──────────┘                 │
      │             │                       │
      │     replicate task                  │
      │             │                       │
      │             ▼                       │
      │        ┌──────────────┐             │
      │        │ DOWNLOADING  │─────────────┤
      │        └──────────────┘             │
      │             │                       │
      │             ▼                       │
      │        ┌──────────────┐             │
      │        │ DOWNLOADED   │─────────────┤
      │        └──────────────┘             │
      │             │                       │
      │             ▼                       │
      │        ┌──────────────┐             │
      │        │  UPLOADING   │─────────────┘
      │        └──────────────┘
      │             │
      │             ▼
      │        ┌──────────────┐
      │        │   UPLOADED   │
      │        └──────────────┘
      │             │
      │             ▼
      │        ┌──────────────┐
      │        │  COMPLETED   │ (terminal)
      │        └──────────────┘
      │
      ├───────────────────────┬───────────────────────┐
      ▼                       ▼                       ▼
┌──────────────┐        ┌──────────────┐        ┌──────────────┐
│   SKIPPED    │        │FAILED_PERMAN │        │  CANCELLED   │
│  (terminal)  │        │  (terminal)  │        │  (terminal)  │
└──────────────┘        └──────────────┘        └──────────────┘
```

| Worker process supervisor / loop | `src.worker` runner | Runner is a lightweight harness calling `<jobs>.api`. |
