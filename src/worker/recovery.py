"""
worker.recovery — what a dead worker left behind (docs/05 §9).

Run once on start-up. Deterministic, idempotent, and safe to run twice: every
step is a conditional update, so a second pass recovers nothing.

The interesting row is the last one. A delivery stuck in `uploading` means
**we do not know whether the upload succeeded**, so it is *reconciled*, not
retried. Reconciling costs about one API unit; guessing costs a duplicate
upload on someone else's channel — the behaviour the legacy could not have,
because it had nothing to reconcile against (D-13).
"""

from __future__ import annotations

from datetime import timedelta

from core.api import now_utc
from delivery.api import reconcile, stalled_uploads
from jobs.api import requeue_stale
from media.api import fail_stale_downloads

__all__ = ["DEFAULT_CLAIM_TIMEOUT_MINUTES", "RecoveryReport", "recover"]

#: How long a claimed job may sit before we assume its worker died. Comfortably
#: longer than the lease in `jobs`, so a healthy long download is never swept
#: out from under itself.
DEFAULT_CLAIM_TIMEOUT_MINUTES = 60


class RecoveryReport:
    """What the sweep found and did, so start-up can log it."""

    def __init__(self, **counts):
        self.jobs_requeued = counts.get("jobs_requeued", 0)
        self.downloads_failed = counts.get("downloads_failed", 0)
        self.uploads_reconciled = counts.get("uploads_reconciled", 0)

    def as_dict(self) -> dict:
        return {
            "jobs_requeued": self.jobs_requeued,
            "downloads_failed": self.downloads_failed,
            "uploads_reconciled": self.uploads_reconciled,
        }

    def __repr__(self) -> str:
        return f"RecoveryReport({self.as_dict()})"


def recover(
    *, now=None, claim_timeout_minutes: int = DEFAULT_CLAIM_TIMEOUT_MINUTES
) -> RecoveryReport:
    """Sweep the wreckage of a previous process. Never raises."""
    moment = now or now_utc()
    cutoff = moment - timedelta(minutes=claim_timeout_minutes)

    # A claimed job whose lease expired: the worker died holding it.
    requeued = requeue_stale(now=moment)

    # A download that never finished. The partial is not valid media, so the
    # asset fails and hygiene reclaims the bytes.
    failed = fail_stale_downloads(now=cutoff)

    # An upload we may or may not have completed: ask the channel, never guess.
    reconciled = 0
    for delivery in stalled_uploads(now=cutoff):
        reconcile(delivery.destination, source_video_id=delivery.source_video_id)
        reconciled += 1

    return RecoveryReport(
        jobs_requeued=requeued,
        downloads_failed=failed,
        uploads_reconciled=reconciled,
    )
