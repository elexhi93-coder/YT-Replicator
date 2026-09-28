"""U05 tests — Google clients, OAuth, and the token lifecycle.

Covers docs/03 §4 (`google_client`, `authorized_channel`), INV-1 (secrets
encrypted at rest and write-only across the boundary), INV-2 (quota day comes
from `core`, never re-derived here) and Pillar 2 §2–§4 (health states, proactive
refresh, `invalid_grant` classification).

No test touches the network: every outbound call goes through `FakeHttp`.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.api import get_default_workspace
from core.api import PermanentAuthError, PermanentError, TransientError, now_utc
from credentials import api, oauth
from credentials.errors import (
    AuthRevoked,
    ChannelNotFound,
    ClientNotFound,
    OAuthExchangeRejected,
    OAuthStateInvalid,
    TokenMissing,
    TokenRefreshFailed,
)
from credentials.http import HttpResponse
from credentials.models import AuthorizedChannel, GoogleClient

pytestmark = pytest.mark.django_db

CLIENT_SECRET = "shh-do-not-log-me"


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    """INV-1 needs a key; a fixed 64-hex value keeps tests hermetic."""
    monkeypatch.setenv("PLATFORM_MASTER_KEY", "0" * 64)


class FakeHttp:
    """Records calls and replays canned Google responses."""

    def __init__(
        self,
        *,
        token_status: int = 200,
        token_body: dict | None = None,
        channel_status: int = 200,
        channel_items: list | None = None,
    ) -> None:
        self.token_status = token_status
        self.token_body = token_body if token_body is not None else {}
        self.channel_status = channel_status
        self.channel_items = channel_items
        self.calls: list[tuple[str, str, dict]] = []

    def post_form(self, url, data, timeout=30.0, headers=None):
        self.calls.append(("post", url, dict(data)))
        return HttpResponse(status=self.token_status, body=dict(self.token_body))

    def get_json(self, url, headers=None, timeout=30.0):
        self.calls.append(("get", url, dict(headers or {})))
        body = {} if self.channel_items is None else {"items": self.channel_items}
        return HttpResponse(status=self.channel_status, body=body)

    @property
    def posts(self) -> list[dict]:
        return [c[2] for c in self.calls if c[0] == "post"]


def token_response(access: str = "access-1", refresh: str | None = "refresh-1") -> dict:
    body = {
        "access_token": access,
        "expires_in": 3600,
        "scope": " ".join(oauth.DEFAULT_SCOPES),
    }
    if refresh:
        body["refresh_token"] = refresh
    return body


@pytest.fixture
def workspace():
    return get_default_workspace()


@pytest.fixture
def client(workspace) -> GoogleClient:
    return api.add_google_client(
        workspace,
        label="Main",
        client_id="123.apps.googleusercontent.com",
        client_secret=CLIENT_SECRET,
    )


@pytest.fixture
def channel(client) -> AuthorizedChannel:
    return api.bind_channel(
        client, channel_id="UCabc", title="My Channel", scopes=oauth.DEFAULT_SCOPES
    )


class TestGoogleClient:
    def test_secret_is_encrypted_at_rest_and_never_in_the_row(self, client):
        raw = bytes(client.client_secret_enc)
        assert CLIENT_SECRET.encode() not in raw  # INV-1: no plaintext column
        assert api.client_secret(client) == CLIENT_SECRET

    def test_default_cap_is_the_documented_six(self, workspace):
        client = api.add_google_client(
            workspace, label="Other", client_id="o.apps", client_secret="s"
        )
        assert client.daily_upload_cap == api.DEFAULT_DAILY_UPLOAD_CAP == 6

    def test_label_and_client_id_are_unique_per_workspace(self, client, workspace):
        # Each violating insert needs its own atomic block: the first IntegrityError
        # poisons the surrounding pytest-django transaction.
        with pytest.raises(IntegrityError), transaction.atomic():
            api.add_google_client(
                workspace, label="Main", client_id="other.apps", client_secret="s"
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            api.add_google_client(
                workspace,
                label="Another",
                client_id=client.client_id,
                client_secret="s",
            )

    def test_cap_must_be_positive(self, workspace):
        with pytest.raises(ValueError):
            api.add_google_client(
                workspace,
                label="Zero",
                client_id="z.apps",
                client_secret="s",
                daily_upload_cap=0,
            )

    def test_lookup_by_label_and_id(self, client, workspace):
        assert api.get_client(workspace, label="Main").pk == client.pk
        assert api.get_client(workspace, client_id=client.client_id).pk == client.pk
        with pytest.raises(ClientNotFound):
            api.get_client(workspace, label="Nope")

    def test_update_rotates_the_secret_and_deactivates(self, client):
        api.update_google_client(client, client_secret="rotated", daily_upload_cap=9)
        assert api.client_secret(client) == "rotated"
        assert client.daily_upload_cap == 9
        api.deactivate_client(client)
        assert client.is_active is False

    def test_list_clients_is_ordered_by_label(self, workspace, client):
        api.add_google_client(
            workspace, label="Alpha", client_id="a.apps", client_secret="s"
        )
        assert [c.label for c in api.list_clients(workspace)] == ["Alpha", "Main"]


class TestChannelBinding:
    def test_bind_is_idempotent_and_keeps_the_row(self, client):
        first = api.bind_channel(client, channel_id="UCabc", title="One")
        again = api.bind_channel(client, channel_id="UCabc", title="Two")
        assert first.pk == again.pk
        assert again.title == "Two"
        assert AuthorizedChannel.objects.count() == 1

    def test_channel_id_is_required_and_blank_is_rejected(self, client):
        with pytest.raises(ValueError):
            api.bind_channel(client, channel_id="   ")

    def test_lookup_by_pk_and_canonical_id(self, channel):
        assert api.get_channel(channel.pk).pk == channel.pk
        assert api.get_channel("UCabc").pk == channel.pk
        with pytest.raises(ChannelNotFound):
            api.get_channel("UCnope")

    def test_new_channel_starts_pending_and_unhealthy(self, client):
        pending = api.new_channel(client)
        assert pending.channel_id.startswith(api.PENDING_CHANNEL_PREFIX)
        assert pending.token_state == AuthorizedChannel.TOKEN_MISSING

    def test_list_channels_ordered_by_title(self, client, channel):
        api.bind_channel(client, channel_id="UCzzz", title="Aardvark")
        assert [c.title for c in api.list_channels(client.workspace)] == [
            "Aardvark",
            "My Channel",
        ]

    def test_revoke_channel_drops_tokens(self, channel):
        api.revoke_channel(channel, reason="operator unplugged it")
        assert channel.token_state == AuthorizedChannel.TOKEN_REVOKED
        assert channel.access_token_enc is None
        assert channel.refresh_token_enc is None
        assert channel.last_error == "operator unplugged it"


class TestOAuthFlow:
    def test_start_oauth_builds_a_consent_url_with_offline_access(self, channel):
        start = api.start_oauth(channel, redirect_uri="https://example.test/cb")
        query = parse_qs(urlparse(start.authorization_url).query)
        assert urlparse(start.authorization_url).netloc == "accounts.google.com"
        assert query["client_id"] == [channel.google_client.client_id]
        assert query["redirect_uri"] == ["https://example.test/cb"]
        assert query["response_type"] == ["code"]
        assert query["access_type"] == ["offline"]  # else no refresh token
        assert query["prompt"] == ["consent"]
        assert query["state"] == [start.state]
        assert set(query["scope"][0].split()) == set(oauth.DEFAULT_SCOPES)

    def test_state_is_signed_and_names_the_channel(self, channel):
        start = api.start_oauth(channel)
        assert api.read_oauth_state(start.state).pk == channel.pk

    def test_tampered_state_is_rejected(self, channel):
        start = api.start_oauth(channel)
        with pytest.raises(OAuthStateInvalid):
            api.read_oauth_state(start.state + "x")

    def test_expired_state_is_rejected(self, channel, monkeypatch):
        # Drive the real code path: any state is stale once the window closes.
        start = api.start_oauth(channel)
        monkeypatch.setattr(api, "OAUTH_STATE_MAX_AGE_SECONDS", -1)
        with pytest.raises(OAuthStateInvalid):
            api.read_oauth_state(start.state)

    def test_channel_without_a_client_cannot_start(self, channel):
        channel.google_client = None
        channel.save(update_fields=["google_client"])
        with pytest.raises(ClientNotFound):
            api.start_oauth(channel)

    def test_complete_oauth_stores_encrypted_tokens(self, channel):
        fake = FakeHttp(token_body=token_response())
        start = api.start_oauth(channel, redirect_uri="https://example.test/cb")
        done = api.complete_oauth(
            "the-code",
            state=start.state,
            redirect_uri="https://example.test/cb",
            http_client=fake,
            now=now_utc(),
        )
        assert done.token_state == AuthorizedChannel.TOKEN_VALID
        assert "access-1" not in bytes(done.access_token_enc).decode("latin-1")
        assert api.refresh_token(done) == "refresh-1"
        assert api.valid_access_token(done, http_client=fake) == "access-1"
        assert fake.posts[0]["grant_type"] == "authorization_code"
        assert fake.posts[0]["code"] == "the-code"
        assert fake.posts[0]["redirect_uri"] == "https://example.test/cb"
        assert done.scopes == list(oauth.DEFAULT_SCOPES)

    def test_complete_oauth_resolves_identity_for_a_new_channel(self, client):
        pending = api.new_channel(client)
        start = api.start_oauth(pending)
        fake = FakeHttp(
            token_body=token_response(),
            channel_items=[{"id": "UCnew", "snippet": {"title": "Fresh Channel"}}],
        )
        done = api.complete_oauth("code", state=start.state, http_client=fake)
        assert done.channel_id == "UCnew"
        assert done.title == "Fresh Channel"
        assert done.token_state == AuthorizedChannel.TOKEN_VALID
        assert [c[0] for c in fake.calls] == ["post", "get"]

    def test_complete_oauth_merges_into_the_known_channel_row(self, client, channel):
        pending = api.new_channel(client)
        start = api.start_oauth(pending)
        fake = FakeHttp(
            token_body=token_response(access="access-9"),
            channel_items=[{"id": channel.channel_id, "snippet": {"title": "Renamed"}}],
        )
        done = api.complete_oauth("code", state=start.state, http_client=fake)
        assert done.pk == channel.pk  # history kept, placeholder dropped
        assert AuthorizedChannel.objects.count() == 1
        assert api.valid_access_token(done, http_client=fake) == "access-9"

    def test_rejected_code_is_permanent_and_not_retried(self, channel):
        fake = FakeHttp(token_status=400, token_body={"error": "invalid_grant"})
        start = api.start_oauth(channel)
        with pytest.raises(OAuthExchangeRejected):
            api.complete_oauth("bad", state=start.state, http_client=fake)
        assert isinstance(OAuthExchangeRejected("x"), PermanentError)

    def test_code_exchange_without_a_response_is_transient(self, channel):
        fake = FakeHttp(token_status=0, token_body={"detail": "connection reset"})
        start = api.start_oauth(channel)
        with pytest.raises(TokenRefreshFailed):
            api.complete_oauth("code", state=start.state, http_client=fake)


class TestTokenLifecycle:
    def _authorize(self, channel, fake):
        start = api.start_oauth(channel)
        return api.complete_oauth("code", state=start.state, http_client=fake)

    def test_fresh_token_is_returned_without_an_http_call(self, channel):
        fake = FakeHttp(token_body=token_response())
        authorised = self._authorize(channel, fake)
        fake.calls.clear()
        assert api.valid_access_token(authorised, http_client=fake) == "access-1"
        assert fake.calls == []

    def test_token_inside_the_window_is_refreshed_proactively(self, channel):
        fake = FakeHttp(token_body=token_response())
        authorised = self._authorize(channel, fake)
        # Pillar 2 §2.2: within 5 minutes of expiry → refresh now, not later.
        authorised.token_expires_at = timezone.now() + timedelta(seconds=60)
        authorised.save(update_fields=["token_expires_at"])
        fake.token_body = token_response(access="access-2", refresh=None)
        fake.calls.clear()

        assert api.valid_access_token(authorised, http_client=fake) == "access-2"
        assert fake.posts[0]["grant_type"] == "refresh_token"
        authorised.refresh_from_db()
        assert api.token_health(authorised) == AuthorizedChannel.TOKEN_VALID

    def test_expired_token_without_refresh_token_needs_reconnect(self, channel):
        fake = FakeHttp(token_body=token_response(refresh=None))
        authorised = self._authorize(channel, fake)
        authorised.token_expires_at = timezone.now() - timedelta(seconds=1)
        authorised.save(update_fields=["token_expires_at"])
        with pytest.raises(TokenMissing):
            api.valid_access_token(authorised, http_client=fake)

    def test_invalid_grant_is_recorded_and_never_retried(self, channel):
        fake = FakeHttp(token_body=token_response())
        authorised = self._authorize(channel, fake)
        authorised.token_expires_at = timezone.now() + timedelta(seconds=30)
        authorised.save(update_fields=["token_expires_at"])
        fake.token_status = 400
        fake.token_body = {"error": "invalid_grant"}
        with pytest.raises(AuthRevoked):
            api.valid_access_token(authorised, http_client=fake)

        authorised.refresh_from_db()
        assert authorised.token_state == AuthorizedChannel.TOKEN_REVOKED
        assert authorised.last_error
        fake.calls.clear()
        with pytest.raises(AuthRevoked):  # terminal: no second network attempt
            api.valid_access_token(authorised, http_client=fake)
        assert fake.calls == []

    def test_server_error_is_retryable_and_leaves_state_alone(self, channel):
        fake = FakeHttp(token_body=token_response())
        authorised = self._authorize(channel, fake)
        authorised.token_expires_at = timezone.now() + timedelta(seconds=30)
        authorised.save(update_fields=["token_expires_at"])
        fake.token_status = 503
        fake.token_body = {"error": "backendError"}
        with pytest.raises(TokenRefreshFailed) as excinfo:
            api.valid_access_token(authorised, http_client=fake)
        assert isinstance(excinfo.value, TransientError)
        authorised.refresh_from_db()
        assert authorised.token_state == AuthorizedChannel.TOKEN_VALID

    def test_unauthorized_channel_reports_missing(self, channel):
        assert api.token_health(channel) == AuthorizedChannel.TOKEN_MISSING
        with pytest.raises(TokenMissing):
            api.valid_access_token(channel)

    def test_health_states_follow_the_pillar_2_state_machine(self, channel):
        fake = FakeHttp(token_body=token_response())
        authorised = self._authorize(channel, fake)
        assert api.token_health(authorised) == AuthorizedChannel.TOKEN_VALID
        authorised.token_expires_at = now_utc() + timedelta(seconds=10)
        assert api.token_health(authorised) == AuthorizedChannel.TOKEN_EXPIRING
        api.revoke_channel(authorised)
        assert api.token_health(authorised) == AuthorizedChannel.TOKEN_REVOKED

    def test_auth_errors_are_permanent_so_the_worker_does_not_retry_them(self):
        for error in (AuthRevoked("x"), TokenMissing("x")):
            assert isinstance(error, PermanentAuthError)
            assert isinstance(error, PermanentError)
            assert not isinstance(error, TransientError)
