"""Navigation as data, never markup (docs/04 §8.2, D17).

A loop in base.html renders NAV; `current()` highlights the active item.
Groups reference Django named routes (docs/04 §8.3) with a minimum role
(docs/04 §9). v1 renders Home + the three groups below; Administration is
reserved (absent in v1) and arrives by appending one NavGroup.

Roles are inert until the owning modules ship their pages (Wave 4 U16-U22);
filtering by role today only hides items the user's rank cannot use.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NavItem:
    """One link: label, Django named route, minimum role to see it."""

    label: str
    route: str
    roles: str = "viewer"


@dataclass(frozen=True)
class NavGroup:
    """One named section of links."""

    title: str
    items: tuple["NavItem", ...] = field(default_factory=tuple)

    def __init__(self, title: str, items: list["NavItem"] | tuple["NavItem", ...]):
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "items", tuple(items))


RANK = {"viewer": 0, "operator": 1, "owner": 2}

NAV: tuple[NavGroup, ...] = (
    NavGroup(
        "Work",
        [
            NavItem("Pipelines", "pipelines:list", roles="operator"),
            NavItem("Queue", "queue:list", roles="operator"),
            NavItem("Library", "library:list", roles="viewer"),
            NavItem("History", "history:list", roles="viewer"),
        ],
    ),
    NavGroup(
        "Content",
        [
            NavItem("Sources", "sources:list", roles="operator"),
            NavItem("Catalog", "catalog:index", roles="viewer"),
        ],
    ),
    NavGroup(
        "Operations",
        [
            NavItem("Credentials", "credentials:list", roles="owner"),
            NavItem("Logs", "ops:logs", roles="owner"),
            NavItem("Settings", "settings:index", roles="owner"),
        ],
    ),
    # NavGroup("Administration", [...])  <- reserved, absent in v1 (docs/04 §8.2).
)


def visible_nav(role: str) -> tuple[NavGroup, ...]:
    """Return the NAV groups whose items `role` may see (unknown role: empty).

    Items whose named route does not reverse yet (owning module not shipped,
    Wave 4 U16-U22) are skipped: the shell must render today without every
    page existing, per U03's "shell first, pages later" order. Under
    ``ui.tests.stub_urls`` every route reverses, so role filtering is fully
    exercised there.
    """
    from django.urls import NoReverseMatch, reverse

    if role not in RANK:
        return ()
    rank = RANK[role]
    visible: list[NavGroup] = []
    for group in NAV:
        items: list[NavItem] = []
        for item in group.items:
            if RANK.get(item.roles, 99) > rank:
                continue
            try:
                reverse(item.route)
            except NoReverseMatch:
                # Owning module hasn't shipped its page yet — hide the link
                # rather than rendering a URL that cannot resolve.
                continue
            except Exception:
                # No URLconf loaded at all (pure unit context): keep the item;
                # reversibility is checked under stub_urls in tests.
                pass
            items.append(item)
        if items:
            visible.append(NavGroup(group.title, tuple(items)))
    return tuple(visible)


def all_nav_labels() -> list[str]:
    """Every label in NAV regardless of role/route (tests §8.2 data shape)."""
    return [item.label for group in NAV for item in group.items]
