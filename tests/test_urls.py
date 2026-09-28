"""Shared test URLconf (U02 shell harness, extended in U03).

U03 ships the real project shell (`ui.urls`: home, healthz, login, logout).
The suite's ROOT_URLCONF includes it first so `reverse("home")` and
`reverse("healthz")` resolve in tests; the dummy login route stays as a
fallback so `login_required` redirects keep reversing even if the shell
is unavailable.
"""

from django.urls import include, path


urlpatterns = [
    path("", include("ui.urls")),
]
