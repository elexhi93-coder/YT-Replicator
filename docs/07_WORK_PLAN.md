# 07 — Work Plan

**Project:** YT-Replicator · **Status:** Draft · **Depends on:** `04`, `06`

Session-sized work units, in dependency order. **Each unit touches exactly one
module.** This file is the practical expression of INV-11: it is what keeps a
session's reading load small and its change isolated.

---

## 0. Status

Updated at the end of every unit. A unit is only listed once its §4 checklist
holds.

| Unit | State | Evidence |
|---|---|---|
| **U00** | **complete** | commits `8b3e5d8` (`.gitignore`, `LEGACY.md`), `f5bef8d` (docs), `434b21d` (legacy archive). 244 tracked files, working tree clean, zero forbidden paths in the index, and no token pattern in any committed file. |
| **U01** | **complete** | `core/settings.py` (documented defaults + `APP_SETTING_DEFAULTS`), contract clock (`quota_day`, `get_pacific_time`, `get_pacific_date_string`, DST tests for 2026-03-08/2026-11-01), `is_safe_ssrf_url`, `resolve_safe_path` fixed to contract §3.3 order, Pillar 0 ports + DTOs + §8 errors in `core.api`. 46 tests green; `CONTRACT.md` §1.1/§2.1 updated; `04` §6 rows added. |
| **U02** | **complete** | Identity + tenant scope: `accounts/models.py` (`workspace`, `workspace_member` + unique/check constraints), migrations `0001_initial` + `0002_default_workspace` (idempotent seed), `accounts/api.py` (single access helper `current_workspace`, `require_role` role gate, `role_required` view decorator), `tests/django_settings.py` + `tests/test_urls.py` (test-only Django harness), 18 module tests + boundary/size guards green, `accounts/CONTRACT.md` published, `04` §6 row added. |
| **U03** | **complete** | Project shell (commit `3260684`): `ui/urls.py` (named routes `home`/`healthz`/`login`/`logout`), `ui/views.py` (login-gated Home placeholder + unauthenticated 200/503 liveness probe), `ui/nav.py` (data-driven `NAV`, `visible_nav`, `all_nav_labels`), `ui/context_processors.py` (`workspace`/`nav_groups`/`user_role`), `base.html` four blocks + Tailwind/HTMX CDN, `ui/settings.py` (PostgreSQL, fail-fast secret, secure sessions), `manage.py` + `ui/wsgi.py`, `ui/CONTRACT.md`, `04` §6 row added. 74 tests green (shell + boundary/size guards). |
| U04–U25 | not started | — |

**Next unit: U04 — enforcement.**

> Security note carried from U00: a credential export containing 22 OAuth
> refresh tokens sits in `project003_bundle/docs/Export-Import/` and is excluded
> by `.gitignore`. It has never been committed. See `LEGACY.md` rule 5.

---

## 1. How to use this file

1. Pick the next unfinished unit from the table.
2. Read, in this order: **the unit's row** → **that module's `CONTRACT.md`** →
   **the one section of `03_DATABASE_SCHEMA.md` it needs** → **its tests**.
3. Do **not** read `00`–`06` end to end. They are reference, not the session's
   input. A unit should need at most a few hundred lines of context to build.
4. Implement → test → update `CONTRACT.md` → run the boundary tests → verify §4.
5. **Stop at the unit boundary.** Do not start the next unit in the same session.

If you are running low partway through: finish at the last step that is still
correct. Every unit boundary is chosen to be shippable, so stopping between
units costs nothing.

---

## 2. Sizing rules

| Size | Definition |
|---|---|
| **S** | One screen of code, one test file, one `CONTRACT.md`. Comfortable in a short session. |
| **M** | The unit a normal session should aim for: a coherent feature, its tests, its contract. |
| **L** | Too big for one sitting. **Split it before starting** — see `media` below. |

A unit that would span two modules is **split before it starts**: write the
interface first, add a row to `04` §6, then run two units. There is no fourth
option, and "I'll just touch this other file" is how `app.py` reached 7 000
lines.

---

## 3. Work units

### Wave 0 — foundation

| ID | Module | What it delivers | Depends on | Size |
|---|---|---|---|---|
| **U00** | — | **Repository hygiene.** `.gitignore`, first clean commit, `LEGACY.md` marking `project003_bundle/` read-only. | — | S |
| **U01** | `core` | Settings with documented defaults, quota-day clock (Pacific), typed errors, logging, path-safety guard, SSRF allow-list. | U00 | S |
| **U02** | `accounts` | Workspace, membership, the single access helper, login required, role check. | U01 | S |
| **U03** | `ui` | Project shell: Django project, `urls.py`, `base.html` with the four blocks, data-driven `NAV`, context slot, `/healthz`. | U02 | S |
| **U04** | — | **Enforcement.** `import-linter` contracts, `test_module_boundaries.py`, `test_module_size.py` (600-line cap). | U01–U03 | S |

**U00 first, always.** It is minutes of work and it prevents secrets, the live
database and the legacy archive from entering history — which is expensive to
undo afterwards.

### Wave 1 — configuration domain (no external calls)

| ID | Module | What it delivers | Depends on | Size |
|---|---|---|---|---|
| **U05** | `credentials` | Google client CRUD, encrypted secret, OAuth start/complete, token health and refresh, client → channel binding. | U02 | M |
| **U06** | `pipelines` | Pipeline CRUD with `draft → active → paused`, sources and destinations per pipeline, download profile, **missing-videos query**. | U02 | M |
| **U07** | `sources` | Add source with SSRF guard and URL normalisation, flat scan (metadata only), lazy hydrate with rate-limit discipline, catalog upserts. | U02 | M |
| **U08** | `jobs` | Enqueue with dedup check, **atomic claim**, state machine, transient/permanent classification, backoff, skip reasons. | U01, U02 | M |

U08 is the correctness keystone: everything downstream trusts its claim and its
error classification.

### Wave 2 — delivery truth and media

| ID | Module | What it delivers | Depends on | Size |
|---|---|---|---|---|
| **U09** | `youtube` | Token refresh, inventory sync, resumable upload with progress, thumbnail set, quota accounting, typed error translation. | U05 | M |
| **U10** | `delivery` | `delivery` + `delivery_attempt`, `deliver()` with marker injection, `reconcile()` and its four outcomes, mark-as-removed. | U08, U09 | M |
| **U11** | `media` | Storage roots with free-space floor, `acquire` (download → verify → atomic rename), hygiene for partials and orphans. | U01 | M |
| **U12** | `media` | **Retention evaluator**: four modes, gate order, dry run, two-phase delete, pin and unpin, `media_event`. | U11 | M |
| **U13** | `media` | Rehydrate (including cold-root relabel without downloading), star-as-pin, `archive_offline` handling. | U11, U12 | S |

`media` is split into three units deliberately (U11–U13): together they would be
`L`, which by §2 must be split before it starts.

### Wave 3 — orchestration and operations

| ID | Module | What it delivers | Depends on | Size |
|---|---|---|---|---|
| **U14** | `worker` | Run loop, dispatch by intent, gate evaluation for quota/disk/operator, restart-recovery pass. | U08, U10, U11 | M |
| **U15** | `ops` | `audit_event`, `worker_heartbeat`, log tail from files, purge command with a dry run, the backup rule. | U01, U02 | S |

### Wave 4 — UI, one page at a time

Each page is a thin layer over services that are already tested, which is why
these come last and are small.

| ID | Module | What it delivers | Depends on | Size |
|---|---|---|---|---|
| **U16** | `ui` | Credentials: client list, connect and reconnect, token health, per-client cap. | U05, U03 | S |
| **U17** | `ui` | Sources and Catalog: add, rescan, filters, star, ignore, enqueue with quota badge, mark-uploaded, CSV, *new since last scan*. | U07, U06, U08 | M |
| **U18** | `ui` | Pipelines: list and detail, activate/pause, download profile, retention settings, **missing-videos preview**. | U06 | M |
| **U19** | `ui` | Queue: SSE live list, failure buckets, pause, resume, retry, cancel, skip reasons on every row. | U08, U14 | M |
| **U20** | `ui` | History: deliveries and attempts, filters, reconcile report with its four outcomes, export and import CSV. | U10 | M |
| **U21** | `ui` | Library: media-state filters, header counters, rehydrate one or bulk, pin and unpin. | U11, U12, U13 | M |
| **U22** | `ui` | Home and Settings: heartbeats, quota left, free disk, queue depth, storage roots, app settings. | U15, U01 | M |

### Wave 5 — integration and closure

| ID | Module | What it delivers | Depends on | Size |
|---|---|---|---|---|
| **U23** | — | Compose (`web`, `worker`, `db`), migration as a one-shot step, healthchecks, volumes, backup script. | all waves | M |
| **U24** | — | **End-to-end smoke test:** one real source, one real destination — scan → backfill → deliver → reconcile → retention dry run. | U01–U23 | M |
| **U25** | — | **Documentation reconciliation:** bring `00`–`07` in line with the code, record every interface change, close the decisions register. | all | S |

**U24 is the proof.** It exercises the one path that matters: a source is
catalogued, missing videos are delivered, reconciliation agrees with reality, and
retention deletes nothing by default. Everything else supports that sentence.

**U25 closes the loop the legacy never closed** — its documents and code
disagreed inside a single release (D-01, D-27). The rule from `03` §1 is that a
change is incomplete until the documentation moved with it; this unit is the
final sweep that verifies it.

---

## 4. Definition of done

A unit is done when every box holds. These are objective, and none of them
require re-reading the whole project.

- [ ] **Only files in the target module changed**, plus that module's tests and
      `CONTRACT.md`. If not, an interface change was recorded in `04` §6 — or a
      boundary violation was fixed.
- [ ] The module's tests pass, **and** `test_module_boundaries` and
      `test_module_size` pass.
- [ ] No file in the module exceeds 600 lines.
- [ ] No URL is hardcoded anywhere in the change.
- [ ] No import of a sibling module except `<sibling>.api`.
- [ ] `CONTRACT.md` lists every new or changed public function, its errors, and
      the tests that cover it.
- [ ] If a model changed: `03_DATABASE_SCHEMA.md` was updated in the same
      change.
- [ ] The behaviour is observable — a test asserts it, or it is visible in the
      UI, or it is recorded in an audit or media event.
- [ ] No secret, database file, media file or legacy archive was added to git.

---

## 5. Session protocol

1. **Name the unit first.** Say `U08`, then read its row. If the row names two
   modules, stop — split it before writing any code.
2. Read only the four things from §1.
3. Write the smallest change that satisfies §4.
4. Run: the module's tests, `test_module_boundaries`, `test_module_size`.
5. Update `CONTRACT.md`; add an `04` §6 row if a published interface changed.
6. Report: what changed, what is next, anything that blocked.
7. **Stop.** The next unit belongs to the next session.

A session that ends with a green `07` §4 checklist is a complete session, even if
it produced only one small function.

---

## 6. Why this order

| Ordering choice | Reason |
|---|---|
| U00 before anything | Minutes of work now; a rewritten history later is not recoverable. |
| U01–U04 before any feature | The enforcement tests must exist **before** modules do, or the modular rule is a wish rather than a check. |
| U08 before U09–U14 | Claiming and error classification are what everything downstream trusts. Build them early, build them with tests. |
| UI last | By then each service is tested, so a page is a thin, safe, low-context change. |
| U24 near the end | It needs everything, and it is the sentence the whole system must be able to say. |
| U25 last | Documents and code reconciled in one deliberate pass, not assumed throughout. |

**Failure mode to avoid:** starting at U16 because UI work feels productive. A
page written before its services exist has nothing to be tested against, and the
session ends up editing four modules — the exact outcome `INV-11` exists to
prevent.