# 01 — Frontend Specification: Media & Storage

**Pillar:** 5 · Media & Storage · **Chapter:** Frontend Specification · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §3  
**Depends on:** `docs/PILLARS/05_MEDIA_AND_STORAGE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-2, INV-3, INV-7, INV-10, INV-11  

---

## 1. Executive Summary & Screen Inventory

Pillar 5 provides the storage governance interface: disk space telemetry, storage root management,
physical asset browser, retention policy dry-run simulation (`INV-10`), and pinned asset management.

### Screen & Component List
1. **Screen 1: Storage Management Console (`/storage`)**
   - KPI Strip (Total Capacity, Used Bytes, Free Bytes, Active Assets, Orphan Partials, 10 GB Floor Warning).
   - Storage Roots Table (Path, Volume Label, Mount State, Usage Gauge, Floor Status).
   - Global Retention Trigger: `[ Run Retention Pruning ]` with mandatory modal dry-run preview (`INV-10`).
2. **Screen 2: Retention Pruning Dry-Run Modal**
   - Dry-Run Table: List of candidate assets eligible for deletion.
   - Guard Column: Reason for deletion, size reclaimed, and proof that all enabled destinations are terminal (`INV-2`).
   - Confirmation Step: Operator typed confirmation `PRUNE` before executing actual unlinks.
3. **Screen 3: Media Asset Inspector (Drawer in `/catalog`)**
   - Asset Details (Relative path, byte size, verified SHA-256 hash, container, resolution).
   - Status Badge (`ON_DISK`, `DOWNLOADING`, `DELETED`, `ARCHIVE_OFFLINE`).
   - Manual Actions: `[ Pin Asset ]` / `[ Unpin Asset ]`, `[ Rehydrate Media ]`.

---

## 2. Screen 1: Storage Management Console (`/storage`)

### 2.1 Layout Block Diagram
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Storage & Media Health                    [ Preview Retention Prune ]│
├─────────────────────────────────────────────────────────────────────────────┤
│ KPI Strip: [ 1.8 TB / 2.0 TB Used (90%) ] [ 204 GB Free ] [ 412 Assets ] [ OK ]│
├─────────────────────────────────────────────────────────────────────────────┤
│ Storage Roots                                                               │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Volume: /data/media (Host NVMe)                               [ MOUNTED ]│ │
│ │ Free Space: 204.2 GB (Floor: 10.0 GB) - Admission Gate: OPEN           │ │
│ │ [████████████████████████████████████████░░░░] 90% Used                 │ │
│ │ Total Assets: 412 | Orphan Partials Cleaned: 3 (1.2 GB reclaimed today) │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Screen 2: Retention Pruning Dry-Run Modal (`INV-10`)

### 3.1 Workflow & Safety Guards
- Triggered by `[ Preview Retention Prune ]`.
- Calls `media.api.evaluate_retention_dry_run()`.
- Table displays:
  - Video Title, Asset Path, Byte Size, Pipeline Policy (`DELETE_AFTER_UPLOAD`).
  - Terminal Verification: Confirms delivery ledger state across all enabled destinations (`INV-2`).
  - Summary: *"28 files selected. 42.6 GB will be safely reclaimed from disk."*
- Button: `[ Execute Pruning ]` is disabled until operator checks: *"I understand this permanently removes verified physical files from disk."*

---

## 4. Verification Checklist (Frontend DoD)

- [ ] Telemetry displays real-time free space against the 10 GB admission floor.
- [ ] Retention pruning never executes without presenting the dry-run summary first (`INV-10`).
- [ ] Terminal destination check is visually confirmed on every deletion candidate row (`INV-2`).
- [ ] Media asset drawer exposes verified SHA-256 checksum and pinning toggle.
