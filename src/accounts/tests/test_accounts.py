from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from accounts.api import (
    ROLE_RANK,
    current_workspace,
    get_default_workspace,
    require_role,
    role_required,
)
from accounts.models import Workspace, WorkspaceMember

pytestmark = pytest.mark.django_db


def make_user(username: str = "u", **kwargs) -> User:
    return User.objects.create_user(username=username, **kwargs)


def make_member(workspace: Workspace, user: User, role: str) -> WorkspaceMember:
    return WorkspaceMember.objects.create(
        workspace=workspace, user=user, role=role
    )


class TestWorkspaceModel:
    def test_default_workspace_seeded_by_migration(self):
        # docs/03 §11: exactly one default workspace row at install.
        ws = get_default_workspace()
        assert ws.slug == "default"
        assert ws.is_active is True
        assert Workspace.objects.count() == 1

    def test_slug_unique(self):
        ws = get_default_workspace()
        with pytest.raises(Exception):
            Workspace.objects.create(name="Dup", slug=ws.slug)


class TestWorkspaceMember:
    def test_membership_unique_per_workspace_user(self):
        ws = get_default_workspace()
        user = make_user()
        make_member(ws, user, WorkspaceMember.ROLE_OWNER)
        with pytest.raises(Exception):
            make_member(ws, user, WorkspaceMember.ROLE_VIEWER)

    def test_role_check_constraint_rejects_unknown_role(self):
        ws = get_default_workspace()
        user = make_user()
        with pytest.raises(Exception):
            make_member(ws, user, "superadmin")

    def test_role_choices_are_documented_trio(self):
        assert [c[0] for c in WorkspaceMember.ROLE_CHOICES] == [
            "owner",
            "operator",
            "viewer",
        ]


class TestCurrentWorkspace:
    def test_member_resolves_membership_workspace(self):
        ws = get_default_workspace()
        user = make_user()
        make_member(ws, user, WorkspaceMember.ROLE_OPERATOR)
        request = RequestFactory().get("/")
        request.user = user
        assert current_workspace(request) == ws

    def test_anonymous_denied(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        with pytest.raises(PermissionDenied):
            current_workspace(request)

    def test_authenticated_non_member_denied(self):
        request = RequestFactory().get("/")
        request.user = make_user()
        with pytest.raises(PermissionDenied):
            current_workspace(request)

    def test_superuser_without_membership_bootstraps_to_default(self):
        # Install path: createsuperuser before any membership row exists.
        request = RequestFactory().get("/")
        request.user = User.objects.create_superuser("root", "r@x.io", "pw")
        assert current_workspace(request) == get_default_workspace()


class TestRequireRole:
    def test_owner_meets_every_role(self):
        ws = get_default_workspace()
        user = make_user("a")
        make_member(ws, user, WorkspaceMember.ROLE_OWNER)
        for required in ("owner", "operator", "viewer"):
            assert require_role(user, ws, required) is not None

    def test_operator_meets_operator_and_viewer_but_not_owner(self):
        ws = get_default_workspace()
        user = make_user("b")
        make_member(ws, user, WorkspaceMember.ROLE_OPERATOR)
        assert require_role(user, ws, "operator")
        assert require_role(user, ws, "viewer")
        with pytest.raises(PermissionDenied):
            require_role(user, ws, "owner")

    def test_viewer_meets_only_viewer(self):
        ws = get_default_workspace()
        user = make_user("c")
        make_member(ws, user, WorkspaceMember.ROLE_VIEWER)
        assert require_role(user, ws, "viewer")
        with pytest.raises(PermissionDenied):
            require_role(user, ws, "operator")

    def test_non_member_denied(self):
        ws = get_default_workspace()
        with pytest.raises(PermissionDenied):
            require_role(make_user("d"), ws, "viewer")

    def test_anonymous_denied(self):
        ws = get_default_workspace()
        with pytest.raises(PermissionDenied):
            require_role(None, ws, "viewer")
        with pytest.raises(PermissionDenied):
            require_role(AnonymousUser(), ws, "viewer")

    def test_unknown_role_fails_loudly(self):
        # A typo'd required role must never silently grant access.
        ws = get_default_workspace()
        user = make_user("e")
        make_member(ws, user, WorkspaceMember.ROLE_OWNER)
        with pytest.raises(KeyError):
            require_role(user, ws, "root")

    def test_role_rank_ordering(self):
        assert ROLE_RANK["owner"] > ROLE_RANK["operator"] > ROLE_RANK["viewer"]


class TestRoleRequiredDecorator:
    def _session_request(self, path: str = "/"):
        from django.contrib.sessions.backends.db import SessionStore

        request = RequestFactory().get(path)
        request.session = SessionStore()
        return request

    def test_anonymous_redirected_to_login(self):
        from django.conf import settings
        from django.contrib.auth import REDIRECT_FIELD_NAME

        @role_required("viewer")
        def my_view(request):
            return "ok"

        request = self._session_request("/secret/")
        request.user = AnonymousUser()
        response = my_view(request)
        assert response.status_code == 302
        assert settings.LOGIN_URL in response.url
        assert REDIRECT_FIELD_NAME in response.url

    def test_authenticated_member_gets_workspace_attached(self):
        from django.http import HttpResponse

        ws = get_default_workspace()
        user = make_user("f")
        make_member(ws, user, WorkspaceMember.ROLE_OWNER)

        @role_required("operator")
        def my_view(request):
            return HttpResponse(request.workspace.slug)

        request = self._session_request()
        request.user = user
        response = my_view(request)
        assert response.status_code == 200
        assert response.content == b"default"

    def test_insufficient_role_denied(self):
        ws = get_default_workspace()
        user = make_user("g")
        make_member(ws, user, WorkspaceMember.ROLE_VIEWER)

        @role_required("owner")
        def my_view(request):
            raise AssertionError("view must not run")

        request = self._session_request()
        request.user = user
        with pytest.raises(PermissionDenied):
            my_view(request)