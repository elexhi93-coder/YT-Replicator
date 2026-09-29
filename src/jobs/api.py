"""jobs.api — the job queue (U08), published surface.

The database is the queue (D3): no Redis, no Celery, no broker. Four
properties matter, and each is one function:

* **Dedup on enqueue** (`enqueue`). One live job per
  `(workspace, pipeline, video, intent)`, enforced by the partial unique index
  rather than a check-then-insert, because the check would race.
* **Atomic claim** (`claim`). `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP
  LOCKED LIMIT 1) RETURNING id` — one statement, safe with many workers. This
  is the fix for the legacy's read-then-write race (P11).
* **Classification** (`fail`). `TransientError` means the job goes back to
  `queued` with a backoff; anything else is permanent and stops. The
  classification comes from the caller's error type, not a guess made here.
* **Self-healing** (`requeue_stale`). A claim is a lease with an expiry, so a
  worker that dies holding a job does not strand it.

Nothing here sleeps: backoff is a timestamp the claim query respects, so a
restart cannot lose a delay.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from core.api import TransientError, now_utc
from jobs.errors import InvalidJobSetting, InvalidJobTransition, JobNotFound
from jobs.models import INTENT_CHOICES, STATUS_UPLOADED, TERMINAL_STATUSES, Job

__all__ = [
    "DEFAULT_LEASE_MINUTES",
    "MAX_ATTEMPTS",
    "backoff_for",
    "cancel",
    "claim",
    "enqueue",
    "fail",
    "get_job",
    "list_jobs",
    "requeue_stale",
    "skip",
    "succeed",
]

#: docs/03 §7: `claim_expires_at = now() + interval '15 minutes'`.
DEFAULT_LEASE_MINUTES = 15
#: After this many transient failures a job is given up on. Without a ceiling a
#: permanently broken video would be retried forever, spending quota each time.
MAX_ATTEMPTS = 5
#: Exponential, capped: 1, 2, 4, 8, 16 minutes.
_BACKOFF_BASE_SECONDS = 60
_BACKOFF_CAP_SECONDS = 3600

_INTENTS = {value for value, _label in INTENT_CHOICES}

# The claim, in one statement: pick a queued job nobody else holds, and take
# it. `claim_expires_at <= now` is the backoff gate: a job that failed and is
# waiting out its delay is invisible to claimants until the delay has passed.
_CLAIM_SQL = """
UPDATE job
   SET status = 'claimed',
       claimed_by = %s,
       claimed_at = %s,
       claim_expires_at = %s,
       started_at = COALESCE(started_at, %s),
       updated_at = %s
 WHERE id = (
     SELECT id FROM job
      WHERE status = 'queued'
        AND (claim_expires_at IS NULL OR claim_expires_at <= %s)
      ORDER BY priority, created_at
      LIMIT 1
      FOR UPDATE SKIP LOCKED)
 RETURNING id
"""

# Same statement without the row lock. Used where the backend has no row
# locking (the SQLite test harness, INV-10); a single writer makes the
# read-then-update equivalent there. Production is PostgreSQL 16 and always
# takes the locked path.
_CLAIM_SQL_UNLOCKED = _CLAIM_SQL.replace("      FOR UPDATE SKIP LOCKED", "")


def backoff_for(attempt: int) -> timedelta:
    """Exponential backoff for the *next* attempt, capped at an hour."""
    seconds = min(
        _BACKOFF_BASE_SECONDS * (2 ** max(attempt - 1, 0)), _BACKOFF_CAP_SECONDS
    )
    return timedelta(seconds=seconds)


def enqueue(
    workspace,
    pipeline,
    source_video_id: str,
    *,
    intent: str = "upload",
    priority: int | None = None,
    source=None,
) -> Job:
    """Queue one job, or return the live one that already exists.

    Dedup comes from the partial unique index and the `IntegrityError` it
    raises — not from a lookup first, because a lookup-then-insert is a race
    and two callers enqueuing the same video would both pass it.
    """
    if intent not in _INTENTS:
        raise InvalidJobSetting("intent", intent, _INTENTS)
    if priority is None:
        # Lower pipeline priority runs first; within a pipeline, FIFO.
        priority = pipeline.priority
    try:
        with transaction.atomic():
            return Job.objects.create(
                workspace=workspace,
                pipeline=pipeline,
                source=source,
                source_video_id=source_video_id,
                intent=intent,
                priority=priority,
            )
    except IntegrityError:
        # A live job already covers this (pipeline, video, intent). Returning
        # it satisfies the caller's intent — "make sure this is queued" — and
        # keeps a duplicate request from failing work that is already under way.
        existing = Job.objects.filter(
            pipeline=pipeline, source_video_id=source_video_id, intent=intent
        ).exclude(status__in=["cancelled", "skipped"])
        return existing.first() or Job.objects.get(
            pipeline=pipeline, source_video_id=source_video_id, intent=intent
        )


@transaction.atomic
def claim(worker: str, *, lease_minutes: int = DEFAULT_LEASE_MINUTES) -> Job | None:
    """Atomically take the next queued job. `None` when the queue is empty.

    The claim is a lease, not an open transaction: the row is marked claimed
    and released at once, so many workers run concurrently and a dead worker's
    job is recoverable by `requeue_stale`.
    """
    if not worker:
        raise InvalidJobSetting("worker", worker, {"a non-empty name"})
    now = now_utc()
    expires = now + timedelta(minutes=lease_minutes)
    args = (worker, now, expires, now, now, now)
    sql = (
        _CLAIM_SQL
        if connection.features.has_select_for_update_skip_locked
        else _CLAIM_SQL_UNLOCKED
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, args)
        row = cursor.fetchone()
    if not row:
        return None
    return Job.objects.get(pk=row[0])


def succeed(job: Job) -> Job:
    """Mark a claimed job finished successfully."""
    if job.status in TERMINAL_STATUSES:
        raise InvalidJobTransition(job.status, STATUS_UPLOADED)
    job.status = STATUS_UPLOADED
    job.error_code = ""
    job.error_message = ""
    job.finished_at = now_utc()
    job.claim_expires_at = None
    job.save(
        update_fields=[
            "status",
            "error_code",
            "error_message",
            "finished_at",
            "claim_expires_at",
            "updated_at",
        ]
    )
    return job


def fail(job: Job, error: BaseException, *, retry: bool = True) -> Job:
    """Record a failure and decide its fate from the error's own type.

    `TransientError` puts the job back in the queue with a backoff; anything
    else is permanent. `retry=False` forces the permanent outcome for a caller
    that knows better than the classification — an operator pressing stop, a
    quota that will not recover on its own.
    """
    if job.status in TERMINAL_STATUSES:
        raise InvalidJobTransition(job.status, "failed")
    job.error_code = getattr(error, "default_code", "") or type(error).__name__
    job.error_message = str(error)[:2000]
    transient = isinstance(error, TransientError)
    if not (transient and retry) or job.attempt_count + 1 >= MAX_ATTEMPTS:
        job.status = "failed_permanent"
        job.finished_at = now_utc()
        job.claim_expires_at = None
    else:
        job.status = "queued"
        job.attempt_count += 1
        # The backoff is a timestamp, not a sleep: a restart cannot lose it.
        job.claim_expires_at = now_utc() + backoff_for(job.attempt_count)
    job.save(
        update_fields=[
            "status",
            "attempt_count",
            "error_code",
            "error_message",
            "finished_at",
            "claim_expires_at",
            "updated_at",
        ]
    )
    return job


def requeue_stale(*, now=None) -> int:
    """Return expired claims to the queue. Returns how many were recovered.

    This is what makes a crashed worker a non-event: its lease expires and the
    job is available again. Idempotent — a second pass recovers nothing.
    """
    moment = now or now_utc()
    return (
        Job.objects.filter(
            status="claimed",
            claim_expires_at__isnull=False,
            claim_expires_at__lt=moment,
        ).update(
            status="queued",
            claimed_by="",
            claimed_at=None,
            claim_expires_at=None,
            updated_at=timezone.now(),
        )
    )


def cancel(job: Job) -> Job:
    """Stop a job. Cancelling frees the dedup key so it can be re-run."""
    if job.status in TERMINAL_STATUSES:
        raise InvalidJobTransition(job.status, "cancelled")
    job.status = "cancelled"
    job.finished_at = now_utc()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    return job


def skip(job: Job, reason: str) -> Job:
    """Take a job out of the queue with a reason the operator can read.

    This is how the legacy's `videos_seen` blob is replaced: the reason travels
    with the row, where it can be queried and shown, instead of living in JSON
    that nothing reads.
    """
    if job.status in TERMINAL_STATUSES:
        raise InvalidJobTransition(job.status, "skipped")
    if not reason:
        raise InvalidJobSetting("reason", reason, {"a non-empty explanation"})
    job.status = "skipped"
    job.skip_reason = reason
    job.finished_at = now_utc()
    job.save(update_fields=["status", "skip_reason", "finished_at", "updated_at"])
    return job


def get_job(job_id) -> Job:
    try:
        return Job.objects.get(pk=job_id)
    except Job.DoesNotExist as exc:
        raise JobNotFound(f"No job {job_id}.") from exc


def list_jobs(workspace, *, status: str | None = None, pipeline=None) -> list[Job]:
    """Jobs in queue order: priority, then age. For the Queue page (U19)."""
    queryset = Job.objects.filter(workspace=workspace)
    if status is not None:
        queryset = queryset.filter(status=status)
    if pipeline is not None:
        queryset = queryset.filter(pipeline=pipeline)
    return list(queryset.order_by("priority", "created_at", "id"))
