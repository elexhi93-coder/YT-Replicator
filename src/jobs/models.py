"""
jobs.models — the queue table (docs/03 §7, Group 5 — Work).

The database *is* the queue: there is no broker, and that is the whole point
(D3). Three things in this file carry the design:

* **A live job is unique per `(workspace, pipeline, video, intent)`** — a
  partial unique index that excludes `cancelled` and `skipped`, so an operator
  can deliberately re-run one. The legacy designed this dedup and never
  shipped it; here it is the schema, not a promise in a comment.
* **A claim is a lease, not a lock.** `claim_expires_at` means a worker that
  dies holding a job does not strand it: the recovery pass returns expired
  claims to `queued`.
* **Failure is classified, not guessed.** `failed_transient` and
  `failed_permanent` are distinct states, because only one of them is retried
  and only the other is worth showing the operator.
"""

from django.db import models

INTENT_UPLOAD = "upload"
INTENT_REHYDRATE = "rehydrate"
INTENT_INSPECT = "inspect"
INTENT_CHOICES = [
    (INTENT_UPLOAD, "Upload"),
    (INTENT_REHYDRATE, "Rehydrate"),
    (INTENT_INSPECT, "Inspect"),
]

#: The only terminal success in the schema's vocabulary. docs/03 §7 spells the
#: status CHECK in upload terms, so every intent lands here; see CONTRACT §5.
STATUS_UPLOADED = "uploaded"

JOB_STATUSES = [
    ("queued", "Queued"),
    ("claimed", "Claimed"),
    ("downloading", "Downloading"),
    ("downloaded", "Downloaded"),
    ("uploading", "Uploading"),
    (STATUS_UPLOADED, STATUS_UPLOADED.title()),
    ("failed_transient", "Failed (transient)"),
    ("failed_permanent", "Failed (permanent)"),
    ("skipped", "Skipped"),
    ("cancelled", "Cancelled"),
]

#: States a job never leaves on its own: a retry creates a *new* job.
TERMINAL_STATUSES = frozenset(
    {STATUS_UPLOADED, "failed_permanent", "skipped", "cancelled"}
)
#: Statuses that keep occupying the dedup key.
LIVE_STATUSES = frozenset(
    {
        "queued",
        "claimed",
        "downloading",
        "downloaded",
        "uploading",
        "failed_transient",
    }
)


class Job(models.Model):
    """One unit of work for one video on one pipeline."""

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="jobs"
    )
    pipeline = models.ForeignKey(
        "pipelines.Pipeline", on_delete=models.CASCADE, related_name="jobs"
    )
    #: SET NULL, not CASCADE: a removed source must not delete queued work or
    #: the history of work already done for it.
    source = models.ForeignKey(
        "sources.Source",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="jobs",
    )
    source_video_id = models.TextField()  # 11-character YouTube id
    intent = models.TextField(choices=INTENT_CHOICES, default=INTENT_UPLOAD)
    status = models.TextField(choices=JOB_STATUSES, default="queued")
    priority = models.IntegerField(default=100)  # lower runs first
    attempt_count = models.IntegerField(default=0)
    claimed_by = models.TextField(default="")
    claimed_at = models.DateTimeField(null=True, blank=True)
    #: Lease expiry while claimed; also the retry-after marker while queued
    #: and backing off (see CONTRACT §5.1).
    claim_expires_at = models.DateTimeField(null=True, blank=True)
    error_code = models.TextField(default="")
    error_message = models.TextField(default="")
    skip_reason = models.TextField(default="")
    bytes_downloaded = models.BigIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "job"
        constraints = [
            # One live job per (pipeline, video, intent). Cancelled and skipped
            # rows are excluded so the operator can re-run one on purpose.
            models.UniqueConstraint(
                fields=["workspace", "pipeline", "source_video_id", "intent"],
                condition=~models.Q(status__in=["cancelled", "skipped"]),
                name="job_live_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "queued",
                        "claimed",
                        "downloading",
                        "downloaded",
                        "uploading",
                        "uploaded",
                        "failed_transient",
                        "failed_permanent",
                        "skipped",
                        "cancelled",
                    ]
                ),
                name="ck_job_status",
            ),
            models.CheckConstraint(
                condition=models.Q(intent__in=["upload", "rehydrate", "inspect"]),
                name="ck_job_intent",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__gte=0), name="ck_job_attempt_count"
            ),
        ]
        indexes = [
            models.Index(
                fields=["priority", "created_at"],
                condition=models.Q(status="queued"),
                name="job_claim_idx",
            ),
            models.Index(
                fields=["workspace", "pipeline", "status"], name="job_pipeline_idx"
            ),
            models.Index(
                fields=["workspace", "source_video_id"], name="job_video_idx"
            ),
            models.Index(
                fields=["status", "claim_expires_at"], name="job_stale_claim_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_video_id} ({self.intent}, {self.status})"
