"""
media.rehydrate — bringing a file back (U13, docs/05 §7).

The flow's first question is the cheapest one, and that ordering is the whole
point of this unit:

    D{asset on a now-mounted root, file still there?}
      yes → verify + relabel, `on_disk`, **no download**
      no  → is the source video still available?
               no  → permanent failure, "no surviving source"
               yes → free space ok? no → transient wait
                      yes → download → verify → rename

That first branch is the payoff for `archive_offline`. Marking a detached root
`archive_offline` rather than deleting its rows (F-52) is what makes
re-attaching a cold drive free instead of a mass re-download.

**Rehydrate never touches `delivery`, and never uses a second downloader.**
It is the same `media.acquire()` and the same `job` row with a different
intent — the rule from `docs/00` §P3. There is no rehydrate queue, because a
second queue is a second thing to lose work.

**A rehydrated file is pinned on arrival** (D4), because an unowned
re-download recreates the storage leak retention exists to close. Only an
explicit release unpins it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.api import ItemUnavailable
from media.models import MediaAsset, MediaEvent

__all__ = [
    "REHYDRATE_PIN_REASON",
    "RehydrateResult",
    "rehydrate",
    "relabel_if_recoverable",
]

#: D4 — the pin a rehydrated file arrives with, and the reason an operator
#: sees when they ask why retention skipped it.
REHYDRATE_PIN_REASON = "rehydrated"


class RehydrateResult:
    """What happened, in the flow's own vocabulary."""

    def __init__(self, asset: MediaAsset, *, relabelled: bool, downloaded: bool):
        self.asset = asset
        self.relabelled = relabelled
        self.downloaded = downloaded

    @property
    def cost(self) -> str:
        """`free`, `downloaded`, or `already_on_disk` — for the Library row."""
        if self.relabelled:
            return "free"
        return "downloaded" if self.downloaded else "already_on_disk"

    def __repr__(self) -> str:
        return f"RehydrateResult({self.asset.pk}, {self.cost})"


def rehydrate(
    workspace,
    source_video_id: str,
    *,
    source=None,
    job=None,
    max_height: int = 0,
    prefer_format: str = "mp4",
    actor: str = "system",
) -> RehydrateResult:
    """Bring one file back, by the cheapest route that can work.

    Raises `ItemUnavailable` (permanent) when the source video itself is gone —
    the flow's *no surviving source* branch. That is a fact about the world,
    not a fault to back off from, so the worker marks the job
    `failed_permanent`; the honest answer beats a job that retries forever
    against a deleted video.
    """
    recovered = relabel_if_recoverable(workspace, source_video_id, actor=actor)
    if recovered is not None:
        return RehydrateResult(recovered, relabelled=True, downloaded=False)

    try:
        # Imported here, not at module scope: `media.api` re-exports
        # `rehydrate` so the worker can reach it through the published
        # surface, and a top-level import would close that into a cycle.
        from media.api import acquire

        asset = acquire(
            workspace,
            source_video_id,
            source=source,
            job=job,
            max_height=max_height,
            prefer_format=prefer_format,
        )
    except Exception as exc:
        if _looks_unavailable(exc):
            raise ItemUnavailable(
                f"{source_video_id} is no longer available at the source."
            ) from exc
        raise

    downloaded = bool(asset.downloaded_at)
    _pin_rehydrated(asset, actor=actor)
    return RehydrateResult(asset, relabelled=False, downloaded=downloaded)


def relabel_if_recoverable(workspace, source_video_id: str, *, actor: str = "system"):
    """Recover an archived file without downloading it. `None` if impossible.

    The check is a real one, not an assumption: the root must be mounted *and*
    the file must still be there *and* its digest must still match what we
    recorded. Trusting the row instead would hand back an `on_disk` asset whose
    bytes are gone — precisely the "the disk is full and nobody knows why"
    class of bug this project exists to remove.
    """
    for asset in MediaAsset.objects.filter(
        workspace=workspace,
        source_video_id=source_video_id,
        state=MediaAsset.STATE_ARCHIVE_OFFLINE,
    ).order_by("-materialization_no"):
        if asset.storage_root_id is None or not asset.storage_root.is_mounted:
            continue
        path = Path(asset.absolute_path())
        if not path.exists():
            continue
        if asset.sha256 and _sha256(path) != asset.sha256:
            # The bytes are not the bytes we recorded. Do not relabel them.
            continue
        asset.state = MediaAsset.STATE_ON_DISK
        asset.deleted_at = None
        asset.delete_reason = ""
        asset.save(
            update_fields=["state", "deleted_at", "delete_reason", "updated_at"]
        )
        _event(
            asset,
            "rehydrated",
            reason="relabelled from a re-attached storage root (no download)",
            bytes=asset.size_bytes,
            actor=actor,
        )
        _pin_rehydrated(asset, actor=actor)
        return asset
    return None


def _pin_rehydrated(asset: MediaAsset, *, actor: str = "system") -> None:
    """D4: a rehydrated file is never auto-deleted.

    `pinned_until = NULL` is our infinity — a real expiry would silently
    un-pin the file when it passed, and nothing would explain why retention
    suddenly started deleting things again.
    """
    if asset.pinned_reason == REHYDRATE_PIN_REASON:
        return  # already pinned by an earlier rehydrate; do not stack events
    asset.pinned_until = None
    asset.pinned_reason = REHYDRATE_PIN_REASON
    asset.delete_after = None
    asset.save(
        update_fields=["pinned_until", "pinned_reason", "delete_after", "updated_at"]
    )
    _event(asset, "pinned", reason=REHYDRATE_PIN_REASON, actor=actor)


def _looks_unavailable(exc: Exception) -> bool:
    """Did the provider tell us the video is gone, in its own words?

    Providers differ in how they say this, and a wrong guess in *either*
    direction is expensive: treating a gone video as transient retries it
    forever, and treating a network blip as permanent loses a recoverable
    file. Only an explicit "gone" signal counts.
    """
    if isinstance(exc, ItemUnavailable):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "private video",
            "video unavailable",
            "has been removed",
            "does not exist",
            "no longer available",
        )
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _event(asset, kind, *, reason="", bytes=0, actor="system") -> None:
    MediaEvent.objects.create(
        workspace_id=asset.workspace_id,
        media_asset=asset,
        source_video_id=asset.source_video_id,
        event=kind,
        reason=reason,
        bytes=bytes,
        actor=actor,
    )

