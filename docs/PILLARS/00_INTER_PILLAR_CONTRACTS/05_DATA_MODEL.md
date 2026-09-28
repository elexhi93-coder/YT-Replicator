# 05 — Data Model & Transfer Objects

**Pillar:** 0 · Inter-Pillar Contracts · **Chapter:** Data Model & Transfer Objects · **Status:** `drafting`
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/04_LOGIC_AND_RULES.md` · `docs/00` §2 · `docs/03` §1–§8 · `docs/04` §2, §5
**Invariants touched:** INV-1, INV-3, INV-7, INV-8, INV-11, INV-12

---

## 1. Purpose

This chapter defines the universal Data Transfer Object (DTO) taxonomy, field typing
rules, immutability constraints, serialization formats, and cross-boundary identity
models for Pillar 0 (Inter-Pillar Contracts).

It does **not** specify internal relational database schemas or ORM mappings.
Relational persistence tables (`sources`, `catalog_videos`, `deliveries`, etc.) are
exclusively governed by `docs/03_DATABASE_SCHEMA.md` and their respective pillars.
Pillar 0 owns solely the transient, cross-boundary data shapes exchanged between ports.

---

## 2. Architectural Boundaries: DTO vs. ORM Entity

To uphold **INV-11** (modular change isolation) and **INV-12** (explicit boundaries),
system entities exist in two strictly segregated representations:

```
┌────────────────────────────────────────────────────────┐
│                   PILLAR BOUNDARY                      │
│                                                        │
│  [Pillar Storage/Relational Layer]                     │
│      PostgreSQL 16 Tables (docs/03)                    │
│      Mutable SQLAlchemy / Row Models                   │
│      Database Transactions & Foreign Keys              │
│                     │                                  │
│                     ▼  [Adapter / Mapper Ingestion]    │
│  [Pillar 0 Inter-Pillar Contract Boundary]             │
│      Frozen Data Transfer Objects (DTOs)               │
│      Pure Python Builtins (str, int, datetime, tuple)  │
│      Zero DB Session / Zero Lazy Loading References    │
│                     │                                  │
│                     ▼  [Port Call Invocation]          │
│  [Receiving Pillar Boundary]                           │
│      Stateless Consumer (No ORM Leakage)               │
└────────────────────────────────────────────────────────┘
```

### Separation Rules
1. **Zero ORM Leakage**: A DTO must never inherit from `SQLAlchemy.DeclarativeBase` or
   contain `Session`, `Query`, or active relations.
2. **Value Semantics**: Equality (`__eq__`) and hashing (`__hash__`) are determined
   strictly by field values, never by identity pointer or database surrogate ID.
3. **Deep Immutability**: All collections embedded in DTOs are immutable tuples
   (`tuple[T, ...]`), never mutable lists or dicts.

---

## 3. Core Contract Type Specifications (Part 1: Ingestion & Discovery)

All DTOs reside in `core.contracts.dto` and are decorated with `@dataclass(frozen=True)`.

### 3.1 Source Ingestion & Discovery

#### `SourceRef`
Uniquely identifies a tracked source within the catalog boundary.
```python
@dataclass(frozen=True)
class SourceRef:
    source_id: int            # Surrogate primary key in our database
    kind: str                 # 'channel' | 'playlist'
    external_id: str          # Canonical platform identifier (e.g., 'UC...', 'PL...')
    url: str                  # Normalized URL
```

#### `ResolvedSource`
Result of initial URL analysis, validation, and SSRF verification.
```python
@dataclass(frozen=True)
class ResolvedSource:
    kind: str                 # 'channel' | 'playlist'
    external_id: str          # Canonical ID
    canonical_url: str        # Normalized URL (e.g. appends '/videos' for channels)
    title: str | None         # Resolved display name (None if resolved offline)
```

#### `VideoRef`
Composite identifier referencing a specific video under a specific source.
```python
@dataclass(frozen=True)
class VideoRef:
    source_id: int            # Our local database source primary key
    video_id: str             # Remote platform video ID (11 chars for YouTube)
```

#### `SourceItem`
Flat metadata discovered during source scanning. Contains zero expensive attributes.
```python
@dataclass(frozen=True)
class SourceItem:
    video_id: str             # Exact platform video identifier
    title: str                # Sanitized display title
    published_at: datetime | None  # UTC timestamp of initial publication
    duration_sec: int | None  # Video duration in seconds
    thumbnail_url: str | None # Best available public thumbnail URL
    live_status: str          # 'not_live' | 'live' | 'was_live'
    availability: str         # 'public' | 'unlisted' | 'private' | 'unknown'
```

#### `SourceItemDetail`
Rich, fully hydrated metadata retrieved lazily or on-demand.
---

## 4. Core Contract Type Specifications (Part 2: Media, Destination & Delivery)

### 4.1 Media & Storage Verification

#### `MaterializeRequest`
Input payload directing the download port to fetch remote media bytes.
```python
@dataclass(frozen=True)
class MaterializeRequest:
    video_id: str
    destination_dir: Path     # Absolute resolved path on local storage
    max_height: int           # Target ceiling (e.g. 1080) from download_profile
    prefer_format: str        # 'mp4' | 'mkv' | 'best'
```

#### `MaterializedMedia`
Output payload declaring verified physical assets on disk.
```python
@dataclass(frozen=True)
class MaterializedMedia:
    file_path: Path           # Seekable media file inside destination_dir
    filename: str             # Normalized filename
    size_bytes: int           # Exact byte count
    sha256: str               # Hex digest calculated over file payload
    duration_sec: int | None
    format: str               # Actual container format written ('mp4', etc.)
```

### 4.2 Destination & Authentication

#### `ChannelRef`
Surrogate reference to an authorized destination channel.
```python
@dataclass(frozen=True)
class ChannelRef:
    channel_id: int           # Local database primary key
    platform: str             # 'youtube' (extensible in v2)
    external_channel_id: str  # Destination platform identifier (e.g., 'UC...')
```

#### `AuthState`
Health status probe for platform authorization credentials.
```python
@dataclass(frozen=True)
class AuthState:
    state: str                # 'valid' | 'expiring' | 'invalid' | 'revoked'
    channel_id: str           # Remote channel ID
    channel_title: str | None # Channel display name
    scopes: tuple[str, ...]   # Authorized OAuth scopes
    expires_at: datetime | None
    refreshed_bundle: str | None  # Re-encrypted token payload if refreshed in flight
```

#### `DestinationVideoDTO`
Metadata entry retrieved during destination channel inventory reconciliation.
```python
@dataclass(frozen=True)
class DestinationVideoDTO:
    destination_video_id: str # Remote video identifier on destination
    title: str                # Remote video title
    description_excerpt: str  # First 500 characters of description
    published_at: datetime | None
    privacy_status: str       # 'public' | 'unlisted' | 'private'
    duration_sec: int | None
    marker: str | None        # Raw parsed '[ref:{source_id}:{delivery_id}]' or None
```

#### `InventoryBatch`
Paginated slice of destination video inventory.
```python
@dataclass(frozen=True)
class InventoryBatch:
    items: tuple[DestinationVideoDTO, ...]  # Immutable tuple of video records
    next_cursor: str | None                 # Page token; None indicates end of stream
```

```python
@dataclass(frozen=True)
class SourceItemDetail:
    video_id: str
    description: str | None
    tags: tuple[str, ...]     # Frozen sequence of tags
    category_id: str | None   # Platform category code (e.g., '22')
    view_count: int | None
    like_count: int | None
    hydrated_at: datetime     # UTC timestamp when hydration succeeded
```

### 4.3 Transformation & Delivery

#### `TransformInput`
Original source metadata delivered to the transformation port.
```python
@dataclass(frozen=True)
class TransformInput:
    source_title: str
    source_description: str | None
    source_tags: tuple[str, ...]
    target_language: str | None
    template_name: str | None
```

#### `TransformResult`
Transformed metadata returned by the transformer (or original metadata on fallback).
```python
@dataclass(frozen=True)
class TransformResult:
    title: str
    description: str
    tags: tuple[str, ...]
    applied: bool             # False if fallback occurred
    fallback_reason: str | None  # None if applied is True
```

#### `UploadRequest`
Complete payload required to execute a platform video insertion.
```python
@dataclass(frozen=True)
class UploadRequest:
    source_video_id: str
    media_path: Path          # Verified local file path
    title: str                # Sanitized, length-bounded title (≤ 100 chars)
    description: str          # Description containing appended provenance marker
    tags: tuple[str, ...]     # Final sanitized tags
    category_id: str          # Destination platform category ID
    privacy: str              # 'public' | 'unlisted' | 'private'
    made_for_kids: bool       # COPPA flag
    contains_synthetic_media: bool
    thumbnail_path: Path | None  # Local thumbnail image or None
    provenance_marker: str    # '[ref:{source_id}:{delivery_id}]'
```

#### `UploadOutcome`
Terminal result of a video upload attempt.
```python
@dataclass(frozen=True)
class UploadOutcome:
    destination_video_id: str # Allocated platform video ID
    destination_url: str      # Public watch URL
    privacy: str              # Platform privacy state confirmed
    units_used: int           # Platform quota units consumed
    http_status: int          # HTTP status returned by API
    raw_error_code: str | None  # Set only on failure
    thumbnail_uploaded: bool  # False if video succeeded but thumbnail failed
```

---

## 5. Serialization and Type Coercion Standards

DTOs crossing process boundaries (e.g., job arguments placed in PostgreSQL JSONB
columns or worker IPC) must be serialized deterministically:

| Python Type | JSON / Database Representation | Parsing / Coercion Rule |
|---|---|---|
| `datetime` | ISO 8601 string (`YYYY-MM-DDTHH:MM:SSZ`) | Always UTC (`datetime.timezone.utc`). Parse via `datetime.fromisoformat()`. |
| `Path` | String (`str(path)`) | Always absolute path. Reconstructed via `pathlib.Path(s)`. |
| `tuple[T, ...]` | JSON Array (`[...]`) | Coerced to `tuple(raw_list)` on deserialization. |
| `int`, `float`, `bool` | Native JSON number / boolean | Strict typing; no string boolean coercion (`"true"` rejected). |
| `None` | JSON `null` | Strict optionality (`T | None`). |

---

## 6. Tenancy and Multi-Workspace Isolation

Per Constitution Article 3, inter-pillar DTOs are **intentionally tenant-neutral**:
- Port contracts do not accept or return `workspace_id`.
- The caller (e.g. `jobs`, `pipelines`, `sources`) resolves the current workspace
  via `get_current_workspace()` **prior** to calling an adapter.
- The adapter operates purely as a stateless computation or gateway engine.
- This prevents platform adapters from becoming entangled with multi-tenant storage
  mechanisms or tenant switching semantics.

---

## 7. Open Questions

Open questions: none. All DTO structures derive directly from `docs/03`, `docs/05`,
and `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`.

---

## 8. Change Log

- **2026-09-28:** Initial authorship of `05_DATA_MODEL.md` establishing DTO vs ORM
  boundaries, full contract dataclass definitions, and serialization rules.

