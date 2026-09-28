"""ui.context_processors — workspace slot + data-driven NAV for every page.

Resolves the request's workspace through the single access helper
(`accounts.api.current_workspace`) and exposes `workspace`, `nav_groups`
(filtered by the user's top role), and `user_role`. Anonymous or
unscoped requests get an empty slot and no groups — the views themselves
enforce login (D16), this processor only decides what the header shows.
"""

from __future__ import annotations

from typing import Any

from accounts.api import ROLE_RANK, current_workspace
from ui.nav import RANK, visible_nav


def nav_context(request: Any) -> dict[str, Any]:
    """Inject `workspace`, `nav_groups`, and `user_role` into all templates."""
    try:
        workspace = current_workspace(request)
    except Exception:
        return {"workspace": None, "nav_groups": (), "user_role": None}

    user = getattr(request, "user", None)
    role = "viewer"
    membership = getattr(user, "memberships", None)
    if membership is not None:
        try:
            memberships = list(membership.filter(workspace=workspace))
            if memberships:
                role = max(memberships, key=lambda m: ROLE_RANK.get(m.role, -1)).role
        except Exception:
            role = "viewer"
    if role not in RANK:
        role = "viewer"
    # U03: no domain page exists yet, so visible_nav() is () — fall back to
    # an empty tuple (never full NAV: its routes would NoReverseMatch in the
    # template, see nav.visible_nav docstring). Groups appear with U16+.
    return {
        "workspace": workspace,
        "nav_groups": visible_nav(role),
        "user_role": role,
    }
