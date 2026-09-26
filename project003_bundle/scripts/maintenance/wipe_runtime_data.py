"""One-shot wipe — keeps:
- channels, sources, pipelines, destinations, download_profiles, routing_rules,
  processing_steps, oauth_tokens, youtube_projects (config)
- catalog_videos (so we don't have to re-scan)
- upload_ledger, upload_results, upload_progress, destination_quota
  (so we never re-upload the same content)
- worker_state rows where kind='setting' (download_workers count, etc.)
Wipes:
- download_queue, jobs, job_outputs, videos, worker_state non-settings
"""
import sqlite3, sys
DB = "/data/app.db" if len(sys.argv) < 2 else sys.argv[1]
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

def show(label):
    print(f"\n=== {label} ===")
    for t in ("download_queue","jobs","job_outputs","videos",
              "upload_ledger","catalog_videos","channels","worker_state"):
        try:
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:20} {n}")
        except Exception as e:
            print(f"  {t:20} ERR {e}")

show("BEFORE")

c.execute("BEGIN")
deleted = {}
for tbl in ("download_queue", "jobs", "job_outputs", "videos"):
    n = c.execute(f"DELETE FROM {tbl}").rowcount
    deleted[tbl] = n
# Reset auto-increment counters so new IDs start at 1
for tbl in ("download_queue", "jobs", "job_outputs", "videos"):
    try:
        c.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tbl,))
    except sqlite3.OperationalError:
        pass
# Wipe non-setting worker_state rows (heartbeats/diagnostics)
n = c.execute("DELETE FROM worker_state WHERE kind != 'setting'").rowcount
deleted["worker_state(non-setting)"] = n
c.commit()

print("\n=== DELETED ===")
for k, v in deleted.items():
    print(f"  {k:30} {v}")

show("AFTER")
c.close()

# VACUUM in its own connection (must be outside any txn)
c2 = sqlite3.connect(DB)
print("\nVACUUM...")
c2.execute("VACUUM")
c2.close()
print("done.")
