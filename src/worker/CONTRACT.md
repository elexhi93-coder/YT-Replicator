# worker — CONTRACT (U14)

**May import:** `core`, `accounts`, `jobs`, `media`, `delivery` (docs/04 §2).
Not `pipelines`, not `sources`, not `youtube` — which is why the upload plan
arrives through a port rather than a query.

**Holds no business rules.** What a download verifies, what a delivery records
and what retention decides are all answered by the modules that own them.

## Published API (`worker.api`)

| Function | Purpose |
|---|---|
| `run_once(worker_id) -> IterationResult` | Claim one job, do it, record the result. Never raises for a failed job. |
| `run_forever(worker_id, *, sleep_seconds, iterations)` | The loop. `iterations` bounds it for tests. |
| `recover(*, now, claim_timeout_minutes) -> RecoveryReport` | The restart sweep. Idempotent. |
| `IterationResult` / `RecoveryReport` | What one pass did / what the sweep found. |

## The three properties worth defending

1. **A pause is not a failure.** A gate that says "not now" calls
   `jobs.release()`, which returns the job to `queued` **without** counting an
   attempt and **without** writing a backoff. Five full disks must not cost a
   video all five of its attempts — that is the assertion the tests lead with.
2. **The error decides the fate, not the worker.** `TransientError` requeues
   with backoff; anything else is permanent. An unrecognised exception is
   failed visibly rather than stranding the job or looping on a crash.
3. **A crash is a non-event.** `recover()` returns expired claims to the queue,
   fails downloads stuck in `downloading`, and **reconciles** — never retries —
   an upload stuck in `uploading`, because we do not know whether the bytes
   landed and a duplicate on someone else's channel is the worse outcome.

## Deferred

- **U15** (`ops`) owns the scheduler cadence: the monitor, hydration, retention
  sweeps and reconciliation ticks. `run_forever` is the loop they hook into.
- **U18** owns routing rules; v1 delivers to every enabled destination.
