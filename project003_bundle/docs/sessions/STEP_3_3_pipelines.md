# SESSION TASK — Step 3.3: Pipelines Page (Full HTMX)

## Your job in this session
Build out `dashboard/templates/pipelines.html` — the main management page for pipelines, sources, and destinations.

## Read these files first (in this order):
1. `docs/DASHBOARD_SPEC.md` — section: "Pipelines Page"
2. `docs/API_CONTRACTS.md` — all `/api/pipelines/*`, `/api/sources/*`, `/api/destinations/*` endpoints
3. `dashboard/templates/base.html` — the layout you must extend
4. `dashboard/app.py` — to verify which routes are already implemented

## Hard constraints:
- HTMX only for all dynamic interactions — no custom JavaScript fetch() calls
- All forms use `hx-post`, `hx-put`, `hx-delete` and `hx-target` / `hx-swap`
- No page reloads — all interactions are partial HTML swaps
- Tailwind for all styling (CDN, no build step)
- Must work with the API routes already in `app.py`

## File to rebuild:
`dashboard/templates/pipelines.html`

## Also create these HTMX partial templates:
- `dashboard/templates/partials/pipeline_list.html` — the `<ul>` of pipeline cards
- `dashboard/templates/partials/pipeline_card.html` — single pipeline card (name, status, source count, dest count, actions)
- `dashboard/templates/partials/source_list.html` — sources list within a pipeline detail panel
- `dashboard/templates/partials/destination_list.html` — destinations list

## What the page must contain:

### Header row
- Title "Pipelines"
- "New Pipeline" button → opens an inline form (HTMX swap into `#new-pipeline-form`)

### New Pipeline inline form (hidden by default)
- Input: Pipeline name
- Submit → `hx-post="/api/pipelines"` → on success, refreshes the pipeline list and hides the form
- Cancel button → hides form

### Pipeline list
- Loaded on page load: `hx-get="/api/pipelines"` `hx-trigger="load"` `hx-target="#pipeline-list"`
- Each pipeline card shows:
  - Pipeline name (editable inline on click)
  - Status badge (active/paused — toggle on click → `hx-put`)
  - "X sources, Y destinations" count
  - Expand/collapse to show sources + destinations inline
  - Delete button with confirm dialog → `hx-delete` with `hx-confirm="Are you sure?"`
  - "Run Now" button → `hx-post="/api/pipelines/<id>/run"`

### Sources panel (inside expanded pipeline)
- List of sources with: platform icon, channel name, enabled toggle
- "Add Source" form: platform select (youtube/twitch/vimeo), channel ID input, interval input
- Delete source button per row

### Destinations panel (inside expanded pipeline)
- List of destinations with: platform, name, enabled toggle
- "Add Destination" form: platform select (youtube/dailymotion/facebook/tiktok), label input
- Delete destination button per row

## App.py additions needed:
Add these routes to return HTML partials (not JSON) when `HX-Request` header is present:
- `GET /api/pipelines` must also handle `hx-request` and return partial HTML
  OR create separate routes like `GET /partials/pipeline-list`

Use whichever pattern you prefer, but be consistent.

## Test / pass criteria:
1. Open `http://localhost:8080/pipelines`
2. Click "New Pipeline" → form appears without page reload
3. Type a name and submit → pipeline card appears in the list
4. Click pipeline card → sources and destinations panels expand
5. Add a source → source row appears
6. Delete the pipeline → it disappears with confirmation prompt

## When done:
- Show `pipelines.html` (full)
- Show all partial templates
- Note any changes made to `app.py`
- Do NOT build anything else in this session
