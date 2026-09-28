# pipelines.CONTRACT — Pipelines, Destinations & Routing (U06)

**Module:** `pipelines` · **Status:** complete except `missing_videos` (§4)
**May import:** `core.api`, `accounts.api` (docs/04 §3). **No sibling at all** —
`pipelines` is in the independence contract, so it may not even reach
`sources.api` or `credentials.api`. Cross-module data arrives as model instances
passed in, or through Django's app registry in tests.
**Owns:** `download_profile`, `pipeline`, `pipeline_source`, `destination`,
`pipeline_destination` (docs/03 §6). It never reads `catalog_video`.

---

## 1. Public surface (`pipelines.api`, INV-12)

| Symbol | Behaviour |
|---|---|
| `create_pipeline(workspace, name, *, description="", priority=100, download_profile=None, default_privacy="unlisted", provenance_marker=True, retention_mode="keep", retention_n=2, retention_hours=24)` | → `Pipeline` in `draft`. Name is unique per workspace **including soft-deleted rows** (the table's `UNIQUE` says so). Raises `PipelineNameTaken`, `InvalidSetting`. |
| `get_pipeline(workspace, pipeline_id)` | → live `Pipeline`; soft-deleted rows are invisible. Raises `PipelineNotFound`. |
| `list_pipelines(workspace, *, status=None, include_deleted=False)` | In run order (priority, id). |
| `update_pipeline(pipeline, **fields)` | Mutable fields only. `status` is not one of them — `activate`/`pause` own the state machine; passing it raises `InvalidSetting`. |
| `activate(pipeline)` | `draft → active`, `paused → active`. Refuses with `PipelineNotRunnable` when there is no source, or no **enabled** destination. Re-activating an active pipeline raises `InvalidTransition`. |
| `pause(pipeline)` | `active → paused`; idempotent on a paused pipeline. Pausing a draft raises `InvalidTransition`. |
| `delete_pipeline(pipeline)` | Soft-deletes, pausing an active pipeline first. Nothing is hard-deleted (INV-4, fixes D-04). |
| `attach_source(pipeline, source, *, mode="monitor", priority=100, daily_cap=None)` | Idempotent on `(pipeline, source)`, and **preserves backfill progress** — re-attaching configures, it does not reset the cursor. |
| `detach_source` / `list_pipeline_sources(pipeline, *, mode=None)` | Removing the link keeps the source and its catalog. |
| `add_destination(workspace, channel, *, label, default_privacy="unlisted", daily_max=6)` | Workspace-level row bound to an authorised channel. This module never decrypts a token. |
| `attach_destination(pipeline, destination, *, enabled=True, priority=100, privacy_override=None, retention_mode_override=None)` | Idempotent; one channel may serve several pipelines. |
| `detach_destination` / `list_pipeline_destinations` / `list_destinations` | |
| `add_download_profile(workspace, name, *, ...)` / `get_download_profile` / `list_download_profiles` | Reusable quality settings; v1 never re-encodes (D15). |

### 1.1 Module layout

* `models.py` — the five tables with the CHECK constraints and indexes of docs/03 §6.
* `errors.py` — typed errors (§2).
* `api.py` — this surface; the only writer of these five tables.

---

## 2. Errors

All are `PermanentError`: a pipeline misconfiguration is something the operator
must resolve, and no retry fixes it.

| Error | Raised when |
|---|---|
| `PipelineError` | Base for the module. |
| `PipelineNotFound` | No live pipeline, or the pipeline is soft-deleted. |
| `PipelineNameTaken` | The name is taken — including by a soft-deleted pipeline. |
| `InvalidTransition` | A status change the state machine forbids; carries `current`/`requested`. |
| `PipelineNotRunnable` | Activation refused; carries `missing` (`"source"` or `"enabled destination"`). |
| `DownloadProfileNotFound` | No profile matches the lookup. |
| `InvalidSetting` | A value outside the schema's CHECK vocabulary; carries `field` and `value`. |

---

## 3. Tests

`src/pipelines/tests/test_pipelines.py` — 35 tests:

* **Create/read** (7): draft default, name uniqueness (including soft-deleted),
  soft-deleted hidden from `get`, run-order listing, status filter, `InvalidSetting`
  naming the field, and `status` refused as a direct write.
* **State machine** (7): activation blocked without a source, blocked without an
  enabled destination, activation, double activation refused, pause/resume, pausing a
  draft refused, delete pauses then soft-deletes, deleted pipeline cannot activate.
* **Sources** (7): idempotent attach, **backfill progress preserved**, detach keeps
  the source, priority order, mode filter, invalid mode, zero daily cap.
* **Destinations** (7): channel binding, idempotent attach with overrides, invalid
  overrides, detach keeps the destination, duplicate label, zero daily max, one
  channel serving several pipelines.
* **Profiles** (5): documented defaults, reuse across pipelines, duplicate name,
  negative height, missing profile.

No test imports a sibling module — sources and channels are created through
Django's app registry, which is the boundary the module itself operates under.

---

## 4. Out of scope — `missing_videos()` is **not** in this unit

`docs/04` §5 lists `missing_videos(pipeline, destination)` for this module, and
the U06 row calls for a "missing-videos query". It cannot be built inside the
current architecture, and the reason is structural rather than incidental:

* The candidate set lives in `catalog_video`, owned by `sources`.
* The already-delivered set lives in `delivery` (U10), which does not exist yet.
* `pipelines` is in the **independence contract**, and `ALLOWED_IMPORTS` in
  `tests/test_module_boundaries.py` permits it `core` and `accounts` only — it may
  not import `sources.api`, and a direct SQL join would be exactly the INV-11
  violation those tests exist to prevent.

Implementing it would mean either breaking the independence contract or inventing
a private SQL channel between modules. Both are architecture decisions, so the
work is recorded as split out (docs/07 §0) rather than smuggled in here. Pillar
1's own `INTER_PILLAR_INTEGRATION.md` names `sources.api.list_videos_for_source(...)`
as the intended edge, so resolving it is a docs/04 §2/§3 change, not a `pipelines`
change.

Everything else the U06 row names is delivered above.

---

## 5. Reconciliations (decided here, recorded for U25)

1. **`download_profile.sub_langs` storage.** docs/03 §6 declares `text[]`; the
   Django field is `JSONField` (jsonb on PostgreSQL) because the harness runs
   SQLite — the same reconciliation as `authorized_channel.scopes` and
   `catalog_video.tags`, which `03` §2.1 already records.
2. **A soft-deleted pipeline keeps its name.** The table's `UNIQUE (workspace,
   name)` covers deleted rows, so `create_pipeline` refuses the name itself rather
   than letting the database raise. Reusing it would make ledger references
   ambiguous.
3. **`update_pipeline` refuses `status`.** The state machine is the module's, not
   the caller's; a direct write would bypass the runnability check entirely.
4. **Deleting an active pipeline pauses it first.** A stopped pipeline is a paused
   one, so deletion must not leave work queued against a pipeline that no longer runs.
5. **Re-attaching a source preserves the backfill cursor.** An operator
   re-configuring a running pipeline must not silently restart its backfill.

