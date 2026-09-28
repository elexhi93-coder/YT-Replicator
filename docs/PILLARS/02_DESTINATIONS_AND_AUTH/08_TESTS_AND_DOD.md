# 08 — Testing Strategy & Definition of Done: Destinations & Auth

**Pillar:** 2 · Destinations & Auth · **Chapter:** Testing Strategy & DoD · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §9  
**Depends on:** All prior chapters in Pillar 2  
**Invariants enforced:** INV-1, INV-2, INV-4, INV-11, INV-12  

---

## 1. Test Suite Architecture

| Layer | Focus / Scope | Key Mocking Boundaries |
|---|---|---|
| **Unit Tests** | Quota math, Pacific day rollover, token expiration math, WebP-to-JPEG conversion | Mock `datetime.now`, mock crypto cipher |
| **AST / Boundary Tests** | Enforce `INV-1` (no plaintext secrets in DTOs/logs) and `INV-4` (zero imports of `src.ledger`) | AST scanner inspecting all `src.destinations` code |
| **Integration Tests** | Resumable chunk upload state machine, token refresh HTTP mocks, PostgreSQL row-level locks | Mock YouTube HTTP server (wiremock / pytest-httpx) |
| **Contract Tests** | Verify `YouTubeDestinationAdapter` strictly adheres to `DestinationPlatform` protocol | Pillar 0 protocol test suite |

---

## 2. Invariant Enforcement Tests

### 2.1 AST Isolation Test (`INV-4`: Zero Ledger Writes)
```python
def test_destinations_never_imports_or_writes_ledger():
    """Verify that src.destinations does not import ledger models or services."""
    import ast
    from pathlib import Path

    destinations_dir = Path("src/destinations")
    for py_file in destinations_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "ledger" not in alias.name, f"Forbidden import in {py_file}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "ledger" not in node.module, f"Forbidden import in {py_file}: {node.module}"
```

### 2.2 Pacific Time Rollover Test (`INV-2`)
```python
def test_quota_rolls_over_at_midnight_pacific():
    """Verify quota usage resets at exactly 00:00:00 Pacific Time regardless of UTC."""
    # 23:59:59 PT -> quota full -> can_upload=False
    # 00:00:01 PT -> quota fresh -> can_upload=True
    ...
```

---

## 3. Definition of Done (DoD) Checklist

- [ ] All 10 destination universe attributes from `00_PILLAR_OVERVIEW.md` §4 are modeled and tested.
- [ ] Client secret and refresh token encryption at rest verified (`INV-1`).
- [ ] Pacific day quota boundary tests passing with 100% test coverage (`INV-2`).
- [ ] AST boundary test confirms zero imports of ledger modules (`INV-4`).
- [ ] Resumable upload chunking handles network disconnect and resumes from byte offset.
- [ ] UI specifications in `01_FRONTEND_SPEC.md` verified against mock layouts.
