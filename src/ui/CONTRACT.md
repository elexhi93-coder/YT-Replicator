# ui.CONTRACT — Project Shell (U03)

**Module:** `ui` · **Status:** Shell complete (pages arrive in Wave 4, U16–U22)

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
render, no hardcoded URLs in templates. Plus global
`tests/test_module_boundaries.py` and `tests/test_module_size.py` (U04).

## 5. Out of scope

All domain pages (Wave 4 U16–U22 own their routes/views); Home becomes
status-at-a-glance in U22; `Administration` nav group is reserved, absent in v1.
