"""
media.retention — the retention evaluator and sweeper (U12, INV-10).

`evaluate()` is a **pure function**: it reads an asset and a fact snapshot and
returns a decision. It performs no I/O, touches no sibling module, and deletes
nothing. That is the whole point of INV-10 — one owner, one order, testable
without a filesystem — and it is why the facts arrive as a value
(`RetentionFacts`) rather than being fetched inside the decision.

**The gate order is not interchangeable** (docs/05 §8), and each step below
names the gate it implements:

1. `keep` short-circuits before any other question is asked (D1).
2. INV-2 — every enabled destination terminal. Deletion is *forbidden* while
   anything is in flight, by any mode, including the backstop.
3. The pin holds (D4, F-10).
4. The last local copy is protected unless the destination copy is confirmed
   present (D3).
5. The mode's own condition.
6. The floors: min-age, then the max-age backstop (D6).

Then the two phases, always separated: `sweep()` only *schedules* (writes
`delete_after` and a `delete_scheduled` event); `execute_due()` is the sole
place a file is unlinked. That is what makes a decision cancellable in between
and auditable afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from core.api import (
    APP_SETTING_DEFAULTS,
    RetentionFacts,
    get_retention_oracle,
    now_utc,
)
from media.models import MediaAsset, MediaEvent

__all__ = [
    "Decision",
    "SweepReport",
    "cancel",
    "evaluate",
    "execute_due",
    "pin",
    "sweep",
    "unpin",
]

#: docs/05 §8 G7 defines a min-age floor but no default value anywhere in the
#: specification, so it ships disabled (0) rather than invented. The gate is
#: implemented and tested; an operator sets the number.
DEFAULT_MIN_AGE_HOURS = 0

#: Scheduling happens in the future so a decision can be cancelled before it
#: fires. Zero would make "two-phase" meaningless.
DEFAULT_GRACE_MINUTES = 60


@dataclass(frozen=True)
class Decision:
    """The evaluator's verdict. `delete=False` always carries a `reason`."""

    delete: bool
    reason: str
    #: When the executor becomes allowed to delete. Set even for
    #: `delete=False` when the mode condition already holds and only a floor
    #: is outstanding — the flow's Z5 branch, "NO, but delete_after is set".
    delete_after: datetime | None = None
    size_bytes: int = 0

    def __bool__(self) -> bool:
        return self.delete


@dataclass(frozen=True)
class SweepReport:
    """What a sweep would do, or did."""

    dry_run: bool
    scheduled: tuple[int, ...]
    skipped: tuple[tuple[int, str], ...]
    bytes_considered: int
    bytes_scheduled: int

    @property
    def candidate_count(self) -> int:
        return len(self.scheduled)


def evaluate(
    asset: MediaAsset,
    facts: RetentionFacts,
    *,
    other_local_copies: bool = False,
    now: datetime | None = None,
    min_age_hours: int = DEFAULT_MIN_AGE_HOURS,
    backstop_days: int | None = None,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
) -> Decision:
    """Decide one asset. Pure: no I/O, no writes, no sibling imports.

    `other_local_copies` is passed in rather than queried, because a query here
    would make this function impure and untestable without a database — and
    because the count is `media`'s own data, not one of the foreign facts the
    oracle supplies. It defaults to `False`, the conservative reading: assume
    this is the last copy unless the caller says otherwise.

    Every early return names the gate that stopped it, because "why was this
    file kept?" is the question the operator actually has — and a bare `False`
    is how the legacy answered it.
    """
    now = now or now_utc()
    if backstop_days is None:
        # `retention_backstop_days` is a documented app_setting (docs/03 §11),
        # not a `core.Settings` field; the `app_setting` table arrives with the
        # Settings page in U22, so the documented default is authoritative now.
        backstop_days = APP_SETTING_DEFAULTS.get("retention_backstop_days")

    # G0 — `keep` short-circuits. No queries are run and no gate is consulted,
    # which is what makes `keep` genuinely free for a small source (D1).
    if facts.mode == "keep":
        return Decision(False, "mode=keep")

    # An asset nobody can attribute to a policy is never auto-deleted.
    if facts.unavailable_reason:
        return Decision(False, f"facts unavailable: {facts.unavailable_reason}")

    # INV-2 — the hard gate. A destination that is still queued, uploading or
    # not yet attempted means the local file is the only copy that will ever
    # satisfy it. No mode, and not the backstop, may override this.
    if not facts.all_destinations_terminal:
        return Decision(False, "destinations not terminal (INV-2)")

    # D4 / F-10 — an explicit pin outranks every policy below it.
    if asset.pinned_until is not None and asset.pinned_until > now:
        return Decision(False, f"pinned until {asset.pinned_until.isoformat()}")

    # D3 — the last surviving local copy. Deleting it while the destination
    # copy is merely unproven trades a certainty (we have the file) for an
    # assumption (the platform still has it).
    if not other_local_copies and not facts.destination_copy_present:
        return Decision(False, "last local copy, destination copy unconfirmed (D3)")

    # Floors apply to the mode's verdict, never instead of the gates above.
    floor = _min_age_passed(asset, now, min_age_hours)
    backstop = _backstop_due(asset, now, backstop_days)
    if facts.mode == "immediate":
        due, why = True, "mode=immediate"
    elif facts.mode == "after_n_jobs":
        # D5: fewer than N newer completed jobs *of the same pipeline*.
        due = facts.newer_completed_jobs < facts.retention_n
        why = f"{facts.newer_completed_jobs} newer completed jobs < N={facts.retention_n}"
    elif facts.mode == "after_hours":
        if facts.uploaded_at is None:
            return Decision(False, "mode=after_hours but nothing has been uploaded")
        age = now - facts.uploaded_at
        due = age >= timedelta(hours=facts.retention_hours)
        why = f"uploaded {age} ago (>= {facts.retention_hours}h)"
    else:
        return Decision(False, f"unknown retention mode {facts.mode!r}")

    # D6: the backstop is a condition of its own, not a footnote on the mode.
    # "Otherwise a stalled pipeline pins disk forever" — so when the mode
    # condition is unmet but the backstop has expired, the backstop wins. It
    # still cannot reach past INV-2, the pin or the last-copy gate, because
    # those returned above.
    due = due or backstop is not None

    if not due:
        return Decision(False, f"mode condition not met: {why}")

    # `is not None`, not a truth test: the helper returns `None` to mean "the
    # floor is satisfied", and `None` is falsy — a truth test here would send
    # every satisfied floor down the "still waiting" branch.
    if _min_age_passed(asset, now, min_age_hours) is not None:
        # Z5 — "NO, but delete_after is set": the policy has decided; only the
        # floor is outstanding, and the decision is recorded so it is visible
        # before it fires.
        return Decision(
            False,
            f"waiting on min-age floor: {floor}",
            delete_after=now + timedelta(minutes=grace_minutes),
            size_bytes=asset.size_bytes,
        )

    return Decision(
        True,
        f"backstop (D6): {backstop}" if backstop else why,
        delete_after=now + timedelta(minutes=grace_minutes),
        size_bytes=asset.size_bytes,
    )


def _has_other_local_copy(asset: MediaAsset) -> bool:
    """Is another on-disk copy of this video in the same workspace?

    `materialization_no` exists so re-downloads are honest, so a second copy is
    a real thing — and while it exists, this one is not the last.
    """
    return (
        MediaAsset.objects.filter(
            workspace_id=asset.workspace_id,
            source_video_id=asset.source_video_id,
            state=MediaAsset.STATE_ON_DISK,
        )
        .exclude(pk=asset.pk)
        .exists()
    )


def _min_age_passed(asset, now, min_age_hours) -> str | None:
    """`None` when the floor is satisfied, else a human explanation of the wait."""
    if min_age_hours <= 0:
        return None
    reference = asset.downloaded_at or asset.created_at
    if reference is None:
        return "asset has no download timestamp"
    remaining = reference + timedelta(hours=min_age_hours) - now
    if remaining > timedelta(0):
        return f"{int(remaining.total_seconds() // 60)} min remaining"
    return None


def _backstop_due(asset, now, backstop_days) -> str | None:
    """D6: the hard ceiling. A stalled pipeline must not pin disk forever.

    This is the one condition that can *add* a deletion the mode did not ask
    for — but only after every safety gate above has already passed.
    """
    if not backstop_days:
        return None
    reference = asset.downloaded_at or asset.created_at
    if reference is None:
        return None
    age_days = (now - reference).days
    if age_days >= backstop_days:
        return f"{age_days}d old >= {backstop_days}d backstop"
    return None


def sweep(
    workspace,
    *,
    dry_run: bool = True,
    actor: str = "system",
    now: datetime | None = None,
    min_age_hours: int = DEFAULT_MIN_AGE_HOURS,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
) -> SweepReport:
    """Phase one: decide, and (unless dry-run) *schedule*.

    This function never deletes. It writes `delete_after` and a
    `delete_scheduled` event, which is what makes a sweep cancellable before it
    fires and reviewable afterwards. `dry_run=True` is the default, so an
    accidental call with no arguments cannot destroy anything (INV-10).
    """
    now = now or now_utc()
    backstop_days = APP_SETTING_DEFAULTS.get("retention_backstop_days")
    oracle = get_retention_oracle()
    scheduled: list[int] = []
    skipped: list[tuple[int, str]] = []
    considered = 0
    bytes_scheduled = 0

    for asset in MediaAsset.objects.filter(
        workspace=workspace, state=MediaAsset.STATE_ON_DISK
    ).order_by("id"):
        considered += asset.size_bytes
        facts = oracle.facts_for(workspace.pk, asset.source_video_id, asset.job_id)
        decision = evaluate(
            asset,
            facts,
            other_local_copies=_has_other_local_copy(asset),
            now=now,
            min_age_hours=min_age_hours,
            backstop_days=backstop_days,
            grace_minutes=grace_minutes,
        )
        if decision.delete_after is None:
            skipped.append((asset.pk, decision.reason))
            continue
        scheduled.append(asset.pk)
        bytes_scheduled += asset.size_bytes
        if not dry_run:
            asset.delete_after = decision.delete_after
            asset.save(update_fields=["delete_after", "updated_at"])
            _event(
                asset,
                "delete_scheduled",
                reason=decision.reason,
                bytes=asset.size_bytes,
                actor=actor,
            )

    return SweepReport(
        dry_run=dry_run,
        scheduled=tuple(scheduled),
        skipped=tuple(skipped),
        bytes_considered=considered,
        bytes_scheduled=bytes_scheduled,
    )


def execute_due(
    workspace,
    *,
    now: datetime | None = None,
    actor: str = "system",
    dry_run: bool = False,
) -> dict:
    """Phase two: the *only* place a retention deletion happens.

    Reads the `media_asset_due_idx` index — assets whose `delete_after` has
    arrived. The pin is re-checked here as well as in `evaluate()`: a file
    pinned between the sweep and the executor must survive, and this is the
    last moment at which that is knowable.
    """
    now = now or now_utc()
    deleted = 0
    bytes_freed = 0
    for asset in MediaAsset.objects.filter(
        workspace=workspace,
        state=MediaAsset.STATE_ON_DISK,
        delete_after__lte=now,
    ).order_by("id"):
        if asset.pinned_until is not None and asset.pinned_until > now:
            # Pinned after the sweep. Recorded, released, kept.
            asset.delete_after = None
            asset.save(update_fields=["delete_after", "updated_at"])
            _event(
                asset,
                "delete_skipped",
                reason="pinned after the sweep; schedule released",
                actor=actor,
            )
            continue
        if dry_run:
            deleted += 1
            bytes_freed += asset.size_bytes
            continue
        path = Path(asset.absolute_path())
        size = asset.size_bytes
        # The file goes first; the row is then marked, so a crash in between
        # leaves `on_disk` with a missing file — which `hygiene()` reclaims —
        # rather than `deleted` with the bytes still on disk.
        path.unlink(missing_ok=True)
        asset.state = MediaAsset.STATE_DELETED
        asset.deleted_at = now
        asset.delete_after = None
        asset.delete_reason = "retention"
        asset.save(
            update_fields=[
                "state",
                "deleted_at",
                "delete_after",
                "delete_reason",
                "updated_at",
            ]
        )
        _event(asset, "deleted", reason="retention", bytes=size, actor=actor)
        deleted += 1
        bytes_freed += size
    return {"deleted": deleted, "bytes_freed": bytes_freed, "dry_run": dry_run}


def cancel(
    asset: MediaAsset, *, actor: str = "system", reason: str = ""
) -> MediaAsset:
    """Release a scheduled deletion before it fires.

    Cancellability is the reason the two phases exist; a sweep that could not
    be undone would make `dry_run` the only safe way to run one.
    """
    asset.delete_after = None
    asset.save(update_fields=["delete_after", "updated_at"])
    _event(asset, "delete_skipped", reason=reason or "cancelled", actor=actor)
    return asset


def pin(
    asset: MediaAsset,
    *,
    until: datetime | None = None,
    reason: str = "",
    actor: str = "system",
) -> MediaAsset:
    """Protect an asset from retention until `until` (forever when `None`)."""
    asset.pinned_until = until
    asset.pinned_reason = reason
    asset.save(update_fields=["pinned_until", "pinned_reason", "updated_at"])
    _event(asset, "pinned", reason=reason, actor=actor)
    return asset


def unpin(asset: MediaAsset, *, actor: str = "system") -> MediaAsset:
    """Release a pin. Only an explicit release does — never a sweep (D4)."""
    asset.pinned_until = None
    asset.pinned_reason = ""
    asset.save(update_fields=["pinned_until", "pinned_reason", "updated_at"])
    _event(asset, "unpinned", actor=actor)
    return asset


def _event(asset, kind, *, reason="", bytes=0, actor="system") -> None:
    MediaEvent.objects.create(
        workspace_id=asset.workspace_id,
        media_asset=asset,
        source_video_id=asset.source_video_id,
        event=kind,
        reason=reason,
        bytes=bytes,
        actor=actor,
    )
