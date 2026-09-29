"""media.api — storage roots, `acquire()`, and hygiene (U11), published surface.

`acquire()` is the unit's centre and its order is the whole point:

1. **Reserve the row** (`expected`), so a crash leaves a record rather than a
   mystery, and a retry knows it is copy N.
2. **Download into a staging directory** inside the chosen root, via the Port A
   adapter obtained from `core` — this module may not import `sources`.
3. **Verify** — recompute the digest and compare it with the declared one. A
   mismatch never becomes an asset, and the bytes are removed.
4. **Rename atomically** into place, so a reader never sees a half-written
   file, and only then mark it `on_disk` and record the event.

Hygiene closes the loop the ledger makes possible: a `*.part` left by a crash
and a file no asset claims are both removed, and both leave an event behind.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from core.api import MaterializeRequest, get_source_provider, now_utc, resolve_safe_path
from media.errors import (
    AssetNotFound,
    NoStorageSpace,
    StorageRootNotFound,
    VerificationFailed,
)
from media.models import MediaAsset, MediaEvent, StorageRoot

__all__ = [
    "acquire",
    "add_storage_root",
    "archive_offline_root",
    "free_space",
    "get_asset",
    "hygiene",
    "list_assets",
    "list_events",
    "list_storage_roots",
    "pick_root",
    "set_mounted",
]

STAGING_DIR = ".staging"
PART_SUFFIX = ".part"


def add_storage_root(
    workspace,
    path,
    *,
    label: str = "",
    role: str = "hot",
    priority: int = 100,
    min_free_bytes: int = 10737418240,
) -> StorageRoot:
    """Register a directory we may write bytes into."""
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return StorageRoot.objects.create(
        workspace=workspace,
        label=label or resolved.name,
        path=str(resolved),
        role=role,
        priority=priority,
        min_free_bytes=min_free_bytes,
    )


def list_storage_roots(workspace, *, active_only: bool = True) -> list[StorageRoot]:
    queryset = StorageRoot.objects.filter(workspace=workspace)
    if active_only:
        queryset = queryset.filter(is_active=True)
    return list(queryset.order_by("priority", "id"))


def set_mounted(root: StorageRoot, mounted: bool) -> StorageRoot:
    """Attach or detach a root.

    Detaching is not an error: every asset on a detached root becomes
    `archive_offline`, which is what stops a re-attached cold drive from
    triggering a mass re-download (F-52).
    """
    root.is_mounted = mounted
    root.last_checked_at = now_utc()
    root.save(update_fields=["is_mounted", "last_checked_at", "updated_at"])
    if not mounted:
        archive_offline_root(root)
    return root


def archive_offline_root(root: StorageRoot) -> int:
    """Mark every asset on a detached root offline, and say so in the log."""
    assets = MediaAsset.objects.filter(
        storage_root=root, state=MediaAsset.STATE_ON_DISK
    )
    count = assets.count()
    for asset in assets:
        MediaEvent.objects.create(
            workspace=asset.workspace,
            media_asset=asset,
            source_video_id=asset.source_video_id,
            event="archive_offline",
            reason="storage root detached",
        )
    assets.update(state=MediaAsset.STATE_ARCHIVE_OFFLINE)
    return count


def free_space(root: StorageRoot) -> int:
    """Bytes free on the root's filesystem, recorded on the row as we read it."""
    usage = shutil.disk_usage(root.path)
    root.free_bytes = usage.free
    root.total_bytes = usage.total
    root.last_checked_at = now_utc()
    root.save(
        update_fields=["free_bytes", "total_bytes", "last_checked_at", "updated_at"]
    )
    return usage.free


def pick_root(workspace, *, needed_bytes: int = 0) -> StorageRoot:
    """The best root that can take `needed_bytes` without breaching its floor.

    Raises `NoStorageSpace` (transient) when none can: a full disk is a
    condition to back off from, not a permanent failure.
    """
    for root in list_storage_roots(workspace):
        if not root.is_mounted:
            continue
        if free_space(root) < max(root.min_free_bytes, needed_bytes):
            continue
        return root
    raise NoStorageSpace("No mounted storage root is above its free-space floor.")


def acquire(
    workspace,
    source_video_id: str,
    *,
    source=None,
    job=None,
    max_height: int = 0,
    prefer_format: str = "mp4",
) -> MediaAsset:
    """Download → verify → atomic rename. Returns the verified asset.

    A healthy copy we already hold is returned as-is: re-downloading a file we
    have is the waste this module exists to prevent.
    """
    existing = (
        MediaAsset.objects.filter(
            workspace=workspace, source_video_id=source_video_id
        )
        .filter(state=MediaAsset.STATE_ON_DISK)
        .order_by("-materialization_no")
        .first()
    )
    if existing is not None and Path(existing.absolute_path()).exists():
        return existing

    root = pick_root(workspace)
    copy_no = _next_copy_no(workspace, source_video_id)
    asset = MediaAsset.objects.create(
        workspace=workspace,
        source_video_id=source_video_id,
        source=source,
        job=job,
        storage_root=root,
        materialization_no=copy_no,
        path=f"{source_video_id}{copy_no}.{prefer_format}",
        state=MediaAsset.STATE_EXPECTED,
    )
    _event(asset, "created", reason=f"copy {copy_no} requested")

    staging = Path(root.path) / STAGING_DIR
    staging.mkdir(parents=True, exist_ok=True)
    provider = get_source_provider()
    asset.state = MediaAsset.STATE_DOWNLOADING
    asset.save(update_fields=["state", "updated_at"])

    try:
        media = provider.materialize(
            MaterializeRequest(
                video_id=source_video_id,
                destination_dir=staging,
                max_height=max_height,
                prefer_format=prefer_format,
            )
        )
    except Exception as exc:
        asset.state = MediaAsset.STATE_FAILED
        asset.delete_reason = str(exc)[:2000]
        asset.save(update_fields=["state", "delete_reason", "updated_at"])
        _event(asset, "created", reason=f"download failed: {exc}")
        raise

    # The staging file is the unit of work: whatever happens next it is removed
    # or promoted, never left behind half-adopted.
    staged = Path(media.file_path)
    if not staged.exists():
        asset.state = MediaAsset.STATE_FAILED
        asset.delete_reason = "provider reported a file that is not there"
        asset.save(update_fields=["state", "delete_reason", "updated_at"])
        raise VerificationFailed(f"Materialized file {staged} does not exist.")
    digest = _sha256(staged)
    if media.sha256 and digest != media.sha256:
        staged.unlink(missing_ok=True)
        asset.state = MediaAsset.STATE_FAILED
        asset.delete_reason = f"sha256 {digest} != declared {media.sha256}"
        asset.save(update_fields=["state", "delete_reason", "updated_at"])
        raise VerificationFailed(
            f"Downloaded {source_video_id} does not match its declared digest."
        )

    final = Path(resolve_safe_path(root.path, asset.path))
    final.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: a reader sees either nothing or the finished file, never a
    # half-written one.
    os.replace(staged, final)

    asset.state = MediaAsset.STATE_ON_DISK
    asset.filename = media.filename
    asset.size_bytes = final.stat().st_size
    asset.sha256 = digest
    asset.duration_sec = media.duration_sec
    asset.downloaded_at = now_utc()
    asset.save(
        update_fields=[
            "state",
            "filename",
            "size_bytes",
            "sha256",
            "duration_sec",
            "downloaded_at",
            "updated_at",
        ]
    )
    _event(asset, "verified", bytes=asset.size_bytes)
    return asset


def hygiene(workspace, *, actor: str = "system") -> dict:
    """Remove what a crash left behind: `*.part` files and unclaimed orphans.

    Two kinds of litter, two different proofs. A `*.part` is ours by
    construction — it can only have come from a staging download. An orphan is
    a file on disk that no `media_asset` row claims, so it is only removed when
    it is *not* inside the staging directory and not claimed by a live asset;
    anything else would be deleting an operator's own file.
    """
    removed_partials = 0
    removed_orphans = 0
    freed_bytes = 0
    for root in list_storage_roots(workspace):
        base = Path(root.path)
        staging = base / STAGING_DIR
        if staging.is_dir():
            for partial in staging.glob(f"*{PART_SUFFIX}"):
                freed_bytes += partial.stat().st_size
                partial.unlink(missing_ok=True)
                removed_partials += 1
        claimed = {
            str(Path(asset.path).name)
            for asset in MediaAsset.objects.filter(
                storage_root=root, state=MediaAsset.STATE_ON_DISK
            )
        }
        for entry in base.iterdir() if base.is_dir() else []:
            if not entry.is_file() or entry.name in claimed:
                continue
            if entry.name.endswith(PART_SUFFIX):
                continue  # counted above, when it is in staging
            size = entry.stat().st_size
            entry.unlink(missing_ok=True)
            freed_bytes += size
            removed_orphans += 1
            MediaEvent.objects.create(
                workspace=workspace,
                source_video_id="",
                event="deleted",
                reason=f"orphan removed by hygiene ({entry.name})",
                bytes=size,
                actor=actor,
            )
    return {
        "partials_removed": removed_partials,
        "orphans_removed": removed_orphans,
        "bytes_freed": freed_bytes,
    }


def get_asset(workspace, asset_id) -> MediaAsset:
    try:
        return MediaAsset.objects.get(workspace=workspace, pk=asset_id)
    except MediaAsset.DoesNotExist as exc:
        raise AssetNotFound(f"No media asset {asset_id}.") from exc


def list_assets(
    workspace, *, state: str | None = None, root=None
) -> list[MediaAsset]:
    queryset = MediaAsset.objects.filter(workspace=workspace)
    if state is not None:
        queryset = queryset.filter(state=state)
    if root is not None:
        queryset = queryset.filter(storage_root=root)
    return list(queryset.order_by("source_video_id", "materialization_no"))


def list_events(workspace, *, source_video_id: str | None = None) -> list[MediaEvent]:
    queryset = MediaEvent.objects.filter(workspace=workspace)
    if source_video_id is not None:
        queryset = queryset.filter(source_video_id=source_video_id)
    return list(queryset.order_by("-created_at", "-id"))


def _next_copy_no(workspace, source_video_id: str) -> int:
    last = (
        MediaAsset.objects.filter(workspace=workspace, source_video_id=source_video_id)
        .order_by("-materialization_no")
        .first()
    )
    return (last.materialization_no + 1) if last else 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _event(asset: MediaAsset, kind: str, *, reason: str = "", bytes: int = 0) -> MediaEvent:
    return MediaEvent.objects.create(
        workspace=asset.workspace,
        media_asset=asset,
        source_video_id=asset.source_video_id,
        event=kind,
        reason=reason,
        bytes=bytes,
    )