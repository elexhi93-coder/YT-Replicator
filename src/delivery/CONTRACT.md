# delivery.CONTRACT — The Delivery Ledger (U10)

**Module:** `delivery` · **Status:** complete
**May import:** `core.api`, `accounts.api`, `youtube.api`, `jobs.api` (docs/04 §3).
**Owns:** `delivery`, `delivery_attempt` (docs/03 §8). It never touches
`destination_inventory` except through `youtube.api`.

---

## 1. Public surface (`delivery.api`, INV-12)

| Symbol | Behaviour |
|---|---|
| `deliver(destination, *, source_video_id, media_path, title, description="", source_title="", tags=(), category_id="", privacy="", job=None, origin="system")` | → `DeliveryResult`. Writes the delivery row **first** (the marker embeds its id), then the attempt, then uploads. Raises `AlreadyDelivered` if the pair is already uploaded, `MediaMissing` if the file is absent, and the platform's typed error after recording the failure. |
| `reconcile(destination)` | → `ReconcileReport` with the four outcomes. Never mutates the ledger. |
| `mark_removed(delivery, reason)` | Operator confirmation that a copy is gone. Requires a reason and an `uploaded` delivery. |
| `get_delivery` / `list_deliveries` / `attempts_for` | Reads for the History page (U20). |
| `parse_marker(description)` | → `(source_video_id, delivery_id)` or `None`. The parse half of the Pillar 0 marker format. |

`origin` (`system`/`retry`/`manual`) answers "why did this upload happen twice?" —
the question the legacy had no answer for.

---

## 2. Errors

| Error | Raised when |
|---|---|
| `DeliveryError` | Base for the module. |
| `DeliveryNotFound` | No delivery matches the lookup. |
| `AlreadyDelivered` | The pair is uploaded and still present. **Not** a failure to retry — the memory rule is *reconcile before retrying*. |
| `MediaMissing` | The media file is not on disk (U11 owns downloads). |
| `InvalidDeliverySetting` | A value outside the CHECK vocabulary; carries `field`/`value`. |

---

## 3. Tests

`src/delivery/tests/test_delivery.py` — 28 tests, no network:

* **Deliver** (12): current truth recorded, the marker carries the delivery id,
  the marker is *appended* so the body survives, the source title is snapshotted,
  one attempt per delivery, a second delivery refused (with no second upload),
  missing media refused before any row, an invalid origin refused, a failure
  recorded then raised, a failure leaves the pair retryable, **the superseded id
  survives a re-upload**, the job is remembered, the inventory row is claimed.
* **Reconcile** (8): a healthy channel is `claimed_ok`, a foreign video is
  `unclaimed_present` and never adopted, a deleted copy is `missing_expected`
  and **not re-uploaded**, a missing inventory row also counts as missing, an
  orphan marker is `marker_mismatch`, absent rows are not counted as present,
  the review count, and the inventory match is a real foreign key.
* **Mark removed** (4): the reason is recorded, a reason is required, only an
  uploaded delivery can be removed, and the attempts survive the verdict.
* **Marker parsing** (3): round-trip, absent, and a lookalike is rejected.

---

## 4. Out of scope

Thumbnails, retention (`media`, U12), and the History page (U20).

---

## 5. Reconciliations (decided here, recorded for U25)

1. **`destination_inventory.matched_delivery_id` became a foreign key here.** U09
   shipped it as a plain `bigint` because `delivery` did not exist; this unit
   turned it into the `REFERENCES delivery(id) ON DELETE SET NULL` docs/03 §8
   always declared. The column name is unchanged (Django's FK attname), so no
   query or index moved. The migration drops the partial index first, because
   SQLite refuses to drop a column an index refers to — a failure invisible on
   PostgreSQL, and caught only because the suite runs on SQLite.
2. **Inventory is read through `youtube.api`, never through `youtube.models`.**
   The boundary test rejected the direct import, correctly: `delivery` needs to
   see the channel's state, so `youtube.api` publishes `inventory_rows()` (a
   read-only view), `claim_inventory()` (the one write the ledger makes), and
   the error classes `delivery` must tell apart.
3. **A failed attempt re-uses the delivery row rather than creating a second
   one.** The pair is the unit of history; the attempt is the unit of tries.
4. **`reconcile` never writes.** A missing video is evidence, not a verdict: the
   report is for a human, and `mark_removed` is the separate, manual step that
   records the conclusion.
5. **`missing_expected` triggers on `is_present = false`, not on a missing
   row.** A video observed once and then never again is the normal shape of a
   deleted copy; treating "row absent" as the only signal would miss it.