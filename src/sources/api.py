"""sources.api — Sources & Catalog (U07), published surface (docs/04 §5).

Three rules shape everything here:

* **The SSRF guard is not optional.** `normalize_source_url` runs before any
  network call, so a non-YouTube host is refused without a request (INV-7).
* **Nothing is ever deleted.** A video that disappears becomes
  `availability='unavailable'` and keeps its history — the ledger in
  `delivery` must stay meaningful (INV-4).
* **Only this module writes `source`/`catalog_video`.** Siblings call these
  functions; they never join our tables directly (INV-11/INV-12).

No function here retries. `jobs` owns the retry policy (Pillar 0 R6), so a
throttle leaves the row untouched and the error propagates typed.
"""

from __future__ import annotations

from django.utils import timezone

from core.api import SourceRef, VideoRef, get_source_provider, now_utc
from sources.dto import HydrateOutcome, ScanOutcome
from sources.errors import ItemGone, SourceUnresolvable
from sources.models import CatalogVideo, Source
from sources.urls import normalize_source_url

# `workspace` parameters are documented as an `accounts.Workspace`, but that
# type is deliberately not imported: INV-12 allows `accounts` only through
# `accounts.api`, and tests/test_module_boundaries.py enforces it at the
# import level. Annotations stay unevaluated (`from __future__ import
# annotations`), so naming the type in prose costs nothing.

__all__ = [
    "HydrateOutcome",
    "ScanOutcome",
    "add_source",
    "hydrate",
    "is_starred",
    "list_sources",
    "scan",
    "source_provider_factory",
]


def is_starred(workspace, source_video_id: str) -> bool:
    """Is this video starred? F-10: a star *is* the retention pin.

    Published for the U12 `RetentionOracle`, which is the only way `media` can
    learn about a flag that lives on this module's table. A video we have never
    scanned is not starred, so absence is `False` rather than an error.
    """
    return CatalogVideo.objects.filter(
        workspace=workspace, video_id=source_video_id, starred=True
    ).exists()


def source_provider_factory():
    """The Port A binding this process uses (Pillar 0 §4).

    Re-exported from `provider` so the wiring in `ui.apps` depends only on
    this published surface — a sibling importing `sources.provider` would
    break the one-way arrow the registry exists to protect (INV-12).
    """
    from sources.provider import YouTubeSourceProvider

    return YouTubeSourceProvider()


def add_source(workspace, url: str, *, name: str = "") -> Source:
    """Register a channel or playlist from operator input.

    Validates through the SSRF allow-list, then resolves the canonical
    external id. Re-registering the same `external_id` in the same workspace
    returns the existing row rather than raising: the operator's intent is
    satisfied either way, and a duplicate is not an error worth a traceback.
    """
    normalized = normalize_source_url(url)  # raises SourceUrlInvalid
    resolved = get_source_provider().resolve(normalized.url)
    if not resolved.external_id:
        raise SourceUnresolvable(f"{url!r} resolved to no external id.")
    source, _created = Source.objects.get_or_create(
        workspace=workspace,
        external_id=resolved.external_id,
        defaults={
            "kind": resolved.kind,
            "url": resolved.canonical_url or normalized.url,
            "name": name or resolved.title or "",
        },
    )
    return source


def list_sources(workspace, *, include_inactive: bool = False) -> list[Source]:
    """Active sources for the workspace, ordered by name.

    Soft-deleted rows are never returned: a removed source keeps its history
    for the ledger, but it is not a working source (docs/03 §12).
    """
    queryset = Source.objects.filter(workspace=workspace, deleted_at__isnull=True)
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return list(queryset.order_by("name", "id"))


def scan(source: Source, *, since=None) -> ScanOutcome:
    """One flat, metadata-only pass over a source; upserts the catalog.

    `since` bounds the enumeration to videos published after it — the
    monitor cadence passes the last successful scan. A full pass (`since=None`)
    also reconciles: previously-seen videos that no longer appear are marked
    unavailable, because that is how a deleted video is detected without ever
    deleting the row (docs/03 §5).

    Deliberately **not** wrapped in one transaction: when a scan fails, the
    error status must survive. A single outer `atomic` block would roll the
    `SCAN_ERROR` write back together with the exception, and the operator
    would see a source that looks untouched by a scan that did run. Per-item
    writes commit as they go, which is also the resilient behaviour (F-48): a
    scan interrupted half-way leaves the rows it managed to write.
    """
    source_id = source.pk
    provider = get_source_provider()
    reference = SourceRef(
        source_id=source_id,
        kind=source.kind,
        external_id=source.external_id,
        url=source.url,
    )
    discovered = created = updated = 0
    seen_ids: set[str] = set()

    source.scan_status = Source.SCAN_SCANNING
    source.last_scan_error = ""
    source.save(update_fields=["scan_status", "last_scan_error"])

    try:
        for item in provider.scan(reference, since):
            discovered += 1
            seen_ids.add(item.video_id)
            # `last_seen_at` (auto) is the scan's real work: it is how a
            # vanished video is recognised on the next pass.
            if _upsert(source, item):
                created += 1
            else:
                updated += 1
    except (SourceUnresolvable, ItemGone) as exc:
        source.scan_status = Source.SCAN_ERROR
        source.last_scan_error = str(exc)
        source.save(update_fields=["scan_status", "last_scan_error"])
        raise

    marked = _mark_vanished(source, seen_ids) if since is None else 0

    source.scan_status = Source.SCAN_OK
    source.last_scan_at = now_utc()
    source.video_count = CatalogVideo.objects.filter(source=source).count()
    source.save(update_fields=["scan_status", "last_scan_at", "video_count"])
    return ScanOutcome(
        source_id=source_id,
        discovered=discovered,
        created=created,
        updated=updated,
        marked_unavailable=marked,
        skipped=0,
    )


def hydrate(batch) -> HydrateOutcome:
    """Fill the expensive fields for a batch of catalog rows.

    Lazy by design: a row with `hydrated_at` set is skipped, so the same
    batch may be retried safely after a partial failure. An item the platform
    no longer serves is marked unavailable and counted, not raised — one dead
    video must not fail the whole batch (F-48).
    """
    rows = list(batch)
    provider = get_source_provider()
    hydrated = unavailable = skipped = 0

    for video in rows:
        if video.hydrated_at is not None:
            skipped += 1
            continue
        try:
            detail = provider.hydrate(
                VideoRef(source_id=video.source_id, video_id=video.video_id)
            )
        except ItemGone:
            # Gone upstream: record the fact, keep the row and its history.
            video.availability = "unavailable"
            video.save(update_fields=["availability", "updated_at"])
            unavailable += 1
            continue
        video.description = detail.description
        video.tags = list(detail.tags)  # docs/03 §2.1: text[] → jsonb
        video.view_count = detail.view_count
        video.like_count = detail.like_count
        video.category = detail.category_id
        video.hydrated_at = detail.hydrated_at
        video.availability = "available"
        video.save(
            update_fields=[
                "description",
                "tags",
                "view_count",
                "like_count",
                "category",
                "hydrated_at",
                "availability",
                "updated_at",
            ]
        )
        hydrated += 1

    return HydrateOutcome(
        requested=len(rows),
        hydrated=hydrated,
        unavailable=unavailable,
        skipped=skipped,
    )



def _upsert(source: Source, item) -> bool:
    """Insert or refresh one catalog row. True when the row was created.

    Uniqueness is `(source, video_id)`, not per workspace: the same video may
    legitimately appear in a channel and in a curated playlist, and it is
    catalogued twice and delivered once (INV-9).
    """
    existing = CatalogVideo.objects.filter(
        source=source, video_id=item.video_id
    ).first()
    fields = {
        "title": item.title,
        "duration_sec": item.duration_sec,
        "published_at": item.published_at,
        "thumbnail_url": item.thumbnail_url or "",
        "live_status": item.live_status,
        "availability": _map_availability(item.availability),
        "updated_at": timezone.now(),
    }
    if existing is None:
        CatalogVideo.objects.create(
            workspace=source.workspace,
            source=source,
            video_id=item.video_id,
            **fields,
        )
        return True
    # Never clobber operator judgement: `starred`/`ignored` are theirs, and
    # are deliberately absent from `fields`.
    for column, value in fields.items():
        setattr(existing, column, value)
    existing.save(update_fields=list(fields))
    return False


def _map_availability(raw: str) -> str:
    """Port availability -> catalog vocabulary (docs/03 §5).

    The port speaks the platform's words (`public`/`unlisted`/`private`); the
    catalog speaks ours (`available`/`unavailable`/`private`/`unknown`). Both a
    public and an unlisted video are deliverable, so both are `available`.
    """
    if raw in ("public", "unlisted"):
        return "available"
    if raw in ("private", "premium_only"):
        return "private"
    if raw in ("none", "unavailable"):
        return "unavailable"
    return "unknown"


def _mark_vanished(source: Source, seen_ids: set[str]) -> int:
    """Mark rows absent from a full scan as unavailable, never deleting them.

    Only rows currently believed available are touched, so repeated full
    scans do not keep re-counting the same rows.
    """
    return (
        CatalogVideo.objects.filter(source=source, availability="available")
        .exclude(video_id__in=seen_ids)
        .update(availability="unavailable", updated_at=timezone.now())
    )
