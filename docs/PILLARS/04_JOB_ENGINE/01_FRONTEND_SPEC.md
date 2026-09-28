# 01 — Frontend Specification: Job Engine

**Pillar:** 4 · Job Engine · **Chapter:** Frontend Specification · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §3  
**Depends on:** `docs/PILLARS/04_JOB_ENGINE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-10, INV-11  

---

## 1. Executive Summary & Screen Inventory

Pillar 4 provides the operational monitoring dashboard for the background execution queue:
live job tracking, worker fleet health, transient failure backoff inspection, manual retries,
and global worker pausing.

### Screen & Component List
1. **Screen 1: Background Jobs Console (`/jobs`)**
   - KPI Strip (Queued, Running, Succeeded Today, Failed / Dead-Letter, Active Workers).
   - Global Pause / Resume Banner (pauses task claiming without mutating rows).
   - Jobs Data Table (Job ID, Task Type, Status Pill, Worker, Attempts, Elapsed Time, Actions).
   - Filter Controls (State: All/Queued/Running/Failed, Task Type, Date Range).
2. **Screen 2: Job Detail & Error Inspector Drawer**
   - Execution Timeline (queued ➔ claimed ➔ downloading ➔ uploading ➔ completed).
   - Redacted Payload JSON Viewer.
   - Failure Diagnostic Panel: Error code, attempt count, backoff schedule, redacted traceback.
   - Manual Actions: `[ Force Retry Now ]`, `[ Cancel Job ]`.

---

## 2. Screen 1: Background Jobs Console (`/jobs`)

### 2.1 Layout Block Diagram
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Background Job Queue                          [ Pause Scheduler ⏸ ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ KPI Strip: [ 12 Queued ] [ 3 Running ] [ 418 Completed ] [ 2 Failed ] [ 4/4 Workers ]│
├─────────────────────────────────────────────────────────────────────────────┤
│ Filters: [ State: All ▼ ] [ Task: All ▼ ] [ Search by Job ID or Entity... ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ Jobs Table                                                                  │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Task / ID         | Phase        | Worker     | Attempts | Created      │ │
│ ├───────────────────┼──────────────┼────────────┼──────────┼──────────────┤ │
│ │ replicate_video   | DOWNLOADING  | worker-01  | 1 / 5    | 2m ago       │ │
│ │ e81f0...          | (45% fetched)| (active)   |          |              │ │
│ ├───────────────────┼──────────────┼────────────┼──────────┼──────────────┤ │
│ │ replicate_video   | RETRY_WAIT   | —          | 2 / 5    | 15m ago      │ │
│ │ a92c4...          | Next in 4m   | (backoff)  |          |              │ │
│ ├───────────────────┼──────────────┼────────────┼──────────┼──────────────┤ │
│ │ sources.scan      | COMPLETED    | worker-02  | 1 / 1    | 1h ago       │ │
│ │ 3f71b...          | (14 found)   | (released) |          |              │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Screen 2: Job Detail & Error Inspector Drawer

### 3.1 Trace & Backoff Visualization
When an operator clicks a failed or running job:
- **Phase Stepper**: Visual indicators for `queued ➔ claimed ➔ downloading ➔ downloaded ➔ uploading ➔ completed`.
- **Backoff Card**: For transient errors (`DEST_ERR_CHUNK_FAILED` or network drops), displays:
  - Error: `CHUNK_UPLOAD_TIMEOUT: Connection reset by peer`
  - Next Retry: `2026-09-28 02:45:10 UTC (Attempt 3 of 5, delay 32s with jitter)`
  - Action: `[ Retry Immediately ]` to bypass the backoff timer.
- **Dead-Letter Card**: For permanent errors (`TOKEN_REVOKED`, `DUPLICATE_VIDEO`), displays operator remediation checklist.

---

## 4. Verification Checklist (Frontend DoD)

- [ ] Real-time updates reflect state machine transitions without full page reload.
- [ ] Global pause banner halts claiming without altering pending job state.
- [ ] Redacted trace viewer prevents credential or plaintext token leakage (`INV-1`).
- [ ] Manual retry and cancellation buttons trigger transactional endpoints.
