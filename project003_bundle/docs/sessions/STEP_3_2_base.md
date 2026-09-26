# SESSION TASK — Step 3.2: Base HTML Template + Navigation

## Your job in this session
Create `dashboard/templates/base.html` — the shared layout used by all pages.

## Read these files first:
1. `docs/DASHBOARD_SPEC.md` — sections: "Layout", "Design System", "Navigation"
2. `dashboard/app.py` — to know what page routes exist (`/pipelines`, `/queue`, `/history`, `/logs`)

## Hard constraints:
- Tailwind CSS via CDN only: `<script src="https://cdn.tailwindcss.com"></script>`
- HTMX via CDN: `<script src="https://unpkg.com/htmx.org@1.9.10"></script>`
- NO build step, NO npm, NO webpack
- GitHub dark color scheme: background `#0d1117`, surface `#161b22`, border `#30363d`, text `#e6edf3`, accent `#58a6ff`
- Navigation must highlight the current active page
- Must include a `<div id="toast-container">` for flash messages
- Block structure: `{% block title %}`, `{% block content %}`, `{% block scripts %}`
- Must be valid Jinja2 template syntax

## File to create:
`dashboard/templates/base.html`

## Layout structure:
```
<html>
  <head>
    Tailwind CDN, HTMX CDN, custom CSS vars, title block
  </head>
  <body style="background: #0d1117">
    <nav>  ← fixed top navigation
      Logo: "project003" (left)
      Links: Pipelines | Queue | History | Logs (center/right)
      Active link highlighted with #58a6ff underline
    </nav>
    <main class="pt-16 px-4">  ← padded below nav
      {% block content %}{% endblock %}
    </main>
    <div id="toast-container" class="fixed bottom-4 right-4 flex flex-col gap-2">
    </div>
    {% block scripts %}{% endblock %}
  </body>
</html>
```

## Also create these stub templates (each extends base.html):

### `dashboard/templates/pipelines.html`
```html
{% extends "base.html" %}
{% block title %}Pipelines — project003{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold text-white mb-6">Pipelines</h1>
<p class="text-gray-400">Coming soon — Step 3.3</p>
{% endblock %}
```

### `dashboard/templates/queue.html`
Same stub, title "Queue", note "Coming soon — Step 3.4"

### `dashboard/templates/history.html`
Same stub, title "History", note "Coming soon — Step 3.5"

### `dashboard/templates/logs.html`
Same stub, title "Logs", note "Coming soon — Step 3.6"

## Test / pass criteria:
Run `dashboard/app.py`, open `http://localhost:8080/pipelines` in a browser.
Should show:
- Dark background
- Navigation bar with 4 links
- "Pipelines" link highlighted
- "Coming soon" message in content area
- No console errors

## When done:
- Show `base.html` (full)
- Show one stub template as example
- Describe what the browser renders
- Do NOT build anything else in this session
