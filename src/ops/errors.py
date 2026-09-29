from __future__ import annotations

"""ops.errors — typed errors for the operations module (docs/04 §5).

Both are *refusals*, not faults: they stop a destructive or unsafe action
before it happens, which is the only moment at which the stop is worth
anything.
"""

from core.api import PermanentError


class OpsError(PermanentError):
    """Base for operational refusals."""

    default_code = "ops_error"


class BackupNotConfirmed(OpsError):
    """A destructive action was attempted without a backup (F-54)."""

    default_code = "backup_not_confirmed"


class LogUnreadable(OpsError):
    """The requested log file does not exist or cannot be read."""

    default_code = "log_unreadable"


__all__ = ["BackupNotConfirmed", "LogUnreadable", "OpsError"]
