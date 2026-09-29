"""
ui.planner — the `UploadPlanner` implementation (U14).

The same architectural situation as `ui/retention.py`. Uploading one video
needs three reads, each owned by a module `worker` may not import:

| What | Owner |
|---|---|
| which destinations, their privacy and daily caps | `pipelines` |
| the catalog title, description and tags | `sources` |
| how many uploads are left today | `youtube` |

`ui` is the outermost layer and may import every module, so this is the one
place the three can be combined. The result is registered as a port, so
`worker` asks `core` and stays free of sibling imports.

Read-only, like every other port: the worker owns every write.
"""

from __future__ import annotations

from pathlib import Path

from core.api import UploadPlan, UploadTarget
from pipelines.api import enabled_destinations
from sources.api import catalog_metadata
from youtube.api import quota_remaining


class UploadPlanner:
    """Assemble one job's upload plan, or say plainly why it cannot."""

    def plan_for(self, job) -> UploadPlan:
        pipeline = job.pipeline
        asset = _asset_for(job)
        if asset is None:
            # No media yet is the *normal* state before a first download, so it
            # is reported as `no_media` rather than as a pause. A gate that read
            # it as a block would stop the very first job from ever running.
            return _no_media(job, pipeline)

        targets = []
        for link in enabled_destinations(pipeline):
            remaining = quota_remaining(link.destination)
            targets.append(
                UploadTarget(
                    destination=link.destination,
                    privacy=link.privacy,
                    quota_ok=remaining > 0,
                    quota_note="" if remaining else "quota exhausted for today",
                )
            )

        meta = catalog_metadata(job.workspace, job.source_video_id)
        profile = pipeline.download_profile
        return UploadPlan(
            workspace=job.workspace,
            source_video_id=job.source_video_id,
            media_path=Path(asset.absolute_path()),
            # A title is mandatory on the platform and the catalog is the only
            # honest source for it. Falling back to the bare video id would
            # upload a video called "dQw4w9WgXcQ"; an empty title is worse,
            # because it is indistinguishable from a bug.
            title=meta.title if meta else job.source_video_id,
            description=meta.description if meta else "",
            tags=meta.tags if meta else (),
            category_id=meta.category_id if meta else "",
            max_height=profile.max_height if profile else 0,
            targets=tuple(targets),
            blocked_reason="" if targets else "no enabled destination",
        )


def _asset_for(job):
    """The newest verified on-disk asset for this job's video, or `None`.

    Read through `media`'s published surface rather than its models, so this
    file stays an orchestration layer with no model knowledge of its own.
    """
    from media.api import list_assets

    assets = [
        asset
        for asset in list_assets(job.workspace, state="on_disk")
        if asset.source_video_id == job.source_video_id
    ]
    if not assets:
        return None
    return max(assets, key=lambda a: a.materialization_no)


def _no_media(job, pipeline) -> UploadPlan:
    """Destinations and quota are still knowable without a file — report both."""
    targets = tuple(
        UploadTarget(
            destination=link.destination,
            privacy=link.privacy,
            quota_ok=quota_remaining(link.destination) > 0,
            quota_note=(
                ""
                if quota_remaining(link.destination) > 0
                else "quota exhausted for today"
            ),
        )
        for link in enabled_destinations(pipeline)
    )
    return UploadPlan(
        workspace=job.workspace,
        source_video_id=job.source_video_id,
        media_path=Path(""),
        title="",
        description="",
        tags=(),
        category_id="",
        max_height=0,
        targets=targets,
        blocked_reason="" if targets else "no enabled destination",
        no_media=True,
    )


def upload_planner_factory() -> UploadPlanner:
    return UploadPlanner()
