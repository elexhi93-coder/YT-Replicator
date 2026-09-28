# 000 — Pillar 3 Instructions & Working Frontier (Pipelines & Routing)

**Pillar:** 3 — Pipelines & Routing  
**Status:** `drafting`  
**Authority:** Local domain directive for Pillar 3. Governed by `docs/000_*` and `docs/PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md`.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
Turn a catalog of discovered source videos into a **decided, explainable candidate set** — deciding which videos replicate to which destinations, in which order (backfill oldest-first vs monitor newest-first), under which download profile and retention policies, and explaining why any candidate was skipped — without ever executing downloads or uploads.

### What This Pillar Owns
- The `pipeline` entity and its lifecycle (`DRAFT` → `ACTIVE` → `PAUSED` → `ARCHIVED`).
- `pipeline_source`: Reusable M:N binding of sources to pipelines, tracking synchronization mode (`BACKFILL`, `MONITOR`, `BOTH`), priority, daily rate cap, and the **backfill cursor** (`backfill_cursor_published_at`).
- `pipeline_destination`: Binding of destinations to pipelines with enabled toggles, priority, and channel-level privacy overrides (`public`, `unlisted`, `private`).
- The `download_profile` entity: Resolution caps (720p, 1080p, 1440p, 2160p), container preferences (`mp4`, `mkv`), audio bitrate, subtitle languages, thumbnail inclusion, and content exclusion filters (`skip_shorts`, `skip_live_streams`).
- The candidate generation query: Calculating missing replication candidates `(source_video_id, destination_channel_id)` by cross-referencing catalog inventory with Pillar 6 ledger records (`INV-5`).
- The canonical candidate explanation model: Answering for every catalog video why it was either selected or skipped (`ALREADY_DELIVERED`, `IGNORED_BY_FILTER`, `SOURCE_UNAVAILABLE`, `SHORTS_FILTERED`, `LIVE_FILTERED`, `QUOTA_EXHAUSTED`).
- Retention policy definitions per pipeline (`KEEP`, `DELETE_AFTER_UPLOAD`, `PURGE_AFTER_7_DAYS`).

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- ❌ **NEVER downloads or modifies media**: Handled exclusively by Pillar 5 (`05_MEDIA_AND_STORAGE`).
- ❌ **NEVER uploads media or refreshes tokens**: Handled exclusively by Pillar 2 (`02_DESTINATIONS_AND_AUTH`).
- ❌ **NEVER executes or retries jobs**: Handled exclusively by Pillar 4 (`04_JOB_ENGINE`) and Pillar 6 (`06_DELIVERY_AND_LEDGER`).
- ❌ **NEVER writes delivery ledger records**: Handled exclusively by Pillar 6 (`06_DELIVERY_AND_LEDGER`).
- ❌ **NEVER crawls external sources**: Handled exclusively by Pillar 1 (`01_SOURCES_AND_CATALOG`).

---

## 2. Invariants & Non-Negotiable Guards

| Invariant | Rule | Enforcement Mechanism |
|---|---|---|
| **INV-5** | **No re-enqueue of delivered pairs** | A candidate pair `(catalog_video_id, destination_channel_id)` is NEVER marked as an actionable candidate if a successful delivery receipt exists in Pillar 6 ledger. |
| **INV-6** | **Retention policy reproducibility** | Retention policy is defined deterministically per pipeline in the database, allowing Pillar 5 to evaluate cleanup without hidden state. |
| **INV-9** | **Source multi-tenancy** | A single `source` may feed multiple independent pipelines without state conflict. Cursor states are tracked on `pipeline_source`, NOT on the `source` entity. |
| **INV-11** | **Port & Adapter encapsulation** | External consumers query candidates solely via `<pipelines>.api` using frozen DTOs (`INV-12`). |

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `00` | `00_PILLAR_OVERVIEW.md` | `locked` | Mission, boundaries, Candidate Universe & Skip Reason Taxonomy |
| `01` | `01_FRONTEND_SPEC.md` | `locked` | Pipeline list, editor tabs, Candidate Preview dry-run drawer |
| `02` | `02_WORKSPACE_AND_TENANCY_SLOT.md` | `scaffolded` | `workspace_id` scoping |
| `03` | `03_INTERFACE_CONTRACT.md` | `locked` | Published `<pipelines>.api`, candidate DTOs, skip reason enums |
| `04` | `04_LOGIC_AND_RULES.md` | `locked` | Candidate generation algorithm, INV-5 deduplication, cursor rules |
| `05` | `05_DATA_MODEL.md` | `locked` | PostgreSQL schema (`pipeline`, `pipeline_source`, `pipeline_destination`, `download_profile`) |
| `06` | `06_FAILURES_AND_ERRORS.md` | `locked` | Error taxonomy, broken bindings, skip explainability loop |
| `07` | `07_OBSERVABILITY_AND_AUDIT.md` | `locked` | Prometheus metrics, candidate throughput, audit events |
| `08` | `08_TESTS_AND_DOD.md` | `locked` | INV-5 deduplication tests, INV-9 multi-cursor tests, AST isolation |
| `09` | `09_LEGACY_TRACEABILITY.md` | `scaffolded` | Anchors: F-01, F-03, F-04, F-06, F-14, F-16, F-17 |
| `10` | `10_OPEN_QUESTIONS.md` | `scaffolded` | Parked routing rules (`F-28`), dynamic tag rewriting |
| `11` | `11_DECISIONS.md` | `scaffolded` | Local architectural decisions (P3-D##) |

**Current Active Frontier:** Authoring `00_PILLAR_OVERVIEW.md` through `08_TESTS_AND_DOD.md` in complete detail.
