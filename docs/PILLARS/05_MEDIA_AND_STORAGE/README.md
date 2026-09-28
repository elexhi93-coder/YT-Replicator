# Pillar 5 — Media & Storage

**Status:** `scaffolded`.
**Chapters:** twelve files, per `_STANDARD/CHAPTER_STANDARD.md`.
**Depends on:** Pillar 0 (contracts), Pillar 4 (job hand-out).

---

## 1. Mission

Be the **only** owner of bytes on disk: acquire a media file, prove it is valid,
place it safely, hold it under a policy, and remove it exactly once.

## 2. Owns

- The `storage_root` entity: hot and cold roots, mounted state, free-space floor.
- The `media_asset` entity: one physical file we hold or held, with size and
  `sha256`, and its state (`expected → downloading → on_disk → deleted /
  archive_offline`).
- The `media_event` append-only audit of every media action.
- Downloading through the pipeline's `download_profile`.
- Verification: size and hash recorded **before** the asset can be considered
  ready, and an atomic rename so a partial file is never mistaken for a whole one.
- Hygiene: partials, orphans and aborted downloads — always on.
- The **retention evaluator**: all four modes, evaluated in one place, with a
  dry run always available (`INV-10`), plus the hard 7-day backstop (D6).
- Rehydrate: re-downloading media for a video we already know, pinned by default
  (D4). Pin and unpin.
- The free-space admission gate, so downloads stop before the disk is full.
- `archive_offline`, so a detached drive never looks like `deleted` (fixes the
  legacy's silent re-download of everything).

## 3. Does not own

| Not owned here | Owner |
|---|---|
| Why a video was chosen | Pillar 3 (`03_PIPELINES_AND_ROUTING`) |
| The queue and retries | Pillar 4 (`04_JOB_ENGINE`) |
| Uploading the file | Pillar 6 (`06_DELIVERY_AND_LEDGER`) |
| Deciding *whether* to ever delete valid media | the operator, via the policy Pillar 3 stores; this pillar only evaluates it |
| Video transformation of any kind | **nobody** — no FFmpeg in v1 (D15) |

## 4. Dependencies

Reads from: Pillar 0. Called by: Pillar 4's dispatch, and Pillar 6 (which asks
whether the file exists and is valid). **No other pillar may touch the
filesystem** — that rule is the entire fix for defect `D-08` (seven deletion
owners) and `D-09` (four simultaneous storage layouts).

## 5. Invariants this pillar protects

`INV-2` (delete only when every enabled destination is terminal), `INV-3` (never
upload a partial or unverified file), `INV-6` (every retention decision
reproducible from the database alone) and `INV-10` (deletion evaluated in one
place, dry run always available). It also owns the path-safety guard — any
deletion must resolve inside a configured storage root.

## 6. Chapter plan

| Chapter | Status |
|---|---|
| `00_PILLAR_OVERVIEW.md` | **locked** — mission, boundaries, Storage Universe & Asset Lifecycle |
| `01_FRONTEND_SPEC.md` | **locked** — storage health console, disk space gauges, retention dry-run UI |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | scaffolded |
| `03_INTERFACE_CONTRACT.md` | **locked** — published `<media>.api`, MediaAssetDTO, RetentionDryRunDTO |
| `04_LOGIC_AND_RULES.md` | **locked** — yt-dlp acquisition, atomic verification, 4 retention modes, safe path checks |
| `05_DATA_MODEL.md` | **locked** — PostgreSQL schema (`storage_root`, `media_asset`, `media_event`) |
| `06_FAILURES_AND_ERRORS.md` | **locked** — disk floor, corrupt hash, unmounted drive, orphan sweeping |
| `07_OBSERVABILITY_AND_AUDIT.md` | **locked** — storage capacity gauges, deletion audit logs, I/O latency |
| `08_TESTS_AND_DOD.md` | **locked** — deletion safety tests, dry-run assertions, path-traversal tests |
| `09_LEGACY_TRACEABILITY.md` | scaffolded — anchors: `F-14`, `F-20`, `F-34`, `F-35` (rejected), `F-38`/`F-39`/`F-55` (rejected), `F-52`, `F-53`; defects `D-08`, `D-09`, `D-10` |
| `10_OPEN_QUESTIONS.md` | scaffolded |
| `11_DECISIONS.md` | scaffolded |

## 7. Next action

Not yet — wait for Pillar 0 to be locked. This is the largest pillar and will be
split across more than one session when its turn comes.
