from __future__ import annotations

"""
YT-Replicator — Typed Error Hierarchy.

Invariants:
- Every replicator error derives from ReplicatorError.
- Recoverable errors derive from TransientError.
- Fatal errors derive from PermanentError.
"""


class ReplicatorError(Exception):
    """Base class for all domain exceptions in YT-Replicator."""

    default_code: str = "internal_error"

    def __init__(self, message: str, code: str | None = None, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details = details or {}

    def __str__(self) -> str:
        return self.message


class TransientError(ReplicatorError):
    """Temporary failure (e.g. network timeout, rate limit, temporary server error).
    The worker should retry with exponential backoff.
    """

    default_code: str = "transient_error"


class PermanentError(ReplicatorError):
    """Unrecoverable failure (e.g. video deleted, private video, invalid media format).
    The worker should mark the job/attempt as permanently failed.
    """

    default_code: str = "permanent_error"


class QuotaExhaustedError(TransientError):
    """YouTube API quota (10,000 units) exhausted for the day.
    Uploads for this client/destination should pause until the Pacific midnight reset.
    """

    default_code: str = "quota_exhausted"

    def __init__(
        self,
        message: str = "YouTube quota exhausted for today",
        resets_at: str | None = None,
        details: dict | None = None,
    ) -> None:
        merged_details = details or {}
        if resets_at:
            merged_details["resets_at"] = resets_at
        super().__init__(message, code=self.default_code, details=merged_details)
        self.resets_at = resets_at


class AuthExpiredError(PermanentError):
    """OAuth refresh token expired or was revoked.
    Requires manual re-authorization from the user via UI.
    """

    default_code: str = "auth_expired"


class BotChallengeRequiredError(TransientError):
    """YouTube issued a bot challenge (e.g. 'Sign in to confirm you're not a bot').
    Requires updating cookies.txt or PO token on the VPS.
    """

    default_code: str = "bot_challenge_required"


class PathTraversalSecurityError(PermanentError):
    """Attempted path traversal attack outside configured media roots."""

    default_code: str = "path_traversal_violation"


class SSRFSecurityError(PermanentError):
    """Attempted request to a non-whitelisted domain or private IP."""

    default_code: str = "ssrf_violation"
