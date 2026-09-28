# 000 — AI Deep Specification Standard (Tree-Branch-Leaf Methodology)

**Project:** YT-Replicator  
**Document Status:** Permanent & Mandatory  
**Authority:** Architectural Standard for Deep Pillar Documentation ("The Leaves")  
**Companion Documents:** Governed by `docs/000_AI_SUPREME_PROTOCOL.md` and tracked in `docs/000_AI_ARCHITECT_INSTRUCTIONS.md`.  

---

## 1. Purpose & The Tree-Branch-Leaf Model

To build a resilient, production-grade system and prevent monolithic assumptions, documentation proceeds hierarchically from systemic structure down to microscopic operational detail:

```
┌────────────────────────────────────────────────────────────────────────┐
│  THE TREE (System Foundation & Cross-Cutting Invariants)               │
│  docs/00–07, docs/000_*, Pillar 0 Inter-Pillar Contracts (The Highway) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  THE BRANCHES (The 7 Pillars & Bounded Modules)                        │
│  Pillars 01 through 07, Chapter 00 to 11 skeletons per CHAPTER_STANDARD│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  THE LEAVES (Deep Domain Exhaustiveness & Field-Level Registries)      │
│  External platform schema universes, screen-by-screen component       │
│  states, error taxonomy, and end-to-end data lineage tables.           │
└────────────────────────────────────────────────────────────────────────┘
```

**The Leaf Mandate:** No production code shall be authored for a module until its external platform schemas (e.g., YouTube field universe), UI component layouts, data lineage, and failure classifications are fully specified down to the bone.

---

## 2. Pillar Leaf Standard: The External Platform Field Universe

When documenting any external platform integration (starting with YouTube in Pillar 1 and Pillar 2), the documentation must explicitly catalog every attribute across the four dimensions of acquisition:

### 2.1 The Four Ingestion / Interaction Tiers

| Tier | Mechanism | Latency / Cost Profile | Auth Requirement | Capabilities / Limits |
|---|---|---|---|---|
| **Tier 1: RSS Feed** | XML Feed (`feeds/videos.xml?channel_id=...`) | Zero quota, HTTP GET (~100ms) | Public / None | Max 15 newest videos; minimal fields (id, title, published, link). |
| **Tier 2: Fast Flat Scan** | `yt-dlp --flat-playlist` | Free (no API quota), light network | Public / None | Fast batch retrieval; provides title, id, duration, basic status. |
| **Tier 3: Hydrated Metadata** | `yt-dlp -j` (full dump) / InnerTube | Heavy scrape, rate-limit sensitive | Public / Web Cookies | Rich description, full tags, formats, chapter markers, view/like counts. |

### 2.2 Mandatory Field Registry Rubric

Every field discovered or managed must be documented in a tabular registry conforming to:

1. **Field Name**: Canonical platform attribute name (e.g. `snippet.title`, `duration`, `tags`).
2. **Access Tier**: Which Tier(s) provide this field (RSS / Flat / Hydrated / API v3).
3. **Visibility**: Public (unauthenticated) vs. Non-Public (requires channel OAuth).
4. **Data Type & Nullability**: e.g., `int | None`, `tuple[str, ...]`.
5. **Storage Destination**: PostgreSQL column name or `raw_metadata` JSONB path.
6. **UI Destination**: Exactly where in the frontend this field appears (e.g. `Catalog Table: Col 2`, `Inspector Modal`, or `Internal Only`).

---

## 3. Frontend Component & Screen Precision Standard

For every screen defined in a pillar's `01_FRONTEND_SPEC.md`:

### 3.1 Mandatory Screen Frame
1. **Screen Name & URL Route**: Exact path (e.g. `/sources/<id>/catalog`).
2. **Layout Slots**:
   - Navigation / Workspace Context Slot.
   - Action / Header Bar (Primary CTA, Refresh, Batch Actions).
   - Filter & Search Bar (Inputs, dropdowns, debounce timings).
   - Data Grid / Table (Columns, sortability, alignment, truncation rules).
   - Detail Drawer / Modal (Hydrated inspector, raw metadata tabs).
3. **Component State Matrix**:
   - `Initial / Empty`: What shows when zero rows exist (exact CTA copy).
   - `Loading / Scanning`: Progress indicators, spinner or progress bar text.
   - `Hydrating`: Visual indicator when flat items are awaiting background detail fetch.
   - `Error / Degraded`: Exact error banners, retry button behavior.
4. **Interactive Controls & Failure Messaging**:
   - Every button must define its disabled conditions and failure feedback strings.

---

## 4. End-to-End Data Lineage Matrix

To guarantee strict compliance with **INV-11** (modularity) and **INV-12** (explicit boundaries), each data point must document its full lifecycle:

```
[External Platform Field]
           │
           ▼
[Port / DTO Attribute] (Pillar 0 Frozen Dataclass)
           │
           ▼
[PostgreSQL 16 Column] (docs/03 Relational Schema)
           │
           ▼
[Module API Function] (<module>.api)
           │
           ▼
[UI Component / Table Cell] (Server-rendered HTML / SSE)
```

---

## 5. Failure Classification & Retry Discipline

No error may be handled generically. Every exception crossing or residing in a pillar must map into:

1. **Category**:
   - `Transient`: Network timeout, 5xx gateway error, rate limit (429) ➔ Eligible for automated retry with exponential backoff via Job Engine (Pillar 4).
   - `Permanent`: 404 Not Found, 403 Forbidden/Account Terminated, invalid file format ➔ Immediate failure, no automated retry, operator intervention required.
   - `Skip`: Item already processed, video private/withdrawn during scan ➔ Safely recorded and skipped without failing the parent batch (`F-48`).
2. **Operator Feedback String**: Deterministic human-readable explanation stored in `last_error` or audit log.
3. **Retry Ceiling**: Maximum retry attempts and backoff formula.

---

## 6. Execution Discipline for Moving from Branch to Leaf

When advancing a Pillar into "The Leaves":
1. **Start with the External Truth**: Map the platform field universe first (what the outside world gives us).
2. **Map the Internal Flow**: Connect fields through the DTOs into the PostgreSQL schema.
3. **Specify the Operator Interface**: Design the exact screens, buttons, and error states that expose that data.
4. **Lock Before Code**: Validate that all specifications meet the **INV** invariants before authoring implementation code.

| **Tier 4: Official Data API v3** | Google REST API (`videos.list`, etc.) | Quota-metered (1 to 1600 units) | OAuth2 Bearer Token | Private tags, exact privacy status, Pacific Midnight quota consumption. |
