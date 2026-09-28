# Pillar 3 — Pipelines & Routing

**Status:** `scaffolded`.
**Chapters:** twelve files, per `_STANDARD/CHAPTER_STANDARD.md`.
**Depends on:** Pillar 0 (contracts), Pillar 1 (catalog), Pillar 2 (destinations).

---

## 1. Mission

Turn a catalog into a **decided, explainable candidate set** — which videos, for
which destinations, in which order, and why anything was skipped.

## 2. Owns

- The `pipeline` entity and its lifecycle (`draft → active → paused`).
- `pipeline_source` (the reusable many-to-many link, with mode, priority, daily
  cap and the **backfill cursor**) and `pipeline_destination` (enabled, priority,
  privacy override).
- The `download_profile` entity: resolution cap, container, codecs, subtitles,
  thumbnail, skip-shorts / skip-live.
- The candidate rule of v1 (D14): **all sources of a pipeline deliver to all its
  enabled destinations.**
- The *missing videos* preview — what would be delivered, shown before anything
  is downloaded.
- Retention settings per pipeline, defaulting to `keep` (D1), and the
  provenance-marker toggle (D2).
- The skip reasons: `ignored`, `unavailable`, `already_delivered`, `quota_full`.

## 3. Does not own

| Not owned here | Owner |
|---|---|
| Executing a download or upload | Pillar 6 (`06_DELIVERY_AND_LEDGER`) via Pillar 4 |
| The queue and its retries | Pillar 4 (`04_JOB_ENGINE`) |
| Whether the destination actually has the video | Pillar 6 (`06_DELIVERY_AND_LEDGER`) |
| Token validity | Pillar 2 (`02_DESTINATIONS_AND_AUTH`) |
| Media retention *evaluation* | Pillar 5 (`05_MEDIA_AND_STORAGE`) — this pillar stores the policy, Pillar 5 applies it |

## 4. Dependencies

Reads from: Pillars 1, 2. Written to by: the operator (UI), and read by Pillars
4 and 6 when they decide what a job means. **This pillar decides; it never
executes.** Routing rules as a feature are parked (`F-28`, v2) — v1 has one rule.

## 5. Invariants this pillar protects

`INV-5` (nothing enqueued for an already-delivered pair), `INV-9` (a source feeds
several pipelines), and the resumability half of `docs/05` §3 — the cursor is a
timestamp, so a crash costs nothing. It also carries the *policy* half of `INV-6`
(retention reproducible from the database alone).

## 6. Chapter plan

| Chapter | Status |
|---|---|
| `00_PILLAR_OVERVIEW.md` | **locked** — mission, boundaries, candidate universe, skip-reason taxonomy |
| `01_FRONTEND_SPEC.md` | **locked** — pipeline list, editor tabs, Candidate Preview dry-run drawer |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | scaffolded |
| `03_INTERFACE_CONTRACT.md` | **locked** — published `<pipelines>.api`, candidate DTOs, skip reason enums |
| `04_LOGIC_AND_RULES.md` | **locked** — candidate generation algorithm, INV-5 deduplication, cursor rules |
| `05_DATA_MODEL.md` | **locked** — PostgreSQL schema (`pipeline`, `pipeline_source`, `pipeline_destination`, `download_profile`) |
| `06_FAILURES_AND_ERRORS.md` | **locked** — error taxonomy, broken bindings, skip explainability loop |
| `07_OBSERVABILITY_AND_AUDIT.md` | **locked** — Prometheus metrics, candidate throughput, audit events |
| `08_TESTS_AND_DOD.md` | **locked** — INV-5 deduplication tests, INV-9 multi-cursor tests, AST isolation |
| `09_LEGACY_TRACEABILITY.md` | scaffolded — anchors: `F-01`, `F-03`, `F-04`, `F-06`, `F-14`, `F-16`, `F-17`, `F-28` (parked), `F-40` (parked); defects `D-02`, `D-03`, `D-04`, `D-27` |
| `10_OPEN_QUESTIONS.md` | scaffolded |
| `11_DECISIONS.md` | scaffolded |

## 7. Next action

Not yet — wait for Pillar 0 to be locked.
