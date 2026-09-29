from __future__ import annotations

"""media.errors — typed errors for the storage module (docs/04 §5).

The classification here is the interesting part. "The disk is full" is **not**
a permanent error: retention (U12) will free space, or an operator will, so
the right response is to back off and try again — exactly like a throttle.
Getting this wrong in either direction costs quota and disk.
"""

from core.api import PermanentError, TransientError


class MediaError(PermanentError):
    """Base for storage configuration failures."""

    default_code = "media_error"


class StorageRootNotFound(MediaError):
    """No storage root matches the lookup."""

    default_code = "storage_root_not_found"


class AssetNotFound(MediaError):
    """No media asset matches the lookup."""

    default_code = "media_asset_not_found"


class NoStorageSpace(TransientError):
    """Every eligible root is below its floor, or none is mounted.

    Transient because the condition resolves: retention frees space, or the
    operator does. A worker that retried immediately would just fill the disk
    again and burn quota, so `jobs` must back off — hence transient, not
    permanent.
    """

    default_code = "no_storage_space"


class VerificationFailed(PermanentError):
    """The downloaded bytes do not match the digest the platform declared.

    Permanent: a corrupt or truncated download will not become correct by being
    downloaded again, and the file is not left on disk pretending otherwise.
    """

    default_code = "verification_failed"


class PathEscapesRoot(MediaError):
    """A relative path resolved outside the storage root (INV-PATH-1)."""

    default_code = "path_escapes_root"


__all__ = [
    "AssetNotFound",
    "MediaError",
    "NoStorageSpace",
    "PathEscapesRoot",
    "StorageRootNotFound",
    "VerificationFailed",
]
