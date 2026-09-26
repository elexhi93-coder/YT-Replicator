# SESSION TASK — Step 3.4: Queue Page + SSE Live Updates

## Your job in this session
Build `dashboard/templates/queue.html` — a live-updating job queue display powered by Server-Sent Events (SSE).

## Read these files first (in this order):
1. `docs/DASHBOARD_SPEC.md` — section: "Queue Page"
2. `docs/API_CONTRACTS.md` — sections: `GET /api/queue` and `GET /api/events` (SSE)
3. `docs/DATABASE_SCHEMA.md` — `download_jobs`, `process_jobs`, `upload_jobs` tables and their status enums
4. `dashboard/app.py` — the `/api/events` SSE route and `/api/queue` route

## Hard constraints:
- SSE must use native `EventSource` JavaScript API (built into browsers — no library needed)
- The SSE endpoint at `/api/events` must already exist in `app.py` (implement it fully now if stub)
- Queue auto-refreshes every 2 seconds via SSE — NOT polling with HTMX `hx-trigger="every 2s"`
  (SSE is more efficient and doesn't hammer the server)
- No websockets, no socket.io
- Tailwind for all styling

## File to build:
`dashboard/templates/queue.html`

## SSE endpoint — implement fully in `app.py` if not done:
```python
@app.route('/api/events')
def sse_events():
    def generate():
        while True:
            jobs = query_active_jobs()  # SELECT from download_jobs WHERE status IN (...)
            data = json.dumps({"jobs": jobs, "count": len(jobs)})
            yield f"data: {data}\n\n"
            time.sleep(2)
    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
```

## What the queue page must show:

### Stats bar (top)
4 stat cards showing live counts:
- Queued (yellow)
- Downloading (blue, with progress)
- Processing (purple)
- Uploading (green)

Counts update live via SSE.

### Job table
Columns: Job ID | Channel | Video Title | Stage | Progress | Started | Actions

Stage pipeline visualization per row:
```
[Download ●] → [Process ○] → [Upload ○]
```
Filled circle = complete, outline = pending, spinning = in-progress.

Progress column: `████░░░░ 45%` style bar (use Tailwind `w-[45%]` inline style from SSE data).

Actions column:
- Cancel button (only for `queued` jobs) → `hx-delete="/api/jobs/<id>"`
- Retry button (only for `failed` jobs) → `hx-post="/api/jobs/<id>/retry"`

### Empty state
When no active jobs: centered message "No active jobs. Pipelines are idle."

## JavaScript required (inline in `{% block scripts %}`):
```javascript
const evtSource = new EventSource('/api/events');
evtSource.onmessage = function(event) {
    const data = JSON.parse(event.data);
    updateQueueTable(data.jobs);
    updateStatCards(data);
};
```

`updateQueueTable(jobs)` replaces the `<tbody id="queue-body">` innerHTML with rendered rows.
`updateStatCards(data)` updates the count badges.

## Test / pass criteria:
1. Open `http://localhost:8080/queue`
2. Stats bar shows (all zeros if no active jobs)
3. Open browser DevTools → Network → Filter: EventSource — must show `/api/events` as active connection
4. Manually insert a row into `download_jobs` via SQLite browser or Python
5. Within 2 seconds, the row appears in the queue without a page reload

## When done:
- Show `queue.html` (full)
- Show the SSE route implementation in `app.py`
- Show DevTools screenshot description confirming EventSource connection
- Do NOT build anything else in this session
