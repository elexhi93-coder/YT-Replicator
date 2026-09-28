# 08 — Testing Strategy & Definition of Done: Job Engine

**Pillar:** 4 · Job Engine · **Chapter:** Testing Strategy & DoD · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §9  
**Depends on:** All prior chapters in Pillar 4  
**Invariants enforced:** INV-5, INV-6, INV-10, INV-11, INV-12  

---

## 1. Test Suite Architecture

| Layer | Focus / Scope | Key Mocking Boundaries |
|---|---|---|
| **Unit Tests** | Backoff delay calculation, jitter distribution, state machine legal transitions | Pure unit tests |
| **Concurrency Tests** | Double-claim prevention (`INV-10`), entity lock exclusion (`ADJ-P1-01`) | Real PostgreSQL 16 container, 10 concurrent worker threads |
| **Recovery Tests** | Worker heartbeat expiration, Janitor lease reaper resumption (`INV-6`) | Fast-forwarding database time |
| **AST / Boundary Tests** | Verify `src.jobs` has zero imports of `google`, `youtube`, `yt_dlp`, `ffmpeg`, or `ledger` | AST parser inspecting `src/jobs` |

---

## 2. Invariant Enforcement Tests

### 2.1 Multi-Worker Concurrency Test (`INV-10`)
```python
def test_ten_workers_claiming_simultaneously_never_double_claim(pg_session_factory):
    """Assert 10 concurrent workers competing for 50 jobs claim each job exactly once."""
    import concurrent.futures
    # 50 queued jobs
    # 10 workers running claim_next_job in parallel loops
    # Assert total distinct claimed jobs == 50
    # Assert zero conflict exceptions or duplicate leases
    ...
```

### 2.2 Per-Entity Concurrency Lock Test (`ADJ-P1-01`)
```python
def test_entity_lock_prevents_simultaneous_scans_of_same_source(pg_session_factory):
    """Assert second job with identical entity_lock_key is skipped while first is active."""
    ...
```

---

## 3. Definition of Done (DoD) Checklist

- [ ] Multi-threaded concurrent claim test demonstrates zero double-claims (`INV-10`).
- [ ] Per-entity lock key prevents simultaneous execution on same entity (`ADJ-P1-01`).
- [ ] Heartbeat reaper recovers zombie jobs after 60 seconds without data loss (`INV-6`).
- [ ] Backoff with jitter correctly schedules retries and respects `max_attempts`.
- [ ] AST boundary tests verify zero domain imports of YouTube, media, or ledger code.
