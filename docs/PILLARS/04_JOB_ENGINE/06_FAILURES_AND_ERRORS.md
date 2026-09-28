# 06 — Failures, Errors, and Recovery: Job Engine

**Pillar:** 4 · Job Engine · **Chapter:** Failures and Errors · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §7  
**Depends on:** `docs/PILLARS/04_JOB_ENGINE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-6, INV-10  

---

## 1. Domain Error Classification

The Job Engine maps all handler exceptions into exactly three categories:

| Category | Typical Causes | Engine Reaction | State Result |
|---|---|---|---|
| **`TRANSIENT`** | Network timeout, 429 rate limit, 5xx server error, chunk upload dropped | Increment `attempt_count`, calculate exponential backoff + jitter, re-queue | `queued` (with future `scheduled_for`) |
| **`PERMANENT`** | YouTube Terms violation, invalid credentials, duplicate video, corrupt file | Dead-letter transition. Do not retry. Alert operator in UI | `failed_permanent` |
| **`SKIP`** | Video filtered by pipeline policy, video already in ledger, video deleted at source | Non-error terminal outcome. Record exact skip reason | `skipped` |

---

## 2. Worker Crash & Power Outage Recovery (`INV-6`)

- If a worker machine crashes or process exits unexpectedly:
  - PostgreSQL transaction automatically rolls back if uncommitted.
  - If lease was committed: the `worker_heartbeat` ceases.
  - Within 60 seconds, the Janitor Reaper claims the row (`heartbeat_at < NOW() - 60s`), increments `attempt_count`, and returns the job to `queued`.
  - Fixes Defect `D-07`: Tasks are never permanently lost mid-flight due to machine restarts.
