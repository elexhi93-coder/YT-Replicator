# 02 — Domain Model

**Project:** YT-Replicator · **Status:** Draft, supersedes nothing yet
**Depends on:** `00_DESIGN_PRINCIPLES.md`, `01_LEGACY_REVERSE_ENGINEERING.md`

This document defines *what exists* and *what may happen to it*. Nothing here
is an implementation detail: table names and columns live in `03`.

**Interpretation recorded:** "SaaS-ready" means the schema is multi-tenant from
day one (every tenant-scoped row carries a workspace), while self-service
signup, billing and tenant administration are explicitly out of v1. "CRM"
refers to the platform this module will later join.

---

## 1. Locked decisions

Chosen as "must" from the legacy. Each is reversible before code exists.

| # | Decision | Rationale |
|---|---|---|
| D1 | Default retention mode is `keep` — nothing is ever deleted unless the operator opts in. | A small source must need zero configuration. Legacy forced the policy on every pipeline. |
| D2 | A short provenance marker is appended to the destination description. | Makes source↔destination matching exact instead of fuzzy, and survives total data loss. Fixes D-14. |
| D3 | The last local copy is deleted only when the destination copy is confirmed present. | Two independent recovery paths before freeing disk. Prevents an unrecoverable delete. |
| D4 | Rehydrated media is pinned by default until explicitly released. | An unowned re-download recreates the original storage leak. |
| D5 | `after_n_jobs` counts completed **jobs of the same pipeline**, not uploads. | One video × two destinations is one media bundle, not two. |
| D6 | A hard max-age backstop (default 7 days) applies regardless of mode. | Otherwise a stalled pipeline pins disk forever. |
| D7 | The Library is one page with a media-state filter, not a separate tab. | Scales to zero for a small source; a dedicated page would sit permanently empty. |
| D8 | **PostgreSQL**, not SQLite. | Multi-worker concurrency, `FOR UPDATE SKIP LOCKED`, managed backups, and it removes the legacy's worst failure mode (four processes on one bound file, D-19). |
| D9 | Monitoring polls the feed every 15 minutes and runs a full reconciliation scan every 6 hours. | Near-real-time detection with a deterministic fallback that does not depend on the feed. |
| D10 | Upload metadata uses the original title/description in v1. AI rewriting is parked. | Removes an external dependency and a whole class of failures from v1. |
| D11 | Tenancy is **tenant-shaped, not tenant-featured**: keep `workspace_id` and one access helper; build no tenant functionality (amended — see §2). | Retrofitting tenancy later costs a migration on every table plus a query-leak audit. The column costs one field and one index. |
| D12 | Deleting a pipeline, source or destination never deletes delivery history. | Fixes the legacy's cascading delete (D-04). |
| D13 | Tokens and client secrets are encrypted at rest; the key lives outside the database. | Fixes plaintext credentials (D-11) and token exports (D-22). |
| D14 | v1 delivery rule: **all sources of a pipeline deliver to all its enabled destinations.** Configurable routing rules are parked. | One rule, trivially predictable. Routing rules were a source of confusion, not capability. |
| D15 | No FFmpeg and no processing steps in v1. | The source file is uploaded as-is. Removes the entire processor component. |
| D16 | Every page requires authentication; CSRF on every mutation. | The legacy assumed a trusted LAN. A VPS is not a LAN. |

---

## 2. Tenancy: tenant-shaped, not tenant-featured

**Decision (D11, amended):** the *shape* is multi-tenant from day one; the
*features* are not built. One deployment serves one workspace, and no tenant
functionality is in v1 scope.

What "shaped" means concretely:

- `workspace` is the tenant root; one default workspace row is created at install.
- Tenant-scoped tables carry `workspace_id` **directly**, not only through a
  parent join. One column, and every query is scoped without a join.
- Every unique constraint on tenant data is scoped by `workspace_id`.
- Every view and service passes through **one** access helper. There is no
  unscoped accessor, so no query can cross tenants by accident.
- `workspace_member` exists and holds exactly one `owner` row in v1. Other
  roles are declared but inert; there is no membership UI.

Why keep the shape when the features are deferred: retrofitting tenancy means a
migration on every table, a backfill, and an audit of every query for leaks —
that is the expensive part. Keeping the column costs one field and one index per
table. Removing it saves nothing that matters and defers the expensive part to
the worst possible moment.

### 2.1 UI readiness — so the dashboard is never redesigned

The dashboard is built **once**, with the tenant-aware slots reserved. These
five rules are what make the later retrofit a configuration change instead of a
redesign.

| Rule | Why |
|---|---|
| One `base.html`; the header has a dedicated **context slot** showing the active workspace name. | Becomes a switcher with no layout change. |
| Navigation is **data-driven** — a list of (label, route, permission) rendered by a loop, never hardcoded markup. | Adding an "Administration" group later is a list entry. |
| **Named routes only.** No URL is hardcoded in a template, redirect or service. | Tenant-prefixed URLs later become a routing change in one place, not a hunt through templates. |
| Every request resolves the workspace through **one** helper before any query. | Roles and per-workspace permissions slot in without touching views. |
| Page templates are grouped by concern (`pipelines/`, `sources/`, `library/`, `ops/`). | An admin area becomes a new folder, not a reorganisation. |

Explicitly **not** built in v1: workspace switcher behaviour, membership
management UI, roles beyond a single owner, and any administration tab.

---

## 3. The four tiers, applied

From `00` §3, realised here:

| Tier | Entities | Default |
|---|---|---|
| **Records** | `source`, `catalog_video`, `pipeline`, `job`, `delivery`, `delivery_attempt` | always on |
| **Hygiene** | `media_asset` (partial/orphan states) | always on |
| **Safety** | `storage_root` (free-space gate), atomic `job` claims | always on, silent |
| **Retention** | `pipeline.retention_*`, `media_event` | **off** (`keep`) |

---

## 4. Entity catalogue

Every entity earns its place. "Legacy link" is where it came from or which
defect it fixes.

### Tenancy and access

| Entity | Purpose | Key / uniqueness | Legacy link |
|---|---|---|---|
| `workspace` | Tenant root. | `pk` | D11 |
| `workspace_member` | User↔workspace with a role (`owner`/`operator`/`viewer`). | `unique(workspace, user)` | D11, enterprise roles |
| `app_user` | Django authentication user. | `pk` | replaces LAN-trust (D16) |
| `app_setting` | Installation-level settings: free-space floor, max-age backstop, poll intervals, reconciliation cadence. | `unique(key)` | D6, safety tier |

### Credentials

| Entity | Purpose | Key / uniqueness | Legacy link |
|---|---|---|---|
| `google_client` | One Google Cloud OAuth client: id, encrypted secret, daily cap, active flag. | `unique(workspace, client_id)` | F-07; rotation across **dedicated** projects only (D-23) |
| `authorized_channel` | A YouTube channel we may upload to: channel id, title, client ref, encrypted access and refresh tokens, expiry, scopes, health. | `unique(workspace, channel_id)` | fixes D-11 and D-23 by binding explicitly |

### Sources and catalog

| Entity | Purpose | Key / uniqueness | Legacy link |
|---|---|---|---|
| `source` | A channel or playlist we read from. Never uploaded to. | `unique(workspace, external_id)` | F-08; reusable across pipelines, INV-9 |
| `catalog_video` | Metadata for one video seen in one source. No media. | `unique(source, video_id)` | F-08, F-10; the same video may appear in several sources |

### Pipelines

| Entity | Purpose | Key / uniqueness | Legacy link |
|---|---|---|---|
| `pipeline` | The configured workflow: activation, priority, retention policy, download profile, upload defaults. | `unique(workspace, name)` | F-01 |
| `pipeline_source` | Which sources feed a pipeline, with mode (`backfill`/`monitor`), priority, daily cap override and backfill progress. | `unique(pipeline, source)` | F-03, F-04 — replaces the JSON array |
| `destination` | An authorized channel plus upload defaults. Workspace-scoped so it can serve several pipelines. | `unique(workspace, label)` | F-26; repairs D-23's binding |
| `pipeline_destination` | Which destinations a pipeline delivers to, with enabled flag, priority and overrides. | `unique(pipeline, destination)` | D14 |
| `download_profile` | Reusable yt-dlp knobs: resolution cap, container, codecs, subtitles, thumbnail, info.json, skip shorts and live, custom format. | `unique(workspace, name)` | F-14 `ADAPT` |

### Work

| Entity | Purpose | Key / uniqueness | Legacy link |
|---|---|---|---|
| `job` | One unit of work: (pipeline, video, intent) where intent is `upload`/`rehydrate`/`inspect`, plus status, claim owner, attempts and timings. | `unique(pipeline, source_video_id, intent)` | F-22, F-23 |

### Delivery truth

| Entity | Purpose | Key / uniqueness | Legacy link |
|---|---|---|---|
| `delivery` | **The durable record**: current state for one (video, destination): status, destination video id and url, title snapshot, provenance marker, match method, upload time, superseded-by, error. | `unique(workspace, source_video_id, destination)` | legacy `upload_ledger`; INV-1, INV-5 |
| `delivery_attempt` | Append-only history of every try: attempt number, status, HTTP code, error, bytes, timing. | `unique(delivery, attempt_no)` | P4 |
| `destination_inventory` | What the destination actually shows right now: destination video id, title, published date, privacy, first and last observed, matched delivery, availability. | `unique(destination, destination_video_id)` | **fixes D-13** — the capability that never existed |
| `quota_usage` | Uploads consumed per destination per YouTube quota day. | `unique(destination, quota_date)` | fixes D-03 |

### Media and storage

| Entity | Purpose | Key / uniqueness | Legacy link |
|---|---|---|---|
| `storage_root` | One media root: path, role (`hot`/`cold`), priority, mounted flag, total and free bytes, free-space floor. | `unique(workspace, path)` | F-34 plus the missing capacity awareness |
| `media_asset` | **One physical copy**: path, storage root, size, sha256, duration, materialisation number, state, pin and its reason, deleted time and reason. | `unique(source_video_id, materialization_no)` | F-52, P8; makes the Library and rehydrate possible |
| `media_event` | Append-only media audit: created, deleted, delete-skipped, rehydrated — with the reason and bytes involved. | `pk` | P14 — makes disk usage explicable |

### Operations

| Entity | Purpose | Key / uniqueness | Legacy link |
|---|---|---|---|
| `worker_heartbeat` | Which workers are alive, what they are doing, when they last reported. | `unique(worker_id)` | F-29 |
---

## 5. Relationships

```
workspace ─┬─ workspace_member ───── app_user
           ├─ google_client ──────── authorized_channel
           ├─ source ─────────────── catalog_video
           ├─ pipeline ─┬─────────── pipeline_source ────── source
           │            ├─────────── pipeline_destination ── destination
           │            └──▶ download_profile   (shared, referenced)
           ├─ destination ─┬──────── destination_inventory
           │               └──────── quota_usage
           ├─ job ────────── media_asset ──▶ storage_root
           ├─ delivery ───── delivery_attempt
           └─ storage_root · media_event · audit_event · worker_heartbeat
```

Notes that matter:

- `delivery` and `delivery_attempt` key on `(source_video_id, destination)`,
  **not** on the job. A job is *attempted work*; a delivery is *what is true
  about a destination*. `delivery.job_id` is set when a job produces the row and
  is `SET NULL` if the job is ever removed, so history never depends on a job
  row existing.
- `authorized_channel` is the only thing that may hold tokens. `destination`
  points at it. This is the explicit binding that D-23 identified as missing.
- `catalog_video` is per `(source, video)`, while `delivery` is global on
  `source_video_id`. That is deliberate: a video appearing in two sources is
  catalogued twice but delivered once.

---

## 6. State machines

### `job.status`

```
queued ─▶ claimed ─▶ downloading ─▶ downloaded ─▶ uploading ─▶ uploaded
   ▲                                        │
   └────────────────────────────────────────┘  (retry, attempt + 1)

terminal: uploaded · failed_permanent · skipped · cancelled
```

| State | Meaning | Allowed exits |
|---|---|---|
| `queued` | Ready to be claimed. | `claimed`, `cancelled`, `skipped` |
| `claimed` | A worker owns it. Claims are atomic and time-bounded. | `downloading`, back to `queued` if the claim goes stale |
| `downloading` | Media is being fetched. | `downloaded`, `failed_transient` |
| `downloaded` | Media verified on disk (size and hash recorded). | `uploading`, `failed_permanent` |
| `uploading` | The delivery is in flight. | `uploaded`, `failed_transient` |
| `failed_transient` | Retryable: network, 5xx, rate limit. | `queued` with backoff |
| `failed_permanent` | Needs a human: auth revoked, video removed, unsupported. | operator action only |
| `skipped` | A policy decided not to proceed (too large, unavailable, already delivered). Always carries a reason. | operator action only |

**Paused is not a job state.** When quota or disk pauses work, the job stays
`queued` and the *scheduler* reports the pause. States describe the work, not
the weather.

**Restart recovery.** On startup a worker resets `claimed` and `downloading`
rows older than the claim timeout back to `queued`, and flags any `uploading`
row older than the timeout as `failed_transient` with reason
`interrupted_during_upload` — because we cannot know whether an interrupted
upload succeeded, and re-checking the destination is cheap while guessing is
not.

### `delivery.status`

```
not_delivered ─▶ queued ─▶ uploading ─▶ uploaded
                                   └──▶ failed ──▶ queued   (retry)
uploaded ─▶ removed            (operator acknowledged the copy is gone)
```

**The write-once resolution.** `delivery` holds *current* state, and its
`destination_video_id`, `destination_url` and `uploaded_at` may only change by
writing a new `delivery_attempt` first. The attempt table is the immutable
record of every value those fields have ever held. So the fields are
effectively write-once *per attempt*, with a complete audit trail, without a
second parallel table.

### `media_asset.state`

```
expected ─▶ downloading ─▶ on_disk ─┬─▶ deleted
                    │               └─▶ archive_offline
                    └─▶ failed       (hygiene removes the partial file)
```

`archive_offline` exists so a detached drive never looks like `deleted`.
Treating an absent cold root as missing is how a system silently re-downloads
and re-uploads everything (F-52).

---

## 7. Invariants and how they are enforced

| Invariant | Enforced by |
|---|---|
| INV-1 one current successful delivery per (video, destination) | `UNIQUE(workspace, source_video_id, destination)` |
| INV-2 delete only when every enabled destination is terminal | retention evaluator reads `pipeline_destination` and `delivery` |
| INV-3 never upload a partial or unverified file | hash and size recorded before `downloaded`; state must be `on_disk` |
| INV-4 removing a pipeline or source never deletes history | `delivery` has no cascading FK to pipeline or source |
| INV-5 nothing enqueued for an already-delivered pair | unique index plus a pre-insert check that returns the reason |
| INV-6 retention decisions reproducible from the database alone | decision is a pure function of stored rows |
| INV-7 scanning never downloads | scan path writes `catalog_video` only |
| INV-8 unclaimed inventory is flagged, never adopted | `destination_inventory.matched_delivery` is nullable and surfaces as a review item |
| INV-9 a source is reusable | many-to-many through `pipeline_source` |
| INV-10 deletion evaluated in one place, dry run always available | single retention service; dry run is the default for the audit view |

---

## 8. Explicitly not in v1

Parked, not forgotten. Each has a home in `06_FEATURE_ROADMAP.md`.

- `processing_steps`, FFmpeg, GPU encoding — source file uploaded as-is (D15).
- Routing rules — replaced by the one rule in D14.
- Any destination that is not YouTube.
- AI metadata rewriting (D10).
- Upload scheduling / `publishAt`.
- Per-channel download overrides — one profile per pipeline.
- Plugin framework.
- Reading logs through the Docker socket.
- Exporting tokens with configuration.
- Bulk rehydrate with capacity and time estimates; cold-root archive workflow.
- Self-service signup, billing, workspace switcher, membership management, roles
  beyond a single owner, administration tab, email notifications.

