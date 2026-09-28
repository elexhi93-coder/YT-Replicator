"""Minimal URLconf for the test suite only (U02).

Provides a dummy login route so `login_required` redirects can reverse
`settings.LOGIN_URL` without the real project shell (U03 `ui` module).
"""

from django.http import HttpResponse
from django.urls import path


def _dummy_login(request):  # pragma: no cover - test harness only
    return HttpResponse("login")


urlpatterns = [path("login/", _dummy_login, name="login")]
