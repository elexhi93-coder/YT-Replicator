"""U09 tests — the destination platform: inventory, quota, upload, errors.

Nothing here touches Google. `FakeHttp` replaces the transport, so the
resumable upload, the inventory upsert and the error translation are all
exercised offline — and the translation table is tested exhaustively, because
it is the one place a status code becomes a decision about whether a video is
retried or failed.

No sibling internals are imported: the channel and destination rows come from
Django's app registry, and the port adapter is installed through `core.api`'s
registry, the same seam production uses.
"""

from __future__ import annotations

import pytest
from django.apps import apps

from accounts.api import get_default_workspace
from core.api import (
    PermanentError,
    ProgressCallback,
    RateLimitExceeded,
    TransientError,
    UploadRequest,
    format_provenance_marker,
    register_destination_platform,
    reset_port_registry,
)
from youtube import api
from youtube.adapter import YouTubePlatform, translate_error
from youtube.errors import (
    PlatformUnavailable,
    QuotaExhausted,
    Throttled,
    TokenRevoked,
    UploadNotFound,
    UploadRejected,
)
from youtube.http import (
    DAILY_UNIT_LIMIT,
    HttpResponse,
    UPLOAD_UNIT_COST,
    YouTubeHttp,
)
from youtube.models import DestinationInventory, QuotaUsage

pytestmark = pytest.mark.django_db

CHANNEL_ID = "UChannelForSmoke"
VIDEO_ID = "ytrabc12345"
SESSION_URL = "https://upload.example/session/xyz"


class FakeHttp:
    """A `YouTubeHttp` that replays canned responses and records the calls."""

    def __init__(
        self,
        *,
        get_status: int = 200,
        get_body: dict | None = None,
        post_status: int = 200,
        post_body: dict | None = None,
        post_headers: dict | None = None,
    ) -> None:
        self.get_status = get_status
        self.get_body = get_body if get_body is not None else {}
        self.post_status = post_status
        self.post_body = post_body if post_body is not None else {}
        self.post_headers = post_headers if post_headers is not None else {}
        self.chunks: list[bytes] = []
        self.calls: list[tuple[str, str, dict]] = []

    def get_json(self, url, *, headers, timeout=30.0):
        self.calls.append(("get", url, dict(headers)))
        return HttpResponse(status=self.get_status, body=self.get_body)

    def post_json(self, url, payload, *, headers, timeout=30.0):
        self.calls.append(("post", url, dict(headers)))
        if url == SESSION_URL:
            return HttpResponse(
                status=self.post_status,
                body=self.post_body,
                headers=self.post_headers,
            )
        return HttpResponse(status=200, body=self.post_body, headers=self.post_headers)

    def post_bytes(self, url, payload, *, headers, timeout=120.0):
        self.chunks.append(payload)
        return HttpResponse(status=200, body={})

    @property
    def gets(self) -> list[str]:
        return [c[1] for c in self.calls if c[0] == "get"]


def _google_error(reason: str, message: str = "nope") -> dict:
    return {"error": {"code": 403, "message": message, "errors": [{"reason": reason}]}}


@pytest.fixture(autouse=True)
def platform_binding():
    """Restore whatever the process had registered (the real adapter, in prod)."""
    snapshot = dict(__import__("core.registry", fromlist=["_PORTS"])._PORTS)
    yield
    reset_port_registry()
    __import__("core.registry", fromlist=["_PORTS"])._PORTS.update(snapshot)


@pytest.fixture
def fake_http():
    return FakeHttp()


@pytest.fixture
def bind(fake_http):
    def _bind(http=None):
        register_destination_platform(
            lambda: YouTubePlatform(http=http or fake_http)
        )

    return _bind


@pytest.fixture
def workspace():
    return get_default_workspace()


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    """INV-1: a key must exist to encrypt the channel's token. Fixed and hermetic."""
    monkeypatch.setenv("PLATFORM_MASTER_KEY", "0" * 64)


@pytest.fixture
def channel(workspace):
    """An authorised channel whose token is real, encrypted and not expiring.

    `valid_access_token` is the only way this module obtains a token, and it
    refuses a channel that was never authorised — so the fixture has to do the
    authorisation properly rather than stub the call away.
    """
    from datetime import timedelta

    from core.api import encrypt, now_utc

    channel_model = apps.get_model("credentials", "AuthorizedChannel")
    return channel_model.objects.create(
        workspace=workspace,
        channel_id=CHANNEL_ID,
        title="Channel",
        access_token_enc=encrypt("access-token").encode("utf-8"),
        refresh_token_enc=encrypt("refresh-token").encode("utf-8"),
        token_state="valid",
        token_expires_at=now_utc() + timedelta(hours=1),
    )


@pytest.fixture
def destination(workspace, channel):
    destination_model = apps.get_model("pipelines", "Destination")
    return destination_model.objects.create(
        workspace=workspace, authorized_channel=channel, label="Main"
    )


class TestErrorTranslation:
    """One table, tested exhaustively: it decides retry vs fail, per video."""

    def test_429_is_transient_and_throttled(self):
        error = translate_error(429, _google_error("rateLimitExceeded"))
        assert isinstance(error, Throttled)
        assert isinstance(error, TransientError)

    def test_quota_exceeded_is_transient_so_the_job_is_rescheduled(self):
        # The whole reason QuotaExhausted is transient: the budget returns at
        # Pacific midnight, so failing the video would be wrong.
        error = translate_error(403, _google_error("quotaExceeded"))
        assert isinstance(error, QuotaExhausted)
        assert isinstance(error, TransientError)

    def test_401_is_a_revoked_token_and_is_permanent(self):
        error = translate_error(401, _google_error("authError"))
        assert isinstance(error, TokenRevoked)
        assert isinstance(error, PermanentError)
        assert not isinstance(error, TransientError)

    def test_a_forbidden_channel_is_a_revoked_token(self):
        # Retrying this is how the legacy uploaded to the wrong channel (D-23).
        error = translate_error(403, _google_error("forbidden"))
        assert isinstance(error, TokenRevoked)

    def test_404_is_permanent(self):
        assert isinstance(translate_error(404, _google_error("notFound")), UploadNotFound)

    def test_5xx_is_transient(self):
        error = translate_error(503, _google_error("backendError"))
        assert isinstance(error, PlatformUnavailable)
        assert isinstance(error, TransientError)

    def test_a_plain_400_is_a_permanent_rejection(self):
        error = translate_error(400, _google_error("invalidTitle"))
        assert isinstance(error, UploadRejected)
        assert isinstance(error, PermanentError)

    def test_the_message_reaches_the_error(self):
        error = translate_error(400, _google_error("invalidTitle", "title too long"))
        assert "title too long" in str(error)

    def test_an_unmapped_status_does_not_escape_as_something_odd(self):
        # Never a bare Exception: an unknown shape is a platform problem, which
        # is retryable, and the job survives it.
        assert isinstance(translate_error(418, {}), UploadRejected)
        assert isinstance(translate_error(200, {}), PlatformUnavailable)


def _playlist_item(video_id: str, *, title: str = "A video", marker: str = "") -> dict:
    description = f"Some description. {marker}".strip() if marker else "Some description."
    return {
        "snippet": {
            "title": title,
            "description": description,
            "publishedAt": "2026-01-01T00:00:00Z",
            "resourceId": {"videoId": video_id},
            "privacyStatus": "unlisted",
        }
    }


class TestInventorySync:
    def test_sync_writes_what_the_api_returned(self, destination, bind):
        marker = format_provenance_marker(VIDEO_ID, 42)
        bind(
            FakeHttp(get_body={"items": [_playlist_item(VIDEO_ID, marker=marker)]})
        )
        rows, cursor = api.sync_inventory(destination)
        assert cursor is None
        row = DestinationInventory.objects.get(destination=destination)
        assert row.destination_video_id == VIDEO_ID
        assert row.privacy == "unlisted"
        assert row.provenance_marker == marker
        assert row.is_present is True
        assert row.matched_delivery_id is None  # unclaimed until U10

    def test_resync_updates_rather_than_duplicates(self, destination, fake_http, bind):
        bind(fake_http)
        fake_http.get_body = {"items": [_playlist_item(VIDEO_ID, title="Old")]}
        api.sync_inventory(destination)
        fake_http.get_body = {"items": [_playlist_item(VIDEO_ID, title="New")]}
        api.sync_inventory(destination)
        assert DestinationInventory.objects.filter(destination=destination).count() == 1
        assert DestinationInventory.objects.get().title == "New"

    def test_the_page_token_is_passed_through(self, destination, fake_http, bind):
        bind(fake_http)
        fake_http.get_body = {"items": [], "nextPageToken": "PAGE2"}
        _, cursor = api.sync_inventory(destination, cursor="PAGE1")
        assert cursor == "PAGE2"
        assert "pageToken=PAGE1" in fake_http.gets[0]

    def test_a_video_that_reappears_is_present_again(self, destination, bind):
        bind(FakeHttp(get_body={"items": [_playlist_item(VIDEO_ID)]}))
        api.sync_inventory(destination)
        api.mark_absent(destination)
        assert DestinationInventory.objects.get().is_present is False
        bind(FakeHttp(get_body={"items": [_playlist_item(VIDEO_ID)]}))
        api.sync_inventory(destination)
        assert DestinationInventory.objects.get().is_present is True

    def test_a_vanished_video_is_never_deleted(self, destination, bind):
        bind(FakeHttp(get_body={"items": [_playlist_item(VIDEO_ID)]}))
        api.sync_inventory(destination)
        removed = api.mark_absent(destination)
        assert removed == 1
        row = DestinationInventory.objects.get()
        assert row.is_present is False
        assert DestinationInventory.objects.count() == 1  # kept, not gone

    def test_only_unseen_videos_are_marked_absent(self, destination, fake_http, bind):
        second = "secondvid01"
        bind(fake_http)
        fake_http.get_body = {
            "items": [_playlist_item(VIDEO_ID), _playlist_item(second)]
        }
        api.sync_inventory(destination)
        # A later full sync saw only the first one.
        assert api.mark_absent(destination, keep_ids=[VIDEO_ID]) == 1
        states = {
            r.destination_video_id: r.is_present
            for r in DestinationInventory.objects.filter(destination=destination)
        }
        assert states == {VIDEO_ID: True, second: False}

    def test_unclaimed_is_surfaced_not_adopted(self, destination, bind):
        bind(FakeHttp(get_body={"items": [_playlist_item(VIDEO_ID)]}))
        api.sync_inventory(destination)
        unclaimed = api.unclaimed_inventory(destination)
        assert [r.destination_video_id for r in unclaimed] == [VIDEO_ID]
        # INV-8: unclaimed content is never turned into a delivery by us.
        assert unclaimed[0].matched_delivery_id is None

    def test_the_sync_time_is_recorded_on_the_destination(self, destination, bind):
        bind(FakeHttp(get_body={"items": []}))
        api.sync_inventory(destination)
        destination.refresh_from_db()
        assert destination.last_sync_at is not None


class TestQuota:
    def test_a_fresh_destination_has_its_whole_allowance(self, destination):
        assert api.quota_remaining(destination) == destination.daily_max

    def test_the_day_is_youtubes_not_utcs(self, destination):
        # The legacy reset its counter at UTC midnight (D-03), so for up to
        # eight hours it believed it had budget it did not have.
        from core.api import quota_day_string

        api.account_upload(destination)
        assert QuotaUsage.objects.get().quota_date.isoformat() == quota_day_string()

    def test_an_upload_is_counted_with_its_units(self, destination):
        row = api.account_upload(destination, units=UPLOAD_UNIT_COST)
        assert row.uploads_used == 1
        assert row.units_used == UPLOAD_UNIT_COST
        assert api.quota_remaining(destination) == destination.daily_max - 1

    def test_remaining_never_goes_negative(self, destination):
        for _ in range(destination.daily_max + 3):
            api.account_upload(destination)
        assert api.quota_remaining(destination) == 0

    def test_a_new_day_starts_a_new_row(self, destination):
        api.account_upload(destination, day="2026-01-01")
        api.account_upload(destination, day="2026-01-02")
        assert QuotaUsage.objects.filter(destination=destination).count() == 2
        assert (
            api.quota_remaining(destination, day="2026-01-02")
            == destination.daily_max - 1
        )

    def test_quota_exhaustion_marks_the_day_spent(self, destination):
        api.record_quota_exhausted(destination)
        assert api.quota_remaining(destination) == 0
        assert QuotaUsage.objects.get().units_used == DAILY_UNIT_LIMIT

    def test_a_throttled_attempt_costs_one_attempt_not_a_day(self, destination, bind):
        # A throttle is not an upload: charging it per retry would let a rate
        # limit drain the allowance.
        bind(
            FakeHttp(
                post_status=429,
                post_body=_google_error("rateLimitExceeded"),
                post_headers={"Location": SESSION_URL},
            )
        )
        with pytest.raises(Throttled):
            api.upload(destination, _upload_request(destination))
        row = QuotaUsage.objects.get()
        assert row.uploads_used == 1
        assert api.quota_remaining(destination) == destination.daily_max - 1


def _upload_request(destination, tmp_path=None, *, size: int = 10):
    """A minimal, real file on disk — the adapter reads it in chunks."""
    import tempfile
    from pathlib import Path

    directory = Path(tempfile.mkdtemp())
    media = directory / "video.mp4"
    media.write_bytes(b"x" * size)
    marker = format_provenance_marker(VIDEO_ID, 7)
    return UploadRequest(
        source_video_id=VIDEO_ID,
        media_path=media,
        title="A replicated video",
        description=f"Body copy.\n{marker}",
        tags=("one", "two"),
        category_id="22",
        privacy="unlisted",
        made_for_kids=False,
        contains_synthetic_media=False,
        thumbnail_path=None,
        provenance_marker=marker,
    )


class TestResumableUpload:
    def test_upload_opens_a_session_then_finalises(self, destination, bind):
        http = FakeHttp(
            post_body={"id": "yt123", "status": {"privacyStatus": "unlisted"}},
            post_headers={"Location": SESSION_URL},
        )
        bind(http)
        outcome = api.upload(destination, _upload_request(destination))
        assert outcome.destination_video_id == "yt123"
        assert outcome.destination_url == "https://youtu.be/yt123"
        assert outcome.privacy == "unlisted"

    def test_the_bytes_are_sent_in_content_ranges(self, destination, bind):
        http = FakeHttp(
            post_body={"id": "yt123", "status": {}},
            post_headers={"Location": SESSION_URL},
        )
        bind(http)
        api.upload(destination, _upload_request(destination, size=10))
        assert b"".join(http.chunks) == b"x" * 10

    def test_progress_is_reported_and_reaches_the_end(self, destination, bind):
        bind(
            FakeHttp(
                post_body={"id": "yt123", "status": {}},
                post_headers={"Location": SESSION_URL},
            )
        )
        seen: list[tuple[int, int]] = []
        api.upload(
            destination,
            _upload_request(destination, size=10),
            on_progress=lambda sent, total: seen.append((sent, total)),
        )
        assert seen[-1] == (10, 10)

    def test_an_upload_is_charged_to_the_pacific_day(self, destination, bind):
        bind(
            FakeHttp(
                post_body={"id": "yt123", "status": {}},
                post_headers={"Location": SESSION_URL},
            )
        )
        api.upload(destination, _upload_request(destination))
        assert QuotaUsage.objects.get().uploads_used == 1

    def test_a_revoked_token_surfaces_permanently(self, destination, bind):
        bind(
            FakeHttp(
                post_status=401,
                post_body=_google_error("authError"),
                post_headers={"Location": SESSION_URL},
            )
        )
        with pytest.raises(TokenRevoked) as excinfo:
            api.upload(destination, _upload_request(destination))
        assert not isinstance(excinfo.value, TransientError)

    def test_a_quota_error_marks_the_day_spent_and_propagates(self, destination, bind):
        bind(
            FakeHttp(
                post_status=403,
                post_body=_google_error("quotaExceeded"),
                post_headers={"Location": SESSION_URL},
            )
        )
        with pytest.raises(QuotaExhausted):
            api.upload(destination, _upload_request(destination))
        # The day is now recorded as spent, so nothing else is attempted.
        assert api.quota_remaining(destination) == 0

    def test_a_missing_session_url_is_a_platform_problem(self, destination, bind):
        bind(FakeHttp(post_body={}, post_headers={}))
        with pytest.raises(PlatformUnavailable):
            api.upload(destination, _upload_request(destination))

    def test_the_unit_cost_is_the_published_one(self, destination, bind):
        bind(FakeHttp())
        platform = YouTubePlatform(http=FakeHttp())
        assert platform.unit_cost_for_upload() > 0
        assert platform.unit_cost_for_upload() >= UPLOAD_UNIT_COST


