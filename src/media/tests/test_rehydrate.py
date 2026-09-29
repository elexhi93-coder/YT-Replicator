"""U13 tests — rehydrate: the cheap route first, and honesty about the rest.

The property that matters most here is that a re-attached cold drive costs
**nothing**: no download, no new copy, no state churn beyond the relabel. That
is what `archive_offline` (F-52) was bought for, so it is asserted directly by
counting provider calls.

The second property is honesty: a file we cannot verify is not relabelled, and
a source video that is gone is a permanent failure rather than an infinite
retry.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest
from core.api import (
    ItemUnavailable,
    MaterializedMedia,
    PermanentError,
    TransientError,
    register_source_provider,
)
from media import api, rehydrate
from media.models import MediaAsset, MediaEvent

pytestmark = pytest.mark.django_db

VIDEO = "rehydrateVid1"


class FakeProvider:
    def __init__(self, *, payload: bytes = b"y" * 128, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def materialize(self, request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        target = Path(request.destination_dir) / f"{request.video_id}.mp4"
        target.write_bytes(self.payload)
        return MaterializedMedia(
            file_path=target,
            filename=target.name,
            size_bytes=len(self.payload),
            sha256=hashlib.sha256(self.payload).hexdigest(),
            duration_sec=60,
            format="mp4",
        )

    def resolve(self, raw_url):  # pragma: no cover
        raise NotImplementedError

    def scan(self, source, since):  # pragma: no cover
        raise NotImplementedError

    def hydrate(self, item):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def workspace():
    from accounts.api import get_default_workspace

    return get_default_workspace()


@pytest.fixture
def root_dir():
    return Path(tempfile.mkdtemp())


@pytest.fixture
def root(workspace, root_dir):
    return api.add_storage_root(workspace, root_dir, label="Cold", min_free_bytes=0)


@pytest.fixture
def provider():
    fake = FakeProvider()
    register_source_provider(lambda: fake)
    return fake


class TestRelabelIsFree:
    def test_a_re_attached_root_costs_no_download(self, workspace, root, provider):
        api.acquire(workspace, VIDEO)
        api.set_mounted(root, mounted=False)
        api.set_mounted(root, mounted=True)
        # F-52: re-attaching a cold drive must not trigger a re-download.
        assert provider.calls == 1

    def test_a_rehydrated_file_comes_back_on_disk(self, workspace, root, provider):
        original = api.acquire(workspace, VIDEO)
        api.set_mounted(root, mounted=False)
        api.set_mounted(root, mounted=True)
        original.refresh_from_db()
        assert original.state == MediaAsset.STATE_ON_DISK
        assert Path(original.absolute_path()).exists()

    def test_rehydrating_an_offline_file_downloads_nothing(self, workspace, root, provider):
        # Deliberately *not* re-attaching through `set_mounted`: the asset must
        # still be `archive_offline` when rehydrate starts, so this exercises
        # `relabel_if_recoverable` and not the earlier automatic restore.
        original = api.acquire(workspace, VIDEO)
        api.set_mounted(root, mounted=False)
        MediaAsset.objects.filter(pk=original.pk).update(
            state=MediaAsset.STATE_ARCHIVE_OFFLINE
        )
        root.refresh_from_db()
        root.is_mounted = True
        root.save(update_fields=["is_mounted"])

        result = rehydrate.rehydrate(workspace, VIDEO)
        assert result.cost == "free"
        assert provider.calls == 1  # the original acquire, nothing since
        assert result.asset.pk == original.pk
        assert result.asset.materialization_no == 1  # not a second copy
        assert result.asset.state == MediaAsset.STATE_ON_DISK

    def test_re_attaching_is_itself_already_free(self, workspace, root, provider):
        # The flow's first branch happens at mount time rather than at
        # rehydrate time: detaching archives, re-attaching restores, and
        # nothing is downloaded in between. Both routes are free; this one is
        # the operator's, the one above is a scheduled job's.
        original = api.acquire(workspace, VIDEO)
        api.set_mounted(root, mounted=False)
        original.refresh_from_db()
        assert original.state == MediaAsset.STATE_ARCHIVE_OFFLINE
        api.set_mounted(root, mounted=True)
        original.refresh_from_db()
        assert original.state == MediaAsset.STATE_ON_DISK
        assert provider.calls == 1

    def test_a_still_detached_root_cannot_be_relabelled(self, workspace, root, provider):
        # Still detached: there is nowhere to read the file from, so the cheap
        # route is impossible and the caller gets the real reason.
        api.acquire(workspace, VIDEO)
        api.set_mounted(root, mounted=False)
        from media.errors import NoStorageSpace

        with pytest.raises(NoStorageSpace):
            rehydrate.rehydrate(workspace, VIDEO)

    def test_the_relabel_is_audited(self, workspace, root, provider):
        api.acquire(workspace, VIDEO)
        api.set_mounted(root, mounted=False)
        api.set_mounted(root, mounted=True)
        assert MediaEvent.objects.filter(event="rehydrated").count() == 1


class TestRelabelRefusesToGuess:
    def test_a_file_that_vanished_is_not_relabelled(self, workspace, root, provider):
        asset = api.acquire(workspace, VIDEO)
        Path(asset.absolute_path()).unlink()
        api.set_mounted(root, mounted=False)
        api.set_mounted(root, mounted=True)
        asset.refresh_from_db()
        # Trusting the row would claim we hold a verified copy we do not.
        assert asset.state == MediaAsset.STATE_ARCHIVE_OFFLINE

    def test_a_file_whose_bytes_changed_is_not_relabelled(
        self, workspace, root, provider
    ):
        asset = api.acquire(workspace, VIDEO)
        Path(asset.absolute_path()).write_bytes(b"tampered")
        api.set_mounted(root, mounted=False)
        api.set_mounted(root, mounted=True)
        asset.refresh_from_db()
        assert asset.state == MediaAsset.STATE_ARCHIVE_OFFLINE
        assert MediaEvent.objects.filter(event="rehydrated").count() == 0


class TestTheDownloadRoute:
    def test_a_missing_file_is_downloaded_again(self, workspace, root, provider):
        asset = api.acquire(workspace, VIDEO)
        Path(asset.absolute_path()).unlink()
        result = rehydrate.rehydrate(workspace, VIDEO)
        assert result.cost == "downloaded"
        assert provider.calls == 2
        # A re-download is a new copy, never an overwrite: the history stays
        # honest about what we had and when.
        assert result.asset.materialization_no == 2

    def test_the_new_copy_is_verified_and_pinned(self, workspace, root, provider):
        asset = api.acquire(workspace, VIDEO)
        Path(asset.absolute_path()).unlink()
        result = rehydrate.rehydrate(workspace, VIDEO)
        assert result.asset.sha256 == hashlib.sha256(b"y" * 128).hexdigest()
        assert result.asset.pinned_reason == rehydrate.REHYDRATE_PIN_REASON

    def test_a_rehydrated_file_never_gets_auto_deleted(self, workspace, root, provider):
        # D4: `pinned_until` is NULL, which is our infinity — a real expiry
        # would silently un-pin the file and nothing would explain it later.
        result = rehydrate.rehydrate(workspace, VIDEO)
        assert result.asset.pinned_until is None
        assert result.asset.pinned_reason == "rehydrated"

    def test_rehydrating_twice_does_not_stack_pin_events(
        self, workspace, root, provider
    ):
        rehydrate.rehydrate(workspace, VIDEO)
        rehydrate.rehydrate(workspace, VIDEO)
        pins = MediaEvent.objects.filter(event="pinned", reason="rehydrated")
        assert pins.count() == 1

    def test_a_file_already_on_disk_costs_nothing(self, workspace, root, provider):
        api.acquire(workspace, VIDEO)
        result = rehydrate.rehydrate(workspace, VIDEO)
        assert provider.calls == 1
        assert result.asset.state == MediaAsset.STATE_ON_DISK


class TestHonestAboutNonRecoverability:
    def test_a_gone_source_is_a_permanent_failure(self, workspace, root, provider):
        provider.error = RuntimeError("ERROR: Video unavailable. This video is private")
        with pytest.raises(ItemUnavailable):
            rehydrate.rehydrate(workspace, VIDEO)

    def test_unavailable_is_permanent_not_transient(self):
        # The Library must be able to say "no surviving source", and the job
        # must not retry a deleted video forever.
        assert not issubclass(ItemUnavailable, TransientError)

    def test_a_network_blip_is_not_mistaken_for_a_gone_video(
        self, workspace, root, provider
    ):
        provider.error = ConnectionError("connection reset by peer")
        # Wrong in either direction is expensive: treating a blip as permanent
        # loses a recoverable file.
        with pytest.raises(ConnectionError):
            rehydrate.rehydrate(workspace, VIDEO)

    def test_a_permanent_error_classification_is_honoured(
        self, workspace, root, provider
    ):
        class Rejected(PermanentError):
            default_code = "rejected"

        provider.error = Rejected("bad metadata")
        with pytest.raises(Rejected):
            rehydrate.rehydrate(workspace, VIDEO)
