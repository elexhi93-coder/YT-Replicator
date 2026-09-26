"""
project003 — YouTube upload-target channel registry.

A YouTube *channel* (UCxxx) is the destination of an upload. It is owned by
exactly one Google account (Brand Account semantics: one Gmail can own
several channels). One channel may be served by many youtube_projects rows
(quota rotation pool). One project = one channel by convention (PR1):
re-authorising a project against a different channel REPLACES the prior
binding rather than adding a second token row.

This module is small and tool-only: schema lives in models.py.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

try:
    from dashboard.models import get_db
except ModuleNotFoundError:
    from models import get_db


def _utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def upsert_channel(
    *,
    channel_id: str,
    title: str = "",
    thumbnail_url: str = "",
    owner_email: str = "",
    owner_display_name: str = "",
) -> int:
    """Insert or update by channel_id (UCxxx). Returns the row id."""
    if not channel_id:
        raise ValueError("channel_id (UCxxx) is required")
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM youtube_channels WHERE channel_id=?",
            (channel_id,),
        ).fetchone()
        now = _utcnow_iso()
        if existing:
            conn.execute(
                """UPDATE youtube_channels SET
                       title=COALESCE(NULLIF(?,''), title),
                       thumbnail_url=COALESCE(NULLIF(?,''), thumbnail_url),
                       owner_email=COALESCE(NULLIF(?,''), owner_email),
                       owner_display_name=COALESCE(NULLIF(?,''), owner_display_name),
                       updated_at=?
                   WHERE id=?""",
                (title, thumbnail_url, owner_email, owner_display_name,
                 now, existing["id"]),
            )
            return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO youtube_channels
                   (channel_id, title, thumbnail_url, owner_email,
                    owner_display_name)
               VALUES (?, ?, ?, ?, ?)""",
            (channel_id, title, thumbnail_url, owner_email,
             owner_display_name),
        )
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def get_channel(youtube_channel_id: int) -> Optional[dict]:
    if not youtube_channel_id:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM youtube_channels WHERE id=?",
            (int(youtube_channel_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_channels() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM youtube_channels ORDER BY title COLLATE NOCASE"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Detection (network call) — best-effort, callers handle exceptions
# ---------------------------------------------------------------------------

def detect_from_credentials(creds) -> dict:
    """Probe Google for the channel + owner identity behind a Credentials.

    Returns a dict with keys: channel_id, title, thumbnail_url,
    owner_email, owner_display_name. Any field may be empty on failure.
    Total cost: 1 quota unit (channels.list) + free (userinfo).
    """
    out = {
        "channel_id": "", "title": "", "thumbnail_url": "",
        "owner_email": "", "owner_display_name": "",
    }
    try:
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        ch = yt.channels().list(part="snippet", mine=True).execute()
        items = ch.get("items", [])
        if items:
            it = items[0]
            out["channel_id"] = it.get("id", "") or ""
            sn = it.get("snippet", {}) or {}
            out["title"] = sn.get("title", "") or ""
            thumbs = sn.get("thumbnails", {}) or {}
            for size in ("medium", "default", "high"):
                if thumbs.get(size, {}).get("url"):
                    out["thumbnail_url"] = thumbs[size]["url"]
                    break
    except Exception:
        pass
    try:
        from googleapiclient.discovery import build
        oa = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = oa.userinfo().get().execute()
        out["owner_email"] = info.get("email", "") or ""
        out["owner_display_name"] = info.get("name", "") or ""
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Bindings (link tokens / projects to a channel row)
# ---------------------------------------------------------------------------

def bind_token_and_project(
    *, token_id: int, project_id: Optional[int],
    youtube_channel_id: int,
) -> None:
    """Write the youtube_channel_id FK on a token row and (optionally) on
    its owning project row."""
    if not (token_id and youtube_channel_id):
        return
    conn = get_db()
    try:
        conn.execute(
            "UPDATE oauth_tokens SET youtube_channel_id=?, updated_at=? "
            "WHERE id=?",
            (int(youtube_channel_id), _utcnow_iso(), int(token_id)),
        )
        if project_id:
            conn.execute(
                "UPDATE youtube_projects SET youtube_channel_id=?, updated_at=? "
                "WHERE id=?",
                (int(youtube_channel_id), _utcnow_iso(), int(project_id)),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# One-shot startup backfill
# ---------------------------------------------------------------------------

def backfill_unbound_tokens(verbose: bool = False) -> dict:
    """For every oauth_tokens row with platform='youtube' and a missing
    youtube_channel_id, refresh creds, probe channels.list+userinfo, and
    write the FK back.

    Safe to call repeatedly. Skips rows that already have a binding.
    Network-bound, so should be called from a background thread at startup.
    Returns a stats dict.
    """
    stats = {"considered": 0, "bound": 0, "failed": 0, "skipped": 0}
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, project_id, youtube_channel_id FROM oauth_tokens "
            "WHERE platform='youtube'"
        ).fetchall()
    finally:
        conn.close()
    # Lazy import to avoid circular at module load.
    try:
        from dashboard.uploader import _load_youtube_credentials  # type: ignore
    except ModuleNotFoundError:
        try:
            from uploader import _load_youtube_credentials  # type: ignore
        except ModuleNotFoundError:
            return stats
    for r in rows:
        stats["considered"] += 1
        if r["youtube_channel_id"]:
            stats["skipped"] += 1
            continue
        try:
            creds = _load_youtube_credentials(
                project_id=r["project_id"] if r["project_id"] else None
            )
            info = detect_from_credentials(creds)
            if not info["channel_id"]:
                stats["failed"] += 1
                if verbose:
                    print(f"[yt-channels] token id={r['id']} — no channel "
                          f"returned by Google", flush=True)
                continue
            ch_id = upsert_channel(**info)
            bind_token_and_project(
                token_id=r["id"],
                project_id=r["project_id"],
                youtube_channel_id=ch_id,
            )
            stats["bound"] += 1
            if verbose:
                print(f"[yt-channels] token id={r['id']} -> channel "
                      f"'{info['title']}' ({info['channel_id']})",
                      flush=True)
        except Exception as e:
            stats["failed"] += 1
            if verbose:
                print(f"[yt-channels] token id={r['id']} backfill failed: {e}",
                      flush=True)
    return stats
