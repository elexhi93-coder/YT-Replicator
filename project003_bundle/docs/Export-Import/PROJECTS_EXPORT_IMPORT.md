# Dashboard Admin Project Export / Import Implementation Guide

This guide explains how to implement the YouTube project export/import feature on the dashboard admin page.
It is written for a developer or AI assistant working from another workstation who needs to reproduce the same feature.

## Goal

Add a new admin-only control at the bottom of `dashboard/templates/admin.html` that lets the user:

- download a JSON export of YouTube project configuration
- upload a JSON file to import YouTube project configuration

This should be implemented in the admin tab only; the Projects tab should not receive the export/import UI.

## Files involved

- `dashboard/config_export.py`
- `dashboard/app.py`
- `dashboard/templates/admin.html`
- `dashboard/Dockerfile`
- `docker-compose.yml` (for rebuild instructions)

## Desired behavior

1. `GET /admin` renders the admin page.
2. The admin page includes a new section near the bottom with:
   - `Export JSON` button
   - file upload input
   - `Import projects` submit button
3. Exporting returns a JSON file containing:
   - `youtube_projects`
   - `youtube_channels`
   - `oauth_tokens` (only `platform='youtube'`)
4. Importing accepts a JSON file and upserts project/channel/token rows without duplicating existing objects.
5. The feature is specific to the admin page and should not alter the Projects tab UI.

## Implementation steps

### 1. Add `dashboard/config_export.py`

Create a new module with two functions:

- `export_projects(conn=None)`
- `import_projects(payload, conn=None)`

The export function should:

- open the DB connection via `get_db()` if none is passed
- select `*` from `youtube_projects`, `youtube_channels`, and `oauth_tokens`
- filter `oauth_tokens` by `platform='youtube'`
- return a JSON-serializable dict with a `metadata` object and the three arrays

The import function should:

- validate the payload is a dict
- validate `metadata.version == 1`
- normalize the three arrays
- upsert `youtube_channels` by `channel_id`
- upsert `youtube_projects` by `client_id`
- upsert `oauth_tokens` by `(platform, project_id)` or by `(platform, account_label)` when `project_id` is absent
- preserve linked `youtube_channel_id` values by remapping old IDs to new IDs
- return counts of imported objects

Example file path:

- `dashboard/config_export.py`

### 2. Update `dashboard/app.py`

Add imports and two new admin routes:

- import the new helper module as `config_export`
- add `@app.get('/admin/export-projects')`
- add `@app.post('/admin/import-projects')`

`/admin/export-projects` should:

- call `config_export.export_projects(g.db)`
- return `Response(body, mimetype='application/json')`
- set `Content-Disposition` to attach a filename such as `project003-youtube-projects-export-YYYYMMDDTHHMMSSZ.json`

`/admin/import-projects` should:

- read `request.files.get('projects_export')`
- decode the uploaded file to text
- parse JSON
- call `config_export.import_projects(payload, g.db)`
- return HTML feedback for success or failure

Keep the existing `/admin` route unchanged.

### 3. Update `dashboard/templates/admin.html`

Add a new section near the bottom, before the toast block, with:

- section title `YouTube project export / import`
- an anchor to `/admin/export-projects`
- a file input named `projects_export`
- a submit button for import
- an empty result container with `id="projects-import-result"`

Use the same admin page styling conventions already present in the template.

### 4. Update `dashboard/Dockerfile`

Ensure the new file is copied into the dashboard image:

```dockerfile
COPY config_export.py .
```

Add it alongside the other copied files before `COPY templates/ templates/`.

### 5. Rebuild and restart the dashboard service

From the repository root:

```bash
cd /c/Users/T490s/Documents/project003
docker compose build --no-cache dashboard
docker compose up -d dashboard
```

### 6. Validate the feature

1. Open `http://localhost:8080/admin`
2. Confirm the bottom section shows `YouTube project export / import`
3. Click `Export JSON` and confirm a JSON download starts
4. Optionally upload a valid export file to confirm the import path works

## Notes for another workstation

- The feature is not tied to `dashboard/projects.html`; it is fully admin-side.
- The export payload uses the dashboard DB schema for YouTube quota management.
- If the dashboard does not load after rebuild, inspect `docker compose logs --tail=40 dashboard`.
- If the admin page still does not show the new section after refresh, clear browser cache or restart the container.

## Troubleshooting

### Dashboard fails on startup

If the container logs show `ModuleNotFoundError: No module named 'config_export'`, then the Dockerfile was not updated to copy `config_export.py`.

### Admin page loaded but no section

Check that `dashboard/templates/admin.html` includes the new section and that the container was rebuilt after the change.

### JSON import validation

If the uploaded file is invalid JSON or missing required top-level arrays, return a user-visible error from the import route with HTTP 400.

## Summary of key files to change

- `dashboard/config_export.py`
- `dashboard/app.py`
- `dashboard/templates/admin.html`
- `dashboard/Dockerfile`
- `docker-compose.yml` only for rebuild commands, not code changes
