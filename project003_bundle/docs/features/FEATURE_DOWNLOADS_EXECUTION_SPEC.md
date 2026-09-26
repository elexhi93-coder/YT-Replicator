# Feature — Downloads Execution Spec

Status: RFC / Ready for implementation planning
Owner: dashboard + watcher teams
Created: 2026-05-03

## 1. Purpose

Define the Downloads tab as an operator control center for:
- Selecting exactly what to download
- Controlling order (oldest/newest)
- Running in batches
- Observing queue health and failures
- Safely handing off jobs to processing/upload pipeline

This document focuses on **Downloads** only and maps how each feature interrelates so implementation can begin immediately.

## 2. Workflow Context

High-level flow:
1. Source emits candidate videos (from catalog/hydrate/discovery)
2. Operator filters by pipeline/source and selects videos
3. Queue receives jobs with order + batch constraints
4. Watcher executes downloads using concurrency and retry policies
5. Integrity checks gate handoff to processing/upload
6. Cleanup + telemetry update status and metrics

## 3. Feature Catalog (Must-Have)

Each feature includes objective, UI, API/data touchpoints, and dependencies.

### D-01 Video Selection Queue

Objective:
- Allow explicit video-level selection (checkbox list) before queueing.

UI:
- Candidate list table in Downloads tab with select-all, per-row checkbox.
- Bulk actions: Queue selected, Skip selected.

API/Data:
- POST `/api/downloads/queue/selected`
- Payload: `{ pipeline_id, source_id, video_ids[], direction, batch_size, profile_id? }`
- Reads from candidate catalog table/view.

Dependencies:
- Requires D-07 (dedup clarity) to avoid confusing skipped rows.
- Feeds D-02 (ordering), D-03 (batching).

Definition of Done:
- Operator can queue arbitrary subset of visible candidates in one action.

---

### D-02 Ordering Control (Oldest/Newest)

Objective:
- Support deterministic ordering: oldest -> newest or newest -> oldest.

UI:
- Direction selector near Queue action and per-source quick trigger.

API/Data:
- Extend queue endpoint with `direction: oldest|newest`.
- Queue row stores `requested_direction`.

Dependencies:
- Requires candidate rows to have stable published timestamp.
- Works with D-03 batch windows.

Definition of Done:
- For same candidate set, queue order is deterministic and reproducible.

---

### D-03 Batch Downloading

Objective:
- Run downloads in controlled chunks (example: 10 at a time).

UI:
- `Batch size` input, `Queue next batch` and optional `auto-continue` toggle.
- Batch status badge: `batch 2/7`.

API/Data:
- Queue rows include `batch_id`, `batch_index`, `batch_total`.
- POST `/api/downloads/queue/batch-next`

Dependencies:
- Uses D-02 ordering.
- Governed by D-06 concurrency guardrails.

Definition of Done:
- System queues/execut es only configured chunk size and tracks progress by batch.

---

### D-04 Row-Level Download Action

Objective:
- One-click queue per video from candidate list.

UI:
- `Download` button on each video row.

API/Data:
- POST `/api/downloads/queue/single`
- Payload: `{ video_id, pipeline_id, direction? }`

Dependencies:
- Uses D-07 dedup checks and D-08 filter persistence.

Definition of Done:
- Clicking row action queues exactly one job and updates row status instantly.

---

### D-05 Quick Download Action in Sources Tab

Objective:
- Provide same one-click queue action from Sources/Catalog context.

UI:
- Add `Download` button in source catalog rows.

API/Data:
- Reuse `/api/downloads/queue/single`
- Source tab sends same payload + returns refreshed row partial.

Dependencies:
- Requires shared queue service used by Downloads and Sources.

Definition of Done:
- Source and Downloads tabs create identical queue entries for same video.

---

### D-06 Queue Guardrails (Concurrency + Pause Controls)

Objective:
- Keep queue safe and controllable under load.

UI:
- Controls: `Pause all`, `Resume all`, `Pause pipeline`, `Resume pipeline`.
- Settings: global workers, per-pipeline workers.

API/Data:
- POST `/api/downloads/control/pause-all`
- POST `/api/downloads/control/resume-all`
- POST `/api/downloads/control/pipeline/{id}/pause|resume`
- Settings persisted in app settings table.

Dependencies:
- Governs D-03 batching throughput.
- Informs D-09 retry backoff behavior.

Definition of Done:
- Controls are respected within one polling cycle and reflected in UI status.

---

### D-07 Dedup & Skip Transparency

Objective:
- Explain why a candidate/job is skipped: already queued, already downloaded, already uploaded, blocked.

UI:
- Status badge + tooltip reason per row.
- Filter chips: `duplicates`, `already done`, `blocked`.

API/Data:
- Queue API returns structured skip reason codes.
- Add `skip_reason` column or computed field in job listing.

Dependencies:
- Required by D-01, D-04, D-05 for trustable operator actions.

Definition of Done:
- Every skipped row has explicit machine + human-readable reason.

---

### D-08 Filter/Context Persistence

Objective:
- Preserve active pipeline/source/order/batch context across all actions and refreshes.

UI:
- All partial reloads keep current filters.

API/Data:
- Include context query params in all HTMX endpoints.
- Server echoes selected context in partial renders.

Dependencies:
- Required by D-01..D-05 usability.

Definition of Done:
- Trigger/toggle/retry actions never reset operator context unexpectedly.

---

### D-09 Retry Policy + Failure Buckets

Objective:
- Make failure handling scalable and predictable.

UI:
- Grouped failure panel by type (`network`, `rate_limit`, `unavailable`, `storage`).
- Actions: `Retry group`, `Cancel group`.

API/Data:
- Retry policy table/config by failure code:
  - max_attempts
  - backoff_strategy
  - cooldown_sec
- Endpoints:
  - POST `/api/downloads/failures/retry-group`
  - POST `/api/downloads/failures/cancel-group`

Dependencies:
- Uses D-06 controls and D-10 storage safety signals.

Definition of Done:
- Group retry/cancel works and policies are auditable.

---

### D-10 Storage Safety + Integrity Gate

Objective:
- Prevent bad or partial assets from entering processing/upload pipeline.

UI:
- Storage health banner (free GB, threshold, mount status).
- Integrity badge per job: `checked`, `failed check`.

API/Data:
- Pre-handoff validator:
  - file exists
  - non-zero size
  - optional probe (duration/stream readable)
- Low-space policy settings:
  - warn_threshold_gb
  - hard_stop_threshold_gb

Dependencies:
- Blocks handoff to downstream pipeline when invalid.
- Works with D-09 to categorize failures.

Definition of Done:
- Invalid download cannot transition to processing/upload-ready state.

## 4. Interlock Map (How Features Interrelate)

### 4.1 Dependency Graph

1. D-01 Selection Queue is the primary entry point.
2. D-02 Ordering and D-03 Batching shape queue formation from D-01.
3. D-04 and D-05 are alternate entry points into D-01 queue service.
4. D-06 governs execution rate/state of queued jobs.
5. D-07 annotates outcomes from all queue entry points.
6. D-08 preserves operator context across D-01..D-09 actions.
7. D-09 handles failure branches from execution.
8. D-10 is the final quality gate before downstream handoff.

### 4.2 Interaction Matrix

| From | To | Relationship |
|---|---|---|
| D-01 | D-02 | Selection uses chosen sort direction |
| D-01 | D-03 | Selection is segmented into batches |
| D-04 | D-01 | Single-row queue uses same core queue service |
| D-05 | D-01 | Sources quick action uses same core queue service |
| D-03 | D-06 | Batch throughput limited by worker controls |
| D-06 | D-09 | Pause/resume and limits affect retry scheduling |
| D-07 | D-01/D-04/D-05 | Dedup reason shown to prevent repeated confusion |
| D-08 | All UI actions | Keeps context stable after every mutation |
| D-09 | D-10 | Failures may escalate to storage/integrity blockers |
| D-10 | downstream processing/upload | Only validated assets can proceed |

## 5. Data & API Contract Draft

## 5.1 Core Queue Request (Unified)

Endpoint:
- POST `/api/downloads/queue`

Payload:
```json
{
  "pipeline_id": 12,
  "source_id": 33,
  "video_ids": ["yt_abcd1", "yt_abcd2"],
  "direction": "oldest",
  "batch_size": 10,
  "auto_continue": false,
  "requested_by": "ui"
}
```

Response:
```json
{
  "queued": 8,
  "skipped": 2,
  "skip_reasons": {
    "already_done": 1,
    "already_queued": 1
  },
  "batch": {
    "id": "b_20260503_001",
    "index": 1,
    "total": 1
  }
}
```

## 5.2 Job Status Model (Minimum)

`pending -> downloading -> downloaded -> validated -> handed_off -> done`

Failure branches:
- `failed_transient`
- `failed_permanent`
- `blocked_storage`
- `blocked_integrity`

## 6. UX Sections for Downloads Tab

Recommended panel order:
1. Selection & Queue Builder (pipeline/source/order/batch + candidate list)
2. Live Execution (active downloads + workers + controls)
3. Failure Buckets (retry/cancel by group)
4. Jobs Timeline (recent + status transitions)
5. Files Browser
6. Storage Settings (collapsed, with health summary in header)

## 7. Implementation Slices (ASAP)

### Slice A (2-3 days): Queue Entry Foundation
- D-01, D-02, D-04
- Unified queue endpoint
- Row-level Download action in Downloads

### Slice B (2-3 days): Batch + Context Stability
- D-03, D-08
- Batch metadata + next-batch endpoint
- Preserve filter state in all HTMX actions

### Slice C (2-3 days): Sources Integration + Dedup Clarity
- D-05, D-07
- Download button in Sources catalog
- Skip reason badges/tooltips

### Slice D (3-4 days): Reliability Layer
- D-06, D-09, D-10
- pause/resume controls
- failure buckets + policy retries
- integrity and storage gate before handoff

## 8. Testing Strategy (Minimum)

Unit:
- queue ordering oldest/newest
- batch partition logic
- dedup reason resolver
- retry policy calculation

Integration:
- queue from Downloads and Sources creates same job shape
- pause/resume reflected in worker execution cycle
- low-storage gate blocks handoff

UI/HTMX:
- filter persistence after trigger/retry/toggle actions
- row Download action updates row status without full reload

## 9. Open Decisions

1. Candidate source of truth: existing catalog table vs new candidate cache table.
2. Batch semantics: strict N queued vs N actively downloading.
3. Auto-continue default: enabled or manual by default.
4. Integrity depth: lightweight probe only vs full ffprobe policy.

## 10. Immediate Next Step

Create the technical backlog from Slice A with concrete tasks:
- DB migration tasks
- API route tasks
- template partial tasks
- queue service refactor tasks
- tests list
