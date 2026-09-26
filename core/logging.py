from __future__ import annotations

"""
YT-Replicator — Structured Logger.

Provides a unified logger wrapper with support for structured context
(workspace_id, job_id, video_id, pipeline_id).
"""

import json
import logging
from typing import Any

DEFAULT_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"


class StructuredLoggerAdapter(logging.LoggerAdapter):
    """Adapter that merges extra context into structured log messages."""

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        extra = self.extra or {}
        kw_extra = kwargs.get("extra", {})
        merged = {**extra, **kw_extra}

        if merged:
            context_str = " " + json.dumps(merged, default=str)
            msg = f"{msg}{context_str}"

        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(name: str, **context: Any) -> StructuredLoggerAdapter:
    """Get a structured logger with optional pre-bound context."""
    base_logger = logging.getLogger(f"replicator.{name}")
    if not base_logger.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        base_logger.addHandler(handler)
        base_logger.setLevel(logging.INFO)

    return StructuredLoggerAdapter(base_logger, context)
