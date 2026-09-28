# Pillar 1 — Sources & Catalog

**Status:** `scaffolded`.
**Chapters:** twelve files, per `_STANDARD/CHAPTER_STANDARD.md`.
**Depends on:** Pillar 0 (contracts).

---

## 1. Mission

Discover what a source exposes, hold that metadata as a catalog, and let the
operator act on it — **without ever downloading a video**.

## 2. Owns

- The `source` entity: a channel or playlist we read from, and never upload to.
- The `catalog_video` entity: metadata for every video a source exposes.
- URL parsing, normalisation and the SSRF allow-list for source URLs.
- Flat scanning (`extract_flat`) and the scan status per source.
- Lazy hydration of expensive fields, with its rate-limit discipline.
- Catalog operator actions: filter, star, ignore, mark-as-already-uploaded,
  CSV export/import, and the *new since last scan* diff.

## 3. Does not own

| Not owned here | Owner |
|---|---|
| Whether a video should be downloaded or uploaded | Pillar 3 (`03_PIPELINES_AND_ROUTING`) |
| Queueing work | Pillar 4 (`04_JOB_ENGINE`) |
| The media file itself | Pillar 5 (`05_MEDIA_AND_STORAGE`) |
| Destination history | Pillar 6 (`06_DELIVERY_AND_LEDGER`) |
| Credentials for reading a source | Pillar 2 (`02_DESTINATIONS_AND_AUTH`) — the one exception, since cookies and the PO-token sidecar are credential-shaped |

## 4. Dependencies

Reads from: Pillar 0 (ports). Written to by: Pillar 3 (the candidate set it
queries). Never calls Pillars 4, 5 or 6 — a scan that triggered a download would
break `INV-7`, which is this pillar's defining guard.

## 5. Invariants this pillar protects

`INV-7` (scanning never downloads), `INV-9` (a source is reusable across
pipelines — the fix for defect D-02), and the scanning half of `INV-5` (nothing
is enqueued for an already-delivered pair).

## 6. Chapter plan

| Chapter | Status |
|---|---|
| `00_PILLAR_OVERVIEW.md` | **drafting** — written; covers mission, boundaries, invariants, and YouTube Field Universe |
| `01_FRONTEND_SPEC.md` | **drafting** — written; sources list, add-source modal, catalog grid, inspector drawer |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | scaffolded |
| `03_INTERFACE_CONTRACT.md` | **drafting** — written; published `<sources>.api` boundary, DTOs, sibling access matrix |
| `04_LOGIC_AND_RULES.md` | **drafting** — written; flat scan, lazy hydration, rate discipline, SSRF checks, F-48 resilience |
| `05_DATA_MODEL.md` | **drafting** — written; PostgreSQL schema for `sources` and `catalog_video` |
| `06_FAILURES_AND_ERRORS.md` | **drafting** — written; transient / permanent / skip (F-48) taxonomy, error UI |
| `07_OBSERVABILITY_AND_AUDIT.md` | **drafting** — written; domain events, fleet health metrics, database auditability |
| `08_TESTS_AND_DOD.md` | **drafting** — written; boundary tests, SSRF tests, F-48 test, DoD checklist |
| `09_LEGACY_TRACEABILITY.md` | scaffolded — anchors: `F-02`, `F-05`, `F-08`, `F-10`–`F-13`, `F-36`, `F-45`–`F-48`; defects `D-02`, `D-07` |
| `10_OPEN_QUESTIONS.md` | scaffolded |
| `11_DECISIONS.md` | scaffolded |

## 7. Next action

Write `01_FRONTEND_SPEC.md` detailing all operator screens for Source management and Catalog exploration, followed by `04_LOGIC_AND_RULES.md` and `05_DATA_MODEL.md`.
defined there.
