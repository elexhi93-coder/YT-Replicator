# 03 — Interface Contract

**Pillar:** 0 · Inter-Pillar Contracts · **Chapter:** Interface Contract · **Status:** `drafting`
**Depends on:** `docs/00` §2, §5, §6 · `docs/02` §4–§6 · `docs/03` §3–§9 · `docs/04` §2–§5 · `docs/05` §4–§6
**Invariants touched:** INV-3, INV-5, INV-7, INV-9, INV-11, INV-12

---

## 1. Purpose

This chapter defines the **only** vocabulary and the **only** interfaces by which
one pillar may ask another for work: three ports, the contract types that cross
between them, the rules of exchange, the errors that may cross, and the
provenance-marker format.

It does **not** define how any of them is implemented, which pillar performs
which step, or what any screen looks like. Those belong to Pillars 1–7.

**Why a port, and not a plain function call.** A pillar is replaceable only if
what it *must* provide is written down separately from *who* provides it. If
`media` called `sources.download()` directly, a non-YouTube source could never be
introduced without editing `media` — INV-11 would be broken by design, and the
legacy's coupling would simply move rather than disappear.

**The three futures this buys** (`000_AI_ARCHITECT_INSTRUCTIONS.md` §4):

| Idea | The port that makes it cheap |
|---|---|
| IDEA-01 — a video editor, local folder or cloud bucket as a source | `SourceProvider` |
| IDEA-02 — Facebook, TikTok, Dailymotion as destinations | `DestinationPlatform` |
| IDEA-03 — AI metadata rewriting, optional, off by default | `MetadataTransformer` |

**One implementation each in v1.** A port with zero implementations is dead
weight; a second implementation is a v2 decision recorded in the Idea Vault. v1
ships: YouTube source, YouTube destination, pass-through metadata.

---

## 2. The published surface at a glance

Three ports, declared as `typing.Protocol` in `core`'s base types. **Module
owner: Pillar 7. Interface owner: this pillar** — the module may change freely;
these signatures may not change without a `docs/04` §6 row.

| Port | v1 implementation | Called by | Never called by |
|---|---|---|---|
| `SourceProvider` | the `sources` module (YouTube via yt-dlp) | `sources`; `media` for `materialize` only | `ui`, `ops`, `worker` |
| `DestinationPlatform` | the `youtube` adapter (Pillar 2) | `delivery` (Pillar 6), through the port | `ui`, `jobs`, `worker`, `media` |
| `MetadataTransformer` | `PassthroughTransformer` (v1) | `delivery` (Pillar 6), inside the upload path | everyone else |

Three rules apply to **every** method below, and are contract-test material:

- **R1 — typed errors only.** It raises from the hierarchy in §8, never a bare
  `Exception`, never an ORM error, never a library-specific exception.
- **R2 — no database writes.** A port is I/O to the outside world only.
  Persistence is the calling pillar's job. This is what keeps `docs/03`'s tables
  owned by exactly one pillar each.
- **R3 — bounded time.** Every call completes within a timeout taken from
  `app_setting`; none may run unbounded. A port that can hang forever cannot be
  claimed by a worker, and claiming is what makes the queue honest.

---

## 3. Port A — `SourceProvider`

**Specification owner:** Pillar 1. **v1 implementation:** the `sources` module.
**Future implementation:** an editor / local-folder / bucket adapter (IDEA-01).

### 3.1 `resolve(raw_url: str) -> ResolvedSource`

- **Purpose:** turn what the operator typed into a canonical identity — or refuse it.
- **Inputs:** the raw URL string. **Outputs:** `ResolvedSource` (§6.1).
- **Raises:** `SourceUrlRejected` (permanent — host not allowed, shape unsupported),
  `TransientError` (the platform could not be reached to resolve an `@handle`).
- **Side effects:** none.
- **Guard:** the **SSRF allow-list** (`docs/04` §9) is applied *inside* the
  implementation, so no caller can forget it. Normalisation rules (`docs/05` §1):
  a channel URL gains `/videos` unless it already ends in `/videos`, `/streams` or
  `/shorts`; the URL is stored exactly as typed and the resolved id separately
  (`docs/03` §5).
- **Idempotent:** yes.

### 3.2 `scan(source: SourceRef, since: datetime | None) -> Iterator[SourceItem]`

- **Purpose:** list what the source exposes — **metadata only**.
- **Inputs:** the source, and an optional lower bound. The bound is a **cursor,
  never a list** (`docs/05` §3).
- **Outputs:** a lazy iterator of `SourceItem` (§6.2) — lazy so an interrupted
  scan still yields everything fetched so far.
- **Raises:** `TransientError` (feed unavailable or rate-limited),
  `PermanentError` (source deleted, made private).
- **Side effects:** **none on our database, ever.** The caller upserts
  `catalog_video`; this call must not — **INV-7**, enforced by a contract test.
- **Partial-failure rule (F-48):** one unavailable, private or deleted item is
  *recorded and skipped*; the iterator continues and never aborts the scan.
- **Idempotent:** yes.

### 3.3 `hydrate(item: VideoRef) -> SourceItemDetail`

- **Purpose:** fetch the expensive fields — description, tags, view and like
  counts, category (`docs/05` §2).
- **Raises:** `TransientError`, `PermanentError` (item withdrawn).
- **Side effects:** none on our database; the caller writes `catalog_video` and
  `hydrated_at`.
- **Rate discipline:** one call, single thread, at least
  `hydrate_interval_seconds` between calls; the caller aborts its batch when a 429
  was seen within `hydrate_abort_on_429_minutes`. **The implementation must not
  retry internally** — retry policy belongs to `jobs` (Pillar 4) and nowhere else.

### 3.4 `materialize(request: MaterializeRequest) -> MaterializedMedia`

- **Purpose:** bring one video's bytes **into a storage root we own**.
- **Inputs:** `MaterializeRequest` (§6.3): the video, an already-resolved target
  directory inside a chosen storage root, and the resolved `download_profile`.
- **Outputs:** `MaterializedMedia` (§6.4) — path, filename, size, `sha256`, duration.
- **Raises:** `TransientError` (network, 5xx, rate limit, corruption that a retry
  may cure), `PermanentError` (unavailable, private, geo-blocked),
  `NoStorageSpace` (the caller's gate should have caught this first).
- **Side effects:** writes **inside the given directory only**. It never chooses a
  root, never renames into place, never deletes anything, never writes a
  `media_asset` row. Root choice, the free-space gate, the `.part` discipline, the
  atomic rename and the `media_event` all belong to `media` (Pillar 5,
  `docs/05` §5).
- **Non-obvious but required:** the result must be a **complete, seekable local
  file** — a partial is never returned as success. It is still *unverified*:
  `media.verify` recomputes size and `sha256`, because **INV-3 is enforced at
  exactly one place**, and that place is not here.
- **Idempotent in effect, not in cost:** calling it twice for the same video
  produces a second materialization (`materialization_no += 1`), which is correct
  — `docs/03` §9 records that copies need not be byte-identical.

**A source that has no network at all** (an editor, a local folder) implements
this as a copy or a move into the target directory and inherits every rule above
unchanged. That is the whole point of the port: `media` cannot tell the
difference, and `docs/05` §5's flow does not change by one line.

---

## 4. Port B — `DestinationPlatform`

**Specification owner:** Pillar 2. **v1 implementation:** the `youtube` adapter
(owned by Pillar 2). **Future implementation:** a Facebook, TikTok or
Dailymotion adapter (IDEA-02).

### 4.1 `probe_auth(credentials: DecryptedCredentials) -> AuthState`

- **Purpose:** verify that stored credentials still work, and read their scope and
  expiry (`docs/05` §10).
- **Inputs:** decrypted platform credentials (decrypted only within Pillar 2,
  never logged — **INV-9**).
- **Outputs:** `AuthState` (§6.5) — `valid`, `expiring`, `invalid`, `revoked`.
- **Raises:** `TransientError` (platform unreachable). It **never raises on an
  invalid token** — it returns `AuthState(state='invalid', ...)`, because
  invalid auth is an expected state, not an exceptional one.
- **Side effects:** may refresh a token against the platform if it is within the
  refresh window, and return the refreshed bundle in `AuthState`. Persistence of
  the new refresh bundle belongs to the caller (Pillar 2 / `credentials`).
- **Idempotent:** yes.

### 4.2 `sync_inventory(channel: ChannelRef, cursor: str | None) -> InventoryBatch`

- **Purpose:** read a page of videos currently published at the destination, for
  reconciliation (`docs/05` §6 step A, `docs/05` §7).
- **Inputs:** the channel identity, and a pagination cursor (never an offset).
- **Outputs:** `InventoryBatch` (§6.6) — a list of `DestinationVideoDTO` and a
  next cursor (or `None` when exhausted).
- **Raises:** `TransientError`, `PermanentAuthError` (channel revoked).
- **Side effects:** none on our database. The caller (Pillar 2) writes
  `destination_inventory`.
- **Provenance-marker duty:** the implementation extracts the marker from the
  description if present, and populates `DestinationVideoDTO.marker`. It does not
  interpret the marker — parsing is Pillar 6's job (rule R5, §7).
- **Idempotent:** yes.

### 4.3 `upload(request: UploadRequest, on_progress: ProgressCallback | None) -> UploadOutcome`

- **Purpose:** perform the physical upload of one video to one destination channel.
- **Inputs:** `UploadRequest` (§6.7) — verified media path, title, description,
  tags, category, privacy, compliance declarations, optional thumbnail path,
  and the computed provenance marker to append.
- **Progress:** an optional callback `(bytes_sent, total_bytes) -> None`, called
  after each chunk so the caller can emit SSE progress (`F-24`).
- **Outputs:** `UploadOutcome` (§6.8) — destination video id, destination URL,
  privacy applied, platform units consumed, HTTP status, platform error detail
  if any.
- **Raises:** `TransientError` (network dropped, resumable 5xx, rate limit),
  `PermanentError` (quota exhausted, format rejected, terms violation, channel
  terminated). **Typed errors only** (§8).
- **Side effects on the platform:** creates a video row on the destination.
  **Side effects on our database:** none. Pillar 6 writes `delivery_attempt`,
  records the ledger row, and transitions the job.
- **Not idempotent:** calling it twice publishes twice. The calling pillar
  (`delivery`, Pillar 6) is therefore required to **reconcile before retry**
  (`docs/05` §6 step A) — this port assumes the caller obeys that contract.
- **Resumable uploads (F-22):** the implementation uses chunked resumable
  transfers (1 MB chunks for YouTube). It holds chunk state in memory for the
  duration of the call; it does **not** persist chunk tokens across process
  restarts in v1.
- **Thumbnail handling (F-25):** if `thumbnail_path` is provided, the
  implementation uploads it as the video thumbnail after the video payload
  succeeds, converting WebP to JPEG if the platform requires it. If the
  thumbnail upload fails after the video succeeds, the call **succeeds** and
  records a warning flag in `UploadOutcome` — a video is not failed because its
  thumbnail failed.

### 4.4 `unit_cost_for_upload() -> int`

- **Purpose:** declare how many quota units a single upload consumes on this
  platform, so Pillar 2 can compute quota availability without hard-coding
  platform numbers.
- **Outputs:** an integer (e.g. `1600` for YouTube v3 `videos.insert`).
- **Idempotent:** pure constant per adapter.
- **A platform with no quota** (e.g. a future Facebook adapter) returns `0`.
  The quota check then naturally becomes a no-op, without any `if platform ==`
  branches in the calling code.

---

## 5. Port C — `MetadataTransformer`

**Specification owner:** Pillar 3 / 6 boundary. **v1 implementation:**
`PassthroughTransformer` (in `core`). **Future implementation:** an AI-powered
rewriter (IDEA-03).

### 5.1 `transform(input: TransformInput) -> TransformResult`

- **Purpose:** rewrite title, description and tags between source and destination,
  or leave them unchanged.
- **Inputs:** `TransformInput` (§6.9) — original title, description, tags, target
  language, and an optional prompt template.
- **Outputs:** `TransformResult` (§6.10) — title, description, tags,
  `applied: bool`, and a fallback reason if it was not applied.
- **Raises:** **never raises.** A transformer is a pure function. On any failure
  (timeout, malformed output, downstream LLM error), it returns the input
  verbatim, sets `applied=False`, and records the reason.
- **Side effects:** none.
- **Pure-function invariant:** same inputs and rules must produce the same
  output. No database access, no network except to the optional configured LLM
  endpoint, no mutation of input objects.


---

## 6. Contract types (DTOs, field by field)

Every type here is a **frozen dataclass** (immutable). None inherits from an
ORM base; none holds a database session; none imports a sibling module. Types
are defined in `core`'s base types.

### 6.1 `ResolvedSource`
```python
@dataclass(frozen=True)
class ResolvedSource:
    kind: str                   # 'channel' | 'playlist'
    external_id: str            # canonical ID, e.g. UC... or PL...
    canonical_url: str          # normalised URL with trailing /videos if channel
    title: str | None           # resolved display title, if fetched at resolve time
```

### 6.2 `SourceItem` and `SourceItemDetail`
```python
@dataclass(frozen=True)
class SourceItem:
    video_id: str               # 11-char YouTube ID (or external ID for other sources)
    title: str
    published_at: datetime | None
    duration_sec: int | None
    thumbnail_url: str | None
    live_status: str            # 'not_live' | 'live' | 'was_live'
    availability: str           # 'public' | 'unlisted' | 'private' | 'unknown'

@dataclass(frozen=True)
class SourceItemDetail:
    video_id: str
    description: str | None
    tags: tuple[str, ...]       # immutable tuple, never a mutable list
    category_id: str | None
    view_count: int | None
    like_count: int | None
    hydrated_at: datetime
```

### 6.3 `MaterializeRequest` and 6.4 `MaterializedMedia`
```python
@dataclass(frozen=True)
class MaterializeRequest:
    video_id: str
    destination_dir: Path       # absolute path inside a resolved storage root
    max_height: int             # e.g. 1080 (from download_profile)
    prefer_format: str          # 'mp4' | 'mkv' | 'best'

@dataclass(frozen=True)
class MaterializedMedia:
    file_path: Path             # complete, seekable file inside destination_dir
    filename: str               # relative filename (e.g. "{id}.mp4")
    size_bytes: int
    sha256: str                 # unverified sha256 declared by the materializer
    duration_sec: int | None
    format: str                 # container format actually written
```

### 6.5 `AuthState`
```python
@dataclass(frozen=True)
class AuthState:
    state: str                  # 'valid' | 'expiring' | 'invalid' | 'revoked'
    channel_id: str
    channel_title: str | None
    scopes: tuple[str, ...]
    expires_at: datetime | None
    refreshed_bundle: str | None  # new encrypted bundle, if refreshed during probe
```

### 6.6 `InventoryBatch` and `DestinationVideoDTO`
```python
@dataclass(frozen=True)
class DestinationVideoDTO:
    destination_video_id: str
    title: str
    description_excerpt: str    # first 500 chars (docs/03 §8)
    published_at: datetime | None
    privacy_status: str         # 'public' | 'unlisted' | 'private'
    duration_sec: int | None
    marker: str | None          # raw provenance marker if found in description

@dataclass(frozen=True)
class InventoryBatch:
    items: tuple[DestinationVideoDTO, ...]
    next_cursor: str | None     # None when exhaustion reached
```

### 6.7 `UploadRequest` and 6.8 `UploadOutcome`
```python
@dataclass(frozen=True)
class UploadRequest:
    source_video_id: str
    media_path: Path            # verified local file
    title: str                  # ≤ 100 chars (YouTube limit)
    description: str            # ≤ 5000 chars, with marker appended
    tags: tuple[str, ...]
    category_id: str
    privacy: str                # 'public' | 'unlisted' | 'private'
    made_for_kids: bool
    contains_synthetic_media: bool
    thumbnail_path: Path | None # verified local image, or None
    provenance_marker: str      # the exact marker line embedded in description

@dataclass(frozen=True)
class UploadOutcome:
    destination_video_id: str
    destination_url: str
    privacy: str
    units_used: int             # platform quota units consumed
    http_status: int
    raw_error_code: str | None  # populated only on error
    thumbnail_uploaded: bool    # False if thumbnail failed after video succeeded
```

### 6.9 `TransformInput` and 6.10 `TransformResult`
```python
@dataclass(frozen=True)
class TransformInput:
    source_title: str
    source_description: str | None
    source_tags: tuple[str, ...]
    target_language: str | None
    template_name: str | None

@dataclass(frozen=True)
class TransformResult:
    title: str
    description: str
    tags: tuple[str, ...]
    applied: bool               # False if fallback occurred
    fallback_reason: str | None # None if applied is True
```

### 6.11 Identity references
```python
@dataclass(frozen=True)
class SourceRef:
    source_id: int
    kind: str
    external_id: str
    url: str

@dataclass(frozen=True)
class ChannelRef:
    channel_id: int
    platform: str               # 'youtube' in v1
    external_channel_id: str

@dataclass(frozen=True)
class VideoRef:
    source_id: int
    video_id: str               # the source's external ID (11 chars for YouTube)
```


---

## 7. Rules of exchange

These six rules are **invariants of the highway**. A PR that violates any one
of them fails code review even if every test passes:

- **R1 — Immobility:** DTOs are frozen. A pillar never mutates an incoming DTO;
  it produces a new one.
- **R2 — No foreign writes:** a port method performs external I/O only. It never
  touches an engine, never opens a transaction, never inserts a row. The calling
  pillar owns the transaction, the table, and the failure record.
- **R3 — Single-direction calling:** calls flow from orchestrator to provider.
  `delivery` calls `DestinationPlatform`; the platform never calls `delivery`.
  `media` calls `SourceProvider.materialize`; the provider never calls `media`.
  Circular calls between pillars are forbidden.
- **R4 — No raw platform types cross:** `googleapiclient` objects, `yt-dlp` info
  dicts, raw HTTP responses and OAuth credential dicts **never cross a port
  boundary**. They are absorbed inside the adapter and mapped to a contract type.
- **R5 — Parsing is caller work:** the destination adapter returns the raw marker
  string it saw; it does not parse or interpret it. Pillar 6 parses it. That keeps
  reconciliation logic in Pillar 6, where the ledger lives.
- **R6 — Retry policy is owned by jobs:** no port method retries on transient
  failure internally. It raises a `TransientError`; `jobs` (Pillar 4) catches it,
  records the attempt, computes exponential backoff with jitter (`docs/04` §7),
  and reschedules. Internal retries inside a port hide failures from the
  operator and starve the worker pool.

---

## 8. Errors that may cross a boundary

All errors crossing a port boundary inherit from `core.PillarError`. Adapters
catch platform-specific exceptions and re-raise one of these:

```
PillarError (base)
├── TransientError                 # jobs will retry with backoff
│   ├── NetworkError               # timeout, connection reset, 5xx
│   ├── RateLimitExceeded          # 429, platform throttle; carries retry_after_sec
│   └── ResourceTemporarilyUnavailable
├── PermanentError                 # jobs will NOT retry; marks failed
│   ├── SourceUrlRejected          # SSRF reject, bad host, malformed shape
│   ├── ItemUnavailable            # deleted, private, geo-blocked
│   ├── TermsViolation             # platform rejected content/metadata
│   └── QuotaExhausted             # platform quota hit; carries reset_at
└── PermanentAuthError             # credentials revoked, channel gone
```

**Rule:** if an adapter encounters an error it does not recognise, it wraps it
as `TransientError(f"unclassified: {err}")` on the first attempt so that a
fluke does not permanently fail a job — but logs the raw exception with
`logger.exception()` at level `ERROR` so the operator sees the unmapped case.


---

## 9. The provenance-marker format

The provenance marker is the breadcrumb that lets YT-Replicator reconcile its
ledger after total data loss (`docs/00` INV-5, `docs/05` §6).

### 9.1 Format specification

The marker is a **single text line** appended to the end of the destination
description:

```
[ref:{source_video_id}:{delivery_id}]
```

Example: `[ref:dQw4w9WgXcQ:42]`

### 9.2 Parsing and generation rules

- **Generation (Pillar 6):** Pillar 6 formats the marker before calling
  `upload()`. It ensures the description plus marker does not exceed 5,000
  characters (YouTube limit). If truncation is required, the original description
  is truncated to 4,940 characters, a newline is added, and the marker is
  appended. **The marker is never truncated.**
- **De-duplication:** before appending, any existing `[ref:...]` line at the end
  of the description is stripped, so re-uploading or editing never stacks markers.
- **Parsing regex:**
  ```python
  import re
  PROVENANCE_MARKER_REGEX = re.compile(
      r"\[ref:(?P<source_video_id>[A-Za-z0-9_-]{11}):(?P<delivery_id>\d+)\]$"
  )
  ```
  Anchored at the end of the text. Whitespace after the marker is stripped before
  matching.
- **Recovery semantics:** if `delivery_id` matches an existing row, the match is
  `claimed_ok`. If `delivery_id` is unknown (e.g. after a disaster recovery from
  a fresh database), the `source_video_id` is used to match by source video, and
  a new delivery row is created with state `claimed_recovered`.

---

## 10. Who may call what (dependency map)

```
┌─────────────────────────────────────────────────────────────┐
│                      PILLAR 0 (Contracts)                   │
│   SourceProvider  │  DestinationPlatform  │  MetadataTrans  │
└──────────▲───────────────────▲─────────────────────▲────────┘
           │                   │                     │
┌──────────┴────────┐  ┌───────┴──────────┐  ┌───────┴────────┐
│ Pillar 1 (Sources)│  │ Pillar 6         │  │ Pillar 6       │
│ calls resolve,    │  │ (Delivery)       │  │ (Delivery)     │
│ scan, hydrate     │  │ calls upload()   │  │ calls          │
│                   │  │ via port         │  │ transform()    │
│ Pillar 5 (Media)  │  │                  │  │ before upload  │
│ calls materialize │  │ Pillar 2         │  └────────────────┘
│ via port          │  │ (Destinations)   │
└───────────────────┘  │ implements       │
                       │ DestinationPlat  │
                       │ via YouTube adap │
                       └──────────────────┘
```

**Forbidden calls (contract-test enforced):**
- Pillar 4 (`jobs`) never calls any port directly; it only runs jobs whose
  handlers call ports.
- Pillar 7 (`ui`, `worker`, `ops`) never imports or calls any port directly.
- No port implementation may call another port.

---

## 11. Versioning: what is a breaking change

Every contract type and port in this chapter is **versioned by addition only**:

| Change type | Permitted? | Obligation |
|---|---|---|
| Adding an optional field to a DTO (with default `None`) | Yes | Update this chapter |
| Adding a new method to a port with a default implementation | Yes | Update this chapter + adapters |
| Changing a field's name or type | **Breaking** | Requires migration; `docs/04` §6 row mandatory |
| Removing a field or method | **Breaking** | Deprecate for 1 release; `docs/04` §6 row mandatory |
| Changing error classification (transient ↔ permanent) | **Breaking** | Affects retry loops; requires review |

---

## 12. Deliberately not in this contract

- **No routing rules:** which sources feed which destinations is owned by
  Pillar 3 (`pipelines`), not by ports.
- **No scheduling or queue logic:** owned by Pillar 4 (`jobs`).
- **No credential encryption:** owned by Pillar 2 (`credentials`). Decrypted
  credentials exist only within the adapter call stack.
- **No disk layout or retention rules:** owned by Pillar 5 (`media`).

---

## 13. Open questions

None. All types and signatures derive directly from `docs/02` §4–§6, `docs/03`
§5/§8, and `docs/05` §1–§6.

---

## 14. Change log

- **2026-09-28:** Authored initial interface contract (Ports A, B, C; DTOs;
  exchange rules R1–R6; marker format; error hierarchy; dependency map).

