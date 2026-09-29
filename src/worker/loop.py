"""
worker.loop — the run loop (U14, docs/04 §7.1).

The whole module is orchestration. It holds **no business rules**: what a
download verifies, what retention decides and what a delivery records are all
answered by the modules that own them. What lives here is the order of
operations and the classification of what comes back.

```
run_once()
  claim                      # jobs - atomic, SKIP LOCKED
  gates                      # quota / disk / operator: a pause, not a failure
  dispatch by intent         # upload | rehydrate | inspect
  succeed                    # jobs
```

Three properties are the design:

* **A pause is not a failure.** When a gate says "not now", the job goes back
  to `queued` with a reason and its attempt counter is *not* incremented. A
  full disk must not burn a video's five attempts (docs/05 §10).
* **The error decides the fate, not the worker.** A `TransientError` requeues
  with backoff; anything else is permanent. The worker never guesses.
* **A crash is a non-event.** The claim is a lease with an expiry, and
  `recovery.recover()` sweeps what a dead worker left behind on start-up.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.api import PermanentError, TransientError, get_upload_planner
from delivery.api import deliver
from jobs.api import claim, fail, release, succeed
from media.api import acquire, rehydrate
from worker import gates

__all__ = ["IterationResult", "run_once", "run_forever"]


@dataclass(frozen=True)
class IterationResult:
    """What one pass of the loop did. Reported, never raised."""

    claimed: bool
    outcome: str          # "succeeded" | "requeued" | "failed" | "idle"
    job_id: int | None = None
    detail: str = ""

    def __bool__(self) -> bool:
        return self.claimed


def run_once(worker_id: str) -> IterationResult:
    """Claim one job, do it, record the result. Never raises for a failed job."""
    job = claim(worker_id)
    if job is None:
        return IterationResult(claimed=False, outcome="idle")

    # The gates are re-evaluated on every claim, so recovery from a pause is
    # automatic and needs no wakeup mechanism (docs/05 §10).
    blocked = gates.evaluate(job)
    if blocked is not None:
        # A pause is not a failure: `release` puts the job back without
        # counting an attempt or writing a backoff.
        release(job, reason=blocked)
        return IterationResult(True, "requeued", job.pk, blocked)

    try:
        detail = _dispatch(job)
    except TransientError as exc:
        fail(job, exc, retry=True)
        return IterationResult(True, "failed", job.pk, str(exc))
    except PermanentError as exc:
        fail(job, exc, retry=False)
        return IterationResult(True, "failed", job.pk, str(exc))
    except Exception as exc:  # pragma: no cover - the loop must survive anything
        # An unclassified crash is a bug, and the worst response is to strand
        # the job. Fail it visibly rather than retry a crash loop forever.
        fail(job, exc, retry=False)
        return IterationResult(True, "failed", job.pk, f"unhandled: {exc}")

    succeed(job)
    return IterationResult(True, "succeeded", job.pk, detail)


def _dispatch(job) -> str:
    """Call the right module for this job's intent. No rules, just routing."""
    if job.intent == "upload":
        acquire(job.workspace, job.source_video_id, source=job.source, job=job)
        return _upload(job)
    if job.intent == "rehydrate":
        # Stops at the file: same downloader, no upload, pinned on arrival.
        result = rehydrate(job.workspace, job.source_video_id, job=job)
        return f"rehydrated ({result.cost})"
    if job.intent == "inspect":
        # v1 reserves the intent; catalog scans are driven by the scheduler
        # (U15), not by a job row.
        return "inspected"
    raise PermanentError(f"Unknown job intent {job.intent!r}.")


def _upload(job) -> str:
    """Deliver to every target the planner says we may upload to right now."""
    plan = get_upload_planner().plan_for(job)
    if plan.blocked_reason or not plan.ready:
        raise TransientError(plan.blocked_reason or "no destination ready")
    if plan.no_media:
        # `acquire()` ran a moment ago, so this is a real inconsistency rather
        # than the normal pre-download state.
        raise TransientError("download finished but no verified media to upload")

    delivered = 0
    for target in plan.ready:
        deliver(
            target.destination,
            source_video_id=job.source_video_id,
            media_path=plan.media_path,
            title=plan.title,
            description=plan.description,
            tags=plan.tags,
            category_id=plan.category_id,
            privacy=target.privacy,
            job=job,
        )
        delivered += 1

    carried = len(plan.targets) - len(plan.ready)
    note = f"delivered to {delivered}"
    if carried:
        # Some destinations were out of quota. That is a pause for *them*, but
        # this video did upload, so the job is done and the ledger records the
        # rest as untouched rather than pretending they were attempted.
        note += f", {carried} carried for quota"
    return note


def run_forever(
    worker_id: str, *, sleep_seconds: float = 5.0, iterations: int | None = None
) -> int:
    """The loop. `iterations` bounds it for tests; `None` runs until stopped."""
    import time

    count = 0
    while iterations is None or count < iterations:
        result = run_once(worker_id)
        count += 1
        if not result.claimed:
            time.sleep(sleep_seconds)
    return count
