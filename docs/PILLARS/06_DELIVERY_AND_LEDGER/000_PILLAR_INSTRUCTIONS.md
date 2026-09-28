# 000 — Pillar 6 Instructions & Working Frontier (Delivery & Ledger)

**Pillar:** 6 — Delivery & Ledger  
**Status:** `drafting`  
**Authority:** Local domain directive for Pillar 6. Governed by `docs/000_*` and `docs/PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md`.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
Deliver verified video media to destination platforms via Pillar 0's `DestinationPlatform` port, record what happened **twice** (what we attempted, and what the destination platform shows), and reconcile the two into an immutable, durable, append-only ledger that survives deletions of pipelines, sources, or destinations (`INV-4`).

### What This Pillar Owns
- The `delivery` entity: Canonical record of one `(catalog_video_id × destination_channel_id)` pair, with both-sided IDs (`source_video_id` and `destination_video_id`) and status (`PENDING`, `IN_FLIGHT`, `DELIVERED_SUCCESS`, `FAILED_PERMANENT`, `REMOVED`).
- The `delivery_attempt` entity: Append-only immutable log of every attempt, duration, bytes uploaded, and error details.
- The `destination_inventory` entity: Observed state of videos present on the target channel, populated by channel inventory sync.
- The **Reconciliation Engine**: Comparing internal ledger against external channel inventory, classifying into the 4 canonical states:
  1. `claimed_ok`: We uploaded it, marker matches, video is present.
  2. `unclaimed_present`: Video exists on channel without a matching replication marker. Flagged for review; never silently adopted (`INV-8`).
  3. `missing_expected`: Ledger says delivered, but video is missing on channel (deleted remotely).
  4. `marker_mismatch`: Video ID exists but provenance marker points to another source/video.
- Provenance Marker Parsing: Parsing the `<!-- YTR:src={source_id}:vid={source_video_id} -->` marker from destination descriptions.
- The **"Reconcile Before Retry"** rule: If an upload is interrupted or crashes mid-flight, reconcile against destination inventory before retrying to prevent duplicate uploads.
- The Delivery Ledger Batch Query API (`ADJ-P1-02`): Serving `get_delivered_video_ids(source_id, destination_id)` for high-performance UI rendering.
- Terminal Delivery Status Helper (`ADJ-P5-01`): Serving `are_all_pipeline_destinations_terminal(catalog_video_id, pipeline_id)` for storage retention pruning.

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- ❌ **NEVER makes direct HTTP calls to YouTube API**: Reaches YouTube strictly through Pillar 0's `DestinationPlatform` port adapter in Pillar 2.
- ❌ **NEVER downloads or modifies media files**: Media acquisition and hash validation belongs to Pillar 5 (`05_MEDIA_AND_STORAGE`).
- ❌ **NEVER deletes physical media files**: Storage retention evaluation and file unlinking belongs to Pillar 5 (`05_MEDIA_AND_STORAGE`).
- ❌ **NEVER calculates quota budgets**: Asks Pillar 2's adapter; does not compute quota math.
- ❌ **NEVER drops delivery records via cascade delete**: History is immutable and permanent (`INV-4`).

---

## 2. Invariants & Non-Negotiable Guards

| Invariant | Rule | Enforcement Mechanism |
|---|---|---|
| **INV-1** | **One successful delivery per video × destination** | PostgreSQL unique partial index: `UNIQUE (catalog_video_id, destination_channel_id) WHERE status = 'DELIVERED_SUCCESS'`. |
| **INV-2** | **Reconcile before retry** | Interrupted uploads must query destination channel inventory before initiating another upload attempt. |
| **INV-4** | **Ledger durability & no cascade delete** | Foreign keys on `delivery` use `ON DELETE RESTRICT` or `ON DELETE SET NULL`. Removing a pipeline or source never destroys delivery history. |
| **INV-8** | **Unclaimed inventory flagged** | Videos found on destination channels without a matching provenance marker are marked `unclaimed_present`; never automatically claimed. |
| **INV-11** | **Port & Adapter encapsulation** | External consumers interact with the ledger exclusively via `<delivery>.api` using frozen DTOs (`INV-12`). |

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `00` | `00_PILLAR_OVERVIEW.md` | `locked` | Mission, boundaries, Delivery Universe & Reconciliation Model |
| `01` | `01_FRONTEND_SPEC.md` | `locked` | Delivery ledger grid, reconciliation review console, CSV export |
| `02` | `02_WORKSPACE_AND_TENANCY_SLOT.md` | `scaffolded` | Multi-tenancy isolation |
| `03` | `03_INTERFACE_CONTRACT.md` | `locked` | Published `<delivery>.api`, DeliveryDTO, batch APIs (ADJ-P1-02/P5-01) |
| `04` | `04_LOGIC_AND_RULES.md` | `locked` | Delivery flow, reconcile-before-retry (INV-2), batch SQL queries |
| `05` | `05_DATA_MODEL.md` | `locked` | PostgreSQL schema (`delivery`, `delivery_attempt`, `destination_inventory`) |
| `06` | `06_FAILURES_AND_ERRORS.md` | `locked` | Interrupted upload recovery, duplicate prevention, remote deletion |
| `07` | `07_OBSERVABILITY_AND_AUDIT.md` | `locked` | Prometheus delivery metrics, reconciliation mismatch alerts |
| `08` | `08_TESTS_AND_DOD.md` | `locked` | Reconcile-before-retry tests, INV-1 uniqueness tests, no-cascade tests |
| `09` | `09_LEGACY_TRACEABILITY.md` | `scaffolded` | Anchors: F-11, F-24, F-25, F-50; defects D-04, D-06, D-13, D-14 |
| `10` | `10_OPEN_QUESTIONS.md` | `scaffolded` | Fuzzy metadata matching, AI transformer |
| `11` | `11_DECISIONS.md` | `scaffolded` | Local architectural decisions (P6-D##) |

**Current Active Frontier:** Authoring chapters `00` through `08`.
