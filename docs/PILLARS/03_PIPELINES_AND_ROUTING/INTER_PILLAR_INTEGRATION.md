# Inter-Pillar Integration Ledger: Pillar 3 (Pipelines & Routing)

**Pillar:** 3 — Pipelines & Routing  
**Status:** `active`  
**Last Synchronized:** 2026-09-28  
**Governed by:** `docs/PILLARS/_STANDARD/INTER_PILLAR_INTEGRATION_STANDARD.md`  

---

## 1. Direct Neighbor Topology

| Sibling Pillar | Interaction Nature | Inbound (What We Receive) | Outbound (What We Provide) |
|---|---|---|---|
| **Pillar 1** (`01_SOURCES_AND_CATALOG`) | Catalog Inventory | Discovered `catalog_video` inventory & metadata | Source association targets |
| **Pillar 2** (`02_DESTINATIONS_AND_AUTH`) | Destination Metadata | Authorized YouTube channels & token health status | Destination association targets |
| **Pillar 4** (`04_JOB_ENGINE`) | Scheduling Triggers | Trigger polling for active pipelines | Work batch payloads |
| **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Media Policy Definition | N/A (Storage reads pipeline policy) | Download & retention profile rules (`INV-6`) |
| **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Deduplication Ledger | Prior delivery receipts (`delivered_pairs`) | Next actionable candidate pairs (`INV-5`) |

---

## 2. Inbound Integrations (What Sibling Pillars Expect From Us)

### Sibling: Pillar 4 (Job Engine) & Pillar 6 (Delivery & Ledger)
- **Contract Boundary**:
  - `pipelines.api.get_next_candidate_batch(pipeline_id, limit) -> tuple[ReplicationCandidateDTO, ...]`
  - `pipelines.api.preview_candidates(pipeline_id) -> CandidatePreviewDTO`
- **Data Exchanged**: Pipeline ID, batch size; returns frozen `ReplicationCandidateDTO` entities.
- **Guarantees We Provide**:
  - `INV-5`: Never returns a candidate pair that already exists in Pillar 6 ledger as successfully delivered.
  - `INV-9`: Multiple pipelines linked to the same source maintain independent cursors.
  - Deterministic ordering: backfill is strictly oldest-first (`published_at ASC`); monitor is newest-first (`published_at DESC`).
- **Pending Adjustments From Upstream Changes**:
  - None currently pending.

### Sibling: Pillar 5 (Media & Storage)
- **Contract Boundary**: `pipelines.api.get_pipeline_media_policy(pipeline_id) -> PipelineMediaPolicyDTO`
- **Data Exchanged**: Pipeline ID; returns resolution limits, container preference, and retention directive (`KEEP`, `DELETE_AFTER_UPLOAD`).
- **Guarantees We Provide**:
  - `INV-6`: Policy is fully declared in relational state; no hidden filesystem state.

---

## 3. Outbound Integrations (What We Expect From Sibling Pillars)

### Sibling: Pillar 6 (Delivery & Ledger)
- **Contract Boundary**: `delivery.api.is_delivered_batch(pairs: tuple[tuple[str, str], ...]) -> dict[tuple[str, str], bool]`
- **Guarantees We Expect**:
  - Fast, indexed lookup answering whether `(catalog_video_id, destination_channel_id)` has a completed delivery receipt.
- **Pending Adjustments Required in Pillar 6 (Downstream Blast Radius)**:
  - Aligned with `ADJ-P1-02` logged in `06_DELIVERY_AND_LEDGER/INTER_PILLAR_INTEGRATION.md`.

### Sibling: Pillar 1 (Sources & Catalog)
- **Contract Boundary**: `sources.api.list_videos_for_source(source_id, ...)`
- **Guarantees We Expect**:
  - Returns canonical catalog videos with parsed `published_at`, duration, and live/short flags.
- **Pending Adjustments Required in Pillar 1 (Downstream Blast Radius)**:
  - None. Aligned with `01_SOURCES_AND_CATALOG/03_INTERFACE_CONTRACT.md`.

---

## 4. Cross-Pillar Change Log & Blast Radius Audit Trail

- **2026-09-28**: Initialized bilateral contract matrix for Pillar 3. Confirmed alignment with Pillar 1 catalog DTOs and Pillar 6 deduplication ledger (`ADJ-P1-02`).
