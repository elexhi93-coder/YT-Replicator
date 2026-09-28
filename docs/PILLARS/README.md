# The Book — Pillar Specifications (YT-Replicator)

**Status:** Scaffolded. Pillar 0 is the first chapter to be written.
**Governed by:** `docs/000_AI_SUPREME_PROTOCOL.md` (the Constitution).
**Companion:** `docs/000_AI_ARCHITECT_INSTRUCTIONS.md` (lore, frontiers, Idea Vault).

---

## 1. What this folder is

This is the **design book**. One folder per pillar. Each pillar is documented
from the **front-end screen down to the database column**, before any code is
written. The rule from the Constitution applies without exception:

> **No production code is written until the chapter that specifies it has been
> written, reviewed, and given a green light.**

`docs/00`–`07` remain the *reference* set (why the system is shaped this way).
The Book is the *specification* set (exactly what each pillar does, screen by
screen, function by function).

---

## 2. The shape: trunk → branches → leaves

| Level | Where | Meaning |
|---|---|---|
| **Trunk** | `docs/000_*`, `docs/00`–`07` | Constitution, principles, invariants, decisions, module map |
| **Branches** | one folder per pillar + its `README.md` | A pillar's mission, scope, interfaces, chapter plan |
| **Leaves** | the numbered chapter files inside a pillar | The actual specification, one concern per file |
| **Standard** | `_STANDARD/CHAPTER_STANDARD.md` | The fixed skeleton every leaf file must follow |

Every pillar chapter file uses the same twelve-section skeleton
(`_STANDARD/CHAPTER_STANDARD.md`), so all seven pillars read the same way and a
session never has to guess where to look.

---

## 3. The pillars

| # | Pillar | Mission in one line | Depends on |
|---|---|---|---|
| **0** | `00_INTER_PILLAR_CONTRACTS` | The highway: DTOs, ports, and the rules for how pillars talk | — |
| **1** | `01_SOURCES_AND_CATALOG` | Discover what exists at a source; hold metadata; never download in the scan path | 0 |
| **2** | `02_DESTINATIONS_AND_AUTH` | Authorise destination channels; hold encrypted credentials; own quota | 0 |
| **3** | `03_PIPELINES_AND_ROUTING` | Bind sources to destinations; own the cursor, the candidate set, and the settings | 0, 1, 2 |
| **4** | `04_JOB_ENGINE` | Hand out work safely: queue, atomic claim, state machine, retry policy | 0 |
| **5** | `05_MEDIA_AND_STORAGE` | The only owner of bytes on disk: acquire, verify, place, retain, remove | 0, 4 |
| **6** | `06_DELIVERY_AND_LEDGER` | Deliver one video to one destination; keep immutable, reconcilable truth | 0, 2, 4, 5 |
| **7** | `07_PLATFORM_FOUNDATION_AND_OPS` | Own the platform: `core`, `accounts`, `worker`, `ops`, the UI shell, and the platform pages (Home, Settings, Logs, Login) | 0 |

**Why Pillar 0 is separate from the other seven.** A pillar is a *replaceable*
part. Sources can be YouTube today and a video editor later. Destinations can be
YouTube today and Facebook later. Metadata can be copied verbatim today and
rewritten by AI later. None of that is possible unless the **contract** between
pillars is written down as its own artefact first — so it is Pillar 0, and it is
written first.

---

## 4. The fixed chapter set (same twelve leaves in every pillar)

| Chapter file | Specifies |
|---|---|
| `00_PILLAR_OVERVIEW.md` | Mission, scope in / scope out, dependencies, glossary slice |
| `01_FRONTEND_SPEC.md` | Screens, tabs, grids, filters, forms, buttons, states, feedback |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | Where `workspace_id` enters the screen and the query |
| `03_INTERFACE_CONTRACT.md` | The published `<module>.api`: inputs, outputs, errors |
| `04_LOGIC_AND_RULES.md` | Flows, state machines, guards, limits, edge cases, invariants touched |
| `05_DATA_MODEL.md` | Tables, columns, constraints, indexes this pillar owns |
| `06_FAILURES_AND_ERRORS.md` | Transient vs permanent, what the operator sees |
| `07_OBSERVABILITY_AND_AUDIT.md` | Events written, heartbeats, dry-run surfaces |
| `08_TESTS_AND_DOD.md` | The assertions that prove the chapter is implemented |
| `09_LEGACY_TRACEABILITY.md` | `F-##` kept/adapted/dropped, `D-##` defects this pillar refuses |
| `10_OPEN_QUESTIONS.md` | Parked, with the reasoning recorded |
| `11_DECISIONS.md` | Pillar-local decisions, numbered, with what they supersede |

A pillar may hold a chapter as "not applicable" with a one-line reason. It may
not silently omit one.

---

## 5. Status legend

| Status | Meaning |
|---|---|
| `scaffolded` | Folder and chapter plan exist; no content written |
| `drafting` | Chapters being written; open questions still open |
| `review` | Written; awaiting the architect's green light |
| `locked` | Approved; code may be written against it |
| `implemented` | Code exists and matches the locked chapter |
| `drifted` | Code and chapter disagree — **a defect**, fix both in one change |

---

## 6. How a session uses the Book

1. Read `docs/000_AI_SUPREME_PROTOCOL.md`, then
   `docs/000_AI_ARCHITECT_INSTRUCTIONS.md`.
2. Take the next pillar from §3 that is not `locked`.
3. Read that pillar's `README.md`, then `_STANDARD/CHAPTER_STANDARD.md`.
4. Write **one chapter** — not the whole pillar — and stop at the boundary.
5. Update the pillar `README.md` status and the Active Frontier in
   `docs/000_AI_ARCHITECT_INSTRUCTIONS.md`.

**Do not** read all eight pillars end to end. A chapter needs its pillar, the
standard, and the referenced sections of `docs/03` (schema) and `docs/00`
(invariants) — nothing else.

---

## 7. Module → pillar ownership map (all twelve modules of `docs/04` §2)

**Every module has exactly one owning pillar.** A chapter that needs another
module's internals is a boundary defect (INV-12), not a licence.

| Module | Pillar | Owns, in one line |
|---|---|---|
| `core` | **7** | settings, quota-day clock, error hierarchy, logging, path safety, SSRF guard — and the **base types** that carry Pillar 0's DTOs and ports |
| `accounts` | **7** | `workspace`, `workspace_member`, and the single access helper |
| `credentials` | **2** | Google client + channel tokens, encrypted at rest, token health |
| `sources` | **1** | `source`, `catalog_video`, scanning, hydration |
| `pipelines` | **3** | `pipeline`, `pipeline_source`, `pipeline_destination`, `download_profile` |
| `jobs` | **4** | the queue, atomic claims, the state machine, retries |
| `youtube` | **2** | the **v1 platform adapter** behind Pillar 0's Destination port (Q-2) |
| `delivery` | **6** | `delivery`, `delivery_attempt`, reconciliation, mark-as-removed |
| `media` | **5** | `storage_root`, `media_asset`, `media_event`, retention |
| `worker` | **7** | the run loop only — **no business rules** |
| `ops` | **7** | `audit_event`, `worker_heartbeat`, health, logs, purge |
| `ui` | **7** (shell) + 1–6 (their pages) | routes and templates; publishes no Python API |

**The one intentional split.** `ui` is a single module, so it has a single owner
(Pillar 7) for the shell and its conventions; the seven *domain pages* are
**specified** by Pillars 1–6 and **rendered** through Pillar 7's shell. The split
is by page, not by module, and it is the only split in this table.

**Divergence between this table and `docs/04` §2 is a defect — fix both in the
same change.**

---

## 8. Page → pillar map (`docs/04` §8.4, plus Login)

| Page | Route name | Pillar |
|---|---|---|
| Home | `home` | 7 |
| Pipelines | `pipelines:list` | 3 |
| Sources | `sources:list` | 1 |
| Catalog | `catalog:index` | 1 |
| Queue | `queue:list` | 4 |
| Library | `library:list` | 5 |
| History | `history:list` | 6 |
| Credentials | `credentials:list` | 2 |
| Ops (logs) | `ops:logs` | 7 |
| Settings | `settings:index` | 7 |
| Login / logout | — (D16) | 7 |

**No pillar may add a page that is not in this table.** A new page is a `docs/04`
§8.4 change first — that ordering is what keeps the page inventory honest.

---

## 9. Pillar → `docs/07` work-unit map

`docs/07` remains the **implementation order**. This table only tells a chapter
which units it unblocks, so a chapter's `08_TESTS_AND_DOD.md` can name them and we
never end up with two competing plans (the D-27 failure mode).

| Pillar | Units it unblocks |
|---|---|
| **0** | realised in **U01** (`core` base types) plus the adapters' own units; its chapters **gate** every unit below |
| **1** | U07, U17 |
| **2** | U05, U09, U16 |
| **3** | U06, U18 |
| **4** | U08, U19 |
| **5** | U11, U12, U13, U21 |
| **6** | U10, U20 |
| **7** | U01, U02, U03, U04, U14, U15, U22, U23 |
| **all** | U00 (hygiene), U24 (the end-to-end proof), U25 (documentation reconciliation) |

---

## 10. Glossary ↔ table map (`docs/00` §2 ↔ `docs/03`)

Purpose: stop the **D-01** defect class, where the prose and the schema silently
disagree. A chapter uses the glossary term in prose and the table name in code,
and this table is the bridge between them.

| Glossary term (`docs/00` §2) | Schema artefact (`docs/03`) |
|---|---|
| Source | `source` |
| Catalog / catalog video | `catalog_video` |
| Destination | `destination` (+ `authorized_channel` for the credential) |
| Pipeline | `pipeline` (+ `pipeline_source`, `pipeline_destination`) |
| Job | `job` |
| Attempt | `delivery_attempt` |
| Ledger | `delivery` |
| Upload log | `delivery` + `delivery_attempt` (the two-sided mapping) |
| Inventory | `destination_inventory` |
| Media asset | `media_asset` |
| Materialization | `media_asset.materialization_no` |
| Provenance marker | `delivery.provenance_marker` · `destination_inventory.provenance_marker` |
| Retention | `pipeline.retention_*` · `media_asset.delete_after` · `media_event` |
| Pin | `media_asset.pinned_until` / `pinned_reason`; `catalog_video.starred` as the operator-facing star (`docs/05` §8) |
| Rehydrate | `job.intent = 'rehydrate'` · `media_event.event = 'rehydrated'` |

**One word, one meaning.** If a chapter needs a word that is not in `docs/00` §2,
the glossary is edited first (`docs/00` §6 rule) — not coined inline.
