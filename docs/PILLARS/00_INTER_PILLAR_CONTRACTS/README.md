# Pillar 0 — Inter-Pillar Contracts (The Highway)

**Status:** `drafting` — **the interface contract (chapter 03) is written.**
**Chapters:** twelve files, per `_STANDARD/CHAPTER_STANDARD.md`.
**Depends on:** nothing. Every other pillar depends on **this**.

---

## 1. Mission

Define the boundary language of the system — the DTOs, the ports, and the rules
for how pillars exchange work — so that any pillar can be replaced without
editing the pillars around it.

**This is the pillar that makes the project extensible.** It exists because of
two agreed futures (`docs/000_AI_ARCHITECT_INSTRUCTIONS.md` §4, IDEA-01/02/03):

- a different **source** pillar (video editor, local folder, cloud bucket) can
  replace the YouTube source pillar;
- a different **destination** pillar (Facebook, TikTok, Dailymotion) can be added
  alongside YouTube;
- a **metadata transformer** (AI or otherwise) can be inserted between source and
  destination, or omitted entirely.

## 2. Owns

- The DTOs that cross a pillar boundary (video identity, media verification,
  metadata payload, delivery outcome).
- The **ports** (abstract interfaces) each pluggable role must satisfy.
- The rules of exchange: who may call whom, what may cross, what may never cross.
- The identity rule: how one video is named consistently across every pillar.
- **The provenance-marker format** itself: it is written by the platform adapter
  (Pillar 2) and parsed by reconciliation (Pillar 6), so it is a boundary artefact
  and therefore a Pillar 0 contract — `docs/05` §6 depends on it.
- **What the contracts are realised in code:** `core`'s base types
  (Pillar 7 owns that module; this pillar owns the interfaces it expresses).

## 3. Does not own

| Not owned here | Owner |
|---|---|
| What a source *is*, or how it is scanned | Pillar 1 (`01_SOURCES_AND_CATALOG`) |
| What a destination *is*, or how it is authorised | Pillar 2 (`02_DESTINATIONS_AND_AUTH`) |
| Which source feeds which destination | Pillar 3 (`03_PIPELINES_AND_ROUTING`) |
| Queue, claims, retries | Pillar 4 (`04_JOB_ENGINE`) |
| Bytes on disk | Pillar 5 (`05_MEDIA_AND_STORAGE`) |
| Upload calls and ledger rows | Pillar 6 (`06_DELIVERY_AND_LEDGER`) |

## 4. Dependencies

Inbound: none. Outbound: this pillar is read by all six others. A change to a
port here is a **breaking change for every pillar** and must be recorded in
`11_DECISIONS.md` and in `docs/04_ARCHITECTURE.md` §6 in the same change.

## 5. Invariants this pillar protects

`INV-9` (a source is reusable), `INV-11` (one module per change), `INV-12`
(imports only through a published interface). It is the mechanism by which those
three become checkable rather than aspirational.

## 6. Chapter plan

| Chapter | Status |
|---|---|
| `00_PILLAR_OVERVIEW.md` | scaffolded |
| `01_FRONTEND_SPEC.md` | scaffolded — expected small: ports are configured through Pillars 2 and 3, not on their own screen |
| `02_WORKSPACE_AND_TENANCY_SLOT.md` | scaffolded |
| `03_INTERFACE_CONTRACT.md` | **drafting** — written; review pending |
| `04_LOGIC_AND_RULES.md` | **drafting** — written; review pending |
| `05_DATA_MODEL.md` | **drafting** — written; review pending |
| `06_FAILURES_AND_ERRORS.md` | scaffolded — a port that raises must be classified |
| `07_OBSERVABILITY_AND_AUDIT.md` | scaffolded |
| `08_TESTS_AND_DOD.md` | scaffolded — contract tests every adapter must pass |
| `09_LEGACY_TRACEABILITY.md` | scaffolded — anchors: `F-45`, `F-47`, `D-09`, `D-13` |
| `10_OPEN_QUESTIONS.md` | scaffolded |
| `11_DECISIONS.md` | scaffolded |

## 7. Obligations this pillar creates

Writing this pillar is not a free edit. Because it **adds published interfaces**
that do not exist today, our own rules require the following in the *same* change
(`03` §1, `04` §6, `00` §6):

| Obligation | Document | Why |
|---|---|---|
| One row per port added to the **interface change log** | `docs/04_ARCHITECTURE.md` §6 | That table is what makes INV-11 auditable |
| The ports added to the **published interface list** | `docs/04_ARCHITECTURE.md` §5 | Otherwise `04` §5 and the code disagree — the D-01 class |
| The `06` §1 entries for the adapters | `docs/06_FEATURE_ROADMAP.md` | A port with no v1 implementation is a park, and parks live in `06` §2 |
| A glossary entry for every new noun (e.g. *port*, *adapter*) | `docs/00_DESIGN_PRINCIPLES.md` §2 | One word, one meaning |
| The `04` §2 module map unchanged, or changed deliberately | `docs/04_ARCHITECTURE.md` §2 | Ports live in `core`'s base types; no new module is created without a decision |

**Out of scope for this pillar, by decision:** v1 ships the ports with exactly one
implementation each (YouTube source, YouTube destination, pass-through metadata).
A port with zero implementations, or a second adapter, is v2 work recorded in the
Idea Vault.

---

## 8. Next action

Write `03_INTERFACE_CONTRACT.md` first — the ports themselves. Everything else
in this pillar documents them.
