# SESSION TASK — Step 1.2: JSON → SQLite Migration Script

## Your job in this session
Create `dashboard/migrate_config.py` — a one-time migration that reads `channel_monitor_config.json` and inserts its data into the SQLite database.

## Read these files first (in this order):
1. `docs/DATABASE_SCHEMA.md` — focus on the `pipelines`, `sources`, and `destinations` tables
2. `dashboard/models.py` — the `get_db()` and `init_db()` functions you will call
3. `channel_monitor_config.json` — the existing config structure you are migrating FROM

## Hard constraints:
- This is a **one-time migration script**, not a regular module
- It must be **idempotent** — running it twice must not create duplicate rows
  - Use `INSERT OR IGNORE` or check for existing records before inserting
- Python 3.11, `sqlite3` only — no ORM, no new packages
- Must call `models.init_db()` first to ensure tables exist
- `created_at` values: use `datetime.utcnow().isoformat() + 'Z'`
- After migration, print a summary: "Migrated X channels as sources in pipeline Y"

## File to create:
`dashboard/migrate_config.py`

## What the script must do:

### 1. Load `channel_monitor_config.json`
Read the JSON file. It contains a list of channel objects with these fields:
- `channel_id` — YouTube channel ID
- `channel_name` — human-readable name
- `enabled` — boolean
- (possibly) `check_interval_minutes`, `max_videos`, `webhook_url`

### 2. Create a default pipeline
Insert a pipeline row:
- `name = "Default Pipeline (Migrated)"`
- `status = "active"`
- Use `INSERT OR IGNORE` with a unique name check

### 3. For each channel, insert a `sources` row
Map these fields:
- `pipeline_id` → the ID of the default pipeline
- `platform = "youtube"`
- `channel_id` → from JSON `channel_id`
- `channel_name` → from JSON `channel_name`
- `enabled` → from JSON `enabled` (1 or 0)
- `check_interval_minutes` → from JSON or default 60
- `backfill_count` → from JSON `max_videos` or default 10

### 4. Print a migration summary
Show count of channels migrated and any skipped (already existed).

## Test / pass criteria:
Run `python dashboard/migrate_config.py` from the project root.
Output should look like:
```
Initializing database...
Loading channel_monitor_config.json...
Found 1 channel(s).
Created pipeline: 'Default Pipeline (Migrated)' (id=1)
  Migrated source: Manhwa Fresh (UCz3IjVYoX-tmmPPTedhXQEQ) — enabled
Migration complete. 1 source(s) migrated, 0 skipped.
```

## When done:
- Show the full file contents
- Show the output of running it
- Do NOT build anything else in this session
