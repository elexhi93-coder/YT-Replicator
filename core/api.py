from __future__ import annotations

"""
core.api — Public Interface Contract for the Core Module.

All cross-module communication touching the core module must import ONLY from core.api.
"""

from core.clock import (
    PACIFIC_TZ,
    next_quota_reset_utc,
    now_pacific,
    now_utc,
    quota_day_string,
)
from core.exceptions import (
    AuthExpiredError,
    BotChallengeRequiredError,
    PathTraversalSecurityError,
    PermanentError,
    QuotaExhaustedError,
    ReplicatorError,
    SSRFSecurityError,
    TransientError,
)
from core.logging import StructuredLoggerAdapter, get_logger
from core.security import resolve_safe_path
from core.validators import extract_video_id, validate_youtube_url

__all__ = [
    "ReplicatorError",
    "TransientError",
    "PermanentError",
    "QuotaExhaustedError",
    "AuthExpiredError",
    "BotChallengeRequiredError",
    "PathTraversalSecurityError",
    "SSRFSecurityError",
    "PACIFIC_TZ",
    "now_utc",
    "now_pacific",
    "next_quota_reset_utc",
    "quota_day_string",
    "resolve_safe_path",
    "validate_youtube_url",
    "extract_video_id",
    "get_logger",
    "StructuredLoggerAdapter",
]
