"""delivery.api — the ledger (U10), published surface.

The ledger is what makes every other module's decision checkable afterwards, and
two rules define it:

* **The delivery row is written before the upload.** The provenance marker
  embeds the delivery id, so the id must exist before the bytes are sent. A
  crash between the two leaves a `queued` row — exactly the state `reconcile()`
  exists to resolve.
* **A pair is delivered once.** A second `deliver()` for an already-uploaded
  pair raises `AlreadyDelivered` instead of re-uploading. The legacy's own
  advice was "reconcile before retrying"; this is that rule in code.

Reconciliation compares what the channel says (`destination_inventory`) with
what the ledger says, and classifies every difference into one of four outcomes
rather than a boolean.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.api import (
    PROVENANCE_MARKER_REGEX,
    UploadRequest,
    format_provenance_marker,
    now_utc,
)
from delivery.dto import DeliveryResult, ReconcileReport
from delivery.errors import (
    AlreadyDelivered,
    DeliveryNotFound,
    InvalidDeliverySetting,
    MediaMissing,
)
from delivery.models import Delivery, DeliveryAttempt

@dataclass(frozen=True)
class DeliveryFacts:
    """What the ledger knows about one video (U12 `RetentionOracle`)."""

    #: INV-2: True only when every named destination has reached a terminal
    #: ledger state. `uploaded` is success; `failed` is a permanent failure and
    #: nothing more will be attempted; `removed` was delivered and then taken
    #: down by an operator, which is likewise final. `not_delivered`, `queued`
    #: and `uploading` are all still in flight, and deletion is forbidden.
    all_terminal: bool
    uploaded_at: datetime | None
    pending_destinations: tuple[int, ...]


#: A delivery in one of these states will not change on its own.
TERMINAL_DELIVERY_STATUSES = ("uploaded", "failed", "removed")


def delivery_facts(
    workspace, source_video_id: str, destination_ids
) -> DeliveryFacts:
    """Summarise the ledger for one video across the given destinations.

    `destination_ids` is the pipeline's *enabled* set. A destination with no
    ledger row at all is pending, not absent — nothing has been attempted, so
    INV-2 forbids deleting the local file.
    """
    wanted = list(destination_ids)
    rows = {
        row.destination_id: row
        for row in Delivery.objects.filter(
            workspace=workspace,
            source_video_id=source_video_id,
            destination_id__in=wanted,
        )
    }
    pending = tuple(
        destination_id
        for destination_id in wanted
        if destination_id not in rows
        or rows[destination_id].status not in TERMINAL_DELIVERY_STATUSES
    )
    uploaded = [
        row.uploaded_at
        for row in rows.values()
        if row.uploaded_at is not None and row.destination_id not in pending
    ]
    return DeliveryFacts(
        all_terminal=not pending,
        uploaded_at=min(uploaded) if uploaded else None,
        pending_destinations=pending,
    )


__all__ = [
    "DeliveryFacts",
    "DeliveryResult",
    "ReconcileReport",
    "TERMINAL_DELIVERY_STATUSES",
    "attempts_for",
    "deliver",
    "delivery_facts",
    "get_delivery",
    "list_deliveries",
    "mark_removed",
    "parse_marker",
    "reconcile",
]

ORIGIN_SYSTEM = "system"
ORIGIN_RETRY = "retry"
ORIGIN_MANUAL = "manual"
_ORIGINS = {ORIGIN_SYSTEM, ORIGIN_RETRY, ORIGIN_MANUAL}


def parse_marker(description: str) -> tuple[str, int] | None:
    """Read a provenance marker back out of a description.

    This is the parse half of the Pillar 0 format, and it belongs here rather
    than in `youtube`: the adapter *extracts* the raw line (R5), the ledger
    *interprets* it.
    """
    match = PROVENANCE_MARKER_REGEX.search(description or "")
    if not match:
        return None
    return match.group("source_video_id"), int(match.group("delivery_id"))


def deliver(
    destination,
    *,
    source_video_id: str,
    media_path,
    title: str,
    description: str = "",
    source_title: str = "",
    tags: tuple[str, ...] = (),
    category_id: str = "",
    privacy: str = "",
    job=None,
    origin: str = ORIGIN_SYSTEM,
) -> DeliveryResult:
    """Deliver one video to one destination, recording every attempt.

    Order matters and is not negotiable: the delivery row is created *first*,
    because the marker embedded in the description contains its id. The attempt
    row is written before the bytes move, so a worker that dies mid-upload
    leaves evidence rather than silence.
    """
    if origin not in _ORIGINS:
        raise InvalidDeliverySetting("origin", origin, _ORIGINS)
    if not Path(media_path).exists():
        raise MediaMissing(f"No media file at {media_path}.")

    existing = Delivery.objects.filter(
        destination=destination, source_video_id=source_video_id
    ).first()
    if existing is not None and existing.status == "uploaded":
        # The memory rule: reconcile before retrying. A second upload of a
        # delivered pair is the waste the legacy is remembered for.
        raise AlreadyDelivered(existing)

    delivery = existing or Delivery.objects.create(
        workspace=destination.workspace,
        source_video_id=source_video_id,
        destination=destination,
        status="queued",
    )
    # The marker is a suffix line, so the body stays intact and readable.
    marker = format_provenance_marker(source_video_id, delivery.pk)
    attempt = DeliveryAttempt.objects.create(
        workspace=delivery.workspace,
        delivery=delivery,
        attempt_no=_next_attempt_no(delivery),
        status="uploading",
        origin=origin,
        privacy=privacy or delivery.privacy,
    )

    delivery.status = "uploading"
    delivery.provenance_marker = marker
    delivery.destination_title = title
    delivery.source_title_snapshot = source_title or title
    delivery.last_job_id = getattr(job, "pk", None) or delivery.last_job_id
    if privacy:
        delivery.privacy = privacy
    delivery.save()

    from youtube.api import upload as youtube_upload

    request = UploadRequest(
        source_video_id=source_video_id,
        media_path=Path(media_path),
        title=title,
        description=f"{description.rstrip()}\n{marker}" if description else marker,
        tags=tuple(tags),
        category_id=category_id or "22",
        privacy=delivery.privacy,
        made_for_kids=False,
        contains_synthetic_media=False,
        thumbnail_path=None,
        provenance_marker=marker,
    )
    try:
        outcome = youtube_upload(destination, request)
    except BaseException as exc:
        _fail(delivery, attempt, exc)
        raise

    delivery.status = "uploaded"
    delivery.destination_video_id = outcome.destination_video_id
    delivery.destination_url = outcome.destination_url
    delivery.privacy = outcome.privacy or delivery.privacy
    delivery.uploaded_at = now_utc()
    delivery.error_message = ""
    delivery.match_method = "marker"
    delivery.save()

    attempt.status = "uploaded"
    attempt.destination_video_id = outcome.destination_video_id
    attempt.destination_url = outcome.destination_url
    attempt.privacy = delivery.privacy
    attempt.http_status = outcome.http_status
    attempt.finished_at = now_utc()
    attempt.save()

    _claim_inventory(destination, delivery)
    return DeliveryResult(
        delivery_id=delivery.pk,
        attempt_no=attempt.attempt_no,
        status=delivery.status,
        destination_video_id=outcome.destination_video_id,
        destination_url=outcome.destination_url,
        provenance_marker=marker,
    )


def reconcile(destination) -> ReconcileReport:
    """Compare the channel against the ledger and classify every difference.

    Run this before retrying anything, and on a schedule: it is the only thing
    that notices a video we uploaded has been deleted, and the only thing that
    stops us "adopting" someone else's video as ours.
    """
    from youtube.api import inventory_rows

    inventory = {row.destination_video_id: row for row in inventory_rows(destination)}
    claimed_ok: list[str] = []
    unclaimed: list[str] = []
    missing: list[str] = []
    mismatch: list[str] = []

    for video_id, row in inventory.items():
        if not row.is_present:
            continue
        if row.matched_delivery_id:
            delivery = _delivery_by_id(row.matched_delivery_id)
            if delivery is not None and delivery.status == "uploaded":
                claimed_ok.append(video_id)
            else:
                # The inventory points at a delivery we no longer agree with.
                mismatch.append(video_id)
            continue
        # No ledger row. If it carries a marker, that marker points somewhere we
        # have no record of; either way it is *not* ours to claim (INV-8).
        if row.provenance_marker:
            parsed = parse_marker(f"text {row.provenance_marker}")
            if parsed is not None and _delivery_by_id(parsed[1]) is None:
                mismatch.append(video_id)
                continue
        unclaimed.append(video_id)

    for delivery in Delivery.objects.filter(destination=destination, status="uploaded"):
        seen = inventory.get(delivery.destination_video_id or "")
        # A row that exists but reads `is_present = False` is exactly how a
        # deleted copy shows up: the sync saw the id once, then stopped.
        if seen is not None and seen.is_present:
            continue
        # Our ledger says uploaded, the channel does not show it. Flag it and
        # do nothing: the operator may have deleted it deliberately.
        missing.append(delivery.destination_video_id or delivery.source_video_id)

    return ReconcileReport(
        destination_id=destination.pk,
        claimed_ok=tuple(sorted(claimed_ok)),
        unclaimed_present=tuple(sorted(unclaimed)),
        missing_expected=tuple(sorted(missing)),
        marker_mismatch=tuple(sorted(mismatch)),
    )


def mark_removed(delivery: Delivery, reason: str) -> Delivery:
    """Operator confirmation that a destination copy is gone.

    Deliberately a separate, manual step: a missing video is *evidence*, not a
    verdict. Auto-clearing the ledger row here is precisely the mistake that
    loses the history this module exists to keep (INV-4).
    """
    if not reason:
        raise InvalidDeliverySetting("reason", reason, {"a non-empty explanation"})
    if delivery.status != "uploaded":
        raise InvalidDeliverySetting(
            "status",
            delivery.status,
            {"uploaded (only an uploaded delivery can be removed)"},
        )
    delivery.status = "removed"
    delivery.error_message = reason
    delivery.save(update_fields=["status", "error_message", "updated_at"])
    return delivery


def get_delivery(delivery_id) -> Delivery:
    try:
        return Delivery.objects.get(pk=delivery_id)
    except Delivery.DoesNotExist as exc:
        raise DeliveryNotFound(f"No delivery {delivery_id}.") from exc


def list_deliveries(
    workspace, *, destination=None, status: str | None = None
) -> list[Delivery]:
    """Deliveries newest first. The History page (U20) reads this."""
    queryset = Delivery.objects.filter(workspace=workspace)
    if destination is not None:
        queryset = queryset.filter(destination=destination)
    if status is not None:
        queryset = queryset.filter(status=status)
    return list(queryset.order_by("-created_at", "-id"))


def attempts_for(delivery: Delivery) -> list[DeliveryAttempt]:
    """Every attempt, oldest first — the audit trail, never pruned."""
    return list(delivery.attempts.order_by("attempt_no"))


def _next_attempt_no(delivery: Delivery) -> int:
    last = delivery.attempts.order_by("-attempt_no").first()
    return (last.attempt_no + 1) if last else 1


def _delivery_by_id(delivery_id: int) -> Delivery | None:
    return Delivery.objects.filter(pk=delivery_id).first()


def _fail(delivery: Delivery, attempt: DeliveryAttempt, error: BaseException) -> None:
    """Record a failed attempt, then let the typed error reach the caller.

    The row is written before the error propagates: a job that fails with no
    trace in the ledger is the state the legacy was found in.
    """
    delivery.status = "failed"
    delivery.error_message = str(error)[:2000]
    delivery.save(update_fields=["status", "error_message", "updated_at"])
    attempt.status = "failed"
    attempt.error_code = getattr(error, "default_code", "") or type(error).__name__
    attempt.error_message = str(error)[:2000]
    attempt.finished_at = now_utc()
    attempt.save(
        update_fields=["status", "error_code", "error_message", "finished_at"]
    )


def _claim_inventory(destination, delivery: Delivery) -> int:
    """Point the inventory row for the video we just uploaded at this delivery.

    This is ledger matching, not a title guess: only the marker is proof of
    authorship, and a fingerprint match is a suggestion (docs/06). The write
    goes through `youtube.api`, so this module never touches that table.
    """
    from youtube.api import claim_inventory

    return claim_inventory(
        destination, delivery.destination_video_id or "", delivery
    )
