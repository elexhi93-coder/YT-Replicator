# 000 — Pillar 0 Instructions & Working Frontier (Inter-Pillar Contracts Trunk)

**Pillar:** 0 — Inter-Pillar Contracts Trunk  
**Status:** `locked`  
**Authority:** Trunk governing contract for all pillars. Governed by `docs/000_*` and `docs/PILLARS/_STANDARD/PILLAR_INSTRUCTIONS_STANDARD.md`.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
Serve as the **single source of truth for cross-pillar interaction**: define the ports (abstract protocols), the frozen Data Transfer Objects (DTOs), the universal provenance marker format, and the architectural invariants that bind all seven domain pillars together without tight coupling or cyclical dependencies.

### What This Pillar Owns
- The abstract port interfaces: `CatalogDiscoveryPort`, `DestinationPlatform`, `MetadataTransformer`.
- The canonical DTO hierarchy: frozen, immutable data structures exchanged across pillar boundaries (`INV-12`).
- The universal Provenance Marker format: `<!-- YTR:src={source_id}:vid={source_video_id} -->`.
- The architectural invariants registry: `INV-1` through `INV-12`.
- Base error taxonomy from which domain-specific pillar exceptions inherit.

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- ❌ **NEVER implements concrete platform adapters**: Adapters live in domain pillars (e.g., YouTube upload adapter lives in Pillar 2).
- ❌ **NEVER touches the database or filesystem**: Contains zero SQL queries, database migrations, or file I/O operations.
- ❌ **NEVER renders HTML or UI**: Contracts are pure Python protocols and data specifications.
- ❌ **NEVER holds application runtime state**: Pure contracts layer.

---

## 2. Invariants & Non-Negotiable Guards

| Invariant | Rule | Enforcement Mechanism |
|---|---|---|
| **INV-1** | **One successful delivery per pair** | Partial unique index on delivery ledger. |
| **INV-2** | **Terminal retention & Reconcile before retry** | Pre-retry inventory check; retention checks all destinations. |
| **INV-3** | **Zero unverified uploads** | Verified SHA-256 and non-zero size required before upload handover. |
| **INV-4** | **Ledger durability** | Foreign key constraints never cascade delete delivery receipts. |
| **INV-5** | **Zero duplicate enqueues** | Deduplication check against delivery ledger before job creation. |
| **INV-6** | **Retention reproducibility** | Retention policy defined in relational state alone. |
| **INV-7** | **Scanning never downloads & safe paths** | Static AST boundary tests; path traversal checks. |
| **INV-8** | **Unclaimed inventory flagged** | Foreign remote videos flagged for review, never auto-adopted. |
| **INV-9** | **Source reusability** | One source feeds multiple pipelines via independent cursors. |
| **INV-10**| **SKIP LOCKED atomic claims & dry-run deletions** | PostgreSQL concurrency; mandatory deletion preview. |
| **INV-11**| **Modular change isolation** | Access only via published `<module>.api` interfaces. |
| **INV-12**| **Frozen DTO boundaries & 600-line cap** | `@dataclass(frozen=True)` across boundaries; AST line count checks. |

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `000` | `000_PILLAR_INSTRUCTIONS.md` | `locked` | Trunk directive, boundaries, invariants registry |
| `03` | `03_INTERFACE_CONTRACT.md` | `locked` | Ports, abstract protocols, frozen DTO hierarchy |
| `04` | `04_LOGIC_AND_RULES.md` | `locked` | Invariant enforcement rules, cross-pillar interaction protocol |
| `05` | `05_DATA_MODEL.md` | `locked` | Shared typing, UUID standards, enum definitions |
| `README` | `README.md` | `locked` | Highway overview & architectural rationale |
