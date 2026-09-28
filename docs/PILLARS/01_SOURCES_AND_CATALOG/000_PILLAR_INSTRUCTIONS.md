# 000 — Pillar 1 Instructions & Working Frontier (Sources & Catalog)

**Pillar:** 1 — Sources & Catalog  
**Status:** `drafting`  
**Authority:** Local domain directive for Pillar 1. Governed by `docs/000_*` and `docs/PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md`.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
Discover, validate, and catalog everything exposed by a content source (channel, playlist) and provide rich operator browsing/filtering/tagging capabilities — **without ever downloading media bytes**.

### What This Pillar Owns
- Source definition (`source` entity): YouTube channel or playlist we read from.
- Catalog items (`catalog_video` entity): metadata discovered for every video.
- Source URL parsing, validation, and SSRF allow-list enforcement.
- Discovery scanning (`extract_flat=True`) and sync status per source.
- Lazy hydration of rich metadata (`description`, `tags`, view/like counts) with strict rate discipline.
- Catalog operator surfaces: search, filter, star, ignore, mark-as-already-uploaded, and CSV export/import.
- Partial-failure resilience (`F-48`): skipped items never abort a source scan.

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- ❌ **NEVER downloads video or audio files**: That is owned exclusively by Pillar 5 (`05_MEDIA_AND_STORAGE`). A scan that downloads violates `INV-7`.
- ❌ **NEVER decides routing or download triggers**: That is owned by Pillar 3 (`03_PIPELINES_AND_ROUTING`).
- ❌ **NEVER schedules or claims execution jobs**: That is owned by Pillar 4 (`04_JOB_ENGINE`).
- ❌ **NEVER interacts with destination channels or upload records**: That is owned by Pillar 2 (`02_DESTINATIONS_AND_AUTH`) and Pillar 6 (`06_DELIVERY_AND_LEDGER`).

---

## 2. Invariants & Non-Negotiable Guards

| Invariant | Rule | Enforcement Mechanism |
|---|---|---|
| **INV-7** | **Scanning never downloads** | Enforced by static boundary test: `sources` module has no import or call to download engines (`yt-dlp` download flags or file writes). |
| **INV-9** | **Source reusability across pipelines** | A source is defined once in `sources` and linked to N pipelines via `pipeline_source` join table (`D-02` fix). |
| **INV-5** | **Delivery deduplication guard** | Catalog views and scan discovery check ledger history before proposing work. |
| **F-48** | **Partial-failure tolerance** | An unavailable, private, or geo-blocked video during a scan is logged as skipped; the scan proceeds. |

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `00` | `00_PILLAR_OVERVIEW.md` | `drafting` | Mission, boundaries, invariants, YouTube Field Universe |
| `01` | `01_FRONTEND_SPEC.md` | `drafting` | Sources list, add-source modal, catalog grid, video drawer |
| `02` | `02_WORKSPACE_AND_TENANCY_SLOT.md` | `scaffolded` | `workspace_id` scoping for `source` and `catalog_video` |
| `03` | `03_INTERFACE_CONTRACT.md` | `drafting` | Published `<sources>.api` functions |
| `04` | `04_LOGIC_AND_RULES.md` | `drafting` | Flat scan, lazy hydration, rate discipline, SSRF checks |
| `05` | `05_DATA_MODEL.md` | `drafting` | PostgreSQL schema mappings for `sources` and `catalog_video` |
| `06` | `06_FAILURES_AND_ERRORS.md` | `drafting` | Error classification: transient vs permanent vs skip (F-48) |
| `07` | `07_OBSERVABILITY_AND_AUDIT.md` | `drafting` | Fleet health, domain events, database auditability |
| `08` | `08_TESTS_AND_DOD.md` | `drafting` | Boundary tests, SSRF tests, F-48 test, DoD checklist |
| `09` | `09_LEGACY_TRACEABILITY.md` | `scaffolded` | Traceability for F-02, F-05, F-08, F-10–13, F-36, F-45–48; D-02, D-07 |
| `10` | `10_OPEN_QUESTIONS.md` | `scaffolded` | Local design questions |
| `11` | `11_DECISIONS.md` | `scaffolded` | Local architectural decisions (P1-D##) |

**Current Active Frontier:** Pillar 1 Core Chapters Authored. Ready for Pillar 2 inception.

---

## 4. Leaf-Level Domain Universe (YouTube Ingestion Tiers)

To ensure backend queries and frontend columns are grounded in reality, this pillar catalogs YouTube attributes across 4 acquisition tiers:

1. **Tier 1 (RSS XML Feed)**: Instant, zero quota cost, newest 15 items, basic public metadata.
2. **Tier 2 (Fast Flat Scan - yt-dlp)**: Batch listing of full playlist/channel without downloading, medium metadata (title, id, duration, availability).
3. **Tier 3 (Hydrated yt-dlp / InnerTube)**: Rich metadata on demand (description, tags, chapters, high-res thumbnails, categories, view/like counts).
4. **Tier 4 (Official Data API v3)**: Quota-metered REST endpoint for strict verification when API keys are configured.

---

## 5. Local Open Questions & Blockers
- None currently blocking. Next task: document the complete YouTube Field Universe table in `00_PILLAR_OVERVIEW.md`.
