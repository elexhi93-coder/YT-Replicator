"""youtube.api — the destination platform (U09), published surface.

Two responsibilities live here rather than in the adapter, because both are
*ours* rather than YouTube's:

* **Inventory sync writes what the platform said, and nothing else.** A video
  the API stops returning sets `is_present = false`; it is never deleted, so
  "the destination copy is gone" stays a fact we can read (docs/03 §8).
* **Quota is counted against the Pacific day.** The row for today is upserted
  on every attempt, and `quota_remaining` is derived from it — never from a
  UTC midnight, which is the legacy's D-03.

`unclaimed_inventory()` exists because an inventory row nobody can claim is
just a silent copy of the legacy's "what is on the channel?" question: the
unclaimed set is surfaced for review and never auto-adopted (INV-8).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from core.api import ChannelRef, get_destination_platform, quota_day_string
from youtube.errors import QuotaExhausted
from youtube.http import DAILY_UNIT_LIMIT
from youtube.models import DestinationInventory, QuotaUsage

__all__ = [
    "account_upload",
    "default_http",
    "mark_absent",
    "probe_auth",
    "quota_remaining",
    "quota_snapshot",
    "record_quota_exhausted",
    "sync_inventory",
    "unclaimed_inventory",
    "upload",
]


def default_http():
    """The real transport, built lazily so importing the module costs nothing."""
    from youtube.http import UrllibHttp

    return UrllibHttp()


def probe_auth(destination):
    """Check the destination's channel and record the outcome on the row."""
    platform = get_destination_platform()
    state = platform.probe_auth(destination.authorized_channel)
    destination.last_sync_at = timezone.now()
    destination.last_sync_error = "" if state.state == "valid" else "token rejected"
    destination.save(update_fields=["last_sync_at", "last_sync_error", "updated_at"])
    return state


@transaction.atomic
def sync_inventory(destination, *, cursor: str | None = None):
    """One page of channel inventory, upserted. Returns `(rows, next_cursor)`."""
    platform = get_destination_platform()
    channel = ChannelRef(
        channel_id=destination.pk,
        platform=destination.platform,
        external_channel_id=destination.authorized_channel.channel_id,
    )
    batch = platform.sync_inventory(channel, cursor, token=_token(destination))
    seen: list[str] = []
    for item in batch.items:
        seen.append(item.destination_video_id)
        DestinationInventory.objects.update_or_create(
            destination=destination,
            destination_video_id=item.destination_video_id,
            defaults={
                "workspace": destination.workspace,
                "title": item.title,
                "description_excerpt": item.description_excerpt,
                "published_at": item.published_at,
                "privacy": item.privacy_status,
                "duration_sec": item.duration_sec,
                "provenance_marker": item.marker,
                # A video that comes back is present again, and its observation
                # time moves — that is how a re-upload after a removal is seen.
                "is_present": True,
            },
        )
    destination.last_sync_at = timezone.now()
    destination.last_sync_error = ""
    destination.save(update_fields=["last_sync_at", "last_sync_error", "updated_at"])
    return list(batch.items), batch.next_cursor


def mark_absent(destination, *, keep_ids: list[str] | None = None) -> int:
    """Mark inventory rows not seen in a full sync as no longer present.

    Only for a *complete* sync (`keep_ids` is the full observed set): marking
    absent after a single page would delete the other pages from existence in
    all but name. Never deletes — the row keeps its history (docs/03 §8 rule 2).
    """
    queryset = DestinationInventory.objects.filter(
        destination=destination, is_present=True
    )
    if keep_ids is not None:
        queryset = queryset.exclude(destination_video_id__in=keep_ids)
    return queryset.update(is_present=False, last_observed_at=timezone.now())


def unclaimed_inventory(destination) -> list[DestinationInventory]:
    """Content on the channel we cannot account for. Never auto-adopted (INV-8)."""
    return list(
        DestinationInventory.objects.filter(
            destination=destination, matched_delivery_id__isnull=True, is_present=True
        ).order_by("-last_observed_at")
    )


# -- quota -------------------------------------------------------------------


def _token(destination) -> str:
    """The channel's access token, obtained the only documented way."""
    from credentials.api import valid_access_token

    return valid_access_token(destination.authorized_channel)


def quota_snapshot(destination, *, day: str | None = None) -> QuotaUsage:
    """Today's usage row, created on first use. The day is YouTube's, not UTC's."""
    quota_date = day or quota_day_string()
    row, _created = QuotaUsage.objects.get_or_create(
        destination=destination,
        quota_date=quota_date,
        defaults={"workspace": destination.workspace},
    )
    return row


def account_upload(destination, *, units: int = 0, day: str | None = None) -> QuotaUsage:
    """Record one upload attempt against the Pacific quota day."""
    row = quota_snapshot(destination, day=day)
    QuotaUsage.objects.filter(pk=row.pk).update(
        uploads_used=row.uploads_used + 1,
        units_used=row.units_used + units,
        updated_at=timezone.now(),
    )
    row.refresh_from_db()
    return row


def record_quota_exhausted(destination, *, day: str | None = None) -> QuotaUsage:
    """Mark the day as fully spent, so nothing else is attempted against it."""
    row = quota_snapshot(destination, day=day)
    QuotaUsage.objects.filter(pk=row.pk).update(
        uploads_used=max(row.uploads_used, destination.daily_max),
        units_used=max(row.units_used, DAILY_UNIT_LIMIT),
        updated_at=timezone.now(),
    )
    row.refresh_from_db()
    return row


def quota_remaining(destination, *, day: str | None = None) -> int:
    """Uploads left today, from our own count. Never negative.

    The count is local because the API reports quota by refusing an upload;
    planning against "try it and see" is how the legacy burned a morning of
    quota before discovering the channel was capped.
    """
    row = quota_snapshot(destination, day=day)
    return max(0, destination.daily_max - row.uploads_used)


def upload(destination, request, *, on_progress=None):
    """Upload to the destination and account for it, in that order.

    The attempt is counted *before* the call, so a platform failure that still
    consumed quota is not free to repeat forever. The exception propagates typed
    — `QuotaExhausted` reschedules for after the reset, everything else fails
    the job (Pillar 0 R6: no internal retries here).
    """
    platform = get_destination_platform()
    token = _token(destination)
    account_upload(destination, units=platform.unit_cost_for_upload())
    try:
        outcome = platform.upload(request, token=token, on_progress=on_progress)
    except QuotaExhausted:
        record_quota_exhausted(destination)
        raise
    return outcome
