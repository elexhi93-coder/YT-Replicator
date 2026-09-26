# SESSION TASK — Step 3.5: History Page + Filters

## Your job in this session
Build `dashboard/templates/history.html` — completed/failed job history with pagination and filters.

## Read these files first:
1. `docs/DASHBOARD_SPEC.md` — section: "History Page"
2. `docs/API_CONTRACTS.md` — section: `GET /api/history`
3. `dashboard/app.py` — the `/api/history` route

## Hard constraints:
- Pagination via HTMX: `hx-get="/api/history?page=2"` `hx-target="#history-table"` `hx-push-url="true"`
- Filters use HTMX: filter form submits with `hx-get` replacing table content
- Default: 50 rows per page
- Tailwind for all styling

## File to build:
`dashboard/templates/history.html`

## What the page must show:

### Filter bar
Inline filter form:
- Status filter: dropdown (All / Completed / Failed / Cancelled)
- Pipeline filter: dropdown populated from `GET /api/pipelines`
- Date range: two date inputs (from / to)
- "Filter" button → `hx-get="/api/history"` with all filter params → `hx-target="#history-table"`
- "Clear" button → resets filters and reloads

### History table
Columns: Date | Pipeline | Channel | Video Title | Status | Duration | Actions

- Date: human-friendly "2 hours ago" format (use Python `timeago` or just format in Jinja)
- Status badge: green "Completed" / red "Failed" / gray "Cancelled"
- Duration: total time from job created to final status
- Actions: "Retry" button for failed jobs only → `hx-post="/api/jobs/<id>/retry"`

### Pagination
Bottom of table:
```
← Prev  Page 2 of 14  Next →
```
Each page link uses HTMX to swap the table without reloading the page.

### Empty state
"No history yet." centered message with icon.

## API route — ensure this is implemented in `app.py`:
```python
@app.route('/api/history')
def api_history():
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    status = request.args.get('status')
    pipeline_id = request.args.get('pipeline_id')
    # date_from, date_to optional
    # Query download_jobs JOIN sources JOIN pipelines
    # Return JSON: {"jobs": [...], "total": N, "page": P, "pages": X}
```

## Test / pass criteria:
1. Open `http://localhost:8080/history`
2. Shows filter bar and empty state (or table if jobs exist)
3. Change status filter to "Failed" → table reloads without full page reload
4. Pagination links work (if enough rows exist)

## When done:
- Show `history.html` (full)
- Note any changes to `app.py`
- Do NOT build anything else in this session
