"""
project003 — Sources & catalog scan helpers.

A "source" is a YouTube channel or playlist URL that the operator
wants to curate manually (separate from the cron-watched pipeline
channels). This module owns:

  * URL parsing / kind detection / external_id extraction
  * Flat-scan via yt-dlp `extract_flat=True` (cheap, single request)
  * Catalog upsert (new rows + last_seen_at refresh + unavailable marking)

Heavy hydration (description, view_count, tags, chapters) is intentionally
NOT in here yet — see `FEATURE_CATALOG_AND_BACKFILL.md` P6.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------

_ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "music.youtube.com", "youtube-nocookie.com",
}

_RE_UC_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_RE_PL_ID = re.compile(r"^(PL|UU|FL|RD|OL)[A-Za-z0-9_-]{10,}$")
_RE_VIDEO = re.compile(r"^[A-Za-z0-9_-]{11}$")


class SourceUrlError(ValueError):
    """Raised when a URL can't be turned into a (kind, external_id, canonical_url)."""


def parse_source_url(raw: str) -> Tuple[str, Optional[str], str]:
    """Return ``(kind, external_id, canonical_url)`` for a YouTube source URL.

    ``kind`` is ``'channel'`` or ``'playlist'``. ``external_id`` may be ``None``
    when the URL uses an ``@handle`` form — yt-dlp will resolve it later and
    we'll patch the row.

    Raises :class:`SourceUrlError` for non-YouTube hosts or unrecognised paths.
    This is the SSRF guardrail; **all** source-creation code paths must call
    this.
    """
    if not raw or not isinstance(raw, str):
        raise SourceUrlError("URL is required")
    raw = raw.strip()
    try:
        u = urlparse(raw)
    except Exception as exc:                          # noqa: BLE001
        raise SourceUrlError(f"Could not parse URL: {exc}") from exc
    if u.scheme not in ("http", "https"):
        raise SourceUrlError("URL must be http(s)")
    host = (u.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise SourceUrlError(f"Host not allowed: {host or '(empty)'}")

    qs = parse_qs(u.query or "")
    path = u.path or "/"

    # Playlist (?list=...)
    list_id = (qs.get("list") or [None])[0]
    if list_id and _RE_PL_ID.match(list_id):
        return ("playlist", list_id, f"https://www.youtube.com/playlist?list={list_id}")

    # /channel/UC...
    m = re.match(r"^/channel/(UC[A-Za-z0-9_-]{22})/?", path)
    if m:
        cid = m.group(1)
        return ("channel", cid, f"https://www.youtube.com/channel/{cid}/videos")

    # /@handle  /@handle/videos
    m = re.match(r"^/(@[A-Za-z0-9_.\-]+)(?:/.*)?$", path)
    if m:
        handle = m.group(1)
        # external_id unknown until yt-dlp resolves it
        return ("channel", None, f"https://www.youtube.com/{handle}/videos")

    # /c/customname or /user/legacyname
    m = re.match(r"^/(c|user)/([A-Za-z0-9_.\-]+)/?", path)
    if m:
        return ("channel", None, raw)

    raise SourceUrlError(
        "URL must point to a YouTube channel (/channel/UC…, /@handle, /c/…, /user/…) "
        "or playlist (?list=PL…)"
    )


# ---------------------------------------------------------------------------
# Flat scan
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _yt_date_to_iso(raw) -> Optional[str]:
    """Convert yt-dlp's ``YYYYMMDD`` upload_date to ``YYYY-MM-DD``."""
    if not raw:
        return None
    s = str(raw)
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return None


class ScanResult(dict):
    """Convenience dict for scan summary."""


def scan_source(conn, source_id: int) -> ScanResult:
    """Run a flat scan against the source URL and upsert ``catalog_videos``.

    Returns a ``ScanResult`` with keys: ``new``, ``updated``, ``unavailable``,
    ``total``. On error, sets ``sources.last_scan_error`` and re-raises.
    """
    import yt_dlp                                       # lazy import

    row = conn.execute(
        "SELECT id, url, kind FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if not row:
        raise LookupError(f"source {source_id} not found")

    started_at = _utcnow()
    opts = {
        "extract_flat": "in_playlist",
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(row["url"], download=False)
    except Exception as exc:                            # noqa: BLE001
        conn.execute(
            "UPDATE sources SET last_scanned_at = ?, last_scan_error = ?, "
            "updated_at = ? WHERE id = ?",
            (started_at, str(exc)[:500], started_at, source_id),
        )
        raise

    entries = list(info.get("entries") or [])
    seen_ids: list[str] = []
    new_video_ids: list[str] = []
    new_count = 0
    updated_count = 0

    # Batched existence check: pull all IDs from this scan once, then look up
    # which ones already exist in catalog_videos for this source in a single
    # query (avoids N+1 per-entry SELECT during the loop below).
    _scan_vids = [
        str(e.get("id")) for e in entries
        if e and e.get("id") and _RE_VIDEO.match(str(e.get("id")))
    ]
    existing_ids: set[str] = set()
    if _scan_vids:
        # SQLite parameter cap is 999 — chunk if needed.
        for i in range(0, len(_scan_vids), 800):
            chunk = _scan_vids[i:i + 800]
            placeholders = ",".join(["?"] * len(chunk))
            for row_ex in conn.execute(
                f"SELECT video_id FROM catalog_videos "
                f"WHERE source_id = ? AND video_id IN ({placeholders})",
                (source_id, *chunk),
            ):
                existing_ids.add(row_ex["video_id"])

    # Resolve canonical external_id + name from the response
    resolved_ext_id = (
        info.get("channel_id")
        or info.get("uploader_id")
        or info.get("id")
        or ""
    )
    resolved_name = (
        info.get("channel")
        or info.get("uploader")
        or info.get("title")
        or row["url"]
    )

    for ent in entries:
        if not ent:
            continue
        vid = ent.get("id")
        if not vid or not _RE_VIDEO.match(str(vid)):
            continue
        seen_ids.append(vid)

        title = ent.get("title") or ""
        duration = ent.get("duration")
        try:
            duration_sec = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_sec = None
        upload_date = _yt_date_to_iso(ent.get("upload_date"))
        # Some channel/playlist responses surface a unix timestamp instead
        if not upload_date:
            ts = ent.get("timestamp") or ent.get("release_timestamp")
            if ts:
                try:
                    upload_date = datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
                except (TypeError, ValueError, OSError):
                    upload_date = None
        live_status = ent.get("live_status") or "not_live"
        thumb = ent.get("thumbnail")
        if not thumb:
            thumbs = ent.get("thumbnails") or []
            if thumbs:
                thumb = thumbs[-1].get("url")
        # view_count is sometimes present in flat responses (newer layouts)
        vc = ent.get("view_count")
        try:
            view_count = int(vc) if vc is not None else None
        except (TypeError, ValueError):
            view_count = None

        existing = vid in existing_ids
        if existing:
            conn.execute(
                """UPDATE catalog_videos
                   SET title = ?, duration_sec = COALESCE(?, duration_sec),
                       upload_date = COALESCE(?, upload_date),
                       live_status = COALESCE(?, live_status),
                       thumbnail_url = COALESCE(?, thumbnail_url),
                       view_count = COALESCE(?, view_count),
                       last_seen_at = ?, unavailable_at = NULL
                   WHERE source_id = ? AND video_id = ?""",
                (title, duration_sec, upload_date, live_status, thumb,
                 view_count, _utcnow(), source_id, vid),
            )
            updated_count += 1
        else:
            conn.execute(
                """INSERT INTO catalog_videos
                       (source_id, video_id, title, duration_sec, upload_date,
                        live_status, thumbnail_url, view_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (source_id, vid, title, duration_sec, upload_date,
                 live_status, thumb, view_count),
            )
            new_count += 1
            new_video_ids.append(vid)

    # Mark rows missing from this scan as unavailable
    unavailable_count = 0
    if seen_ids:
        placeholders = ",".join(["?"] * len(seen_ids))
        cur = conn.execute(
            f"""UPDATE catalog_videos
                SET unavailable_at = ?
                WHERE source_id = ?
                  AND unavailable_at IS NULL
                  AND video_id NOT IN ({placeholders})""",
            (_utcnow(), source_id, *seen_ids),
        )
        unavailable_count = cur.rowcount or 0

    # Patch source row with resolved metadata
    conn.execute(
        """UPDATE sources
           SET last_scanned_at = ?, last_scan_error = '',
               total_known = ?, name = COALESCE(NULLIF(name, ''), ?),
               external_id = COALESCE(NULLIF(external_id, ''), NULLIF(?, '')),
               updated_at = ?
           WHERE id = ?""",
        (started_at, len(seen_ids), resolved_name,
         resolved_ext_id, started_at, source_id),
    )

    return ScanResult(
        new=new_count,
        updated=updated_count,
        unavailable=unavailable_count,
        total=len(seen_ids),
        new_video_ids=new_video_ids,
    )


# ---------------------------------------------------------------------------
# Per-video hydration (date / view_count / like_count / description / tags)
# ---------------------------------------------------------------------------

def hydrate_catalog(conn, source_id: int, limit: int = 25) -> dict:
    """Fetch full per-video metadata for the next ``limit`` un-hydrated rows.

    Cheap fields (title, duration, thumbnail, live_status) are filled by
    :func:`scan_source`; this fills upload_date, view_count, like_count,
    description, tags, age_limit, chapters — fields the flat scan does not
    return for channel /videos pages.

    Synchronous; one yt-dlp call per video. ~0.5–1.5 s each.
    """
    import yt_dlp                                       # lazy import

    rows = conn.execute(
        """SELECT id, video_id FROM catalog_videos
            WHERE source_id = ?
              AND (hydrated_at IS NULL OR (view_count IS NULL AND upload_date IS NULL))
              AND unavailable_at IS NULL
            ORDER BY id
            LIMIT ?""",
        (source_id, max(1, min(int(limit), 200))),
    ).fetchall()
    if not rows:
        remaining = 0
        return {"hydrated": 0, "failed": 0, "remaining": remaining}

    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "socket_timeout": 30,
        # Cheaper: skip comments, formats heavy work
        "extract_flat": False,
        "no_color": True,
    }

    hydrated = 0
    failed = 0
    with yt_dlp.YoutubeDL(opts) as ydl:
        for r in rows:
            vid = r["video_id"]
            try:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={vid}",
                    download=False,
                )
            except Exception:                           # noqa: BLE001
                info = None
            if not info:
                # mark as attempted to avoid infinite retries this batch
                conn.execute(
                    "UPDATE catalog_videos SET hydrated_at = ? WHERE id = ?",
                    (_utcnow(), r["id"]),
                )
                failed += 1
                continue

            upload_date = _yt_date_to_iso(info.get("upload_date"))
            if not upload_date:
                ts = info.get("timestamp") or info.get("release_timestamp")
                if ts:
                    try:
                        upload_date = datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
                    except (TypeError, ValueError, OSError):
                        upload_date = None

            def _i(v):
                try:
                    return int(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            view_count  = _i(info.get("view_count"))
            like_count  = _i(info.get("like_count"))
            age_limit   = _i(info.get("age_limit"))
            duration    = _i(info.get("duration"))
            description = info.get("description") or ""
            tags        = info.get("tags") or []
            chapters    = info.get("chapters") or []
            thumb = info.get("thumbnail")
            if not thumb:
                thumbs = info.get("thumbnails") or []
                if thumbs:
                    thumb = thumbs[-1].get("url")

            import json as _json
            conn.execute(
                """UPDATE catalog_videos
                      SET upload_date   = COALESCE(?, upload_date),
                          view_count    = COALESCE(?, view_count),
                          like_count    = COALESCE(?, like_count),
                          age_limit     = COALESCE(?, age_limit),
                          duration_sec  = COALESCE(?, duration_sec),
                          description   = ?,
                          tags_json     = ?,
                          chapters_json = ?,
                          thumbnail_url = COALESCE(?, thumbnail_url),
                          hydrated_at   = ?
                    WHERE id = ?""",
                (upload_date, view_count, like_count, age_limit, duration,
                 description, _json.dumps(tags), _json.dumps(chapters),
                 thumb, _utcnow(), r["id"]),
            )
            hydrated += 1

    remaining = conn.execute(
        """SELECT COUNT(*) FROM catalog_videos
            WHERE source_id = ?
              AND (hydrated_at IS NULL OR (view_count IS NULL AND upload_date IS NULL))
              AND unavailable_at IS NULL""",
        (source_id,),
    ).fetchone()[0]

    return {"hydrated": hydrated, "failed": failed, "remaining": remaining}
