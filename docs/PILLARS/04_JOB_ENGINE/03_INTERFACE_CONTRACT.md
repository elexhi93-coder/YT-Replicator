# 03 — Interface Contract: Job Engine

**Pillar:** 4 · Job Engine · **Chapter:** Interface Contract · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §4  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`  
**Invariants enforced:** INV-5, INV-10, INV-11, INV-12  

---

## 1. Boundary & Encapsulation Rules

The `jobs` pillar is accessed exclusively via the published module interface:
`src.jobs.api`.

### Boundary Guarantees
1. **Generic Payload Isolation**: The job engine stores payloads as arbitrary JSON dictionaries. It contains zero references to YouTube models, video metadata, or filesystem paths.
2. **Atomic Leases**: Work cannot be processed without acquiring a valid claim lease via `claim_next_job()`.
3. **Immutability (`INV-12`)**: All exported types are `@dataclass(frozen=True)` or `Enum`.

---

## 2. Published DTO Hierarchy

```python
"""Public Data Transfer Objects for Pillar 4 (Job Engine)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional


class JobState(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    COMPLETED = "completed"
    FAILED_PERMANENT = "failed_permanent"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ErrorCategory(str, Enum):
    TRANSIENT = "TRANSIENT"       # Backoff and retry
    PERMANENT = "PERMANENT"       # Mark failed_permanent
    SKIP = "SKIP"                 # Mark skipped with reason


@dataclass(frozen=True)
class EnqueueJobRequest:
    """Request to create a new background job."""
    task_type: str
    payload: Mapping[str, Any]
    idempotency_key: Optional[str] = None       # INV-5 deduplication key
    entity_lock_key: Optional[str] = None       # ADJ-P1-01 concurrency lock key
    priority: int = 100
    scheduled_for: Optional[datetime] = None
    max_attempts: int = 5


@dataclass(frozen=True)
class ClaimedJobDTO:
    """Active execution lease issued to a worker."""
    job_id: str
    task_type: str
    payload: Mapping[str, Any]
    attempt_count: int
    worker_id: str
    lease_expires_at: datetime


@dataclass(frozen=True)
class JobSummaryDTO:
    """Public read-only snapshot of a job record."""
    job_id: str
    task_type: str
    state: JobState
    priority: int
    attempt_count: int
    max_attempts: int
    claimed_by_worker: Optional[str]
    last_error_code: Optional[str]
    skip_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
```

---

## 3. Public API Specification (`src.jobs.api`)

```python
"""Public API functions exported by the jobs module."""
from __future__ import annotations

from typing import Optional
from src.jobs.dto import EnqueueJobRequest, ClaimedJobDTO, JobSummaryDTO, JobState, ErrorCategory


def enqueue_job(request: EnqueueJobRequest) -> str:
    """Enqueue a single background job. Returns created job UUID.
    
    If idempotency_key is provided and already exists, returns existing job_id without duplicate insert.
    """
    ...


def enqueue_batch(requests: tuple[EnqueueJobRequest, ...]) -> tuple[str, ...]:
    """Atomically enqueue a batch of background jobs."""
    ...


def claim_next_job(worker_id: str, supported_task_types: tuple[str, ...]) -> Optional[ClaimedJobDTO]:
    """Atomically claim the highest-priority eligible job using FOR UPDATE SKIP LOCKED.
    
    Respects entity_lock_key: skips jobs whose entity lock is currently held by an active job (ADJ-P1-01).
    """
    ...


def record_heartbeat(job_id: str, worker_id: str) -> bool:
    """Extend lease for an active job. Returns False if lease was stolen/cancelled."""
    ...


def transition_phase(job_id: str, worker_id: str, next_state: JobState) -> None:
    """Progress intermediate job execution phase (e.g. DOWNLOADING -> DOWNLOADED)."""
    ...


def complete_job(job_id: str, worker_id: str, result_summary: Optional[dict] = None) -> None:
    """Mark job as COMPLETED and release any held entity locks."""
    ...


def fail_job(
    job_id: str,
    worker_id: str,
    category: ErrorCategory,
    error_code: str,
    error_detail: str,
    retry_delay_seconds: Optional[int] = None,
) -> None:
    """Report task failure.
    
    - TRANSIENT: Increments attempt_count, calculates exponential backoff + jitter, schedules next run.
    - PERMANENT: Transitions to FAILED_PERMANENT.
    - SKIP: Transitions to SKIPPED with skip_reason.
    """
    ...
```
