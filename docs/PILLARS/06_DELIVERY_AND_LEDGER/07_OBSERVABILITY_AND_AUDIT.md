# 07 — Observability and Audit: Delivery & Ledger

**Pillar:** 6 · Delivery & Ledger · **Chapter:** Observability and Audit · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §8  
**Depends on:** `docs/PILLARS/06_DELIVERY_AND_LEDGER/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-4, INV-8  

---

## 1. Domain Event Registry

| Event Name | Trigger Condition | Payload Key Attributes | Purpose |
|---|---|---|---|
| `delivery.attempt.started` | Upload session initiated | `delivery_id`, `destination_channel_id`, `attempt_number` | Active upload telemetry |
| `delivery.succeeded` | Video confirmed uploaded and active on YouTube | `delivery_id`, `destination_video_id`, `duration_ms` | Throughput and ledger audit |
| `delivery.failed` | Upload attempt failed permanently | `delivery_id`, `error_code`, `error_detail` | Failure alerts |
| `delivery.reconciled` | Inventory sync reconciled video status | `delivery_id`, `reconciliation_state` | Reconciliation tracking |
| `delivery.unclaimed_detected` | Unclaimed video found on remote channel | `destination_channel_id`, `remote_video_id` | Operator alert (`INV-8`) |

---

## 2. Real-Time Prometheus Metrics

```prometheus
# HELP ytr_delivery_success_total Total videos successfully delivered to destination platforms.
# TYPE ytr_delivery_success_total counter
ytr_delivery_success_total{destination="Tech Insights"} 1280

# HELP ytr_delivery_attempt_duration_seconds Upload duration histogram.
# TYPE ytr_delivery_attempt_duration_seconds histogram

# HELP ytr_reconciliation_mismatches_total Current unreconciled discrepancies.
# TYPE ytr_reconciliation_mismatches_total gauge
ytr_reconciliation_mismatches_total{state="unclaimed_present"} 2
ytr_reconciliation_mismatches_total{state="missing_expected"} 0
```
