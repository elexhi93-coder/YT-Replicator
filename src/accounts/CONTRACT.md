"""accounts.CONTRACT — Published interface of the Accounts Module (U02).

Owners: workspace, workspace_member, and the single access helper.
May import: core.api only (docs/04 §3). Nothing else.
"""

# 1. Public surface — import ONLY via `accounts.api` (INV-12)

| Symbol | Signature | Behaviour |
|---|---|---|
| `ROLE_RANK` | `dict[str, int]` | Role hierarchy `viewer < operator < owner` (docs/04 §9); single place the rank is defined. |
| `get_default_workspace()` | `() -> Workspace` | The single active workspace (v1; exactly one exists). Raises `Workspace.DoesNotExist` when missing (broken install). |
| `current_workspace(request)` | `(HttpRequest) -> Workspace` | THE single access helper (D11, docs/04 §5): member's active workspace; anonymous → `PermissionDenied` (views apply `login_required` first as the primary redirect, D16); authenticated non-member → `PermissionDenied` except superuser bootstrap to the default workspace. |
| `require_role(user, workspace, role)` | `(user, Workspace, str) -> WorkspaceMember` | The one place roles are checked (docs/04 §9): returns the active membership when rank suffices; anonymous/non-member/under-ranked → `PermissionDenied`; unknown `role` → `KeyError` (fails loudly). |
| `role_required(role)` | `(str) -> decorator` | Login required + role gate; attaches scope as `request.workspace` (§6 row 2026-09-28). Anonymous → redirect to `LOGIN_URL`; below role → 403. |

Models (`Workspace`, `WorkspaceMember`) are used within the module and via
Django's app registry elsewhere; cross-module Python access is only via the
five symbols above (INV-12: sibling access only via `<sibling>.api`; tests
use the registry / fixtures rather than importing `accounts.models`).

# 2. Errors

`django.core.exceptions.PermissionDenied` (anonymous, non-member, under-ranked),
`Workspace.DoesNotExist` (no default workspace — broken installation),
`KeyError` (unknown role string — programming error).

# 3. Tests

`src/accounts/tests/test_accounts.py` — 18 tests: seed row (§11), slug/unique/check
constraints, member/anonymous/non-member/superuser scoping, full role matrix,
unknown-role KeyError, decorator redirect/attach/deny. Plus global
`tests/test_module_boundaries.py` and `tests/test_module_size.py` (U04 already in
place: 12 modules, api-only imports along §3 arrows, acyclic, 600-line cap).

# 4. Out of scope

Multi-tenancy switching (v1 has one workspace), user registration / password
flows (Django auth), OAuth (credentials module owns it).
