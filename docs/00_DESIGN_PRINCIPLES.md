# 00 — Design Principles and Glossary

**Project:** YT-Replicator
**Legacy reference:** `project003_bundle/` (read-only; generations 1–3 of "project003")
**Status:** Draft for review. Supersedes the direction notes it absorbs.
**Rule for the whole set:** if a document and the code disagree, one of them is
wrong — fix both in the same change. The legacy bundle drifted until its own
docs contradicted its own Dockerfiles.

---

## How to read this set

| File | Answers |
|---|---|
| `00_DESIGN_PRINCIPLES.md` (this) | vocabulary, rules, invariants |
| `01_LEGACY_REVERSE_ENGINEERING.md` | what project003 actually did; keep / adapt / drop |
| `02_DOMAIN_MODEL.md` | entities, keys, states, relationships |
| `03_DATABASE_SCHEMA.md` | tables, columns, indexes, migrations |
| `04_ARCHITECTURE.md` | modules, workers, deployment, security |
| `05_FLOWS.md` | flowcharts and state machines |
| `06_FEATURE_ROADMAP.md` | v1 / v2 / parking lot + legacy feature diff |
| `07_WORK_PLAN.md` | session-sized work units in dependency order, each confined to one module |

---

## 1. Scope

**In scope for v1:** one installation, one workspace, YouTube sources →
YouTube destinations, Python, self-hosted on a VPS, browser UI.

**Explicitly out of scope for v1** — each of these was a real cost in the
legacy: other platforms; n8n or any external workflow engine; Redis, Celery or
a message broker; desktop GUI; FFmpeg transformations; AI metadata rewriting;
multi-tenant SaaS features.

---

## 2. Glossary

One word, one meaning. Most legacy defects reduce to one word meaning two.

| Term | Meaning |
|---|---|
| **Source** | A YouTube channel or playlist we read from. Never uploaded to. |
| **Catalog** | Metadata for every video a Source exposes. No media. |
| **Destination** | A YouTube channel we are authorised to upload to. |
| **Pipeline** | The configured link: source(s) → destination(s) + settings. |
| **Job** | One unit of work for one video. Intent: `upload` / `rehydrate` / `inspect`. |
| **Attempt** | One try at one outcome for one destination. Append-only. |
| **Ledger** | Our durable record of what we did. Ours alone. |
| **Inventory** | What the destination currently shows. Observed, not owned. |
| **Upload log** | The two-sided mapping: source video ↔ destination video, per attempt. |
| **Media asset** | One physical file we hold or held. |
| **Materialization** | The Nth physical copy of a video (original, or a later re-download). Never assume identical bytes. |
| **Provenance marker** | A short code written into the destination video's description so both sides can be re-joined after total data loss. |
| **Reconciliation** | Comparing ledger against inventory to find missing or unclaimed content. |
| **Hygiene** | Removing media that is never valid. Always on. |
| **Retention** | Policy for deleting *valid* media. Opt-in, default off. |
| **Pin** | An explicit hold that exempts media from retention. |
| **Rehydrate** | Re-downloading media for a video we already know, without re-uploading. |

---

## 3. Four tiers: complexity proportional to need

A source with little content must require **zero** configuration.

| Tier | Needed by | Default | Cost of omission |
|---|---|---|---|
| **Records** — ledger, upload log, dedup | everyone | always on | duplicate uploads; rebuilding from scratch impossible |
| **Hygiene** — partial downloads, orphans, aborted jobs | everyone | always on | media that is never valid accumulates |
| **Safety** — free-space admission guard, atomic claims | everyone | always on, silent | disk fills, writes fail, work is duplicated |
| **Retention** — deleting valid media | large sources only | **off** (`keep`) | disk fills — and only for large sources |

Deletion is a feature, not a requirement. `keep` must short-circuit: no scans,
no queries, no UI clutter.

---

## 4. Principles

Every principle is a lesson already paid for. The right column is the receipt.

| # | Principle | Evidence in the legacy |
|---|---|---|
| P1 | One module, one concern. No file owns two decisions. | `dashboard/app.py`: 384 KB, ~7 000 lines, 100+ routes |
| P2 | Records outlive media. The database is the source of truth for state; the filesystem is a cache. | media state lived on disk — delete the file and the UI row vanished |
| P3 | Exactly one owner per decision: one downloader, one uploader, one deleter, one policy evaluator. | seven separate deleters across watcher, uploader, app and processor |
| P4 | Facts are append-only; state is derived. Never edit history to fix a status. | retries mutated and duplicated `upload_results` rows |
| P5 | Opt-in by need. Defaults must do nothing and cost nothing. | retention forced on every pipeline by a single boolean |
| P6 | Separate facts from inferences. Ledger is ours; inventory is observed. | no destination inventory sync existed at all |
| P7 | Exact by construction. Identity comes from keys and markers, never titles. | fuzzy title/date matching proposed as a safety mechanism |
| P8 | Every asset has an owner and an expiry, or is explicitly pinned. | the TTL sweeper could not see per-job folders, so files accumulated forever |
| P9 | Idempotent and resumable. Any call may fail; a half-file is never valid. | a 24 h TTL sweep raced the uploader's `rmtree` on the same folder |
| P10 | Quota-aware. An upload costs 1 600 of 10 000 daily units; a read costs about 1. | reads were never used; uploads were the only lever |
| P11 | One writer per resource; claim work atomically. | four containers shared one SQLite file over a bind mount |
| P12 | Secrets never sit in plaintext in the database file or in git. | `oauth_tokens.access_token` and `youtube_projects.client_secret` are plaintext columns |
| P13 | Policy decisions are pure functions with tested decision tables. | policy was scattered across UI handlers |
| P14 | Every destructive action is logged with a reason; freed and held bytes are visible numbers. | disk usage was not explicable from the app |
| P15 | Never discard recoverable work. | the watcher "marks a video as seen even if download fails" |
| P16 | One module, one reason to change. Cross-module access only through a module's published interface. | the 384 KB `app.py` meant every change risked every feature |

---

## 5. Invariants

Non-negotiable. A change that breaks one is a bug, not a trade-off.

- **INV-1** A (video, destination) pair has at most one *current* successful upload-log row.
- **INV-2** Media is deleted only when every enabled destination for that job is terminal-success, or the job never needed a destination.
- **INV-3** A partial, unverified or unhashed file is never uploaded.
- **INV-4** Removing a source, destination or pipeline never deletes history.
- **INV-5** Nothing is enqueued for a pair that already has a current successful attempt, unless the operator forces it explicitly.
- **INV-6** Every retention decision is reproducible from the database alone.
- **INV-7** Metadata scanning never triggers a download.
- **INV-8** Unclaimed inventory is flagged for review; it is never silently adopted or overwritten.
- **INV-9** A source is reusable: the same channel may feed several pipelines.
- **INV-10** Deletion is evaluated in one place, and a dry run is always available.
- **INV-11** A change that does not alter a published interface touches exactly one module's code and that module's tests, and nothing else.
- **INV-12** No module may be imported except through its published interface, and no module file exceeds 600 lines.

---

## 6. Decisions register

Every decision below is **locked**. They were settled deliberately before any
code existed, so reversing one is possible — but only by editing this table and
every document named in its row, in the same change. Nothing here is left open.

| # | Decision | Resolution | Documented in |
|---|---|---|---|
| D1 | Default retention mode | `keep` — delete nothing unless the operator opts in | `02` §1, `05` §8 |
| D2 | Provenance marker in the destination description | on; a short `ref:` code at the end of the description | `02` §1, `05` §6 |
| D3 | Deleting the last local copy | only when the destination copy is confirmed present | `02` §1, `05` §8 |
| D4 | Rehydrated media | pinned by default until explicitly released | `02` §1, `05` §7 |
| D5 | What `after_n_jobs` counts | completed jobs of the pipeline, not uploads | `02` §1, `05` §8 |
| D6 | Hard max-age backstop | 7 days, applied in every mode | `02` §1, `03` §11 |
| D7 | Library page | one page with a media-state filter, not a separate tab | `02` §1, `04` §8.4 |
| D8 | Database engine | PostgreSQL 16 | `02` §1, `03` §1 |
| D9 | Detection and reconciliation cadence | poll every 15 minutes; full reconciliation every 6 hours | `03` §11, `05` §4 |
| D10 | Upload metadata | original only in v1; AI rewriting parked in v2 | `06` §2 |
| D11 | Tenancy | tenant-shaped, not tenant-featured; no tenant work in v1 | `02` §2 |
| D12 | History when configuration is deleted | configuration may be deleted; delivery history never cascades | `02` §1, `03` §2 |
| D13 | Credentials | encrypted at rest; the key lives outside the database | `03` §4, `04` §9 |
| D14 | v1 delivery rule | all sources of a pipeline → all its enabled destinations | `02` §1, `05` §4 |
| D15 | Video transformation | none in v1; the source file is uploaded as-is | `06` §3 |
| D16 | Authentication | required on every page; CSRF on every mutation | `04` §9 |
| D17 | Dashboard readiness | context slot, data-driven nav, named routes, one workspace helper | `02` §2.1, `04` §8 |

A decision changed in code but not in this table, or in this table but not in a
document that cites it, is a documentation defect. That is precisely what
happened in the legacy (D-01, D-27), and this register exists to make it
detectable.
