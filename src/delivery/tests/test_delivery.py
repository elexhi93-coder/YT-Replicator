"""U10 tests â€” the ledger: marker injection, attempt history, reconciliation.

The behaviour under test is the behaviour the legacy lacked. A pair is
delivered once, every try is recorded, a vanished video is flagged rather than
re-uploaded, and content we cannot account for is never silently adopted.

Nothing touches the network: the Port B adapter is installed through
`core.api`'s registry with a fake, and the channel/destination rows come from
Django's app registry.
"""

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from django.apps import apps

from accounts.api import get_default_workspace
from core.api import (
    TransientError,
    encrypt,
    format_provenance_marker,
    now_utc,
    register_destination_platform,
    reset_port_registry,
)
from delivery import api
from delivery.errors import (
    AlreadyDelivered,
    InvalidDeliverySetting,
    MediaMissing,
)
from delivery.models import Delivery, DeliveryAttempt
# Errors and the inventory model come through `youtube.api` â€” this module may
# not import a sibling's internals (INV-12), and the errors are part of the
# published surface because `delivery` must distinguish a throttle from a
# rejection to record the right attempt outcome.
from youtube.api import Throttled, UploadRejected
from youtube.api import inventory_rows

pytestmark = pytest.mark.django_db

CHANNEL_ID = "UChannelLedger"
SOURCE_VIDEO = "srcreplicate1"
DEST_VIDEO = "destVideo001"


class FakePlatform:
    """A Port B adapter that succeeds, or fails the way the test needs."""

    def __init__(self, *, error: Exception | None = None, video_id: str = DEST_VIDEO):
        self.error = error
        self.video_id = video_id
        self.requests = []

    def probe_auth(self, channel):  # pragma: no cover - not this unit
        raise NotImplementedError

    def sync_inventory(self, channel, cursor=None, *, token=None):  # pragma: no cover
        raise NotImplementedError

    def unit_cost_for_upload(self) -> int:
        return 1600

    def upload(self, request, *, token, on_progress=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        from core.api import UploadOutcome

        return UploadOutcome(
            destination_video_id=self.video_id,
            destination_url=f"https://youtu.be/{self.video_id}",
            privacy=request.privacy,
            units_used=1600,
            http_status=200,
            raw_error_code=None,
            thumbnail_uploaded=False,
        )


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setenv("PLATFORM_MASTER_KEY", "0" * 64)


@pytest.fixture
def registry_snapshot():
    snapshot = dict(__import__("core.registry", fromlist=["_PORTS"])._PORTS)
    yield
    reset_port_registry()
    __import__("core.registry", fromlist=["_PORTS"])._PORTS.update(snapshot)


@pytest.fixture
def platform(registry_snapshot):
    fake = FakePlatform()
    register_destination_platform(lambda: fake)
    return fake


@pytest.fixture
def workspace():
    return get_default_workspace()


@pytest.fixture
def destination(workspace):
    channel_model = apps.get_model("credentials", "AuthorizedChannel")
    channel = channel_model.objects.create(
        workspace=workspace,
        channel_id=CHANNEL_ID,
        title="Channel",
        access_token_enc=encrypt("token").encode("utf-8"),
        refresh_token_enc=encrypt("refresh").encode("utf-8"),
        token_state="valid",
        token_expires_at=now_utc() + timedelta(hours=1),
    )
    destination_model = apps.get_model("pipelines", "Destination")
    return destination_model.objects.create(
        workspace=workspace, authorized_channel=channel, label="Main"
    )


@pytest.fixture
def media():
    directory = Path(tempfile.mkdtemp())
    path = directory / "video.mp4"
    path.write_bytes(b"x" * 32)
    return path


def _deliver(destination, media, **overrides):
    payload = {
        "source_video_id": SOURCE_VIDEO,
        "media_path": media,
        "title": "A replicated video",
        "description": "Body copy.",
        "source_title": "Source title",
    }
    payload.update(overrides)
    return api.deliver(destination, **payload)


def _inventory_model():
    """The `youtube` inventory model, reached through the app registry.

    A test may not import a sibling's models any more than its module may, so
    the fixture creates rows through Django's registry â€” the same boundary the
    test is asserting.
    """
    return apps.get_model("youtube", "DestinationInventory")


def _inventory(destination, video_id: str, *, present: bool = True, **kwargs):
    return _inventory_model().objects.create(
        workspace=destination.workspace,
        destination=destination,
        destination_video_id=video_id,
        is_present=present,
        **kwargs,
    )


class TestDeliver:
    def test_delivery_records_the_current_truth(self, destination, media, platform):
        result = _deliver(destination, media)
        delivery = api.get_delivery(result.delivery_id)
        assert delivery.status == "uploaded"
        assert delivery.destination_video_id == DEST_VIDEO
        assert delivery.destination_url == f"https://youtu.be/{DEST_VIDEO}"
        assert delivery.uploaded_at is not None
        assert result.status == "uploaded"

    def test_the_marker_carries_the_delivery_id(self, destination, media, platform):
        result = _deliver(destination, media)
        delivery = api.get_delivery(result.delivery_id)
        # The marker is only writable because the row was created first.
        assert result.provenance_marker == format_provenance_marker(
            SOURCE_VIDEO, delivery.pk
        )
        assert delivery.provenance_marker == result.provenance_marker

    def test_the_marker_is_appended_not_substituted(self, destination, media, platform):
        _deliver(destination, media, description="Keep this body.")
        sent = platform.requests[0].description
        assert sent.startswith("Keep this body.")
        assert sent.rstrip().endswith(format_provenance_marker(SOURCE_VIDEO, 1))

    def test_the_source_title_is_snapshotted(self, destination, media, platform):
        _deliver(destination, media, source_title="What it was called then")
        assert Delivery.objects.get().source_title_snapshot == "What it was called then"

    def test_one_attempt_is_recorded_per_delivery(self, destination, media, platform):
        _deliver(destination, media)
        attempts = api.attempts_for(Delivery.objects.get())
        assert [a.attempt_no for a in attempts] == [1]
        assert attempts[0].status == "uploaded"
        assert attempts[0].destination_video_id == DEST_VIDEO

    def test_a_second_delivery_is_refused(self, destination, media, platform):
        _deliver(destination, media)
        with pytest.raises(AlreadyDelivered):
            _deliver(destination, media)
        # The legacy's answer to an uncertain upload was "upload it again".
        assert DeliveryAttempt.objects.count() == 1
        assert len(platform.requests) == 1

    def test_a_missing_media_file_is_refused_before_any_row(self, destination, platform):
        with pytest.raises(MediaMissing):
            _deliver(destination, Path("nope.mp4"))
        assert Delivery.objects.count() == 0

    def test_an_invalid_origin_is_refused(self, destination, media, platform):
        with pytest.raises(InvalidDeliverySetting):
            _deliver(destination, media, origin="vibes")

    def test_a_failed_attempt_is_recorded_then_raised(self, destination, media, platform):
        platform.error = Throttled("429")
        with pytest.raises(Throttled):
            _deliver(destination, media)
        delivery = Delivery.objects.get()
        assert delivery.status == "failed"
        assert "429" in delivery.error_message
        attempt = delivery.attempts.get()
        assert attempt.status == "failed"
        assert attempt.error_code == "throttled"

    def test_a_failure_leaves_the_pair_retryable(self, destination, media, platform):
        platform.error = UploadRejected("bad title")
        with pytest.raises(UploadRejected):
            _deliver(destination, media)
        platform.error = None
        result = _deliver(destination, media)  # not AlreadyDelivered
        assert result.attempt_no == 2
        assert [a.attempt_no for a in api.attempts_for(Delivery.objects.get())] == [1, 2]

    def test_the_superseded_id_survives_a_reupload(self, destination, media, platform):
        # The write-once rule of docs/03 section 8, told as a story: we upload,
        # the operator deletes the copy, we re-upload, and attempt 1 still holds
        # the id that no longer exists.
        result = _deliver(destination, media)
        api.mark_removed(api.get_delivery(result.delivery_id), "deleted on YouTube")
        platform.video_id = "secondVideo1"
        second = _deliver(destination, media)
        delivery = api.get_delivery(second.delivery_id)
        assert delivery.destination_video_id == "secondVideo1"
        historical = [a.destination_video_id for a in api.attempts_for(delivery)]
        assert historical == [DEST_VIDEO, "secondVideo1"]

    def test_the_job_is_remembered_on_the_delivery(self, destination, media, platform):
        job_model = apps.get_model("jobs", "Job")
        pipeline_model = apps.get_model("pipelines", "Pipeline")
        pipeline = pipeline_model.objects.create(
            workspace=destination.workspace, name="P"
        )
        job = job_model.objects.create(
            workspace=destination.workspace,
            pipeline=pipeline,
            source_video_id=SOURCE_VIDEO,
        )
        result = _deliver(destination, media, job=job)
        assert api.get_delivery(result.delivery_id).last_job_id == job.pk

    def test_the_uploaded_video_is_claimed_in_the_inventory(
        self, destination, media, platform
    ):
        row = _inventory(destination, DEST_VIDEO)
        result = _deliver(destination, media)
        row.refresh_from_db()
        assert row.matched_delivery_id == result.delivery_id


class TestReconcile:
    def test_a_healthy_channel_reports_claimed_ok(self, destination, media, platform):
        # Inventory first: a sync creates the rows, delivery only claims them.
        _inventory(destination, DEST_VIDEO)
        _deliver(destination, media)
        report = api.reconcile(destination)
        assert report.claimed_ok == (DEST_VIDEO,)
        assert report.is_clean is True
        assert report.needs_review == 0

    def test_a_foreign_video_is_unclaimed_and_never_adopted(
        self, destination, media, platform
    ):
        _inventory(destination, DEST_VIDEO)
        _deliver(destination, media)
        _inventory(destination, "someoneElse1")
        report = api.reconcile(destination)
        assert report.unclaimed_present == ("someoneElse1",)
        # INV-8: surfaced, not adopted. No delivery row was invented for it.
        assert Delivery.objects.count() == 1
        assert (
            _inventory_model().objects.get(destination_video_id="someoneElse1")
            .matched_delivery_id
            is None
        )

    def test_a_deleted_copy_is_flagged_not_re_uploaded(
        self, destination, media, platform
    ):
        _inventory(destination, DEST_VIDEO)
        _deliver(destination, media)
        # The operator deleted it on YouTube; the next sync marks it absent.
        _inventory_model().objects.filter(destination=destination).update(
            is_present=False
        )
        report = api.reconcile(destination)
        assert report.missing_expected == (DEST_VIDEO,)
        # Nothing re-uploaded it: the ledger flagged, the operator decides.
        assert len(platform.requests) == 1

    def test_a_missing_inventory_row_also_counts_as_missing(
        self, destination, media, platform
    ):
        _deliver(destination, media)
        _inventory_model().objects.all().delete()
        assert api.reconcile(destination).missing_expected == (DEST_VIDEO,)

    def test_a_marker_with_no_ledger_row_is_a_mismatch(
        self, destination, media, platform
    ):
        _inventory(destination, DEST_VIDEO)
        _deliver(destination, media)
        _inventory(
            destination,
            "orphanVideo",
            provenance_marker=format_provenance_marker("orphanvid01", 9999),
        )
        report = api.reconcile(destination)
        assert report.marker_mismatch == ("orphanVideo",)
        assert Delivery.objects.count() == 1  # nothing adopted

    def test_inventory_match_is_a_real_foreign_key(self, destination, media, platform):
        # U09 shipped this column as a plain bigint and deferred the
        # constraint; U10 made it the foreign key docs/03 §8 always declared,
        # so a match to a delivery that does not exist is now impossible.
        field = _inventory_model()._meta.get_field("matched_delivery")
        assert field.is_relation
        assert field.remote_field.model.__name__ == "Delivery"

    def test_absent_rows_are_not_counted_as_present(self, destination, media, platform):
        _inventory(destination, DEST_VIDEO)
        _deliver(destination, media)
        _inventory_model().objects.filter(destination=destination).update(
            is_present=False
        )
        assert api.reconcile(destination).claimed_ok == ()

    def test_the_report_counts_what_needs_review(self, destination, media, platform):
        _inventory(destination, DEST_VIDEO)
        _deliver(destination, media)
        _inventory(destination, "someoneElse1")
        assert api.reconcile(destination).needs_review == 1


class TestMarkRemoved:
    def test_marking_removed_records_the_operator_reason(self, destination, media, platform):
        result = _deliver(destination, media)
        delivery = api.mark_removed(
            api.get_delivery(result.delivery_id), "operator deleted it for copyright"
        )
        assert delivery.status == "removed"
        assert "copyright" in delivery.error_message

    def test_a_removal_needs_a_reason(self, destination, media, platform):
        result = _deliver(destination, media)
        with pytest.raises(InvalidDeliverySetting):
            api.mark_removed(api.get_delivery(result.delivery_id), "")

    def test_only_an_uploaded_delivery_can_be_removed(self, destination, media, platform):
        delivery = Delivery.objects.create(
            workspace=destination.workspace,
            source_video_id="never",
            destination=destination,
            status="failed",
        )
        with pytest.raises(InvalidDeliverySetting):
            api.mark_removed(delivery, "because")

    def test_removal_does_not_delete_the_attempts(self, destination, media, platform):
        result = _deliver(destination, media)
        api.mark_removed(api.get_delivery(result.delivery_id), "gone")
        # INV-4: the history survives the verdict.
        assert DeliveryAttempt.objects.count() == 1


class TestMarkerParsing:
    def test_a_written_marker_reads_back(self):
        parsed = api.parse_marker(f"Body\n{format_provenance_marker('abc12345678', 7)}")
        assert parsed == ("abc12345678", 7)

    def test_text_without_a_marker_reads_as_none(self):
        assert api.parse_marker("just a description") is None
        assert api.parse_marker("") is None

    def test_a_lookalike_marker_is_not_accepted(self):
        assert api.parse_marker("[ref:short:1]") is None

