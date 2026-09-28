# 07 — Observability and Audit: Job Engine

**Pillar:** 4 · Job Engine · **Chapter:** Observability and Audit · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §8  
**Depends on:** `docs/PILLARS/04_JOB_ENGINE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-10  

---

## 1. Domain Event Registry

| Event Name | Trigger Condition | Payload Key Attributes | Purpose |
|---|---|---|---|
| `job.enqueued` | Job inserted into queue | `job_id`, `task_type`, `priority`, `scheduled_for` | Queue depth monitoring |
| `job.claimed` | Worker claims job lease | `job_id`, `task_type`, `worker_id` | Worker activity tracking |
| `job.phase_transition` | Execution phase changes | `job_id`, `from_phase`, `to_phase` | Progress telemetry |
| `job.completed` | Task finished successfully | `job_id`, `task_type`, `duration_ms` | Throughput and SLA metrics |
| `job.retried` | Transient error backoff | `job_id`, `attempt_count`, `next_delay_s` | Failure pattern detection |
| `job.dead_lettered` | Max attempts reached or permanent error | `job_id`, `error_code`, `error_detail` | Operator alert |
| `job.lease.reclaimed` | Janitor reclaims abandoned job | `job_id`, `former_worker_id` | Worker crash diagnosis |

---

## 2. Real-Time Prometheus Metrics

```prometheus
# HELP ytr_jobs_queued_total Current count of queued jobs by task type.
# TYPE ytr_jobs_queued_total gauge
ytr_jobs_queued_total{task_type="replicate_video"} 12
ytr_jobs_queued_total{task_type="sources.scan"} 1

# HELP ytr_jobs_active_total Currently executing jobs across workers.
# TYPE ytr_jobs_active_total gauge
ytr_jobs_active_total{phase="downloading"} 2
ytr_jobs_active_total{phase="uploading"} 1

# HELP ytr_jobs_execution_duration_seconds Histogram of total task execution time.
# TYPE ytr_jobs_execution_duration_seconds histogram

# HELP ytr_jobs_reaper_reclaimed_total Count of zombie jobs reclaimed after worker failure.
# TYPE ytr_jobs_reaper_reclaimed_total counter
```
