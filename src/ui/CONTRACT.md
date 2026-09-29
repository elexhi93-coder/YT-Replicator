# ui.CONTRACT — Project Shell (U03)

**Module:** `ui` · **Status:** Shell + Credentials complete (U03, U16; U17–U22 to come)

HTTP routes only. Publishes **no Python API** — nothing may import `ui`
(docs/04 §3/§5, `tests/test_module_boundaries.py`). May import any module's
`*.api` along the §3 arrows.

---

## 1. Routes (`ui.urls` — named routes only, docs/04 §8.3)

| Route name | Path | View | Auth |
|---|---|---|---|
| `home` | `/` | `ui.views.home` — Home placeholder | `login_required` (D16: anonymous → 302 to `LOGIN_URL`, never a partial page) |
| `healthz` | `/healthz` | `ui.views.healthz` — unauthenticated liveness probe (docs/04 §10.1) | none |
| `login` | `/login/` | Django `LoginView` (`ui/login.html`) | none |
| `logout` | `/logout/` | Django `LogoutView` | none |

### 1.1 Credentials page (U16) — namespace `credentials`

Every route is `role_required("owner")` (docs/04 §9), matching the nav item's
declared minimum: who can add a Google client can also spend its quota, so the
two go together.

| Route name | Path | View | Method |
|---|---|---|---|
| `credentials:list` | `/credentials/` | `ui.pages.credentials.credentials_page` | GET |
| `credentials:client_add` | `/credentials/clients/add/` | `.add_client` | POST |
| `credentials:client_edit` | `/credentials/clients/<pk>/edit/` | `.edit_client` | POST |
| `credentials:client_toggle` | `/credentials/clients/<pk>/toggle/` | `.toggle_client` | POST |
| `credentials:channel_connect` | `/credentials/channels/connect/` | `.connect_channel` | POST |
| `credentials:channel_reconnect` | `/credentials/channels/<pk>/reconnect/` | `.reconnect_channel` | POST |
| `credentials:channel_disconnect` | `/credentials/channels/<pk>/disconnect/` | `.disconnect_channel` | POST |
| `credentials:oauth_callback` | `/credentials/oauth/callback/` | `.oauth_callback` | GET |

The callback is a GET because Google redirects with one, so it is reachable by
anything; it trusts only the signed `state` and treats a denied consent, a
missing code, and a rejected exchange as messages rather than tracebacks.

**Invariants the page holds by delegating** (a view decides nothing):

- No secret is ever rendered (INV-1): a client row shows its `client_id` and
  *whether* a secret is stored, never the value. A blank secret field on edit
  means "keep the existing one".
- The health badge is `credentials.api.token_health`, the same function the
  worker uses, so the page cannot disagree with the process.
- Tenant scoping happens in `_find()` against the request's workspace, so a row
  in another workspace reads as "not found" — never a 403 that confirms it
  exists.
- The `redirect_uri` is built from the request
  (`request.build_absolute_uri(reverse("credentials:oauth_callback"))`), not
  configured, so a deployment on any host agrees with itself and cannot hit
  `redirect_uri_mismatch`.
- Editing a client never changes `is_active`; deactivation is its own explicit
  action, so an omitted checkbox cannot silently switch a client off.

No URL is hardcoded: every link uses `{% url %}`, so adding a tenant prefix
later (`/w/<slug>/…`) is a change in `ui/urls.py` alone.

## 2. Layout + navigation

- `ui/templates/ui/base.html` — the one layout (docs/04 §8.1, D17) with exactly
  four blocks: `context_slot`, `nav`, `page_header` (title/actions), `content`.
- `ui/nav.py` — navigation as data (docs/04 §8.2): `NAV` (`NavGroup`/`NavItem`
  with `label`, named `route`, minimum `roles`), rendered by a loop in
  `base.html`. `visible_nav(role)` filters by rank and skips routes that do not
  reverse yet (owning page not shipped — full NAV reverses under
  `ui.tests.stub_urls`). `all_nav_labels()` exposes the data shape for tests.
  As of U16 `credentials:list` is the first route that reverses, so it is the
  first link an owner actually sees.
- `ui/context_processors.py::nav_context` — injects `workspace` (via the single
  access helper `accounts.api.current_workspace`), `nav_groups` (filtered by the
  user's top role), and `user_role` into every template. Anonymous/unscoped →
  empty slot, no groups (views enforce login; this only decides the header).
- Theme: Tailwind + HTMX via CDN (docs/04 §8.5) — no build step, no JS
  framework.
- `ui/settings.py` — production settings: PostgreSQL via `DATABASE_URL`,
  fail-fast `DJANGO_SECRET_KEY` (dev fallback only when `DJANGO_DEBUG=1`),
  `secure/httponly/samesite=Lax` sessions (docs/04 §9). Tests keep using
  `tests/django_settings.py` (SQLite in-memory harness).
- `manage.py` / `ui/wsgi.py` — management entrypoint (worker + one-shot ops
  commands) and the gunicorn WSGI application (docs/04 §10.1).

## 3. Errors

`healthz`: `200 {"status": "healthy"}` on `SELECT 1`, else
`503 {"status": "unhealthy", "reason": "database unreachable"}` (never leaks
internals; DB/disk specifics join when `ops`/`media` land — the 200/503 shape
is stable). Views: anonymous on `home` → 302 to `LOGIN_URL`; unscoped member →
`PermissionDenied` (403) from `current_workspace`.

## 4. Tests

`src/ui/tests/test_shell.py` (+ `stub_urls.py`): NAV groups match docs/04 §8.2,
role filtering (`viewer` sees Library not Pipelines; `owner` sees Credentials),
`healthz` 200/503 shapes, Home login-redirect, four-blocks + context-slot
render, no hardcoded URLs in templates.

`src/ui/tests/test_credentials_page.py` (U16, 34 tests) — a thin page's tests
are about what the modules beneath cannot catch: owner-only access on every
route, POST-only mutation, tenant scoping reading as "not found", no secret in
any rendered page, and the OAuth callback's three ordinary failure modes.
Models in tests come from the app registry, never `accounts.models` (INV-12).

Plus global `tests/test_module_boundaries.py` and `tests/test_module_size.py` (U04).

## 5. Out of scope

All domain pages (Wave 4 U16–U22 own their routes/views); Home becomes
status-at-a-glance in U22; `Administration` nav group is reserved, absent in v1.
