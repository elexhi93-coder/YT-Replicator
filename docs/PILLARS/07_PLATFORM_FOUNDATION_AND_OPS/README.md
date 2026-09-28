# Pillar 7 — Platform Foundation & Operations

**Status:** `scaffolded`.
**Chapters:** twelve files, per `_STANDARD/CHAPTER_STANDARD.md`.
**Depends on:** Pillar 0 (contracts). **Depended on by:** every other pillar.

---

## 1. Mission

Own the platform the domain stands on: the shared primitives, **who may act**,
**who is running**, **what happened**, and the shell all other pages render into.

## 2. Why this pillar exists

`docs/04` §2 defines **twelve** modules. Before this pillar, six had an owner and
six did not (`core`, `accounts`, `worker`, `ops`, `ui`, and `youtube` as an
adapter). Two concrete consequences forced the decision:

1. **Three pages, plus login, belonged to nobody.** `docs/04` §8.4 lists ten
   pages; Pillars 1–6 own seven of them. **Home**, **Settings** and **Ops (logs)**
   — plus the Login page `docs/04` §9 (D16) requires — had no pillar.
2. **The enforcement tests that make INV-11/INV-12 real are platform concerns.**
   `docs/07` U04 (`import-linter` contracts, `test_module_boundaries.py`,
   `test_module_size.py` — the 600-line cap) protects every module; it needs a
   home, and that home is not a domain pillar.

Keeping these inside Pillar 0 was considered and rejected: Pillar 0 is the
**contracts** layer — the ports and DTOs. Burying the shell, auth, workers and
operations inside it would make one pillar own six unrelated concerns and would
make the highway hard to read. That is the D-27 failure mode in miniature.

## 3. Owns (the five unowned modules)

| Module | What this pillar specifies |
|---|---|
| `core` | Settings with documented defaults; the **quota-day clock** (Pacific, D-03); the typed error hierarchy; structured logging; the media **path-safety** guard; the **SSRF allow-list**; and the **base types** that carry Pillar 0's DTOs and ports. |
| `accounts` | `workspace`, `workspace_member`, Django `auth_user`, login/logout, and **the single access helper**. No tenant features in v1 (D11). |
| `worker` | The run loop, dispatch by intent, gate evaluation (quota / disk / operator) and the restart-recovery pass. **Orchestration only — no business rules** (`docs/04` §2). |
| `ops` | `audit_event`, `worker_heartbeat`, health, log tail **from files** (never the Docker socket, D-05), maintenance commands (dry-run first), and the backup-before-maintenance rule (F-54). |
| `ui` shell | `base.html` with its four blocks, the data-driven `NAV`, the **workspace context slot**, named routes only, flash/toast, `/healthz`, and the platform pages below. |

## 4. Does not own

| Not owned here | Owner |
|---|---|
| The seven domain pages (Pipelines, Sources, Catalog, Queue, Library, History, Credentials) | Pillars 3, 1, 1, 4, 5, 6, 2 — this pillar owns the **shell** they render into |
| Business decisions about videos, sources, destinations | Pillars 1–3 |
| Queue semantics: states, claims, retries, classification | Pillar 4 (`04_JOB_ENGINE`) |
| Media bytes, verification, retention evaluation | Pillar 5 (`05_MEDIA_AND_STORAGE`) |
| Delivery truth and reconciliation | Pillar 6 (`06_DELIVERY_AND_LEDGER`) |
| The port definitions, DTOs and marker format | Pillar 0 — `core` carries the base types that express them |
| The YouTube platform adapter | Pillar 2 (`02_DESTINATIONS_AND_AUTH`) |

## 5. Dependencies

`core` imports **nothing** (`docs/04` §3). `accounts` → `core`. `ops` → `core`,
`accounts`. `worker` → `jobs`, `media`, `delivery`. **Nothing imports `ui` or
`worker`** — they are leaves. This pillar is the one place where "no cycles, ever"
is the whole point, because every module sits above it.

## 6. Invariants this pillar protects

`INV-11` / `INV-12` (the enforcement tests live in U04), `D16` (auth on every
page, CSRF on every mutation), `D17` (context slot, data-driven nav, named routes,
one access helper), and `P15` (never discard recoverable work → restart
recovery). It is also where `D-05` (no Docker socket, ever), `D-12`/`D-25`
(`.gitignore` from the first commit) and `D-19` (PostgreSQL, never four processes
on one SQLite file) are structurally refused.

## 7. Chapter plan

| Chapter | Status | Notes |
|---|---|---|
| `00_PILLAR_OVERVIEW.md` | **locked** — mission, 5 unowned modules, Platform Universe |
| `01_FRONTEND_SPEC.md` | **locked** — universal shell (base.html), Home cockpit, Login, Settings, Ops logs |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | scaffolded |
| `03_INTERFACE_CONTRACT.md` | **locked** — published `<core>.crypto`, `<core>.clock`, `<core>.security`, `<ops>.api` |
| `04_LOGIC_AND_RULES.md` | **locked** — AES-256-GCM cipher (ADJ-P2-01), worker run loop, Pacific clock rollover |
| `05_DATA_MODEL.md` | **locked** — PostgreSQL schema (`workspace`, `workspace_member`, `audit_event`, `app_setting`) |
| `06_FAILURES_AND_ERRORS.md` | **locked** — auth failures, dead workers, disk floors, cipher errors |
| `07_OBSERVABILITY_AND_AUDIT.md` | **locked** — centralized audit trail, logging, Prometheus metrics, /healthz |
| `08_TESTS_AND_DOD.md` | **locked** — boundary linter tests (U04), 600-line limit tests, crypto tests |
| `09_LEGACY_TRACEABILITY.md` | scaffolded | anchors: `F-29`, `F-30`, `F-54`; defects `D-05`, `D-12`, `D-16`, `D-19`, `D-25`, `D-26` |
| `10_OPEN_QUESTIONS.md` | scaffolded | |
| `11_DECISIONS.md` | scaffolded | |

## 8. Next action

Not yet — Pillar 0 must be locked first. When it is, this pillar is the **second**
to be written, because every other pillar's chapters will cite its access helper,
its clock and its error hierarchy.
