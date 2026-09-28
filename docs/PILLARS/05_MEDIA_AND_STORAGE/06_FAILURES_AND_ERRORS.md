# 06 — Failures, Errors, and Recovery: Media & Storage

**Pillar:** 5 · Media & Storage · **Chapter:** Failures and Errors · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §7  
**Depends on:** `docs/PILLARS/05_MEDIA_AND_STORAGE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-2, INV-3, INV-7, INV-10  

---

## 1. Domain Error Taxonomy

```
MediaStorageError (base)
├── DiskSpaceFloorReachedError (free space < 10 GB floor)
├── MediaIntegrityVerificationError (hash mismatch or 0-byte file)
├── UnmountedStorageRootError (volume detached -> ARCHIVE_OFFLINE)
├── PathTraversalSecurityError (path escape detected, INV-7)
├── PrematureDeletionAttemptError (violates INV-2 terminal destination check)
└── OrphanFileDetectedWarning (lingering .part file cleaned)
```

---

## 2. Exhaustive Error Catalog

| Error Code | Cause | Classification | Recovery / Action |
|---|---|---|---|
| `MEDIA_ERR_DISK_FLOOR` | Free space drops below 10 GB | **Transient** | Reject new downloads. Trigger retention sweep or alert operator. |
| `MEDIA_ERR_CHECKSUM_MISMATCH`| Computed SHA-256 differs from expected | **Permanent** | Delete corrupt partial. Re-queue download from scratch (`INV-3`). |
| `MEDIA_ERR_UNMOUNTED_ROOT`| Host volume unmounted or disconnected | **System Error**| Transition assets to `ARCHIVE_OFFLINE`. Halt downloads; DO NOT re-download. |
| `MEDIA_ERR_PATH_ESCAPE` | Attempted traversal (`../`) outside root | **Fatal / Security** | Terminate request immediately. Log security alert (`INV-7`). |
| `MEDIA_ERR_PREMATURE_DELETE`| Retention prune attempted before all destinations terminal | **Policy Violation** | Abort deletion. Asset remains safe on disk (`INV-2`). |

---

## 3. Storage Hygiene & Orphan Sweep Loop

- A background janitor runs every 10 minutes:
  - Scans `{storage_root}/partials/*.part`.
  - If a `.part` file has no active downloading job holding it for > 30 minutes, it is classified as an orphan.
  - The orphan is securely deleted, logging bytes reclaimed to `media_event`.
  - Fixes Defect `D-10`: Disk space is never permanently leaked by interrupted downloads.
