# Pillar 6 — Delivery & Ledger

**Status:** `scaffolded`.
**Chapters:** twelve files, per `_STANDARD/CHAPTER_STANDARD.md`.
**Depends on:** Pillar 0 (contracts), Pillar 2 (authorisation + quota), Pillar 4
(job hand-out), Pillar 5 (verified media).

---

## 1. Mission

Deliver one verified video to one destination, record what happened **twice** —
what we did, and what the destination shows — and make the two agree.

## 2. Owns

- The `delivery` entity: current state of one (video × destination) pair, with
  both-sided snapshots (`source_video_id` and `destination_video_id`).
- The `delivery_attempt` entity: the append-only history of every attempt, and
  the immutable record of every value the current-state fields have held.
- The `destination_inventory` entity: what the destination currently shows —
  observed, not owned.
- The delivery **decision and outcome**: requesting the upload through Pillar 0's
  Destination port, and translating what the port returns into Pillar 4's typed
  errors. *The API call itself is made by Pillar 2's platform adapter — this
  pillar never calls the platform.*
- The provenance marker (`ref:` code appended to the description, D2) — **parsing
  it back**. The format is a Pillar 0 contract; Pillar 2 writes it.
- **Reconciliation** and its four outcomes (`claimed_ok`, `unclaimed_present`,
  `missing_expected`, `marker_mismatch`), with the memory rule: *after an
  interrupted upload, reconcile before retrying.*
- Mark-as-removed, when the operator confirms a copy is gone.
- The ledger's durability rule: history is never cascaded away (`INV-4`).

## 3. Does not own

| Not owned here | Owner |
|---|---|
| Whether we are allowed to upload now | Pillar 2 (`02_DESTINATIONS_AND_AUTH`) |
| Calling the platform's upload or inventory endpoints | Pillar 2's platform adapter — this pillar consumes it through the port |
| The marker *format* | Pillar 0 (written by Pillar 2, parsed here) |
| The media file's validity | Pillar 5 (`05_MEDIA_AND_STORAGE`) |
| Deciding *what* to upload | Pillar 3 (`03_PIPELINES_AND_ROUTING`) |
| Queue state and retries | Pillar 4 (`04_JOB_ENGINE`) |
| Metadata invention or rewriting | the Metadata Transformer port defined in Pillar 0 (v1 is pass-through) |
| Deleting the local file after success | Pillar 5, on request — never this pillar |

## 4. Dependencies

Reads from: Pillars 0, 2, 4, 5. Writes: the ledger and its attempts, and the
inventory it observes. **The platform is reached only through Pillar 0's
Destination port**, whose v1 adapter is owned by Pillar 2 — so adding a new
platform is an adapter change in Pillar 2 and touches nothing here.

## 5. Invariants this pillar protects

`INV-1` (one current successful delivery per video × destination, enforced by a
scoped unique index), `INV-4` (removing a pipeline or source never deletes
history), `INV-8` (unclaimed inventory is flagged, never silently adopted) and
the single-copy rule of `INV-2`. It is the answer to defects `D-04` (cascading
delete destroyed history), `D-06` (a callback lost the result) and `D-13` (no
inventory sync existed, so reconciliation was impossible).

## 6. Chapter plan

| Chapter | Status |
|---|---|
| `00_PILLAR_OVERVIEW.md` | **locked** — mission, boundaries, Delivery Universe & Reconciliation Model |
| `01_FRONTEND_SPEC.md` | **locked** — delivery history grid, both-sided links, CSV export/import, reconciliation review |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | scaffolded |
| `03_INTERFACE_CONTRACT.md` | **locked** — published `<delivery>.api`, DeliveryDTO, batch APIs (ADJ-P1-02/P5-01) |
| `04_LOGIC_AND_RULES.md` | **locked** — delivery flow, reconcile-before-retry (INV-2), batch SQL queries |
| `05_DATA_MODEL.md` | **locked** — PostgreSQL schema (`delivery`, `delivery_attempt`, `destination_inventory`) |
| `06_FAILURES_AND_ERRORS.md` | **locked** — interrupted upload recovery, duplicate prevention, remote deletion |
| `07_OBSERVABILITY_AND_AUDIT.md` | **locked** — Prometheus delivery metrics, reconciliation mismatch alerts |
| `08_TESTS_AND_DOD.md` | **locked** — reconcile-before-retry tests, INV-1 uniqueness tests, no-cascade tests |
| `09_LEGACY_TRACEABILITY.md` | scaffolded — anchors: `F-11`, `F-24`, `F-25`, `F-50`; defects `D-04`, `D-06`, `D-13`, `D-14` |
| `10_OPEN_QUESTIONS.md` | scaffolded — includes the parked fuzzy-matching question and the parked AI-transformer question |
| `11_DECISIONS.md` | scaffolded |

## 7. Next action

Not yet — wait for Pillar 0 to be locked.

> **Why this pillar is the proof of the whole design:** `docs/07` §3 calls the
> end-to-end test *the sentence the system must be able to say* — a source is
> catalogued, missing videos are delivered, reconciliation agrees with reality,
> and retention deletes nothing by default. Every word of that sentence lands in
> this pillar.
