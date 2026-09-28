from __future__ import annotations

"""
credentials.oauth — the Google OAuth 2.0 protocol, as four small functions.

Pillar 2 §2–§4 specifies the flow; this module is the part that is pure protocol
(URL building, response parsing, error classification) so `api.py` can stay
about state and policy.

* Authorization code exchange: `POST /token` with `grant_type=authorization_code`.
* Refresh: `POST /token` with `grant_type=refresh_token`.
* Identity: `GET /youtube/v3/channels?part=snippet&mine=true` — the only reliable
  way to learn *which* channel a fresh token belongs to.
"""

import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta

from credentials.errors import (
    AuthRevoked,
    OAuthExchangeRejected,
    TokenRefreshFailed,
)
from credentials.http import HttpClient, HttpResponse

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"

#: Upload + read. `youtube.upload` covers `videos.insert` and
#: `thumbnails.set`; `youtube.readonly` covers the inventory sync that makes
#: reconciliation possible. Nothing broader is requested.
SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
SCOPE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
DEFAULT_SCOPES: tuple[str, ...] = (SCOPE_UPLOAD, SCOPE_READONLY)

#: Proactive refresh window (Pillar 2 §2.2): refresh when this close to expiry.
REFRESH_WINDOW_SECONDS = 300


@dataclass(frozen=True)
class TokenPayload:
    """The four fields we persist from a Google token response."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: tuple[str, ...]


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> str:
    """The URL the operator is sent to (Pillar 2 §3, `access_type=offline`).

    `prompt=consent` is required on every start: without it Google silently
    drops the refresh token on a re-authorization, and the channel later fails
    with no explanation.
    """
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return f"{AUTH_ENDPOINT}?{query}"


def _parse_expiry(body: dict, now: datetime) -> datetime:
    expires_in = body.get("expires_in")
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        seconds = 3600  # Google's documented token lifetime
    return now + timedelta(seconds=seconds)


def _invalid_grant(body: dict) -> bool:
    return str(body.get("error", "")).strip() == "invalid_grant"


def _raise_for_transport_failure(response: HttpResponse, action: str) -> None:
    """status 0 means the request never completed — always retryable."""
    if response.status == 0:
        raise TokenRefreshFailed(
            f"{action} failed: no HTTP response ({response.body.get('detail', '')})"
        )


def exchange_code(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    now: datetime,
    http_client: HttpClient,
) -> TokenPayload:
    """Trade an authorization `code` for tokens (Pillar 2 §2.1)."""
    response = http_client.post_form(
        TOKEN_ENDPOINT,
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    _raise_for_transport_failure(response, "Authorization code exchange")
    if response.status != 200 or not response.body.get("access_token"):
        raise OAuthExchangeRejected(
            f"Google rejected the authorization code (HTTP {response.status}): "
            f"{response.body.get('error', 'unknown_error')}"
        )
    return TokenPayload(
        access_token=str(response.body["access_token"]),
        refresh_token=(
            str(response.body["refresh_token"])
            if response.body.get("refresh_token")
            else None
        ),
        expires_at=_parse_expiry(response.body, now),
        scopes=tuple(str(response.body.get("scope", "")).split()) or (),
    )


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    now: datetime,
    http_client: HttpClient,
) -> TokenPayload:
    """Exchange a refresh token for a fresh access token (Pillar 2 §2.2)."""
    response = http_client.post_form(
        TOKEN_ENDPOINT,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    _raise_for_transport_failure(response, "Token refresh")
    if response.status in (400, 401) and _invalid_grant(response.body):
        raise AuthRevoked(
            "Google returned invalid_grant: the refresh token is revoked or "
            "expired. The channel must be re-connected by an owner."
        )
    if response.status != 200 or not response.body.get("access_token"):
        raise TokenRefreshFailed(
            f"Token refresh failed (HTTP {response.status}): "
            f"{response.body.get('error', 'unknown_error')}"
        )
    return TokenPayload(
        access_token=str(response.body["access_token"]),
        refresh_token=refresh_token,  # refresh responses do not rotate it
        expires_at=_parse_expiry(response.body, now),
        scopes=tuple(str(response.body.get("scope", "")).split()) or (),
    )


def fetch_channel_identity(
    *, access_token: str, http_client: HttpClient
) -> tuple[str, str]:
    """Return `(channel_id, title)` for the token's own channel.

    Called only when the channel id is not already known — a re-connect of an
    existing channel keeps its row and its history.
    """
    url = f"{CHANNELS_ENDPOINT}?part=snippet&mine=true"
    response = http_client.get_json(
        url, headers={"Authorization": f"Bearer {access_token}"}
    )
    _raise_for_transport_failure(response, "Channel identity lookup")
    items = response.body.get("items") or []
    if response.status != 200 or not items:
        raise OAuthExchangeRejected(
            f"Could not resolve the authorized channel (HTTP {response.status}). "
            "Check that the Google account owns a YouTube channel."
        )
    first = items[0]
    snippet = first.get("snippet") or {}
    return str(first.get("id", "")), str(snippet.get("title", ""))
