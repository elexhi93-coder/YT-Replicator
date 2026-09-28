# 08 — Testing Strategy & Definition of Done: Platform Foundation & Ops

**Pillar:** 7 · Platform Foundation & Operations · **Chapter:** Testing Strategy & DoD · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §9  
**Depends on:** All prior chapters in Pillar 7  
**Invariants enforced:** INV-1, INV-2, INV-7, INV-10, INV-11, INV-12  

---

## 1. Test Suite Architecture

| Layer | Focus / Scope | Key Mocking Boundaries |
|---|---|---|
| **Cryptographic Tests** | AES-256-GCM encryption/decryption, tamper detection, random IV generation | Test master key |
| **Pacific Clock Tests** | Verify PST/PDT DST transitions and 00:00:00 rollover accuracy (`INV-2`) | Freezegun / fixed UTC timestamps |
| **Security Tests** | SSRF URL validation, safe path resolution (`INV-7`), CSRF token enforcement | Mock network sockets |
| **Architecture Enforcement (U04)** | 600-line limit per file, zero circular dependencies, AST boundary import rules (`INV-11`) | Pure AST scanner over entire codebase |

---

## 2. Invariant Enforcement Tests

### 2.1 AST Architecture Boundary & 600-Line Cap Test (`INV-11`, U04)
```python
def test_enforce_module_boundaries_and_size():
    """Verify strict layer isolation and 600-line cap across all Python files."""
    import ast
    from pathlib import Path

    src_dir = Path("src")
    for py_file in src_dir.rglob("*.py"):
        # 1. Enforce 600-line cap
        lines = py_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 600, f"File {py_file} exceeds 600 lines ({len(lines)})"

        # 2. Enforce core imports nothing from other modules
        if "src/core" in str(py_file.as_posix()):
            tree = ast.parse("\n".join(lines))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    # Core can only import stdlib and cryptography
                    ...
```

### 2.2 Authenticated AES-256-GCM Cryptographic Test (`INV-1`)
```python
def test_aes_gcm_encryption_and_tamper_resistance():
    """Verify plaintext is encrypted with random IV and detects tampering."""
    secret = "my_super_secret_oauth_token"
    ciphertext = encrypt(secret)
    assert secret not in ciphertext
    
    # Tamper with single byte of tag
    corrupted = ciphertext[:-2] + "AA"
    with pytest.raises(SecretDecryptionError):
        decrypt(corrupted)
```

---

## 3. Definition of Done (DoD) Checklist

- [ ] AES-256-GCM cipher helper verified with 100% test coverage (`ADJ-P2-01`).
- [ ] Pacific Time clock correctly accounts for daylight saving transitions (`INV-2`).
- [ ] Path traversal and SSRF defenses reject malicious inputs (`INV-7`).
- [ ] Automated AST architecture test enforces 600-line limit and illegal import guards (`INV-11`).
- [ ] Docker socket access is structurally forbidden across all modules (`D-05`).
- [ ] `/healthz` probe accurately reports database and disk storage status.
