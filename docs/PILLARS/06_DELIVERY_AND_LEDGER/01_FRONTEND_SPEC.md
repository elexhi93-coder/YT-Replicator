# 01 — Frontend Specification: Delivery & Ledger

**Pillar:** 6 · Delivery & Ledger · **Chapter:** Frontend Specification · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §3  
**Depends on:** `docs/PILLARS/06_DELIVERY_AND_LEDGER/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-4, INV-8, INV-11  

---

## 1. Executive Summary & Screen Inventory

Pillar 6 provides the audit ledger console: viewing immutable delivery receipts, inspecting
both-sided links (source video ➔ target YouTube video), reviewing reconciliation mismatches,
triggering channel inventory scans, and exporting CSV audit reports.

### Screen & Component List
1. **Screen 1: Delivery Ledger (`/deliveries`)**
   - KPI Strip (Delivered Total, Today's Deliveries, Permanent Failures, Unreconciled / Mismatches).
   - Deliveries Table: Source Title, Source Channel, Target Destination, Target Video Link, Status Pill, Delivered Timestamp, Actions.
   - Filter & Search Bar: Source filter, Destination filter, Status filter (`DELIVERED_SUCCESS`, `FAILED_PERMANENT`, `REMOVED`), Date range.
   - Action Button: `[ Export CSV Audit Report ]`.
2. **Screen 2: Reconciliation Review Console (`/reconciliation`)**
   - Mismatch Summary Banner (Highlights `unclaimed_present` and `missing_expected` count).
   - Reconciliation Discrepancy Table: Remote Video Title, Channel, Remote Video ID, Marker State, Detected Discrepancy, Remediation Options (`Adopt Video`, `Mark Removed`, `Ignore`).
   - Trigger: `[ Run Channel Inventory Scan Now ]`.
3. **Screen 3: Delivery Attempt Inspector Drawer**
   - Timeline of attempts (Attempt 1: timeout, Attempt 2: success).
   - HTTP response status, upload duration, byte size, verified provenance marker code.

---

## 2. Screen 1: Delivery Ledger (`/deliveries`)

### 2.1 Layout Block Diagram
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Delivery Ledger                              [ Export CSV Audit ⤓ ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ KPI Strip: [ 1,280 Delivered ] [ 18 Today ] [ 2 Failed ] [ 1 Mismatch ⚠ ]   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Filters: [ Dest: Tech Insights ▼ ] [ Status: All ▼ ] [ Search title... ]    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Deliveries Table                                                            │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Source Title      | Destination   | Remote Video Link  | Status | Time  │ │
│ ├───────────────────┼───────────────┼────────────────────┼────────┼───────┤ │
│ │ Quantum Computing | Tech Insights | youtube.com/watch? | SUCCESS| 2h ago│ │
│ │ Explained         |               | v=k81f0923zy       | [pill] |       │ │
│ ├───────────────────┼───────────────┼────────────────────┼────────┼───────┤ │
│ │ Fusion Energy 101 | Tech Insights | youtube.com/watch? | SUCCESS| 5h ago│ │
│ │                   |               | v=a10c9481xx       | [pill] |       │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Screen 2: Reconciliation Review Console (`/reconciliation`)

### 3.1 Resolving Unclaimed Remote Inventory (`INV-8`)
- When YouTube channel inventory sync discovers a video that has no matching marker:
  - Displayed in **`UNCLAIMED_PRESENT`** table.
  - Options:
    1. `[ Manual Adopt ]`: Operator explicitly confirms this video was an out-of-band replication of an existing catalog video.
    2. `[ Ignore ]`: Retain as foreign external content. Never automatically touched or deleted.
- When an expected video is missing on YouTube:
  - Displayed in **`MISSING_EXPECTED`** table.
  - Option: `[ Mark as Removed ]` updates ledger status to `REMOVED` without re-uploading unless pipeline requests re-backfill.

---

## 4. Verification Checklist (Frontend DoD)

- [ ] Both-sided hyperlinks (source URL and destination YouTube watch URL) are present on every row.
- [ ] Export CSV includes canonical source ID, destination channel ID, remote video ID, and timestamp.
- [ ] Unclaimed remote videos are explicitly flagged and never silently adopted (`INV-8`).
- [ ] Attempt drawer displays granular history without exposing secrets.
