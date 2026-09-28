# 04 — Logic and Business Rules: Pipelines & Routing

**Pillar:** 3 · Pipelines & Routing · **Chapter:** Logic and Business Rules · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §5  
**Depends on:** `docs/PILLARS/03_PIPELINES_AND_ROUTING/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-6, INV-9, INV-11  

---

## 1. Candidate Selection Engine (`INV-5`)

### 1.1 Step-by-Step Candidate Pipeline Algorithm
When `get_candidate_batch(pipeline_id, limit)` is invoked:
1. **Pipeline Validation**: Verify pipeline exists and `status == 'ACTIVE'`. If paused/draft, return empty batch.
2. **Fetch Active Bindings**: Retrieve enabled sources (`pipeline_source`) and enabled destinations (`pipeline_destination`).
3. **Filter Profile Resolution**: Fetch linked `download_profile`.
4. **Catalog Query**:
   - For `BACKFILL` mode: Query `catalog_video` for each source where `published_at >= backfill_cursor_published_at`, ordered by `published_at ASC`.
   - For `MONITOR` mode: Query latest `catalog_video` records ordered by `published_at DESC`.
5. **Quality & Compliance Filtering**:
   - If `profile.skip_shorts` AND `video.is_short` (or `duration_seconds < 60`), mark `SHORTS_FILTERED`.
   - If `profile.skip_live_streams` AND `video.is_live`, mark `LIVE_FILTERED`.
   - If `duration_seconds` outside `[min_duration_s, max_duration_s]`, mark `DURATION_OUT_OF_BOUNDS`.
6. **Cross-Pillar Deduplication (`INV-5`)**:
   - Query Pillar 6 delivery ledger: `delivery.api.is_delivered_batch([(v.id, d.canonical_id)])`.
   - If delivered: mark `ALREADY_DELIVERED`.
7. **Destination Quota Check**:
   - Query Pillar 2: `destinations.api.check_quota_budget(d.id)`.
   - If `can_upload_now == False`: mark `DESTINATION_QUOTA_FULL`.
8. **Yield Actionable Batch**: Return first `limit` items where `skip_reason == NONE`.

```
Catalog Video ──▶ [ Profile Filters ] ──▶ [ Pillar 6 Ledger Check ] ──▶ [ Actionable Candidate ]
                         │                            │
                 Filtered: Shorts/Live        Delivered: Skip (INV-5)
```

---

## 2. Cursor Resumability & Multi-Tenancy (`INV-9`)

- Cursors are stored on `pipeline_source(pipeline_id, source_id, backfill_cursor_published_at)`.
- **Zero Cross-Talk**: If Source A is shared across Pipeline 1 (which backfills 2020-2024) and Pipeline 2 (which backfills 2023-2024), each pipeline advances its own cursor independently.
- **Crash Resilience**: Because the cursor is a published timestamp, if a worker crashes mid-batch, the next poll safely restarts from the last committed timestamp without skipping videos.
