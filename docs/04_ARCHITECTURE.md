# 04 — Architecture

**Project:** YT-Replicator · **Status:** Draft · **Depends on:** `00`–`03`

---

## 1. The mandatory rule

> **A change that does not alter a published interface must be achievable by
> editing exactly one module's code and that module's tests — and nothing else.**

This is INV-11. It is the reason the project is being rebuilt, and it is the
rule that keeps each piece of work small enough to finish in one sitting. If a
change forces an edit in a second module, one of two things is true:

- the module's **published interface** is changing — which is allowed, but must
  be recorded in §6 and reviewed deliberately; or
- a **boundary has been violated** — which is a defect, not a trade-off.

There is no third option. "I'll just tweak this other file" is how the legacy's
`app.py` grew to 7 000 lines.

### 1.1 How this maps to a working session

| Working rule | Consequence |
|---|---|
| One work unit touches one module. | A session loads only that module's files, its interface and its tests. |
| If a unit needs a second module, the interface is written first, then the unit is split in two. | Nothing is ever written twice, and no session has to hold the whole system in mind. |
| Tests for a module run without any other module's test suite. | Feedback is fast and failures point at one place. |
| A module's contract lives in one file. | Reading one short file is enough to work on it. |

The work units themselves are enumerated in `07_WORK_PLAN.md`.

---

## 2. Module map

Twelve modules. Each owns one concern, and one concern only.

| Module | Owns | May import |
|---|---|---|
| `core` | Settings, logging, error types, the clock (including the YouTube quota day), base types. | *nothing* |
| `accounts` | `workspace`, `workspace_member`, and **the single access helper**. | `core` |
| `credentials` | `google_client`, `authorized_channel`, token encryption, the OAuth flow. | `core`, `accounts` |
| `sources` | `source`, scanning, hydration, `catalog_video`. | `core`, `accounts` |
| `pipelines` | `pipeline`, `pipeline_source`, `pipeline_destination`, `destination`, `download_profile`. | `core`, `accounts` |
| `jobs` | `job`, the queue, claiming, the state machine, retry and backoff policy. | `core`, `accounts` |
| `youtube` | The API client: token refresh, inventory sync, resumable upload, error translation, quota accounting. | `core`, `accounts`, `credentials` |
| `delivery` | `delivery`, `delivery_attempt`, and the act of delivering one video to one destination. | `core`, `accounts`, `youtube`, `jobs.api` |
| `media` | `storage_root`, `media_asset`, `media_event`, downloading, hashing, hygiene, and the retention evaluator. | `core`, `accounts` |
| `worker` | The run loop. Claims a job and dispatches it by intent. Orchestration only, no business rules. | `jobs`, `media`, `delivery` |
| `ops` | `audit_event`, `worker_heartbeat`, health, log reading, maintenance commands. | `core`, `accounts` |
| `ui` | Routes, views, templates, and the navigation definition. | every module's `.api` |

Two facts worth noticing:

- **`jobs` knows nothing about YouTube or files.** It knows how to hand out work
  safely. `media` knows how to get a file. `delivery` knows how to push one.
  `worker` wires them together and holds no rules of its own. This inversion is
  what makes the whole system changeable: swapping the download mechanism touches
  `media` and nothing else.
- **`core` imports nothing.** If `core` ever needs something from another module,
  that module's responsibility is wrong.

---

## 3. Dependency rules

```
ui ──────────────▶ every module's api
worker ──────────▶ jobs · media · delivery
delivery ────────▶ youtube · jobs.api
youtube ─────────▶ credentials
media ───────────▶ core · accounts
jobs ────────────▶ core · accounts
sources ─────────▶ core · accounts
pipelines ───────▶ core · accounts
credentials ─────▶ core · accounts
accounts ────────▶ core
core ────────────▶ (nothing)
```

| Rule | Reason |
|---|---|
| Imports flow **in one direction**; no cycles, ever. | A cycle means two modules are really one, and neither can be changed alone. |
| Cross-module access is **only** via `<module>.api`. | The internals stay free to change without a ripple. |
| Nothing imports `ui` or `worker`. | UI and orchestration are leaves; nothing may depend on them. |
| `core` imports no sibling module. | Keeps the foundation changeable by everyone and dependent on nobody. |
| A module never reaches into another module's models directly. | Reaching into someone's tables is how a schema change becomes a project. |

---

## 4. Enforcement

Rules that are not mechanically checked are wishes. Three checks, all in the test
suite, all failing the build:

1. **Import contracts.** `import-linter` layered contracts declared in
   `pyproject.toml`, expressing exactly the arrows in §3. A forbidden import
   fails CI.
2. **`tests/test_module_boundaries.py`.** Walks each module's source with `ast`
   and asserts that no import of a sibling module exists except `<sibling>.api`,
   and that no cycle exists. This catches the case where `import-linter` is
   configured correctly but someone adds a module.
3. **`tests/test_module_size.py`.** No module file exceeds **600 lines**. The
   legacy's own build order offered "put all routes in `app.py` for simplicity"
   (D-26), and that single sentence produced 7 000 lines. A size guard makes the
   same shortcut impossible.

Every module also ships a `CONTRACT.md` next to its code: the published
functions, their inputs and outputs, the errors they raise, and the tests that
cover them. It is short by design — the point is that reading one file is enough
to work on the module.

---

## 5. Published interfaces

One line per module. This is the complete list of what may be called across a
boundary; anything else is internal and free to change at will.

| Module | Published surface |
|---|---|
| `core` | `settings`, `get_logger()`, the error hierarchy, `quota_day(now) -> date`, the port protocols and contract types (Pillar 0) |
| `accounts` | `current_workspace(request)`, `require_role(user, workspace, role)` |
| `credentials` | `add_google_client()`, `start_oauth(channel)`, `complete_oauth(code)`, `valid_access_token(channel)` |
| `sources` | `add_source(url, kind)`, `scan(source) -> ScanResult`, `hydrate(batch) -> HydrateResult` |
| `pipelines` | `create_pipeline()`, `activate(pipeline)`, `pause(pipeline)`, `missing_videos(pipeline, destination)` |
| `jobs` | `enqueue(pipeline, video, intent)`, `claim(worker) -> Job \| None`, `succeed(job)`, `fail(job, error)`, `requeue_stale()` |
| `youtube` | `sync_inventory(destination) -> InventoryDiff`, `upload(path, metadata) -> UploadResult`, `quota_remaining(destination) -> int` |
| `delivery` | `deliver(job) -> DeliveryResult`, `reconcile(destination) -> ReconcileReport`, `mark_removed(delivery, reason)` |
| `media` | `acquire(video_id) -> MediaAsset`, `verify(asset)`, `release(asset, reason)`, `retention_decisions(now)`, `hygiene()` |
| `worker` | `run_once()`, `run_forever()` — the only way to start work |
| `ops` | `audit(actor, entity, action, detail)`, `heartbeat(state)`, `purge_history(workspace, before)` |
| `ui` | HTTP routes only. It publishes no Python API, and nothing may import it. |

Errors are part of the contract. Each module raises its own typed errors —
`SourceUnresolvable`, `QuotaExhausted`, `AuthRevoked`, `AlreadyDelivered`,
`NoStorageSpace`, `DownloadFailed` — never a bare `Exception`. The caller decides
whether a failure is transient or permanent, which is what makes the retry policy
in `jobs` expressible at all.

---

## 6. Interface change log

Every change to a published interface is recorded here in the same commit. This
table is what makes INV-11 auditable: a change that touches two modules either
appears here, or it is a violation.

| Date | Module | Interface change | Reason | Data migration? |
|---|---|---|---|---|
| 2026-09-28 | `core` (base types) | **Added** three port protocols (`SourceProvider`, `DestinationPlatform`, `MetadataTransformer`), their frozen DTOs, and the provenance-marker specification (`docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`). Contract defined before code. | Pillars must be replaceable: non-YouTube source (IDEA-01), second destination platform (IDEA-02), and AI metadata rewriting (IDEA-03) all require an explicit port first (Q-2). | No |
| 2026-09-28 | `core` | **Added** `settings` (`Settings`/`get_settings()`/`APP_SETTING_DEFAULTS`), `quota_day(now)`, `get_pacific_time()`, `get_pacific_date_string()`, `is_safe_ssrf_url()`, and the Pillar 0 §8 error classes (`NetworkError`, `RateLimitExceeded`, `ResourceTemporarilyUnavailable`, `SourceUrlRejected`, `ItemUnavailable`, `TermsViolation`, `PermanentAuthError`, alias `PillarError`/`QuotaExhausted`) — all reachable via `core.api`. **Changed** `resolve_safe_path` argument order from `(target_path, base_root)` to contract §3.3's `(base_root, relative_path)`; no consumer existed yet. | U01 completion: settings with documented defaults (U01 row), contract-mandated clock/SSRF signatures (Pillar 7 §3.2–3.3), and port-boundary error vocabulary before any adapter is written. | No |
| 2026-09-28 | `accounts.api` | U02 access helper (`current_workspace`, `require_role`, `role_required` view decorator attaching `request.workspace`): anonymous → login redirect (via `login_required`), authenticated non-member / under-ranked → 403. Single-tenant: one default `workspace` + membership | `accounts` | complete |
| 2026-09-28 | `credentials.api` | U05 published surface: `add_google_client`, `update_google_client`, `client_secret`, `get_client`, `list_clients`, `deactivate_client`, `bind_channel`, `new_channel`, `get_channel`, `list_channels`, `revoke_channel`, `start_oauth`, `read_oauth_state`, `complete_oauth`, `refresh_token`, `token_health`, `refresh_channel_token`, `valid_access_token` (+ `OAuthStart`, `DEFAULT_DAILY_UPLOAD_CAP`, `PENDING_CHANNEL_PREFIX`). New module error set (`CredentialError`, `ClientNotFound`, `ChannelNotFound`, `OAuthStateInvalid`, `OAuthExchangeRejected`, `TokenMissing`, `AuthRevoked`, `TokenRefreshFailed`). | U05: `google_client` + `authorized_channel` (docs/03 §4) with INV-1 encrypted secrets, the OAuth flow, and a single `valid_access_token()` entry point so the Pillar 2 §2.2 proactive-refresh rule cannot be skipped. `valid_access_token` is the docs/04 §5 name for `valid_access_token(channel)`. | No (new tables: `google_client`, `authorized_channel`) |
| 2026-09-28 | `ui` (routes) | **Added** project shell routes `home` (`/`), `healthz` (`/healthz`), `login`/`logout` — named routes only (docs/04 §8.3); `ui` publishes no Python API (docs/04 §5). `base.html` four blocks, data-driven `NAV`, workspace context slot, Tailwind+HTMX via CDN. | U03 shell: pages arrive in Wave 4 (U16–U22); shell must exist before pages. | No |
| 2026-09-28 | `core` (port registry) | **Added** to `core.api`: `PortNotRegistered`, `register_source_provider`/`get_source_provider`, `register_destination_platform`/`get_destination_platform`, `register_metadata_transformer`/`get_metadata_transformer`, `reset_port_registry`. Implemented in `core/registry.py`; the Port A binding is installed by `ui.apps.UiConfig.ready`. | Pillar 0 §3–§5: the module that *needs* a port adapter (`worker`, `media`) may not import the module that *implements* it (`sources`, `youtube`, `delivery`) — docs/04 §2/§3 forbid those arrows. One registration point inverts the dependency without a sibling import. Interface written first (docs/07 §2), then the two units that use it. | No |
| 2026-09-28 | `sources.api` | **Added** U07 surface: `add_source(workspace, url, *, name="")` → `Source` (SSRF-validated, idempotent on `(workspace, external_id)`), `list_sources(workspace, *, include_inactive=False)`, `scan(source, *, since=None)` → `ScanOutcome` (flat metadata-only pass, upsert on `(source, video_id)`, vanished rows marked unavailable and never deleted), `hydrate(batch)` → `HydrateOutcome` (lazy; one gone item does not fail the batch), `source_provider_factory`, plus the frozen `ScanOutcome`/`HydrateOutcome` DTOs and the module error set (`SourceError`, `SourceUrlInvalid`, `SourceUnresolvable`, `SourceNotFound`, `CatalogVideoNotFound`, `ItemGone`, `HydrationRateLimited`, `ProviderUnavailable`). | U07 row: add a source with the SSRF guard and URL normalisation, flat scan, lazy hydrate with rate-limit discipline, catalog upserts. Names follow the docs/04 §5 surface (`add_source`, `scan`, `hydrate`); Pillar 1's `register_source`/`execute_source_scan` over UUID ids stays `drafting` and is reconciled in U25 (the numbered set wins, docs/README). | No (new tables: `source`, `catalog_video`) |
| 2026-09-28 | `pipelines.api` | **Added** U06 surface: `create_pipeline`, `get_pipeline`, `list_pipelines`, `update_pipeline`, `activate`, `pause`, `delete_pipeline`, `attach_source`, `detach_source`, `list_pipeline_sources`, `add_destination`, `attach_destination`, `detach_destination`, `list_pipeline_destinations`, `list_destinations`, `add_download_profile`, `get_download_profile`, `list_download_profiles`, plus the typed error set (`PipelineError`, `PipelineNotFound`, `PipelineNameTaken`, `InvalidTransition`, `PipelineNotRunnable`, `DownloadProfileNotFound`, `InvalidSetting`). `missing_videos()` is **not** published — see `pipelines/CONTRACT.md` §4. | U06 row: pipeline CRUD with `draft → active → paused`, sources and destinations per pipeline, download profile. | No (new tables: `download_profile`, `pipeline`, `pipeline_source`, `destination`, `pipeline_destination`) |
| 2026-09-28 | `jobs.api` | **Added** U08 surface: `enqueue`, `claim`, `succeed`, `fail`, `requeue_stale`, `cancel`, `skip`, `get_job`, `list_jobs`, `backoff_for`, plus the constants `DEFAULT_LEASE_MINUTES` (15), `MAX_ATTEMPTS` (5) and the typed error set (`JobError`, `JobNotFound`, `InvalidJobSetting`, `InvalidJobTransition`). | U08 row: enqueue with dedup check, atomic claim, state machine, transient/permanent classification, backoff, skip reasons. The claim is the `FOR UPDATE SKIP LOCKED` statement of docs/03 §7 and replaces the legacy's read-then-write race (P11). | No (new table: `job`) |
| 2026-09-28 | `youtube.api` | **Added** U09 surface: `probe_auth`, `sync_inventory`, `mark_absent`, `unclaimed_inventory`, `upload`, `quota_remaining`, `account_upload`, `record_quota_exhausted`, `quota_snapshot`, `default_http`, plus the Port B adapter `YouTubePlatform` (`probe_auth`/`sync_inventory`/`upload`/`unit_cost_for_upload`), the `YouTubeHttp` transport seam, the typed error set (`YouTubeError`, `UploadRejected`, `UploadNotFound`, `TokenRevoked`, `Throttled`, `PlatformUnavailable`, `QuotaExhausted`) and the constants in `youtube.http` (`DAILY_UNIT_LIMIT`, `UPLOAD_UNIT_COST`, `METADATA_UNIT_COST`, `THUMBNAIL_UNIT_COST`, `CHUNK_BYTES`). | U09 row: token refresh, inventory sync, resumable upload with progress, quota accounting, typed error translation. `youtube` is the one domain module allowed to import `credentials.api` — Port B cannot work without a token, and `valid_access_token` is the single documented way to get one. | No (new tables: `destination_inventory`, `quota_usage`) |
| 2026-09-28 | `delivery.api` | **Added** U10 surface: `deliver`, `reconcile`, `mark_removed`, `get_delivery`, `list_deliveries`, `attempts_for`, `parse_marker`, the frozen `DeliveryResult`/`ReconcileReport` DTOs, and the typed error set (`DeliveryError`, `DeliveryNotFound`, `AlreadyDelivered`, `MediaMissing`, `InvalidDeliverySetting`). | U10 row: `delivery` + `delivery_attempt`, `deliver()` with marker injection, `reconcile()` and its four outcomes, mark-as-removed. The ledger is what makes every other module's decision checkable afterwards (D-13). | No (new tables: `delivery`, `delivery_attempt`) |
| 2026-09-28 | `youtube.api` | **Added** for U10: `inventory_rows(destination)` (a read-only `InventoryRow` view of `destination_inventory`), `claim_inventory(destination, video_id, delivery)`, and the re-exported errors `Throttled`, `UploadRejected`, `TokenRevoked`, `QuotaExhausted`. | `delivery` reconciles against the channel, so it must *read* `destination_inventory` — but it may not import `youtube.models` (INV-12). The read and the single claim-write therefore become the published surface, instead of a sibling reaching into another module's table. | No (a new foreign key on `destination_inventory.matched_delivery_id`, the constraint U09 deferred) |

Rules for this table:

1. Adding a function is a change and is recorded.
2. Changing a parameter's meaning, or its error behaviour, is a change and is
   recorded; renaming a parameter without changing meaning is not.
3. An entry means "two modules were touched on purpose, by decision" — never
   "we were in a hurry".

---

## 7. Runtime shape

One codebase, two long-lived processes, one database. No message broker, no
cache server, no external queue — the job table is the queue.

```
┌───────────────────┐   reads/writes   ┌────────────┐
│ web (Django)      │◀───────────────▶│ PostgreSQL │
│ routes · views    │                  │  jobs ·    │
└───────────────────┘                  │  delivery  │
                                       └──────▲─────┘
┌───────────────────┐   claims + writes      │
│ worker            │────────────────────────┘
│ run_once() loop   │──▶ media (yt-dlp) ──▶ youtube (upload)
└───────────────────┘
```

| Process | Command | Responsibility |
|---|---|---|
| `web` | `gunicorn` / Django WSGI | HTTP, authentication, rendering, HTMX and SSE endpoints. **Never downloads or uploads.** |
| `worker` | `manage.py runworker` | Claim → dispatch → record. Owns all long-running work. |
| `db` | `postgres:16` | State. |

**The hard rule: no long-running work inside a request.** A download takes
minutes; an upload takes longer. The web process accepts an intent by writing a
row and returns immediately. That is what keeps the UI responsive during a large
backfill, and it is why a dropped connection can never half-complete an
operation.

### 7.1 Worker loop

```python
def run_once() -> bool:
    heartbeat("busy")
    job = jobs.claim(worker_id)            # atomic, SKIP LOCKED
    if job is None:
        heartbeat("idle")
        return False
    try:
        if job.intent == "upload":
            asset = media.acquire(job.source_video_id)  # no-op if on disk
            media.verify(asset)
            delivery.deliver(job)
        elif job.intent == "rehydrate":
            media.acquire(job.source_video_id)          # stops at the file
        elif job.intent == "inspect":
            sources.scan_one(job.source_video_id)
        jobs.succeed(job)
    except TransientError as exc:
        jobs.fail(job, exc, permanent=False)   # backoff, requeue
    except PermanentError as exc:
        jobs.fail(job, exc, permanent=True)    # operator-visible
    return True
```

`run_forever()` calls this and sleeps briefly when idle. Concurrency is
horizontal: run **N workers**, and `SKIP LOCKED` guarantees no two take the same
job. No tuning, no lock table, no advisory-lock dance.

### 7.2 Why two processes and not one

The legacy ran four containers sharing one SQLite file, so any process could
stall every other (D-19). Here the split is deliberate: the web process stays
responsive while workers work, but both share **one codebase, one set of models,
one set of migrations** — so there is no duplicated logic and no second copy of a
business rule to drift.

---

## 8. Dashboard shell

Server-rendered Django templates with HTMX. No build step and no JavaScript
framework, so there is no front-end asset pipeline that can rot.

### 8.1 Anatomy

```
┌──────────────────────────────────────────────────────────────────────┐
│ [context slot] │ nav: Work · Content · Operations        [user menu] │  ← base.html
├──────────────────────────────────────────────────────────────────────┤
│ Page title                                    primary · secondary btn│  ← block title
├──────────────────────────────────────────────────────────────────────┤
│ content area                                                  toasts │  ← block content
└──────────────────────────────────────────────────────────────────────┘
```

`base.html` supplies exactly four blocks: **context slot**, **nav**,
**title/actions**, **content**. Nothing else varies, so a new page is a small
template rather than a layout change.

### 8.2 Navigation is data, never markup

```python
NAV = [
    NavGroup("Work", [
        NavItem("Pipelines", "pipelines:list", roles="operator"),
        NavItem("Queue",     "queue:list",     roles="operator"),
        NavItem("Library",   "library:list",   roles="viewer"),
        NavItem("History",   "history:list",   roles="viewer"),
    ]),
    NavGroup("Content", [
        NavItem("Sources",  "sources:list",   roles="operator"),
        NavItem("Catalog",  "catalog:index",  roles="viewer"),
    ]),
    NavGroup("Operations", [
        NavItem("Credentials", "credentials:list", roles="owner"),
        NavItem("Logs",        "ops:logs",        roles="owner"),
        NavItem("Settings",    "settings:index",  roles="owner"),
    ]),
    # NavGroup("Administration", [...])   ← reserved, absent in v1
]
```

A loop renders this; a `current()` helper highlights the active item. Adding the
administration area later is appending one `NavGroup`, and the header cannot go
stale because it is computed, not written twice.

### 8.3 Named routes only — zero hardcoded URLs

Every link uses `{% url %}`, every redirect names a route, and no view
string-builds a path. The consequence matters: adding a tenant prefix later
(`/w/<slug>/…`) is a change in **one** `urls.py`, because no template and no view
knows the current shape.

### 8.4 v1 page inventory

| Page | Route name | Purpose | Key actions | Module |
|---|---|---|---|---|
| Home | `home` | Status at a glance: worker heartbeats, quota remaining today, free disk, queue depth, last errors. | — | `ops` |
| Pipelines | `pipelines:list` | List and detail: sources, destinations, download profile, retention, and the **missing-videos preview**. | activate, pause, edit | `pipelines` |
| Sources | `sources:list` | Registered sources with scan status. | add, rescan | `sources` |
| Catalog | `catalog:index` | A source's videos with filters. | star, ignore, enqueue, mark-uploaded, export CSV | `sources` |
| Queue | `queue:list` | Live jobs and failure buckets. | pause, resume, retry, cancel | `jobs` |
| Library | `library:list` | The content inventory with media-state filters. | rehydrate (one or bulk), pin, unpin | `media` |
| History | `history:list` | Deliveries and their attempts. | filter, export and import CSV, re-verify | `delivery` |
| Credentials | `credentials:list` | Google clients and authorized channels with token health. | connect, reconnect | `credentials` |
| Ops | `ops:logs` | Heartbeats and log tail. | dry-run retention, purge | `ops` |
| Settings | `settings:index` | Installation settings, storage roots, free-space floor. | edit, test root | `core` |

Every page listed here exists because a legacy defect or a decision demands it.
There is no page whose only purpose is to look like a dashboard.

### 8.5 Component conventions

| Convention | Why |
|---|---|
| Every mutation returns the **re-rendered row or fragment**, never a full page reload. | Instant feedback and no lost scroll position. |
| One fragment prefix — `/partials/…`. | The legacy shipped two (`/fragments` *and* `/partials`), so its own documentation disagreed with its own code. |
| SSE **only** for `queue:list`; 5-second polling elsewhere. | Live updates where they matter, cheap everywhere else. |
| Bulk actions over 10 rows require typing the count. | The legacy RFC's own safety rule. |
| Enqueue controls show a quota badge — *ManhuaNova (4/6 today)*. | The operator sees the cost before acting. |
| Every skipped row shows **why**, on the row. | Fixes D-07: never a silent non-action. |
| Empty states explain the next action. | A blank table is not an answer. |
| Confirm dialogs state count, destination and privacy. | Destructive actions must be legible. |
| Theme: Tailwind and HTMX via CDN, dark, no build step. | No asset pipeline to break, no version drift. |

### 8.6 Reserved tenant slots

- **Header context slot** — shows the active workspace name. Becomes a switcher
  with no layout change.
- **`NAV` structure** — ready to receive an `Administration` group.
- **One access helper** resolved per request — roles slot in without editing any
  view.
- **URL shape** flat today, prefixable later because of §8.3.

None of this is *behavioural* in v1 (D11). These are placeholders in the shell,
which is precisely what makes the dashboard not need redesigning later.

---

## 9. Security

| Concern | Rule |
|---|---|
| **Authentication** | Required on every view. Django session auth; anonymous requests get redirected to login, never a partial page. (D16) |
| **Authorization** | Three roles exist (`owner`, `operator`, `viewer`) and are checked in **one** helper. In v1 only `owner` is used; the other roles are inert until they are needed. |
| **CSRF** | Django CSRF on every state-changing request; HTMX sends the token via header. |
| **Credentials at rest** | Tokens and client secrets are `bytea`, encrypted with `SECRET_ENCRYPTION_KEY`. The key comes from the environment, is **never** stored in the database, and is backed up alongside it — lose the key and the tokens are unrecoverable, which is stated in the backup procedure, not left to be discovered. (fixes D-11, D-22) |
| **Version control** | `.gitignore` is mandatory from the first commit: `.env`, `db/*.db*`, `media/`, `cookies.txt`, `*.pem`, `.venv`, `__pycache__`, `local_settings.py`, and any token export. CI fails on a secret-looking string in tracked files. (fixes D-12, D-20, D-25) |
| **SSRF** | Every operator-supplied URL is validated before use: `http(s)` only, host allow-listed to YouTube (`youtube.com`, `youtu.be`, `youtube-nocookie.com`), bounded timeout. (carried over from the legacy's own RFC) |
| **Media path safety** | Any file deletion must resolve **inside** a configured storage root; the path is resolved and compared, not trusted. (the legacy already had this guard — worth keeping) |
| **Docker socket** | Not mounted anywhere. Log viewing reads log files. (fixes D-05) |
| **Sessions** | `secure`, `httponly`, `samesite=Lax`; rotate on login. |
| **Transport** | TLS terminated at a reverse proxy; the database port is never published. |

---

## 10. Deployment

### 10.1 Compose services

| Service | Image | Ports | Notes |
|---|---|---|---|
| `web` | build `.` | `8080` | Django + gunicorn. Healthcheck `GET /healthz`. |
| `worker` | same image, different command | none | `manage.py runworker`. Scale with `--scale worker=N`. |
| `db` | `postgres:16` | *internal only* | Named volume. Healthcheck `pg_isready`. |

Same image for `web` and `worker` is deliberate: one artefact, one set of
dependencies, no possibility of the two drifting apart.

### 10.2 Volumes and paths

| Path | Contents | Backed up |
|---|---|---|
| `./db` | PostgreSQL data | yes, daily |
| `./media` | the `hot` storage root | no — derivable, re-downloadable |
| `./logs` | application and worker logs | no |
| `./secrets` | `SECRET_ENCRYPTION_KEY`, OAuth credentials | **yes, with the database** |

A cold root (an external drive) is mounted as an extra volume and marked
`is_mounted` in `storage_root`.

### 10.3 Start-up order

1. `manage.py migrate` runs as a **one-shot step** that completes before `web`
   or `worker` start (`depends_on: service_completed_successfully`).
2. Data migration creates the default workspace, owner membership, default
   storage root, default download profile and `app_setting` rows (03 §11).
3. `web` and `worker` start.
4. `worker` writes `worker_heartbeat`; `web` reports staleness after three missed
   intervals.

### 10.4 Backups

- `pg_dump` daily to a location outside `./db`.
- The encryption key file is copied **in the same operation** — a dump without
  the key restores a database of unreadable tokens.
- Take a backup before any maintenance or migration (the legacy's own
  convention, kept as a rule).
- Restore is tested, or it is not a backup.

### 10.5 Day-two operations

| Task | How |
|---|---|
| More throughput | `--scale worker=N`. Nothing else changes. |
| Disk pressure | Settings page shows `storage_root` free space against `min_free_bytes`; the admission gate stops new downloads before it becomes critical. |
| Stuck worker | `worker_heartbeat` shows stale; claims are expired and requeued automatically. |
| Observability | Home page: heartbeats, quota left, free disk, queue depth, recent errors. |
| Log rotation | Rotated files under `./logs`; no container-log tailing needed. |