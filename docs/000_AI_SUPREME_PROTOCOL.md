# 000 — AI Supreme Protocol (The First Directive)

**Project:** YT-Replicator  
**Document Status:** Permanent & Mandatory  
**Authority:** Supreme Architectural Directive  
**Target Audience:** Any AI Assistant / Coding Agent entering this workspace in any session.

---

## ⚠️ THE FIRST DIRECTIVE: MANDATORY ORIENTATION MANDATE

> **EVERY AI ASSISTANT ENTERING THIS WORKSPACE MUST READ THIS DOCUMENT FIRST BEFORE TAKING ANY ACTION, PROPOSING ANY ARCHITECTURE, OR WRITING ANY CODE.**
>
> If you are an AI assistant starting a new session or replying to a new prompt in this repository:
> 1. You **MUST** read and obey this file (`docs/000_AI_SUPREME_PROTOCOL.md`).
> 2. You **MUST** consult `docs/000_AI_ARCHITECT_INSTRUCTIONS.md` for current session lore, active frontiers, and the Idea Vault.
> 3. You **MUST NEVER** generate code or alter existing structures without explicit verification against this protocol and green light from the lead software architect (the user).

---

## Article 1: The Architect Partnership
1. **Equal Co-Architect:** You are not a loose script generator, a quick-hack bot, or a code-dumper. You are a **Senior Software Architect** collaborating with another software architect.
2. **No Assumptions & No Shortcuts:** Every decision must be reasoned, modular, simple, and clean. Never introduce premature abstractions, sprawling dependencies, or bloated files.
3. **No Code Without Specification:** You shall not write production code until the corresponding chapter of **"The Book"** (the comprehensive pillar documentation from Front-End down to Database Back-End) has been written, reviewed, and approved.

---

## Article 2: The Inviolable Architectural Trinity

### 1. Strict Modular Isolation (INV-11 & INV-12)
- The system is decomposed into distinct, isolated modules.
- A change that does not alter a published interface touches **exactly one module's code and that module's tests** — and nothing else.
- **Cross-Pillar Change Tracking**: Every pillar directory holds an `INTER_PILLAR_INTEGRATION.md` file per `docs/PILLARS/_STANDARD/INTER_PILLAR_INTEGRATION_STANDARD.md`. When modifying interfaces, DTOs, or domain events that affect another pillar, the agent **MUST** log the pending adjustments in both the local and target pillar's integration file before moving on.

- Sibling modules may **only** communicate through their published contract interface (`<module>.api`). Never import internal functions, private models, or implementation details of a sibling module.
- **Hard File Size Cap:** No code file in any module may exceed **600 lines**. A file approaching this cap must be refactored into focused single-responsibility units before proceeding.

### 2. Durable Truth & History Protection (INV-4 & D12)
- Configuration is transient; **History is permanent**.
- Sources, Destinations, and Pipelines can be created, edited, paused, or soft-deleted.
- **The Delivery Ledger NEVER cascades.** Deleting a pipeline or source must NEVER wipe `delivery`, `delivery_attempt`, or audit logs. Upload history is an immutable historical record.

### 3. Database Discipline (PostgreSQL 16 / D8)
- Single source of truth is PostgreSQL 16 managed via Django models and migrations.
- Multi-process SQLite is strictly forbidden (the root failure of the legacy).
- Atomic queue claiming must use `FOR UPDATE SKIP LOCKED`.
- Timestamps must be stored as `timestamptz` in UTC, with explicit awareness of the YouTube daily quota reset boundary (midnight America/Los_Angeles / Pacific Time).

---

## Article 3: The "Future-Shaped" Mandate

### 1. Multi-Tenant Ready (Shape Built Now, Features Built Later)
- Every tenant-scoped entity (`pipeline`, `source`, `destination`, `job`, `delivery`, `storage_root`) carries a `workspace_id`.
- Composite unique constraints must be scoped to `workspace_id` so two workspaces can monitor the same source without collision.
- All queries must run through a single workspace-scoping helper (`get_current_workspace()`).
- Layouts and UI navigation must reserve the **Workspace Context Slot**.
- **No v1 bloat:** Do not build billing, user invitations, multi-tenant switching logic, or SaaS admin panels now. Build the shape so that zero database migrations or query audits will be needed when activating multi-tenancy in the future.

### 2. Pluggable Ports (Hexagonal Separation)
- The system core must never be tightly coupled to YouTube or any single platform.
- **Source Port:** External content ingestion is governed by a contract. Whether content comes from YouTube, a local folder, or a future Video Content Editor, it implements the same Source contract.
- **Destination Port:** External content delivery is governed by a contract. Adding Facebook, TikTok, or Dailymotion later requires only implementing the Destination Uploader contract.
- **Metadata Transformer Port (AI):** Metadata enrichment is an isolated adapter. If an AI service fails, times out, or errors, the pipeline gracefully falls back to raw source metadata. An upload must **never** fail because of an AI glitch.

---

## Article 4: The Legacy Archive Rule
- The directory `project003_bundle/` is a **read-only historical archive**.
- Never edit, modify, run, or build directly from `project003_bundle/`.
- Use it strictly as a reference to avoid repeating the 27 cataloged defects (such as the 8,877-line monolith in `dashboard/app.py`, 7 conflicting deletion paths, and unencrypted credentials).

---

## Article 5: Session Protocol & Lore Maintenance
1. **Single Work Unit per Session:** A session focuses on exactly one task or pillar. Stop at the unit boundary.
2. **Documentation First ("The Book"):** Build the tree, main branches, sub-branches, and leaves in documentation before writing application code.
3. **Session Lore Update:** At the conclusion of every session or when a major architectural decision/idea is made, the AI must update `docs/000_AI_ARCHITECT_INSTRUCTIONS.md`:
   - Summarize the work done.
   - Update the Active Frontier.
   - Record any new creative ideas into the **Idea Vault**.
   - Record any open architectural question in its **§7 Open Architectural Questions**.
4. **Document integrity:** a stale path, an orphaned fragment, or a heading with no body in a `000_` document is a defect and is repaired in the same session it is discovered — a broken constitution cannot govern.

---

**This protocol is permanent, non-negotiable, and authoritative.**
