"""U15 tests — the audit trail, worker heartbeats, log tail, and the backup rule.

The property that matters throughout is **honesty about what is visible and
what is destroyed**: a dead worker must be *visible* rather than inferred, an
audit entry must survive its subject, and a purge must refuse rather than hope
the operator remembered to take a backup.
"""

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from django.apps import apps
from ops import api
from ops.errors import BackupNotConfirmed, LogUnreadable

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace():
    from accounts.api import get_default_workspace

    return get_default_workspace()


class TestAudit:
    def test_an_action_is_recorded_with_its_detail(self, workspace):
        event = api.audit(
            workspace, "pipeline", "created", entity_id="7",
            detail={"name": "P"}, actor="operator",
        )
        assert event.actor == "operator"
        assert event.entity == "pipeline"
        assert event.detail == {"name": "P"}

    def test_the_trail_reads_newest_first(self, workspace):
        api.audit(workspace, "job", "a")
        api.audit(workspace, "job", "b")
        assert [e.action for e in api.list_audit(workspace)] == ["b", "a"]

    def test_the_trail_can_be_filtered_to_one_subject(self, workspace):
        api.audit(workspace, "job", "a", entity_id="1")
        api.audit(workspace, "job", "a", entity_id="2")
        found = api.list_audit(workspace, entity="job", entity_id="2")
        assert [e.entity_id for e in found] == ["2"]

    def test_the_trail_outlives_its_workspace(self, workspace):
        # SET NULL, not CASCADE: an audit log that disappears with its subject
        # is not an audit log.
        AuditEvent = apps.get_model("ops", "AuditEvent")
        api.audit(workspace, "job", "created")
        workspace.delete()
        assert AuditEvent.objects.count() == 1
        assert AuditEvent.objects.first().workspace_id is None

    def test_an_empty_detail_is_still_valid(self, workspace):
        assert api.audit(workspace, "job", "x").detail == {}


class TestHeartbeats:
    def test_a_beat_creates_the_row(self, workspace):
        row = api.heartbeat("w1", "busy", workspace=workspace, detail="job 7")
        assert row.worker_id == "w1"
        assert row.status == "busy"
        assert row.detail == "job 7"

    def test_beating_again_updates_rather_than_duplicates(self, workspace):
        api.heartbeat("w1", "busy", workspace=workspace)
        row = api.heartbeat("w1", "idle", workspace=workspace)
        assert apps.get_model("ops", "WorkerHeartbeat").objects.count() == 1
        assert row.status == "idle"

    def test_a_silent_worker_becomes_visible(self, workspace):
        row = api.heartbeat("w1", "busy", workspace=workspace)
        Heartbeat = apps.get_model("ops", "WorkerHeartbeat")
        Heartbeat.objects.filter(pk="w1").update(
            last_beat_at=row.last_beat_at
            - timedelta(seconds=api.DEFAULT_STALE_SECONDS + 1)
        )
        assert [w.worker_id for w in api.stale_workers()] == ["w1"]
        assert api.worker_status("w1") == "stale"

    def test_a_live_worker_is_not_stale(self, workspace):
        api.heartbeat("w1", "busy", workspace=workspace)
        assert api.stale_workers() == []
        assert api.worker_status("w1") == "alive"

    def test_a_clean_shutdown_is_distinguishable_from_a_crash(self, workspace):
        api.heartbeat("w1", "stopped", workspace=workspace)
        # "finished" and "vanished" are different operator problems.
        assert api.worker_status("w1") == "stopped"

    def test_an_unknown_worker_is_unknown_not_dead(self, workspace):
        assert api.worker_status("never-ran") == "unknown"

    def test_the_current_job_is_remembered(self, workspace):
        Job = apps.get_model("jobs", "Job")
        Pipeline = apps.get_model("pipelines", "Pipeline")
        pipeline = Pipeline.objects.create(workspace=workspace, name="P")
        job = Job.objects.create(
            workspace=workspace, pipeline=pipeline, source_video_id="v1"
        )
        row = api.heartbeat("w1", "busy", workspace=workspace, current_job=job)
        assert row.current_job_id == job.pk

    def test_the_host_and_pid_are_recorded(self, workspace):
        row = api.heartbeat("w1", "idle", workspace=workspace, host="box-1", pid=4321)
        assert row.host == "box-1" and row.pid == 4321


class TestLogTail:
    def test_the_last_lines_are_returned_newest_last(self):
        path = Path(tempfile.mkdtemp()) / "app.log"
        path.write_text("\n".join(f"line {i}" for i in range(50)), encoding="utf-8")
        tail = api.tail_logs(path, lines=5)
        assert len(tail) == 5
        assert tail[-1] == "line 49"

    def test_a_missing_log_is_an_error_not_an_empty_page(self):
        with pytest.raises(LogUnreadable):
            api.tail_logs(Path(tempfile.mkdtemp()) / "nope.log")

    def test_a_short_file_is_returned_whole(self):
        path = Path(tempfile.mkdtemp()) / "app.log"
        path.write_text("only line", encoding="utf-8")
        assert api.tail_logs(path, lines=200) == ["only line"]

    def test_undecodable_bytes_do_not_crash_the_read(self):
        path = Path(tempfile.mkdtemp()) / "app.log"
        path.write_bytes(b"good line\n\xff\xfe binary junk\n")
        assert any("good line" in line for line in api.tail_logs(path))


class TestTheBackupRule:
    def test_a_destructive_action_is_refused_without_a_backup(self):
        # F-54 was a comment in the legacy. Here it is a refusal.
        with pytest.raises(BackupNotConfirmed):
            api.require_backup("purge runtime data", confirmed=False)

    def test_the_reference_is_returned_when_confirmed(self):
        assert api.require_backup(
            "purge", confirmed=True, backup_ref="/backups/2026-09-28.dump"
        ) == "/backups/2026-09-28.dump"

    def test_confirmation_without_a_reference_still_says_so(self):
        # Better a recorded gap than a silent one.
        assert "confirmed-without-reference" in api.require_backup(
            "purge", confirmed=True
        )