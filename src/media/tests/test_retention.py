"""U12 tests — the retention evaluator, the gate order, and the two phases.

The evaluator is a pure function, so most of these need no filesystem, no
oracle and no network: they build an asset-shaped stand-in and a
`RetentionFacts` value and assert the verdict. That is the payoff of INV-10 —
the rules are testable as rules, not as a side effect of a sweep.

The gate *order* is asserted explicitly, because a reordering that still
"passes" the happy path is exactly the defect that would delete a file an
upload still needs.
"""

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from core.api import RetentionFacts, now_utc
from media import api, retention

pytestmark = pytest.mark.django_db

NOW = now_utc()
VIDEO = "retentionVid1"


class FakeAsset:
    """The only attributes `evaluate()` reads."""

    def __init__(self, pk=1, size=1000, pinned_until=None, age_days=0):
        self.pk = pk
        self.id = pk
        self.size_bytes = size
        self.pinned_until = pinned_until
        self.downloaded_at = NOW - timedelta(days=age_days)
        self.created_at = self.downloaded_at


def facts(**overrides) -> RetentionFacts:
    base = dict(
        mode="immediate",
        retention_n=2,
        retention_hours=24,
        all_destinations_terminal=True,
        destination_copy_present=True,
        newer_completed_jobs=0,
        uploaded_at=NOW - timedelta(hours=48),
    )
    base.update(overrides)
    return RetentionFacts(**base)


def decide(asset=None, **overrides) -> retention.Decision:
    return retention.evaluate(
        asset or FakeAsset(), facts(**overrides), now=NOW, backstop_days=7
    )


class TestGateOrder:
    def test_keep_short_circuits_before_anything_else(self):
        # Even with every other gate open, `keep` stops at the first line.
        decision = decide(mode="keep")
        assert decision.delete is False
        assert decision.reason == "mode=keep"

    def test_a_non_terminal_destination_forbids_deletion(self):
        # INV-2 outranks the mode, the pin and the backstop.
        decision = decide(mode="immediate", all_destinations_terminal=False)
        assert decision.delete is False
        assert "INV-2" in decision.reason

    def test_a_pin_outranks_the_mode(self):
        pinned = FakeAsset(pinned_until=NOW + timedelta(days=1))
        decision = retention.evaluate(
            pinned, facts(mode="immediate"), now=NOW, backstop_days=7
        )
        assert decision.delete is False
        assert "pinned" in decision.reason

    def test_an_expired_pin_no_longer_holds(self):
        stale = FakeAsset(pinned_until=NOW - timedelta(days=1))
        decision = retention.evaluate(
            stale, facts(mode="immediate"), now=NOW, backstop_days=7
        )
        assert decision.delete is True

    def test_unknown_facts_never_delete(self):
        decision = decide(unavailable_reason="no job for this asset")
        assert decision.delete is False
        assert "facts unavailable" in decision.reason


class TestModes:
    def test_immediate_deletes_once_the_gates_pass(self):
        assert decide(mode="immediate").delete is True

    def test_after_n_jobs_waits_for_n_newer_jobs(self):
        # D5: fewer than N newer completed jobs remain.
        assert decide(mode="after_n_jobs", retention_n=2, newer_completed_jobs=1).delete
        assert not decide(
            mode="after_n_jobs", retention_n=2, newer_completed_jobs=2
        ).delete

    def test_after_hours_waits_for_the_clock(self):
        assert decide(
            mode="after_hours",
            retention_hours=24,
            uploaded_at=NOW - timedelta(hours=25),
        ).delete
        assert not decide(
            mode="after_hours",
            retention_hours=24,
            uploaded_at=NOW - timedelta(hours=23),
        ).delete

    def test_after_hours_refuses_when_nothing_was_uploaded(self):
        # No `uploaded_at` means the gate cannot be satisfied; guessing "now"
        # would delete on a clock that never started.
        decision = decide(mode="after_hours", uploaded_at=None)
        assert decision.delete is False
        assert "nothing has been uploaded" in decision.reason

    def test_an_unknown_mode_is_refused_not_guessed(self):
        decision = decide(mode="whenever")
        assert decision.delete is False
        assert "unknown retention mode" in decision.reason

    def test_the_backstop_forces_deletion_a_stalled_mode_would_keep(self):
        # D6: otherwise a stalled pipeline pins disk forever. 30 days old with
        # the mode unmet — the backstop is the only thing that says yes.
        old = FakeAsset(age_days=30)
        decision = retention.evaluate(
            old,
            facts(mode="after_n_jobs", retention_n=2, newer_completed_jobs=9),
            now=NOW,
            backstop_days=7,
        )
        assert decision.delete is True
        assert "backstop" in decision.reason

    def test_the_backstop_cannot_override_inv2(self):
        old = FakeAsset(age_days=30)
        decision = retention.evaluate(
            old,
            facts(mode="immediate", all_destinations_terminal=False),
            now=NOW,
            backstop_days=7,
        )
        assert decision.delete is False
        assert "INV-2" in decision.reason


class TestFloors:
    def test_the_min_age_floor_defers_but_still_records_the_decision(self):
        fresh = FakeAsset(age_days=0)
        decision = retention.evaluate(
            fresh, facts(mode="immediate"), now=NOW, backstop_days=7, min_age_hours=24
        )
        # Z5: "NO, but delete_after is set" — visible before it fires.
        assert decision.delete is False
        assert decision.delete_after is not None
        assert "min-age floor" in decision.reason

    def test_the_min_age_floor_is_off_by_default(self):
        # docs/05 §8 G7 defines the gate but no default value, so it ships
        # disabled rather than invented.
        assert retention.DEFAULT_MIN_AGE_HOURS == 0
        assert decide(mode="immediate").delete is True


@pytest.fixture
def workspace():
    from accounts.api import get_default_workspace

    return get_default_workspace()


@pytest.fixture
def root_dir():
    return Path(tempfile.mkdtemp())


@pytest.fixture
def on_disk_asset(workspace, root_dir):
    """A real on-disk asset. The provider is irrelevant: the file is already here."""
    from media.models import MediaAsset

    root = api.add_storage_root(workspace, root_dir, label="Hot", min_free_bytes=0)
    target = Path(root.path) / f"{VIDEO}.mp4"
    target.write_bytes(b"x" * 1000)
    return MediaAsset.objects.create(
        workspace=workspace,
        source_video_id=VIDEO,
        storage_root=root,
        path=target.name,
        state=MediaAsset.STATE_ON_DISK,
        size_bytes=target.stat().st_size,
        downloaded_at=now_utc(),
    )


@pytest.fixture
def fake_oracle():
    """Install an oracle that says "delete everything", so the sweep tests
    exercise the sweeper rather than the gates (which are tested above)."""
    from core.api import get_retention_oracle, register_retention_oracle

    real = get_retention_oracle()
    register_retention_oracle(lambda: _AlwaysDelete())
    yield
    register_retention_oracle(lambda: real)


class _AlwaysDelete:
    def facts_for(self, workspace_id, source_video_id, job_id):
        return facts(mode="immediate", destination_copy_present=True)


class TestLastCopy:
    def test_the_only_local_copy_survives_an_unconfirmed_destination(self, on_disk_asset):
        # D3: we hold a certainty and the platform holds an assumption.
        decision = retention.evaluate(
            on_disk_asset,
            facts(mode="immediate", destination_copy_present=False),
            now=NOW,
            backstop_days=7,
        )
        assert decision.delete is False
        assert "last local copy" in decision.reason

    def test_a_second_local_copy_makes_the_first_disposable(
        self, workspace, on_disk_asset
    ):
        from media.models import MediaAsset

        MediaAsset.objects.create(
            workspace=workspace,
            source_video_id=VIDEO,
            materialization_no=2,
            storage_root=on_disk_asset.storage_root,
            path="copy2.mp4",
            state=MediaAsset.STATE_ON_DISK,
            size_bytes=10,
            downloaded_at=now_utc(),
        )
        decision = retention.evaluate(
            on_disk_asset,
            facts(mode="immediate", destination_copy_present=False),
            other_local_copies=True,
            now=NOW,
            backstop_days=7,
        )
        assert decision.delete is True


class TestTwoPhase:
    def test_a_dry_run_schedules_nothing(self, workspace, on_disk_asset, fake_oracle):
        report = retention.sweep(workspace, dry_run=True, now=NOW)
        on_disk_asset.refresh_from_db()
        assert on_disk_asset.delete_after is None
        assert report.dry_run is True

    def test_a_sweep_schedules_but_never_deletes(
        self, workspace, on_disk_asset, fake_oracle
    ):
        retention.sweep(workspace, dry_run=False, now=NOW, grace_minutes=60)
        on_disk_asset.refresh_from_db()
        # Phase one writes the intent…
        assert on_disk_asset.state == "on_disk"
        assert on_disk_asset.delete_after == NOW + timedelta(minutes=60)
        # …and the bytes are still there.
        assert Path(on_disk_asset.absolute_path()).exists()

    def test_execute_due_deletes_only_what_is_due(
        self, workspace, on_disk_asset, fake_oracle
    ):
        on_disk_asset.delete_after = NOW - timedelta(minutes=1)
        on_disk_asset.save(update_fields=["delete_after"])
        result = retention.execute_due(workspace, now=NOW)
        on_disk_asset.refresh_from_db()
        assert result["deleted"] == 1
        assert on_disk_asset.state == "deleted"
        assert on_disk_asset.deleted_at is not None
        assert not Path(on_disk_asset.absolute_path()).exists()

    def test_execute_due_ignores_a_future_schedule(
        self, workspace, on_disk_asset, fake_oracle
    ):
        on_disk_asset.delete_after = NOW + timedelta(hours=1)
        on_disk_asset.save(update_fields=["delete_after"])
        assert retention.execute_due(workspace, now=NOW)["deleted"] == 0
        assert Path(on_disk_asset.absolute_path()).exists()

    def test_a_pin_arriving_after_the_sweep_still_saves_the_file(
        self, workspace, on_disk_asset, fake_oracle
    ):
        # The executor re-checks the pin: this is the last moment it is knowable.
        on_disk_asset.delete_after = NOW - timedelta(minutes=1)
        on_disk_asset.pinned_until = NOW + timedelta(days=1)
        on_disk_asset.save(update_fields=["delete_after", "pinned_until"])
        assert retention.execute_due(workspace, now=NOW)["deleted"] == 0
        on_disk_asset.refresh_from_db()
        assert on_disk_asset.state == "on_disk"
        assert on_disk_asset.delete_after is None  # the schedule is released
        assert Path(on_disk_asset.absolute_path()).exists()

    def test_cancelling_releases_the_schedule(
        self, workspace, on_disk_asset, fake_oracle
    ):
        on_disk_asset.delete_after = NOW - timedelta(minutes=1)
        on_disk_asset.save(update_fields=["delete_after"])
        retention.cancel(on_disk_asset, actor="operator")
        on_disk_asset.refresh_from_db()
        assert on_disk_asset.delete_after is None
        assert retention.execute_due(workspace, now=NOW)["deleted"] == 0

    def test_a_deletion_is_audited_with_its_bytes(
        self, workspace, on_disk_asset, fake_oracle
    ):
        from media.models import MediaEvent

        on_disk_asset.delete_after = NOW - timedelta(minutes=1)
        on_disk_asset.save(update_fields=["delete_after"])
        retention.execute_due(workspace, now=NOW, actor="operator")
        event = MediaEvent.objects.filter(event="deleted").first()
        # "4.2 GB was freed at 03:11" is only possible if this is recorded.
        assert event is not None
        assert event.bytes == 1000
        assert event.actor == "operator"


class TestPin:
    def test_pin_then_unpin_round_trips(self, on_disk_asset):
        retention.pin(on_disk_asset, reason="operator asked")
        on_disk_asset.refresh_from_db()
        assert on_disk_asset.pinned_reason == "operator asked"
        retention.unpin(on_disk_asset)
        on_disk_asset.refresh_from_db()
        assert on_disk_asset.pinned_until is None
        assert on_disk_asset.pinned_reason == ""

    def test_pin_and_unpin_are_audited(self, on_disk_asset):
        from media.models import MediaEvent

        retention.pin(on_disk_asset, reason="keep me")
        retention.unpin(on_disk_asset)
        kinds = [e.event for e in MediaEvent.objects.all()]
        assert "pinned" in kinds and "unpinned" in kinds

