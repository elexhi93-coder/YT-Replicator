from __future__ import annotations

"""delivery.errors — typed errors for the ledger (docs/04 §5).

The distinction that matters here is between *this* attempt failing and the
delivery being impossible. A 429 is a failed attempt on a delivery that will
succeed later; an already-delivered pair is not an error at all but a fact the
caller asked about.
"""

from core.api import PermanentError


class DeliveryError(PermanentError):
    """Base for ledger-level failures."""

    default_code = "delivery_error"


class DeliveryNotFound(DeliveryError):
    """No delivery matches the lookup."""

    default_code = "delivery_not_found"


class AlreadyDelivered(DeliveryError):
    """The pair is already delivered and still present on the destination.

    Raised by `deliver()` rather than silently re-uploading: the memory rule is
    *reconcile before retrying*, and a second upload of the same video is the
    exact waste the legacy made.
    """

    default_code = "already_delivered"

    def __init__(self, delivery) -> None:
        super().__init__(
            f"{delivery.source_video_id} is already delivered to "
            f"destination {delivery.destination_id} as "
            f"{delivery.destination_video_id}."
        )
        self.delivery_id = delivery.pk


class MediaMissing(DeliveryError):
    """The media file this job refers to is not on disk (U11 owns downloads)."""

    default_code = "media_missing"


class InvalidDeliverySetting(DeliveryError):
    """A value outside the schema's CHECK vocabulary (origin, reason, ...)."""

    default_code = "delivery_invalid_setting"

    def __init__(self, field: str, value: object, allowed) -> None:
        super().__init__(f"{field}={value!r} is not one of {sorted(allowed)}.")
        self.field = field
        self.value = value


__all__ = [
    "AlreadyDelivered",
    "DeliveryError",
    "DeliveryNotFound",
    "InvalidDeliverySetting",
    "MediaMissing",
]
