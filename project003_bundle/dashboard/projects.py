"""
project003 — YouTube Cloud-project rotation.

YouTube's upload quota (~1600 units / 10 000 daily) effectively caps each
Google Cloud project at ~6 uploads / day. To go beyond that we register
multiple OAuth clients (one per Google Cloud project) and rotate.

Picker rules (in order):
  1. Skip projects that are inactive.
  2. Skip projects whose `quota_resets_at` is still in the future.
  3. Skip projects that already hit their `daily_cap` today (UTC date).
  4. Among the remainder, pick the project with the FEWEST uploads today,
     ties broken by oldest `last_used_at` — i.e. round-robin.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

try:
    from dashboard.models import get_db
except ModuleNotFoundError:
    from models import get_db


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _today_utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _next_quota_reset_iso() -> str:
    """Return ISO-8601 UTC for YouTube's next daily quota reset.

    YouTube quota resets at midnight America/Los_Angeles (Pacific Time),
    which floats between 07:00 UTC (PDT) and 08:00 UTC (PST). Using a
    fixed 08:00 UTC was wrong half the year — we'd either release projects
    an hour early (= 403 quotaExceeded) or hold them for an hour past
    actual reset.
    """
    if ZoneInfo is not None:
        try:
            from datetime import timezone
            pt = ZoneInfo("America/Los_Angeles")
            now_pt = datetime.now(pt)
            tomorrow_pt = (now_pt + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            reset_utc = tomorrow_pt.astimezone(timezone.utc)
            return reset_utc.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            pass
    # Fallback (no tzdata): assume PST (UTC-8) -> 08:00 UTC.
    now = datetime.utcnow()
    reset = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= reset:
        reset = reset + timedelta(days=1)
    return reset.strftime("%Y-%m-%dT%H:%M:%S")


def _roll_counter_if_new_day(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """Reset uploads_today to 0 if counter_date != today."""
    today = _today_utc()
    if row["counter_date"] == today:
        return dict(row)
    conn.execute(
        "UPDATE youtube_projects SET uploads_today=0, counter_date=?, updated_at=? "
        "WHERE id=?",
        (today, _utcnow_iso(), row["id"]),
    )
    refreshed = conn.execute(
        "SELECT * FROM youtube_projects WHERE id=?", (row["id"],)
    ).fetchone()
    return dict(refreshed)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_projects(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Return all projects as dicts, with counters rolled to today."""
    own_conn = conn is None
    conn = conn or get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM youtube_projects ORDER BY id ASC"
        ).fetchall()
        return [_roll_counter_if_new_day(conn, r) for r in rows]
    finally:
        if own_conn:
            conn.close()


def add_project(label: str, client_id: str, client_secret: str,
                daily_cap: int = 6) -> int:
    """Insert a new project. Returns its id. Idempotent on client_id."""
    label = (label or "").strip() or f"Project {client_id[:12]}…"
    if not (client_id and client_secret):
        raise ValueError("client_id and client_secret are required")

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM youtube_projects WHERE client_id=?", (client_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE youtube_projects SET label=?, client_secret=?, "
                "daily_cap=?, active=1, updated_at=? WHERE id=?",
                (label, client_secret, daily_cap, _utcnow_iso(), existing["id"]),
            )
            return int(existing["id"])
        cur = conn.execute(
            "INSERT INTO youtube_projects (label, client_id, client_secret, "
            "daily_cap, counter_date) VALUES (?, ?, ?, ?, ?)",
            (label, client_id, client_secret, daily_cap, _today_utc()),
        )
        return int(cur.lastrowid)
    finally:
        conn.close()


def delete_project(project_id: int) -> None:
    conn = get_db()
    try:
        conn.execute("DELETE FROM youtube_projects WHERE id=?", (project_id,))
        conn.execute("UPDATE oauth_tokens SET project_id=NULL WHERE project_id=?",
                     (project_id,))
    finally:
        conn.close()


def set_active(project_id: int, active: bool) -> None:
    conn = get_db()
    try:
        conn.execute(
            "UPDATE youtube_projects SET active=?, updated_at=? WHERE id=?",
            (1 if active else 0, _utcnow_iso(), project_id),
        )
    finally:
        conn.close()


def get_project(project_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM youtube_projects WHERE id=?", (project_id,)
        ).fetchone()
        if not row:
            return None
        return _roll_counter_if_new_day(conn, row)
    finally:
        conn.close()


def pick_active_project() -> Optional[dict]:
    """Choose the next project to use for an upload.

    Returns a dict (project row) or None if no project is currently usable
    (all caps reached, or none configured).

    NOTE: This is the legacy GLOBAL picker — rotates across ALL active
    projects regardless of channel. Used as a fallback when a destination
    has no `youtube_channel_id` set. For multi-channel correctness, callers
    should prefer ``pick_active_project_for_channel(channel_id)`` so an
    upload destined for channel A doesn't get a token authorized for
    channel B.
    """
    return _pick_active_project_filtered(youtube_channel_id=None)


def pick_active_project_for_channel(youtube_channel_id: int) -> Optional[dict]:
    """Channel-scoped picker: rotate only among projects whose stored token
    is authorized for the given youtube_channels.id.

    Returns the project row dict (or None). The caller can then pass
    ``project_id`` to the credential loader, which already locates the
    correct token via oauth_tokens.project_id.
    """
    if not youtube_channel_id:
        return None
    return _pick_active_project_filtered(youtube_channel_id=int(youtube_channel_id))


def _pick_active_project_filtered(youtube_channel_id: Optional[int]) -> Optional[dict]:
    """Shared rotation logic for both global and channel-scoped pickers.

    Uses BEGIN EXCLUSIVE to atomically pick the best project AND reserve
    a slot (uploads_today += 1) so concurrent upload threads never pick
    the same project twice.
    """
    conn = get_db()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        try:
            today = _today_utc()
            now = _utcnow_iso()
            if youtube_channel_id is not None:
                rows = conn.execute(
                    """SELECT p.* FROM youtube_projects p
                         JOIN oauth_tokens t
                           ON t.project_id = p.id
                          AND t.platform   = 'youtube'
                        WHERE p.active = 1
                          AND t.youtube_channel_id = ?
                    """,
                    (int(youtube_channel_id),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM youtube_projects WHERE active=1"
                ).fetchall()
            if not rows:
                conn.execute("ROLLBACK")
                return None
            candidates: list[dict] = []
            for r in rows:
                p = dict(r)
                # Roll counter inline within the exclusive transaction.
                if p["counter_date"] != today:
                    conn.execute(
                        "UPDATE youtube_projects SET uploads_today=0, "
                        "counter_date=?, updated_at=? WHERE id=?",
                        (today, now, p["id"]),
                    )
                    p["uploads_today"] = 0
                    p["counter_date"] = today
                if p["quota_resets_at"] and p["quota_resets_at"] > now:
                    continue
                if int(p["uploads_today"]) >= int(p["daily_cap"]):
                    continue
                candidates.append(p)
            if not candidates:
                conn.execute("ROLLBACK")
                return None
            candidates.sort(key=lambda p: (int(p["uploads_today"]),
                                           p["last_used_at"] or ""))
            best = candidates[0]
            project_id = int(best["id"])
            # Reserve the slot atomically before any other picker can see it.
            conn.execute(
                "UPDATE youtube_projects SET uploads_today=uploads_today+1, "
                "last_used_at=?, updated_at=? WHERE id=?",
                (now, now, project_id),
            )
            best["uploads_today"] = int(best["uploads_today"]) + 1
            conn.execute("COMMIT")
            return best
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
    finally:
        conn.close()


def record_upload(project_id: int) -> None:
    """No-op: slot is now reserved atomically at pick time.

    Kept for backwards-compatibility so callers don't need updating.
    The counter is incremented inside _pick_active_project_filtered
    using a BEGIN EXCLUSIVE transaction, so calling this again would
    double-count. Safe to call — it does nothing.
    """
    return  # counter already bumped at pick time


def mark_quota_exceeded(project_id: int) -> str:
    """Mark this project as quota-exceeded until next reset (08:00 UTC)."""
    reset_at = _next_quota_reset_iso()
    if not project_id:
        return reset_at
    conn = get_db()
    try:
        conn.execute(
            "UPDATE youtube_projects SET quota_resets_at=?, "
            "uploads_today=daily_cap, updated_at=? WHERE id=?",
            (reset_at, _utcnow_iso(), project_id),
        )
    finally:
        conn.close()
    return reset_at


def project_for_token(token_row: sqlite3.Row | dict) -> Optional[dict]:
    """Return the project row that a given oauth_tokens row was issued for."""
    pid = token_row["project_id"] if "project_id" in token_row.keys() else None  # type: ignore[union-attr]
    if not pid:
        return None
    return get_project(int(pid))
