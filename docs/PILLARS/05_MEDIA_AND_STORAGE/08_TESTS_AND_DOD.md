# 08 — Testing Strategy & Definition of Done: Media & Storage

**Pillar:** 5 · Media & Storage · **Chapter:** Testing Strategy & DoD · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §9  
**Depends on:** All prior chapters in Pillar 5  
**Invariants enforced:** INV-2, INV-3, INV-6, INV-7, INV-10, INV-11, INV-12  

---

## 1. Test Suite Architecture

| Layer | Focus / Scope | Key Mocking Boundaries |
|---|---|---|
| **Unit Tests** | Path traversal boundary checks (`INV-7`), SHA-256 calculation, retention policy rule math | Temporary in-memory or pytest `tmp_path` |
| **Integration Tests** | Two-phase atomic rename (`.part` ➔ `.mp4`), orphan reaper loop, DB state updates | Real filesystem sandbox |
| **Safety Invariant Tests** | Enforce `INV-2` (premature deletion blocked if destination not terminal) and `INV-10` (dry-run deletes zero files) | Mock Pillar 6 ledger |
| **AST / Boundary Tests** | Verify **no other module in codebase imports `os.remove`, `os.unlink`, or `shutil.rmtree`** | AST scanner across `src/` |

---

## 2. Invariant Enforcement Tests

### 2.1 Dry-Run Non-Destructive Guarantee (`INV-10`)
```python
def test_retention_dry_run_never_mutates_filesystem(tmp_path):
    """Assert evaluate_retention_dry_run leaves all physical files intact."""
    test_file = tmp_path / "videos" / "test.mp4"
    test_file.write_bytes(b"dummy media bytes")
    
    # Run dry-run simulation
    result = evaluate_retention_dry_run()
    
    # Assert file is listed as candidate but still physically exists
    assert result.total_candidates >= 1
    assert test_file.exists()
```

### 2.2 Terminal Destination Defense (`INV-2`)
```python
def test_retention_prune_blocked_if_any_destination_in_flight(mock_ledger):
    """Assert asset is NOT eligible for deletion while any bound destination is in-flight."""
    ...
```

### 2.3 Exclusive Disk Ownership AST Test
```python
def test_only_media_module_touches_filesystem_deletion():
    """Verify that only src/media performs physical file unlinks."""
    import ast
    from pathlib import Path

    for py_file in Path("src").rglob("*.py"):
        if "src/media" in str(py_file.as_posix()):
            continue
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("unlink", "remove", "rmdir"):
                raise AssertionError(f"Illegal filesystem mutation in non-media module: {py_file}:{node.lineno}")
```

---

## 3. Definition of Done (DoD) Checklist

- [ ] Path traversal defenses tested against directory escape vectors (`INV-7`).
- [ ] Atomic verification tests confirm `.part` rename occurs only after valid SHA-256 (`INV-3`).
- [ ] Dry-run retention test proves zero file deletions occurred during preview (`INV-10`).
- [ ] Retention prune requires all bound pipeline destinations to be terminal (`INV-2`).
- [ ] Free space admission gate halts downloads before disk saturation (< 10 GB).
- [ ] AST test passes: zero filesystem deletion calls outside `src.media`.
