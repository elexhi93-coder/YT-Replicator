# 04 — Logic and Business Rules: Job Engine

**Pillar:** 4 · Job Engine · **Chapter:** Logic and Business Rules · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §5  
**Depends on:** `docs/PILLARS/04_JOB_ENGINE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-6, INV-10, INV-11  

---

## 1. Atomic Claim Algorithm (`FOR UPDATE SKIP LOCKED`, `INV-10`)

### 1.1 Concurrency & Entity Locking Logic (`ADJ-P1-01`)
When a worker invokes `claim_next_job(worker_id, supported_types)`:
1. Candidate jobs must satisfy:
   - `state = 'queued'`
   - `scheduled_for <= NOW()`
   - `task_type IN (:supported_types)`
   - `(entity_lock_key IS NULL OR entity_lock_key NOT IN (SELECT entity_lock_key FROM job WHERE state IN ('claimed', 'downloading', 'downloaded', 'uploading', 'uploaded') AND entity_lock_key IS NOT NULL))`
2. Query orders by `priority DESC, scheduled_for ASC, created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED`.
3. If row found:
   - Update `state = 'claimed'`
   - Set `claimed_by_worker = :worker_id`, `claimed_at = NOW()`, `heartbeat_at = NOW()`.
   - Commit transaction and return `ClaimedJobDTO`.
4. If no row found, return `None`.

```sql
-- Atomic Claim Query with Entity Lock Protection (INV-10, ADJ-P1-01)
WITH active_locks AS (
    SELECT entity_lock_key
    FROM job
    WHERE state IN ('claimed', 'downloading', 'downloaded', 'uploading', 'uploaded')
      AND entity_lock_key IS NOT NULL
)
SELECT id FROM job
WHERE state = 'queued'
  AND scheduled_for <= NOW()
  AND task_type = ANY(:supported_types)
  AND (entity_lock_key IS NULL OR entity_lock_key NOT IN (SELECT entity_lock_key FROM active_locks))
ORDER BY priority DESC, scheduled_for ASC, created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;
```

---

## 2. Exponential Backoff with Jitter

When a task fails with `ErrorCategory.TRANSIENT`:
- `attempt_count` is incremented by 1.
- If `attempt_count >= max_attempts`:
  - Transition state to `FAILED_PERMANENT`.
  - Log dead-letter event.
- If `attempt_count < max_attempts`:
  - Base delay: `backoff = min(max_backoff, initial_delay * (2 ** (attempt_count - 1)))`.
  - Jitter: `jitter = random.uniform(0.8, 1.2)`.
  - `delay = int(backoff * jitter)`.
  - Update `scheduled_for = NOW() + delay`.
  - Reset `state = 'queued'`, clear `claimed_by_worker`.

---

## 3. Zombie Lease Reclamation (Reaper Protocol, `INV-6`)

- A background janitor loop runs every 30 seconds:
- Query:
  ```sql
  SELECT id FROM job
  WHERE state IN ('claimed', 'downloading', 'downloaded', 'uploading', 'uploaded')
    AND heartbeat_at < NOW() - INTERVAL '60 seconds'
  FOR UPDATE SKIP LOCKED;
  ```
- Any found job is considered abandoned by a crashed or hung worker:
  - Increment `attempt_count += 1`.
  - If `attempt_count >= max_attempts`: transition to `FAILED_PERMANENT`.
  - Else: reset `state = 'queued'`, set `scheduled_for = NOW() + 10 seconds`.
  - Emit alert `job.lease.reclaimed`.
