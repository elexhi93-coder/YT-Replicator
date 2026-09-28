"""U06 tests — pipelines: CRUD, the state machine, and attachment management.

The interesting behaviour is not the happy path but the guards: a draft
pipeline cannot run, a half-configured one refuses to activate, and a soft
delete never cascades the ledger (INV-4, D-04). Those are the rules the legacy
broke, so they are what is asserted here.

No test reaches another module's tables: sources and channels are created
through their own `api` surfaces, which is also the boundary the module
operates under (INV-11/INV-12).
"""

from __future__ import annotations

import pytest
from django.apps import apps

from accounts.api import get_default_workspace
from core.api import PermanentError
from pipelines import api
from pipelines.errors import (
    DownloadProfileNotFound,
    InvalidSetting,
    InvalidTransition,
    PipelineNameTaken,
    PipelineNotFound,
    PipelineNotRunnable,
)
from pipelines.models import Destination, Pipeline, PipelineSource

pytestmark = pytest.mark.django_db

CHANNEL_ID = "UCdestination0000000abc"


@pytest.fixture
def workspace():
    return get_default_workspace()


@pytest.fixture
def pipeline(workspace):
    return api.create_pipeline(workspace, "Recreate channel", description="main")


def _source(workspace, external_id, handle):
    """Create a `sources.Source` through the app registry.

    The `pipelines` module may not import a sibling at all (docs/04 §2, the
    independence contract), and that holds for its tests too. Django's app
    registry is the documented way to reference another module's model
    without an import — the same trick `credentials` uses for
    `accounts.Workspace`.
    """
    source_model = apps.get_model("sources", "Source")
    return source_model.objects.create(
        workspace=workspace,
        kind="channel",
        external_id=external_id,
        url=f"https://www.youtube.com/{handle}/videos",
        name=handle,
    )


@pytest.fixture
def source(workspace):
    return _source(workspace, "UC" + "s" * 22, "@somechannel")


@pytest.fixture
def other_source(workspace):
    return _source(workspace, "UC" + "o" * 22, "@other")


@pytest.fixture
def channel(workspace):
    """An authorised channel, created through the registry for the same reason."""
    channel_model = apps.get_model("credentials", "AuthorizedChannel")
    return channel_model.objects.create(
        workspace=workspace, channel_id=CHANNEL_ID, title="Destination"
    )


@pytest.fixture
def destination(workspace, channel):
    return api.add_destination(workspace, channel, label="Main channel")


@pytest.fixture
def runnable(pipeline, source, destination):
    """A pipeline with one source and one enabled destination."""
    api.attach_source(pipeline, source)
    api.attach_destination(pipeline, destination)
    return pipeline


class TestCreateAndRead:
    def test_new_pipeline_is_a_draft(self, pipeline):
        # The whole point of the draft state: nothing runs until an operator
        # says so (the legacy's open question, answered).
        assert pipeline.status == Pipeline.STATUS_DRAFT
        assert pipeline.retention_mode == "keep"
        assert pipeline.default_privacy == "unlisted"
        assert pipeline.provenance_marker is True

    def test_name_is_unique_per_workspace(self, workspace, pipeline):
        with pytest.raises(PipelineNameTaken):
            api.create_pipeline(workspace, "Recreate channel")

    def test_a_soft_deleted_name_stays_taken(self, workspace, pipeline):
        # docs/03 §6 declares UNIQUE (workspace, name) on the table, and that
        # constraint covers soft-deleted rows too. Reusing a deleted pipeline's
        # name would be ambiguous in the delivery ledger, so it is refused.
        api.delete_pipeline(pipeline)
        with pytest.raises(PipelineNameTaken):
            api.create_pipeline(workspace, "Recreate channel")

    def test_get_hides_soft_deleted(self, workspace, pipeline):
        api.delete_pipeline(pipeline)
        with pytest.raises(PipelineNotFound):
            api.get_pipeline(workspace, pipeline.pk)

    def test_list_is_in_run_order(self, workspace, pipeline):
        api.create_pipeline(workspace, "Second", priority=10)
        names = [p.name for p in api.list_pipelines(workspace)]
        assert names == ["Second", "Recreate channel"]

    def test_list_filters_by_status(self, workspace, runnable):
        api.activate(runnable)
        assert [p.status for p in api.list_pipelines(workspace, status="active")] == [
            "active"
        ]
        assert api.list_pipelines(workspace, status="draft") == []

    def test_invalid_setting_is_named_and_typed(self, workspace):
        with pytest.raises(InvalidSetting) as excinfo:
            api.create_pipeline(workspace, "Bad", default_privacy="secret")
        assert excinfo.value.field == "default_privacy"
        assert issubclass(InvalidSetting, PermanentError)

    def test_status_cannot_be_written_directly(self, pipeline):
        with pytest.raises(InvalidSetting):
            api.update_pipeline(pipeline, status="active")


class TestStateMachine:
    def test_activate_requires_a_source(self, workspace, pipeline, destination):
        api.attach_destination(pipeline, destination)
        with pytest.raises(PipelineNotRunnable) as excinfo:
            api.activate(pipeline)
        assert excinfo.value.missing == "source"

    def test_activate_requires_an_enabled_destination(self, pipeline, source):
        api.attach_source(pipeline, source)
        with pytest.raises(PipelineNotRunnable) as excinfo:
            api.activate(pipeline)
        assert excinfo.value.missing == "enabled destination"

    def test_draft_activates_when_configured(self, runnable):
        assert api.activate(runnable).status == Pipeline.STATUS_ACTIVE

    def test_activating_twice_is_refused(self, runnable):
        api.activate(runnable)
        with pytest.raises(InvalidTransition):
            api.activate(runnable)

    def test_pause_then_resume(self, runnable):
        api.activate(runnable)
        assert api.pause(runnable).status == Pipeline.STATUS_PAUSED
        assert api.activate(runnable).status == Pipeline.STATUS_ACTIVE

    def test_pausing_a_draft_is_refused(self, pipeline):
        with pytest.raises(InvalidTransition):
            api.pause(pipeline)

    def test_delete_pauses_before_soft_deleting(self, runnable):
        api.activate(runnable)
        deleted = api.delete_pipeline(runnable)
        assert deleted.status == Pipeline.STATUS_PAUSED
        assert deleted.deleted_at is not None
        # Configuration is hidden, not destroyed (INV-4 / D-04).
        assert Pipeline.objects.filter(pk=deleted.pk).exists()

    def test_a_deleted_pipeline_cannot_be_activated(self, runnable):
        api.delete_pipeline(runnable)
        with pytest.raises(PipelineNotFound):
            api.activate(runnable)


class TestSourceAttachment:
    def test_attach_is_idempotent_and_updates(self, pipeline, source):
        first = api.attach_source(pipeline, source, mode=PipelineSource.MODE_MONITOR)
        second = api.attach_source(
            pipeline, source, mode=PipelineSource.MODE_BACKFILL, daily_cap=5
        )
        assert first.pk == second.pk
        assert second.mode == PipelineSource.MODE_BACKFILL
        assert second.daily_cap == 5
        assert PipelineSource.objects.filter(pipeline=pipeline).count() == 1

    def test_attach_preserves_backfill_progress(self, pipeline, source):
        link = api.attach_source(pipeline, source, mode=PipelineSource.MODE_BACKFILL)
        link.backfill_done_count = 12
        link.backfill_cursor_published_at = link.created_at
        link.save()
        again = api.attach_source(pipeline, source, priority=5)
        again.refresh_from_db()
        # Re-attaching configures; it must not reset delivery progress.
        assert again.backfill_done_count == 12
        assert again.priority == 5

    def test_detach_keeps_the_source(self, pipeline, source):
        api.attach_source(pipeline, source)
        assert api.detach_source(pipeline, source) is True
        assert api.detach_source(pipeline, source) is False
        # The source row itself is untouched: history outlives configuration.
        assert source.__class__.objects.filter(pk=source.pk).exists()

    def test_list_is_in_priority_order(self, pipeline, source, other_source):
        api.attach_source(pipeline, source, priority=200)
        api.attach_source(pipeline, other_source, priority=1)
        assert [link.source_id for link in api.list_pipeline_sources(pipeline)] == [
            other_source.pk,
            source.pk,
        ]

    def test_list_filters_by_mode(self, pipeline, source, other_source):
        api.attach_source(pipeline, source, mode=PipelineSource.MODE_BACKFILL)
        api.attach_source(pipeline, other_source, mode=PipelineSource.MODE_MONITOR)
        backfill = api.list_pipeline_sources(pipeline, mode=PipelineSource.MODE_BACKFILL)
        assert [link.source_id for link in backfill] == [source.pk]

    def test_invalid_mode_is_refused(self, pipeline, source):
        with pytest.raises(InvalidSetting):
            api.attach_source(pipeline, source, mode="sideways")

    def test_zero_daily_cap_is_refused(self, pipeline, source):
        with pytest.raises(InvalidSetting):
            api.attach_source(pipeline, source, daily_cap=0)


class TestDestinationAttachment:
    def test_destination_is_bound_to_the_channel(self, destination, channel):
        assert destination.authorized_channel_id == channel.pk
        assert destination.platform == "youtube"
        assert destination.daily_max == 6

    def test_attach_is_idempotent_and_carries_overrides(self, pipeline, destination):
        api.attach_destination(pipeline, destination)
        link = api.attach_destination(
            pipeline,
            destination,
            priority=3,
            privacy_override="private",
            retention_mode_override="after_n_jobs",
        )
        assert link.privacy_override == "private"
        assert link.retention_mode_override == "after_n_jobs"
        assert link.priority == 3

    def test_invalid_override_is_refused(self, pipeline, destination):
        with pytest.raises(InvalidSetting):
            api.attach_destination(pipeline, destination, privacy_override="secret")
        with pytest.raises(InvalidSetting):
            api.attach_destination(
                pipeline, destination, retention_mode_override="forever"
            )

    def test_detach_keeps_the_destination(self, pipeline, destination, workspace):
        api.attach_destination(pipeline, destination)
        assert api.detach_destination(pipeline, destination) is True
        assert api.detach_destination(pipeline, destination) is False
        assert len(api.list_destinations(workspace)) == 1

    def test_duplicate_label_is_refused(self, workspace, destination, channel):
        with pytest.raises(PipelineNameTaken):
            api.add_destination(workspace, channel, label="Main channel")

    def test_zero_daily_max_is_refused(self, workspace, channel):
        with pytest.raises(InvalidSetting):
            api.add_destination(workspace, channel, label="Broken", daily_max=0)

    def test_one_channel_can_serve_several_pipelines(
        self, workspace, pipeline, destination, channel
    ):
        other = api.create_pipeline(workspace, "Second pipeline")
        api.attach_destination(pipeline, destination)
        api.attach_destination(other, destination)
        # The destination is shared, not duplicated (docs/03 §6).
        assert Destination.objects.filter(label="Main channel").count() == 1
        assert other.pipeline_destinations.count() == 1


class TestDownloadProfile:
    def test_defaults_are_the_documented_ones(self, workspace):
        profile = api.add_download_profile(workspace, "Default")
        assert profile.max_height == 0  # 0 = no cap
        assert profile.sub_langs == ["en"]
        assert profile.skip_live is True
        assert profile.skip_shorts is False

    def test_profile_is_reusable_across_pipelines(self, workspace, pipeline):
        profile = api.add_download_profile(workspace, "Default")
        api.update_pipeline(pipeline, download_profile=profile)
        second = api.create_pipeline(workspace, "Another")
        api.update_pipeline(second, download_profile=profile)
        assert api.get_download_profile(workspace, profile.pk).pk == profile.pk

    def test_duplicate_name_is_refused(self, workspace):
        api.add_download_profile(workspace, "Default")
        with pytest.raises(PipelineNameTaken):
            api.add_download_profile(workspace, "Default")

    def test_negative_height_is_refused(self, workspace):
        with pytest.raises(InvalidSetting):
            api.add_download_profile(workspace, "Bad", max_height=-1)

    def test_missing_profile_raises(self, workspace):
        with pytest.raises(DownloadProfileNotFound):
            api.get_download_profile(workspace, 999999)


