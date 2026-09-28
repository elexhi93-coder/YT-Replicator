# 01 — Frontend Specification: Pipelines & Routing

**Pillar:** 3 · Pipelines & Routing · **Chapter:** Frontend Specification · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §3  
**Depends on:** `docs/PILLARS/03_PIPELINES_AND_ROUTING/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-6, INV-9, INV-11  

---

## 1. Executive Summary & Screen Inventory

Pillar 3 provides the operator console to orchestrate replication flows: defining pipelines,
binding multiple sources to multiple destinations, configuring quality and filter profiles,
and previewing the exact list of missing videos with skip-reason explanations before
any media download begins.

### Screen & Component List
1. **Screen 1: Pipeline List (`/pipelines`)**
   - KPI Strip (Active Pipelines, Total Sources Linked, Total Destinations Linked, Today's Candidates).
   - Pipeline Table / Cards (Name, Status Toggle, Sync Mode, Source Badges, Destination Badges, Delivery Progress).
   - Action Button: `[ + New Pipeline ]`.
2. **Screen 2: Pipeline Studio / Editor (`/pipelines/[id]`)**
   - **Tab 1: Sources & Destinations**: Link/unlink catalog sources, set backfill cursors, bind authorized target channels.
   - **Tab 2: Download & Filter Profile**: Resolution caps, shorts/live toggles, duration bounds, retention settings.
   - **Tab 3: Candidate Preview & Explainability Drawer**: Full dry-run table showing all evaluated videos, candidate status (`ACTIONABLE`, `ALREADY_DELIVERED`, `SHORTS_FILTERED`), and one-click trigger.

---

## 2. Screen 1: Pipeline List (`/pipelines`)

### 2.1 Layout Block Diagram
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Replication Pipelines                        [ + Create Pipeline ]  │
├─────────────────────────────────────────────────────────────────────────────┤
│ KPI Strip: [ 6 Pipelines ] [ 14 Sources ] [ 4 Destinations ] [ 82 Pending ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ Search & Status: [ Filter pipelines... ] [ Status: Active ▼ ]               │
├─────────────────────────────────────────────────────────────────────────────┤
│ Pipeline Cards                                                              │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Tech Digest Auto-Replication                            [ ACTIVE ]      │ │
│ │ Sources: @Veritasium, @Kurzgesagt  ──▶  Dest: Tech Insights (Unlisted)  │ │
│ │ Profile: 1080p | No Shorts | Keep Media                                 │ │
│ │ ─────────────────────────────────────────────────────────────────────── │ │
│ │ Progress: [██████████████████████░░░░░░░░] 74% Backfilled (42/57 done)   │ │
│ │ Cursor: 2024-03-15 | Next Candidate: "The Mystery of Dark Energy"       │ │
│ │ ─────────────────────────────────────────────────────────────────────── │ │
│ │ Actions: [ View Candidates (15) ] [ Pause ] [ Edit Pipeline ]           │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Screen 2: Candidate Preview & Explainability Studio

### 3.1 The Missing Videos Dry-Run Table
Before initiating replication or while monitoring live progress, operators can open the
**Candidate Preview Drawer**:
- Displays real-time candidate evaluation for the pipeline.
- Column headers: Video Title, Source Channel, Published Date, Duration, Target Destination, Status Pill, Skip Reason.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Candidate Preview: Tech Digest Auto-Replication                                 [ Refresh ] [ X ] │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Summary: 15 Actionable Candidates | 42 Already Delivered | 18 Filtered                           │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Title                           | Published  | Dest Channel     | Candidate Status | Reason      │
├─────────────────────────────────┼────────────┼──────────────────┼──────────────────┼─────────────┤
│ The Mystery of Dark Energy      | 2024-03-18 | Tech Insights    | ACTIONABLE       | Ready       │
│ How Quantum Computers Compute   | 2024-03-12 | Tech Insights    | ALREADY_DELIV    | INV-5 Match │
│ 15 Seconds of Fusion Power      | 2024-03-10 | Tech Insights    | FILTERED         | Short (<60s)│
│ Live Stream Q&A with Physicist  | 2024-03-01 | Tech Insights    | FILTERED         | Live Stream │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Verification Checklist (Frontend DoD)

- [ ] Pipeline builder supports M:N source-to-destination binding (`INV-9`).
- [ ] Candidate preview clearly displays skip reasons and respects Pillar 6 ledger (`INV-5`).
- [ ] Profile editor controls resolution (720p-4k), skip_shorts, skip_live, and retention (`INV-6`).
- [ ] Immediate status toggle allows instant pausing of active pipelines.
