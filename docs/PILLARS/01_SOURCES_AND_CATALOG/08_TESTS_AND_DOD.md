# 08 — Tests and Definition of Done: Sources & Catalog

**Pillar:** 1 · Sources & Catalog · **Chapter:** Tests and DoD · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md`  
**Depends on:** `docs/PILLARS/01_SOURCES_AND_CATALOG/03_INTERFACE_CONTRACT.md` · `docs/PILLARS/01_SOURCES_AND_CATALOG/04_LOGIC_AND_RULES.md`  
**Invariants enforced:** INV-5, INV-7, INV-9, INV-11, INV-12, F-48  

---

## 1. Test Suite Architecture

Pillar 1 requires four distinct tiers of automated tests:

### 1.1 Architectural Boundary Tests (Non-Negotiable)
- `test_sources_cannot_import_media()`: Static AST analysis asserting zero imports of `media` or download libraries (`yt_dlp.YoutubeDL.download`) within `sources/`. **Guarantees INV-7**.
- `test_sources_external_access_via_api_only()`: AST analysis asserting no module outside `sources/` imports internal tables or submodules, only `sources.api`. **Guarantees INV-11**.
- `test_sources_dtos_are_frozen()`: Verifies that all DTOs returned by `sources.api` are `@dataclass(frozen=True)` with immutable sequences (`tuple`). **Guarantees INV-12**.

### 1.2 SSRF & Security Unit Tests
- `test_register_source_rejects_localhost()`: Verifies `http://localhost`, `127.0.0.1`, `::1` raise `InvalidSourceUrlError`.
- `test_register_source_rejects_private_ips()`: Verifies `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.169.254` are blocked.
- `test_register_source_rejects_non_youtube_schemes()`: Verifies `ftp://`, `file://`, and other domains are rejected.

### 1.3 Logic & Partial Failure Tests (`F-48`)
- `test_scan_recovers_from_deleted_video()`: Mocks playlist containing a deleted item (`[Deleted video]`); asserts scan completes, logs `ITEM_SKIP_DELETED`, persists valid items, and leaves source in `PARTIAL_WARNING`.
- `test_scan_concurrency_lock()`: Simulates concurrent scan requests for the same `source_id`; asserts the second request is rejected or queued (`ADJ-P1-01`).
- `test_source_reusability_across_pipelines()`: Simulates two pipelines linking to the same `source_id`; asserts zero catalog duplication (`INV-9`).

### 1.4 Database & Schema Integration Tests
- `test_catalog_upsert_idempotency()`: Re-running a scan on an existing playlist updates `view_count` but never creates duplicate rows (`uq_source_video`).
- `test_is_hydrated_flag_preserved()`: Proves that upserting an already-hydrated video (`is_hydrated=True`) never resets it back to `False`.

---

## 2. Definition of Done (DoD) Checklist

A pull request implementing Pillar 1 cannot be merged unless all items pass:

- [ ] **Architecture Check**: Static boundary tests pass proving zero download capability in `sources/` (`INV-7`).
- [ ] **Security Check**: SSRF firewall blocks all non-YouTube and private IP patterns.
- [ ] **Resilience Check**: `F-48` partial failure test passes with zero uncaught exceptions when encountering private/deleted videos.
- [ ] **Schema Check**: Migrations for `sources` and `catalog_video` run cleanly forward and backward on PostgreSQL 16.
- [ ] **Contract Check**: All methods in `sources.api` return frozen DTOs and raise only typed errors.
- [ ] **UI Conformance**: Sources view and Catalog Explorer render correctly in empty, scanning, error, and partial-warning states.

---

## 3. Change Log

- **2026-09-28:** Authored `08_TESTS_AND_DOD.md` specifying test tiers (boundary, security, logic, schema) and the definitive Definition of Done checklist.
