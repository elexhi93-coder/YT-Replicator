# 08 — Testing Strategy & Definition of Done: Delivery & Ledger

**Pillar:** 6 · Delivery & Ledger · **Chapter:** Testing Strategy & DoD · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §9  
**Depends on:** All prior chapters in Pillar 6  
**Invariants enforced:** INV-1, INV-2, INV-4, INV-8, INV-11, INV-12  

---

## 1. Test Suite Architecture

| Layer | Focus / Scope | Key Mocking Boundaries |
|---|---|---|
| **Unit Tests** | Provenance marker parsing, reconciliation matrix classification, status transitions | In-memory strings & records |
| **Durability Tests** | Enforce `INV-4`: Deleting pipeline/source records never cascades to delete delivery receipts | Real PostgreSQL 16 container |
| **Reconcile Before Retry Tests** | Enforce `INV-2`: Interrupted upload resumes via inventory check without duplicating uploads | Mock YouTube destination platform |
| **Uniqueness Tests** | Enforce `INV-1`: Duplicate insert for `DELIVERED_SUCCESS` pair fails on partial unique index | Database constraint test |

---

## 2. Invariant Enforcement Tests

### 2.1 Reconcile-Before-Retry Test (`INV-2`)
```python
def test_interrupted_upload_reconciles_before_retrying(mock_destination):
    """Assert interrupted upload checks destination inventory and avoids double upload."""
    # Given an in-flight delivery where worker crashed
    # And the remote destination actually received the video and has the provenance marker
    # When worker retries delivery
    # Then delivery is marked DELIVERED_SUCCESS without executing an upload call
    ...
```

### 2.2 Durability & No-Cascade Test (`INV-4`)
```python
def test_delivery_history_survives_source_and_pipeline_deletion(db_session):
    """Assert deleting a pipeline does not delete delivery attempts or receipts."""
    # Create pipeline, source, video, and delivery record
    # Delete pipeline (expect pipeline_id set to NULL)
    # Attempt to delete source/video (expect ON DELETE RESTRICT foreign key error)
    ...
```

---

## 3. Definition of Done (DoD) Checklist

- [ ] INV-1 unique partial index verified: duplicate delivery prohibited.
- [ ] INV-2 reconcile-before-retry protocol tested under simulated worker crash.
- [ ] INV-4 durability verified: delivery attempts and receipts survive upstream deletion.
- [ ] INV-8 unclaimed remote videos flagged and never silently adopted.
- [ ] Batch query APIs (`ADJ-P1-02` and `ADJ-P5-01`) pass performance benchmarks.
- [ ] CSV audit export produces RFC 4180 compliant delivery history.
