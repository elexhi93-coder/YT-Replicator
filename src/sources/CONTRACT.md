# sources.CONTRACT — Sources & Catalog (U07)

**Module:** `sources` · **Status:** complete (Wave 1)
**May import:** `core.api`, `accounts.api` (docs/04 §3). Nothing else.
**Owns:** `source`, `catalog_video` (docs/03 §5) and the Port A adapter. It
never downloads media bytes (INV-7) — files belong to `media` (U11).

---

## 1. Public surface (`sources.api`, INV-12)

| Symbol | Signature | Behaviour |
|---|---|---|
| `add_source(workspace, url, *, name="")` | → `Source` | SSRF allow-list first (`normalize_source_url`), then resolve the canonical id. Idempotent on `(workspace, external_id)`. Raises `SourceUrlInvalid`, `SourceUnresolvable`. |
| `list_sources(workspace, *, include_inactive=False)` | → `list[Source]` | Ordered by name. Soft-deleted rows are never returned. |
| `scan(source, *, since=None)` | → `ScanOutcome` | One flat, metadata-only pass; upserts on `(source, video_id)`. `since=None` is a full pass and additionally marks vanished videos unavailable — never deleted. Raises `SourceUnresolvable`/`ItemGone` after recording `scan_status='error'`. |
| `hydrate(batch)` | → `HydrateOutcome` | Lazy: a row with `hydrated_at` set is skipped without a call. An item the platform no longer serves is counted and marked, not raised (F-48). Transient failures propagate for `jobs` to retry. |
| `source_provider_factory()` | → `SourceProvider` | The Port A binding installed at startup by `ui.apps.UiConfig.ready`. |
| `ScanOutcome` / `HydrateOutcome` | frozen dataclasses | `source_id/discovered/created/updated/marked_unavailable/skipped` and `requested/hydrated/unavailable/skipped`. |

No function retries (Pillar 0 R6) — `jobs` owns the retry policy.

### 1.1 Module layout

* `models.py` — `source`, `catalog_video` with the CHECK constraints and indexes of docs/03 §5.
* `urls.py` — the two guards every operator URL passes: `to_https`, `normalize_source_url` (INV-7).
* `errors.py` — typed errors (§2).
* `provider.py` — `YouTubeSourceProvider`, the only code that shells out to yt-dlp. No DB writes (R2).
* `dto.py` — the frozen outcome types.
* `api.py` — this surface; the only writer of both tables.

---

## 2. Errors

| Error | Parent(s) | Classified as | Raised when |
|---|---|---|---|
| `SourceError` | `PermanentError` | permanent | Base for every operator-resolvable failure. |
| `SourceUrlInvalid` | `SourceError` + `SourceUrlRejected` | permanent | Not a usable YouTube URL: bad host, `http://`, or a single video. |
| `SourceUnresolvable` | `SourceError` | permanent | Well-formed URL, nothing behind it. |
| `SourceNotFound` / `CatalogVideoNotFound` | `SourceError` | permanent | A lookup matched no row. |
| `ItemGone` | `SourceError` + `ItemUnavailable` | permanent | Deleted, private or geo-blocked upstream. |
| `HydrationRateLimited` | `RateLimitExceeded` (hence transient) | **transient** | HTTP 429 — cool off and continue (INV-7). |
| `ProviderUnavailable` | `TransientError` | **transient** | yt-dlp missing, timed out, or would not run. |

`isinstance(err, TransientError)` stays the single retry test.

---

## 3. Tests

`src/sources/tests/test_sources.py` — 22 tests; `src/core/tests/test_registry.py` — 8.

* **URL guards** (7): channel/playlist/handle shapes, `/videos` tab, non-YouTube host, `http://`, single video, blank, permanent classification.
* **Add** (4): scoped row, idempotency, SSRF refusal before any call, soft-delete hidden.
* **Scan** (9): create/update counts, status + counters, vanish-marking, bounded scans never marking, operator flags surviving a rescan, availability translation, typed failure with the error recorded.
* **Hydrate** (4): expensive fields filled, lazy repeat batch, one gone item does not fail the batch, batch-wide transient failure propagates.
* **Classification** (4): throttle and missing extractor are transient; unresolvable, gone and invalid URL are permanent.

No test touches the network or yt-dlp: `FakeProvider` replaces the port binding
through the registry — the same seam `worker` and `media` use.

---

## 4. Out of scope

Downloading media (`media`, U11), routing candidates (`pipelines`, U06), queueing
(`jobs`, U08), and any UI page (U17).

---

## 5. Reconciliations (decided here, recorded for U25)

1. **`catalog_video.tags` storage.** docs/03 §5 declares `text[]`; the Django field
   is `JSONField`, because the test harness runs SQLite and `text[]` has no SQLite
   equivalent. On PostgreSQL this emits `jsonb`; `03` §2.1 already records the
   pattern for `authorized_channel.scopes`.
2. **Pillar 1's `03_INTERFACE_CONTRACT.md` names `register_source`/`execute_source_scan`
   over UUID ids.** The numbered build set wins (docs/README: the `00`–`07` set is
   authoritative), so the surface follows docs/04 §5 — `add_source`, `scan`,
   `hydrate` — over the `bigint` keys of docs/03. The Pillar chapter stays
   `drafting` and is reconciled in U25.
3. **`add_source` resolves the workspace from its argument, not from the request.**
   Views resolve scope through `accounts.api.current_workspace(request)` and pass
   the result in, so the service layer never reaches for a request object.
4. **`add_source` is idempotent, not raising on duplicates.** Re-registering the
   same channel satisfies the operator either way; Pillar 1's `DuplicateSourceError`
   has no counterpart in docs/03 §5, which defines uniqueness as a constraint.
5. **`scan()` is not one transaction.** See its docstring: a single `atomic` block
   would roll back the `SCAN_ERROR` status together with the exception, and the
   partial-progress behaviour of F-48 would be lost.
