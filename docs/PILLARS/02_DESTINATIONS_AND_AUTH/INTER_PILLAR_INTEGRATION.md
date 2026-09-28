# Inter-Pillar Integration Ledger: Pillar 2 (Destinations & Auth)

**Pillar:** 2 — Destinations & Auth  
**Status:** `active`  
**Last Synchronized:** 2026-09-28  
**Governed by:** `docs/PILLARS/_STANDARD/INTER_PILLAR_INTEGRATION_STANDARD.md`  

---

## 1. Direct Neighbor Topology

| Sibling Pillar | Interaction Nature | Inbound (What We Receive) | Outbound (What We Provide) |
|---|---|---|---|
| **Pillar 0** (`00_INTER_PILLAR_CONTRACTS`) | Port Contract Conformance | `DestinationPlatform` protocol, `DestinationUploadInput`, `DestinationUploadResult` | Concrete YouTube adapter implementation |
| **Pillar 3** (`03_PIPELINES_AND_ROUTING`) | Destination Routing | Channel pairing in pipelines (`pipeline_destination`) | List of active authorized channels, channel health |
| **Pillar 5** (`05_MEDIA_AND_STORAGE`) | Media Asset Handover | Rendered media file path & thumbnail byte stream | Upload execution (no media modification) |
| **Pillar 6** (`06_DELIVERY_AND_LEDGER`) | Upload Execution & Quota Check | Pre-upload quota authorization request; upload invocation | Execution receipt (`DestinationUploadResult`); quota decrement |
| **Pillar 7** (`07_PLATFORM_FOUNDATION_AND_OPS`) | Secret Cryptography | AES-256-GCM platform key cipher helper | Encrypted ciphertext storage (`client_secret`, `refresh_token`) |

---

## 2. Inbound Integrations (What Sibling Pillars Expect From Us)

### Sibling: Pillar 6 (Delivery & Ledger)
- **Contract Boundary**:
  - `destinations.api.can_upload(channel_id) -> QuotaCheckResult`
  - `destinations.api.upload_video(channel_id, upload_input) -> DestinationUploadResult`
- **Data Exchanged**: Channel ID, `DestinationUploadInput` DTO; returns `DestinationUploadResult`.
- **Guarantees We Provide**:
  - `INV-2`: Pacific Time quota budget strictly enforced. If budget < 1600 units, `can_upload` returns `False`.
  - Automatic proactive token refresh: if access token has < 5 minutes remaining, refreshed before upload begins.
  - Resumable chunked upload with automatic byte-offset retry upon network drop.
- **Pending Adjustments From Upstream Changes**:
  - None currently pending.

### Sibling: Pillar 3 (Pipelines & Routing)
- **Contract Boundary**: `destinations.api.list_authorized_channels(workspace_id) -> tuple[DestinationChannelDTO, ...]`
- **Data Exchanged**: Workspace ID; returns active destination channels and token status (`HEALTHY`, `EXPIRING`, `EXPIRED`, `REVOKED`).
- **Guarantees We Provide**:
  - Exposes token health so pipelines never queue work for dead or revoked channels.
- **Pending Adjustments From Upstream Changes**:
  - None currently pending.

---

## 3. Outbound Integrations (What We Expect From Sibling Pillars)

### Sibling: Pillar 6 (Delivery & Ledger)
- **Contract Boundary**: Ledger append.
- **Guarantees We Expect**:
  - `INV-4`: Pillar 6 must record the delivery receipt in its own append-only ledger. Pillar 2 does NOT write to the delivery ledger.
- **Pending Adjustments Required in Pillar 6 (Downstream Blast Radius)**:
  - None. Aligned with `06_DELIVERY_AND_LEDGER/INTER_PILLAR_INTEGRATION.md`.

### Sibling: Pillar 7 (Platform Foundation & Ops)
- **Contract Boundary**: `core.crypto.encrypt(plaintext: str) -> str`, `core.crypto.decrypt(ciphertext: str) -> str`
- **Guarantees We Expect**:
  - `INV-1`: AES-256-GCM authenticated encryption using platform master key from environment.
- **Pending Adjustments Required in Pillar 7 (Downstream Blast Radius)**:
  - `[ADJ-P2-01]` `[2026-09-28]` `[STATUS: RESOLVED_IN_SPEC]` **Platform Encryption Helper**: Pillar 7 must expose `core.crypto` authenticated encryption helpers for OAuth client secrets and refresh tokens. *Adopted into Pillar 7.*

---

## 4. Cross-Pillar Change Log & Blast Radius Audit Trail

- **2026-09-28**: [Pillar 2 ➔ Pillar 7] Logged requirement `ADJ-P2-01` (AES-256-GCM authenticated crypto helper for token encryption). Status: `RESOLVED_IN_SPEC`.
