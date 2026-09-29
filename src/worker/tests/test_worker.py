"""
U14 tests — the run loop, the gates, and restart recovery.

The properties worth protecting are all about *not losing work* and *not
lying*:

* a pause returns the job untouched — no attempt counted, no backoff written;
* a transient failure retries, a permanent one does not, and the loop survives
  an error it has never seen;
* a dead worker's wreckage is swept, and an interrupted upload is
  **reconciled rather than retried**.

The end-to-end test drives the real modules with a fake Port A provider and a
fake Port B platform, so the only thing stubbed is the network.
"""

from __future__ import annotations

import hashlib
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from core.api import (
    MaterializedMedia,
    MaterializeRequest,
    TransientError,
    register_destination_platform,
    register_source_provider,
)
from django.apps import apps
from media.api import add_storage_root
from worker import gates, recovery
from worker.api import run_once

pytestmark = pytest.mark.django_db

VIDEO = "workerVid001"


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    """INV-1 needs a key to encrypt the channel's token. Fixed and hermetic."""
    monkeypatch.setenv("PLATFORM_MASTER_KEY", "0" * 64)



class FakeSource:
    """Port A: writes bytes, or refuses like a deleted video."""

    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.calls = 0

    def materialize(self, request: MaterializeRequest) -> MaterializedMedia:
        self.calls += 1
        if self.error is not None:
            raise self.error
        target = Path(request.destination_dir) / f"{request.video_id}.mp4"
        target.write_bytes(b"m" * 256)
        return MaterializedMedia(
            file_path=target,
            filename=target.name,
            size_bytes=256,
            sha256=hashlib.sha256(b"m" * 256).hexdigest(),
            duration_sec=42,
            format="mp4",
        )

    def resolve(self, raw_url):
        from core.api import ResolvedSource

        # `add_source` resolves the URL to register it, so the fake has to be a
        # real Port A — otherwise the fixture would shell out to yt-dlp.
        handle = raw_url.rstrip("/").split("/")[-1].lstrip("@")
        return ResolvedSource(
            kind="channel",
            external_id=f"UC{handle[:22].upper()}",
            canonical_url=raw_url,
            title="Worker Channel",
        )

    def scan(self, source, since):
        raise NotImplementedError

    def hydrate(self, item):
        raise NotImplementedError


class FakePlatform:
    """Port B: records that it was asked to upload."""

    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.uploads = []
        self.tokens = []

    def probe_auth(self, credentials: bytes):
        raise NotImplementedError

    def sync_inventory(self, channel, cursor=None):
        raise NotImplementedError

    def upload(self, request, *, token="", on_progress=None):
        # Mirrors the real Port B call site in `youtube.api.upload`, which
        # passes the token and the callback as keywords.
        from core.api import UploadOutcome

        self.uploads.append(request)
        self.tokens.append(token)
        if self.error is not None:
            raise self.error
        return UploadOutcome(
            destination_video_id="yt00000001",
            destination_url="https://youtu.be/yt00000001",
            privacy=request.privacy,
            units_used=1600,
            http_status=200,
            raw_error_code=None,
            thumbnail_uploaded=False,
        )

    def unit_cost_for_upload(self):
        return 1600


@pytest.fixture(autouse=True)
def restore_ports():
    from core.api import get_retention_oracle, get_source_provider, get_upload_planner

    real = {
        "source": get_source_provider(),
        "planner": get_upload_planner(),
        "oracle": get_retention_oracle(),
    }
    yield
    register_source_provider(lambda: real["source"])
    from core.api import register_retention_oracle, register_upload_planner

    register_upload_planner(lambda: real["planner"])
    register_retention_oracle(lambda: real["oracle"])


@pytest.fixture
def source_port():
    fake = FakeSource()
    register_source_provider(lambda: fake)
    return fake


@pytest.fixture
def platform():
    fake = FakePlatform()
    register_destination_platform(lambda: fake)
    return fake


@pytest.fixture
def workspace():
    from accounts.api import get_default_workspace

    return get_default_workspace()


@pytest.fixture
def root(workspace):
    return add_storage_root(
        workspace, Path(tempfile.mkdtemp()), label="Hot", min_free_bytes=0
    )


@pytest.fixture
def channel(workspace):
    """An authorised channel whose token is real, encrypted and not expiring.

    `valid_access_token` is the only way `youtube` obtains a token, and it
    refuses a channel that was never authorised — so the fixture authorises one
    properly rather than stubbing the call away. Same reasoning as the U09
    tests: that refusal is real behaviour, and stubbing it would test nothing.

    The rows are built through the app registry rather than by importing
    `credentials`, because `worker` may not import it (docs/04 §2) and the
    boundary test enforces that on this file too.
    """
    from core.api import encrypt, now_utc

    client_model = apps.get_model("credentials", "GoogleClient")
    channel_model = apps.get_model("credentials", "AuthorizedChannel")
    client = client_model.objects.create(
        workspace=workspace,
        label="Worker",
        client_id="worker-client",
        client_secret_enc=encrypt("s").encode("utf-8"),
        daily_upload_cap=6,
        is_active=True,
    )
    channel = channel_model.objects.create(
        workspace=workspace,
        google_client=client,
        channel_id="UCworker00001",
        title="Worker Channel",
        access_token_enc=encrypt("access-token").encode("utf-8"),
        refresh_token_enc=encrypt("refresh-token").encode("utf-8"),
        token_state="valid",
        token_expires_at=now_utc() + timedelta(hours=1),
    )
    return channel


@pytest.fixture
def rig(workspace, platform, source_port, channel):
    """A pipeline with a source and an authorised destination, both attached.

    Built through the app registry for the same reason as `channel`: the worker
    may not import `pipelines` or `sources`, and its tests are held to the same
    rule as its code.
    """
    source_model = apps.get_model("sources", "Source")
    destination_model = apps.get_model("pipelines", "Destination")
    pipeline_model = apps.get_model("pipelines", "Pipeline")
    link_model = apps.get_model("pipelines", "PipelineDestination")

    destination = destination_model.objects.create(
        workspace=workspace,
        authorized_channel=channel,
        label="Main",
        platform="youtube",
        default_privacy="unlisted",
        daily_max=6,
        enabled=True,
    )
    source = source_model.objects.create(
        workspace=workspace,
        kind="channel",
        external_id="UCworker00001",
        url="https://www.youtube.com/@WorkerChannel",
        name="Worker Channel",
    )
    pipeline = pipeline_model.objects.create(
        workspace=workspace, name="P", status="active", priority=100
    )
    link_model.objects.create(
        workspace=workspace,
        pipeline=pipeline,
        destination=destination,
        enabled=True,
        priority=100,
        privacy_override="unlisted",
    )
    return {
        "pipeline": pipeline,
        "destination": destination,
        "channel": channel,
        "source": source,
    }


def enqueue(workspace, pipeline, source, *, intent="upload", video=VIDEO):
    from jobs.api import enqueue as jobs_enqueue

    return jobs_enqueue(workspace, pipeline, video, intent=intent, source=source)


class TestTheLoop:
    def test_an_empty_queue_is_idle_not_an_error(self):
        result = run_once("w1")
        assert result.claimed is False
        assert result.outcome == "idle"
        assert bool(result) is False

    def test_an_upload_job_runs_end_to_end(
        self, workspace, rig, root, source_port, platform
    ):
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        result = run_once("w1")
        assert result.outcome == "succeeded"
        job.refresh_from_db()
        assert job.status == "uploaded"
        # The one thing that matters: the bytes reached the platform.
        assert len(platform.uploads) == 1
        assert platform.uploads[0].provenance_marker.startswith("[ref:")

    def test_the_media_lands_on_disk_before_the_upload(
        self, workspace, rig, root, source_port, platform
    ):
        MediaAsset = apps.get_model("media", "MediaAsset")

        enqueue(workspace, rig["pipeline"], rig["source"])
        run_once("w1")
        assert MediaAsset.objects.filter(
            source_video_id=VIDEO, state="on_disk"
        ).exists()

    def test_a_rehydrate_job_never_uploads(
        self, workspace, rig, root, source_port, platform
    ):
        job = enqueue(workspace, rig["pipeline"], rig["source"], intent="rehydrate")
        result = run_once("w1")
        assert result.outcome == "succeeded"
        job.refresh_from_db()
        assert job.status == "uploaded"
        # The whole point of a separate intent: the file comes back, the
        # channel is not touched.
        assert platform.uploads == []
        assert "rehydrated" in result.detail

    def test_a_transient_failure_requeues_with_backoff(
        self, workspace, rig, root, source_port
    ):
        source_port.error = TransientError("network hiccup")
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        result = run_once("w1")
        assert result.outcome == "failed"
        job.refresh_from_db()
        assert job.status == "queued"
        assert job.attempt_count == 1
        # Backing off means the next claim will not find it.
        assert job.claim_expires_at is not None

    def test_a_permanent_failure_stops_the_video(
        self, workspace, rig, root, source_port
    ):
        source_port.error = RuntimeError(
            "ERROR: Video unavailable. This video is private"
        )
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        result = run_once("w1")
        job.refresh_from_db()
        # A deleted video is a fact, not a fault: no amount of retrying helps.
        assert result.outcome == "failed"
        assert job.status == "failed_permanent"
        # `fail()` only counts an attempt on the *retry* path. A permanent
        # failure will not be retried, so the counter stays put rather than
        # implying a try that is never going to happen.
        assert job.attempt_count == 0
        assert job.finished_at is not None

    def test_the_loop_survives_an_error_it_has_never_seen(
        self, workspace, rig, root, source_port
    ):
        source_port.error = ZeroDivisionError("a genuine bug")
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        result = run_once("w1")
        # Stranding the job would be worse than failing it visibly.
        assert result.outcome == "failed"
        job.refresh_from_db()
        assert job.status == "failed_permanent"


def pause_pipeline(pipeline):
    """Pause it the way an operator would, without importing `pipelines`.

    The worker may not import that module, and its tests are held to the same
    rule as its code — so the row is written directly rather than routing
    around the boundary to call `pipelines.api.pause`.
    """
    pipeline.status = "paused"
    pipeline.save(update_fields=["status", "updated_at"])
    return pipeline


class TestGates:
    def test_a_paused_pipeline_holds_the_job(self, workspace, rig, root, source_port):
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        pause_pipeline(rig["pipeline"])
        result = run_once("w1")
        assert result.outcome == "requeued"
        job.refresh_from_db()
        assert job.status == "queued"
        assert "paused" in job.error_message
        assert source_port.calls == 0  # nothing was downloaded

    def test_a_pause_does_not_burn_an_attempt(self, workspace, rig, root, source_port):
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        pause_pipeline(rig["pipeline"])
        run_once("w1")
        job.refresh_from_db()
        # The difference between a pause and a failure, in one assertion: five
        # full disks must not cost a video all five of its attempts.
        assert job.attempt_count == 0

    def test_a_pause_writes_no_backoff(self, workspace, rig, root, source_port):
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        pause_pipeline(rig["pipeline"])
        run_once("w1")
        job.refresh_from_db()
        assert job.claim_expires_at is None

    def test_a_gate_that_passes_lets_the_job_through(
        self, workspace, rig, root, source_port
    ):
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        assert gates.evaluate(job) is None

    def test_a_full_disk_holds_the_job(self, workspace, rig, source_port):
        StorageRoot = apps.get_model("media", "StorageRoot")

        # The only root is below its floor, so nothing may be downloaded.
        for root in StorageRoot.objects.filter(workspace=workspace):
            root.min_free_bytes = 2**62
            root.save(update_fields=["min_free_bytes"])
        job = enqueue(workspace, rig["pipeline"], rig["source"])
        result = run_once("w1")
        assert result.outcome == "requeued"
        assert "paused" in result.detail
        job.refresh_from_db()
        assert job.attempt_count == 0
        assert source_port.calls == 0

    def test_quota_exhaustion_holds_instead_of_failing(
        self, workspace, rig, root, source_port, platform
    ):
        QuotaUsage = apps.get_model("youtube", "QuotaUsage")
        from core.api import quota_day_string

        job = enqueue(workspace, rig["pipeline"], rig["source"])
        # Fill the destination's daily allowance before the worker looks.
        QuotaUsage.objects.update_or_create(
            workspace=workspace,
            destination=rig["destination"],
            quota_date=quota_day_string(),
            defaults={"uploads_used": rig["destination"].daily_max, "units_used": 0},
        )
        result = run_once("w1")
        assert result.outcome == "requeued"
        assert "quota" in result.detail
        job.refresh_from_db()
        assert job.status == "queued"
        assert job.attempt_count == 0
        assert platform.uploads == []


class TestRecovery:
    def test_an_expired_claim_returns_to_the_queue(self, workspace, rig, source_port):
        from django.utils import timezone

        from jobs.api import claim

        job = enqueue(workspace, rig["pipeline"], rig["source"])
        claimed = claim("dead-worker")
        claimed.claim_expires_at = timezone.now() - timedelta(hours=2)
        claimed.save(update_fields=["claim_expires_at"])
        report = recovery.recover()
        assert report.jobs_requeued == 1
        job.refresh_from_db()
        assert job.status == "queued"
        assert job.claimed_by == ""

    def test_a_live_claim_is_left_alone(self, workspace, rig, source_port):
        from jobs.api import claim

        job = enqueue(workspace, rig["pipeline"], rig["source"])
        claim("busy-worker")
        recovery.recover()
        job.refresh_from_db()
        # A healthy long download must never be swept out from under itself.
        assert job.status == "claimed"

    def test_a_stuck_download_fails_and_says_why(self, workspace, rig, root, source_port):
        from django.utils import timezone

        MediaAsset = apps.get_model("media", "MediaAsset")

        asset = MediaAsset.objects.create(
            workspace=workspace,
            source_video_id=VIDEO,
            storage_root=root,
            path=f"{VIDEO}1.mp4",
            state=MediaAsset.STATE_DOWNLOADING,
        )
        MediaAsset.objects.filter(pk=asset.pk).update(
            updated_at=timezone.now() - timedelta(hours=3)
        )
        report = recovery.recover()
        assert report.downloads_failed == 1
        asset.refresh_from_db()
        assert asset.state == MediaAsset.STATE_FAILED
        assert "interrupted" in asset.delete_reason

    def test_recovery_is_idempotent(self, workspace, rig, source_port):
        from django.utils import timezone

        from jobs.api import claim

        enqueue(workspace, rig["pipeline"], rig["source"])
        claimed = claim("dead-worker")
        claimed.claim_expires_at = timezone.now() - timedelta(hours=2)
        claimed.save(update_fields=["claim_expires_at"])
        first = recovery.recover()
        second = recovery.recover()
        assert first.jobs_requeued == 1
        assert second.jobs_requeued == 0

    def test_the_report_reads_the_way_start_up_logs_it(self, workspace, rig, source_port):
        report = recovery.recover()
        assert set(report.as_dict()) == {
            "jobs_requeued",
            "downloads_failed",
            "uploads_reconciled",
        }



