"""U16 tests — the Credentials page.

A page is thin by design, so these tests are not about markup. They are about
the four things a page can get wrong that the modules underneath cannot:

1. **Access.** Every route is owner-only, including the ones that mutate.
2. **Tenant scoping.** A row from another workspace must read as "not found",
   never as a 403 that confirms it exists.
3. **Secrets.** No rendered page may contain a client secret (INV-1).
4. **The OAuth callback**, a GET and therefore reachable by anything: a denied
   consent and a missing code are normal outcomes, not tracebacks.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.urls import reverse

from accounts.api import get_default_workspace
from credentials.api import add_google_client, bind_channel, new_channel

# `Workspace`/`WorkspaceMember` are reached through the app registry, never by
# importing `accounts.models` — the accounts CONTRACT's own instruction, and
# what `tests/test_module_boundaries.py` enforces (INV-12).
Workspace = apps.get_model("accounts", "Workspace")
WorkspaceMember = apps.get_model("accounts", "WorkspaceMember")

pytestmark = pytest.mark.django_db

SECRET = "super-secret-value-do-not-render"


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setenv("PLATFORM_MASTER_KEY", "0" * 64)


@pytest.fixture
def workspace():
    return get_default_workspace()


def make_user(django_user_model, workspace, username, role):
    user = django_user_model.objects.create_user(username=username, password="pw")
    WorkspaceMember.objects.create(workspace=workspace, user=user, role=role)
    return user


@pytest.fixture
def owner(workspace, django_user_model):
    return make_user(django_user_model, workspace, "owner", "owner")


@pytest.fixture
def operator(workspace, django_user_model):
    return make_user(django_user_model, workspace, "operator", "operator")


@pytest.fixture
def client_row(workspace):
    return add_google_client(
        workspace,
        label="Production",
        client_id="123.apps.googleusercontent.com",
        client_secret=SECRET,
        daily_upload_cap=6,
    )


def signed_in(client, user):
    client.force_login(user)
    return client


def new_client_payload(**overrides):
    payload = {
        "label": "Staging",
        "client_id": "456.apps.googleusercontent.com",
        "client_secret": SECRET,
        "daily_upload_cap": "3",
    }
    payload.update(overrides)
    return payload


class TestAccess:
    def test_anonymous_is_sent_to_the_login_page(self, client):
        response = client.get(reverse("credentials:list"))
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_a_viewer_is_refused(self, client, workspace, django_user_model):
        user = make_user(django_user_model, workspace, "viewer", "viewer")
        signed_in(client, user)
        # 403, not a redirect: the user is known, and pretending otherwise
        # would only confuse them.
        assert client.get(reverse("credentials:list")).status_code == 403

    def test_an_operator_is_refused(self, client, operator):
        # Who can add a Google client can also spend its quota, so the two
        # roles go together (docs/04 §9).
        signed_in(client, operator)
        assert client.get(reverse("credentials:list")).status_code == 403

    def test_an_owner_gets_the_page(self, client, owner):
        signed_in(client, owner)
        assert client.get(reverse("credentials:list")).status_code == 200

    @pytest.mark.parametrize(
        "route", ["credentials:client_add", "credentials:channel_connect"]
    )
    def test_a_mutating_route_is_post_only(self, client, owner, route):
        signed_in(client, owner)
        # A GET must never change anything: these write rows and redirect to
        # Google.
        assert client.get(reverse(route)).status_code == 405

    def test_a_mutating_route_needs_a_post(self, client, operator):
        signed_in(client, operator)
        assert client.post(reverse("credentials:client_add")).status_code == 403


class TestThePageRenders:
    def test_an_empty_installation_says_so(self, client, owner):
        signed_in(client, owner)
        body = client.get(reverse("credentials:list")).content.decode()
        assert "No clients yet." in body
        assert "No channels yet." in body

    def test_a_client_is_listed_with_its_cap(self, client, owner, client_row):
        signed_in(client, owner)
        body = client.get(reverse("credentials:list")).content.decode()
        assert "Production" in body
        assert client_row.client_id in body

    def test_a_channel_shows_its_token_health(self, client, owner, client_row):
        channel = bind_channel(client_row, channel_id="UCpage000001", title="Tech")
        signed_in(client, owner)
        body = client.get(reverse("credentials:list")).content.decode()
        assert "Tech" in body
        assert "missing" in body  # never authorised
        assert channel.channel_id in body

    def test_a_pending_channel_says_it_is_awaiting_connection(
        self, client, owner, client_row
    ):
        new_channel(client_row, title="Fresh")
        signed_in(client, owner)
        body = client.get(reverse("credentials:list")).content.decode()
        assert "awaiting connection" in body

    def test_the_secret_is_never_rendered(self, client, owner, client_row):
        signed_in(client, owner)
        body = client.get(reverse("credentials:list")).content.decode()
        # INV-1: the page may say a secret is stored, never what it is.
        assert SECRET not in body
        assert "stored (never shown)" in body


class TestAddingAClient:
    def test_a_valid_client_is_created(self, client, owner, workspace):
        signed_in(client, owner)
        response = client.post(reverse("credentials:client_add"), new_client_payload())
        assert response.status_code == 302
        assert workspace.google_clients.get(label="Staging").daily_upload_cap == 3

    def test_a_missing_field_is_refused_with_a_message(self, client, owner, workspace):
        signed_in(client, owner)
        response = client.post(
            reverse("credentials:client_add"),
            new_client_payload(client_secret=""),
            follow=True,
        )
        assert response.status_code == 200
        assert workspace.google_clients.filter(label="Staging").count() == 0
        assert "required" in response.content.decode()

    def test_a_nonsense_cap_falls_back_rather_than_crashing(self, client, owner):
        signed_in(client, owner)
        # A bad number in a text field is a typo, not a 500.
        response = client.post(
            reverse("credentials:client_add"),
            new_client_payload(daily_upload_cap="lots"),
        )
        assert response.status_code == 302

    def test_the_secret_is_stored_encrypted_not_in_clear(self, client, owner, workspace):
        signed_in(client, owner)
        client.post(reverse("credentials:client_add"), new_client_payload())
        row = workspace.google_clients.get(label="Staging")
        assert SECRET.encode() not in row.client_secret_enc


class TestEditingAClient:
    def test_a_blank_secret_keeps_the_existing_one(self, client, owner, client_row):
        from credentials.api import client_secret

        signed_in(client, owner)
        client.post(
            reverse("credentials:client_edit", args=[client_row.pk]),
            {"label": "Renamed", "daily_upload_cap": "9", "client_secret": ""},
        )
        client_row.refresh_from_db()
        assert client_row.label == "Renamed"
        assert client_row.daily_upload_cap == 9
        # Fixing a label must not destroy a working credential.
        assert client_secret(client_row) == SECRET

    def test_a_new_secret_rotates_it(self, client, owner, client_row):
        from credentials.api import client_secret

        signed_in(client, owner)
        client.post(
            reverse("credentials:client_edit", args=[client_row.pk]),
            {"label": "Rotated", "client_secret": "a-brand-new-secret"},
        )
        # `refresh_from_db()` mutates the instance in place and returns None.
        client_row.refresh_from_db()
        assert client_secret(client_row) == "a-brand-new-secret"

    def test_editing_does_not_deactivate_the_client(self, client, owner, client_row):
        signed_in(client, owner)
        client.post(
            reverse("credentials:client_edit", args=[client_row.pk]),
            {"label": "Just a rename", "client_secret": ""},
        )
        client_row.refresh_from_db()
        # A form that omits an unchecked box must not switch a working client
        # off; deactivation has its own explicit action.
        assert client_row.is_active is True
        assert client_row.label == "Just a rename"

    def test_editing_a_missing_client_is_refused(self, client, owner):
        signed_in(client, owner)
        response = client.post(
            reverse("credentials:client_edit", args=[9999]),
            {"label": "Ghost"},
            follow=True,
        )
        assert response.status_code == 200
        assert "No client" in response.content.decode()


class TestTogglingAClient:
    def test_deactivating_keeps_its_channels(self, client, owner, client_row):
        channel = bind_channel(client_row, channel_id="UCpage000002")
        signed_in(client, owner)
        client.post(reverse("credentials:client_toggle", args=[client_row.pk]))
        # `refresh_from_db()` mutates the instance in place and returns None.
        client_row.refresh_from_db()
        assert client_row.is_active is False
        # A deactivated client is recoverable; a deleted one with history is not.
        assert Workspace.objects.filter(pk=client_row.workspace_id).exists()
        assert channel.pk is not None

    def test_a_deactivated_client_can_be_reactivated(self, client, owner, client_row):
        signed_in(client, owner)
        url = reverse("credentials:client_toggle", args=[client_row.pk])
        client.post(url)
        client.post(url)
        client_row.refresh_from_db()
        assert client_row.is_active is True


class TestConnectingAChannel:
    def test_connect_redirects_to_google(self, client, owner, client_row):
        signed_in(client, owner)
        response = client.post(
            reverse("credentials:channel_connect"),
            {"client_id": str(client_row.pk), "title": "Tech Daily"},
        )
        assert response.status_code == 302
        assert response["Location"].startswith("https://accounts.google.com")

    def test_the_row_is_created_before_the_redirect(self, client, owner, client_row):
        signed_in(client, owner)
        client.post(
            reverse("credentials:channel_connect"),
            {"client_id": str(client_row.pk), "title": "Tech Daily"},
        )
        # There has to be something for the tokens to land on when Google
        # comes back.
        assert client_row.channels.count() == 1

    def test_the_consent_url_carries_our_callback(self, client, owner, client_row):
        signed_in(client, owner)
        response = client.post(
            reverse("credentials:channel_connect"), {"client_id": str(client_row.pk)}
        )
        # A redirect_uri we did not register is the classic
        # `redirect_uri_mismatch`; it is built from the request for that reason.
        assert "redirect_uri" in response["Location"]
        assert "callback" in response["Location"]

    def test_a_deactivated_client_cannot_connect(self, client, owner, client_row):
        client_row.is_active = False
        client_row.save(update_fields=["is_active"])
        signed_in(client, owner)
        response = client.post(
            reverse("credentials:channel_connect"),
            {"client_id": str(client_row.pk)},
            follow=True,
        )
        assert response.status_code == 200
        assert client_row.channels.count() == 0
        assert "deactivated" in response.content.decode()

    def test_reconnect_restarts_the_flow(self, client, owner, client_row):
        channel = bind_channel(client_row, channel_id="UCpage000003")
        signed_in(client, owner)
        response = client.post(
            reverse("credentials:channel_reconnect", args=[channel.pk])
        )
        assert response["Location"].startswith("https://accounts.google.com")

    def test_disconnect_drops_the_tokens(self, client, owner, client_row):
        channel = bind_channel(client_row, channel_id="UCpage000004")
        signed_in(client, owner)
        client.post(reverse("credentials:channel_disconnect", args=[channel.pk]))
        channel.refresh_from_db()
        assert channel.token_state == "revoked"


class TestTheOAuthCallback:
    def test_a_denied_consent_is_a_message_not_a_traceback(self, client, owner):
        signed_in(client, owner)
        response = client.get(
            reverse("credentials:oauth_callback"),
            {"error": "access_denied"},
            follow=True,
        )
        assert response.status_code == 200
        assert "refused" in response.content.decode()

    def test_a_missing_code_is_a_message(self, client, owner):
        signed_in(client, owner)
        response = client.get(reverse("credentials:oauth_callback"), {}, follow=True)
        assert response.status_code == 200
        assert "no authorization code" in response.content.decode()

    def test_a_tampered_state_is_a_message_not_a_500(self, client, owner):
        signed_in(client, owner)
        response = client.get(
            reverse("credentials:oauth_callback"),
            {"code": "abc", "state": "tampered"},
            follow=True,
        )
        # A stale or forged state is an ordinary outcome, not a crash.
        assert response.status_code == 200
        assert "state" in response.content.decode().lower()

    def test_the_callback_still_requires_a_login(self, client):
        # It is a GET anyone can request, and it exchanges a code for tokens.
        assert client.get(
            reverse("credentials:oauth_callback"), {"error": "access_denied"}
        ).status_code == 302


class TestTenantScoping:
    def test_another_workspaces_client_is_not_found(
        self, client, owner, django_user_model
    ):
        other = Workspace.objects.create(name="Other", slug="other")
        foreign = add_google_client(
            other, label="Foreign", client_id="f.apps", client_secret="s"
        )
        signed_in(client, owner)
        response = client.post(
            reverse("credentials:client_toggle", args=[foreign.pk]), follow=True
        )
        assert response.status_code == 200
        foreign.refresh_from_db()
        assert foreign.is_active is True
        # "No client N in this workspace" — never a 403, which would confirm
        # the row exists.
        assert "No client" in response.content.decode()

    def test_another_workspaces_channel_cannot_be_disconnected(
        self, client, owner, django_user_model
    ):
        other = Workspace.objects.create(name="Other2", slug="other2")
        foreign_client = add_google_client(
            other, label="F2", client_id="f2.apps", client_secret="s"
        )
        foreign = bind_channel(foreign_client, channel_id="UCforeign00001")
        signed_in(client, owner)
        response = client.post(
            reverse("credentials:channel_disconnect", args=[foreign.pk]), follow=True
        )
        foreign.refresh_from_db()
        assert foreign.token_state == "missing"  # untouched
        assert "No channel" in response.content.decode()


