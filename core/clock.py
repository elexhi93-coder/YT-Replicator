from __future__ import annotations

"""
YT-Replicator — Pacific Time YouTube Quota Clock.

YouTube daily API quotas reset at midnight America/Los_Angeles (Pacific Time).
Pacific Time alternates between PST (UTC-8) and PDT (UTC-7).

Using a static 08:00 UTC boundary (as legacy did half the time) causes uploads
either to be released 1 hour too early (triggering 403 quotaExceeded) or delayed
1 hour past the actual reset.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


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
