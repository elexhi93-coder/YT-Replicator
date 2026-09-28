# Pillar 4 — Job Engine

**Status:** `scaffolded`.
**Chapters:** twelve files, per `_STANDARD/CHAPTER_STANDARD.md`.
**Depends on:** Pillar 0 (contracts).

---

## 1. Mission

Hand out work safely, once, in a way that survives a crash, a restart and a
second worker — while knowing nothing about YouTube or about files.

## 2. Owns

- The `job` entity and the queue: enqueue, atomic claim, hand out, complete,
  fail, cancel, retry.
- The **state machine** (`queued → claimed → downloading → downloaded →
  uploading → uploaded`, plus the failure and retry paths).
- Atomic claiming with `FOR UPDATE SKIP LOCKED` — the reason the engine is
  PostgreSQL and not SQLite (D8).
- Error **classification** in exactly three buckets: transient, permanent, skip.
- Retry policy: attempt counting, backoff with jitter, maximum attempts, and
  `attempt_count` incrementing only for transient retries.
- The **skip-reason contract** — a caller can be told *why nothing was done*.
- Pause and resume as **scheduler state**: a pause never mutates a job row.
- Restart recovery for rows left mid-flight.
- `worker_heartbeat` and staleness reporting, so a dead worker is visible.

## 3. Does not own

| Not owned here | Owner |
|---|---|
| What a job means, or which videos qualify | Pillar 3 (`03_PIPELINES_AND_ROUTING`) |
| Downloading, hashing, deleting files | Pillar 5 (`05_MEDIA_AND_STORAGE`) |
| Uploading, or the ledger | Pillar 6 (`06_DELIVERY_AND_LEDGER`) |
| Quota arithmetic | Pillar 2 (`02_DESTINATIONS_AND_AUTH`) — the engine asks, does not compute |
| Orchestration order (claim → dispatch) | the `worker` module, which holds no rules of its own |

## 4. Dependencies

Reads from: Pillar 0. Called by: Pillars 3, 5 and 6 (enqueue and complete) and by
the `worker` module (claim and dispatch). **`jobs` knows nothing about YouTube or
files** — this inversion is what makes the whole system changeable.

## 5. Invariants this pillar protects

`INV-5` (nothing enqueued for a delivered pair, enforced here as well as in
Pillar 3), the determinism half of `INV-6`, and the restart-recovery guarantees
of `docs/05` §9. It is the mechanism that fixes defect `D-07` (a failed download
being marked as seen, so it is never retried).

## 6. Chapter plan

| Chapter | Status |
|---|---|
| `00_PILLAR_OVERVIEW.md` | **locked** — mission, boundaries, state machine & job universe |
| `01_FRONTEND_SPEC.md` | **locked** — live queue console, error inspector drawer, pause bar |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | scaffolded |
| `03_INTERFACE_CONTRACT.md` | **locked** — published `<jobs>.api`, ClaimedJobDTO, EnqueueJobRequest |
| `04_LOGIC_AND_RULES.md` | **locked** — SKIP LOCKED claim query, entity lock keys (ADJ-P1-01), backoff + jitter, reaper |
| `05_DATA_MODEL.md` | **locked** — PostgreSQL schema (`job`, `worker_heartbeat`) |
| `06_FAILURES_AND_ERRORS.md` | **locked** — 3-bucket error classification, crash recovery |
| `07_OBSERVABILITY_AND_AUDIT.md` | **locked** — Prometheus queue metrics, domain events, worker telemetry |
| `08_TESTS_AND_DOD.md` | **locked** — concurrency claim stress tests, entity lock tests, AST isolation |
| `09_LEGACY_TRACEABILITY.md` | scaffolded — anchors: `F-09`, `F-18`, `F-19`, `F-21`, `F-22`, `F-23`, `F-29`, `F-42`; defect `D-07` |
| `10_OPEN_QUESTIONS.md` | scaffolded |
| `11_DECISIONS.md` | scaffolded |

## 7. Next action

Not yet — wait for Pillar 0 to be locked.

> **Build order note:** `docs/07` §6 places the worker's claim and error logic
> before everything downstream, because every other pillar trusts it. When we
> reach implementation, this is the pillar that gets tests first.
