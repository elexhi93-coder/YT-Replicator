# 00 — Pillar Overview & The YouTube Destination Universe

**Pillar:** 2 · Destinations & Auth · **Chapter:** Pillar Overview & Destination Universe · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md` · `docs/00` §2 · `docs/02` §4 · `docs/03` §2  
**Invariants touched:** INV-1, INV-2, INV-4, INV-11, INV-12  

---

## 1. Mission

Pillar 2 securely manages authorized YouTube destination channels, Google Cloud OAuth
credentials, token lifecycles, and Pacific Time quota budgets. It implements the concrete
`DestinationPlatform` adapter for video uploads, answering with absolute precision:
*"May we upload right now, and how many uploads remain today?"*

It guarantees that client secrets and refresh tokens are encrypted at rest (`INV-1`),
upload limits are never breached (`INV-2`), and uploads are executed reliably through
resumable chunked transfers — while delegating all delivery tracking to Pillar 6 (`INV-4`).

---

## 2. Owns vs. Does Not Own

### 2.1 What This Pillar Owns
- **The `google_client` entity**: Registration, validation, and encrypted storage of
  Google Cloud OAuth 2.0 Client credentials (Client ID, Client Secret).
- **The `authorized_channel` entity**: YouTube destination channels authorized by operators,
  tracking OAuth refresh tokens, access tokens, and token health states (`VALID`, `EXPIRING`, `EXPIRED`, `REVOKED`).
- **OAuth 2.0 Web Authorization Flow**: Handling authorization URLs, PKCE verification,
  redirect callbacks, and code-for-token exchange.
- **Proactive Token Refresh Loop**: Background verification and automatic token refreshing
  before expiration (within 5 minutes of token expiry).
- **Pacific Day Quota Budgeting (`quota_usage`)**: Tracking daily YouTube Data API v3 units
  resetting strictly at midnight Pacific Time (00:00:00 PT).
- **The `youtube` Destination Adapter**: Implementing Pillar 0's `DestinationPlatform` port:
  resumable chunked upload protocol, thumbnail format conversion (WebP ➔ JPEG), and
  provenance marker injection.

### 2.2 What This Pillar Does NOT Own

| Responsibility | Owning Pillar | Reason for Boundary |
|---|---|---|
| Recording completed uploads & receipts | **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | **INV-4**: The delivery ledger is owned exclusively by Pillar 6. Pillar 2 returns the result DTO. |
| Deciding which video replicates to which channel | **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Destination pairing is a pipeline routing policy. |
| Downloading source media files | **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Source media downloading and rendering belongs to media storage. |
| Scheduling background upload worker tasks | **Pillar 4** (`04_JOB_ENGINE`) | Worker claiming, queue dispatch, and retry orchestration. |
| Discovered catalog inventory | **Pillar 1** (`01_SOURCES_AND_CATALOG`) | Source media inventory belongs to the source catalog. |

---

## 3. Dependencies & Invariants

### 3.1 Dependency Topology
- **Inbound Calls**: Called by **Pillar 6** (`delivery` checks quota before scheduling uploads, and invokes the `DestinationPlatform` adapter) and **Pillar 3** (pipelines inspect available channels).
- **Outbound Calls**: Implements **Pillar 0** (`DestinationPlatform` port). Calls **Pillar 7** (`core.crypto` for encryption/decryption). Never touches database tables of other pillars.

### 3.2 Invariants Enforced
- **INV-1 (Encrypted Secrets at Rest)**: `client_secret` and `refresh_token` are encrypted
  using AES-256-GCM before writing to PostgreSQL. Plaintext secrets never appear in logs or unauthenticated APIs.
- **INV-2 (Pacific Day Quota Rollover)**: Quota resets at 00:00:00 America/Los_Angeles.
  Upload requests are rejected if `consumed_units + 1600 > daily_limit`.
- **INV-4 (No Ledger Ownership)**: Pillar 2 provides execution receipts; it never writes to `ledger` tables.
- **INV-11 & INV-12 (Port & DTO Isolation)**: All upload operations use `DestinationUploadInput`
  and return `DestinationUploadResult`.

---

## 4. The YouTube Destination Field Universe (Leaf-Level Registry)

Conforming to `docs/000_AI_DEEP_SPEC_STANDARD.md`, this section catalogs all attributes
governing YouTube destination accounts, OAuth credentials, and upload payloads.

### 4.1 OAuth & Client Credentials Universe

| Field Name | Entity / Context | Visibility | Storage Mode | PostgreSQL Column | UI Placement | Notes |
|---|---|---|---|---|---|---|
| `client_id` | `google_client` | Public | Plaintext | `google_client.client_id` | Client Settings Form | Sourced from Google Cloud Console. |
| `client_secret` | `google_client` | Private | **AES-256-GCM** | `google_client.client_secret_encrypted` | Client Settings Form (Masked: `••••••`) | Decrypted in-memory only during OAuth token exchange (`INV-1`). |
| `daily_quota_limit` | `google_client` | System | Plaintext | `google_client.daily_quota_limit` | Quota Gauge | Default: `10000` units per client project. |
| `auth_code` | OAuth Callback | Private | Ephemeral | In-memory only | N/A | Exchanged for tokens via POST to `oauth2.googleapis.com/token`. |
| `refresh_token` | `authorized_channel` | Private | **AES-256-GCM** | `authorized_channel.refresh_token_encrypted` | N/A (Hidden) | Long-lived token; persists until revoked by user (`INV-1`). |
| `access_token` | `authorized_channel` | Private | Ephemeral (Cache/RAM) | In-memory or Redis | N/A | 3600-second lifespan; refreshed automatically at 3300 seconds. |
| `token_expires_at` | `authorized_channel` | System | UTC Timestamp | `authorized_channel.token_expires_at` | Channel Health Pill | Proactive refresh trigger threshold: `NOW() + 300s`. |
| `token_health` | `authorized_channel` | Public | Enum | `authorized_channel.token_health` | Channel Health Pill | `VALID`, `EXPIRING`, `EXPIRED`, `REVOKED`. |

### 4.2 Video Upload & Metadata Payload Universe

| Attribute | API / Port Field | Data Type | Default / Constraints | UI Destination | Notes |
|---|---|---|---|---|---|
| `channel_id` | `channel_id` | `str` (`UC...`) | Matches authorized account | Channel Selector | Destination channel receiving the upload. |
| `title` | `snippet.title` | `str` (max 100 chars) | Required | Upload Modal / Inspector | Truncated to 100 characters if input exceeds YouTube limit. |
| `description` | `snippet.description` | `str` (max 5000 chars) | Optional | Upload Modal / Inspector | Includes the Pillar 0 Provenance Marker appended at the end. |
| `tags` | `snippet.tags` | `tuple[str, ...]` | Max 500 chars total | Inspector Tags | Comma-delimited list of keywords. |
| `category_id` | `snippet.categoryId` | `str` | Default: `'22'` (People & Blogs) | Channel Defaults | Numeric YouTube category ID. |
| `privacy_status` | `status.privacyStatus` | `str` | `'public'`, `'unlisted'`, `'private'` | Channel Defaults / Override | Global default or per-destination override. |
| `made_for_kids` | `status.selfDeclaredMadeForKids` | `bool` | Default: `False` | Compliance Toggle | Required YouTube COPPA compliance flag. |
| `embeddable` | `status.embeddable` | `bool` | Default: `True` | Channel Defaults | Allows embedding on third-party sites. |
| `thumbnail_bytes` | `thumbnails.set` | `bytes \| None` | Max 2 MB, JPEG/PNG | Inspector Thumbnail | Automatic conversion from WebP to JPEG if source was WebP. |
| `provenance_marker` | `snippet.description` | `str` | Format: `<!-- YTR:src={id}:vid={id} -->` | Read-only in UI | Machine-readable provenance tag appended to description. |

---

## 5. Quota Cost Accounting Reference (YouTube Data API v3)

| Operation | Google API Endpoint | Quota Units Consumed | Notes |
|---|---|---|---|
| **Video Insert (Upload)** | `POST /upload/youtube/v3/videos` | **1,600 units** | Resumable chunked upload. The dominant quota consumer. |
| **Thumbnail Upload** | `POST /upload/youtube/v3/thumbnails/set` | **50 units** | Sets custom video thumbnail. |
| **Video Update (Metadata)**| `PUT /youtube/v3/videos` | **50 units** | Updates title/description/tags post-upload. |
| **Channel Info Query** | `GET /youtube/v3/channels?mine=true` | **1 unit** | Used during OAuth setup to identify channel title & avatar. |
| **Video List Verification** | `GET /youtube/v3/videos?id={ids}` | **1 unit per 50 IDs** | Used for pre-upload or post-upload status checks. |

*Note: Default Google Cloud project limit is 10,000 units/day = exactly **6 video uploads per day per client**.*

---

## 6. Change Log

- **2026-09-28:** Authored `00_PILLAR_OVERVIEW.md` establishing mission, boundaries, invariants (`INV-1`, `INV-2`, `INV-4`), OAuth/Upload Field Universe registry, and Quota accounting costs.

| Master AES-256 cipher implementation | **Pillar 7** (`07_PLATFORM_FOUNDATION_AND_OPS`) | Platform crypto primitives live in `core.crypto`. |
