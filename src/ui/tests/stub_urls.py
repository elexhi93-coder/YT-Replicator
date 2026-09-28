"""Stub URLconf exposing every NAV route so visible_nav() role filtering can
be tested with all names reversible (test-only; real pages ship in U16-U22).
"""

from __future__ import annotations

from django.http import HttpResponse
from django.urls import include, path


def _stub(request):  # pragma: no cover - test harness only
    return HttpResponse("stub")


pipelines_urls = (  # namespace "pipelines"
    [path("list/", _stub, name="list")],
    "pipelines",
)
queue_urls = ([path("list/", _stub, name="list")], "queue")
library_urls = ([path("list/", _stub, name="list")], "library")
history_urls = ([path("list/", _stub, name="list")], "history")
sources_urls = ([path("list/", _stub, name="list")], "sources")
catalog_urls = ([path("", _stub, name="index")], "catalog")
credentials_urls = ([path("list/", _stub, name="list")], "credentials")
ops_urls = ([path("logs/", _stub, name="logs")], "ops")
settings_urls = ([path("", _stub, name="index")], "settings")

urlpatterns = [
    path("pipelines/", include(pipelines_urls, namespace="pipelines")),
    path("queue/", include(queue_urls, namespace="queue")),
    path("library/", include(library_urls, namespace="library")),
    path("history/", include(history_urls, namespace="history")),
    path("sources/", include(sources_urls, namespace="sources")),
    path("catalog/", include(catalog_urls, namespace="catalog")),
    path("credentials/", include(credentials_urls, namespace="credentials")),
    path("ops/", include(ops_urls, namespace="ops")),
    path("settings/", include(settings_urls, namespace="settings")),
]
