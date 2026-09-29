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

## Deferred / out of scope

- **U12** owns `delete_after` evaluation, pinning, and the `rehydrated` /
  `delete_skipped` events. This unit only writes the fields.
- **U25** evaluates `media_asset_due_idx`; `list_assets` is the read side until
  then.
