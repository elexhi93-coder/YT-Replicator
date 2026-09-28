# 07 — Observability and Audit: Sources & Catalog

**Pillar:** 1 · Sources & Catalog · **Chapter:** Observability and Audit · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/01_SOURCES_AND_CATALOG/00_PILLAR_OVERVIEW.md` · `docs/PILLARS/01_SOURCES_AND_CATALOG/06_FAILURES_AND_ERRORS.md`  
**Invariants enforced:** INV-7, INV-9, F-48  

---

## 1. Structured Telemetry & Domain Events

Pillar 1 emits structured audit events to the global event bus. All events conform
to the JSON event envelope with tenant context (`workspace_id`):

| Event Name | Trigger Condition | Payload Fields |
|---|---|---|
| `EVENT_SOURCE_REGISTERED` | New channel/playlist added | `source_id`, `canonical_id`, `source_type`, `scan_depth` |
| `EVENT_SOURCE_SCAN_STARTED` | Scan execution starts | `source_id`, `scan_mode` (`"flat"` \| `"rss"`), `triggered_by` |
| `EVENT_SOURCE_SCAN_COMPLETED`| Scan finishes successfully | `source_id`, `duration_ms`, `items_found`, `items_upserted`, `items_skipped` |
| `EVENT_SOURCE_SCAN_FAILED` | Fatal scan failure | `source_id`, `error_code`, `error_message`, `retry_count` |
| `EVENT_ITEM_DISCOVERED` | New video found | `source_id`, `video_id`, `title`, `published_at` |
| `EVENT_ITEM_SKIPPED` (`F-48`) | Private/deleted item encountered | `source_id`, `video_id`, `skip_reason` |
| `EVENT_ITEM_HYDRATED` | Lazy hydration completed | `catalog_video_id`, `video_id`, `duration_ms`, `has_chapters` |
| `EVENT_SOURCES_RATE_LIMITED` | YouTube HTTP 429 received | `source_id`, `cooling_off_minutes` (15) |

---

## 2. Health & Operational Metrics

These metrics are calculated for the Operator Dashboard:

1. **Source Fleet Health**:
   - `sources_total`: Count of all configured sources.
   - `sources_healthy`: Count where `sync_status = 'IDLE'`.
   - `sources_warning`: Count where `sync_status = 'PARTIAL_WARNING'` (F-48 skips).
   - `sources_failing`: Count where `sync_status = 'FAILED'`.
2. **Catalog Velocity**:
   - `catalog_items_total`: Total discovered videos in catalog.
   - `catalog_unhydrated_queue`: Count of items with `is_hydrated = FALSE`.
   - `catalog_items_discovered_24h`: Rate of discovery over last 24 hours.
3. **Bot & Rate Limit Sentinel**:
   - `rate_limit_hits_total`: Count of HTTP 429 cooling events triggered.

---

## 3. Database Auditability

Every state change in Pillar 1 is reconstructible from PostgreSQL without relying on external logs:
- `sources.last_scanned_at`: Proves exact timing of last completed scan.
- `sources.last_error_message`: Retains error context if a source enters `FAILED`.
- `catalog_video.created_at` vs. `hydrated_at`: Proves discovery time vs. enrichment time.
- `catalog_video.availability`: Retains historical record of videos that later became deleted or private.

---

## 4. Change Log

- **2026-09-28:** Authored `07_OBSERVABILITY_AND_AUDIT.md` specifying structured domain events, fleet health metrics, and database auditability rules.
