"""`sources.dto` — the frozen result types this module returns (Pillar 0 R4).

`SourceItem` and `SourceItemDetail` are *not* here: they belong to Pillar 0
and arrive through `core.api`, so re-declaring them would be a second source
of truth for the same shape (docs/03 §1).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanOutcome:
    """What a scan did, counted. Frozen because it crosses a boundary (INV-12)."""

    source_id: int
    discovered: int
    created: int
    updated: int
    # Videos seen previously but absent from this scan are marked
    # `availability='unavailable'`, never deleted (docs/03 §5, F-48).
    marked_unavailable: int
    # Non-fatal per-item skips (private/removed mid-scan); the scan completes.
    skipped: int


@dataclass(frozen=True)
class HydrateOutcome:
    """Counts for a hydration batch. Frozen: it crosses a boundary (INV-12)."""

    requested: int
    hydrated: int
    # Items the platform no longer serves: availability updated, not deleted.
    unavailable: int
    # Items skipped because the batch already carried hydrated rows.
    skipped: int


__all__ = ["HydrateOutcome", "ScanOutcome"]
