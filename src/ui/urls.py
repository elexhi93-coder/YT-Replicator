"""ui.urls — the project's single URLconf (U03).

Named routes only (docs/04 §8.3): no template or view hardcodes a path, so
adding a tenant prefix later (`/w/<slug>/...`) is a change here alone.
`app_name = "ui"` is intentionally absent: page route names (`home`,
`pipelines:list`, ...) are global and stable for `{% url %}` lookups.
"""

from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.urls import include, path

from ui.pages import credentials as credentials_views
from ui.views import healthz, home

#: The Credentials page (U16) in its own namespace, so `{% url 'credentials:list' %}`
#: is the only place the name appears (docs/04 §8.3).
#:
#: Only shipped pages are registered. `visible_nav()` deliberately hides any link
#: whose route will not reverse ("hide the link rather than rendering a URL that
#: cannot resolve"), so adding a placeholder here would put a dead link in the
#: sidebar — the opposite of what the shell is for.
_credentials_urls = (
    [
        path("", credentials_views.credentials_page, name="list"),
        path("clients/add/", credentials_views.add_client, name="client_add"),
        path(
            "clients/<int:pk>/edit/",
            credentials_views.edit_client,
            name="client_edit",
        ),
        path(
            "clients/<int:pk>/toggle/",
            credentials_views.toggle_client,
            name="client_toggle",
        ),
        path(
            "channels/connect/",
            credentials_views.connect_channel,
            name="channel_connect",
        ),
        path(
            "channels/<int:pk>/reconnect/",
            credentials_views.reconnect_channel,
            name="channel_reconnect",
        ),
        path(
            "channels/<int:pk>/disconnect/",
            credentials_views.disconnect_channel,
            name="channel_disconnect",
        ),
        path(
            "oauth/callback/",
            credentials_views.oauth_callback,
            name="oauth_callback",
        ),
    ],
    "credentials",
)

urlpatterns = [
    path("", home, name="home"),
    path("healthz", healthz, name="healthz"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="ui/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("credentials/", include(_credentials_urls, namespace="credentials")),
]
