# 01 — Frontend Specification: Destinations & Auth

**Pillar:** 2 · Destinations & Auth · **Chapter:** Frontend Specification · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §3  
**Depends on:** `docs/PILLARS/02_DESTINATIONS_AND_AUTH/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-11  

---

## 1. Executive Summary & Screen Inventory

Pillar 2 provides the operator interface for managing target YouTube channels, configuring
Google Cloud OAuth 2.0 clients, observing live quota burn across the Pacific day, and
monitoring token health. In strict compliance with **INV-1**, secrets are never revealed
in plain text or serialized to client-side bundles.

### Screen & Component List
1. **Screen 1: Destinations Management (`/destinations`)**
   - Header & Summary KPI Strip (Active Channels, Healthy Tokens, Total Uploads Today, Quota Remaining).
   - Authorized Channel Cards / Table (Channel avatar, title, client binding, token health badge, daily quota meter).
   - Action Modal: **Connect YouTube Channel Modal** (select client project, OAuth redirect trigger).
   - Action Modal: **Edit Channel Defaults Drawer** (privacy status, COPPA `madeForKids` flag, category ID).
2. **Screen 2: Google OAuth Clients (`/settings/google-clients`)**
   - OAuth Project List Table (Client ID, Project Name, Configured Channels, Quota Cap).
   - Action Modal: **Add / Edit Google Client Modal** (Client ID, Client Secret input with masking, daily quota limit).
   - Quota Burn Analytics Panel (Hourly burn, rollover countdown to 00:00 PT).

---

## 2. Screen 1: Destinations Management (`/destinations`)

### 2.1 Route & Purpose
- **Route**: `/destinations`
- **Entry Points**: Primary navigation bar item "Destinations".
- **Primary Goal**: View authorized YouTube target channels, check token freshness,
  observe remaining daily video upload capacity, and trigger re-authorization if expired.

### 2.2 Layout Block Diagram
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: Destination Channels                     [ + Connect New Channel ]  │
├─────────────────────────────────────────────────────────────────────────────┤
│ KPI Strip: [ 4 Channels ] [ 4 Tokens Healthy ] [ 18 Uploads Today ] [ 52% ] │
├─────────────────────────────────────────────────────────────────────────────┤
│ Search & Status Filter: [ Filter by channel name... ] [ Status: All ▼ ]     │
├─────────────────────────────────────────────────────────────────────────────┤
│ Destination Channel Grid / Cards                                            │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ [Avatar] Tech Insights Daily                       [ HEALTHY ]          │ │
│ │ Channel ID: UC987654321ZYX | Project: Production App 01                  │ │
│ │ ─────────────────────────────────────────────────────────────────────── │ │
│ │ Quota Remaining: 5,200 / 10,000 units (3 uploads left today)           │ │
│ │ [██████████████████░░░░░░░░░░░░░░░░] 48% Consumed                       │ │
│ │ Defaults: Privacy: Public | COPPA: Not for Kids | Cat: 28 (Tech)        │ │
│ │ ─────────────────────────────────────────────────────────────────────── │ │
│ │ Actions: [ Edit Defaults ] [ Test Connection ] [ Reconnect OAuth ]      │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Channel Card Data Lineage & Elements

| UI Element | Field Lineage (00 §4) | Type / Format | Notes & State Transitions |
|---|---|---|---|
| **Avatar & Title** | `authorized_channel.title`, `avatar_url` | 48x48 rounded image + text | Display title and thumbnail fetched via `channels.list?mine=true`. |
| **Channel ID** | `authorized_channel.canonical_id` | Monospace `UC...` | Click to copy canonical YouTube channel ID. |
| **OAuth Client Binding** | `google_client.project_name` | Text badge | Shows which GCP OAuth client owns the token quota. |
| **Token Health Badge** | `authorized_channel.token_health` | Status Pill | Green: `VALID`, Amber: `EXPIRING` (< 24h), Red: `EXPIRED`, Dark Red: `REVOKED`. |
| **Quota Meter Bar** | `quota_usage.consumed_units` vs `google_client.daily_quota_limit` | Progress bar + units | Green (< 70%), Amber (70-90%), Red (> 90%). Shows exact "X uploads remaining". |
| **Rollover Countdown** | System PT Clock | Muted text | "Resets in 7h 14m (00:00 PT)" (`INV-2`). |
| **Default Settings** | `authorized_channel.default_privacy`, `made_for_kids` | Key-value tags | Highlights target channel compliance defaults. |


---

## 3. Interactive Modals & Control Behaviors

### 3.1 "Connect YouTube Channel" Modal
- **Trigger**: Click `[+ Connect New Channel]` in `/destinations` header.
- **Workflow**:
  1. **Step 1 (Select Client)**: Dropdown selecting configured `google_client` project. If none exist, shows banner prompting operator to add a Google Client first.
  2. **Step 2 (Scope Consent)**: Clear notice displaying required YouTube scopes:
     - `https://www.googleapis.com/auth/youtube.upload` (Upload videos and thumbnails)
     - `https://www.googleapis.com/auth/youtube.readonly` (Read channel ID and title)
  3. **Step 3 (Initiate Flow)**: Button `[Authorize via Google ↗]`.
     - Opens Google OAuth consent screen in a secure popup or redirect with PKCE `state` parameter.
  4. **Step 4 (Callback & Channel Selection)**: Upon successful Google approval:
     - Callback exchanges authorization code for refresh token.
     - Fetches authorized channel info. If multiple brand channels exist on the Google account, presents a selector.
     - Encrypts refresh token via `core.crypto` (`INV-1`) and persists `authorized_channel`.

### 3.2 "Add / Edit Google Client" Modal (`/settings/google-clients`)
- **Fields**:
  - `Project Name`: Human-friendly label (e.g. "Primary Prod YouTube Client").
  - `Client ID`: Text input (`*.apps.googleusercontent.com`).
  - `Client Secret`: Password input with eye-toggle.
    - **Defensive Rule (`INV-1`)**: On edit, secret is never pre-filled in plaintext; renders placeholder `••••••••••••`. Only overwritten if user types a new value.
  - `Daily Quota Limit`: Numeric input, default `10000`.

---

## 4. UI States & Edge Cases

### 4.1 Quota Exhaustion Presentation (`INV-2`)
When remaining quota drops below **1,600 units** (cost of 1 video upload):
- Channel card status pill changes to **`QUOTA_EXHAUSTED`** (solid red).
- Primary actions on linked pipelines are disabled with tooltip: *"Daily YouTube quota reached (10,000/10,000 units). Next upload available at 00:00 Pacific Time."*
- Quota progress bar fills to 100% with countdown clock displaying exact hours/minutes until rollover.

### 4.2 Revoked / Invalid Token Presentation
If Google returns `invalid_grant` or token revocation:
- Channel status badge transitions to **`REVOKED`** (flashing amber/red pill).
- Card displays high-visibility alert: *"Google authorization was revoked or expired. Re-authenticate to resume replication."*
- Action button morphs into high-priority `[Reconnect Channel]`.

---

## 5. Verification Checklist (Frontend DoD)

- [ ] All 10 destination universe attributes from `00_PILLAR_OVERVIEW.md` §4 are accounted for.
- [ ] No client secret or refresh token is rendered in plain text (`INV-1`).
- [ ] Quota meter explicitly maps 1,600 units per video insert and displays countdown to 00:00 PT (`INV-2`).
- [ ] Empty states, connecting states, expired token states, and quota-capped states are fully designed.
