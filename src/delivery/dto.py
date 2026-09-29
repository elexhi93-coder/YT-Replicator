"""`delivery.dto` — the frozen results this module returns (Pillar 0 R4).

`ReconcileReport` exists because "is our ledger true?" is a question with four
answers and no single yes/no, and collapsing them into a boolean is how the
legacy ended up unable to explain its own history. The four buckets are named
in docs/05 §reconcile and are the unit's headline deliverable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryResult:
    """What one `deliver()` call did. Frozen because it crosses a boundary."""

    delivery_id: int
    attempt_no: int
    status: str                       # 'uploaded' | 'failed' | 'removed'
    destination_video_id: str
    destination_url: str
    provenance_marker: str


@dataclass(frozen=True)
class ReconcileReport:
    """The four outcomes, counted and itemised (docs/05 §reconcile).

    * `claimed_ok` — we uploaded it, the marker matches, the video is there.
    * `unclaimed_present` — on the channel, no delivery record. Never adopted
      automatically (INV-8); surfaced for review.
    * `missing_expected` — our ledger says uploaded, the channel no longer shows
      it. Flagged, *not* re-uploaded: the operator may have deleted it
      deliberately (copyright, duplicate).
    * `marker_mismatch` — a marker points at a delivery we have no record of.
    """

    destination_id: int
    claimed_ok: tuple[str, ...]
    unclaimed_present: tuple[str, ...]
    missing_expected: tuple[str, ...]
    marker_mismatch: tuple[str, ...]

    @property
    def needs_review(self) -> int:
        """How many rows a human has to look at."""
        return (
            len(self.unclaimed_present)
            + len(self.missing_expected)
            + len(self.marker_mismatch)
        )

    @property
    def is_clean(self) -> bool:
        return self.needs_review == 0


__all__ = ["DeliveryResult", "ReconcileReport"]