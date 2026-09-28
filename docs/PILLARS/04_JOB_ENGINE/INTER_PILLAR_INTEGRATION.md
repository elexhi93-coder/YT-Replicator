# Inter-Pillar Integration Ledger: Pillar 4 (Job Engine)

**Pillar:** 4 — Job Engine  
**Status:** `active`  
**Last Synchronized:** 2026-09-28  
**Governed by:** `docs/PILLARS/_STANDARD/INTER_PILLAR_INTEGRATION_STANDARD.md`  

---

## 1. Direct Neighbor Topology

| Sibling Pillar | Interaction Nature | Inbound (What We Receive) | Outbound (What We Provide) |
|---|---|---|---|
| **Pillar 1** (`01_SOURCES_AND_CATALOG`) | Background Discovery Scans | Enqueued scan tasks (`sources.scan`, `sources.hydrate`) | Worker execution, concurrency guarantees, task status |
| **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Pipeline Sync Scheduling | Scheduled pipeline ticks and replication trigger jobs | Worker execution and lock coordination |
| **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Media Download / Process Jobs | Download tasks (`media.download`, `media.render`) | Concurrency control over heavy network and CPU tasks |
| **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Upload Execution Jobs | Upload tasks (`delivery.upload`) | Quota-aware task dispatch |

---

## 2. Inbound Integrations (What Sibling Pillars Expect From Us)

### Sibling: Pillar 1 (Sources & Catalog)
- **Contract Boundary**: `jobs.api.enqueue_job(task_type, payload, entity_lock_key)`
- **Data Exchanged**: Source scanning jobs.
- **Guarantees We Provide**:
  - Deterministic queue ordering with retry backoff.
- **Pending Adjustments From Upstream Changes**:
  - `[ADJ-P1-01]` `[2026-09-28]` `[STATUS: RESOLVED_IN_SPEC]` **Job Engine Scan Concurrency Lock**: Formally adopted into `04_LOGIC_AND_RULES.md` and `05_DATA_MODEL.md`.

---

## 3. Outbound Integrations (What We Expect From Sibling Pillars)

- **Worker Dispatch Loop**: The generic worker module invokes registered task handlers provided by Pillars 1, 5, and 6. Job Engine passes immutable task payloads and receives `TaskExecutionResult` (success, transient error with retry after, permanent failure, or skip).

---

## 4. Cross-Pillar Change Log & Blast Radius Audit Trail

- **2026-09-28**: [Pillar 1 ➔ Pillar 4] Resolved requirement `ADJ-P1-01` by adding `entity_lock_key` to `job` table and claim query. Status: `RESOLVED_IN_SPEC`.
