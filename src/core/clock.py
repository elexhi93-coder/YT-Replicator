from __future__ import annotations

"""
YT-Replicator — Pacific Time YouTube Quota Clock.

YouTube daily API quotas reset at midnight America/Los_Angeles (Pacific Time).
Pacific Time alternates between PST (UTC-8) and PDT (UTC-7).

Using a static 08:00 UTC boundary (as legacy did half the time) causes uploads
either to be released 1 hour too early (triggering 403 quotaExceeded) or delayed
1 hour past the actual reset.
"""

from datetime import date, datetime, time, timedelta, timezone
from dataclasses import dataclass
from zoneinfo import ZoneInfo

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class PacificTimeDTO:
    """Authoritative Pacific Time snapshot for quota boundaries (Pillar 7 §2).

    All quota math across the system reads these four fields; nobody computes
    their own Pacific midnight.
    """

    utc_now: datetime
    pacific_now: datetime
    pacific_date: date                   # Calendar date in America/Los_Angeles
    next_midnight_pacific_utc: datetime  # UTC moment of next 00:00:00 PT rollover


def now_utc() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def now_pacific() -> datetime:
    """Return the current timezone-aware Pacific datetime."""
    return datetime.now(PACIFIC_TZ)


def next_quota_reset_utc(from_time: datetime | None = None) -> datetime:
    """Return the next YouTube daily quota reset timestamp in timezone-aware UTC.

    Resets occur at exactly 00:00:00 (midnight) in America/Los_Angeles.
    """
    if from_time is None:
        from_time = now_utc()
    elif from_time.tzinfo is None:
        # Default naive datetime to UTC
        from_time = from_time.replace(tzinfo=timezone.utc)

    # Convert reference time to Pacific Time
    pacific_dt = from_time.astimezone(PACIFIC_TZ)

    # Midnight of the next calendar day in Pacific
    pacific_tomorrow_midnight = datetime.combine(
        pacific_dt.date() + timedelta(days=1),
        time.min,
        tzinfo=PACIFIC_TZ,
    )

    # Convert back to UTC
    return pacific_tomorrow_midnight.astimezone(timezone.utc)


def quota_day_string(dt: datetime | None = None) -> str:
    """Return the quota date identifier string (YYYY-MM-DD) based on Pacific Time.

    All uploads made during the same Pacific calendar day share the same quota window.
    """
    if dt is None:
        dt = now_utc()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    pacific_dt = dt.astimezone(PACIFIC_TZ)
    return pacific_dt.strftime("%Y-%m-%d")


def quota_day(now: datetime) -> date:
    """Return the Pacific calendar date that owns `now`'s quota usage (docs/04 §5).

    Naive datetimes are interpreted as UTC. This is the single canonical
    quota-day evaluator (INV-2): every quota query across the system derives
    its day boundary from this function.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(PACIFIC_TZ).date()


def get_pacific_time() -> "PacificTimeDTO":
    """Return the authoritative Pacific Time snapshot for quota calculations (INV-2).

    Contract: `docs/PILLARS/07.../03_INTERFACE_CONTRACT.md` §3.2.
    """
    utc_now = now_utc()
    pacific_now = utc_now.astimezone(PACIFIC_TZ)
    pacific_date = pacific_now.date()
    next_midnight_pacific = datetime.combine(
        pacific_date + timedelta(days=1),
        time.min,
        tzinfo=PACIFIC_TZ,
    )
    return PacificTimeDTO(
        utc_now=utc_now,
        pacific_now=pacific_now,
        pacific_date=pacific_date,
        next_midnight_pacific_utc=next_midnight_pacific.astimezone(timezone.utc),
    )


def get_pacific_date_string() -> str:
    """Return the current Pacific calendar date formatted as 'YYYY-MM-DD' (INV-2).

    Contract: `docs/PILLARS/07.../03_INTERFACE_CONTRACT.md` §3.2.
    """
    return get_pacific_time().pacific_date.strftime("%Y-%m-%d")
