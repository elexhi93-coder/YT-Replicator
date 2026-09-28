# 07 — Observability and Audit: Pipelines & Routing

**Pillar:** 3 · Pipelines & Routing · **Chapter:** Observability and Audit · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §8  
**Depends on:** `docs/PILLARS/03_PIPELINES_AND_ROUTING/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-6, INV-9  

---

## 1. Domain Event Registry

| Event Name | Trigger Condition | Payload Key Attributes | Purpose |
|---|---|---|---|
| `pipeline.status_changed` | Operator pauses, activates, or archives pipeline | `pipeline_id`, `old_status`, `new_status` | Job scheduler starts/stops polling |
| `pipeline.cursor.advanced` | Worker completes delivery and updates backfill position | `pipeline_id`, `source_id`, `cursor_timestamp` | Audit backfill progression |
| `pipeline.candidates.evaluated`| Batch calculation completed | `pipeline_id`, `actionable_count`, `skipped_count` | Metric tracking |
| `pipeline.source.exhausted` | Backfill cursor catches up to newest catalog video | `pipeline_id`, `source_id` | Operator notification |

---

## 2. Real-Time Prometheus Metrics

```prometheus
# HELP ytr_pipeline_candidates_actionable_total Number of actionable candidates generated.
# TYPE ytr_pipeline_candidates_actionable_total counter
ytr_pipeline_candidates_actionable_total{pipeline_id="..."} 150

# HELP ytr_pipeline_candidates_skipped_total Number of candidates skipped by reason.
# TYPE ytr_pipeline_candidates_skipped_total counter
ytr_pipeline_candidates_skipped_total{pipeline_id="...", reason="ALREADY_DELIVERED"} 420
ytr_pipeline_candidates_skipped_total{pipeline_id="...", reason="SHORTS_FILTERED"} 85

# HELP ytr_pipeline_backfill_progress_ratio Ratio of backfilled videos to total catalog items.
# TYPE ytr_pipeline_backfill_progress_ratio gauge
ytr_pipeline_backfill_progress_ratio{pipeline_id="...", source_id="..."} 0.74
```
