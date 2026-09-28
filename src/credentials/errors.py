from __future__ import annotations

"""
credentials.errors — typed errors for the credentials module (docs/04 §5).

Every module raises its own typed errors, never a bare `Exception`: the caller
(`jobs`, `worker`) decides whether a failure is transient or permanent, and that
decision is what makes the retry policy expressible at all.

Classification (docs/04 §7.1 catches `TransientError`, then `PermanentError`):

* `CredentialError` → `PermanentError`: bad configuration, no retry.
* `AuthRevoked` / `TokenMissing` also inherit Pillar 0 §8's `PermanentAuthError`,
  which hangs directly off the base — without the extra parent the worker's
  `except PermanentError` clause would not catch them.
* `TokenRefreshFailed` → `TransientError`: a 5xx or a dropped connection is
  worth a retry at the next backoff step.
"""

from core.api import PermanentAuthError, PermanentError, TransientError


class CredentialError(PermanentError):
    """Base for credentials failures the operator must fix."""

    default_code = "credential_error"


class ClientNotFound(CredentialError):
    """No `google_client` row matches the lookup."""

    default_code = "client_not_found"


class ChannelNotFound(CredentialError):
    """No `authorized_channel` row matches the lookup."""

    default_code = "channel_not_found"


class OAuthStateInvalid(CredentialError):
    """The OAuth `state` is missing, tampered with, or older than its window."""

    default_code = "oauth_state_invalid"


class OAuthExchangeRejected(CredentialError):
    """Google rejected the authorization code (expired, replayed, wrong client)."""

    default_code = "oauth_exchange_rejected"


class TokenMissing(CredentialError, PermanentAuthError):
    """The channel has no usable refresh token — the operator must re-connect it."""

    default_code = "token_missing"


class AuthRevoked(CredentialError, PermanentAuthError):
    """Google returned `invalid_grant`: the refresh token is dead. Never retried."""

    default_code = "auth_revoked"


class TokenRefreshFailed(TransientError):
    """Refreshing was attempted and failed for a retryable reason (5xx, network)."""

    default_code = "token_refresh_failed"
