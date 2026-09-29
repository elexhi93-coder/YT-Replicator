# youtube.CONTRACT — The Destination Platform (U09)

**Module:** `youtube` · **Status:** complete
**May import:** `core.api`, `accounts.api`, **`credentials.api`** (docs/04 §3).
`youtube` is the one domain module allowed a sibling import: Port B cannot work
without a token, and `credentials.api.valid_access_token` is U05's single
documented way to get one.
**Owns:** `destination_inventory`, `quota_usage` (docs/03 §8). It never writes
`delivery` — inventory is observation, not ownership (docs/03 §8 rule 1).

---

## 1. Public surface (`youtube.api`, INV-12)

| Symbol | Behaviour |
|---|---|
| `probe_auth(destination)` | Asks Google who the token belongs to; records the outcome on the destination row. → `AuthState`. |
| `sync_inventory(destination, *, cursor=None)` | One page of channel inventory, upserted. Returns `(items, next_cursor)`. |
| `mark_absent(destination, *, keep_ids=None)` | After a **complete** sync, marks unseen rows `is_present = false`. Never deletes. |
| `unclaimed_inventory(destination)` | Content we cannot account for. Surfaced for review, never auto-adopted (INV-8). |
| `upload(destination, request, *, on_progress=None)` | Charges the attempt, then uploads; `QuotaExhausted` is recorded as a spent day and re-raised. → `UploadOutcome`. |
| `quota_remaining(destination, *, day=None)` | Uploads left today, from our own count. Never negative. |
| `account_upload` / `record_quota_exhausted` / `quota_snapshot` | The accounting primitives `upload` and `quota_remaining` are built from. |
| `default_http()` | The real transport, built lazily. |

`youtube.adapter.YouTubePlatform` is the Port B adapter (`probe_auth`,
`sync_inventory`, `upload`, `unit_cost_for_upload`); `youtube.http.YouTubeHttp`
is its only network seam.

---

## 2. Errors

| Error | Classified as | Raised when |
|---|---|---|
| `YouTubeError` | permanent | Base for platform failures an operator must resolve. |
| `UploadRejected` | permanent | 400, or a 403 that is not quota. Retrying will not help. |
| `UploadNotFound` | permanent | 404 — no such upload session or video. |
| `TokenRevoked` | **permanent** | 401, or a 403 `forbidden`/`youtubeSignupRequired`. |
| `Throttled` | **transient** | 429. |
| `PlatformUnavailable` | **transient** | 5xx, timeout, network failure, or an unrecognised shape. |
| `QuotaExhausted` | **transient** | 403 `quotaExceeded`. |

`translate_error(status, body)` is the only place that mapping exists, and it is
tested exhaustively — it decides, per video, whether work is retried or failed.

---

## 3. Tests

`src/youtube/tests/test_youtube.py` — 32 tests, **no network**:

* **Error translation** (9): 429 transient, quota transient, 401 permanent,
  forbidden-as-revoked, 404 permanent, 5xx transient, 400 permanent, the message
  survives, an unmapped status still yields a typed error.
* **Inventory** (8): what the API said is written (including the marker), resync
  updates rather than duplicates, the page token is passed through, a video that
  reappears is present again, **a vanished video is never deleted**, only unseen
  rows are marked absent, unclaimed is surfaced not adopted, sync time recorded.
* **Quota** (7): a fresh allowance, **the day is YouTube's not UTC's** (D-03),
  units counted, remaining never negative, a new day is a new row, exhaustion
  marks the day spent, a throttled attempt costs one attempt.
* **Upload** (8): session then finalise, bytes sent in ranges, progress reaches
  the end, the attempt is charged, a revoked token surfaces permanently, a quota
  error marks the day spent and propagates, a missing session URL is a platform
  problem, the unit cost is the published one.

The channel fixture mints a **real encrypted token** rather than stubbing
`valid_access_token`, because that function refusing an unauthorised channel is
exactly the behaviour U05 built, and stubbing it away would test nothing.

---

## 4. Out of scope

Thumbnails (the field is carried in `UploadRequest` and reported as
`thumbnail_uploaded=False` until U14 wires the set step), the delivery ledger
(U10), and any UI (U16).

---

## 5. Reconciliations (decided here, recorded for U25)

1. **`destination_inventory.matched_delivery_id` has no FK constraint yet.**
   docs/03 §8 declares `REFERENCES delivery(id)`, but `delivery` is created by
   U10. The column exists so the table matches the documented shape, and U10's
   migration adds the constraint. Nothing writes the column until then, so no
   unreferential row can exist.
2. **`probe_auth(channel)` instead of `probe_auth(credentials: bytes)`.** The
   port's abstract signature hands the adapter an encrypted bundle to decrypt.
   Here the adapter takes the channel and calls
   `credentials.api.valid_access_token`, which is the one entry point that
   cannot skip the proactive-refresh rule. No plaintext secret appears in any
   signature, so the *intent* of the port rule (a decrypted secret never crosses
   a boundary) is better served, not weakened. The Protocol in `core` is
   unchanged.
3. **Two index names are shorter than docs/03 §8 wrote them.** Django caps
   index names at 30 characters and refused to migrate, so the migration wins
   (docs/03 §1): `destination_inventory_unclaimed_idx` → `inv_unclaimed_idx`,
   `destination_inventory_title_idx` → `inv_title_idx`. Columns, predicates and
   partial conditions are unchanged, and §8 was corrected in the same change.
4. **Quota is counted locally, not asked for.** The API reports quota by
   refusing an upload, so `quota_remaining` is derived from `quota_usage`. An
   authoritative `quotaExceeded` immediately calls `record_quota_exhausted`, so
   a refusal corrects our count in the same transaction rather than the next day.
