# 03 — Interface Contract: Pipelines & Routing

**Pillar:** 3 · Pipelines & Routing · **Chapter:** Interface Contract · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §4  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`  
**Invariants enforced:** INV-5, INV-6, INV-9, INV-11, INV-12  

---

## 1. Boundary & Encapsulation Rules

The `pipelines` pillar is accessed exclusively via the published module interface:
`src.pipelines.api`.

### Boundary Guarantees
1. **Explainable candidate generation**: Evaluates catalog videos against filters and
   the delivery ledger, producing `ReplicationCandidateDTO` objects with exact skip reasons.
2. **Never execute media operations**: Does NOT trigger yt-dlp or upload calls.
3. **Immutability (`INV-12`)**: All exported types are `@dataclass(frozen=True)` or `Enum`.

---

## 2. Published DTO Hierarchy

```python
"""Public Data Transfer Objects for Pillar 3 (Pipelines & Routing)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class PipelineStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class SyncMode(str, Enum):
    BACKFILL = "BACKFILL"   # Oldest-first from cursor
    MONITOR = "MONITOR"     # Newest-first for incoming videos
    BOTH = "BOTH"           # Interleaved: monitor new, backfill old


class SkipReason(str, Enum):
    NONE = "NONE"                             # Video is actionable
    ALREADY_DELIVERED = "ALREADY_DELIVERED"   # Found in delivery ledger (INV-5)
    SHORTS_FILTERED = "SHORTS_FILTERED"       # Excluded by skip_shorts
    LIVE_FILTERED = "LIVE_FILTERED"           # Excluded by skip_live_streams
    DURATION_OUT_OF_BOUNDS = "DURATION_OUT_OF_BOUNDS"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    DESTINATION_QUOTA_FULL = "DESTINATION_QUOTA_FULL"


@dataclass(frozen=True)
class PipelineMediaPolicyDTO:
    """Media download and retention policy exported to Pillar 5."""
    max_resolution: str               # '720p', '1080p', '1440p', '2160p'
    preferred_container: str          # 'mp4', 'mkv'
    include_subtitles: bool
    include_thumbnail: bool
    retention_policy: str             # 'KEEP' | 'DELETE_AFTER_UPLOAD' (INV-6)


@dataclass(frozen=True)
class ReplicationCandidateDTO:
    """Actionable candidate pairing a catalog video to a target destination."""
    pipeline_id: str
    source_id: str
    catalog_video_id: str
    destination_channel_id: str
    canonical_video_id: str           # YouTube video ID (e.g. 'dQw4w9WgXcQ')
    video_title: str
    published_at: datetime
    duration_seconds: int
    privacy_status: str               # 'public', 'unlisted', 'private'
    media_policy: PipelineMediaPolicyDTO
    skip_reason: SkipReason = SkipReason.NONE


@dataclass(frozen=True)
class CandidatePreviewDTO:
    """Dry-run preview summary for operator inspection."""
    pipeline_id: str
    total_evaluated: int
    actionable_count: int
    delivered_count: int
    filtered_count: int
    candidates: tuple[ReplicationCandidateDTO, ...]
```

---

## 3. Public API Specification (`src.pipelines.api`)

```python
"""Public API functions exported by the pipelines module."""
from __future__ import annotations

from typing import Optional
from src.pipelines.dto import (
    PipelineStatus,
    ReplicationCandidateDTO,
    CandidatePreviewDTO,
    PipelineMediaPolicyDTO,
)


def get_candidate_batch(
    pipeline_id: str,
    limit: int = 10,
) -> tuple[ReplicationCandidateDTO, ...]:
    """Calculate and return the next batch of actionable replication candidates.
    
    Cross-references catalog inventory with Pillar 6 ledger.
    Enforces INV-5: Never returns an already delivered pair.
    """
    ...


def preview_pipeline_candidates(pipeline_id: str) -> CandidatePreviewDTO:
    """Dry-run candidate evaluation returning full explainability for all videos."""
    ...


def advance_backfill_cursor(
    pipeline_id: str,
    source_id: str,
    new_cursor_published_at: datetime,
) -> None:
    """Advance the backfill cursor for a pipeline source after successful delivery."""
    ...


def get_pipeline_media_policy(pipeline_id: str) -> Optional[PipelineMediaPolicyDTO]:
    """Retrieve media resolution and retention directives for a pipeline (INV-6)."""
    ...
```
