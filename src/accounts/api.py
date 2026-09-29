from __future__ import annotations

"""
accounts.api — Public Interface Contract for the Accounts Module.

The single access helper (docs/02 §2, D11): every view and service resolves
tenant scope through `current_workspace()`; there is no unscoped accessor, so
no query can cross tenants by accident.

v1 shape (D11): one default workspace, one `owner` membership. The roles and
the membership table exist so that activating multi-tenancy later is a feature
switch, not a migration.
"""

from typing import TYPE_CHECKING

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from accounts.models import Workspace, WorkspaceMember

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.http import HttpRequest

# Role hierarchy: owner > operator > viewer (docs/03 §3, docs/04 §9).
# In v1 only `owner` is active; the others are inert until needed.
ROLE_RANK = {
    WorkspaceMember.ROLE_VIEWER: 0,
    WorkspaceMember.ROLE_OPERATOR: 1,
    WorkspaceMember.ROLE_OWNER: 2,
}


def get_default_workspace() -> Workspace:
    """Return the single active workspace (v1: exactly one exists).

    Raises `Workspace.DoesNotExist` if the install-seeded workspace is
    missing — that is a broken installation, not a user error.
    """
    return Workspace.objects.filter(is_active=True).get()


def current_workspace(request: "HttpRequest") -> Workspace:
    """Resolve the tenant scope for this request — THE single access helper.

    Contract: `docs/04_ARCHITECTURE.md` §5, `docs/000_AI_SUPREME_PROTOCOL.md` §1.

    - Authenticated users resolve to the workspace they are a member of
      (v1: the single default workspace).
    - Anonymous users are rejected with `PermissionDenied`; views are expected
      to apply `login_required` first so this is defence in depth, not the
      primary redirect (D16: anonymous gets redirected to login, never a
      partial page).
    """
    user = getattr(request, "user", None)
    if user is None or isinstance(user, AnonymousUser) or not user.is_authenticated:
        raise PermissionDenied("Authentication required to resolve workspace scope.")

    membership = (
        WorkspaceMember.objects.filter(user=user, workspace__is_active=True)
        .order_by("created_at")
        .select_related("workspace")
        .first()
    )
    if membership is not None:
        return membership.workspace
    # Authenticated but no membership: fall back to the default workspace only
    # when the user is a superuser (install bootstrap), otherwise deny.
    if getattr(user, "is_superuser", False):
        return get_default_workspace()
    raise PermissionDenied("User has no active workspace membership.")


def require_role(
    user: "AbstractBaseUser | None", workspace: Workspace, role: str
) -> WorkspaceMember:
    """Enforce the role gate — the one place roles are checked (docs/04 §9).

    Args:
        user: The authenticated user (or None / AnonymousUser).
        workspace: The workspace the action targets.
        role: The minimum required role (`owner` | `operator` | `viewer`).

    Returns:
        The active `WorkspaceMember` when the user meets the requirement.

    Raises:
        PermissionDenied: user is anonymous, is not a member of `workspace`,
            or their role rank is below the required rank.
        KeyError: `role` is not a known role — a programming error, so it
            fails loudly in tests rather than silently allowing access.
    """
    if role not in ROLE_RANK:
        raise KeyError(
            f"Unknown role {role!r}; expected one of {sorted(ROLE_RANK)}."
        )
    if user is None or isinstance(user, AnonymousUser) or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    try:
        membership = WorkspaceMember.objects.select_related("workspace").get(
            user=user, workspace=workspace, workspace__is_active=True
        )
    except WorkspaceMember.DoesNotExist:
        raise PermissionDenied("User is not a member of this workspace.")

    if ROLE_RANK[membership.role] < ROLE_RANK[role]:
        raise PermissionDenied(
            f"Role {role!r} required; user has {membership.role!r}."
        )
    return membership


def role_required(role: str):
    """View decorator: login required + role check (D16, docs/04 §9).

    Anonymous requests are redirected to the login page by Django's
    `login_required`; authenticated users below `role` get 403 via
    `PermissionDenied`. Attaches the resolved scope as `request.workspace`
    so the view never re-derives tenant context.

    Recorded as a published-surface addition in docs/04 §6 (2026-09-28).
    """
    from functools import wraps

    from django.contrib.auth.decorators import login_required

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            workspace = current_workspace(request)
            require_role(request.user, workspace, role)
            request.workspace = workspace
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def get_workspace(workspace_id) -> Workspace | None:
    """Resolve a workspace by primary key, or `None`.

    Exists for the U12 `RetentionOracle`, which is handed a workspace *id* (it
    is a port, so it cannot see model instances) and must still hand a real
    `Workspace` to the sibling APIs that scope by tenant.
    """
    return Workspace.objects.filter(pk=workspace_id).first()


__all__ = [
    "ROLE_RANK",
    "current_workspace",
    "get_default_workspace",
    "get_workspace",
    "require_role",
    "role_required",
]