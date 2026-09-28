# 00 — Pillar Overview & The Media Storage Universe

**Pillar:** 5 · Media & Storage · **Chapter:** Pillar Overview · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/05` §1-§4  
**Invariants touched:** INV-2, INV-3, INV-6, INV-7, INV-10, INV-11, INV-12  

---

## 1. Mission

Pillar 5 is the **sole and exclusive owner of physical files on disk** across the entire
YT-Replicator architecture. It acquires media streams safely using `yt-dlp` according to
pipeline quality profiles, verifies size and SHA-256 hashes prior to release (`INV-3`),
enforces strict path traversal defenses within configured storage roots (`INV-7`), and
executes retention policies with single-point-of-deletion control and mandatory dry-run
previews (`INV-10`).

By eliminating all direct filesystem access from other modules, it resolves legacy defects
`D-08` (seven conflicting deletion owners) and `D-09` (multiple conflicting storage directory layouts).

---

## 2. Owns vs. Does Not Own

### 2.1 What This Pillar Owns
- **The `storage_root` entity**: Registration of filesystem roots, mount detection, free-space
  threshold admission gating (stops downloads when free space drops below 10 GB).
- **The `media_asset` entity**: Canonical registry of media files on disk, storing absolute path,
  byte size, container format, video resolution, SHA-256 checksum, and lifecycle state.
- **The `media_event` append-only audit trail**: Recording all media downloads, verifications,
  integrity failures, renames, and deletions with operator attribution.
- **Acquisition Engine (`yt-dlp`)**: Executing media extraction obeying resolution limits and
  format preferences from Pillar 3.
- **Atomic Two-Phase Verification**: Downloading files to temporary `.part` paths, computing
  checksums, and executing an atomic OS rename to the final file name only after verification (`INV-3`).
- **Retention Evaluator & Sweeper**: Applying pipeline retention policies (`KEEP`, `DELETE_AFTER_UPLOAD`,
  `PURGE_AFTER_7_DAYS`) with mandatory dry-run previews (`INV-10`), checking that all enabled
  destinations are terminal before deleting (`INV-2`).
- **Hygiene & Orphan Reaper**: Background cleanup of abandoned `.part` files and temporary thumbnails.
- **Rehydration & Pinning**: Enabling on-demand re-download of previously deleted media with
  protection against automated pruning.

### 2.2 What This Pillar Does NOT Own

| Responsibility | Owning Pillar | Reason for Boundary |
|---|---|---|
| Deciding which video replicates where | **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Pipeline policies dictate candidate pairings. |
| Uploading media to YouTube | **Pillar 2** (`02_DESTINATIONS_AND_AUTH`) | Pillar 2 owns OAuth tokens and resumable chunking. |
| Recording delivery receipts | **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Pillar 6 is the sole authority on what was delivered. |
| Managing execution queues & worker leases | **Pillar 4** (`04_JOB_ENGINE`) | Pillar 4 orchestrates task leases. |
| Video transcode / transformation in v1 | **Nobody** (Decision D15) | No FFmpeg re-encoding in v1; direct container pass-through. |
| Filesystem access outside this module | **Nobody** | Strictly forbidden across all other pillars. |

---

## 3. The Media & Storage Universe (Leaf-Level Registry)

All attributes governing physical storage assets, roots, and retention states:

| Attribute Name | Entity / Context | Data Type | Default / Constraints | Notes |
|---|---|---|---|---|
| `root_path` | `storage_root` | `str(512)` | Path string | Base directory on host (e.g. `/data/media` or `D:\media`). |
| `is_mounted` | `storage_root` | `bool` | Live probe | False if external volume unmounted (triggers `ARCHIVE_OFFLINE`). |
| `free_space_bytes` | `storage_root` | `int` | Live probe | Free storage available; admission stops if `< min_free_floor_bytes`. |
| `min_free_floor` | `storage_root` | `int` | `10 * 1024^3` (10 GB) | Minimum safety buffer to prevent disk exhaustion. |
| `asset_id` | `media_asset` | `UUID` | Primary Key | Canonical media asset UUID. |
| `catalog_video_id` | `media_asset` | `UUID` | Foreign Key (P1) | Links media to source video record. |
| `relative_path` | `media_asset` | `str(512)` | `videos/{id}.mp4` | Relative path inside storage root (`INV-7`). |
| `byte_size` | `media_asset` | `int` | Verified file size | Must be > 0 before marked `ON_DISK` (`INV-3`). |
| `sha256` | `media_asset` | `str(64)` | Hex digest | Computed post-download, verified before upload (`INV-3`). |
| `container` | `media_asset` | `str(8)` | `'mp4'`, `'mkv'`, `'webm'`| Physical file container format. |
| `state` | `media_asset` | `enum` | `'EXPECTED'` | `EXPECTED`, `DOWNLOADING`, `ON_DISK`, `DELETED`, `ARCHIVE_OFFLINE`. |
| `is_pinned` | `media_asset` | `bool` | `False` | When True, exempt from automated retention pruning. |
| `verified_at` | `media_asset` | `TIMESTAMPTZ`| Nullable | Timestamp when checksum and size verification succeeded. |
| `deleted_at` | `media_asset` | `TIMESTAMPTZ`| Nullable | Timestamp of physical file removal from disk. |

---

## 4. Media Asset Lifecycle State Machine

```
      [ CANDIDATE ENQUEUED ]
                │
                ▼
        ┌──────────────┐
        │   EXPECTED   │ (record created)
        └──────────────┘
                │
         download starts
                │
                ▼
        ┌──────────────┐
        │ DOWNLOADING  │ (file written to .part path)
        └──────────────┘
                │
         checksum + size verified
         atomic rename to .mp4
                │
                ▼
        ┌──────────────┐
        │   ON_DISK    │ (ready for upload; INV-3)
        └──────────────┘
           │        │
   retention prune  │ drive unmounted
   (INV-2, INV-10)  ▼
           │  ┌──────────────────┐
           │  │ ARCHIVE_OFFLINE  │ (drive detached)
           ▼  └──────────────────┘
    ┌──────────────┐
    │   DELETED    │ (file unlinked; tombstone kept)
    └──────────────┘
```

