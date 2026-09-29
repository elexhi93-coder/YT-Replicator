# jobs.CONTRACT — The Job Queue (U08)

**Module:** `jobs` · **Status:** complete
**May import:** `core.api`, `accounts.api` (docs/04 §3). **No sibling at all** —
`jobs` is in the independence contract. A pipeline and an optional source
arrive as model instances; the module never imports either.
**Owns:** `job` (docs/03 §7). The database *is* the queue (D3): no Redis, no
Celery, no broker.

---

## 1. Public surface (`jobs.api`, INV-12)

| Symbol | Behaviour |
|---|---|
| `enqueue(workspace, pipeline, source_video_id, *, intent="upload", priority=None, source=None)` | → `Job` in `queued`, or **the live job that already exists**. Dedup is enforced by the partial unique index and the `IntegrityError` it raises — not by a lookup first, which would race. `priority` defaults to the pipeline's. |
| `claim(worker, *, lease_minutes=15)` | → the next queued `Job`, or `None`. One statement: `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id`. Sets `claimed_by`, `claimed_at`, `claim_expires_at`, and `started_at` (once). |
| `succeed(job)` | → terminal `uploaded`, `finished_at` set, lease cleared, any previous error cleared. |
| `fail(job, error, *, retry=True)` | Classifies by the **error's own type**: `TransientError` → back to `queued` with exponential backoff; anything else → `failed_permanent`. `retry=False` forces the permanent outcome. `error_code`/`error_message` are recorded either way. |
| `requeue_stale(*, now=None)` | Returns expired `claimed` jobs to `queued`; returns the count. Idempotent. |
| `cancel(job)` / `skip(job, reason)` | Terminal. Both free the dedup key, so the operator can deliberately re-run. `skip` requires a non-empty reason. |
| `get_job(job_id)` / `list_jobs(workspace, *, status=None, pipeline=None)` | Queue order: priority, then age. |
| `backoff_for(attempt)` / `DEFAULT_LEASE_MINUTES` / `MAX_ATTEMPTS` | 15-minute lease, 5 attempts, 1→2→4→8→16 minutes, capped at an hour. |

A job that *fails* is data, not an exception: the worker must survive it, so
`fail` records the outcome and returns the row.

---

## 2. Errors

All `PermanentError`. These are for misuse of the queue, never for a job that
merely failed.

| Error | Raised when |
|---|---|
| `JobError` | Base for the module. |
| `JobNotFound` | No job matches the lookup. |
| `InvalidJobSetting` | A value outside the schema's CHECK vocabulary (intent, worker name, empty skip reason); carries `field`/`value`. |
| `InvalidJobTransition` | A change the state machine forbids, e.g. succeeding an already-finished job; carries `current`/`requested`. |

---

## 3. Tests

`src/jobs/tests/test_jobs.py` — 37 tests:

* **Dedup** (9): queue defaults, duplicate returns the live job, intent and
  video are separate keys, cancel and skip free the key, **the database itself
  refuses a second live job** (`IntegrityError`, bypassing the API), invalid
  intent, source attachment.
* **Claim** (7): takes a queued job and stamps the lease, empty queue, **a
  claimed job is never handed to a second worker** (the P11 race), priority then
  age ordering, a backing-off job is not offered, it returns after its delay,
  worker name required.
* **Success** (3): finishes and clears the lease, clears a previous error, no
  double success.
* **Classification** (7): transient requeues with backoff, permanent stops,
  `retry=False` overrides, a permanent job is not claimable, **attempts are
  capped**, backoff grows and is capped, no failing a finished job.
* **Recovery** (4): an expired lease is recovered, a live one is left alone,
  idempotent, and the recovered job is claimable again.
* **Skip/cancel** (4): the reason is recorded and required, cancel, and no
  cancelling a finished job.
* **Listing** (3): queue order, filters, missing job.

**These run on SQLite, which cannot check the production claim.** The
`FOR UPDATE SKIP LOCKED` statement, the `UPDATE … RETURNING` and the partial
unique index were verified separately against the live PostgreSQL 16 database:
two workers took two different jobs, the third claim returned nothing, priority
order held, a backing-off job was not offered, and an expired lease was
recovered.

---

## 4. Out of scope

Dispatching the work — which module performs a download or an upload — belongs
to `worker` (U14). Quota accounting is `youtube`/`delivery` (U09/U10). The
Queue page is U19.

---

## 5. Reconciliations (decided here, recorded for U25)

1. **`claim_expires_at` does double duty.** While `claimed` it is the lease; while
   `queued` after a transient failure it is the *retry-after* moment, and the
   claim query honours it. docs/03 §7 has no `next_attempt_at` column, and
   adding one would put the model ahead of the schema. A consequence worth
   knowing: backoff survives a restart, which a `sleep()` never could.
2. **`MAX_ATTEMPTS` and the backoff curve are code, not configuration.** They
   are documented defaults in this CONTRACT and constants in `api.py`; making
   them operator-tunable is an `app_setting` decision (U14/U22), not this unit's.
3. **Success is `uploaded` for every intent.** The `status` CHECK in docs/03 §7
   is spelled in upload terms and has one success value, so an `inspect` or
   `rehydrate` job also lands on `uploaded`. The vocabulary should gain a
   neutral `succeeded`; that is a schema change for U25, not a silent one here.
4. **The claim falls back to an unlocked statement off PostgreSQL.** SQLite has
   no row locking, and the suite runs there (INV-10 permits SQLite in tests, not
   production). The fallback is selected by
   `connection.features.has_select_for_update_skip_locked`, so production always
   takes the locked path; the two statements differ only by that clause.
