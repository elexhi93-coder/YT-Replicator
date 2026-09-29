"""
ops.models — the operational record (docs/03 §10, Group 8).

Two tables that answer questions nothing else can:

* **`worker_heartbeat`** makes a *silently dead* worker visible. Without it, a
  dead worker is only inferable from a queue that stopped moving — and by then
  nobody knows whether it stopped because the worker died or because there was
  no work. One row per worker, upserted on every beat.
* **`audit_event`** is the trail of who did what. `workspace_id` is
  `ON DELETE SET NULL` so the trail outlives the workspace it describes: an
  audit log that disappears with its subject is not an audit log.

`detail` is `jsonb` on purpose — it is the one genuinely schema-less payload in
the system, and an audit entry has to be able to record whatever was true at the
time rather than whatever the schema later decided.
"""

from django.db import models

HEARTBEAT_STATUSES = [
    ("idle", "Idle"),
    ("busy", "Busy"),
    ("error", "Error"),
    ("stopped", "Stopped"),
]

#: A worker silent for longer than this is shown as stale. Three missed beats:
#: long enough to survive a slow job, short enough to notice a dead process.
DEFAULT_STALE_SECONDS = 180


class WorkerHeartbeat(models.Model):
    """One row per worker process, replaced on every beat."""

    worker_id = models.TextField(primary_key=True)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="worker_heartbeats",
    )
    kind = models.TextField(default="")
    status = models.TextField(choices=HEARTBEAT_STATUSES, default="idle")
    detail = models.TextField(default="")
    current_job = models.ForeignKey(
        "jobs.Job",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="worker_heartbeats",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_beat_at = models.DateTimeField(auto_now=True)
    host = models.TextField(default="")
    pid = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "worker_heartbeat"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["idle", "busy", "error", "stopped"]),
                name="ck_worker_heartbeat_status",
            )
        ]
        indexes = [
            models.Index(fields=["last_beat_at"], name="worker_heartbeat_stale_idx")
        ]

    def __str__(self) -> str:
        return f"{self.worker_id} ({self.status})"


class AuditEvent(models.Model):
    """Append-only: who did what, to which entity, and when."""

    workspace = models.ForeignKey(
        "accounts.Workspace",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    actor = models.TextField(default="system")
    entity = models.TextField()
    entity_id = models.TextField(default="")
    action = models.TextField()
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_event"
        indexes = [
            models.Index(fields=["-created_at"], name="audit_event_recent_idx"),
            models.Index(
                fields=["entity", "entity_id"], name="audit_event_entity_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.actor} {self.action} {self.entity}:{self.entity_id}"
