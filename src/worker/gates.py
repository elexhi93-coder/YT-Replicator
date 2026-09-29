"""
worker.gates — quota, disk and operator pauses (docs/05 §10).

A gate answers one question: *should this job start right now?* When the
answer is no, the job goes back to `queued` **untouched** — no attempt is
counted, no timestamp is rewritten — so the queue's history stays truthful and
a video does not burn its five attempts against a full disk.

The order is cheapest-first: a paused pipeline costs nothing to check, and
quota comes before disk because a quota pause is the common case while a disk
check touches the filesystem.
"""

from __future__ import annotations

from core.api import get_upload_planner
from media.api import NoStorageSpace, pick_root

__all__ = ["evaluate"]


def evaluate(job) -> str | None:
    """`None` when the job may proceed, else why it is being held."""
    pipeline = job.pipeline

    # 1. The operator's own switch. Cheapest, and unambiguous.
    if pipeline.status != "active":
        return f"pipeline is {pipeline.status}"

    if job.intent == "rehydrate":
        # A rehydrate needs disk like any other download; quota does not apply
        # because it never reaches the platform.
        return _disk_pause(job)

    # 2. Destinations and quota come from the planner, the only thing allowed
    #    to read `pipelines`, `sources` and `youtube`. Note that `no_media` is
    #    *not* consulted: having no file yet is the normal state before a first
    #    download, and the download is what this job is for.
    plan = get_upload_planner().plan_for(job)
    if plan.blocked_reason:
        return plan.blocked_reason

    if not plan.ready:
        notes = ", ".join(t.quota_note for t in plan.targets if t.quota_note)
        return f"paused - quota ({notes or 'no uploads left today'})"

    # 3. Disk, last.
    return _disk_pause(job)


def _disk_pause(job) -> str | None:
    try:
        pick_root(job.workspace)
    except NoStorageSpace as exc:
        return f"paused - {exc}"
    return None
