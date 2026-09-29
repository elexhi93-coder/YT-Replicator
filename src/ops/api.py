from __future__ import annotations

from core.api import now_utc
from ops.errors import BackupNotConfirmed, LogUnreadable
from ops.models import DEFAULT_STALE_SECONDS, AuditEvent, WorkerHeartbeat

__all__ = [
    "DEFAULT_STALE_SECONDS",
    "audit",
    "heartbeat",
    "list_audit",
    "list_heartbeats",
    "require_backup",
    "stale_workers",
    "tail_logs",
    "worker_status",
]


def audit(
    workspace,
    entity: str,
    action: str,
    *,
    entity_id: str = "",
    detail: dict | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record something an operator may later need to explain.

    Append-only and never updated: an audit entry that could be edited is a
    suggestion, not a record.
    """
    return AuditEvent.objects.create(
        workspace=workspace,
        actor=actor,
        entity=entity,
        entity_id=str(entity_id),
        action=action,
        detail=detail or {},
    )


def list_audit(
    workspace=None, *, entity: str | None = None, entity_id: str | None = None, limit: int = 100
) -> list[AuditEvent]:
    """Newest first. `workspace=None` reads the installation-wide trail."""
    queryset = AuditEvent.objects.all()
    if workspace is not None:
        queryset = queryset.filter(workspace=workspace)
    if entity is not None:
        queryset = queryset.filter(entity=entity)
    if entity_id is not None:
        queryset = queryset.filter(entity_id=str(entity_id))
    return list(queryset.order_by("-created_at", "-id")[: max(1, limit)])


def heartbeat(
    worker_id: str,
    status: str = "idle",
    *,
    workspace=None,
    detail: str = "",
    current_job=None,
    kind: str = "",
    host: str = "",
    pid: int | None = None,
) -> WorkerHeartbeat:
    """Upsert one worker's liveness. Idempotent per `worker_id` by design.

    `status="stopped"` is a courtesy write on a clean shutdown so the dashboard
    can distinguish *finished* from *vanished* without waiting three intervals.
    """
    row, _created = WorkerHeartbeat.objects.update_or_create(
        worker_id=worker_id,
        defaults={
            "workspace": workspace,
            "kind": kind,
            "status": status,
            "detail": detail,
            "current_job": current_job,
            "host": host,
            "pid": pid,
        },
    )
    return row


def list_heartbeats() -> list[WorkerHeartbeat]:
    return list(WorkerHeartbeat.objects.order_by("worker_id"))


def stale_workers(*, now=None, stale_seconds: int = DEFAULT_STALE_SECONDS) -> list[WorkerHeartbeat]:
    """Workers that have gone silent.

    This is the whole point of the table: a dead worker is *visible* rather
    than inferred from a queue that stopped moving.
    """
    moment = now or now_utc()
    cutoff = moment.timestamp() - stale_seconds
    return [row for row in list_heartbeats() if row.last_beat_at.timestamp() < cutoff]


def worker_status(worker_id: str, *, stale_seconds: int = DEFAULT_STALE_SECONDS) -> str:
    """`alive` | `stale` | `stopped` | `unknown` — the four words a UI needs."""
    try:
        row = WorkerHeartbeat.objects.get(worker_id=worker_id)
    except WorkerHeartbeat.DoesNotExist:
        return "unknown"
    if row.status == "stopped":
        return "stopped"
    if row.last_beat_at.timestamp() < (now_utc().timestamp() - stale_seconds):
        return "stale"
    return "alive"


def tail_logs(path, *, lines: int = 200) -> list[str]:
    """The last `lines` lines of a log file, newest last.

    Reads the file rather than the logging handlers, so it works for a log
    written by a process that is no longer running — which is exactly when an
    operator wants to read it.
    """
    from pathlib import Path

    target = Path(path)
    if not target.is_file():
        raise LogUnreadable(f"No log file at {target}.")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise LogUnreadable(f"Cannot read {target}: {exc}") from exc
    return content.splitlines()[-max(1, lines):]


def require_backup(action: str, *, confirmed: bool, backup_ref: str = "") -> str:
    """The F-54 rule, enforced rather than documented.

    The legacy's convention was "copy the database before running any one-shot
    script" — a comment nobody reads. Here a destructive maintenance action
    **refuses to run** until the operator states that a backup exists, and the
    reference to it is kept so the audit trail can say where.
    """
    if not confirmed:
        raise BackupNotConfirmed(
            f"Refusing to {action}: take a backup first and pass "
            "backup_confirmed=True (F-54)."
        )
    return backup_ref or "confirmed-without-reference"
