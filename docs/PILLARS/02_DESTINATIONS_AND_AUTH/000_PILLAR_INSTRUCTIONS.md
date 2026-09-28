# 000 — Pillar 2 Instructions & Working Frontier (Destinations & Auth)

**Pillar:** 2 — Destinations & Auth  
**Status:** `drafting`  
**Authority:** Local domain directive for Pillar 2. Governed by `docs/000_*` and `docs/PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md`.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
Securely manage authorized destination platforms, Google Cloud OAuth clients, refresh token lifecycles, and daily upload quota accounting — and provide the concrete `DestinationPlatform` adapter for YouTube uploads without ever managing delivery history or ledger records.

### What This Pillar Owns
- Google Cloud OAuth Client entities (`google_client`) with encrypted secrets at rest.
- Authorized channel destinations (`authorized_channel`) and token health states (`VALID`, `EXPIRING`, `EXPIRED`, `REVOKED`).
- Secure OAuth 2.0 PKCE / Web redirect flow and automatic proactive token refresh.
- Accurate Pacific Time (PT) quota accounting (`quota_usage` table) enforcing daily ceilings (10,000 units default, 1,600 units per video insert).
- Provenance marker injection in uploaded video descriptions (per Pillar 0 format).
- Resumable upload chunking (1 MB minimum chunks) and thumbnail setting (WebP to JPEG conversion).
- Quota budget gating: answering *"May we upload right now, and how many uploads remain today?"*

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- ❌ **NEVER writes delivery ledger records**: That is owned exclusively by Pillar 6 (`06_DELIVERY_AND_LEDGER`). Pillar 2 executes the upload and returns the result DTO (`INV-4`).
- ❌ **NEVER downloads or modifies source media files**: Pillar 5 (`05_MEDIA_AND_STORAGE`) owns media storage and rendering.
- ❌ **NEVER routes videos or pairs sources with destinations**: Pillar 3 (`03_PIPELINES_AND_ROUTING`) decides routing.
- ❌ **NEVER reads source catalogs**: Pillar 1 (`01_SOURCES_AND_CATALOG`) owns external discovery.

---

## 2. Invariants & Non-Negotiable Guards

| Invariant | Rule | Enforcement Mechanism |
|---|---|---|
| **INV-1** | **Client secrets and refresh tokens encrypted at rest** | AES-256-GCM encryption envelope using platform key; never logged or serialized in plain text. |
| **INV-2** | **Strict Pacific Time quota rollover** | Quota resets at 00:00:00 PT (UTC-8 / UTC-7 DST). Upload rejected if `current_usage + 1600 > daily_limit`. |
| **INV-4** | **No ledger ownership** | Pillar 2 adapter performs uploads and returns `DestinationUploadResult`; never inserts into `ledger`. |
| **INV-11** | **Port & Adapter encapsulation** | External modules interact with destination accounts via `<destinations>.api` or through the `DestinationPlatform` port. |

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `00` | `00_PILLAR_OVERVIEW.md` | `locked` | Mission, boundaries, OAuth/Upload Field Universe, quota costs |
| `01` | `01_FRONTEND_SPEC.md` | `locked` | Screen layouts, controls, quota meter, auth modals |
| `02` | `02_WORKSPACE_AND_TENANCY_SLOT.md` | `scaffolded` | `workspace_id` scoping for clients and channels |
| `03` | `03_INTERFACE_CONTRACT.md` | `locked` | Published `<destinations>.api` and `DestinationPlatform` adapter |
| `04` | `04_LOGIC_AND_RULES.md` | `locked` | Pacific quota math, token refresh loop, resumable chunking |
| `05` | `05_DATA_MODEL.md` | `locked` | PostgreSQL schema (`google_client`, `authorized_channel`, `quota_usage`) |
| `06` | `06_FAILURES_AND_ERRORS.md` | `locked` | Error taxonomy, quota exhaustion delay, recovery loop |
| `07` | `07_OBSERVABILITY_AND_AUDIT.md` | `locked` | Prometheus metrics, domain events, redaction rules |
| `08` | `08_TESTS_AND_DOD.md` | `locked` | AST boundary tests (`INV-4`), quota rollover tests (`INV-2`), DoD |
| `09` | `09_LEGACY_TRACEABILITY.md` | `scaffolded` | Traceability for F-01, F-03, F-04, F-06, F-09; D-01, D-04, D-08 |
| `10` | `10_OPEN_QUESTIONS.md` | `scaffolded` | Local design questions |
| `11` | `11_DECISIONS.md` | `scaffolded` | Local architectural decisions (P2-D##) |

**Current Active Frontier:** Authoring `00_PILLAR_OVERVIEW.md` with the deep Leaf-Level YouTube Destination & OAuth Field Universe.

---

## 4. Leaf-Level Domain Universe (YouTube Destination Attributes)

To eliminate runtime ambiguity, this pillar catalogs all attributes involved in YouTube OAuth and upload operations:
1. **OAuth 2.0 Credentials**: Client ID, Client Secret (AES encrypted), Scopes (`youtube.upload`, `youtube.readonly`), Auth Code, Refresh Token (AES encrypted), Access Token, Token Expiry.
2. **Channel Identity & Compliance**: Destination Channel ID (`UC...`), Title, Avatar, `madeForKids` flag, `privacyStatus` (`public`, `unlisted`, `private`), License (`youtube`, `creativeCommon`), Embeddable, Category ID.
3. **Quota Accounting**: Pacific Date (`YYYY-MM-DD` PT), Daily Limit (default 10,000 units), Consumed Units, Video Upload Cost (1,600 units), Thumbnail Set Cost (50 units), Channel Sync Cost (1-5 units).
4. **Resumable Upload Stream**: Initial session URI, Chunk byte range (`bytes 0-1048575/total`), HTTP 308 Resume Incomplete, Final HTTP 200 payload.

---

## 5. Local Open Questions & Blockers
- None blocking. Next task: document the complete Leaf-Level Destination Universe in `00_PILLAR_OVERVIEW.md`.
