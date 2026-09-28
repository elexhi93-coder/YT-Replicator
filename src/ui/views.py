"""ui.views — the project shell's only views (U03).

Home (login-required, workspace context in the header slot) plus the
unauthenticated liveness probe. Domain pages arrive in Wave 4 (U16-U22);
nothing here downloads, uploads, or claims work (docs/04 §7).
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from accounts.api import current_workspace


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Status-at-a-glance placeholder. Full Home ships in U22 (ops data)."""
    workspace = current_workspace(request)
    return render(
        request,
        "ui/home.html",
        {"workspace": workspace},
    )


def healthz(request: HttpRequest) -> JsonResponse:
    """Unauthenticated liveness probe for orchestrators (docs/04 §10.1).

    U03 checks DB connectivity only (`SELECT 1`). Disk floor and master-key
    checks join when `ops`/`media` land (their modules own those facts);
    the 200/503 shape is stable from day one.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # never leak internals to the probe
        return JsonResponse(
            {"status": "unhealthy", "reason": "database unreachable"},
            status=503,
        )
    return JsonResponse({"status": "healthy"})
