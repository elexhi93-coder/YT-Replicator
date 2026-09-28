"""U03 shell tests: base.html blocks, NAV-as-data, /healthz, auth gating.

Covers docs/04 §8.1 (four blocks), §8.2 (NAV as data), §8.3 (named routes
only), §8.5 (Tailwind + HTMX via CDN, no build step), §8.6 (context slot)
and D16 (anonymous → login redirect).
"""

from __future__ import annotations

import pytest
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.api import get_default_workspace
from django.apps import apps
from django.contrib.auth import get_user_model

from ui.nav import NAV, NavGroup, NavItem, all_nav_labels, visible_nav


@override_settings(
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": ["src/ui/templates"],
            "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                    "ui.context_processors.nav_context",
                ],
            },
        }
    ],
)
class ShellTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="op", password="pw")
        self.ws = get_default_workspace()
        WorkspaceMember = apps.get_model("accounts", "WorkspaceMember")
        WorkspaceMember.objects.create(
            user=self.user, workspace=self.ws, role="owner"
        )
        self.client = Client()

    def test_nav_groups_match_architecture_section_82(self):
        assert [g.title for g in NAV] == ["Work", "Content", "Operations"]
        assert isinstance(NAV[0], NavGroup) and isinstance(NAV[0].items[0], NavItem)
        # Full NAV is data-complete even though no route reverses yet (U16+).
        assert set(all_nav_labels()) == {
            "Pipelines", "Queue", "Library", "History",
            "Sources", "Catalog", "Credentials", "Logs", "Settings",
        }

    def test_visible_nav_filters_by_role_rank(self):
        # Under ui.urls no domain page ships yet → every NAV item is hidden
        # (NoReverseMatch skip). Role filtering itself is covered below under
        # stub_urls where every route reverses.
        assert visible_nav("viewer") == ()
        assert visible_nav("owner") == ()
        assert visible_nav("nobody") == ()

    def test_healthz_unauthenticated_and_healthy(self):
        response = self.client.get(reverse("healthz"))
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_home_requires_login_redirect_not_partial(self):
        response = self.client.get(reverse("home"))
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_home_renders_four_blocks_and_context_slot(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "Default Workspace" in content  # context slot (04 §8.6)
        assert "<nav" in content  # nav block (04 §8.1)
        assert "Liveness probe" in content
        assert "cdn.tailwindcss.com" in content  # 04 §8.5 theme via CDN
        assert "htmx.org" in content

    def test_no_hardcoded_urls_in_templates(self):
        import re
        from pathlib import Path

        for tpl in (Path("src/ui/templates/ui")).glob("*.html"):
            text = tpl.read_text(encoding="utf-8")
            hrefs = re.findall(r'href="([^"{%]+?)"', text)
            hardcoded = [
                h
                for h in hrefs
                if h.startswith("/") and not h.startswith("https://")
            ]
            assert not hardcoded, f"{tpl.name} hardcodes URL(s): {hardcoded}"


@pytest.mark.django_db
def test_healthz_unhealthy_shape_on_db_failure(client, monkeypatch):
    from django.db import connection

    class _BadCursor:
        def __enter__(self):
            raise RuntimeError("db down")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(connection, "cursor", lambda: _BadCursor())
    response = client.get(reverse("healthz"))
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


@override_settings(ROOT_URLCONF="ui.tests.stub_urls")
class VisibleNavRoleTests(TestCase):
    """visible_nav() role filtering with every NAV route reversible (§8.2)."""

    def test_viewer_sees_library_not_pipelines(self):
        viewer_labels = [i.label for g in visible_nav("viewer") for i in g.items]
        assert "Library" in viewer_labels
        assert "Pipelines" not in viewer_labels

    def test_owner_sees_credentials(self):
        owner_labels = [i.label for g in visible_nav("owner") for i in g.items]
        assert "Credentials" in owner_labels
