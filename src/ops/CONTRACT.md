# ops — CONTRACT (U15)

**May import:** `core`, `accounts` — and nothing else (docs/04 §2).

That restriction is the design, not an accident. An operations module that
could reach every table would be a back door around the whole dependency
structure, so **`ops` cannot delete another module's data** — see §3.

## Published API (`ops.api`)

| Function | Purpose |
|---|---|
| `audit(workspace, entity, action, *, entity_id, detail, actor)` | Append-only: who did what, to which entity. |
| `list_audit(workspace=None, *, entity, entity_id, limit)` | Newest first. `workspace=None` reads the installation trail. |
| `heartbeat(worker_id, status, *, workspace, detail, current_job, kind, host, pid)` | Upsert one worker's liveness. |
| `list_heartbeats()` / `stale_workers(*, now, stale_seconds)` | Every worker; the ones that have gone silent. |
| `worker_status(worker_id, *, stale_seconds)` | `alive` / `stale` / `stopped` / `unknown`. |
| `tail_logs(path, *, lines=200)` | The last N lines of a log file, newest last. |
| `require_backup(action, *, confirmed, backup_ref)` | F-54, enforced rather than documented. |

## Three decisions worth defending

1. **A dead worker is visible, not inferred.** Without `worker_heartbeat` a dead
   worker can only be guessed at from a queue that stopped moving — and by then
   nobody knows whether it stopped because the worker died or because there was
   no work. Three missed beats and it is shown as stale.

2. **The audit trail outlives its subject.** `workspace_id` is `SET NULL`, so
   deleting a workspace does not delete the record of what was done to it. An
   audit log that disappears with its subject is not an audit log.

3. **The backup rule refuses rather than warns.** F-54 was a comment in the
   legacy. `require_backup` raises `BackupNotConfirmed` — and records the
   backup reference, or records that there wasn't one, because a recorded gap
   is better than a silent one.

## Where the purge lives, and why not here

`ops` cannot import `jobs`, `media` or `delivery`, so it cannot delete their
rows. Each module therefore owns its own `purge_plan` / `purge_runtime`, and
**`manage.py purge_runtime_data` in `ui` composes them** — `ui` is the outermost
layer and may see everything. The composition is a command, not a library call,
so the destructive path is always visible in one place.

Its three safety properties, each enforced rather than documented:

* the dry run is the default and every plan is computed from the same query the
  real purge uses — a plan written separately from the action can lie;
* the **delivery ledger is never touched**, and the dry run prints the kept
  counts so an operator can see that rather than trust it (F-53, D-12);
* `--apply` without `--backup-confirmed` is refused, and the whole thing is
  written to the audit trail.

## Deferred

- **U22** owns the `app_setting` table and the Settings page.
- **U23** is the Logs page, which renders `tail_logs` and `list_audit`.
