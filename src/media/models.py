"""
media.models — storage, what we downloaded, and what happened (docs/03 §9).

Three tables, three jobs. `storage_root` says *where* bytes may live;
`media_asset` says *what we have*; `media_event` says *why it looks like that*.

Decisions worth remembering:

* **A detached root is a state, not an error.** `is_mounted = false` makes every
  asset on it `archive_offline`, which is what stops a re-attached cold drive
  from triggering a mass re-download (F-52).
* **`materialization_no` makes re-downloads honest.** Copy 1 was the original,
  copy 2 is a later re-download, and `sha256` records that they need not be
  byte-identical.
* **Events outlive their subject.** `media_event.media_asset_id` is
  `ON DELETE SET NULL`, so the audit of a deletion survives the row being
  deleted — the difference between "the disk is full and nobody knows why" and
  "4.2 GB was freed at 03:11 because pipeline 3 reached N = 2".
"""

from core.api import resolve_safe_path
from django.db import models

ROLE_CHOICES = [("hot", "Hot"), ("cold", "Cold")]

ASSET_STATES = [
    ("expected", "Expected"),
    ("downloading", "Downloading"),
    ("on_disk", "On disk"),
    ("archive_offline", "Archived (offline)"),
    ("deleted", "Deleted"),
    ("failed", "Failed"),
]

MEDIA_EVENTS = [
    ("created", "Created"),
    ("verified", "Verified"),
    ("pinned", "Pinned"),
    ("unpinned", "Unpinned"),
    ("delete_scheduled", "Delete scheduled"),
    ("delete_skipped", "Delete skipped"),
    ("deleted", "Deleted"),
    ("rehydrated", "Rehydrated"),
    ("archive_offline", "Archived offline"),
]


class StorageRoot(models.Model):
    """A directory we are allowed to put bytes in."""

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="storage_roots"
    )
    label = models.TextField()
    path = models.TextField()
    role = models.TextField(choices=ROLE_CHOICES, default="hot")
    priority = models.IntegerField(default=100)  # lower fills first
    #: 10 GiB floor. Refusing a download that would breach it is the whole
    #: point of the column: a full disk fails jobs in ways nobody can explain.
    min_free_bytes = models.BigIntegerField(default=10737418240)
    is_mounted = models.BooleanField(default=True)
    free_bytes = models.BigIntegerField(null=True, blank=True)
    total_bytes = models.BigIntegerField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "storage_root"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "path"], name="uq_storage_root_path"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=["hot", "cold"]), name="ck_storage_root_role"
            ),
            models.CheckConstraint(
                condition=models.Q(min_free_bytes__gte=0),
                name="ck_storage_root_min_free",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "is_active", "role", "priority"],
                name="storage_root_pick_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.role}, mounted={self.is_mounted})"


class MediaAsset(models.Model):
    """One materialised copy of one source video."""

    STATE_EXPECTED = "expected"
    STATE_DOWNLOADING = "downloading"
    STATE_ON_DISK = "on_disk"
    STATE_ARCHIVE_OFFLINE = "archive_offline"
    STATE_DELETED = "deleted"
    STATE_FAILED = "failed"

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="media_assets"
    )
    source_video_id = models.TextField()
    source = models.ForeignKey(
        "sources.Source",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="media_assets",
    )
    job = models.ForeignKey(
        "jobs.Job",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="media_assets",
    )
    storage_root = models.ForeignKey(
        StorageRoot,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="media_assets",
    )
    materialization_no = models.IntegerField(default=1)
    #: Always relative to the root's path. The absolute form is derived, never
    #: stored, so moving a root does not invalidate every row (INV-PATH-1).
    path = models.TextField()
    filename = models.TextField(default="")
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.TextField(default="")
    duration_sec = models.IntegerField(null=True, blank=True)
    state = models.TextField(choices=ASSET_STATES, default=STATE_EXPECTED)
    pinned_until = models.DateTimeField(null=True, blank=True)
    pinned_reason = models.TextField(default="")
    downloaded_at = models.DateTimeField(null=True, blank=True)
    delete_after = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    delete_reason = models.TextField(default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "media_asset"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_video_id", "materialization_no"],
                name="uq_media_asset_copy",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    state__in=[
                        "expected",
                        "downloading",
                        "on_disk",
                        "archive_offline",
                        "deleted",
                        "failed",
                    ]
                ),
                name="ck_media_asset_state",
            ),
            models.CheckConstraint(
                condition=models.Q(materialization_no__gte=1),
                name="ck_media_asset_copy_no",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "state"], name="media_asset_state_idx"),
            models.Index(
                fields=["workspace", "source_video_id"], name="media_asset_video_idx"
            ),
            models.Index(
                fields=["delete_after"],
                condition=models.Q(state="on_disk"),
                name="media_asset_due_idx",
            ),
            models.Index(fields=["storage_root_id", "state"], name="media_asset_root_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source_video_id}#{self.materialization_no} ({self.state})"

    def absolute_path(self) -> str:
        """The file's real location: root path + the stored relative path.

        The absolute form is derived, never stored, so moving a root does not
        invalidate every row. `resolve_safe_path` is what stops a stored
        relative path from escaping the root (INV-PATH-1).
        """
        if self.storage_root_id is None:
            return self.path
        return str(resolve_safe_path(self.storage_root.path, self.path))


class MediaEvent(models.Model):
    """Append-only: what happened to a file, and why, with the bytes it moved.

    This table is what turns "the disk is full and nobody knows why" into
    "4.2 GB was freed at 03:11 because pipeline 3 reached N = 2". `actor` makes
    the answer distinguish an operator from the system.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="media_events"
    )
    media_asset = models.ForeignKey(
        MediaAsset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    source_video_id = models.TextField()
    event = models.TextField(choices=MEDIA_EVENTS)
    reason = models.TextField(default="")
    bytes = models.BigIntegerField(default=0)
    actor = models.TextField(default="system")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "media_event"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    event__in=[
                        "created",
                        "verified",
                        "pinned",
                        "unpinned",
                        "delete_scheduled",
                        "delete_skipped",
                        "deleted",
                        "rehydrated",
                        "archive_offline",
                    ]
                ),
                name="ck_media_event_kind",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "-created_at"], name="media_event_recent_idx"
            ),
            models.Index(
                fields=["workspace", "source_video_id"], name="media_event_video_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event} {self.source_video_id} ({self.bytes} bytes)"
