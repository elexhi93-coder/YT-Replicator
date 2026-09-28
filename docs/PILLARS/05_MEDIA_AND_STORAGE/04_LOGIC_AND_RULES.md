# 04 — Logic and Business Rules: Media & Storage

**Pillar:** 5 · Media & Storage · **Chapter:** Logic and Business Rules · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §5  
**Depends on:** `docs/PILLARS/05_MEDIA_AND_STORAGE/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-2, INV-3, INV-6, INV-7, INV-10, INV-11  

---

## 1. Safe Acquisition & Atomic Verification Protocol (`INV-3`)

### 1.1 Free Space Admission Gate
Before executing `yt-dlp`:
1. Check `storage_root.free_space_bytes`.
2. If `free_space_bytes < 10 * 1024^3` (10 GB floor):
   - Reject acquisition with `DiskSpaceFloorReachedError`.
   - Halts download before disk saturation.

### 1.2 Two-Phase Atomic Placement
1. **Phase 1 (Stream to Temporary Path)**:
   - Target path: `{root_path}/partials/{asset_id}.part`.
   - `yt-dlp` extracts streams according to resolution caps (e.g. `format="bestvideo[height<=1080]+bestaudio/best"`).
2. **Phase 2 (Verification & Atomic Commit)**:
   - File size is checked: must be > 0 bytes.
   - Streaming SHA-256 is computed across the file bytes.
   - If verification passes:
     - Final path: `{root_path}/videos/{sha256}.{container}`.
     - Atomic rename: `os.replace(partial_path, final_path)` (POSIX/Windows atomic file rename).
     - Database record updated: `state = 'ON_DISK'`, `byte_size = :size`, `sha256 = :hash`, `verified_at = NOW()`.
     - Log `media.asset.verified` event.
   - If verification fails or download is aborted:
     - Delete partial file.
     - Reset `state = 'EXPECTED'`.

---

## 2. Retention Evaluation & Single Deletion Choke-Point (`INV-2`, `INV-10`)

### 2.1 The Terminal Destination Invariant (`INV-2`)
A media asset is eligible for automated deletion under retention policy `DELETE_AFTER_UPLOAD`
**ONLY IF**:
1. The asset is NOT pinned (`is_pinned == False`).
2. Every destination channel bound to the pipeline has reached a **terminal state** in the
   Pillar 6 delivery ledger: either `DELIVERED_SUCCESS` or `FAILED_PERMANENT`.
3. If any destination is still pending, queued, or running, deletion is strictly forbidden.

### 2.2 The Four Retention Modes
1. **`KEEP`**: Asset is never pruned automatically.
2. **`DELETE_AFTER_UPLOAD`**: Pruned once all enabled pipeline destinations reach terminal status (`INV-2`).
3. **`PURGE_AFTER_7_DAYS`**: Hard retention backstop: pruned 7 days after delivery completion.
4. **`MANUAL`**: Pruning occurs only upon explicit operator intervention in UI.

### 2.3 Mandatory Dry-Run Pipeline (`INV-10`)
All deletions must pass through the simulation engine:
```
[ Trigger Retention Sweep ]
           │
           ▼
[ Query Unpinned ON_DISK Assets ]
           │
           ▼
[ Ledger Cross-Check: All Destinations Terminal? (INV-2) ]
     │                           │
     ├─ NO ──> Skip Asset        └─ YES ──> Add to Candidates
                                                │
                                                ▼
                                    [ Generate Dry-Run Token ]
                                    [ Display Summary in UI ]
                                                │
                                        Operator Confirms
                                                │
                                                ▼
                                    [ Atomic OS Unlink ]
                                    [ media_asset.state = DELETED ]
                                    [ Append to media_event Audit ]
```

---

## 3. Path Traversal & Safe Root Boundary Defense (`INV-7`)

To prevent arbitrary filesystem reading or deletion:
```python
def resolve_safe_path(storage_root: Path, relative_path: str) -> Path:
    """Enforce INV-7: Ensure relative path strictly resolves inside storage root."""
    resolved_root = storage_root.resolve()
    candidate_path = (storage_root / relative_path).resolve()
    
    if not candidate_path.is_relative_to(resolved_root):
        raise PathTraversalSecurityError(f"Path escape attempt detected: {relative_path}")
        
    return candidate_path
```
All filesystem calls (`exists`, `stat`, `unlink`, `replace`) MUST operate solely on
verified `resolve_safe_path` results.
