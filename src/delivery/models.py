"""
delivery.models — the ledger (docs/03 §8, Group 6).

`delivery` holds the **current** state; `delivery_attempt` is the **immutable**
record of every try. That split is the whole point: when a delivery's
destination video is deleted and re-uploaded, `delivery.destination_video_id`
moves to the new id while the old one stays in attempt 1 forever, so history
is never overwritten — only superseded (INV-4).

Two fields exist purely so history stays readable:

* `source_title_snapshot` — what the source called it *at upload time*. The
  source can retitle or delete a video afterwards, and without the snapshot
  the two halves of a delivery could never be compared. Its absence is why
  reconciliation was impossible in the legacy (D-13).
* `origin` on the attempt — an automatic retry and an operator-initiated
  re-upload are otherwise indistinguishable, which is how "why did this
  upload twice?" ends up with no answer.
"""

from django.db import models

DELIVERY_STATUSES = [
    ("not_delivered", "Not delivered"),
    ("queued", "Queued"),
    ("uploading", "Uploading"),
    ("uploaded", "Uploaded"),
    ("failed", "Failed"),
    ("removed", "Removed"),
]

#: How this row came to claim a destination video. `fingerprint` is a
#: *suggestion* only (docs/06): a title match is never proof of authorship.
MATCH_METHODS = [
    ("ledger", "Ledger"),
    ("marker", "Marker"),
    ("fingerprint", "Fingerprint"),
    ("manual", "Manual"),
]

ATTEMPT_STATUSES = [
    ("uploading", "Uploading"),
    ("uploaded", "Uploaded"),
    ("failed", "Failed"),
    ("cancelled", "Cancelled"),
]

ORIGINS = [("system", "System"), ("retry", "Retry"), ("manual", "Manual")]


class Delivery(models.Model):
    """One (source video → destination) delivery, and its current state."""

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="deliveries"
    )
    source_video_id = models.TextField()
    #: RESTRICT, not CASCADE: a destination with history is soft-deleted, never
    #: hard-deleted. Enforced by the database rather than by discipline (D-12).
    destination = models.ForeignKey(
        "pipelines.Destination",
        on_delete=models.RESTRICT,
        related_name="deliveries",
    )
    status = models.TextField(choices=DELIVERY_STATUSES, default="not_delivered")
    destination_video_id = models.TextField(null=True, blank=True)
    destination_url = models.TextField(default="")
    destination_title = models.TextField(default="")  # as we uploaded it
    source_title_snapshot = models.TextField(default="")  # title at upload time
    provenance_marker = models.TextField(default="")
    match_method = models.TextField(choices=MATCH_METHODS, default="ledger")
    privacy = models.TextField(default="unlisted")
    uploaded_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(default="")
    last_job_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_video_id", "destination"],
                name="uq_delivery_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "not_delivered",
                        "queued",
                        "uploading",
                        "uploaded",
                        "failed",
                        "removed",
                    ]
                ),
                name="ck_delivery_status",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    match_method__in=["ledger", "marker", "fingerprint", "manual"]
                ),
                name="ck_delivery_match_method",
            ),
        ]
        indexes = [
            models.Index(
                fields=["destination", "status"], name="delivery_destination_idx"
            ),
            models.Index(
                fields=["workspace", "source_video_id"], name="delivery_video_idx"
            ),
            models.Index(
                fields=["destination", "-uploaded_at"], name="delivery_retention_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_video_id} -> {self.destination_id} ({self.status})"


class DeliveryAttempt(models.Model):
    """One attempt at a delivery. Append-only: rows are never updated.

    The identifying values (`destination_video_id`, `destination_url`) are
    write-once *per attempt*, which is what preserves a superseded id when a
    deleted video is re-uploaded. Only `finished_at` is written again, to close
    the attempt out.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="delivery_attempts"
    )
    delivery = models.ForeignKey(
        Delivery, on_delete=models.CASCADE, related_name="attempts"
    )
    attempt_no = models.IntegerField()
    status = models.TextField(choices=ATTEMPT_STATUSES)
    origin = models.TextField(choices=ORIGINS, default="system")
    destination_video_id = models.TextField(null=True, blank=True)
    destination_url = models.TextField(default="")
    privacy = models.TextField(default="unlisted")
    http_status = models.IntegerField(null=True, blank=True)
    error_code = models.TextField(default="")
    error_message = models.TextField(default="")
    bytes_sent = models.BigIntegerField(default=0)
    duration_ms = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "delivery_attempt"
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "attempt_no"], name="uq_delivery_attempt_no"
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_no__gte=1), name="ck_attempt_no"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["uploading", "uploaded", "failed", "cancelled"]
                ),
                name="ck_attempt_status",
            ),
            models.CheckConstraint(
                condition=models.Q(origin__in=["system", "retry", "manual"]),
                name="ck_attempt_origin",
            ),
        ]
        indexes = [
            models.Index(
                fields=["delivery", "-attempt_no"], name="delivery_attempt_recent_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"attempt {self.attempt_no} of {self.delivery_id} ({self.status})"
