from __future__ import annotations

"""jobs.errors — typed errors for the job engine (docs/04 §5).

The job engine does not raise on a failed *job* — that is data, recorded on
the row, because the worker must survive it. These are the errors for misuse
of the queue itself: an unknown intent, a transition the state machine forbids.
"""

from core.api import PermanentError


class JobError(PermanentError):
    """Base for queue misuse. Never raised for a job that merely failed."""

    default_code = "job_error"


class JobNotFound(JobError):
    """No job matches the lookup."""

    default_code = "job_not_found"


class InvalidJobSetting(JobError):
    """A value outside the schema's CHECK vocabulary (intent, worker, ...)."""

    default_code = "job_invalid_setting"

    def __init__(self, field: str, value: object, allowed) -> None:
        super().__init__(f"{field}={value!r} is not one of {sorted(allowed)}.")
        self.field = field
        self.value = value


class InvalidJobTransition(JobError):
    """A status change the state machine does not allow (docs/02 §4)."""

    default_code = "job_invalid_transition"

    def __init__(self, current: str, requested: str) -> None:
        super().__init__(f"Cannot move a job from {current!r} to {requested!r}.")
        self.current = current
        self.requested = requested


__all__ = [
    "InvalidJobSetting",
    "InvalidJobTransition",
    "JobError",
    "JobNotFound",
]
