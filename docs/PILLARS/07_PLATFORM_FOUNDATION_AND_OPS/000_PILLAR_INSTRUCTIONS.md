# 000 — Pillar 7 Instructions & Working Frontier (Platform Foundation & Ops)

**Pillar:** 7 — Platform Foundation & Operations  
**Status:** `drafting`  
**Authority:** Local domain directive for Pillar 7. Governed by `docs/000_*` and `docs/PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md`.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
Own the foundational platform upon which all domain pillars stand: the cryptographic primitives (`core.crypto`, `ADJ-P2-01`), the Pacific Time quota clock (`core.clock`), the authenticated workspace tenancy model (`accounts`), the generic worker dispatch loop (`worker`), the audit ledger and log viewer (`ops`), and the universal UI application shell (`ui`).

### What This Pillar Owns
- The `core` module: Base typed errors, structured JSON logging, SSRF IP firewall, Pacific Time clock (`America/Los_Angeles`), and AES-256-GCM cipher (`ADJ-P2-01`).
- The `accounts` module: `workspace`, `workspace_member`, Django session auth, login/logout, CSRF protection, and the unified access helper (`current_workspace()`).
- The `worker` module: Pure execution runner (`run_once()` / `run_forever()`), dispatching claimed tasks by intent, evaluating admission gates (quota, disk floor, operator pause), and initiating restart recovery.
- The `ops` module: Centralized `audit_event` append-only audit trail, worker heartbeat registry, `/healthz` liveness probes, log file streaming (never Docker socket, `D-05`), and maintenance commands.
- The `ui` shell: Universal HTML layout (`base.html`), data-driven navigation bar, workspace switcher slot, flash/toast messages, and the 4 platform pages:
  1. `/` (Executive Operations Home).
  2. `/login` (Authenticated Session Entry).
  3. `/settings` (System & Security Configuration).
  4. `/ops/logs` (Streaming Diagnostic Logs).
- Architectural linting & boundary enforcement tests (600-line module cap, zero circular imports, port contract validation).

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- ❌ **NEVER contains YouTube-specific API logic**: Belongs to Pillars 1 & 2.
- ❌ **NEVER executes or evaluates media files**: Belongs to Pillar 5 (`05_MEDIA_AND_STORAGE`).
- ❌ **NEVER makes candidate routing decisions**: Belongs to Pillar 3 (`03_PIPELINES_AND_ROUTING`).
- ❌ **NEVER owns queue row states or database locks**: Belongs to Pillar 4 (`04_JOB_ENGINE`).
- ❌ **NEVER owns the delivery ledger**: Belongs to Pillar 6 (`06_DELIVERY_AND_LEDGER`).

---

## 2. Invariants & Non-Negotiable Guards

| Invariant | Rule | Enforcement Mechanism |
|---|---|---|
| **INV-1** | **Cryptographic token encryption** | Exposes AES-256-GCM cipher helper in `core.crypto` using platform master key (`ADJ-P2-01`). |
| **INV-2** | **Pacific Day quota clock** | Single canonical clock `core.clock.get_pacific_date()` evaluated across system. |
| **INV-7** | **Zero path traversal / SSRF** | `core.security.resolve_safe_path` and `core.security.is_safe_ssrf_url` guard all external I/O. |
| **INV-10** | **PostgreSQL concurrency only** | Strictly forbids SQLite or shared in-memory concurrency in production (`D-19`). |
| **INV-11** | **Strict module boundary linting** | AST import linter tests ensure zero illegal sibling dependencies and enforce the 600-line cap per file. |

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `00` | `00_PILLAR_OVERVIEW.md` | `locked` | Mission, 5 unowned modules, Platform Universe |
| `01` | `01_FRONTEND_SPEC.md` | `locked` | Universal shell (base.html), Home cockpit, Login, Settings, Ops logs |
| `02` | `02_WORKSPACE_AND_TENANCY_SLOT.md` | `scaffolded` | Tenancy model, scoped constraints, access helpers |
| `03` | `03_INTERFACE_CONTRACT.md` | `locked` | Published `<core>.crypto`, `<core>.clock`, `<core>.security`, `<ops>.api` |
| `04` | `04_LOGIC_AND_RULES.md` | `locked` | AES-256-GCM cipher (ADJ-P2-01), worker run loop, Pacific clock rollover |
| `05` | `05_DATA_MODEL.md` | `locked` | PostgreSQL schema (`workspace`, `workspace_member`, `audit_event`, `app_setting`) |
| `06` | `06_FAILURES_AND_ERRORS.md` | `locked` | Auth failures, dead workers, disk floors, cipher errors |
| `07` | `07_OBSERVABILITY_AND_AUDIT.md` | `locked` | Centralized audit trail, logging, Prometheus metrics, /healthz |
| `08` | `08_TESTS_AND_DOD.md` | `locked` | Boundary linter tests (U04), 600-line limit tests, crypto tests |
| `09` | `09_LEGACY_TRACEABILITY.md` | `scaffolded` | Anchors: F-29, F-30, F-54; defects D-05, D-12, D-16, D-19, D-25, D-26 |
| `10` | `10_OPEN_QUESTIONS.md` | `scaffolded` | Local design questions |
| `11` | `11_DECISIONS.md` | `scaffolded` | Local architectural decisions (P7-D##) |

**Current Active Frontier:** Authoring chapters `00` through `08`.
