# 00 — Pillar Overview & The Delivery Ledger Universe

**Pillar:** 6 · Delivery & Ledger · **Chapter:** Pillar Overview · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/06` §1-§4  
**Invariants touched:** INV-1, INV-2, INV-4, INV-8, INV-11, INV-12  

---

## 1. Mission

Pillar 6 is the **definitive source of truth for replication delivery**. It orchestrates the
actual delivery of verified media to destination channels via Pillar 0's `DestinationPlatform`
port, records execution history **twice** (what we attempted, and what the destination platform
actually reflects), and reconciles internal state against remote reality.

It enforces the permanent durability of delivery history (`INV-4`), ensures that every video
replicates at most once per destination (`INV-1`), mandates inventory reconciliation before
retrying interrupted uploads (`INV-2`), and flags remote non-replicated videos without
silently adopting them (`INV-8`).

---

## 2. Owns vs. Does Not Own

### 2.1 What This Pillar Owns
- **The `delivery` entity**: Current state of one `(catalog_video_id × destination_channel_id)` pair,
  linking `source_video_id` to `destination_video_id` with execution status.
- **The `delivery_attempt` entity**: Immutable append-only log of every upload attempt, duration,
  bytes transferred, HTTP status codes, and error tracebacks.
- **The `destination_inventory` entity**: Cached catalog of videos observed on destination channels,
  storing external video ID, title, description, and parsed provenance markers.
- **Reconciliation Engine**: Comparing internal ledger against external inventory, classifying into:
  `claimed_ok`, `unclaimed_present`, `missing_expected`, and `marker_mismatch`.
- **The "Reconcile Before Retry" Rule**: Interrupted or timed-out uploads must query the remote
  channel before re-uploading to prevent duplicate uploads (`INV-2`).
- **Provenance Marker Parser**: Extracting `src` and `vid` IDs from YouTube descriptions.
- **Mark-as-Removed**: Manual operator tombstone acknowledging a video was intentionally deleted
  from the remote destination.

### 2.2 What This Pillar Does NOT Own

| Responsibility | Owning Pillar | Reason for Boundary |
|---|---|---|
| YouTube API HTTP calls & OAuth tokens | **Pillar 2** (`02_DESTINATIONS_AND_AUTH`) | Pillar 2 implements the upload adapter. |
| YouTube quota arithmetic & limits | **Pillar 2** (`02_DESTINATIONS_AND_AUTH`) | Quota is owned by the auth pillar. |
| Downloading and hashing media files | **Pillar 5** (`05_MEDIA_AND_STORAGE`) | File bytes are owned exclusively by Pillar 5. |
| Deleting local media after upload | **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Retention evaluation and unlinks belong to storage. |
| Scheduling worker jobs and claims | **Pillar 4** (`04_JOB_ENGINE`) | Worker leases are managed by the Job Engine. |
| Deciding which videos qualify | **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Candidate routing is decided by pipelines. |

---

## 3. The Delivery & Ledger Universe (Leaf-Level Registry)

All attributes governing delivery records, attempts, and inventory tracking:

| Attribute Name | Entity / Context | Data Type | Default / Constraints | Notes |
|---|---|---|---|---|
| `delivery_id` | `delivery` | `UUID` | Primary Key | Canonical delivery UUID. |
| `catalog_video_id` | `delivery` | `UUID` | Foreign Key (P1) | `ON DELETE RESTRICT` (`INV-4`). |
| `destination_channel_id`| `delivery` | `UUID` | Foreign Key (P2) | `ON DELETE RESTRICT` (`INV-4`). |
| `pipeline_id` | `delivery` | `UUID` | Foreign Key (P3) | `ON DELETE SET NULL` (`INV-4`). |
| `destination_video_id` | `delivery` | `str(32)` | Nullable | YouTube video ID created on destination channel. |
| `status` | `delivery` | `enum` | `'PENDING'` | `PENDING`, `IN_FLIGHT`, `DELIVERED_SUCCESS`, `FAILED_PERMANENT`, `REMOVED`. |
| `marker_verified` | `delivery` | `bool` | `False` | True if provenance marker confirmed via inventory scan. |
| `reconciliation_state` | `delivery` | `enum` | `'UNRECONCILED'` | `claimed_ok`, `unclaimed_present`, `missing_expected`, `marker_mismatch`. |
| `attempt_id` | `delivery_attempt` | `UUID` | Primary Key | Immutable attempt record. |
| `attempt_number` | `delivery_attempt` | `int` | Sequential | Attempt ordinal (1, 2, ...). |
| `duration_ms` | `delivery_attempt` | `int` | Milliseconds | Upload duration from session start to completion. |
| `error_code` | `delivery_attempt` | `str(64)` | Nullable | Canonical error identifier if attempt failed. |
| `error_detail` | `delivery_attempt` | `TEXT` | Nullable | Sanitized error detail / response body. |

---

## 4. The Four Reconciliation Outcomes

```
           Ledger says: DELIVERED_SUCCESS?
                    │
       ┌────────────┴────────────┐
       ▼ YES                     ▼ NO
  Video on Remote?          Video on Remote?
    ┌──────┴──────┐           ┌──────┴──────┐
    ▼ YES         ▼ NO        ▼ YES         ▼ NO
Marker match?  [MISSING_   Marker match?  [NOTHING_TO_DO]
  ┌───┴───┐     EXPECTED]    ┌───┴───┐
  ▼ YES   ▼ NO               ▼ YES   ▼ NO
[CLAIMED  [MARKER_         [RECOVER  [UNCLAIMED_
   OK]    MISMATCH]        ADOPTION]  PRESENT] (INV-8)
```
