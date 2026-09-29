"""
youtube.models — what the platform told us, and what it cost (docs/03 §8).

`destination_inventory` and `quota_usage`. Three rules in this file are the
capability the legacy never had (D-13):

* **Inventory is observation, not ownership.** A sync writes what the YouTube
  API returned; it says nothing about what *we* did — that is `delivery`.
* **A sync never deletes.** A video the API stops returning sets
  `is_present = false`, which makes "the destination copy is gone" a
  *detectable fact* instead of a guess. `last_observed_at` freezes on that row,
  so "when did we last see it" and "when did we stop seeing it" differ.
* **`quota_date` is a Pacific date.** YouTube's day starts at midnight Pacific;
  counting from UTC midnight is the legacy's D-03, an eight-hour window in
  which the app believes it has budget it does not have.
"""

from django.db import models

PRIVACY_CHOICES = [
    ("public", "Public"),
    ("unlisted", "Unlisted"),
    ("private", "Private"),
    ("unknown", "Unknown"),
]

#: How an inventory row was tied to one of our deliveries (docs/02 §4).
#: `none` is the unclaimed state — surfaced for review, never auto-adopted
#: (INV-8).
MATCH_METHODS = [
    ("none", "None"),
    ("marker", "Marker"),
    ("ledger", "Ledger"),
    ("fingerprint", "Fingerprint"),
]


class DestinationInventory(models.Model):
    """What the destination channel currently holds, as last observed."""

    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="destination_inventory",
    )
    destination = models.ForeignKey(
        "pipelines.Destination",
        on_delete=models.CASCADE,
        related_name="inventory",
    )
    destination_video_id = models.TextField()
    title = models.TextField(default="")
    description_excerpt = models.TextField(default="")
    published_at = models.DateTimeField(null=True, blank=True)
    privacy = models.TextField(choices=PRIVACY_CHOICES, default="unknown")
    duration_sec = models.IntegerField(null=True, blank=True)
    #: The raw marker line found in the description, stored rather than
    #: re-derived: a marker whose format later changes still reads correctly
    #: in history. Extracting it is this module's job; interpreting it belongs
    #: to `delivery` (Pillar 0 R5).
    provenance_marker = models.TextField(null=True, blank=True)
    #: **Not a foreign key yet.** docs/03 §8 declares
    #: `REFERENCES delivery(id)`, but `delivery` is created by U10. The column
    #: exists so the table matches the schema; U10's migration adds the
    #: constraint. See CONTRACT §5.1.
    matched_delivery_id = models.BigIntegerField(null=True, blank=True)
    match_method = models.TextField(
        choices=MATCH_METHODS, default="none"
    )
    is_present = models.BooleanField(default=True)
    first_observed_at = models.DateTimeField(auto_now_add=True)
    last_observed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "destination_inventory"
        constraints = [
            models.UniqueConstraint(
                fields=["destination", "destination_video_id"],
                name="uq_destination_inventory_video",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    privacy__in=["public", "unlisted", "private", "unknown"]
                ),
                name="ck_destination_inventory_privacy",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    match_method__in=["none", "marker", "ledger", "fingerprint"]
                ),
                name="ck_destination_inventory_match_method",
            ),
        ]
        indexes = [
            # The unclaimed set: the queue a reviewer works through. (Index
            # names are capped at 30 characters by Django, so these are short
            # forms of docs/03 §8's names — see CONTRACT §5.3.)
            models.Index(
                fields=["destination", "matched_delivery_id"],
                condition=models.Q(matched_delivery_id__isnull=True),
                name="inv_unclaimed_idx",
            ),
            models.Index(
                fields=["destination", "title"],
                name="inv_title_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.destination_id}:{self.destination_video_id}"


class QuotaUsage(models.Model):
    """One row per (destination, YouTube quota day).

    `units_used` is tracked next to `uploads_used` because units are the real
    constraint: an upload costs ~1 600 units against 10 000 a day, so counting
    uploads alone cannot explain an exhaustion — and being able to say *why*
    the budget ran out is the operational clarity the legacy lacked.
    """

    workspace = models.ForeignKey(
        "accounts.Workspace", on_delete=models.CASCADE, related_name="quota_usage"
    )
    destination = models.ForeignKey(
        "pipelines.Destination", on_delete=models.CASCADE, related_name="quota_usage"
    )
    quota_date = models.DateField()  # Pacific midnight, not UTC
    uploads_used = models.IntegerField(default=0)
    units_used = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "quota_usage"
        constraints = [
            models.UniqueConstraint(
                fields=["destination", "quota_date"], name="uq_quota_usage_day"
            ),
            models.CheckConstraint(
                condition=models.Q(uploads_used__gte=0), name="ck_quota_usage_uploads"
            ),
            models.CheckConstraint(
                condition=models.Q(units_used__gte=0), name="ck_quota_usage_units"
            ),
        ]
        indexes = [
            models.Index(
                fields=["destination", "-quota_date"], name="quota_usage_recent_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.destination_id} {self.quota_date}: {self.uploads_used} uploads"
