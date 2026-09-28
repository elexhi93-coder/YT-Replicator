# Inter-Pillar Integration Ledger: Pillar 5 (Media & Storage)

**Pillar:** 5 — Media & Storage  
**Status:** `active`  
**Last Synchronized:** 2026-09-28  
**Governed by:** `docs/PILLARS/_STANDARD/INTER_PILLAR_INTEGRATION_STANDARD.md`  

---

## 1. Direct Neighbor Topology

| Sibling Pillar | Interaction Nature | Inbound (What We Receive) | Outbound (What We Provide) |
|---|---|---|---|
| **Pillar 1** (`01_SOURCES_AND_CATALOG`) | Catalog Identity | Source video canonical ID & metadata | Media status updates (`has_media_on_disk`) |
| **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Media Policies | `PipelineMediaPolicyDTO` (resolution cap, retention) | Asset availability for candidate evaluation |
| **Pillar 4** (`04_JOB_ENGINE`) | Task Dispatch & Execution | Download / purge task invocations | Intermediate state updates (`downloading` ➔ `downloaded`) |
| **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Media Consumption & Ledger Check | Delivery queries & upload media path requests | Verified physical media path (`media_asset.absolute_path`) |
| **Pillar 7** (`07_PLATFORM_FOUNDATION_AND_OPS`) | Host Filesystem Access | Mount point locations & disk space telemetry | Storage capacity metrics |

---

## 2. Inbound Integrations (What Sibling Pillars Expect From Us)

### Sibling: Pillar 6 (Delivery & Ledger)
- **Contract Boundary**: `media.api.get_verified_asset_for_upload(catalog_video_id) -> VerifiedMediaAssetDTO`
- **Data Exchanged**: Catalog video ID; returns verified file path, size, MIME type, and thumbnail stream.
- **Guarantees We Provide**:
  - `INV-3`: Only returns assets whose status is strictly `ON_DISK` with confirmed SHA-256 and size > 0.
  - Zero uploads of incomplete or in-progress `.part` files.
- **Pending Adjustments From Upstream Changes**:
  - None currently pending.

### Sibling: Pillar 3 (Pipelines & Routing)
- **Contract Boundary**: `media.api.evaluate_retention_dry_run(pipeline_id) -> RetentionDryRunResultDTO`
- **Guarantees We Provide**:
  - `INV-10`: Dry-run query previews exact list of files and bytes eligible for deletion without deleting anything.
  - `INV-2`: Cross-checks Pillar 6 ledger to ensure every enabled destination has terminal receipt before marking candidate for deletion.

---

## 3. Outbound Integrations (What We Expect From Sibling Pillars)

### Sibling: Pillar 6 (Delivery & Ledger)
- **Contract Boundary**: `delivery.api.are_all_pipeline_destinations_terminal(catalog_video_id, pipeline_id) -> bool`
- **Guarantees We Expect**:
  - `INV-2`: Accurate answer determining whether every enabled target channel has either succeeded or failed permanently before file deletion is permitted.
- **Pending Adjustments Required in Pillar 6 (Downstream Blast Radius)**:
  - `[ADJ-P5-01]` `[2026-09-28]` `[STATUS: RESOLVED_IN_SPEC]` **Terminal Destination Delivery Check**: Pillar 6 must expose an efficient batch helper `are_all_pipeline_destinations_terminal` for retention sweeps. *Adopted into Pillar 6.*

---

## 4. Cross-Pillar Change Log & Blast Radius Audit Trail

- **2026-09-28**: [Pillar 5 ➔ Pillar 6] Logged requirement `ADJ-P5-01` (terminal delivery verification helper for retention pruning). Status: `RESOLVED_IN_SPEC`.
