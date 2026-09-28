# 03 — Interface Contract: Delivery & Ledger

**Pillar:** 6 · Delivery & Ledger · **Chapter:** Interface Contract · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §4  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`  
**Invariants enforced:** INV-1, INV-2, INV-4, INV-8, INV-11, INV-12  

---

## 1. Boundary & Encapsulation Rules

The `delivery` pillar is accessed exclusively via the published module interface:
`src.delivery.api`.

### Boundary Guarantees
1. **Append-Only History (`INV-4`)**: Deletion of pipeline or source entities never cascades to delete delivery receipts.
2. **Batch Query APIs (`ADJ-P1-02`, `ADJ-P5-01`)**: Provides high-efficiency batch lookups for UI catalog views and retention sweeps.
3. **Immutability (`INV-12`)**: All exported types are `@dataclass(frozen=True)` or `Enum`.

---

## 2. Published DTO Hierarchy

```python
"""Public Data Transfer Objects for Pillar 6 (Delivery & Ledger)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    DELIVERED_SUCCESS = "DELIVERED_SUCCESS"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    REMOVED = "REMOVED"


class ReconciliationStatus(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    CLAIMED_OK = "CLAIMED_OK"
    UNCLAIMED_PRESENT = "UNCLAIMED_PRESENT"
    MISSING_EXPECTED = "MISSING_EXPECTED"
    MARKER_MISMATCH = "MARKER_MISMATCH"


@dataclass(frozen=True)
class DeliveryDTO:
    """Canonical delivery receipt linking source video to destination video."""
    delivery_id: str
    catalog_video_id: str
    destination_channel_id: str
    destination_video_id: Optional[str]
    status: DeliveryStatus
    reconciliation_state: ReconciliationStatus
    marker_verified: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DeliveryAttemptDTO:
    """Immutable audit record of a delivery attempt."""
    attempt_id: str
    delivery_id: str
    attempt_number: int
    duration_ms: int
    status_code: Optional[int]
    error_code: Optional[str]
    error_detail: Optional[str]
    created_at: datetime
```

---

## 3. Public API Specification (`src.delivery.api`)

```python
"""Public API functions exported by the delivery module."""
from __future__ import annotations

from typing import Optional, Set, Dict, Tuple
from src.delivery.dto import DeliveryDTO, DeliveryStatus, ReconciliationStatus


def get_delivered_video_ids(source_id: str, destination_channel_id: str) -> Set[str]:
    """Retrieve all catalog_video_id strings delivered to destination (ADJ-P1-02).
    
    Powers fast Catalog Grid rendering without N+1 queries.
    """
    ...


def is_delivered_batch(pairs: Tuple[Tuple[str, str], ...]) -> Dict[Tuple[str, str], bool]:
    """Batch lookup checking whether pairs of (catalog_video_id, destination_channel_id) exist as DELIVERED_SUCCESS.
    
    Powers Pillar 3 candidate deduplication (INV-5).
    """
    ...


def are_all_pipeline_destinations_terminal(catalog_video_id: str, pipeline_id: str) -> bool:
    """Check if all enabled destinations for video have reached a terminal delivery state (ADJ-P5-01).
    
    Enforces INV-2: Required by Pillar 5 before executing storage retention pruning.
    """
    ...


def record_delivery_attempt_start(catalog_video_id: str, destination_channel_id: str, pipeline_id: Optional[str]) -> str:
    """Initialize or update delivery record to IN_FLIGHT and create new attempt row."""
    ...


def record_delivery_success(delivery_id: str, destination_video_id: str, duration_ms: int) -> None:
    """Mark delivery as DELIVERED_SUCCESS, update remote video ID, and commit attempt receipt."""
    ...


def record_delivery_failure(delivery_id: str, error_code: str, error_detail: str, duration_ms: int, is_permanent: bool) -> None:
    """Record failed attempt. If is_permanent=True, transitions delivery to FAILED_PERMANENT."""
    ...


def reconcile_destination_inventory(destination_channel_id: str) -> Dict[ReconciliationStatus, int]:
    """Execute reconciliation comparison between remote channel inventory and internal ledger."""
    ...
```
