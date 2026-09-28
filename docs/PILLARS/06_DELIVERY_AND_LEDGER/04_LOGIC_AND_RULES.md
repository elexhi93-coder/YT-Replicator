# 04 — Logic and Business Rules: Delivery & Ledger

**Pillar:** 6 · Delivery & Ledger · **Chapter:** Logic and Business Rules · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §5  
**Depends on:** `docs/PILLARS/06_DELIVERY_AND_LEDGER/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-4, INV-8, INV-11  

---

## 1. The Delivery Flow & Reconcile-Before-Retry Protocol (`INV-2`)

### 1.1 Step-by-Step Delivery Execution
When worker executes an upload task:
1. **Pre-Flight Ledger Check**: Verify `(catalog_video_id, destination_channel_id)` is not already `DELIVERED_SUCCESS` (`INV-1`).
2. **Reconcile-Before-Retry Check (`INV-2`)**:
   - If prior delivery attempt exists in `IN_FLIGHT` or failed transiently:
   - Query remote channel inventory or search by provenance marker `<!-- YTR:src={source_id}:vid={video_id} -->`.
   - If video is already present on YouTube:
     - Recover remote video ID.
     - Record success without re-uploading bytes!
     - Avoids duplicate upload and saves 1,600 API quota units.
3. **Execute Upload**:
   - Record attempt start in `delivery_attempt`.
   - Invoke `destinations.api.execute_upload(destination_channel_id, upload_input)`.
   - On Success: commit `DELIVERED_SUCCESS`, store `destination_video_id`, commit attempt.
   - On Failure: record error in `delivery_attempt`.

```
[ Upload Task Started ]
          │
          ▼
Prior attempt in-flight / crashed?
     │                  │
    YES                 NO
     │                  │
     ▼                  │
[ Query Remote Channel Inventory (INV-2) ]
     │                  │
   Found?               │
  ┌──┴──┐               │
 YES    NO              │
  │      └──────┬───────┘
  │             │
  │             ▼
  │     [ Execute Upload via Pillar 2 Adapter ]
  │             │
  │       ┌─────┴─────┐
  │    Success     Failure
  │       │           │
  ▼       ▼           ▼
[ Mark DELIVERED_SUCCESS ]  [ Record Attempt Error ]
[ Update Ledger Receipt  ]  [ Transient / Permanent ]
```

---

## 2. High-Efficiency Batch Queries (`ADJ-P1-02`, `ADJ-P5-01`)

### 2.1 Fast Catalog Delivery Status (`ADJ-P1-02`)
To support the Pillar 1 catalog grid without N+1 queries:
```sql
SELECT catalog_video_id
FROM delivery
WHERE destination_channel_id = :destination_channel_id
  AND status = 'DELIVERED_SUCCESS'
  AND catalog_video_id IN (
      SELECT id FROM catalog_video WHERE source_id = :source_id
  );
```
Returns a fast `Set[str]` in single indexed round-trip.

### 2.2 Terminal Destination Retention Check (`ADJ-P5-01`)
```sql
SELECT COUNT(*) = 0 AS all_terminal
FROM pipeline_destination pd
LEFT JOIN delivery d ON d.destination_channel_id = pd.destination_channel_id 
                    AND d.catalog_video_id = :catalog_video_id
WHERE pd.pipeline_id = :pipeline_id
  AND pd.is_enabled = TRUE
  AND (d.status IS NULL OR d.status NOT IN ('DELIVERED_SUCCESS', 'FAILED_PERMANENT'));
```
If `all_terminal == True`, Pillar 5 is permitted to delete local media file (`INV-2`).
