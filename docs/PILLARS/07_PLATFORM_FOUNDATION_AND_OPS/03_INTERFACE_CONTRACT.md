# 03 — Interface Contract: Platform Foundation & Ops

**Pillar:** 7 · Platform Foundation & Operations · **Chapter:** Interface Contract · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §4  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`  
**Invariants enforced:** INV-1, INV-2, INV-7, INV-11, INV-12  

---

## 1. Boundary & Encapsulation Rules

Pillar 7 exports the foundation interfaces via the following public boundaries:
- `src.core.crypto`: Authenticated AES-256-GCM encryption/decryption (`ADJ-P2-01`).
- `src.core.clock`: Authoritative Pacific Time quota clock (`INV-2`).
- `src.core.security`: Path traversal resolution (`INV-7`) and SSRF domain firewall.
- `src.accounts.api`: Tenancy context (`current_workspace()`) and role enforcement.
- `src.ops.api`: Centralized audit logging (`record_audit_event()`) and health probes.
- `src.worker.api`: Generic worker runner (`run_once()`, `run_forever()`).

---

## 2. Published DTO Hierarchy

```python
"""Public Data Transfer Objects for Pillar 7 (Platform Foundation & Ops)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from typing import Any, Mapping, Optional


class WorkspaceRole(str, Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


@dataclass(frozen=True)
class WorkspaceContextDTO:
    """Current authenticated workspace context."""
    workspace_id: str
    workspace_name: str
    user_id: int
    user_role: WorkspaceRole


@dataclass(frozen=True)
class PacificTimeDTO:
    """Authoritative Pacific Time snapshot for quota boundaries."""
    utc_now: datetime
    pacific_now: datetime
    pacific_date: date                   # Calendar date in America/Los_Angeles
    next_midnight_pacific_utc: datetime  # UTC moment of next 00:00:00 PT rollover


@dataclass(frozen=True)
class AuditEventDTO:
    """Immutable platform audit event record."""
    event_id: str
    event_name: str
    actor_id: str
    workspace_id: Optional[str]
    payload: Mapping[str, Any]
    occurred_at: datetime
```

---

## 3. Public API Specifications

### 3.1 Cryptographic API (`src.core.crypto`, `ADJ-P2-01`)
```python
def encrypt(plaintext: str) -> str:
    """Encrypt plaintext string using AES-256-GCM with platform master key.
    
    Returns base64 formatted ciphertext: 'iv:ciphertext:tag' (INV-1).
    """
    ...


def decrypt(ciphertext: str) -> str:
    """Decrypt AES-256-GCM ciphertext back to plaintext.
    
    Raises SecretDecryptionError if ciphertext is corrupt, tampered with, or key mismatches.
    """
    ...
```

### 3.2 Pacific Clock API (`src.core.clock`, `INV-2`)
```python
def get_pacific_time() -> PacificTimeDTO:
    """Return authoritative Pacific Time snapshot for daily quota calculations."""
    ...


def get_pacific_date_string() -> str:
    """Return current Pacific calendar date formatted as 'YYYY-MM-DD'."""
    ...
```

### 3.3 Security & Safe Path API (`src.core.security`, `INV-7`)
```python
def resolve_safe_path(base_root: Path, relative_path: str) -> Path:
    """Resolve and verify that relative_path strictly resides within base_root.
    
    Raises PathTraversalSecurityError on path escape attempts ('../').
    """
    ...


def is_safe_ssrf_url(url: str, allowed_domains: tuple[str, ...]) -> bool:
    """Validate that URL strictly targets allowed public domains and does not resolve to private IPs."""
    ...
```

### 3.4 Audit API (`src.ops.api`)
```python
def record_audit_event(
    event_name: str,
    actor_id: str,
    payload: Mapping[str, Any],
    workspace_id: Optional[str] = None,
) -> str:
    """Append an immutable audit entry to audit_event ledger. Returns event UUID."""
    ...
```
