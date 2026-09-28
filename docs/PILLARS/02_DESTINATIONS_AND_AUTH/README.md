# Pillar 2 — Destinations & Authorizations

**Status:** `scaffolded`.
**Chapters:** twelve files, per `_STANDARD/CHAPTER_STANDARD.md`.
**Depends on:** Pillar 0 (contracts).

---

## 1. Mission

Hold the authorised accounts we are permitted to upload to, keep their
credentials safe, and answer one question precisely: *may we upload right now,
and how many uploads are left today?*

## 2. Owns

- The `google_client` entity: a Google Cloud OAuth client with an **encrypted**
  secret at rest, and its own daily cap.
- The `authorized_channel` entity: one destination channel, bound explicitly to
  one client, with token health state.
- The OAuth connect / reconnect flow, and automatic token refresh before expiry.
- Quota accounting per `quota_date` in the Pacific day (`quota_usage`).
- Per-destination upload defaults (privacy override, compliance fields).
- Token health surfaced as a state, so a revoked token is visible before it
  fails an upload.
- **The `youtube` module — the v1 platform adapter** behind Pillar 0's Destination
  port: destination inventory sync (`channels.list` → uploads playlist →
  `playlistItems.list` → `videos.list`), resumable upload in 1 MB chunks,
  thumbnail set with WebP→JPEG conversion, and **writing the provenance marker**
  whose format Pillar 0 defines. Pillar 6 consumes it through the port, never
  through its internals.

## 3. Does not own

| Not owned here | Owner |
|---|---|
| Deciding *whether* to upload, and recording what happened | Pillar 6 (`06_DELIVERY_AND_LEDGER`) — this pillar's adapter performs the call it is asked to make |
| Reading the *source* channel | Pillar 1 (`01_SOURCES_AND_CATALOG`) |
| Which destination a video goes to | Pillar 3 (`03_PIPELINES_AND_ROUTING`) |
| Media files | Pillar 5 (`05_MEDIA_AND_STORAGE`) |
| Cipher implementation | `core` (Pillar 7 owns the module; Pillar 0 owns the interface) |
| The marker *format* | Pillar 0 (written here, parsed by Pillar 6) |

## 4. Dependencies

Reads from: Pillar 0. Written to by: Pillar 3 (which destinations exist), Pillar 6
(quota consumption as uploads happen). **Pillar 6 asks this pillar for permission
and hands it the work; the ledger stays in Pillar 6.** That separation is what
keeps the quota rule in exactly one place and the truth in exactly one place.

**Why the adapter lives here** (decision Q-2): everything platform-specific about
YouTube already lives in this pillar — the client, the tokens, the quota day, the
scopes. Splitting the adapter across two pillars would give one module two owners.
Adding Facebook or Dailymotion later is therefore:

1. a new adapter in *this* pillar behind the same Destination port, and
2. nothing at all in Pillars 4, 5 or 6.

## 5. Invariants this pillar protects

The credential rule of the Constitution (encrypted at rest, key outside the
database), and the quota half of "quota is never exceeded" from `docs/05` §3.
It is the fix for defects `D-11` (plaintext tokens), `D-22` (token exports) and
`D-12` (secrets in the tree).

## 6. Chapter plan

| Chapter | Status |
|---|---|
| `00_PILLAR_OVERVIEW.md` | **locked** — mission, boundaries, OAuth/Upload Field Universe, quota costs |
| `01_FRONTEND_SPEC.md` | **locked** — screen layouts, controls, quota meter, auth modals |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | scaffolded |
| `03_INTERFACE_CONTRACT.md` | **locked** — published `<destinations>.api` and `DestinationPlatform` adapter |
| `04_LOGIC_AND_RULES.md` | **locked** — Pacific quota math, token refresh loop, resumable chunking |
| `05_DATA_MODEL.md` | **locked** — PostgreSQL schema (`google_client`, `authorized_channel`, `quota_usage`) |
| `06_FAILURES_AND_ERRORS.md` | **locked** — error taxonomy, quota exhaustion delay, recovery loop |
| `07_OBSERVABILITY_AND_AUDIT.md` | **locked** — Prometheus metrics, domain events, redaction rules |
| `08_TESTS_AND_DOD.md` | **locked** — AST boundary tests (`INV-4`), quota rollover tests (`INV-2`), DoD |
| `09_LEGACY_TRACEABILITY.md` | scaffolded — anchors: `F-07`, `F-26`, `F-27`, `F-33`, `F-41`; defects `D-03`, `D-11`, `D-12`, `D-22` |
| `10_OPEN_QUESTIONS.md` | scaffolded — includes the parked quota-rotation idea |
| `11_DECISIONS.md` | scaffolded |

## 7. Next action

Not yet — wait for Pillar 0 to be locked.

> **Parked, deliberately:** the legacy's multi-project quota rotation
> (`dashboard/projects.py`) is recorded in `10_OPEN_QUESTIONS.md` and in the Idea
> Vault as `IDEA-05` territory. v1 uses one client bound to one channel.
