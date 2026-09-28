# 03 — Interface Contract: Destinations & Auth

**Pillar:** 2 · Destinations & Auth · **Chapter:** Interface Contract · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §4  
**Depends on:** `docs/PILLARS/00_INTER_PILLAR_CONTRACTS/03_INTERFACE_CONTRACT.md`  
**Invariants enforced:** INV-1, INV-2, INV-4, INV-11, INV-12  

---

## 1. Boundary & Encapsulation Rules

The `destinations` pillar is accessed exclusively via the published module interface:
`src.destinations.api` or through the `DestinationPlatform` adapter instance registered
in the platform registry.

### Strict Architectural Boundaries
1. **Never write to ledger tables (`INV-4`)**: The `upload_video` implementation uploads the
   media to YouTube via resumable chunks, fetches the final video ID, and returns a
   `DestinationUploadResult` DTO. It does NOT create ledger entries.
2. **Encrypted at rest (`INV-1`)**: DTOs returned across pillar boundaries NEVER contain
   decrypted OAuth client secrets or refresh tokens. Only ephemeral short-lived access
   tokens are used internally during upload execution.
3. **Immutability (`INV-12`)**: All DTOs are defined with `@dataclass(frozen=True)`.

---

## 2. Published DTO Hierarchy

```python
"""Public Data Transfer Objects for Pillar 2 (Destinations & Auth)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class TokenHealthStatus(str, Enum):
    VALID = "VALID"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class DestinationChannelDTO:
    """Public summary of an authorized YouTube destination channel."""
    id: str                               # Internal UUID
    canonical_id: str                     # YouTube Channel ID ('UC...')
    title: str                            # Channel Title
    avatar_url: Optional[str]             # Display icon
    client_id: str                        # Owning Google Client ID
    token_health: TokenHealthStatus       # Current OAuth token health
    default_privacy: str                  # 'public' | 'unlisted' | 'private'
    default_category_id: str              # YouTube Category ID (e.g. '22')
    made_for_kids: bool                   # COPPA compliance declaration
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class QuotaBudgetDTO:
    """Live snapshot of YouTube API quota consumption for a channel's client."""
    client_id: str
    pacific_date: str                     # Format: 'YYYY-MM-DD'
    consumed_units: int                   # Cumulative units consumed today
    daily_limit: int                      # Daily project limit (e.g. 10000)
    units_remaining: int                  # daily_limit - consumed_units
    can_upload_now: bool                  # True if units_remaining >= 1600
    uploads_remaining: int                # units_remaining // 1600
    resets_at_utc: datetime               # UTC timestamp of next 00:00:00 PT
```

---

## 3. Public API Specification (`src.destinations.api`)

```python
"""Public API functions exported by the destinations module."""
from __future__ import annotations

from typing import Optional
from src.destinations.dto import DestinationChannelDTO, QuotaBudgetDTO
from src.contracts.destination import DestinationUploadInput, DestinationUploadResult


def get_channel(channel_id: str) -> Optional[DestinationChannelDTO]:
    """Retrieve an authorized destination channel by its internal or canonical ID."""
    ...


def list_authorized_channels(workspace_id: Optional[str] = None) -> tuple[DestinationChannelDTO, ...]:
    """List all authorized channels for a workspace, sorted by title."""
    ...


def check_quota_budget(channel_id: str) -> QuotaBudgetDTO:
    """Inspect remaining daily YouTube quota budget for the channel's Google client.
    
    Enforces INV-2: Evaluates quota strictly against Pacific Time calendar date.
    Returns can_upload_now=True ONLY if units_remaining >= 1600.
    """
    ...


def execute_upload(
    channel_id: str,
    upload_input: DestinationUploadInput,
) -> DestinationUploadResult:
    """Executes video upload against YouTube Data API v3.
    
    Conforms to Pillar 0 DestinationPlatform port contract.
    Enforces INV-1 (decrypts refresh token in-memory), INV-2 (reserves 1600 units),
    and INV-4 (returns DestinationUploadResult; does NOT write to ledger).
    """
    ...
```

---

## 4. YouTube Destination Platform Adapter Implementation

Pillar 2 implements the Pillar 0 `DestinationPlatform` port protocol:

```python
class YouTubeDestinationAdapter:
    """Concrete DestinationPlatform adapter for YouTube Data API v3."""

    def __init__(self, channel_id: str) -> None:
        self._channel_id = channel_id

    def may_upload_now(self) -> bool:
        """Returns True if the channel token is valid and quota has >= 1600 units left."""
        budget = check_quota_budget(self._channel_id)
        return budget.can_upload_now

    def upload_video(self, payload: DestinationUploadInput) -> DestinationUploadResult:
        """Executes resumable chunked upload and thumbnail setting."""
        return execute_upload(self._channel_id, payload)
```

---

## 5. Cross-Pillar Access Rules

| Caller Module | Permitted APIs | Prohibited Access |
|---|---|---|
| `src.delivery` (Pillar 6) | `check_quota_budget()`, `execute_upload()`, `YouTubeDestinationAdapter` | Direct SQL access to `authorized_channel` or `quota_usage` |
| `src.pipelines` (Pillar 3)| `list_authorized_channels()`, `get_channel()` | Upload execution or client secret inspection |
| `src.jobs` (Pillar 4) | Indirectly through `src.delivery` | Direct imports of `src.destinations` |
| External HTTP / UI | `list_authorized_channels()`, `check_quota_budget()` | Plaintext token or secret exports (`INV-1`) |
