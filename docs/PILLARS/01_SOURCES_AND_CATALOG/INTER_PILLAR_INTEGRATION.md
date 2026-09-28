# Inter-Pillar Integration Ledger: Pillar 1 (Sources & Catalog)

**Pillar:** 1 — Sources & Catalog  
**Status:** `active`  
**Last Synchronized:** 2026-09-28  
**Governed by:** `docs/PILLARS/_STANDARD/INTER_PILLAR_INTEGRATION_STANDARD.md`  

---

## 1. Direct Neighbor Topology

| Sibling Pillar | Interaction Nature | Inbound (What We Receive) | Outbound (What We Provide) |
|---|---|---|---|
| **Pillar 0** (`00_INTER_PILLAR_CONTRACTS`) | Port Contract & DTOs | `SourceProvider` protocol, `SourceItem`, `SourceItemDetail` DTOs | Concrete YouTube adapter implementation conforming to `SourceProvider` |
| **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Pipeline Candidate Selection | Source association queries (`pipeline_source`) | Queryable catalog videos (`catalog_video`), un-replicated candidate lists |
| **Pillar 4** (`04_JOB_ENGINE`) | Background Task Execution | Job dispatch & execution guarantees for discovery scans | Task descriptors for channel scans and metadata hydration jobs |
| **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Media Ingestion Handover | Handover signal / media fetch requests | Metadata context (`video_id`, source URL); **never media bytes (INV-7)** |
| **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Deduplication Audit | Completed delivery ledger history (`ledger` records) | Catalog video status checking (`already_uploaded` flag validation) |

---

## 2. Inbound Integrations (What Sibling Pillars Expect From Us)

### Sibling: Pillar 3 (Pipelines & Routing)
- **Contract Boundary**: `sources.api.get_catalog_items_for_pipeline(pipeline_id, ...)`
- **Data Exchanged**: Sequence of `SourceItem` DTOs matching pipeline inclusion/exclusion criteria.
- **Guarantees We Provide**:
  - `INV-9`: A source can belong to multiple pipelines without data duplication.
  - Exclude videos with `live_status == 'live'` or `availability in ('private', 'deleted')`.
- **Pending Adjustments From Upstream Changes**:
  - None currently pending.

### Sibling: Pillar 5 (Media & Storage)
- **Contract Boundary**: `sources.api.get_item_materialization_target(video_id)`
- **Data Exchanged**: Source video ID, canonical YouTube URL.
- **Guarantees We Provide**:
  - `INV-7`: Pillar 1 never touches media bytes. Pillar 5 independently executes download through yt-dlp using canonical URL.
- **Pending Adjustments From Upstream Changes**:
  - None currently pending.

---

## 3. Outbound Integrations (What We Expect From Sibling Pillars)

### Sibling: Pillar 0 (Inter-Pillar Contracts)
- **Contract Boundary**: Implementation of `SourceProvider` protocol.
- **Data Exchanged**: Returns immutable frozen dataclasses (`SourceItem`, `SourceItemDetail`).
- **Guarantees We Expect**:
  - Errors conform strictly to `SourceProviderError` hierarchy (`SourceUnavailableError`, `ItemNotFoundError`, etc.).
- **Pending Adjustments Required in Pillar 0 (Downstream Blast Radius)**:
  - None currently pending. Fully aligned with `00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`.

### Sibling: Pillar 4 (Job Engine)
- **Contract Boundary**: `jobs.api.enqueue_job("sources.scan", payload)`
- **Data Exchanged**: `source_id`, `scan_mode` (`"flat"`, `"rss"`).
- **Guarantees We Expect**:
  - Atomic lock per `source_id` so two scans never run concurrently on the same channel.
  - Partial failure tolerance (`F-48`): task completes with warning rather than aborting.
- **Pending Adjustments Required in Pillar 4 (Downstream Blast Radius)**:
  - `[ADJ-P1-01]` `[2026-09-28]` `[STATUS: RESOLVED_IN_SPEC]` **Job Engine Scan Concurrency Lock**: Pillar 4 must ensure task type `sources.scan` enforces a per-entity concurrency limit of 1 per `source_id` to prevent rate-limit bans from YouTube. *Adopted into Pillar 4.*

### Sibling: Pillar 6 (Delivery & Ledger)
- **Contract Boundary**: `delivery.api.is_delivered(source_id, video_id, destination_id)`
- **Data Exchanged**: Deduplication check queries.
- **Guarantees We Expect**:
  - Fast indexed lookup across delivery ledger so catalog UI can render "Already Uploaded" badge.
- **Pending Adjustments Required in Pillar 6 (Downstream Blast Radius)**:
  - `[ADJ-P1-02]` `[2026-09-28]` `[STATUS: RESOLVED_IN_SPEC]` **Ledger Query Performance**: Ledger must expose a batch query API `delivery.api.get_delivered_video_ids(source_id, destination_id)` returning a set of `video_id`s so Pillar 1 can batch-render catalog rows efficiently without N+1 queries. *Adopted into Pillar 6.*

---

## 4. Cross-Pillar Change Log & Blast Radius Audit Trail

- **2026-09-28**: [Pillar 1 ➔ Pillar 4] Identified requirement for per-source concurrency lock on scan jobs (`ADJ-P1-01`). Status: `RESOLVED_IN_SPEC`.
- **2026-09-28**: [Pillar 1 ➔ Pillar 6] Identified requirement for batch delivery status query (`ADJ-P1-02`) to support high-performance Catalog Grid rendering. Status: `RESOLVED_IN_SPEC`.
