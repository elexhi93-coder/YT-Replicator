from __future__ import annotations

"""pipelines.errors — typed errors for the pipelines module (docs/04 §5).

Every one of them is permanent: a pipeline misconfiguration is something the
operator must resolve, and no amount of retrying fixes it. `jobs` records the
failure and the UI shows it.
"""

from core.api import PermanentError


class PipelineError(PermanentError):
    """Base for every pipeline configuration failure."""

    default_code = "pipeline_error"


class PipelineNotFound(PipelineError):
    """No pipeline matches the lookup (or it is soft-deleted)."""

    default_code = "pipeline_not_found"


class PipelineNameTaken(PipelineError):
    """Another pipeline in the workspace already uses that name."""

    default_code = "pipeline_name_taken"


class InvalidTransition(PipelineError):
    """A status change the state machine does not allow (docs/02 §4)."""

    default_code = "pipeline_invalid_transition"

    def __init__(self, current: str, requested: str) -> None:
        super().__init__(
            f"Cannot move a pipeline from {current!r} to {requested!r}."
        )
        self.current = current
        self.requested = requested


class PipelineNotRunnable(PipelineError):
    """Activation refused: the pipeline is not fully configured yet.

    This is the guard behind "a half-configured pipeline cannot run" — it is
    why a pipeline is created as a draft and only an operator's explicit
    activation starts work.
    """

    default_code = "pipeline_not_runnable"

    def __init__(self, missing: str) -> None:
        super().__init__(
            f"Pipeline cannot run: it has no enabled {missing} yet."
        )
        self.missing = missing


class DownloadProfileNotFound(PipelineError):
    """No download profile matches the lookup."""

    default_code = "download_profile_not_found"


class InvalidSetting(PipelineError):
    """A value outside the vocabulary the schema CHECK constraints allow."""

    default_code = "pipeline_invalid_setting"

    def __init__(self, field: str, value: object, allowed) -> None:
        super().__init__(
            f"{field}={value!r} is not one of {sorted(allowed)}."
        )
        self.field = field
        self.value = value


__all__ = [
    "DownloadProfileNotFound",
    "InvalidSetting",
    "InvalidTransition",
    "PipelineError",
    "PipelineNameTaken",
    "PipelineNotFound",
    "PipelineNotRunnable",
]
