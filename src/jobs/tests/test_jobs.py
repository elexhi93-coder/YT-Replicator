"""U08 tests — the job queue: dedup, atomic claim, classification, backoff.

The properties under test are the ones the legacy got wrong (P11, D-13): a job
must not be handed to two workers, a duplicate must not be queued twice, a
transient failure must be retryable and a permanent one must not, and a worker
that dies must not strand its job.

No test imports a sibling module — the pipeline and source rows they need are
created through Django's app registry, the boundary this module works under.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.apps import apps
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.api import get_default_workspace
from core.api import PermanentError, TransientError
from jobs import api
from jobs.errors import (
    InvalidJobSetting,
    InvalidJobTransition,
    JobNotFound,
)
from jobs.models import Job

pytestmark = pytest.mark.django_db

VIDEO_A = "aaaaaaaaaaa"
VIDEO_B = "bbbbbbbbbbb"


class Flaky(TransientError):
    """A transient failure, the kind a worker should retry."""

    default_code = "flaky"


class Fatal(PermanentError):
    """A permanent failure — retrying cannot help."""

    default_code = "fatal"


@pytest.fixture
def workspace():
    return get_default_workspace()


@pytest.fixture
def pipeline(workspace):
    pipeline_model = apps.get_model("pipelines", "Pipeline")
    return pipeline_model.objects.create(workspace=workspace, name="Recreate")


@pytest.fixture
def source(workspace):
    source_model = apps.get_model("sources", "Source")
    return source_model.objects.create(
        workspace=workspace,
        kind="channel",
        external_id="UC" + "s" * 22,
        url="https://www.youtube.com/@some/videos",
    )


@pytest.fixture
def job(workspace, pipeline):
    return api.enqueue(workspace, pipeline, VIDEO_A)


class TestEnqueueDedup:
    def test_enqueue_creates_a_queued_job(self, job, pipeline):
        assert job.status == "queued"
        assert job.priority == pipeline.priority
        assert job.attempt_count == 0
        assert job.source_video_id == VIDEO_A

    def test_duplicate_returns_the_live_job(self, workspace, pipeline, job):
        # The dedup the legacy designed and never shipped.
        again = api.enqueue(workspace, pipeline, VIDEO_A)
        assert again.pk == job.pk
        assert Job.objects.filter(pipeline=pipeline).count() == 1

    def test_a_different_intent_is_a_different_job(self, workspace, pipeline, job):
        inspect = api.enqueue(workspace, pipeline, VIDEO_A, intent="inspect")
        assert inspect.pk != job.pk
        assert Job.objects.filter(pipeline=pipeline).count() == 2

    def test_a_different_video_is_a_different_job(self, workspace, pipeline, job):
        api.enqueue(workspace, pipeline, VIDEO_B)
        assert Job.objects.filter(pipeline=pipeline).count() == 2

    def test_cancelled_job_frees_the_key_for_a_rerun(self, workspace, pipeline, job):
        api.cancel(job)
        again = api.enqueue(workspace, pipeline, VIDEO_A)
        assert again.pk != job.pk
        assert again.status == "queued"

    def test_skipped_job_frees_the_key_for_a_rerun(self, workspace, pipeline, job):
        api.skip(job, "operator said no")
        again = api.enqueue(workspace, pipeline, VIDEO_A)
        assert again.pk != job.pk

    def test_the_index_is_the_guarantee_not_the_lookup(self, workspace, pipeline, job):
        # Bypass the API: the database itself must refuse a second live job.
        with pytest.raises(IntegrityError), transaction.atomic():
            Job.objects.create(
                workspace=workspace,
                pipeline=pipeline,
                source_video_id=VIDEO_A,
                intent="upload",
            )

    def test_invalid_intent_is_refused(self, workspace, pipeline):
        with pytest.raises(InvalidJobSetting) as excinfo:
            api.enqueue(workspace, pipeline, VIDEO_A, intent="teleport")
        assert excinfo.value.field == "intent"

    def test_enqueue_accepts_a_source(self, workspace, pipeline, source):
        assert api.enqueue(workspace, pipeline, VIDEO_B, source=source).source_id == source.pk


class TestClaim:
    def test_claim_takes_the_queued_job(self, job):
        claimed = api.claim("worker-1")
        assert claimed.pk == job.pk
        assert claimed.status == "claimed"
        assert claimed.claimed_by == "worker-1"
        assert claimed.claim_expires_at is not None
        assert claimed.started_at is not None

    def test_empty_queue_claims_nothing(self, workspace):
        assert api.claim("worker-1") is None

    def test_a_claimed_job_is_not_handed_out_twice(self, job):
        first = api.claim("worker-1")
        assert api.claim("worker-2") is None  # the P11 race, closed
        assert first.status == "claimed"

    def test_claim_is_priority_then_age(self, workspace, pipeline):
        pipeline.priority = 200
        pipeline.save()
        low = api.enqueue(workspace, pipeline, VIDEO_A)
        high_model = apps.get_model("pipelines", "Pipeline")
        urgent = high_model.objects.create(
            workspace=workspace, name="Urgent", priority=1
        )
        first = api.enqueue(workspace, urgent, VIDEO_B, priority=1)
        assert api.claim("worker-1").pk == first.pk
        assert api.claim("worker-2").pk == low.pk

    def test_a_backing_off_job_is_not_claimable(self, job):
        api.claim("worker-1")
        api.fail(job, Flaky("throttled"))
        # The backoff is a timestamp, so the queue simply does not offer it yet.
        assert api.claim("worker-2") is None
        job.refresh_from_db()
        assert job.status == "queued"

    def test_a_backed_off_job_returns_after_its_delay(self, job):
        api.claim("worker-1")
        api.fail(job, Flaky("throttled"))
        job.refresh_from_db()
        job.claim_expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["claim_expires_at"])
        assert api.claim("worker-2").pk == job.pk

    def test_worker_name_is_required(self, job):
        with pytest.raises(InvalidJobSetting):
            api.claim("")


class TestSuccess:
    def test_succeed_finishes_the_job(self, job):
        api.claim("worker-1")
        done = api.succeed(job)
        assert done.status == "uploaded"
        assert done.finished_at is not None
        assert done.claim_expires_at is None

    def test_succeeding_clears_a_previous_error(self, job):
        api.claim("worker-1")
        api.fail(job, Flaky("blip"))
        job.refresh_from_db()
        done = api.succeed(job)
        assert done.error_code == "" and done.error_message == ""

    def test_a_finished_job_cannot_finish_again(self, job):
        api.claim("worker-1")
        api.succeed(job)
        with pytest.raises(InvalidJobTransition):
            api.succeed(job)


class TestFailureClassification:
    def test_transient_requeues_with_backoff(self, job):
        api.claim("worker-1")
        failed = api.fail(job, Flaky("throttled"))
        assert failed.status == "queued"
        assert failed.attempt_count == 1
        assert failed.claim_expires_at > timezone.now()
        assert failed.error_code == "flaky"
        assert failed.error_message == "throttled"

    def test_permanent_stops_the_job(self, job):
        api.claim("worker-1")
        failed = api.fail(job, Fatal("video is gone"))
        assert failed.status == "failed_permanent"
        assert failed.finished_at is not None
        assert failed.attempt_count == 0  # no retry was ever scheduled

    def test_retry_false_overrides_the_classification(self, job):
        api.claim("worker-1")
        failed = api.fail(job, Flaky("throttled"), retry=False)
        assert failed.status == "failed_permanent"

    def test_a_permanent_job_is_not_claimable(self, job):
        api.claim("worker-1")
        api.fail(job, Fatal("gone"))
        assert api.claim("worker-2") is None

    def test_attempts_are_capped(self, workspace, pipeline):
        # Without a ceiling, a permanently broken video would be retried
        # forever, spending quota on every attempt.
        exhausted = api.enqueue(workspace, pipeline, VIDEO_A)
        exhausted.attempt_count = api.MAX_ATTEMPTS - 1
        exhausted.save(update_fields=["attempt_count"])
        api.claim("worker-1")
        failed = api.fail(exhausted, Flaky("still throttled"))
        assert failed.status == "failed_permanent"

    def test_backoff_grows_and_is_capped(self):
        first = api.backoff_for(1)
        second = api.backoff_for(2)
        assert second > first
        assert api.backoff_for(99) == timedelta(seconds=3600)

    def test_failing_a_finished_job_is_refused(self, job):
        api.claim("worker-1")
        api.succeed(job)
        with pytest.raises(InvalidJobTransition):
            api.fail(job, Fatal("too late"))


class TestRecovery:
    def test_an_expired_claim_is_recovered(self, job):
        api.claim("dead-worker")
        # The lease is 15 minutes, so recovery is exercised by moving the
        # clock past it rather than by sleeping.
        later = timezone.now() + timedelta(hours=1)
        assert api.requeue_stale(now=later) == 1
        job.refresh_from_db()
        assert job.status == "queued"
        assert job.claimed_by == ""
        assert job.claim_expires_at is None

    def test_a_live_claim_is_left_alone(self, job):
        api.claim("worker-1", lease_minutes=180)
        # An hour later the 3-hour lease still holds: stealing work from a
        # healthy worker would be worse than waiting.
        assert api.requeue_stale(now=timezone.now() + timedelta(hours=1)) == 0
        job.refresh_from_db()
        assert job.status == "claimed"

    def test_recovery_is_idempotent(self, job):
        api.claim("dead-worker")
        later = timezone.now() + timedelta(hours=1)
        assert api.requeue_stale(now=later) == 1
        assert api.requeue_stale(now=later) == 0

    def test_a_recovered_job_can_be_claimed_again(self, job):
        api.claim("dead-worker")
        api.requeue_stale(now=timezone.now() + timedelta(hours=1))
        assert api.claim("worker-2").pk == job.pk


class TestSkipAndCancel:
    def test_skip_records_a_readable_reason(self, job):
        skipped = api.skip(job, "already on the destination")
        assert skipped.status == "skipped"
        assert skipped.skip_reason == "already on the destination"

    def test_skip_requires_a_reason(self, job):
        # The legacy stored `videos_seen` in JSON nobody queried; a skip with
        # no reason is the same defect wearing a different hat.
        with pytest.raises(InvalidJobSetting):
            api.skip(job, "")

    def test_cancel_stops_a_queued_job(self, job):
        assert api.cancel(job).status == "cancelled"

    def test_cancelling_a_finished_job_is_refused(self, job):
        api.claim("worker-1")
        api.succeed(job)
        with pytest.raises(InvalidJobTransition):
            api.cancel(job)


class TestListing:
    def test_list_is_in_queue_order(self, workspace, pipeline):
        api.enqueue(workspace, pipeline, VIDEO_B, priority=50)
        api.enqueue(workspace, pipeline, VIDEO_A, priority=10)
        assert [j.priority for j in api.list_jobs(workspace)] == [10, 50]

    def test_list_filters_by_status_and_pipeline(self, workspace, pipeline, job):
        api.claim("worker-1")
        api.succeed(job)
        assert api.list_jobs(workspace, status="uploaded") == [job]
        assert api.list_jobs(workspace, pipeline=pipeline, status="queued") == []

    def test_get_missing_job_raises(self):
        with pytest.raises(JobNotFound):
            api.get_job(999999)

