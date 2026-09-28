"""U07 tests — sources & catalog: URL guards, add, flat scan, lazy hydrate.

No test touches the network and none shells out to yt-dlp: `FakeProvider`
replaces the port binding through the registry, which is the same seam
`worker`/`media` will use. What is asserted here is the module's own
behaviour — the guards, the upsert, the never-delete rule, and the fact that
errors come out typed and classified (INV-7, INV-9, F-48).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from accounts.api import get_default_workspace
from core.api import (
    PermanentError,
    RateLimitExceeded,
    ResolvedSource,
    SourceItem,
    SourceItemDetail,
    TransientError,
    VideoRef,
    register_source_provider,
    reset_port_registry,
)
from sources import api
from sources.errors import (
    HydrationRateLimited,
    ItemGone,
    ProviderUnavailable,
    SourceUrlInvalid,
    SourceUnresolvable,
)
from sources.models import CatalogVideo, Source
from sources.urls import normalize_source_url

pytestmark = pytest.mark.django_db

CHANNEL_URL = "https://www.youtube.com/@SomeChannel"
CHANNEL_ID = "UC" + "a" * 22
VIDEO_ID = "dQw4w9WgXcQ"


def _item(video_id: str = VIDEO_ID, **overrides) -> SourceItem:
    """A flat scan row, overridable per test."""
    base = dict(
        video_id=video_id,
        title="A video",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_sec=120,
        thumbnail_url="https://i.ytimg.com/x.jpg",
        live_status="not_live",
        availability="public",
    )
    base.update(overrides)
    return SourceItem(**base)


class FakeProvider:
    """A SourceProvider that answers from memory instead of from YouTube."""

    def __init__(
        self,
        *,
        resolved: ResolvedSource | None = None,
        items: list[SourceItem] | None = None,
        details: dict[str, SourceItemDetail] | None = None,
        resolve_error: Exception | None = None,
        scan_error: Exception | None = None,
        gone: tuple[str, ...] = (),
        hydrate_error: Exception | None = None,
    ) -> None:
        self._resolved = resolved or ResolvedSource(
            kind="channel",
            external_id=CHANNEL_ID,
            canonical_url="https://www.youtube.com/@SomeChannel/videos",
            title="Some Channel",
        )
        self._items = items or []
        self._details = details or {}
        self._resolve_error = resolve_error
        self._scan_error = scan_error
        # Per-video absence (F-48: one dead video must not fail the batch), as
        # opposed to `hydrate_error`, which fails every item in the batch.
        self._gone = tuple(gone)
        self._hydrate_error = hydrate_error
        self.scan_calls: list[tuple[object, object]] = []
        self.hydrate_calls: list[VideoRef] = []

    def resolve(self, raw_url: str) -> ResolvedSource:
        if self._resolve_error:
            raise self._resolve_error
        return self._resolved

    def scan(self, source, since):
        self.scan_calls.append((source, since))
        if self._scan_error:
            raise self._scan_error
        return iter(self._items)

    def hydrate(self, item: VideoRef) -> SourceItemDetail:
        self.hydrate_calls.append(item)
        if item.video_id in self._gone:
            raise ItemGone(f"{item.video_id} was deleted")
        if self._hydrate_error:
            raise self._hydrate_error
        return self._details[item.video_id]

    def materialize(self, request):  # pragma: no cover - not this unit
        raise NotImplementedError


@pytest.fixture(autouse=True)
def fake_provider():
    """Install a FakeProvider, then restore the process wiring."""
    snapshot = dict(__import__("core.registry", fromlist=["_PORTS"])._PORTS)
    provider = FakeProvider()
    register_source_provider(lambda: provider)
    yield provider
    reset_port_registry()
    __import__("core.registry", fromlist=["_PORTS"])._PORTS.update(snapshot)


@pytest.fixture
def workspace():
    return get_default_workspace()


class TestUrlGuards:
    """INV-7: the guard runs before any request, so a bad host costs nothing."""

    def test_channel_url_is_accepted_and_gets_a_videos_tab(self):
        result = normalize_source_url(CHANNEL_URL)
        assert result.kind == "channel"
        assert result.url.endswith("/videos")

    def test_playlist_list_parameter_is_recognised(self):
        result = normalize_source_url("https://www.youtube.com/playlist?list=PLabc")
        assert (result.kind, result.external_id) == ("playlist", "PLabc")

    def test_bare_handle_becomes_a_channel_url(self):
        result = normalize_source_url("@handle")
        assert result.kind == "channel"
        assert result.url == "https://www.youtube.com/@handle/videos"

    def test_non_youtube_host_is_refused(self):
        with pytest.raises(SourceUrlInvalid):
            normalize_source_url("https://evil.example.com/@x")

    def test_plain_http_is_refused(self):
        with pytest.raises(SourceUrlInvalid):
            normalize_source_url("http://www.youtube.com/@x")

    def test_single_video_is_not_a_source(self):
        with pytest.raises(SourceUrlInvalid):
            normalize_source_url(f"https://www.youtube.com/watch?v={VIDEO_ID}")

    def test_blank_input_is_refused(self):
        with pytest.raises(SourceUrlInvalid):
            normalize_source_url("   ")

    def test_guards_are_permanent_errors(self):
        # Permanent, not transient: retrying a rejected URL can never help.
        assert issubclass(SourceUrlInvalid, PermanentError)


class TestAddSource:
    def test_add_creates_a_scoped_row(self, workspace):
        source = api.add_source(workspace, CHANNEL_URL, name="Mine")
        assert source.kind == "channel"
        assert source.external_id == CHANNEL_ID
        assert source.workspace_id == workspace.pk
        assert source.scan_status == Source.SCAN_NEVER

    def test_add_is_idempotent_per_workspace(self, workspace):
        first = api.add_source(workspace, CHANNEL_URL)
        second = api.add_source(workspace, CHANNEL_URL)
        assert first.pk == second.pk
        assert Source.objects.filter(workspace=workspace).count() == 1

    def test_rejected_url_never_reaches_the_provider(self, workspace, fake_provider):
        with pytest.raises(SourceUrlInvalid):
            api.add_source(workspace, "https://evil.example.com/@x")

    def test_list_sources_is_ordered_and_hides_soft_deleted(self, workspace, fake_provider):
        api.add_source(workspace, CHANNEL_URL, name="Alpha")
        # A second, *distinct* channel: the fake resolves one id per provider,
        # so without re-pointing it `add_source` would (correctly) deduplicate.
        fake_provider._resolved = ResolvedSource(
            kind="channel",
            external_id="UC" + "b" * 22,
            canonical_url="https://www.youtube.com/@Beta/videos",
            title="Beta",
        )
        source = api.add_source(workspace, "https://www.youtube.com/@Beta", name="Beta")
        source.deleted_at = datetime.now(timezone.utc)
        source.save(update_fields=["deleted_at"])
        assert [s.name for s in api.list_sources(workspace)] == ["Alpha"]


class TestScan:
    def test_scan_creates_catalog_rows_and_counts_them(self, workspace, fake_provider):
        fake_provider._items = [_item(), _item("other11chars")]
        source = api.add_source(workspace, CHANNEL_URL)
        outcome = api.scan(source)
        assert (outcome.discovered, outcome.created) == (2, 2)
        assert outcome.updated == 0
        assert CatalogVideo.objects.filter(source=source).count() == 2

    def test_rescanning_updates_instead_of_duplicating(self, workspace, fake_provider):
        fake_provider._items = [_item()]
        source = api.add_source(workspace, CHANNEL_URL)
        api.scan(source)
        fake_provider._items = [_item(title="Renamed")]
        outcome = api.scan(source)
        assert (outcome.created, outcome.updated) == (0, 1)
        assert CatalogVideo.objects.get(source=source, video_id=VIDEO_ID).title == "Renamed"

    def test_scan_records_status_and_counters(self, workspace, fake_provider):
        fake_provider._items = [_item()]
        source = api.add_source(workspace, CHANNEL_URL)
        api.scan(source)
        source.refresh_from_db()
        assert source.scan_status == Source.SCAN_OK
        assert source.last_scan_at is not None
        assert source.video_count == 1

    def test_vanished_video_is_marked_never_deleted(self, workspace, fake_provider):
        fake_provider._items = [_item(), _item("other11chars")]
        source = api.add_source(workspace, CHANNEL_URL)
        api.scan(source)
        fake_provider._items = [_item()]  # the other one is gone upstream
        outcome = api.scan(source)
        assert outcome.marked_unavailable == 1
        gone = CatalogVideo.objects.get(source=source, video_id="other11chars")
        assert gone.availability == "unavailable"
        assert CatalogVideo.objects.filter(source=source).count() == 2  # kept, not deleted

    def test_bounded_scan_marks_nothing_vanished(self, workspace, fake_provider):
        fake_provider._items = [_item()]
        source = api.add_source(workspace, CHANNEL_URL)
        api.scan(source)
        fake_provider._items = []
        outcome = api.scan(source, since=datetime(2026, 6, 1, tzinfo=timezone.utc))
        assert outcome.marked_unavailable == 0
        assert CatalogVideo.objects.get(source=source).availability == "available"

    def test_operator_flags_survive_a_rescan(self, workspace, fake_provider):
        fake_provider._items = [_item()]
        source = api.add_source(workspace, CHANNEL_URL)
        api.scan(source)
        CatalogVideo.objects.filter(source=source).update(starred=True, ignored=True)
        api.scan(source)
        row = CatalogVideo.objects.get(source=source, video_id=VIDEO_ID)
        assert row.starred and row.ignored  # the operator's call, never ours to reset

    def test_availability_is_translated_to_our_vocabulary(self, workspace, fake_provider):
        fake_provider._items = [
            _item("a" * 11, availability="unlisted"),
            _item("b" * 11, availability="private"),
        ]
        source = api.add_source(workspace, CHANNEL_URL)
        api.scan(source)
        rows = {r.video_id: r.availability for r in CatalogVideo.objects.filter(source=source)}
        assert rows["a" * 11] == "available"  # unlisted is still deliverable
        assert rows["b" * 11] == "private"

    def test_failed_scan_records_the_error_and_raises_typed(self, workspace, fake_provider):
        fake_provider._scan_error = SourceUnresolvable("channel is gone")
        source = api.add_source(workspace, CHANNEL_URL)
        with pytest.raises(SourceUnresolvable):
            api.scan(source)
        source.refresh_from_db()
        assert source.scan_status == Source.SCAN_ERROR
        assert "channel is gone" in source.last_scan_error

    def test_full_scan_passes_since_none_to_the_provider(self, workspace, fake_provider):
        fake_provider._items = [_item()]
        source = api.add_source(workspace, CHANNEL_URL)
        api.scan(source)
        assert fake_provider.scan_calls[0][1] is None


class TestHydrate:
    def _catalog(self, workspace, fake_provider, *ids):
        fake_provider._items = [_item(v) for v in ids]
        source = api.add_source(workspace, CHANNEL_URL)
        api.scan(source)
        return list(CatalogVideo.objects.filter(source=source).order_by("video_id"))

    def test_hydrate_fills_the_expensive_fields(self, workspace, fake_provider):
        video_id = "a" * 11
        rows = self._catalog(workspace, fake_provider, video_id)
        fake_provider._details[video_id] = SourceItemDetail(
            video_id=video_id,
            description="Full description",
            tags=("one", "two"),
            category_id="10",
            view_count=1234,
            like_count=56,
            hydrated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        outcome = api.hydrate(rows)
        assert (outcome.requested, outcome.hydrated) == (1, 1)
        row = CatalogVideo.objects.get(pk=rows[0].pk)
        assert row.description == "Full description"
        assert row.tags == ["one", "two"]  # text[] → jsonb (docs/03 §2.1)
        assert row.view_count == 1234
        assert row.hydrated_at is not None

    def test_hydrate_is_lazy_on_a_repeat_batch(self, workspace, fake_provider):
        video_id = "a" * 11
        rows = self._catalog(workspace, fake_provider, video_id)
        fake_provider._details[video_id] = SourceItemDetail(
            video_id=video_id,
            description=None,
            tags=(),
            category_id=None,
            view_count=None,
            like_count=None,
            hydrated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        api.hydrate(rows)
        assert len(fake_provider.hydrate_calls) == 1
        # Same batch again: already hydrated, so the provider is not called.
        outcome = api.hydrate(list(CatalogVideo.objects.filter(pk=rows[0].pk)))
        assert (outcome.hydrated, outcome.skipped) == (0, 1)
        assert len(fake_provider.hydrate_calls) == 1

    def test_gone_item_is_counted_not_raised(self, workspace, fake_provider):
        first, second = "a" * 11, "b" * 11
        rows = self._catalog(workspace, fake_provider, first, second)
        fake_provider._gone = (second,)  # the second video is gone upstream
        fake_provider._details[first] = SourceItemDetail(
            video_id=first,
            description="d",
            tags=(),
            category_id=None,
            view_count=None,
            like_count=None,
            hydrated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        outcome = api.hydrate(rows)
        assert (outcome.hydrated, outcome.unavailable) == (1, 1)
        gone = CatalogVideo.objects.get(source=rows[0].source, video_id=second)
        assert gone.availability == "unavailable"
        assert CatalogVideo.objects.filter(source=rows[0].source).count() == 2

    def test_batch_wide_hydrate_failure_propagates_typed(self, workspace, fake_provider):
        rows = self._catalog(workspace, fake_provider, "a" * 11)
        fake_provider._hydrate_error = HydrationRateLimited("429")
        with pytest.raises(HydrationRateLimited):
            api.hydrate(rows)


class TestErrorClassification:
    """`isinstance(err, TransientError)` is the retry test the worker uses."""

    def test_throttle_is_transient(self):
        assert issubclass(HydrationRateLimited, TransientError)
        assert issubclass(HydrationRateLimited, RateLimitExceeded)

    def test_missing_extractor_is_transient(self):
        assert issubclass(ProviderUnavailable, TransientError)

    def test_unresolvable_and_gone_are_permanent(self):
        assert issubclass(SourceUnresolvable, PermanentError)
        assert issubclass(ItemGone, PermanentError)

    def test_source_url_invalid_is_permanent(self):
        assert issubclass(SourceUrlInvalid, PermanentError)

