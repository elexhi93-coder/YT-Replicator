# 01 — Frontend Specification: Platform Shell & Operations

**Pillar:** 7 · Platform Foundation & Operations · **Chapter:** Frontend Specification · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §3  
**Depends on:** `docs/PILLARS/07_PLATFORM_FOUNDATION_AND_OPS/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-1, INV-2, INV-11  

---

## 1. Executive Summary & Screen Inventory

Pillar 7 owns the universal application shell (`base.html`), authentication flows, and the
four core platform screens:
1. **Screen 1: Operations Home (`/`)** — High-level executive cockpit summarizing system health across all pillars.
2. **Screen 2: Operator Login (`/login`)** — Authenticated session login with CSRF protection and brute-force backoff.
3. **Screen 3: System Settings (`/settings`)** — Master configurations, storage roots, API quota caps, and maintenance controls.
4. **Screen 4: Diagnostic Logs (`/ops/logs`)** — Real-time streaming log tail direct from host log files (never Docker socket, `D-05`).

---

## 2. Universal Application Shell Architecture (`base.html`)

### 2.1 The Four Master Layout Blocks
Every UI page across YT-Replicator inherits from `base.html` containing exactly four structural blocks:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ BLOCK 1: HEADER & NAVIGATION                                                │
│ [ Logo: YT-Replicator ] [ Workspace: Default ▼ ]   [ Worker: Active 🟢 ]    │
│ Nav: [ Home | Sources | Catalog | Pipelines | Destinations | Queue | Ops ]  │
├─────────────────────────────────────────────────────────────────────────────┤
│ BLOCK 2: SYSTEM ALERT & FLASH BANNER (Global Pause, Quota Full, Expired Auth)│
├─────────────────────────────────────────────────────────────────────────────┤
│ BLOCK 3: MAIN VIEWPORT CONTENT (Pillar-specific screens render here)        │
│                                                                             │
│                                                                             │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ BLOCK 4: FOOTER & TELEMETRY (Version, PostgreSQL Status, Pacific Time Clock)│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Platform Screens Specification

### 3.1 Screen 1: Operations Home (`/`)
- **Purpose**: At-a-glance health overview answering: *"Is replication running smoothly right now?"*
- **KPI Summary Cards**:
  - **Catalog Health**: Discovered videos count, active sources count, last crawl timestamp.
  - **Replication Progress**: Deliveries completed today, active in-flight uploads, queued jobs.
  - **Quota Status**: Consumed vs. remaining YouTube Data API units for current Pacific day (`INV-2`).
  - **Storage Utilization**: Free disk bytes on primary mount vs. 10 GB floor.
  - **Worker Status**: Active workers count, last heartbeat timestamp, scheduler pause toggle.

### 3.2 Screen 2: Diagnostic Log Viewer (`/ops/logs`)
- **Security Rule (`D-05`)**: Logs are streamed from dedicated rotating file appenders on disk (`logs/app.log`, `logs/worker.log`); **NEVER by mounting or querying `/var/run/docker.sock`**.
- **Controls**: Log level filter (`DEBUG`, `INFO`, `WARNING`, `ERROR`), component filter (`sources`, `worker`, `delivery`), auto-scroll toggle, pause stream button.
- **Redaction**: Passwords, OAuth tokens, and authorization codes are stripped before rendering.

---

## 4. Verification Checklist (Frontend DoD)

- [ ] Universal shell enforces authenticated session and CSRF token on every POST (`D16`).
- [ ] Navigation is purely data-driven using named reverse routes (`D17`).
- [ ] Log viewer reads exclusively from disk files without container socket access (`D-05`).
- [ ] Footer displays authoritative Pacific Time clock alongside UTC.
