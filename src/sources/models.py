from __future__ import annotations

"""
sources.models — `source` and `catalog_video` (docs/03 §5).

A source is what the operator registered (a channel or a playlist); a catalog
video is what a scan discovered under it. Three decisions worth remembering:

* **Two identifiers.** `url` is what the operator typed (so the UI can echo it
  back), `external_id` is the canonical `UC…`/`PL…` form the resolver returned
  (so matching is exact).
* **Uniqueness is `(source_id, video_id)`, not per workspace.** The same video
  legitimately appears in a channel and in a curated playlist: it is catalogued
  twice and delivered once (INV-9).
* **A vanished video is never deleted.** A scan that no longer sees it sets
  `availability='unavailable'` and leaves everything else intact.
"""

from django.db import models


class Source(models.Model):
    """A registered channel or playlist."""

    KIND_CHANNEL = "channel"
    KIND_PLAYLIST = "playlist"
    KIND_CHOICES = [(KIND_CHANNEL, "Channel"), (KIND_PLAYLIST, "Playlist")]

    SCAN_NEVER = "never"
    SCAN_SCANNING = "scanning"
    SCAN_OK = "ok"
    SCAN_PARTIAL = "partial"
    SCAN_ERROR = "error"
    SCAN_STATUSES = [
        (SCAN_NEVER, "Never"),
        (SCAN_SCANNING, "Scanning"),
        (SCAN_OK, "Ok"),
        (SCAN_PARTIAL, "Partial"),
        (SCAN_ERROR, "Error"),
    ]

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="sources"
    )
    kind = models.TextField(choices=KIND_CHOICES)
    external_id = models.TextField()
    url = models.TextField()
    name = models.TextField(default="")
    is_active = models.BooleanField(default=True)
    scan_status = models.TextField(choices=SCAN_STATUSES, default=SCAN_NEVER)
    last_scan_at = models.DateTimeField(null=True, blank=True)
    last_scan_error = models.TextField(default="")
    video_count = models.IntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "source"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "external_id"], name="uq_source_workspace_external"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["channel", "playlist"]),
                name="ck_source_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    scan_status__in=["never", "scanning", "ok", "partial", "error"]
                ),
                name="ck_source_scan_status",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "is_active", "last_scan_at"],
                name="source_scan_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name or self.external_id} ({self.kind})"


class CatalogVideo(models.Model):
    """One video discovered under one source."""

    AVAILABILITY_CHOICES = [
        ("available", "Available"),
        ("unavailable", "Unavailable"),
        ("private", "Private"),
        ("unknown", "Unknown"),
    ]

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="catalog_videos"
    )
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, related_name="videos"
    )
    video_id = models.TextField()
    title = models.TextField(default="")
    duration_sec = models.IntegerField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    thumbnail_url = models.TextField(default="")
    live_status = models.TextField(default="unknown")
    availability = models.TextField(
        choices=AVAILABILITY_CHOICES, default="unknown"
    )
    # Hydration: NULL means "not hydrated yet", which is not the same as "".
    description = models.TextField(null=True, blank=True)
    tags = models.JSONField(null=True, blank=True)  # docs/03 `text[]` → jsonb (§2.1)
    view_count = models.BigIntegerField(null=True, blank=True)
    like_count = models.BigIntegerField(null=True, blank=True)
    category = models.TextField(null=True, blank=True)
    hydrated_at = models.DateTimeField(null=True, blank=True)
    # Operator flags. `starred` doubles as the retention pin (never auto-delete).
    starred = models.BooleanField(default=False)
    ignored = models.BooleanField(default=False)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalog_video"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "video_id"], name="uq_catalog_video_source_video"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    availability__in=["available", "unavailable", "private", "unknown"]
                ),
                name="ck_catalog_video_availability",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source", "-published_at"], name="catalog_video_source_date_idx"
            ),
            models.Index(
                fields=["workspace", "video_id"], name="catalog_video_lookup_idx"
            ),
            models.Index(
                fields=["source", "hydrated_at"], name="catalog_video_hydrate_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.video_id} — {self.title or '(untitled)'}"
