"""
ui.pages.credentials — the Credentials page (U16).

Google OAuth clients and the channels authorised against them. Four actions,
each one delegation deep:

* add / edit a client  → `credentials.add_google_client` / `update_google_client`
* connect a channel    → `credentials.new_channel` + `start_oauth` → Google
* finish connecting    → `credentials.complete_oauth` (the callback)
* reconnect / revoke   → `credentials.start_oauth` / `revoke_channel`

Three things this page deliberately does **not** do:

1. **It never displays a secret** (INV-1). A client row shows its *client id*,
   which Google publishes, and whether a secret is stored — never the value.
2. **It never decides health.** The badge is `credentials.token_health`, the
   same function the worker's auth path uses, so the page cannot disagree with
   the process about whether a channel works.
3. **It does no long-running work** (docs/04 §7). Connecting a channel is a
   redirect to Google and a callback; the token exchange is one HTTP call, and
   nothing here downloads or uploads.

The OAuth callback is a GET because Google redirects with one, so it is
reachable by anything: it trusts only the signed `state`, and a user who denies
consent is a normal outcome rather than an error.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.api import role_required
from credentials.api import (
    PENDING_CHANNEL_PREFIX,
    CredentialError,
    add_google_client,
    complete_oauth,
    deactivate_client,
    list_channels,
    list_clients,
    new_channel,
    revoke_channel,
    start_oauth,
    token_health,
    update_google_client,
)

#: Routes live in the `credentials` namespace (docs/04 §8.3): no path is
#: hardcoded here, so a tenant prefix later is a change in `urls.py` alone.
_LIST = "credentials:list"


@role_required("owner")
@require_GET
def credentials_page(request: HttpRequest) -> HttpResponse:
    """Clients, channels, and their token health — the whole page.

    The owner role matches the nav item's declared minimum (docs/04 §9): who
    can add a Google client can also spend its quota, so the two go together.
    """
    workspace = request.workspace
    clients = list_clients(workspace)
    channels = [_channel_row(channel) for channel in list_channels(workspace)]
    return render(
        request,
        "ui/credentials.html",
        {
            "workspace": workspace,
            "clients": clients,
            "channels": channels,
            "healthy": sum(1 for row in channels if row["health"] == "valid"),
            "total": len(channels),
        },
    )


@role_required("owner")
@require_POST
def add_client(request: HttpRequest) -> HttpResponse:
    """Register a Google Cloud project. The secret is write-only (INV-1)."""
    form = _client_form(request.POST)
    if not form["label"] or not form["client_id"] or not form["client_secret"]:
        messages.error(request, "Label, client id and client secret are all required.")
        return redirect(_LIST)
    try:
        add_google_client(
            request.workspace,
            label=form["label"],
            client_id=form["client_id"],
            client_secret=form["client_secret"],
            daily_upload_cap=form["cap"],
        )
    except (ValueError, CredentialError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Added client {form['label']!r}.")
    return redirect(_LIST)


@role_required("owner")
@require_POST
def edit_client(request: HttpRequest, pk: int) -> HttpResponse:
    """Update the mutable fields, including the daily upload cap.

    A blank secret field means "keep the existing one" rather than "erase it",
    so an operator fixing a label cannot accidentally destroy a working
    credential — and the secret is never rendered back to the form.
    """
    client = _find(request, pk, list_clients(request.workspace), "client")
    if client is None:
        return redirect(_LIST)
    form = _client_form(request.POST)
    kwargs = {
        "label": form["label"] or client.label,
        "daily_upload_cap": form["cap"],
    }
    if form["client_secret"]:
        kwargs["client_secret"] = form["client_secret"]
    # `is_active` is deliberately absent: deactivation has its own explicit
    # action (`toggle`), and an HTML form that omits an unchecked box would
    # otherwise silently switch a working client off every time it was renamed.
    try:
        update_google_client(client, **kwargs)
    except (ValueError, CredentialError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Updated {client.label!r}.")
    return redirect(_LIST)


@role_required("owner")
@require_POST
def toggle_client(request: HttpRequest, pk: int) -> HttpResponse:
    """Deactivate a client without deleting its channels.

    `deactivate_client` stops new work while the channel rows survive, so a
    client is recoverable — deleting one that has history behind it is not.
    """
    client = _find(request, pk, list_clients(request.workspace), "client")
    if client is None:
        return redirect(_LIST)
    if client.is_active:
        deactivate_client(client)
        messages.info(request, f"Deactivated {client.label!r}.")
    else:
        client.is_active = True
        client.save(update_fields=["is_active", "updated_at"])
        messages.success(request, f"Reactivated {client.label!r}.")
    return redirect(_LIST)


@role_required("owner")
@require_POST
def connect_channel(request: HttpRequest) -> HttpResponse:
    """Begin the OAuth dance: create the row, then redirect to Google.

    The row is created *before* the redirect because Google's consent screen
    only tells us which channel authorised us afterwards — there is nothing to
    attach the tokens to if we wait.
    """
    client = _find(request, _int(request.POST.get("client_id")),
                   list_clients(request.workspace), "client")
    if client is None:
        return redirect(_LIST)
    if not client.is_active:
        messages.error(request, f"Client {client.label!r} is deactivated.")
        return redirect(_LIST)
    channel = new_channel(client, title=request.POST.get("title", "").strip())
    start = start_oauth(channel, redirect_uri=_redirect_uri(request))
    return redirect(start.authorization_url)


@role_required("owner")
@require_POST
def reconnect_channel(request: HttpRequest, pk: int) -> HttpResponse:
    """Re-run consent for a channel whose token is missing, expiring or revoked."""
    channel = _find(request, pk, list_channels(request.workspace), "channel")
    if channel is None:
        return redirect(_LIST)
    start = start_oauth(channel, redirect_uri=_redirect_uri(request))
    return redirect(start.authorization_url)


@role_required("owner")
@require_POST
def disconnect_channel(request: HttpRequest, pk: int) -> HttpResponse:
    """Disconnect a channel: a terminal state, and both tokens are dropped.

    `revoke_channel` also clears the tokens, so nothing can silently retry with
    credentials the operator has just withdrawn.
    """
    channel = _find(request, pk, list_channels(request.workspace), "channel")
    if channel is None:
        return redirect(_LIST)
    revoke_channel(channel, reason=request.POST.get("reason", "").strip())
    messages.info(request, f"Disconnected {channel.title or channel.channel_id}.")
    return redirect(_LIST)


@role_required("owner")
@require_GET
def oauth_callback(request: HttpRequest) -> HttpResponse:
    """Where Google sends us back. A GET, so it must be untrusting.

    Three outcomes, and only the third is a fault: the user denied consent,
    Google returned no code, or the exchange failed. The first two are normal
    and get a message rather than a stack trace.
    """
    if request.GET.get("error"):
        messages.error(
            request, f"Google refused the connection ({request.GET['error']})."
        )
        return redirect(_LIST)
    code = request.GET.get("code")
    state = request.GET.get("state")
    if not code or not state:
        messages.error(request, "Google returned no authorization code.")
        return redirect(_LIST)
    try:
        channel = complete_oauth(
            code, state=state, redirect_uri=_redirect_uri(request)
        )
    except CredentialError as exc:
        messages.error(request, str(exc))
        return redirect(_LIST)
    messages.success(request, f"Connected {channel.title or channel.channel_id}.")
    return redirect(_LIST)


# --- helpers -----------------------------------------------------------------


def _channel_row(channel) -> dict:
    """One channel plus its health, computed by the module that owns it.

    `token_health` is called rather than the stored column read directly,
    because it applies the state machine (terminal states win) and the
    expiry window — the page must not reimplement either.
    """
    return {
        "channel": channel,
        "health": token_health(channel),
        "client": channel.google_client,
        "pending": channel.channel_id.startswith(PENDING_CHANNEL_PREFIX),
    }


def _client_form(post) -> dict:
    """Read the shared client fields. Blank means "unchanged", not "cleared"."""
    raw_cap = (post.get("daily_upload_cap") or "").strip()
    try:
        cap = max(1, int(raw_cap)) if raw_cap else 6
    except ValueError:
        cap = 1
    return {
        "label": (post.get("label") or "").strip(),
        "client_id": (post.get("client_id") or "").strip(),
        # Not `.strip()`ed: a secret may legitimately contain a space, and
        # trimming it would store a different secret than the one typed.
        "client_secret": post.get("client_secret") or "",
        "cap": cap,
    }


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _find(request, pk, rows, kind: str):
    """Look the row up **within the request's workspace**, or say so and stop.

    Tenant scoping happens here rather than in a `get(pk=…)`: a row from
    another workspace must read as "not found", never as a 403 that confirms
    it exists.
    """
    for row in rows:
        if row.pk == pk:
            return row
    messages.error(request, f"No {kind} {pk} in this workspace.")
    return None


def _redirect_uri(request: HttpRequest) -> str:
    """The exact URL Google will redirect to, derived from this request.

    Built rather than configured, so a deployment on any host or port agrees
    with itself — a mismatch here is the classic `redirect_uri_mismatch`.
    """
    return request.build_absolute_uri(reverse("credentials:oauth_callback"))

