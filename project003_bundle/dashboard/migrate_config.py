"""
project003 — One-time migration from channel_monitor_config.json into SQLite.

Reads the legacy JSON config (channels + backfill state) and inserts:
- one default pipeline
- one channel row per channel in the config

Idempotent: running it twice does not duplicate rows.
Run with:  python dashboard/migrate_config.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running as `python dashboard/migrate_config.py` from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.models import get_db, init_db, DB_PATH  # noqa: E402

CONFIG_PATH = os.environ.get(
    "CHANNEL_CONFIG_PATH",
    str(Path(__file__).resolve().parent.parent / "channel_monitor_config.json"),
)
DEFAULT_PIPELINE_NAME = "Default Pipeline (Migrated)"


def utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def get_or_create_default_pipeline(conn) -> int:
    row = conn.execute(
        "SELECT id FROM pipelines WHERE name = ?", (DEFAULT_PIPELINE_NAME,)
    ).fetchone()
    if row:
        print(f"Pipeline already exists: '{DEFAULT_PIPELINE_NAME}' (id={row['id']})")
        return row["id"]

    cur = conn.execute(
        "INSERT INTO pipelines (name, description, active, created_at) VALUES (?, ?, ?, ?)",
        (
            DEFAULT_PIPELINE_NAME,
            "Auto-created during migration from channel_monitor_config.json",
            1,
            utcnow_iso(),
        ),
    )
    pid = cur.lastrowid
    print(f"Created pipeline: '{DEFAULT_PIPELINE_NAME}' (id={pid})")
    return pid


def derive_channel_id(key: str, channel: dict) -> str:
    """Pick a stable unique channel_id.

    The legacy JSON does not always store the YouTube channel ID (UCxxx).
    We use whatever uniquely identifies the channel:
      1. explicit `channel_id` field if present
      2. `@handle` parsed from URL
      3. fallback: the JSON dict key
    """
    if channel.get("channel_id"):
        return channel["channel_id"]

    url = channel.get("url", "")
    if "/@" in url:
        return "@" + url.split("/@", 1)[1].split("/")[0].split("?")[0]
    if "/channel/" in url:
        return url.split("/channel/", 1)[1].split("/")[0].split("?")[0]

    return key


def migrate_channel(conn, pipeline_id: int, key: str, channel: dict) -> str:
    """Insert one channel row. Returns one of: 'inserted', 'skipped'."""
    chan_id = derive_channel_id(key, channel)

    existing = conn.execute(
        "SELECT id FROM channels WHERE channel_id = ?", (chan_id,)
    ).fetchone()
    if existing:
        print(f"  - SKIP {channel.get('name', key)} ({chan_id}) — already in DB (id={existing['id']})")
        return "skipped"

    backfill_queue = channel.get("backfill_queue", [])
    backfill_entry_map = channel.get("backfill_entry_map", {})

    conn.execute(
        """
        INSERT INTO channels (
            pipeline_id, name, channel_id, url, mode,
            backfill_complete, backfill_queue, backfill_entry_map,
            daily_limit, uploads_today, uploads_today_date,
            last_check, active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pipeline_id,
            channel.get("name", key),
            chan_id,
            channel.get("url", ""),
            "monitor" if channel.get("backfill_complete", False) else "backfill",
            1 if channel.get("backfill_complete", False) else 0,
            json.dumps(backfill_queue),
            json.dumps(backfill_entry_map),
            int(channel.get("daily_upload_limit", 10)),
            int(channel.get("uploads_today", 0)),
            channel.get("uploads_today_date", ""),
            channel.get("last_check", "1970-01-01T00:00:00"),
            1 if channel.get("auto_download", True) else 0,
            utcnow_iso(),
        ),
    )
    print(f"  + ADD  {channel.get('name', key)} ({chan_id})")
    return "inserted"


def main() -> int:
    print(f"Database:   {DB_PATH}")
    print(f"Config:     {CONFIG_PATH}")
    print("Initializing database schema...")
    init_db()

    if not os.path.exists(CONFIG_PATH):
        print(f"ERROR: config file not found at {CONFIG_PATH}", file=sys.stderr)
        return 1

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    channels = cfg.get("channels", {})
    if not channels:
        print("No channels in config. Nothing to migrate.")
        return 0

    print(f"Found {len(channels)} channel(s) in config.")

    conn = get_db()
    try:
        conn.execute("BEGIN")
        pipeline_id = get_or_create_default_pipeline(conn)

        inserted = 0
        skipped = 0
        for key, channel in channels.items():
            result = migrate_channel(conn, pipeline_id, key, channel)
            if result == "inserted":
                inserted += 1
            else:
                skipped += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    print()
    print(f"Migration complete. {inserted} inserted, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
