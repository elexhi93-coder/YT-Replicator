from __future__ import annotations

"""youtube.errors — typed errors for the destination platform (docs/04 §5).

Every Google failure is translated here into the project's vocabulary, and the
translation is the contract: a 429 is transient and will be retried, a 403
`quotaExceeded` is transient but *also* recorded against the budget, a 404 or a
rejected privacy setting is permanent, and a revoked token is permanent because
no retry can bring it back (docs/01 D-23 class of failure: a channel that is
silently uploading to the wrong place).

`QuotaExhausted` is an alias of `QuotaExhaustedError`, which `core` classifies
as **transient**: the quota returns at Pacific midnight, so the right response
is to reschedule, not to fail the video (Pillar 0 §8, core CONTRACT §2.1).
"""

from core.api import (
    ItemUnavailable,
    PermanentAuthError,
    PermanentError,
    QuotaExhaustedError,
    RateLimitExceeded,
    TransientError,
)


class YouTubeError(PermanentError):
    """Base for platform failures the operator must resolve."""

    default_code = "youtube_error"


class UploadRejected(YouTubeError):
    """The platform refused the upload for a reason retrying will not fix.

    Covers a 400 (bad request, an invalid privacy status) and a 403 that is
    not a quota problem. The video is failed, not requeued.
    """

    default_code = "upload_rejected"


class UploadNotFound(YouTubeError, ItemUnavailable):
    """The upload session or the video id does not exist (404)."""

    default_code = "upload_not_found"


class TokenRevoked(YouTubeError, PermanentAuthError):
    """The channel's authorization was revoked; an owner must reconnect it.

    Permanent on purpose: the legacy's D-23 is a channel uploading to the wrong
    place, and a revoked token that keeps retrying is how that happens.
    """

    default_code = "token_revoked"


class Throttled(RateLimitExceeded):
    """HTTP 429 — slow down. Transient; the worker backs off."""

    default_code = "throttled"


class PlatformUnavailable(TransientError):
    """5xx, a network failure, or a response we could not parse."""

    default_code = "platform_unavailable"


class QuotaExhausted(QuotaExhaustedError):
    """The daily budget is spent. Reschedule for after the Pacific reset."""

    default_code = "quota_exhausted"


__all__ = [
    "PlatformUnavailable",
    "QuotaExhausted",
    "Throttled",
    "TokenRevoked",
    "UploadNotFound",
    "UploadRejected",
    "YouTubeError",
]
