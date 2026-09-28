"""ui.urls — the project's single URLconf (U03).

Named routes only (docs/04 §8.3): no template or view hardcodes a path, so
adding a tenant prefix later (`/w/<slug>/...`) is a change here alone.
`app_name = "ui"` is intentionally absent: page route names (`home`,
`pipelines:list`, ...) are global and stable for `{% url %}` lookups.
"""

from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.urls import path

from ui.views import healthz, home

urlpatterns = [
    path("", home, name="home"),
    path("healthz", healthz, name="healthz"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="ui/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
