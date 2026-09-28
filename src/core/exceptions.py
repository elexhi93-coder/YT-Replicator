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

class SecretDecryptionError(PermanentError):
    """Cryptographic decryption failed: corrupt ciphertext, bad tag, or mismatched key."""

    default_code: str = "secret_decryption_error"


class MasterKeyMissingError(PermanentError):
    """PLATFORM_MASTER_KEY environment variable is missing or invalid."""

    default_code: str = "master_key_missing"


# --- Port-boundary errors (Pillar 0 / docs/PILLARS/00.../03_INTERFACE_CONTRACT §8) ---
# Every error crossing a port boundary inherits from PillarError. Retry policy
# (docs/07 U08): jobs retries `TransientError` subclasses with backoff and
# reschedules; everything else marks the job failed. Alias, not a new class,
# so TransientError/PermanentError both satisfy "inherits from PillarError".
PillarError = ReplicatorError


class NetworkError(TransientError):
    """Timeout, connection reset, or 5xx from an external platform."""

    default_code: str = "network_error"


class RateLimitExceeded(TransientError):
    """HTTP 429 / platform throttle; carries retry_after_sec when known."""

    default_code: str = "rate_limit_exceeded"

    def __init__(
        self,
        message: str = "Rate limited by platform",
        retry_after_sec: int | None = None,
        details: dict | None = None,
    ) -> None:
        merged_details = details or {}
        if retry_after_sec is not None:
            merged_details["retry_after_sec"] = retry_after_sec
        super().__init__(message, code=self.default_code, details=merged_details)
        self.retry_after_sec = retry_after_sec


class ResourceTemporarilyUnavailable(TransientError):
    """The target resource exists but is temporarily unavailable."""

    default_code: str = "resource_unavailable"


class SourceUrlRejected(PermanentError):
    """SSRF reject, host not allow-listed, or URL shape unsupported."""

    default_code: str = "source_url_rejected"


class ItemUnavailable(PermanentError):
    """Item deleted, made private, or geo-blocked at the source/destination."""

    default_code: str = "item_unavailable"


class TermsViolation(PermanentError):
    """Platform rejected the content or metadata on terms grounds."""

    default_code: str = "terms_violation"


# Pillar 0 §8 draws QuotaExhausted under PermanentError, but Pillar 0's own
# logic chapter (04_LOGIC_AND_RULES.md) maps GoogleHttpError(403) to
# "QuotaExhaustedError (transient)" and jobs must reschedule work at the
# Pacific reset rather than fail it permanently — so the alias points at the
# transient class. Recorded in CONTRACT.md §2.
QuotaExhausted = QuotaExhaustedError


class PermanentAuthError(ReplicatorError):
    """Credentials revoked or channel gone (Pillar 0 §8: direct child of PillarError).

    Not a `TransientError`: never retried. Also not a `PermanentError` subclass
    by design — the §8 tree hangs it directly off the base; callers classify
    retryability by `isinstance(err, TransientError)`.
    """

    default_code: str = "permanent_auth_error"

