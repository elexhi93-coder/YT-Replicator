# 000 — Pillar 5 Instructions & Working Frontier (Media & Storage)

**Pillar:** 5 — Media & Storage  
**Status:** `drafting`  
**Authority:** Local domain directive for Pillar 5. Governed by `docs/000_*` and `docs/PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md`.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
Be the **sole, exclusive owner of bytes on disk**: acquire media files via `yt-dlp` according to pipeline download profiles, verify file integrity and SHA-256 hashes before marking ready, safely place content in storage roots, evaluate retention policies deterministically (`INV-6`, `INV-10`), and delete media safely and once without race conditions.

### What This Pillar Owns
- The `storage_root` entity: Hot and cold roots, mount state, path resolution, and free-space floor enforcement (e.g. minimum 10 GB free required before admitting downloads).
- The `media_asset` entity: Canonical record of physical files on disk, size, format, SHA-256 hash, and lifecycle states (`EXPECTED` → `DOWNLOADING` → `ON_DISK` → `DELETED` / `ARCHIVE_OFFLINE`).
- The `media_event` append-only audit trail logging every download, verification, rename, and deletion.
- Acquisition via `yt-dlp`: Executing media extraction using parameters declared by Pillar 3's `download_profile` (resolution caps, format container).
- Two-phase file placement & verification: Download to `.part` file, calculate SHA-256 and size, verify integrity, and perform an **atomic rename** to final file path (`INV-3`).
- Storage hygiene: Automated background sweeping of orphaned `.part` files, aborted transfers, and temporary thumbnail rasters.
- The **Retention Evaluation Engine**: Evaluating declarative policies (`KEEP`, `DELETE_AFTER_UPLOAD`, `PURGE_AFTER_7_DAYS`) with mandatory dry-run support (`INV-10`), requiring all enabled destinations to reach terminal state before deletion (`INV-2`).
- Rehydration & Pinning: Re-downloading missing assets for existing catalog videos with explicit `pinned` flags preventing deletion.
- `ARCHIVE_OFFLINE` detection: Marking assets as offline if an external mount unmounts, preventing catastrophic re-download loops.

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- ❌ **NEVER uploads files or manages YouTube OAuth**: Handled exclusively by Pillar 2 (`02_DESTINATIONS_AND_AUTH`).
- ❌ **NEVER writes to the delivery ledger**: Handled exclusively by Pillar 6 (`06_DELIVERY_AND_LEDGER`).
- ❌ **NEVER schedules background tasks or manages worker queues**: Handled exclusively by Pillar 4 (`04_JOB_ENGINE`).
- ❌ **NEVER invents retention policies on the fly**: Evaluates solely the declarative policies stored by Pillar 3 (`INV-6`).
- ❌ **NEVER executes video re-encoding or FFmpeg transformations in v1**: Direct container acquisition only (Decision D15).
- ❌ **NO OTHER PILLAR TOUCHES THE FILESYSTEM**: All file I/O operations are strictly forbidden outside `src.media`.

---

## 2. Invariants & Non-Negotiable Guards

| Invariant | Rule | Enforcement Mechanism |
|---|---|---|
| **INV-2** | **Delete only when all enabled destinations terminal** | Retention engine cross-checks Pillar 6 ledger. Deletion is blocked if any enabled pipeline destination is pending or in-flight. |
| **INV-3** | **Zero partial or unverified uploads** | Upload handlers cannot read an asset unless its state is `ON_DISK` with confirmed SHA-256 and size > 0. Files are downloaded with temporary extensions and atomically renamed only after verification. |
| **INV-6** | **Retention policy reproducibility** | All retention decisions are 100% reproducible from PostgreSQL relational state. No hidden filesystem state. |
| **INV-7** | **Path Traversal & Safe Root Boundary** | All file read/write/delete operations must strictly resolve inside the configured `storage_root` directory. Relative path traversal (`../`) is rejected with security exceptions. |
| **INV-10** | **Centralized Deletion & Mandatory Dry-Run** | Single deletion choke-point in `src.media.retention`. Dry-run query is always available to preview what would be deleted without mutating disk. |
| **INV-11** | **Port & Adapter encapsulation** | External consumers interact with media assets exclusively through `<media>.api` using frozen DTOs (`INV-12`). |

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `00` | `00_PILLAR_OVERVIEW.md` | `locked` | Mission, boundaries, Storage Universe & Asset Lifecycle |
| `01` | `01_FRONTEND_SPEC.md` | `locked` | Storage health console, disk space gauges, retention dry-run UI |
| `02` | `02_WORKSPACE_AND_TENANCY_SLOT.md` | `scaffolded` | `workspace_id` isolation |
| `03` | `03_INTERFACE_CONTRACT.md` | `locked` | Published `<media>.api`, MediaAssetDTO, RetentionDryRunDTO |
| `04` | `04_LOGIC_AND_RULES.md` | `locked` | yt-dlp acquisition, atomic verification, 4 retention modes, safe path checks |
| `05` | `05_DATA_MODEL.md` | `locked` | PostgreSQL schema (`storage_root`, `media_asset`, `media_event`) |
| `06` | `06_FAILURES_AND_ERRORS.md` | `locked` | Disk floor, corrupt hash, unmounted drive, orphan sweeping |
| `07` | `07_OBSERVABILITY_AND_AUDIT.md` | `locked` | Storage capacity gauges, deletion audit logs, I/O latency |
| `08` | `08_TESTS_AND_DOD.md` | `locked` | Deletion safety tests, dry-run assertions, path-traversal tests |
| `09` | `09_LEGACY_TRACEABILITY.md` | `scaffolded` | Anchors: F-14, F-20, F-34, F-52, F-53; defects D-08, D-09, D-10 |
| `10` | `10_OPEN_QUESTIONS.md` | `scaffolded` | Cold archive migration, tiering |
| `11` | `11_DECISIONS.md` | `scaffolded` | Local architectural decisions (P5-D##) |

**Current Active Frontier:** Authoring chapters `00` through `08`.
