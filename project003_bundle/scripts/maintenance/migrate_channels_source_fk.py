"""Migration: link channels.source_id -> sources.id

Idempotent. For every channels row:
  1. Try to find a matching sources row by external_id, then by url.
  2. If none found, insert one (canonicalising the URL through
     parse_source_url so a bare @handle becomes @handle/videos).
  3. Set channels.source_id to the resolved id.

After this script runs, _resolve_channel_source_id can be reduced to a
single FK lookup. The two tables remain physically separate (sources
holds catalog state, channels holds monitor/runtime state) but the
relationship is now explicit and enforced.

Usage (host):  python _migrate_channels_source_fk.py db/app.db
Usage (container):  docker exec project003-dashboard python /tmp/_migrate_channels_source_fk.py
"""
import os
import sqlite3
import sys

DB = "/data/app.db" if len(sys.argv) < 2 else sys.argv[1]

# Make dashboard package importable when running from host or container
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "dashboard"))
sys.path.insert(0, "/app")          # dashboard container
sys.path.insert(0, os.getcwd())

try:
    from dashboard.sources import parse_source_url, SourceUrlError
except ImportError:
    from sources import parse_source_url, SourceUrlError  # type: ignore


def ensure_column(conn, table, column, decl):
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = {r[1] for r in cur.fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        print(f"  + added {table}.{column}")


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")

    print(f"DB: {DB}")
    print("\n=== Step 1: ensure channels.source_id column ===")
    ensure_column(conn, "channels", "source_id",
                  "INTEGER REFERENCES sources(id) ON DELETE SET NULL")

    print("\n=== Step 2: link existing channels -> sources ===")
    chans = conn.execute(
        "SELECT id, name, channel_id, url, pipeline_id, source_id FROM channels"
    ).fetchall()
    if not chans:
        print("  (no channels to migrate)")
    else:
        linked = created = skipped = 0
        for c in chans:
            if c["source_id"]:
                skipped += 1
                continue

            # Canonicalise URL (so @handle -> @handle/videos matches the
            # canonical form stored in sources.url).
            try:
                _kind, _ext, canonical = parse_source_url(c["url"] or "")
            except SourceUrlError:
                canonical = c["url"] or ""

            # Match by external_id (channel_id) first, then by canonical URL,
            # then by raw URL.
            src = conn.execute(
                """SELECT id FROM sources
                    WHERE external_id = ? OR url = ? OR url = ?
                    LIMIT 1""",
                (c["channel_id"], canonical, c["url"] or ""),
            ).fetchone()
            if src:
                src_id = src["id"]
                linked += 1
                action = "linked"
            else:
                cur = conn.execute(
                    """INSERT INTO sources
                           (kind, url, external_id, name, pipeline_id)
                       VALUES ('channel', ?, ?, ?, ?)""",
                    (canonical, c["channel_id"], c["name"], c["pipeline_id"]),
                )
                src_id = cur.lastrowid
                created += 1
                action = "created"

            conn.execute(
                "UPDATE channels SET source_id = ? WHERE id = ?",
                (src_id, c["id"]),
            )
            print(f"  {action}: channel {c['id']} ({c['name']}) -> source {src_id}")

        print(f"\n  totals: linked={linked} created={created} skipped={skipped}")

    conn.commit()

    print("\n=== Step 3: verify ===")
    rows = conn.execute(
        """SELECT c.id, c.name, c.source_id, s.url, s.external_id
             FROM channels c
        LEFT JOIN sources s ON s.id = c.source_id"""
    ).fetchall()
    for r in rows:
        marker = "OK" if r["source_id"] else "MISSING"
        print(f"  [{marker}] channel {r['id']} {r['name']!r} -> source {r['source_id']} url={r['url']}")

    conn.close()
    print("\ndone.")


if __name__ == "__main__":
    main()
