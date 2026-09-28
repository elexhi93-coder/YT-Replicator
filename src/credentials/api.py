from __future__ import annotations

"""
credentials.api — Public Interface Contract for the Credentials Module (U05).

Owns: `google_client`, `authorized_channel` (docs/03 §4), the OAuth flow, and
the token lifecycle. May import `core.api` and `accounts.api` only (docs/04 §3).

Two rules shape everything here:

1. **Secrets are write-only across this boundary (INV-1).** Nothing returned to
   a caller contains a decrypted client secret or refresh token; only the two
   functions whose job *is* to use them (`client_secret()`, `access_token()`)
   decrypt, and only in memory, for the length of the call.
2. **Tokens are refreshed proactively (Pillar 2 §2.2).** `valid_access_token()`
   is the only way to obtain a usable token, so the "expires in under five
   minutes" case can never be forgotten by a caller.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core import signing
from django.db import transaction

from core.api import decrypt, encrypt, now_utc
from credentials.errors import (
    AuthRevoked,
    ChannelNotFound,
    ClientNotFound,
    OAuthStateInvalid,
    TokenMissing,
)
from credentials.http import HttpClient, UrllibHttpClient
from credentials.models import AuthorizedChannel, GoogleClient
from credentials import oauth

#: `state` lifetime: long enough for a human to click through Google's consent
#: screens, short enough that a leaked URL is useless.
OAUTH_STATE_MAX_AGE_SECONDS = 900
OAUTH_STATE_SALT = "credentials.oauth.state"

DEFAULT_REDIRECT_URI = "http://localhost:8080/credentials/callback"

#: New clients start at the documented default cap (docs/03 §4).
DEFAULT_DAILY_UPLOAD_CAP = 6

#: Placeholder prefix for a channel row created before its canonical id is known.
PENDING_CHANNEL_PREFIX = "pending-"


@dataclass(frozen=True)
class OAuthStart:
    """What the UI needs to send the operator to Google."""

    authorization_url: str
    state: str


def _http(http_client: HttpClient | None) -> HttpClient:
    return http_client if http_client is not None else UrllibHttpClient()


def _dt(value: datetime) -> datetime:
    """Normalize naive datetimes (tests) to aware UTC, as Django stores them."""
    if value.tzinfo is None:
        from django.utils import timezone

        return timezone.make_aware(value, timezone.utc)
    return value


# --- Google clients ---------------------------------------------------------


def add_google_client(
    workspace,
    *,
    label: str,
    client_id: str,
    client_secret: str,
    daily_upload_cap: int = DEFAULT_DAILY_UPLOAD_CAP,
    is_active: bool = True,
) -> GoogleClient:
    """Register a Google Cloud project. The secret is encrypted before insert."""
    if not label.strip():
        raise ValueError("label is required")
    if not client_id.strip():
        raise ValueError("client_id is required")
    if daily_upload_cap < 1:
        raise ValueError("daily_upload_cap must be >= 1")
    return GoogleClient.objects.create(
        workspace=workspace,
        label=label.strip(),
        client_id=client_id.strip(),
        client_secret_enc=encrypt(client_secret).encode("utf-8"),
        daily_upload_cap=daily_upload_cap,
        is_active=is_active,
    )


def update_google_client(
    client: GoogleClient,
    *,
    label: str | None = None,
    client_secret: str | None = None,
    daily_upload_cap: int | None = None,
    is_active: bool | None = None,
) -> GoogleClient:
    """Change a client's mutable fields. `client_id` is immutable by design."""
    if label is not None:
        client.label = label.strip()
    if client_secret is not None:
        client.client_secret_enc = encrypt(client_secret).encode("utf-8")
    if daily_upload_cap is not None:
        if daily_upload_cap < 1:
            raise ValueError("daily_upload_cap must be >= 1")
        client.daily_upload_cap = daily_upload_cap
    if is_active is not None:
        client.is_active = is_active
    client.save()
    return client


def client_secret(client: GoogleClient) -> str:
    """Decrypt a client secret **in memory only** (INV-1: never log the result)."""
    return decrypt(bytes(client.client_secret_enc).decode("utf-8"))


def get_client(workspace, *, label: str | None = None, client_id: str | None = None) -> GoogleClient:
    """Fetch one client by label or client id. Raises `ClientNotFound`."""
    query = GoogleClient.objects.filter(workspace=workspace)
    if label is not None:
        query = query.filter(label=label)
    if client_id is not None:
        query = query.filter(client_id=client_id)
    client = query.first()
    if client is None:
        raise ClientNotFound(
            f"No Google client matches label={label!r} client_id={client_id!r}."
        )
    return client


def list_clients(workspace) -> list[GoogleClient]:
    """All clients of a workspace, stable order for the UI."""
    return list(GoogleClient.objects.filter(workspace=workspace).order_by("label"))


def deactivate_client(client: GoogleClient) -> GoogleClient:
    """Stop using a client without deleting its channels (SET_NULL-style intent)."""
    client.is_active = False
    client.save(update_fields=["is_active", "updated_at"])
    return client


# --- Channels ---------------------------------------------------------------


def bind_channel(
    client: GoogleClient,
    *,
    channel_id: str,
    title: str = "",
    scopes: tuple[str, ...] | list[str] = (),
) -> AuthorizedChannel:
    """Create or update the channel row for `channel_id` (idempotent).

    Re-binding keeps the row and therefore the channel's whole delivery history;
    only the owning client and the display title change.
    """
    if not channel_id.strip():
        raise ValueError("channel_id is required")
    channel, _created = AuthorizedChannel.objects.update_or_create(
        workspace=client.workspace,
        channel_id=channel_id.strip(),
        defaults={
            "google_client": client,
            "title": title or "",
            "scopes": [str(s) for s in scopes],
        },
    )
    return channel


def new_channel(client: GoogleClient, *, title: str = "") -> AuthorizedChannel:
    """Create a channel row whose canonical id is not known yet.

    The operator starts from a Google client, not from a channel id, so the row
    is created with a unique `pending-…` placeholder and `token_state='missing'`.
    `complete_oauth()` replaces the placeholder with the real `UC…` id (and
    merges into an existing row if the channel was already known).
    """
    from uuid import uuid4

    return AuthorizedChannel.objects.create(
        workspace=client.workspace,
        google_client=client,
        channel_id=f"{PENDING_CHANNEL_PREFIX}{uuid4().hex[:12]}",
        title=title,
        token_state=AuthorizedChannel.TOKEN_MISSING,
    )


def _is_pending(channel: AuthorizedChannel) -> bool:
    return not channel.channel_id or channel.channel_id.startswith(PENDING_CHANNEL_PREFIX)


def get_channel(channel_id: str | int, *, workspace=None) -> AuthorizedChannel:
    """Fetch a channel by primary key or canonical id. Raises `ChannelNotFound`."""
    query = AuthorizedChannel.objects.select_related("google_client")
    if workspace is not None:
        query = query.filter(workspace=workspace)
    channel = None
    if isinstance(channel_id, int) or str(channel_id).isdigit():
        channel = query.filter(pk=int(channel_id)).first()
    if channel is None:
        channel = query.filter(channel_id=str(channel_id)).first()
    if channel is None:
        raise ChannelNotFound(f"No authorized channel matches {channel_id!r}.")
    return channel


def list_channels(workspace) -> list[AuthorizedChannel]:
    """All channels of a workspace, ordered by title (Pillar 2 §3)."""
    return list(
        AuthorizedChannel.objects.filter(workspace=workspace)
        .select_related("google_client")
        .order_by("title", "channel_id")
    )


def revoke_channel(channel: AuthorizedChannel, *, reason: str = "") -> AuthorizedChannel:
    """Mark a channel dead and drop its tokens — the operator must re-connect it."""
    channel.token_state = AuthorizedChannel.TOKEN_REVOKED
    channel.access_token_enc = None
    channel.refresh_token_enc = None
    channel.token_expires_at = None
    channel.last_error = reason
    channel.save()
    return channel


# --- OAuth flow -------------------------------------------------------------


def _require_client(channel: AuthorizedChannel) -> GoogleClient:
    if channel.google_client is None:
        raise ClientNotFound(
            f"Channel {channel.channel_id!r} has no Google client bound; "
            "re-bind it before authorizing."
        )
    return channel.google_client


def start_oauth(
    channel: AuthorizedChannel,
    *,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    scopes: tuple[str, ...] = oauth.DEFAULT_SCOPES,
) -> OAuthStart:
    """Begin authorization for a channel row (docs/04 §5 `start_oauth(channel)`).

    Returns the Google consent URL plus the signed `state` the callback must
    echo back. The state is a Django-signed payload carrying the channel id, so
    a callback cannot be pointed at a different channel.
    """
    client = _require_client(channel)
    state = signing.dumps(
        {"channel": channel.pk, "client": client.pk}, salt=OAUTH_STATE_SALT
    )
    return OAuthStart(
        authorization_url=oauth.build_authorization_url(
            client_id=client.client_id,
            redirect_uri=redirect_uri,
            state=state,
            scopes=tuple(scopes),
        ),
        state=state,
    )


def read_oauth_state(state: str) -> AuthorizedChannel:
    """Verify a callback `state` and return the channel it names."""
    try:
        payload = signing.loads(
            state,
            salt=OAUTH_STATE_SALT,
            max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        )
    except signing.BadSignature as exc:  # includes SignatureExpired
        raise OAuthStateInvalid(
            "The OAuth state is invalid or expired; start the connection again."
        ) from exc
    channel = AuthorizedChannel.objects.filter(pk=payload.get("channel")).first()
    if channel is None:
        raise ChannelNotFound("The channel named by the OAuth state no longer exists.")
    return channel


@transaction.atomic
def complete_oauth(
    code: str,
    *,
    state: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    http_client: HttpClient | None = None,
    now: datetime | None = None,
) -> AuthorizedChannel:
    """Finish authorization: exchange the code and store **encrypted** tokens.

    The channel id is taken from the state when it is known; otherwise it is
    resolved from the token itself (`channels?mine=true`), the only reliable way
    to learn which channel just authorized us.
    """
    channel = read_oauth_state(state)
    client = _require_client(channel)
    moment = _dt(now or now_utc())

    tokens = oauth.exchange_code(
        code=code,
        client_id=client.client_id,
        client_secret=client_secret(client),
        redirect_uri=redirect_uri,
        now=moment,
        http_client=_http(http_client),
    )

    if _is_pending(channel):
        resolved_id, title = oauth.fetch_channel_identity(
            access_token=tokens.access_token, http_client=_http(http_client)
        )
        existing = (
            AuthorizedChannel.objects.filter(
                workspace=channel.workspace, channel_id=resolved_id
            )
            .exclude(pk=channel.pk)
            .first()
        )
        if existing is not None:
            # The channel was already known: keep that row and its delivery
            # history, and drop the placeholder instead of colliding with the
            # `unique(workspace, channel_id)` constraint.
            channel.delete()
            channel = existing
        channel.channel_id = resolved_id
        channel.title = title or channel.title

    channel.access_token_enc = encrypt(tokens.access_token).encode("utf-8")
    if tokens.refresh_token:
        channel.refresh_token_enc = encrypt(tokens.refresh_token).encode("utf-8")
    channel.token_expires_at = tokens.expires_at
    if tokens.scopes:
        channel.scopes = list(tokens.scopes)
    channel.token_state = AuthorizedChannel.TOKEN_VALID
    channel.last_checked_at = moment
    channel.last_error = ""
    channel.save()
    return channel


# --- Token lifecycle --------------------------------------------------------


def refresh_token(channel: AuthorizedChannel) -> str:
    """Decrypt the stored refresh token (in memory, INV-1). Raises `TokenMissing`."""
    if not channel.refresh_token_enc:
        raise TokenMissing(
            f"Channel {channel.channel_id!r} has no refresh token; "
            "re-connect it from Operations → Credentials."
        )
    return decrypt(bytes(channel.refresh_token_enc).decode("utf-8"))


def token_health(
    channel: AuthorizedChannel, *, now: datetime | None = None
) -> str:
    """Pillar 2 §2.1 health state, derived from stored facts.

    `valid` / `expiring` (inside the 5-minute window) / `revoked` / `invalid` /
    `missing`. The stored `token_state` wins when it is a terminal state, so a
    revoked channel never reports healthy again by accident.
    """
    if channel.token_state in (
        AuthorizedChannel.TOKEN_REVOKED,
        AuthorizedChannel.TOKEN_INVALID,
    ):
        return channel.token_state
    if not channel.access_token_enc and not channel.refresh_token_enc:
        return AuthorizedChannel.TOKEN_MISSING
    expires_at = channel.token_expires_at
    if expires_at is None:
        return AuthorizedChannel.TOKEN_VALID
    moment = _dt(now or now_utc())
    if expires_at <= moment:
        return AuthorizedChannel.TOKEN_EXPIRING
    if expires_at - moment <= timedelta(seconds=oauth.REFRESH_WINDOW_SECONDS):
        return AuthorizedChannel.TOKEN_EXPIRING
    return AuthorizedChannel.TOKEN_VALID


def refresh_channel_token(
    channel: AuthorizedChannel,
    *,
    http_client: HttpClient | None = None,
    now: datetime | None = None,
) -> AuthorizedChannel:
    """Exchange the refresh token for a new access token and persist it.

    Raises `AuthRevoked` when Google says `invalid_grant` (never retried — the
    state is recorded so the UI shows "reconnect"), and `TokenRefreshFailed` for
    transport/5xx failures (retryable).
    """
    client = _require_client(channel)
    moment = _dt(now or now_utc())
    try:
        tokens = oauth.refresh_access_token(
            client_id=client.client_id,
            client_secret=client_secret(client),
            refresh_token=refresh_token(channel),
            now=moment,
            http_client=_http(http_client),
        )
    except AuthRevoked as exc:
        channel.token_state = AuthorizedChannel.TOKEN_REVOKED
        channel.last_error = str(exc)
        channel.last_checked_at = moment
        channel.save(
            update_fields=["token_state", "last_error", "last_checked_at", "updated_at"]
        )
        raise

    channel.access_token_enc = encrypt(tokens.access_token).encode("utf-8")
    channel.token_expires_at = tokens.expires_at
    channel.token_state = AuthorizedChannel.TOKEN_VALID
    channel.last_checked_at = moment
    channel.last_error = ""
    channel.save()
    return channel


def valid_access_token(
    channel: AuthorizedChannel,
    *,
    http_client: HttpClient | None = None,
    now: datetime | None = None,
) -> str:
    """Return a usable access token, refreshing first when needed (docs/04 §5).

    This is the only supported way for another module to get a token, which is
    what makes the proactive-refresh rule (Pillar 2 §2.2) impossible to skip.
    """
    moment = _dt(now or now_utc())
    if channel.token_state in (
        AuthorizedChannel.TOKEN_REVOKED,
        AuthorizedChannel.TOKEN_INVALID,
    ):
        raise AuthRevoked(
            f"Channel {channel.channel_id!r} is {channel.token_state!r}; "
            "re-connect it from Operations → Credentials."
        )
    if not channel.access_token_enc:
        raise TokenMissing(
            f"Channel {channel.channel_id!r} has never been authorized."
        )

    health = token_health(channel, now=moment)
    if health != AuthorizedChannel.TOKEN_VALID:
        channel = refresh_channel_token(channel, http_client=http_client, now=moment)
    return decrypt(bytes(channel.access_token_enc).decode("utf-8"))


__all__ = [
    "DEFAULT_DAILY_UPLOAD_CAP",
    "DEFAULT_REDIRECT_URI",
    "OAUTH_STATE_MAX_AGE_SECONDS",
    "OAuthStart",
    "AuthorizedChannel",
    "GoogleClient",
    "add_google_client",
    "bind_channel",
    "client_secret",
    "complete_oauth",
    "deactivate_client",
    "get_channel",
    "get_client",
    "list_channels",
    "list_clients",
    "new_channel",
    "PENDING_CHANNEL_PREFIX",
    "read_oauth_state",
    "refresh_channel_token",
    "refresh_token",
    "revoke_channel",
    "start_oauth",
    "token_health",
    "update_google_client",
    "valid_access_token",
]
