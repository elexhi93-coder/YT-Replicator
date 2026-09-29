"""U11 tests — storage roots, `acquire` (download → verify → rename), hygiene.

Two properties are worth more than the happy path, and both are asserted
here: a download is **verified** before it is ever called an asset, and
hygiene only removes what it can *prove* is ours.

Nothing touches a network or a real volume: the Port A provider is installed
through `core.api`'s registry, and every test works in a temp directory.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest
from django.apps import apps

from accounts.api import get_default_workspace
from core.api import (
    MaterializedMedia,
    MaterializeRequest,
    PermanentError,
    TransientError,
    register_source_provider,
    reset_port_registry,
)
from media import api
from media.errors import AssetNotFound, NoStorageSpace, VerificationFailed
from media.models import MediaAsset, MediaEvent, StorageRoot

pytestmark = pytest.mark.django_db

VIDEO = "mediaVideo01"


class FakeProvider:
    """A Port A source that writes bytes where it is told, or misbehaves."""

    def __init__(self, *, payload: bytes = b"x" * 64, error: Exception | None = None):
        self.payload = payload
        self.error = error
        #: Overrides the *declared* digest, so a test can simulate a platform
        #: whose announced checksum does not match the bytes that arrived. The
        #: default is derived from `payload`, which is the honest case.
        self.declared_sha256: str | None = None
        self.requests: list[MaterializeRequest] = []

    def materialize(self, request: MaterializeRequest) -> MaterializedMedia:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        target = Path(request.destination_dir) / f"{request.video_id}.mp4"
        target.write_bytes(self.payload)
        return MaterializedMedia(
            file_path=target,
            filename=target.name,
            size_bytes=len(self.payload),
            sha256=self.declared_sha256 or hashlib.sha256(self.payload).hexdigest(),
            duration_sec=90,
            format="mp4",
        )

    def resolve(self, raw_url):  # pragma: no cover - not this unit
        raise NotImplementedError

    def scan(self, source, since):  # pragma: no cover - not this unit
        raise NotImplementedError

    def hydrate(self, item):  # pragma: no cover - not this unit
        raise NotImplementedError


@pytest.fixture(autouse=True)
def registry_snapshot():
    snapshot = dict(__import__("core.registry", fromlist=["_PORTS"])._PORTS)
    yield
    reset_port_registry()
    __import__("core.registry", fromlist=["_PORTS"])._PORTS.update(snapshot)


@pytest.fixture
def provider(registry_snapshot):
    fake = FakeProvider()
    register_source_provider(lambda: fake)
    return fake


@pytest.fixture
def workspace():
    return get_default_workspace()


@pytest.fixture
def root_dir():
    return Path(tempfile.mkdtemp())


@pytest.fixture
def root(workspace, root_dir):
    return api.add_storage_root(workspace, root_dir, label="Hot", min_free_bytes=0)


class TestStorageRoots:
    def test_a_root_records_where_bytes_may_live(self, root, root_dir):
        assert Path(root.path) == root_dir.resolve()
        assert root.role == "hot"
        assert root.is_mounted is True

    def test_roots_are_picked_in_priority_order(self, workspace, root_dir):
        second_dir = Path(tempfile.mkdtemp())
        late = api.add_storage_root(
            workspace, root_dir, label="A", priority=200, min_free_bytes=0
        )
        early = api.add_storage_root(
            workspace, second_dir, label="B", priority=1, min_free_bytes=0
        )
        assert [r.pk for r in api.list_storage_roots(workspace)] == [early.pk, late.pk]
        assert api.pick_root(workspace).pk == early.pk

    def test_a_root_below_its_floor_is_skipped(self, workspace, root_dir, provider):
        api.add_storage_root(workspace, root_dir, label="Tiny", min_free_bytes=2**62)
        # The floor is a policy, not a suggestion: a download that would breach
        # it must not start.
        with pytest.raises(NoStorageSpace):
            api.pick_root(workspace)

    def test_no_space_is_transient_not_permanent(self):
        # Retention (U12) frees space, and so does an operator, so a full disk
        # must be backed off from, not failed forever.
        assert issubclass(NoStorageSpace, TransientError)
        assert not issubclass(NoStorageSpace, PermanentError)

    def test_a_detached_root_is_not_picked(self, workspace, root, provider):
        api.set_mounted(root, mounted=False)
        with pytest.raises(NoStorageSpace):
            api.pick_root(workspace)

    def test_detaching_archives_the_assets_on_it(self, workspace, root, provider):
        asset = api.acquire(workspace, VIDEO)
        assert asset.state == MediaAsset.STATE_ON_DISK
        # A re-attached cold drive must not trigger a mass re-download (F-52).
        api.set_mounted(root, mounted=False)
        asset.refresh_from_db()
        assert asset.state == MediaAsset.STATE_ARCHIVE_OFFLINE
        assert MediaEvent.objects.filter(event="archive_offline").count() == 1

    def test_free_space_is_recorded_when_we_read_it(self, root, provider):
        free = api.free_space(root)
        root.refresh_from_db()
        assert free > 0
        assert root.free_bytes == free


class TestAcquire:
    def test_acquire_verifies_then_renames_into_place(self, workspace, root, provider):
        asset = api.acquire(workspace, VIDEO)
        assert asset.state == MediaAsset.STATE_ON_DISK
        assert asset.sha256 == hashlib.sha256(b"x" * 64).hexdigest()
        assert asset.size_bytes == 64
        assert asset.materialization_no == 1
        final = Path(asset.absolute_path())
        assert final.exists()
        assert final.parent == Path(root.path).resolve()

    def test_the_staging_file_does_not_survive(self, workspace, root, provider):
        api.acquire(workspace, VIDEO)
        staging = Path(root.path) / api.STAGING_DIR
        assert not list(staging.glob("*.mp4"))

    def test_the_path_is_relative_so_a_root_can_move(self, workspace, root, provider):
        asset = api.acquire(workspace, VIDEO)
        # The absolute form is derived, never stored (INV-PATH-1).
        assert "/" not in asset.path
        assert asset.absolute_path().startswith(root.path)

    def test_a_digest_mismatch_is_never_an_asset(self, workspace, root, provider):
        # The bytes that arrived are not the bytes the platform promised.
        provider.declared_sha256 = hashlib.sha256(b"something else").hexdigest()
        with pytest.raises(VerificationFailed):
            api.acquire(workspace, VIDEO)
        # The row records the failure; the bytes are not left on disk.
        asset = MediaAsset.objects.get(source_video_id=VIDEO)
        assert asset.state == MediaAsset.STATE_FAILED
        assert not Path(asset.absolute_path()).exists()
        staging = Path(root.path) / api.STAGING_DIR
        assert not list(staging.glob("*.mp4")), "the bad download must be removed"

    def test_a_failed_download_is_recorded_then_raised(self, workspace, root, provider):
        provider.error = RuntimeError("network died")
        with pytest.raises(RuntimeError):
            api.acquire(workspace, VIDEO)
        assert (
            MediaAsset.objects.get(source_video_id=VIDEO).state
            == MediaAsset.STATE_FAILED
        )

    def test_a_copy_we_already_hold_is_reused(self, workspace, root, provider):
        first = api.acquire(workspace, VIDEO)
        again = api.acquire(workspace, VIDEO)
        assert again.pk == first.pk
        assert len(provider.requests) == 1  # nothing was downloaded twice

    def test_a_lost_file_is_re_downloaded_as_the_next_copy(
        self, workspace, root, provider
    ):
        first = api.acquire(workspace, VIDEO)
        Path(first.absolute_path()).unlink()
        again = api.acquire(workspace, VIDEO)
        # Copy 2, not an overwrite: the history stays honest.
        assert again.pk != first.pk
        assert again.materialization_no == 2
        assert Path(again.absolute_path()).exists()

    def test_events_are_written_for_what_happened(self, workspace, root, provider):
        api.acquire(workspace, VIDEO)
        kinds = [e.event for e in api.list_events(workspace)]
        assert "created" in kinds and "verified" in kinds
        verified = next(e for e in api.list_events(workspace) if e.event == "verified")
        assert verified.bytes == 64

    def test_the_job_is_remembered_on_the_asset(self, workspace, root, provider):
        job_model = apps.get_model("jobs", "Job")
        pipeline_model = apps.get_model("pipelines", "Pipeline")
        pipeline = pipeline_model.objects.create(workspace=workspace, name="P")
        job = job_model.objects.create(
            workspace=workspace, pipeline=pipeline, source_video_id=VIDEO
        )
        assert api.acquire(workspace, VIDEO, job=job).job_id == job.pk


class TestHygiene:
    def test_a_partial_from_a_crash_is_removed(self, workspace, root, provider):
        staging = Path(root.path) / api.STAGING_DIR
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "leftover.mp4.part").write_bytes(b"junk")
        report = api.hygiene(workspace)
        assert report["partials_removed"] == 1
        assert not (staging / "leftover.mp4.part").exists()

    def test_an_unclaimed_file_is_removed(self, workspace, root, provider):
        (Path(root.path) / "mystery.mp4").write_bytes(b"nope")
        report = api.hygiene(workspace)
        assert report["orphans_removed"] == 1
        assert not (Path(root.path) / "mystery.mp4").exists()

    def test_a_file_we_claim_is_never_removed(self, workspace, root, provider):
        asset = api.acquire(workspace, VIDEO)
        report = api.hygiene(workspace)
        assert report["orphans_removed"] == 0
        assert Path(asset.absolute_path()).exists()

    def test_the_bytes_freed_are_reported(self, workspace, root, provider):
        (Path(root.path) / "mystery.mp4").write_bytes(b"y" * 500)
        assert api.hygiene(workspace)["bytes_freed"] == 500


class TestReads:
    def test_assets_can_be_filtered_by_state(self, workspace, root, provider):
        api.acquire(workspace, VIDEO)
        assert len(api.list_assets(workspace, state="on_disk")) == 1
        assert api.list_assets(workspace, state="failed") == []

    def test_a_missing_asset_raises(self, workspace):
        with pytest.raises(AssetNotFound):
            api.get_asset(workspace, 999999)