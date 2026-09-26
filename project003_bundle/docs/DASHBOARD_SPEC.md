# Dashboard Specification
## project003 — UI Pages, Routes, and HTMX Patterns

**Status:** LOCKED  
**Framework:** Flask + HTMX + TailwindCSS (CDN)  
**Theme:** Dark (GitHub-style dark, consistent with current dashboard)  
**Port:** 8080

---

## 1. Layout and Navigation

### 1.1 Base Template (`base.html`)

All pages extend a single base template with:
- Top navigation bar with project name and active page indicator
- Main content area
- No sidebar (simple top-nav is sufficient for this tool)

**Nav links:**
```
[ Pipelines ] [ Queue ] [ History ] [ Logs ]
```

**Active state:** Current page link has a highlighted indicator.

**Tailwind classes pattern:**
```html
<nav class="bg-gray-900 border-b border-gray-700 px-6 py-3 flex items-center gap-6">
  <span class="text-white font-bold text-lg">project003</span>
  <a href="/pipelines" class="text-gray-300 hover:text-white ...">Pipelines</a>
  <a href="/queue"     class="text-gray-300 hover:text-white ...">Queue</a>
  <a href="/history"   class="text-gray-300 hover:text-white ...">History</a>
  <a href="/logs"      class="text-gray-300 hover:text-white ...">Logs</a>
</nav>
```

---

## 2. Page: Pipelines (`/pipelines`)

**Purpose:** The main configuration page. Create pipelines, add channels, add destinations, configure processing steps.

### 2.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│  Pipelines                              [+ New Pipeline] │
├─────────────────────────────────────────────────────────┤
│  ▼  Manhwa Fresh → Multi-Platform  [Edit] [Pause] [Delete]│
│                                                         │
│  ┌── Channels ─────────────────────────────┐           │
│  │  Manhwa Fresh   UCz3...  backfill  10/day  [Pause]  │
│  │  @FreshManhwa   @fresh   monitor   5/day   [Pause]  │
│  │  [+ Add Channel]                                    │
│  └─────────────────────────────────────────┘           │
│                                                         │
│  ┌── Destinations ──────────────────────────┐          │
│  │  YouTube    Main Channel   [webhook]  [Edit] [Del]  │
│  │  TikTok     Brand TikTok   [webhook]  [Edit] [Del]  │
│  │  [+ Add Destination]                               │
│  └─────────────────────────────────────────┘          │
│                                                         │
│  ┌── Processing Steps ──────────────────────┐          │
│  │  [Global]   0  trim       0s → 180s      [Edit][Del]│
│  │  [Global]   1  normalize  -14 LUFS       [Edit][Del]│
│  │  [YouTube]  0  crop       16:9 center    [Edit][Del]│
│  │  [TikTok]   0  crop       9:16 center    [Edit][Del]│
│  │  [+ Add Step]                                       │
│  └─────────────────────────────────────────┘          │
│                                                         │
│  ▶  K-Drama → YouTube Only  [Edit] [Pause] [Delete]    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Interactions (HTMX)

**Create pipeline:**
```html
<form hx-post="/api/pipelines" hx-target="#pipeline-list" hx-swap="beforeend">
  <input name="name" placeholder="Pipeline name" required>
  <button type="submit">Create</button>
</form>
```
On success: appends new pipeline accordion row. No page reload.

**Toggle pipeline accordion (expand/collapse):**
```html
<div hx-get="/fragments/pipeline-detail/1" hx-trigger="click" hx-target="#pipeline-1-detail" hx-swap="innerHTML">
```

**Add channel (inside expanded pipeline):**
```html
<form hx-post="/api/channels" hx-target="#channels-list-1" hx-swap="beforeend">
  <input name="pipeline_id" value="1" type="hidden">
  <input name="url" placeholder="YouTube channel URL">
  <input name="name" placeholder="Display name">
  <select name="mode">
    <option value="monitor">Monitor (new videos only)</option>
    <option value="backfill">Backfill (full history first)</option>
  </select>
  <input name="daily_limit" type="number" value="10" min="1" max="100">
  <button type="submit">Add</button>
</form>
```

**Delete channel:**
```html
<button hx-delete="/api/channels/3"
        hx-target="#channel-row-3"
        hx-swap="outerHTML"
        hx-confirm="Remove this channel?">
  Delete
</button>
```

**Add processing step:**
A modal/inline form appears when "Add Step" is clicked. Step type selector changes the visible params form dynamically:
```html
<select name="step_type"
        hx-get="/fragments/step-params-form"
        hx-target="#step-params-container"
        hx-trigger="change"
        hx-include="[name='step_type']">
```

---

## 3. Page: Queue (`/queue`)

**Purpose:** Live view of all active and recent jobs. Updates in real-time via SSE.

### 3.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│  Queue                                    [Manual Trigger]│
├──────┬────────────────────┬──────────┬────────┬─────────┤
│  ID  │  Video             │ Pipeline │ Status │ Updated │
├──────┼────────────────────┼──────────┼────────┼─────────┤
│  42  │ Chapter 47 - Final │ Manhwa   │ ●●●○○  │  1m ago │
│      │ [processing]        │          │        │         │
│  41  │ Chapter 46         │ Manhwa   │ ●●●●● done│ 5m ago │
│  40  │ Chapter 45         │ Manhwa   │ ✗ failed │ 8m ago │
└──────┴────────────────────┴──────────┴────────┴─────────┘
```

### 3.2 Status Badge Colors

| Status       | Badge color  | Indicator          |
|--------------|--------------|--------------------|
| pending      | gray         | ○○○○○              |
| downloading  | blue         | ●○○○○ (animated)   |
| downloaded   | blue         | ●●○○○              |
| processing   | yellow       | ●●●○○ (animated)   |
| processed    | yellow       | ●●●●○              |
| uploading    | purple       | ●●●●○ (animated)   |
| done         | green        | ●●●●● ✓            |
| partial      | orange       | ●●●●◐              |
| failed       | red          | ✗ failed           |

### 3.3 Live Updates (SSE)

```html
<!-- SSE connection — auto-reconnects on disconnect -->
<div hx-ext="sse"
     sse-connect="/api/queue/stream"
     sse-swap="job_update"
     hx-target="#queue-tbody"
     hx-swap="none">
</div>

<!-- HTMX event listener on SSE message -->
<script>
document.body.addEventListener('htmx:sseMessage', function(evt) {
  if (evt.detail.type === 'job_update') {
    const data = JSON.parse(evt.detail.data);
    // Refresh the specific row
    htmx.trigger(`#job-row-${data.job_id}`, 'refresh');
  }
});
</script>
```

### 3.4 Manual Trigger

Clicking "Manual Trigger" opens an inline form:
```
URL: [____________________________]  Pipeline: [dropdown]  [Start]
```

On submit: `POST /api/jobs` → new row appears in queue with status `pending`.

---

## 4. Page: History (`/history`)

**Purpose:** Searchable/filterable log of all completed uploads.

### 4.1 Layout

```
┌─────────────────────────────────────────────────────────────┐
│  History                                                    │
│  Filter: [Platform ▼] [Status ▼] [Pipeline ▼]  [Search...]│
├────┬────────────────────┬──────────┬─────────┬─────────────┤
│ ID │ Video Title        │ Platform │ Status  │ Uploaded At │
├────┼────────────────────┼──────────┼─────────┼─────────────┤
│ 1  │ Epic Final Battle  │ YouTube  │ success │ 2026-04-22  │
│    │ AI: "Epic Final..." │          │ 🔗 Link │ 10:05       │
│ 2  │ Chapter 46         │ TikTok   │ failed  │ 2026-04-22  │
│    │ Error: Rate limited │         │ [Retry] │ 09:58       │
└────┴────────────────────┴──────────┴─────────┴─────────────┘
```

### 4.2 Filters (HTMX)

Each filter dropdown triggers a server-side reload of the table body:
```html
<select name="platform"
        hx-get="/fragments/history"
        hx-target="#history-tbody"
        hx-trigger="change"
        hx-include="[name='platform'],[name='status'],[name='pipeline_id'],[name='q']">
```

### 4.3 Row Detail

Clicking a row expands it to show:
- Original title vs AI-rewritten title
- AI description (truncated to 2 lines)
- AI tags list
- Source URL
- File sizes (source, output)
- Error message (if failed)

---

## 5. Page: Logs (`/logs`)

**Purpose:** Live log viewer for watcher and processor containers. Replaces the current implementation but keeps the same approach.

### 5.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│  Logs    [Watcher] [Processor] [Both]    [↓ Tail 120 ▼]│
├─────────────────────────────────────────────────────────┤
│ 2026-04-22 10:05:12 [INFO    ] Checking channel UCz3... │
│ 2026-04-22 10:05:13 [INFO    ] 2 new videos found       │
│ 2026-04-22 10:05:14 [INFO    ] Downloading: Chapter 47  │
│ 2026-04-22 10:05:45 [INFO    ] Download complete ✓      │
│ 2026-04-22 10:05:46 [INFO    ] Webhook fired to n8n     │
└─────────────────────────────────────────────────────────┘
                                              [Auto-refresh ON]
```

### 5.2 Color Coding

| Log level | Text color (Tailwind) |
|-----------|-----------------------|
| DEBUG     | `text-gray-500`       |
| INFO      | `text-gray-200`       |
| WARNING   | `text-yellow-400`     |
| ERROR     | `text-red-400`        |
| CRITICAL  | `text-red-600 font-bold` |

### 5.3 Auto-refresh

```html
<div id="log-container"
     hx-get="/api/logs?container=all&tail=120"
     hx-trigger="every 5s"
     hx-swap="innerHTML"
     hx-target="#log-lines">
```

Auto-scroll to bottom on each update (JavaScript):
```javascript
document.body.addEventListener('htmx:afterSwap', function(evt) {
  if (evt.target.id === 'log-lines') {
    evt.target.scrollTop = evt.target.scrollHeight;
  }
});
```

---

## 6. Flask Route → Template Map

| Route              | Template         | Description                          |
|--------------------|------------------|--------------------------------------|
| `GET /`            | redirect to `/pipelines` |                                |
| `GET /pipelines`   | `pipelines.html` | Pipeline management                  |
| `GET /queue`       | `queue.html`     | Live job queue                       |
| `GET /history`     | `history.html`   | Upload results history               |
| `GET /logs`        | `logs.html`      | Container log viewer                 |

All data routes are under `/api/*` (JSON) or `/fragments/*` (HTML fragments for HTMX).

---

## 7. HTMX Extension: SSE

The dashboard uses the HTMX SSE extension for the Queue page live updates:

```html
<!-- In base.html head -->
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
<script src="https://unpkg.com/htmx-ext-sse@2.2.2/sse.js"></script>
```

No other JavaScript frameworks are used.

---

## 8. Database Access Pattern (Flask)

All Flask routes use a single helper to get a DB connection:

```python
# dashboard/models.py
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv('DB_PATH', '/data/app.db'))

def get_db():
    """Return a SQLite connection with row_factory and pragmas set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows accessible as dicts
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
```

All connections are opened per-request and closed when the request ends. No connection pooling needed for this scale.

---

## 9. Error Pages

- `404` → Simple dark-themed page: "Page not found. [← Back to Dashboard]"
- `500` → Simple dark-themed page with error message shown in dev mode, generic message in production

---

*Next: [BUILD_ORDER.md](BUILD_ORDER.md)*
