# 08 — Testing Strategy & Definition of Done: Pipelines & Routing

**Pillar:** 3 · Pipelines & Routing · **Chapter:** Testing Strategy & DoD · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §9  
**Depends on:** All prior chapters in Pillar 3  
**Invariants enforced:** INV-5, INV-6, INV-9, INV-11, INV-12  

---

## 1. Test Suite Architecture

| Layer | Focus / Scope | Key Mocking Boundaries |
|---|---|---|
| **Unit Tests** | Filter logic (shorts, live, duration ranges), candidate sorting (backfill vs monitor) | In-memory candidate lists |
| **Deduplication Tests** | Enforce `INV-5`: Never generate candidate for already delivered pair | Mock Pillar 6 ledger responses |
| **Multi-Tenancy Tests** | Enforce `INV-9`: Independent cursor progression across multiple pipelines | Test database with 2 pipelines on 1 source |
| **AST / Boundary Tests** | Verify `src.pipelines` never imports `yt_dlp` or Google API clients | AST parser inspecting `src/pipelines` |

---

## 2. Invariant Enforcement Tests

### 2.1 Deduplication Guarantee (`INV-5`)
```python
def test_delivered_pair_is_never_returned_as_actionable(mock_catalog, mock_ledger):
    """Assert candidate batch excludes videos present in delivery ledger."""
    # Given video_1 delivered to dest_A
    # When get_candidate_batch is queried for dest_A
    # Then video_1 must have skip_reason == SkipReason.ALREADY_DELIVERED
    ...
```

### 2.2 Independent Multi-Pipeline Cursor Test (`INV-9`)
```python
def test_source_feeds_multiple_pipelines_with_independent_cursors():
    """Assert advancing cursor on Pipeline 1 leaves Pipeline 2 cursor unchanged."""
    ...
```

---

## 3. Definition of Done (DoD) Checklist

- [ ] All candidate universe attributes and filter controls specified.
- [ ] INV-5 deduplication strictly guaranteed against delivery ledger.
- [ ] INV-9 multi-pipeline source sharing tested and verified.
- [ ] INV-6 retention policies mapped deterministically in relational schema.
- [ ] Candidate preview UI accurately reflects skip reasons in dry run.
- [ ] AST boundary tests confirm zero downloads/uploads executed in this pillar.
