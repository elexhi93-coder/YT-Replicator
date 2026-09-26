# Maintenance scripts

One-shot operational scripts. Not imported by the app.

| Script | Purpose | When to run |
|---|---|---|
| `wipe_runtime_data.py` | Truncate `download_queue`, `jobs`, `job_outputs`, `videos` and non-setting `worker_state`. Preserves `upload_ledger`, sources, channels, pipelines, destinations, settings. | When you want a clean slate without losing upload history. |
| `migrate_channels_source_fk.py` | Idempotent backfill of `channels.source_id` for installs that pre-date the FK column. Fresh DBs already have it via `models.py::_ensure_column`. | Once per pre-existing DB, after upgrading. |

Both accept the SQLite path as `argv[1]` (default `/data/app.db`, the in-container path).

## Running inside the dashboard container

```sh
docker compose cp scripts/maintenance/migrate_channels_source_fk.py dashboard:/tmp/m.py
docker exec -w /app project003-dashboard python /tmp/m.py /data/app.db
```

Always take a backup first:

```sh
cp db/app.db db/app.db.bak.$(date +%Y-%m-%d)
```
