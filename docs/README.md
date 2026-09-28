# YT-Replicator

YT-Replicator is a hosted web application for managing YouTube content replication through configurable Pipelines. A Pipeline connects one or more YouTube Sources to one or more YouTube Destinations, catalogs source videos, identifies items not yet uploaded to each destination, and manages their download and upload lifecycle.

The project is intentionally modular, but should remain straightforward to deploy and troubleshoot. It is not a desktop application and will not use n8n for orchestration.

## Initial direction

- Django web application with server-rendered pages.
- PostgreSQL for application, Pipeline, job, and upload-history data.
- A background worker in the same codebase for monitoring, downloading, and uploading.
- YouTube-only for the initial production scope.
- One Workspace per installation initially; keep account ownership boundaries clear for a possible shared SaaS deployment later.
- Keep upload records after a Pipeline or Source is removed. Do not delete history through cascading Pipeline deletion.

## Documents

### AI Directives & Supreme Protocol (Mandatory First Reads)

| # | Document | Purpose |
|---|---|---|
| [000](000_AI_SUPREME_PROTOCOL.md) | AI Supreme Protocol | The First Directive: mandatory orientation, invariants, file bounds, and partnership rules |
| [000](000_AI_ARCHITECT_INSTRUCTIONS.md) | AI Architect Instructions & Idea Vault | Session lore, active frontiers, and the parked repository for future features (AI, editor, multi-tenancy) |
| [000](000_AI_DEEP_SPEC_STANDARD.md) | AI Deep Specification Standard | Tree-Branch-Leaf methodology: external platform field universe rubric, frontend component frames, and end-to-end data lineage |

### The Book — pillar specifications (in progress)

One folder per pillar, specified from the front-end screen down to the database
column, before any code is written. Start at its index.

| Folder | Pillar | Status |
|---|---|---|
| [PILLARS/README.md](PILLARS/README.md) | **The Book — index and reading order** | scaffolded |
| [PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md](PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md) | Standard for the local `000_PILLAR_INSTRUCTIONS.md` guardrail in each pillar branch | locked |
| [PILLARS/_STANDARD/INTER_PILLAR_INTEGRATION_STANDARD.md](PILLARS/_STANDARD/INTER_PILLAR_INTEGRATION_STANDARD.md) | Standard for cross-pillar change coordination and blast-radius tracking | locked |


| [PILLARS/_STANDARD/](PILLARS/_STANDARD/CHAPTER_STANDARD.md) | Chapter Standard — the fixed twelve-section skeleton every chapter follows | locked |
| [PILLARS/00_INTER_PILLAR_CONTRACTS/](PILLARS/00_INTER_PILLAR_CONTRACTS/README.md) | 0 — Inter-Pillar Contracts (the highway: DTOs, ports, rules of exchange) | **drafting** — `03_INTERFACE_CONTRACT.md` written |
| [PILLARS/01_SOURCES_AND_CATALOG/](PILLARS/01_SOURCES_AND_CATALOG/README.md) | 1 — Sources & Catalog | scaffolded |
| [PILLARS/02_DESTINATIONS_AND_AUTH/](PILLARS/02_DESTINATIONS_AND_AUTH/README.md) | 2 — Destinations & Authorizations | scaffolded |
| [PILLARS/03_PIPELINES_AND_ROUTING/](PILLARS/03_PIPELINES_AND_ROUTING/README.md) | 3 — Pipelines & Routing | scaffolded |
| [PILLARS/04_JOB_ENGINE/](PILLARS/04_JOB_ENGINE/README.md) | 4 — Job Engine | scaffolded |
| [PILLARS/05_MEDIA_AND_STORAGE/](PILLARS/05_MEDIA_AND_STORAGE/README.md) | 5 — Media & Storage | scaffolded |
| [PILLARS/06_DELIVERY_AND_LEDGER/](PILLARS/06_DELIVERY_AND_LEDGER/README.md) | 6 — Delivery & Ledger | scaffolded |
| [PILLARS/07_PLATFORM_FOUNDATION_AND_OPS/](PILLARS/07_PLATFORM_FOUNDATION_AND_OPS/README.md) | 7 — Platform Foundation & Operations (shell, access, worker, ops) | scaffolded |

Rules: the Constitution governs (`000_AI_SUPREME_PROTOCOL.md`), and no production
code is written until the chapter that specifies it is `locked`.

### The build set — authoritative

Read `00` → `01` → `02` → `03` once. After that, consult `04`–`07` by section
rather than reading end to end.

| # | Document | Answers |
|---|---|---|
| [00](00_DESIGN_PRINCIPLES.md) | Design principles and glossary | Vocabulary, the four tiers, 16 principles, 12 invariants, decisions **D1–D17** |
| [01](01_LEGACY_REVERSE_ENGINEERING.md) | Legacy reverse engineering | What project003 did: **56 features** kept / adapted / dropped, **27 defects**, behaviour worth preserving, coverage log |
| [02](02_DOMAIN_MODEL.md) | Domain model | **23 entities**, relationships, three state machines, tenancy, UI readiness |
| [03](03_DATABASE_SCHEMA.md) | Database schema | **22 PostgreSQL tables**, **33 indexes**, conventions, bootstrapping, migration policy |
| [04](04_ARCHITECTURE.md) | Architecture | Module map, dependency rules, enforcement, published interfaces, runtime shape, **dashboard shell**, security, deployment |
| [05](05_FLOWS.md) | Flows | 11 flows: scan, hydrate, backfill, monitor, deliver, reconcile, rehydrate, retention, recovery, pauses, error taxonomy |
| [06](06_FEATURE_ROADMAP.md) | Feature roadmap | v1 / v2 / rejected, plus a coverage table proving no legacy feature was silently dropped |
| [07](07_WORK_PLAN.md) | Work plan | **26 session-sized work units** in dependency order, definition of done, session protocol |

### How this repository is worked on

One module, one work unit, one session — INV-11. `07` names the unit; that unit's
`CONTRACT.md` and tests are the session's only reading. The change is complete
when `07` §4 holds. See `04` §4 for the enforcement tests that make this a
checked rule rather than an intention.

### Superseded — retained, not deleted

| File | Superseded by |
|---|---|
| `ARCHITECTURE.md` | `04_ARCHITECTURE.md` |
| `PIPELINE_WORKFLOW.md` | `02_DOMAIN_MODEL.md` and `05_FLOWS.md` |

These were the original direction notes. They are kept unmodified so nothing is
lost. **If they contradict the numbered set, the numbered set wins** — and the
contradiction should be logged, because documentation disagreeing with itself is
precisely what happened in the legacy (D-01).

### Reference

`project003_bundle/` is a **read-only legacy archive**. Its 62 documents are
summarised and dispositioned in `01`; nothing there is built from directly. Do not
edit it.
