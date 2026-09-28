# 000 — AI Architect Instructions & Idea Vault (YT-Replicator)

**Document Purpose:** Session-to-session memory, architectural lore, active working frontiers, and long-term idea repository.  
**Companion Document:** Governed strictly by `docs/000_AI_SUPREME_PROTOCOL.md`.  
**Last Updated:** Session 3 — full documentation read-through (`00`–`07` + the Book), integrity check of the two `000_` documents, findings recorded in §7.

---

## 1. Project Overview & Meta-State

We are two software architects building **YT-Replicator**, a clean, modular, self-hosted web system for automated YouTube content replication.

### The Previous Legacy Project (`project003_bundle/`)
- A senior developer built an ambitious system ("project003") spanning 3 generations (Desktop Tkinter, Headless Docker + n8n, Flask + SQLite).
- **Why it stalled:** Monolithic approach (`dashboard/app.py` ballooned to 8,877 lines), 4 processes bound to one SQLite file causing concurrency locks, 7 competing file deletion paths, and unencrypted credentials.
- **Our mandate:** Modular Architecture, Simplicity, Clean Boundaries, and Step-by-Step Rigor.

---

## 2. The 8 Foundation Pillars (0–7)

Our architecture is structured as a complete "Book" where each pillar represents a main branch, documented from the **Front-End UI down to the Back-End Database**:

| Pillar | Domain | Core Responsibility |
|---|---|---|
| **Pillar 0** | **Inter-Pillar Contracts (The Highway)** | Standard DTOs, Source Provider Port, Destination Uploader Port, and Metadata Transformer Port. Decouples modules completely. |
| **Pillar 1** | **Sources & Catalog** | Ingests metadata from YouTube (or future editor), flat scans, lazy hydration, catalog search/filter. |
| **Pillar 2** | **Destinations & Authorizations** | Authorizes upload channels, AES-encrypted tokens at rest, Pacific midnight quota management. |
| **Pillar 3** | **Pipelines & Routing** | Connects Sources to Destinations, candidate preview, backfill cursor timestamps, 15-min monitor cadence. |
| **Pillar 4** | **Job Engine & Scheduler** | Agnostic work queue, atomic PostgreSQL claims (`FOR UPDATE SKIP LOCKED`), retry state machine, classification of transient vs. permanent errors. |
| **Pillar 5** | **Media & Storage Lifecycle** | Single owner of downloads and files, sha256 verification, path safety, hygiene sweeps, safe retention policies (default `keep`). |
| **Pillar 6** | **Delivery Truth & Ledger** | Permanent delivery records (`delivery`, `delivery_attempt`), two-sided reconciliation with destination inventory, deterministic provenance markers (`ref:` codes). |
| **Pillar 7** | **Platform Foundation & Operations** | Owns the platform: `core` (clock, settings, errors, logging, path safety, SSRF, base types), `accounts` (workspace + access helper), `worker` (run loop, no rules), `ops` (audit, heartbeat, logs, purge), and the UI shell + the platform pages (Home, Settings, Logs, Login). |

---

## 3. Core Architectural Directives

1. **Multi-Tenant Shaped, Single-Tenant Operated:**
   - Every tenant-scoped entity carries a `workspace_id` foreign key.
   - All queries scope through a centralized `get_current_workspace()` helper.
   - The UI shell and navigation reserve the **Workspace Context Slot**.
   - No billing, invitations, or tenant switching in v1; zero migrations needed when activating them later.
2. **Strict File & Module Bounds:**
   - Maximum **600 lines** per file.
   - Module cross-communication happens exclusively via `<module>.api`.
3. **Delivery History is Permanent:**
   - Soft-delete configuration (sources, pipelines); **never cascade-delete the delivery ledger**.
4. **PostgreSQL 16 Engine:**
   - Multi-worker concurrency, atomic queue claims (`SKIP LOCKED`), UTC `timestamptz`.

---

## 4. 💡 THE IDEA VAULT (The "Great Ideas for Later" Archive)

*This is our dedicated repository for high-value ideas conceived during architectural discussions that are intentionally parked for post-v1 implementation. Nothing recorded here is lost.*

### [IDEA-01] Pluggable Source: Custom Video Content Editor / Ingestion Port
- **Concept:** Allow YT-Replicator to ingest content not just from external YouTube channels, but from an internal video editor, a local rendering folder, or an S3/cloud bucket.
- **Architecture:** The content editor only needs to output standard `SourceItemDTO` records and provide the media path to the Source Port. The Pipeline, Queue, and Destination modules process and deliver it with zero code changes.
- **Phase:** v2 (Post-v1).

### [IDEA-02] Pluggable Destinations: Multi-Platform Syndication (Facebook, TikTok, Dailymotion)
- **Concept:** Extend automated replication to Facebook, TikTok, Instagram, and Dailymotion.
- **Architecture:** Implement concrete adapters for the standard `DestinationUploader` port. The core orchestration, ledger, and media management remain completely untouched.
- **Phase:** v2 (Post-v1).

### [IDEA-03] AI Metadata Transformer with Graceful Fallback
- **Concept:** Allow automated AI rewriting of titles, descriptions, SEO tags, and language translation before uploading.
- **Architecture:** Defined as an isolated `MetadataTransformer` port. Includes a customizable prompt template in the Pipeline UI.
- **Golden Invariant:** If the AI model fails, times out, or hits rate limits, the pipeline logs a warning and **automatically falls back to raw source metadata**. Uploads never fail due to an AI glitch.
- **Phase:** Specified in Pillar 0 contracts now; concrete AI adapter activated in v2.

### [IDEA-04] Full Multi-Tenant SaaS Expansion
- **Concept:** Turn YT-Replicator into a multi-customer SaaS platform.
- **Architecture:** Because all tables already carry `workspace_id` and UI layouts reserve the Workspace slot, this requires only:
  - User self-signup & authentication.
  - Team member invitations and role matrices (`owner`, `operator`, `viewer`).
  - Active workspace dropdown switcher in the UI header.
  - Subscription / billing integration.
- **Phase:** v2 / v3.

### [IDEA-05] Multi-Project Quota Rotation (Revived from the Legacy)
- **Concept:** YouTube grants ~10,000 API units/day per Google Cloud project, and one upload costs ~1,600 — roughly 6 uploads per project per day. The legacy rotated across many Google Cloud projects (`dashboard/projects.py`) to reach 50–100 uploads/day.
- **Legacy flaw:** rotation picked a project by counter, and could therefore upload to the wrong channel. It also reset its counter on the **UTC** day while YouTube resets on the **Pacific** day (defect D-03).
- **Our v1 position:** one client explicitly bound to one channel, no rotation. Simple, predictable, safe.
- **Parked design:** if rotation returns, it must be bound by *channel ownership*, not by a counter — rotate only among clients that are authorised for the same destination channel — and every counter must use the Pacific quota day.
- **Phase:** v2 (post-v1), recorded in `docs/PILLARS/02_DESTINATIONS_AND_AUTH/10_OPEN_QUESTIONS.md`.

---

## 5. Active Working Frontier

- **Completed:**
  - Full reverse-engineering of `project003_bundle` (all 62 legacy docs, plus the Python source: the 8,877-line `dashboard/app.py`, `models.py`, `uploader.py`, `sources.py`, `router.py`, `projects.py`, `oauth_youtube.py`, `headless_watcher.py`, `processor.py`, and the Gen-1 `core/`, `plugins/`, `uploaders/`).
  - Full review of the existing foundation set (`docs/00`–`07`).
  - Definition of the 7 Foundation Pillars (0 = Inter-Pillar Contracts, plus 1–6).
  - Constitution written: `docs/000_AI_SUPREME_PROTOCOL.md`.
  - Idea Vault written: `docs/000_AI_ARCHITECT_INSTRUCTIONS.md` (this file).
  - Both renamed with the `000_` prefix so they always sort first; `docs/README.md` index updated.
  - **The Book scaffolded:** `docs/PILLARS/README.md` (index), `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` (the fixed twelve-section chapter skeleton), and a branch-level `README.md` for each of the 7 pillars with mission / owns / does-not-own / dependencies / invariants / chapter plan / legacy anchors.

- **Logic and Rules authored (this session):**
  `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/04_LOGIC_AND_RULES.md` authored. It
  formalizes the universal exchange invariants (R1–R6), identity resolution and
  propagation rules (ID-1 to ID-4), sequence validation rules (SEQ-1 to SEQ-5),
  provenance marker lifecycle and recovery mechanics (MKR-1 to MKR-3, REC-1 to REC-3),
  and adapter error isolation firewalls.
- **Data Model & Transfer Objects authored (this session):**
  `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/05_DATA_MODEL.md` authored. It establishes
  the DTO vs. ORM entity boundary (INV-11, INV-12), value semantics, frozen immutability,
  the complete typed contract dataclass definitions across all four domains (Sources,
  Media, Destinations, Delivery), deterministic JSON/IPC serialization rules, and
  tenancy boundary neutrality.
- **Leaf Specification Standard established (this session):**
  `docs/000_AI_DEEP_SPEC_STANDARD.md` authored. It establishes the Tree-Branch-Leaf
  framework, mandatory external platform field universe rubrics (RSS, Flat scan,
  Hydrated metadata, and Official Data API v3 tiers), frontend screen frames,
  end-to-end data lineage matrices, and failure classification rules.
- **Next Frontier (one chapter, one session):**
  - Author `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/06_FAILURES_AND_ERRORS.md` (or complete Pillar 0 overview) to lock port error taxonomy before diving into the detailed leaf specs of Pillar 1 (`01_SOURCES_AND_CATALOG`).

- **Session 3 — the full read-through (this session):** every line of `README.md` and
  `00`–`07` read (glossary, P1–P16, INV-1…INV-12, D1–D17, F-01…F-56, D-01…D-27, 23
  entities, all 8 schema groups, 12-module map, 11 flows, 56-row coverage table,
  U00–U25), plus both `000_` documents read from disk. Three structural gaps found
  and **recorded in §7** rather than acted on. Two defects in the mandatory
  documents repaired: an orphaned fragment left under §3 item 4 (now restored in
  place) and a stale path in the Protocol's Article 5 (now `000_`).

- **Interface Contract authored (this session):**
  `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` authored. It
  defines three ports (`SourceProvider`, `DestinationPlatform`,
  `MetadataTransformer`), their frozen DTOs, rules of exchange R1–R6, the
  provenance-marker format (`[ref:{source_id}:{delivery_id}]`), the shared typed
  error hierarchy, and the dependency map.
- **Q-3 closed:** writing the interface contract carried the required obligations:
  `docs/04` §5 `core` row updated, `docs/04` §6 interface change row added
  (2026-09-28), `docs/06` §1 `core` line updated, `docs/06` §2 v2 rows added
  (second destination platform, non-YouTube source), `docs/06` §3 rejection
  clarified, and three nouns (*Port*, *Adapter*, *DTO*) added to `docs/00` §2
  glossary.
- **Standard clarified:** `CHAPTER_STANDARD.md` clarified: the twelve files are the
  pillar's structure; each file carries a four-part internal frame.

- **Session discipline:** one chapter per session; stop at the boundary; update the pillar `README.md` status and this frontier before finishing.

---

## 6. Parked Artifacts (untracked, not authoritative)

Recorded so a future session does not mistake them for the plan:

| Artifact | State | Standing |
|---|---|---|
| `core/` — 8 Python files, `CONTRACT.md`, `tests/test_core.py` | untracked, never committed | Written prematurely by a team member from the **superseded** `docs/00`–`07` reading. Not deleted (evidence is cheap to keep), **not** authoritative. May be mined later for ideas, never for structure. |
| `accounts/`, `credentials/`, `jobs/`, `delivery/`, `media/`, `ops/`, `pipelines/`, `sources/`, `ui/`, `worker/`, `youtube/` | untracked empty scaffold folders | Superseded module naming — the Book's pillar list is the authority. |
| `SESSION_RECAP.md`, `CONVERSATION_HISTORY.md`, `docs.zip` | committed in an earlier session | Historical session notes. Superseded by this file as the frontier of record. |

**Rule:** nothing in this table may be cited as a decision, a contract, or a
reason to skip a chapter. If a file here contains an idea worth keeping, it is
promoted into the Idea Vault above with a note on where it came from.

---

## 7. Open Architectural Questions

Recorded so they survive the session that raised them. **None of these may be
answered in code.** An answer here becomes an edit to the document that owns it,
in the same change.

### 7.1 Resolved

| # | Question | Resolution | Recorded in |
|---|---|---|---|
| **Q-1** | Which pillar owns `core`, `accounts`, `worker`, `ops`, `ui`-shell and `youtube`? | **Pillar 7 — Platform Foundation & Operations** owns `core`, `accounts`, `worker`, `ops` and the UI shell. `youtube` is owned by **Pillar 2** as the v1 platform adapter. All twelve modules now have twelve owners; the orphaned pages (Home, Settings, Logs) and Login gained a home. | `docs/PILLARS/README.md` §7, §8; `07_PLATFORM_FOUNDATION_AND_OPS/README.md` |
| **Q-2** | Is `youtube` the adapter behind Pillar 0's port, or a pillar of its own? | The **adapter**: authored in Pillar 2, consumed by Pillar 6 through Pillar 0's Destination port. Adding Facebook later is therefore an adapter change, not a pillar change. | `docs/PILLARS/README.md` §7 |
| **Q-4** | Pillar ↔ U-unit cross-reference. | Table added. `docs/07` remains the implementation order; a chapter's `08_TESTS_AND_DOD.md` names the units it unblocks. | `docs/PILLARS/README.md` §9 |
| **Q-5** | Glossary ↔ table-name map. | Table added, covering all fifteen glossary terms. | `docs/PILLARS/README.md` §10 |
| **Q-3** | Writing Pillar 0 creates published interfaces. | **Closed:** recorded in `docs/04` §5/§6, `docs/06` §1/§2/§3, and `docs/00` §2 in the same change as `03_INTERFACE_CONTRACT.md`. | `docs/04_ARCHITECTURE.md` §5, §6; `docs/06_FEATURE_ROADMAP.md` §1, §2, §3; `docs/00_DESIGN_PRINCIPLES.md` §2 |


### 7.2 Still open

| # | Question | Why it matters | Blocks |
|---|---|---|---|
| **Q-6** | The credential export holding **22 live OAuth refresh tokens** inside `project003_bundle/docs/Export-Import/`. | Gitignored and never committed (verified), but it belongs outside the repository and the tokens should be rotated. A refresh token does not expire. | the architect — a two-minute action |

