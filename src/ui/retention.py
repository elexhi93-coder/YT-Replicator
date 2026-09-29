"""
ui.retention — the `RetentionOracle` implementation (U12).

This file exists because of an architectural constraint rather than a
functional one. The retention gates need four facts owned by four different
modules:

| Fact | Owner |
|---|---|
| the policy (mode, n, hours, enabled destinations) | `pipelines` |
| ledger terminality and `uploaded_at` | `delivery` |
| newer completed jobs of the pipeline | `jobs` |
| "does a destination still hold this video" | `youtube` |

`media` may import `core` and `accounts` only (docs/04 §2), so it cannot read
any of them directly. `ui` is the outermost layer and may import every module,
which makes this the one place the four can be combined — the same reason
`ui.apps.ready` already binds the Port A provider.

The result is registered as a port, so `media.retention` asks `core` for it
rather than importing anything. It performs **no writes** (Pillar 0 R2): the
evaluator in `media` owns every decision and every byte.
"""

from __future__ import annotations

from accounts.api import get_workspace
from core.api import RetentionFacts
from delivery.api import delivery_facts
from jobs.api import find_job, newer_completed_jobs
from pipelines.api import retention_policy_for_job
from youtube.api import copy_confirmed


class RetentionOracle:
    """Read-only fact snapshot for the retention gates."""

    def facts_for(
        self, workspace_id: int, source_video_id: str, job_id: int | None
    ) -> RetentionFacts:
        job = find_job(job_id)
        if job is None:
            # Without a job there is no pipeline, so there is no policy, and an
            # asset nobody can attribute to a pipeline is never auto-deleted.
            return RetentionFacts(
                mode="keep",
                retention_n=0,
                retention_hours=0,
                all_destinations_terminal=False,
                destination_copy_present=False,
                newer_completed_jobs=0,
                uploaded_at=None,
                unavailable_reason="no job for this asset",
            )

        workspace = get_workspace(workspace_id)
        if workspace is None:
            return RetentionFacts(
                mode="keep",
                retention_n=0,
                retention_hours=0,
                all_destinations_terminal=False,
                destination_copy_present=False,
                newer_completed_jobs=0,
                uploaded_at=None,
                unavailable_reason="unknown workspace",
            )

        policy = retention_policy_for_job(job)
        ledger = delivery_facts(
            workspace, source_video_id, policy.enabled_destination_ids
        )
        return RetentionFacts(
            mode=policy.mode,
            retention_n=policy.retention_n,
            retention_hours=policy.retention_hours,
            all_destinations_terminal=ledger.all_terminal,
            destination_copy_present=copy_confirmed(workspace, source_video_id),
            newer_completed_jobs=newer_completed_jobs(
                workspace, job.pipeline, job.created_at
            ),
            uploaded_at=ledger.uploaded_at,
        )


def retention_oracle_factory() -> RetentionOracle:
    return RetentionOracle()
