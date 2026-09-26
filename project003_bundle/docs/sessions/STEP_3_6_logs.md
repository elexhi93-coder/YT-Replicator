# SESSION TASK — Step 3.6: Logs Page + Auto-Refresh

## Your job in this session
Build `dashboard/templates/logs.html` — a real-time log viewer that streams Docker container logs.

## Read these files first:
1. `docs/DASHBOARD_SPEC.md` — section: "Logs Page"
2. Current `dashboard/app.py` — the existing Docker log reader (may already exist from old app.py)

## Hard constraints:
- Use Docker Unix socket `/var/run/docker.sock` to read container logs
- The `dashboard` container must have the socket mounted in `docker-compose.yml`
- Auto-refresh using HTMX `hx-trigger="every 3s"` — NOT SSE (SSE is for queue only)
- Show last 200 log lines by default
- Tailwind for all styling

## Files to build:
`dashboard/templates/logs.html`

## Also add to `app.py`:
```python
import docker  # pip install docker
# OR use subprocess + docker CLI if docker SDK not available

@app.route('/api/logs/<container_name>')
def api_logs(container_name):
    # Whitelist allowed container names (security: never pass user input directly to docker)
    allowed = {'watcher', 'processor', 'n8n', 'dashboard'}
    if container_name not in allowed:
        return jsonify({"error": "Not allowed"}), 403
    # Read last 200 lines from Docker logs
    # Return as plain text or JSON array of lines
```

Note: If `docker` Python SDK is not in requirements.txt, use subprocess:
```python
import subprocess
result = subprocess.run(['docker', 'logs', '--tail', '200', container_name],
                       capture_output=True, text=True)
```

## What the logs page must show:

### Container selector tabs
Four tabs: Watcher | Processor | n8n | Dashboard
Clicking a tab → `hx-get="/api/logs/<name>"` → `hx-target="#log-output"` `hx-trigger="click"`

### Log output panel
- Dark terminal-style box: `bg-black text-green-400 font-mono text-sm`
- Scrollable, fixed height (70vh)
- Auto-scroll to bottom when new content loads
- Auto-refreshes every 3 seconds: `hx-get="/api/logs/<active>"` `hx-trigger="every 3s"` `hx-target="#log-output"`

### Line coloring (optional but nice):
- Lines containing "ERROR" → red text
- Lines containing "WARNING" → yellow text
- Lines containing "INFO" → default green
Apply with a simple Jinja `{% if 'ERROR' in line %}` pattern.

### Controls
- "Clear" button — clears the visible log display (client-side only, doesn't delete logs)
- "Download" button — `<a href="/api/logs/<container>?download=1">` to download as .txt

## Test / pass criteria:
1. Open `http://localhost:8080/logs`
2. "Watcher" tab is active by default, showing watcher container logs
3. Click "Processor" tab → log content changes without full reload
4. Wait 3 seconds → log auto-refreshes (visible if watcher is actively logging)

## When done:
- Show `logs.html` (full)
- Show the `/api/logs/<container_name>` route in `app.py`
- Do NOT build anything else in this session
