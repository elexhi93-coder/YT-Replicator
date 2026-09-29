# media — CONTRACT (U11)

**May import:** `core`, `accounts` — and nothing else (docs/04 §2). The Port A
materialiser is obtained from `core.api.get_source_provider()` at call time, so
this module never imports `sources`. That is what lets `worker` run a download
without `sources` in its import graph.

## Published API (`media.api`)

| Function | Purpose |
|---|---|
| `add_storage_root(workspace, path, *, label, role, priority, min_free_bytes)` | Register a directory we may write into. Creates it. |
| `list_storage_roots(workspace, *, active_only=True)` | Roots in `priority` order (lower fills first). |
| `set_mounted(root, mounted)` | Attach/detach. Detaching archives the assets on it. |
| `archive_offline_root(root)` | Mark every `on_disk` asset on the root `archive_offline`. |
| `free_space(root)` | Read the filesystem and record `free_bytes`/`total_bytes`/`last_checked_at`. |
| `pick_root(workspace, *, needed_bytes=0)` | Best mounted root above its floor. Raises `NoStorageSpace`. |
| `acquire(workspace, source_video_id, *, source, job, max_height, prefer_format)` | Download → verify → atomic rename. |
| `hygiene(workspace, *, actor="system")` | Remove `*.part` litter and unclaimed orphans. |
| `get_asset` / `list_assets` / `list_events` | Reads. |

## The three decisions worth defending

**1. `NoStorageSpace` is transient, not permanent.** A full disk resolves —
retention (U12) frees space, or an operator does. A permanent classification
would fail every video on the disk forever; a worker that retried immediately
would just fill it again. Back off, then try again.

**2. `media_asset.path` is relative to the root; the absolute path is derived.**
`absolute_path()` composes `storage_root.path` + `path` through
`core.api.resolve_safe_path`, which rejects a traversal. Storing the absolute
form would mean a moved root invalidates every row, and a path that escaped
the root would be a single missed `..` away.

**3. A failed download leaves a row, not a mystery.** `acquire` marks the asset
`failed` and writes a `media_event` *before* re-raising, so the operator can
see which video failed and why. A digest mismatch additionally deletes the
staged bytes: corrupt data is worse than no data.

## 3. U12 additions — `media.retention`

| Function | Purpose |
|---|---|
| `evaluate(asset, facts, *, other_local_copies=False, now, min_age_hours, backstop_days, grace_minutes)` | **Pure.** One asset → one `Decision`. No I/O, no writes, no sibling imports. |
| `sweep(workspace, *, dry_run=True, actor, now, min_age_hours, grace_minutes)` | Phase one: decide and (unless dry-run) *schedule*. Never deletes. |
| `execute_due(workspace, *, now, actor, dry_run=False)` | Phase two: the **only** place a retention deletion happens. |
| `cancel(asset, *, actor, reason)` | Release a scheduled deletion before it fires. |
| `pin(asset, *, until, reason, actor)` / `unpin(asset, *, actor)` | D4: the pin, and the only thing that releases it. |
| `Decision` / `SweepReport` | Frozen: `delete`, `reason`, `delete_after`, `size_bytes`; and the sweep's `scheduled` / `skipped` / byte totals. |

### The gate order (docs/05 §8) — not interchangeable

1. `keep` short-circuits before anything else is asked (D1).
2. **INV-2** — every *enabled* destination terminal. Nothing may override this.
3. The pin holds (D4, F-10).
4. **D3** — the last local copy survives an unconfirmed destination copy.
5. The mode's condition (`immediate` / `after_n_jobs` / `after_hours`).
6. The floors: min-age, then the max-age backstop (D6).

### Three decisions worth defending

**1. `evaluate()` takes `other_local_copies` as a parameter, not a query.** The
first version queried for it, which made the "pure" function impure and
untestable without a database — the tests caught it at once. The count is
`media`'s own data, so it is an input, and the default `False` is the
conservative reading (assume last copy).

**2. The backstop is a condition, not a footnote.** D6 exists so a *stalled*
pipeline cannot pin disk forever; an implementation where the backstop only
annotated an already-satisfied mode would never fire at all. It can force
deletion past the mode condition — but never past INV-2, the pin, or D3.

**3. The min-age floor ships disabled (`DEFAULT_MIN_AGE_HOURS = 0`).** docs/05
§8 G7 defines the gate, but no specification anywhere gives a default value.
Inventing one would be a policy decision dressed up as a default.

## Deferred / out of scope

- **U13** adds rehydrate and the star-as-pin bridge (`catalog_video.starred`
  doubles as this pin — F-10). U12 reads `pinned_until` only.
- **U22** owns the `app_setting` table, so the backstop reads
  `APP_SETTING_DEFAULTS` until then.
- **U21** is the Library page that surfaces the dry-run modal.
