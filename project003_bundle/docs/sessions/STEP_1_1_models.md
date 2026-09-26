# SESSION TASK — Step 1.1: SQLite Database Models

## Your job in this session
Create `dashboard/models.py` — the SQLite database initialization module.

## Read these files first (in this order):
1. `docs/DATABASE_SCHEMA.md` — full schema, all 8 tables, SQL DDL, indexes, constraints
2. `docs/ARCHITECTURE.md` — sections: "Volumes & Shared State" and "Security"

## Hard constraints (do not violate these):
- Python 3.11 only. No external ORM (no SQLAlchemy, no Tortoise). Raw `sqlite3` module only.
- WAL mode must be enabled: `PRAGMA journal_mode=WAL`
- Foreign keys must be enabled: `PRAGMA foreign_keys=ON`
- All tables use `INTEGER PRIMARY KEY AUTOINCREMENT` for IDs
- `created_at` / `updated_at` columns use `TEXT` storing ISO-8601 UTC strings (not DATETIME)
- No third-party packages beyond what is in `requirements.txt` already
- Database file path comes from env var `DB_PATH`, defaulting to `/data/app.db`

## File to create:
`dashboard/models.py`

## What this file must contain:

### 1. `get_db()` function
- Opens a connection to the DB path from env
- Sets `row_factory = sqlite3.Row` (so rows behave like dicts)
- Sets `PRAGMA journal_mode=WAL`
- Sets `PRAGMA foreign_keys=ON`
- Returns the connection

### 2. `init_db()` function
- Calls `get_db()`
- Runs the full `CREATE TABLE IF NOT EXISTS` DDL for all 8 tables (from DATABASE_SCHEMA.md)
- Creates all indexes listed in the schema doc
- Commits and closes

### 3. All 8 tables:
Exact names and columns as specified in `DATABASE_SCHEMA.md`:
- `pipelines`
- `sources`
- `destinations`
- `pipeline_steps`
- `download_jobs`
- `process_jobs`
- `upload_jobs`
- `event_log`

## Test / pass criteria:
After you write the file, write a small inline test block under `if __name__ == "__main__":` that:
1. Calls `init_db()`
2. Inserts one row into `pipelines` with `name='Test Pipeline'` and `status='active'`
3. Reads it back with `SELECT *`
4. Prints the row as a dict
5. Deletes it
6. Prints "OK"

Run it with `python dashboard/models.py` from the project root and show the output.

## When done:
- Confirm the file exists at `dashboard/models.py`
- Show the full file contents
- Show the test output
- Do NOT build anything else in this session
