# 03 — Interface Contract: Media & Storage

**Pillar:** 5 · Media & Storage · **Chapter:** Interface Contract · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §4  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`  
**Invariants enforced:** INV-2, INV-3, INV-7, INV-10, INV-11, INV-12  

---

## 1. Boundary & Encapsulation Rules

The `media` pillar is accessed exclusively via the published module interface:
`src.media.api`.

### Strict Boundary Guarantees
1. **Exclusive Disk Owner**: No other pillar in the system is permitted to perform file I/O, `open()`, `os.remove()`, or directory scans.
2. **Pre-condition for Upload (`INV-3`)**: Uploaders can obtain a physical media path ONLY by calling `get_verified_asset_for_upload()`, which checks that the asset is strictly in `ON_DISK` state with non-zero size and verified SHA-256.
3. **Safe Roots (`INV-7`)**: All paths returned or processed are guaranteed to resolve inside configured storage roots.
4. **Dry-Run Enforcement (`INV-10`)**: Deletion logic is centralized; dry-run query guarantees zero disk side-effects.
5. **Immutability (`INV-12`)**: All exported types are `@dataclass(frozen=True)` or `Enum`.

---

## 2. Published DTO Hierarchy

```python
"""Public Data Transfer Objects for Pillar 5 (Media & Storage)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class MediaAssetState(str, Enum):
    EXPECTED = "EXPECTED"
    DOWNLOADING = "DOWNLOADING"
    ON_DISK = "ON_DISK"
    DELETED = "DELETED"
    ARCHIVE_OFFLINE = "ARCHIVE_OFFLINE"


@dataclass(frozen=True)
class MediaAssetDTO:
    """Public read-only summary of a media asset."""
    asset_id: str
    catalog_video_id: str
    state: MediaAssetState
    byte_size: int
    sha256: Optional[str]
    container: str
    is_pinned: bool
    verified_at: Optional[datetime]
    created_at: datetime


@dataclass(frozen=True)
class VerifiedMediaAssetDTO:
    """Verified payload provided exclusively to the upload engine (INV-3)."""
    asset_id: str
    catalog_video_id: str
    absolute_path: Path
    byte_size: int
    sha256: str
    container: str
    thumbnail_bytes: Optional[bytes]


@dataclass(frozen=True)
class RetentionCandidateDTO:
    """Candidate asset selected for retention pruning with verification proof."""
    asset_id: str
    catalog_video_id: str
    relative_path: str
    byte_size: int
    pipeline_id: str
    retention_reason: str
    all_destinations_terminal: bool       # Verified via INV-2 ledger check


@dataclass(frozen=True)
class RetentionDryRunResultDTO:
    """Result of retention dry-run simulation (INV-10)."""
    evaluated_at: datetime
    total_candidates: int
    total_reclaimable_bytes: int
    candidates: tuple[RetentionCandidateDTO, ...]
```

---

## 3. Public API Specification (`src.media.api`)

```python
"""Public API functions exported by the media module."""
from __future__ import annotations

from typing import Optional
from src.media.dto import (
    MediaAssetDTO,
    VerifiedMediaAssetDTO,
    RetentionDryRunResultDTO,
)
from src.pipelines.dto import PipelineMediaPolicyDTO


def acquire_media(
    catalog_video_id: str,
    source_url: str,
    policy: PipelineMediaPolicyDTO,
) -> MediaAssetDTO:
    """Acquire video media via yt-dlp according to pipeline quality policy.
    
    Downloads to temporary .part file, computes SHA-256 and size, and atomically renames (INV-3).
    Enforces free-space floor check (> 10 GB free) before starting.
    """
    ...


def get_verified_asset_for_upload(catalog_video_id: str) -> Optional[VerifiedMediaAssetDTO]:
    """Retrieve verified media path and metadata for video upload.
    
    Enforces INV-3: Returns VerifiedMediaAssetDTO ONLY if asset is strictly ON_DISK with confirmed SHA-256.
    """
    ...


def evaluate_retention_dry_run(pipeline_id: Optional[str] = None) -> RetentionDryRunResultDTO:
    """Simulate retention policy evaluation without deleting files (INV-10).
    
    Enforces INV-2: Validates that all enabled pipeline destinations have terminal status in Pillar 6 ledger.
    """
    ...


def execute_retention_prune(dry_run_token: str) -> int:
    """Execute physical unlinks for confirmed retention candidates.
    
    Centralized single deletion choke-point (INV-10). Returns total bytes reclaimed.
    """
    ...


def pin_asset(catalog_video_id: str) -> None:
    """Pin an asset to protect it from automated retention pruning."""
    ...


def unpin_asset(catalog_video_id: str) -> None:
    """Unpin an asset to allow automated retention pruning."""
    ...
```
