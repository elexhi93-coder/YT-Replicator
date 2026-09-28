"""
pipelines.models — the five tables of docs/03 §6 (Group 4).

`download_profile`, `pipeline`, `pipeline_source`, `destination` and
`pipeline_destination`. Three decisions worth remembering:

* **A pipeline starts as a draft.** A half-configured pipeline cannot run,
  which is the explicit answer to the legacy's open question of whether
  backfill should start by itself.
* **The backfill queue is a cursor, not a list.** `backfill_cursor_published_at`
  replaces the legacy's `backfill_queue` / `videos_seen` JSON blobs, so what
  is left to backfill is a query against `catalog_video` and needs no
  maintenance (fixes F-04, F-05).
* **`destination` lives at workspace level** and joins to pipelines, so one
  authorised channel can serve several pipelines without being duplicated.

Cross-module links are string references (`"sources.Source"`,
`"credentials.AuthorizedChannel"`), so no sibling is imported: Django resolves
them through the app registry, and behaviour still crosses only `<sibling>.api`
(INV-12).
"""

from django.db import models

PRIVACY_CHOICES = [
    ("private", "Private"),
    ("unlisted", "Unlisted"),
    ("public", "Public"),
]
RETENTION_MODES = [
    ("keep", "Keep"),
    ("immediate", "Immediate"),
    ("after_n_jobs", "After N jobs"),
    ("after_hours", "After N hours"),
]


class DownloadProfile(models.Model):
    """Reusable quality/format settings. v1 never re-encodes (D15)."""

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="download_profiles",
    )
    name = models.TextField()
    max_height = models.IntegerField(default=0)  # 0 = no cap
    container = models.TextField(default="mp4")
    video_codec = models.TextField(default="any")
    audio_codec = models.TextField(default="any")
    write_subs = models.BooleanField(default=True)
    #: docs/03 §6 declares `text[]`; stored as JSON (jsonb on PostgreSQL) because
    #: the test harness runs SQLite — same reconciliation as `scopes`/`tags`.
    sub_langs = models.JSONField(default=list, blank=True)
    write_thumbnail = models.BooleanField(default=True)
    write_info_json = models.BooleanField(default=True)
    skip_shorts = models.BooleanField(default=False)
    shorts_max_seconds = models.IntegerField(default=60)
    skip_live = models.BooleanField(default=True)
    #: Escape hatch for yt-dlp flags the model does not name. Empty by default:
    #: an unbounded override is how the legacy profile became unreproducible.
    extra_ytdlp_opts = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "download_profile"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"], name="uq_download_profile_workspace_name"
            ),
            models.CheckConstraint(
                condition=models.Q(max_height__gte=0), name="ck_download_profile_height"
            ),
        ]


class Pipeline(models.Model):
    """One replication job: N sources → M destinations, with its own policy."""

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
    ]

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="pipelines"
    )
    name = models.TextField()
    description = models.TextField(default="")
    status = models.TextField(choices=STATUS_CHOICES, default=STATUS_DRAFT)
    priority = models.IntegerField(default=100)  # lower runs first
    download_profile = models.ForeignKey(
        DownloadProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pipelines",
    )
    default_privacy = models.TextField(choices=PRIVACY_CHOICES, default="unlisted")
    provenance_marker = models.BooleanField(default=True)  # D2
    retention_mode = models.TextField(choices=RETENTION_MODES, default="keep")
    retention_n = models.IntegerField(default=2)
    retention_hours = models.IntegerField(default=24)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pipeline"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"], name="uq_pipeline_workspace_name"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "active", "paused"]),
                name="ck_pipeline_status",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    default_privacy__in=["private", "unlisted", "public"]
                ),
                name="ck_pipeline_default_privacy",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    retention_mode__in=[
                        "keep",
                        "immediate",
                        "after_n_jobs",
                        "after_hours",
                    ]
                ),
                name="ck_pipeline_retention_mode",
            ),
            models.CheckConstraint(
                condition=models.Q(retention_n__gte=1), name="ck_pipeline_retention_n"
            ),
            models.CheckConstraint(
                condition=models.Q(retention_hours__gte=1),
                name="ck_pipeline_retention_hours",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "status", "priority"], name="pipeline_run_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"


class PipelineSource(models.Model):
    """One source feeding a pipeline, with its mode and backfill cursor.

    The backfill queue is a cursor, not a list: "what is left to backfill" is
    `catalog_video` filtered by `backfill_cursor_published_at`, so it is always
    correct and resumable from any point.
    """

    MODE_MONITOR = "monitor"
    MODE_BACKFILL = "backfill"
    MODE_CHOICES = [
        (MODE_MONITOR, "Monitor"),
        (MODE_BACKFILL, "Backfill"),
    ]

    BACKFILL_NOT_STARTED = "not_started"
    BACKFILL_RUNNING = "running"
    BACKFILL_PAUSED = "paused"
    BACKFILL_COMPLETE = "complete"
    BACKFILL_STOPPED = "stopped"
    BACKFILL_STATES = [
        (BACKFILL_NOT_STARTED, "Not started"),
        (BACKFILL_RUNNING, "Running"),
        (BACKFILL_PAUSED, "Paused"),
        (BACKFILL_COMPLETE, "Complete"),
        (BACKFILL_STOPPED, "Stopped"),
    ]

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="pipeline_sources",
    )
    pipeline = models.ForeignKey(
        Pipeline, on_delete=models.CASCADE, related_name="pipeline_sources"
    )
    source = models.ForeignKey(
        "sources.Source", on_delete=models.CASCADE, related_name="pipeline_sources"
    )
    mode = models.TextField(choices=MODE_CHOICES, default=MODE_MONITOR)
    priority = models.IntegerField(default=100)
    #: NULL means "governed only by the destination's own cap and quota".
    daily_cap = models.IntegerField(null=True, blank=True)
    backfill_state = models.TextField(
        choices=BACKFILL_STATES, default=BACKFILL_NOT_STARTED
    )
    backfill_cursor_published_at = models.DateTimeField(null=True, blank=True)
    backfill_done_count = models.IntegerField(default=0)
    backfill_total_count = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pipeline_source"
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "source"], name="uq_pipeline_source_pair"
            ),
            models.CheckConstraint(
                condition=models.Q(mode__in=["monitor", "backfill"]),
                name="ck_pipeline_source_mode",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    backfill_state__in=[
                        "not_started",
                        "running",
                        "paused",
                        "complete",
                        "stopped",
                    ]
                ),
                name="ck_pipeline_source_backfill_state",
            ),
            models.CheckConstraint(
                condition=models.Q(daily_cap__isnull=True)
                | models.Q(daily_cap__gt=0),
                name="ck_pipeline_source_daily_cap",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline", "backfill_state"],
                name="pipeline_source_backfill_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.pipeline_id}:{self.source_id} ({self.mode})"


class Destination(models.Model):
    """A workspace-level upload target bound to an authorised channel.

    `ON DELETE RESTRICT` on the channel is deliberate: a destination must
    never be orphaned into a state with nowhere to deliver.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="destinations"
    )
    authorized_channel = models.ForeignKey(
        "credentials.AuthorizedChannel",
        on_delete=models.RESTRICT,
        related_name="destinations",
    )
    label = models.TextField()
    #: A CHECK permitting one value in v1; another platform is a deliberate
    #: migration, never an accident.
    platform = models.TextField(default="youtube")
    default_privacy = models.TextField(choices=PRIVACY_CHOICES, default="unlisted")
    daily_max = models.IntegerField(default=6)
    enabled = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(default="")
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "destination"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "label"], name="uq_destination_workspace_label"
            ),
            models.CheckConstraint(
                condition=models.Q(platform="youtube"), name="ck_destination_platform"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    default_privacy__in=["private", "unlisted", "public"]
                ),
                name="ck_destination_default_privacy",
            ),
            models.CheckConstraint(
                condition=models.Q(daily_max__gt=0), name="ck_destination_daily_max"
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "enabled"], name="destination_enabled_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.platform})"


class PipelineDestination(models.Model):
    """A destination's participation in one pipeline.

    By D14 the v1 rule is simple: every enabled row here receives every video
    from every source of the pipeline. The overrides exist because "keep the
    last N jobs" must stay computable for a destination that serves more than
    one pipeline.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="pipeline_destinations",
    )
    pipeline = models.ForeignKey(
        Pipeline, on_delete=models.CASCADE, related_name="pipeline_destinations"
    )
    destination = models.ForeignKey(
        Destination, on_delete=models.CASCADE, related_name="pipeline_destinations"
    )
    enabled = models.BooleanField(default=True)
    priority = models.IntegerField(default=100)
    privacy_override = models.TextField(
        choices=PRIVACY_CHOICES, null=True, blank=True
    )
    retention_mode_override = models.TextField(
        choices=RETENTION_MODES, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pipeline_destination"
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "destination"],
                name="uq_pipeline_destination_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    privacy_override__in=["private", "unlisted", "public"]
                )
                | models.Q(privacy_override__isnull=True),
                name="ck_pipeline_destination_privacy",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    retention_mode_override__in=[
                        "keep",
                        "immediate",
                        "after_n_jobs",
                        "after_hours",
                    ]
                )
                | models.Q(retention_mode_override__isnull=True),
                name="ck_pipeline_destination_retention",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline", "enabled"], name="pipeline_destination_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.pipeline_id}:{self.destination_id}"
