# 06 — Failures, Errors, and Recovery: Delivery & Ledger

**Pillar:** 6 · Delivery & Ledger · **Chapter:** Failures and Errors · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §7  
**Depends on:** `docs/PILLARS/06_DELIVERY_AND_LEDGER/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-4, INV-8  

---

## 1. Domain Error Classification

```
DeliveryLedgerError (base)
├── DuplicateDeliveryViolationError (INV-1 conflict attempt)
├── InterruptedUploadError (worker crashed mid-stream -> triggers INV-2 reconcile)
├── RemoteVideoNotFoundError (video was deleted on YouTube -> MISSING_EXPECTED)
├── MarkerMismatchError (video exists but belongs to different source)
└── CascadeDeleteProhibitedError (attempt to cascade delete delivery history, INV-4)
```

---

## 2. Exhaustive Error Catalog

| Error Code | Cause | Classification | Recovery / Action |
|---|---|---|---|
| `DELIV_ERR_INTERRUPTED` | Worker or process dropped during upload PUT | **Transient** | Do NOT immediately retry. Trigger reconcile-before-retry (`INV-2`). |
| `DELIV_ERR_DUPLICATE_PAIR` | Second delivery attempted for already delivered pair | **Invariant Violation** | Reject insert (`INV-1`). Fetch existing delivery receipt. |
| `DELIV_ERR_REMOTE_DELETED` | YouTube video deleted by user/moderation | **Reconciliation** | Transition to `REMOVED` upon operator confirmation. |
| `DELIV_ERR_UNCLAIMED_FOUND`| Video exists on YouTube without replication marker | **Reconciliation** | Mark `UNCLAIMED_PRESENT`. Alert operator (`INV-8`). |

---

## 3. Remote Interruption Recovery Loop (`INV-2`)

If a worker terminates while a delivery is in `IN_FLIGHT`:
1. The Job Engine Janitor marks the job for retry.
2. The retried worker enters `record_delivery_attempt_start`.
3. Before issuing any upload call to Pillar 2, the worker inspects `destination_inventory` or performs a direct `channels.list/videos.list` query searching for the unique provenance tag: `<!-- YTR:src={source_id}:vid={video_id} -->`.
4. If found:
   - YouTube already processed the prior attempt before the network dropped!
   - System updates `destination_video_id`, marks `DELIVERED_SUCCESS`, commits the attempt receipt, and skips physical re-upload.
5. If not found:
   - Safe to proceed with normal resumable chunk upload.
