#!/usr/bin/env python3
"""
project003 — Headless Channel Watcher (SQLite edition)
======================================================

Reads channels from the SQLite database (table: `channels`), downloads new
videos via yt-dlp, records each download as `videos` + `jobs` rows, and fires
a webhook to n8n for every (job × destination) pair.

Two operating modes (per channel, stored in `channels.mode`):

  BACKFILL — process the channel's full history oldest-first, up to the
             channel's daily_limit per day. Switches to MONITOR when the
             backfill_queue is empty.

  MONITOR  — every CHECK_INTERVAL minutes, fetch the latest entries and
             download anything not already in the `videos` table.

CLI:
  python headless_watcher.py                 # daemon: forever loop
  python headless_watcher.py --once          # single cycle, then exit
  python headless_watcher.py --dry-run       # inspect-only (no downloads, no webhooks)
  python headless_watcher.py --channel <id>  # only process the given channel.id

Environment variables:
  DB_PATH              SQLite path        (default: /data/app.db)
  DOWNLOAD_DIR         Output directory   (default: /downloads)
  N8N_WEBHOOK_URL      Fallback webhook   (used when a channel's pipeline has no destinations)
  CHECK_INTERVAL       Minutes between monitor cycles  (default: 15)
  DAILY_UPLOAD_LIMIT   Global default daily cap        (default: 10)
  CLEANUP_TTL_HOURS    Hours before temp file deletion (default: 24)
  LOG_LEVEL            INFO / DEBUG / WARNING          (default: INFO)
  SUBTITLE_LANGS       Comma-separated lang codes      (default: en)
  DOWNLOAD_WORKERS     Parallel download slots         (default: 2)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
import yt_dlp

# Allow `python headless_watcher.py` from project root to find dashboard.models
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard.models import get_db, init_db  # noqa: E402
from dashboard.download_profile import build_ydl_opts, should_skip  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
DOWNLOAD_DIR        = Path(os.getenv("DOWNLOAD_DIR", "/downloads"))
N8N_WEBHOOK_URL     = os.getenv("N8N_WEBHOOK_URL", "")
CHECK_INTERVAL      = int(os.getenv("CHECK_INTERVAL", "15"))
DAILY_UPLOAD_LIMIT  = int(os.getenv("DAILY_UPLOAD_LIMIT", "10"))
CLEANUP_TTL_HOURS   = int(os.getenv("CLEANUP_TTL_HOURS", "24"))
LOG_LEVEL           = os.getenv("LOG_LEVEL", "INFO")
DOWNLOAD_WORKERS    = max(1, int(os.getenv("DOWNLOAD_WORKERS", "5")))
# Total attempts per job = MAX_DOWNLOAD_RETRIES (1 initial + N-1 retries).
# Set to 1 to disable auto-retry entirely.
MAX_DOWNLOAD_RETRIES = max(1, int(os.getenv("MAX_DOWNLOAD_RETRIES", "3")))
# Cookie file for YouTube authentication — fixes 429 / bot-detection.
# Set YOUTUBE_COOKIES_FILE=/cookies/cookies.txt in docker-compose/.env
YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "")
_COOKIES_OPTS: dict = (
    {"cookiefile": YOUTUBE_COOKIES_FILE}
    if YOUTUBE_COOKIES_FILE and os.path.isfile(YOUTUBE_COOKIES_FILE)
    else {}
)

# bgutil PO Token provider sidecar URL (Docker-internal hostname).
# The bgutil-provider container listens on port 4416 by default.
_BGUTIL_BASE_URL = os.getenv("BGUTIL_BASE_URL", "http://bgutil-provider:4416")
_BGUTIL_EXTRACTOR_ARG = f"youtubepot-bgutilhttp:base_url={_BGUTIL_BASE_URL}"
SUBTITLE_LANGS      = [
    l.strip() for l in os.getenv("SUBTITLE_LANGS", "en").split(",") if l.strip()
]

# ---------------------------------------------------------------------------
# Logging — unbuffered stdout for Docker logs
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("watcher")


def utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Per-thread SQLite connection cache for hot-path writes
# ---------------------------------------------------------------------------
# yt-dlp progress hooks fire ~1Hz per active download. Opening a fresh
# connection on every tick churns through file descriptors and re-applies
# PRAGMAs each call. Keep one connection per worker thread, reuse forever.
_PROGRESS_LOCAL = threading.local()


def _progress_conn():
    """Return a thread-local SQLite connection. Lazy-opens on first call."""
    conn = getattr(_PROGRESS_LOCAL, "conn", None)
    if conn is None:
        conn = get_db()
        _PROGRESS_LOCAL.conn = conn
    return conn


class _DownloadCancelled(Exception):
    """Raised inside a yt-dlp progress hook to abort an in-flight download.

    The dashboard sets ``download_queue.status='cancelled'`` when the user
    clicks Cancel; the hook polls that status each tick and raises this
    sentinel so yt-dlp cleanly tears down sockets / temp files.
    """
    pass


# ---------------------------------------------------------------------------
# Per-channel folder support
# ---------------------------------------------------------------------------
_FORBIDDEN_FS_CHARS = '<>:"/\\|?*'


def _sanitize_folder(name: str) -> str:
    """Make a string safe to use as a single filesystem folder name.

    - Strips reserved Windows/POSIX characters.
    - Collapses whitespace, trims dots/spaces (Windows reserves trailing).
    - Caps length at 100 chars.
    - Falls back to '_unknown' when the result is empty.
    """
    if not name:
        return "_unknown"
    cleaned = "".join(c for c in str(name) if c not in _FORBIDDEN_FS_CHARS and ord(c) >= 32)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if len(cleaned) > 100:
        cleaned = cleaned[:100].rstrip(" .")
    return cleaned or "_unknown"


def _resolve_download_root() -> Path:
    """Return the active downloads root.

    Reads optional override from worker_state (kind='setting',
    worker_id='downloads_root'). Falls back to the DOWNLOAD_DIR env var.
    The override path must already exist inside the container — otherwise
    we silently fall back to the default and log a warning once per cycle.
    """
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT detail FROM worker_state WHERE worker_id='downloads_root'"
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            override = Path(str(row[0]).strip())
            if override.exists() and override.is_dir():
                return override
            log.warning(
                f"downloads_root override '{override}' does not exist; using default {DOWNLOAD_DIR}"
            )
    except Exception as e:
        log.debug(f"_resolve_download_root: {e}")
    return DOWNLOAD_DIR


# ===========================================================================
# Database helpers
# ===========================================================================

def db_get_active_channels(channel_id_filter: Optional[int] = None) -> list[dict]:
    conn = get_db()
    try:
        sql = """
            SELECT c.*, COALESCE(c.download_priority, 100) AS download_priority,
                   p.name AS pipeline_name, p.active AS pipeline_active
            FROM channels c
            JOIN pipelines p ON p.id = c.pipeline_id
            WHERE c.active = 1 AND p.active = 1
        """
        params: tuple = ()
        if channel_id_filter is not None:
            sql += " AND c.id = ?"
            params = (channel_id_filter,)
        sql += " ORDER BY COALESCE(c.download_priority, 100) ASC, c.id ASC"
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # Older DB without channels.download_priority column.
            legacy_sql = """
                SELECT c.*, p.name AS pipeline_name, p.active AS pipeline_active
                FROM channels c
                JOIN pipelines p ON p.id = c.pipeline_id
                WHERE c.active = 1 AND p.active = 1
            """
            legacy_params: tuple = ()
            if channel_id_filter is not None:
                legacy_sql += " AND c.id = ?"
                legacy_params = (channel_id_filter,)
            legacy_sql += " ORDER BY c.id ASC"
            rows = conn.execute(legacy_sql, legacy_params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def db_get_destinations_for_pipeline(pipeline_id: int) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM destinations WHERE pipeline_id = ? AND enabled = 1",
            (pipeline_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def db_get_destination(destination_id: int) -> Optional[dict]:
    """Fetch a single destination row (used to resolve AI prompt overrides
    when firing the n8n webhook). Returns None if not found.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM destinations WHERE id = ?",
            (destination_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def db_get_profile_for_pipeline(pipeline_id: int) -> Optional[dict]:
    """Return the download_profiles row linked to ``pipeline_id``.

    Falls back to the pipeline-less default profile (``is_default=1``) if
    no explicit profile is configured. Returns ``None`` only if the table
    is missing entirely (legacy DB without the migration applied yet).
    """
    conn = get_db()
    try:
        try:
            row = conn.execute(
                """SELECT dp.* FROM pipelines p
                     LEFT JOIN download_profiles dp ON dp.id = p.download_profile_id
                    WHERE p.id = ?""",
                (pipeline_id,),
            ).fetchone()
            if row and row["id"] is not None:
                return dict(row)
            row = conn.execute(
                "SELECT * FROM download_profiles WHERE is_default = 1 LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        except Exception:                                       # noqa: BLE001
            return None
    finally:
        conn.close()


def db_video_exists(youtube_video_id: str) -> Optional[int]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM videos WHERE youtube_video_id = ?",
            (youtube_video_id,),
        ).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def db_insert_video(channel_pk: int, entry_meta: dict) -> int:
    """Insert a videos row, or update + return the existing one.

    The dashboard sometimes pre-creates a `videos` row (e.g. when a job is
    queued from the catalog before the watcher has downloaded it). When the
    watcher later downloads that same video, the INSERT would crash with a
    UNIQUE constraint on `youtube_video_id`. Treat that as an "upsert":
    fill in any blank metadata fields on the existing row and return its id.
    """
    conn = get_db()
    try:
        try:
            cur = conn.execute(
                """
                INSERT INTO videos (
                    channel_id, youtube_video_id, original_title, original_description,
                    duration, source_url, thumbnail_url, published_at, created_at,
                    view_count, like_count, comment_count,
                    tags_json, categories_json, language
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_pk,
                    entry_meta["video_id"],
                    entry_meta.get("title", ""),
                    entry_meta.get("description", ""),
                    int(entry_meta.get("duration") or 0),
                    entry_meta.get("source_url", ""),
                    entry_meta.get("thumbnail_url", ""),
                    entry_meta.get("published_at", ""),
                    utcnow_iso(),
                    _safe_int(entry_meta.get("view_count")),
                    _safe_int(entry_meta.get("like_count")),
                    _safe_int(entry_meta.get("comment_count")),
                    _safe_json(entry_meta.get("tags"), 4000),
                    _safe_json(entry_meta.get("categories"), 1000),
                    str(entry_meta.get("language") or "")[:32],
                ),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # Row already exists — backfill missing metadata and reuse it.
            row = conn.execute(
                "SELECT id FROM videos WHERE youtube_video_id = ?",
                (entry_meta["video_id"],),
            ).fetchone()
            if not row:
                raise
            video_pk = row["id"]
            conn.execute(
                """UPDATE videos SET
                    original_title       = COALESCE(NULLIF(?, ''), original_title),
                    original_description = COALESCE(NULLIF(?, ''), original_description),
                    duration             = COALESCE(NULLIF(?, 0),  duration),
                    source_url           = COALESCE(NULLIF(?, ''), source_url),
                    thumbnail_url        = COALESCE(NULLIF(?, ''), thumbnail_url),
                    published_at         = COALESCE(NULLIF(?, ''), published_at),
                    view_count           = COALESCE(?, view_count),
                    like_count           = COALESCE(?, like_count),
                    comment_count        = COALESCE(?, comment_count),
                    tags_json            = COALESCE(NULLIF(?, ''), tags_json),
                    categories_json      = COALESCE(NULLIF(?, ''), categories_json),
                    language             = COALESCE(NULLIF(?, ''), language)
                  WHERE id = ?""",
                (
                    entry_meta.get("title", ""),
                    entry_meta.get("description", ""),
                    int(entry_meta.get("duration") or 0),
                    entry_meta.get("source_url", ""),
                    entry_meta.get("thumbnail_url", ""),
                    entry_meta.get("published_at", ""),
                    _safe_int(entry_meta.get("view_count")),
                    _safe_int(entry_meta.get("like_count")),
                    _safe_int(entry_meta.get("comment_count")),
                    _safe_json(entry_meta.get("tags"), 4000),
                    _safe_json(entry_meta.get("categories"), 1000),
                    str(entry_meta.get("language") or "")[:32],
                    video_pk,
                ),
            )
            return video_pk
    finally:
        conn.close()


def _safe_int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_json(v, max_len: int):
    if not v:
        return ""
    try:
        s = json.dumps(v)
    except (TypeError, ValueError):
        return ""
    return s[:max_len]


def db_insert_job(video_pk: int, pipeline_id: int, source_file_path: str) -> int:
    conn = get_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO jobs (video_id, pipeline_id, status, source_file_path, created_at, updated_at)
            VALUES (?, ?, 'downloaded', ?, ?, ?)
            """,
            (video_pk, pipeline_id, source_file_path, utcnow_iso(), utcnow_iso()),
        )
        return cur.lastrowid
    finally:
        conn.close()


def db_update_channel(channel_pk: int, **fields) -> None:
    if not fields:
        return
    cols = []
    vals: list = []
    for k, v in fields.items():
        if isinstance(v, (list, dict)):
            v = json.dumps(v)
        cols.append(f"{k} = ?")
        vals.append(v)
    vals.append(channel_pk)
    conn = get_db()
    try:
        conn.execute(
            f"UPDATE channels SET {', '.join(cols)} WHERE id = ?",
            tuple(vals),
        )
    finally:
        conn.close()


# ===========================================================================
# Channel Watcher
# ===========================================================================

class ChannelWatcher:

    def __init__(self, dry_run: bool = False, run_once: bool = False,
                 channel_filter: Optional[int] = None):
        self._stop_event    = threading.Event()
        self._dry_run       = dry_run
        self._run_once      = run_once
        self._channel_filter = channel_filter
        # Track jobs currently being downloaded by this process so the
        # mid-loop recovery sweep can safely reset rows that are stuck in
        # 'downloading' but NOT in flight (orphans from prior crash, killed
        # threads, etc.) without disturbing live downloads.
        self._inflight_jobs: set[int] = set()
        self._inflight_lock           = threading.Lock()
        if not dry_run:
            DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Daily limit helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_daily_limit(channel: dict) -> int:
        return int(channel.get("daily_limit") or DAILY_UPLOAD_LIMIT)

    def _reset_daily_counter_if_needed(self, channel: dict) -> dict:
        today = date.today().isoformat()
        if channel.get("uploads_today_date") != today:
            if not self._dry_run:
                db_update_channel(
                    channel["id"], uploads_today=0, uploads_today_date=today,
                )
            channel["uploads_today"] = 0
            channel["uploads_today_date"] = today
        return channel

    def _increment_daily_counter(self, channel: dict) -> None:
        new_count = int(channel.get("uploads_today") or 0) + 1
        channel["uploads_today"] = new_count
        if not self._dry_run:
            db_update_channel(channel["id"], uploads_today=new_count)

    def _daily_slots_remaining(self, channel: dict) -> int:
        channel = self._reset_daily_counter_if_needed(channel)
        return max(0, self._get_daily_limit(channel) - int(channel.get("uploads_today") or 0))

    # ------------------------------------------------------------------
    # yt-dlp helpers
    # ------------------------------------------------------------------
    def _fetch_all_video_ids(self, channel_url: str) -> list:
        log.info("Fetching full channel history (this may take a moment)...")
        opts = {"extract_flat": True, "quiet": True, "no_warnings": True,
                "extractor_args": {"youtubepot-bgutilhttp": {"base_url": [_BGUTIL_BASE_URL]}},
                **_COOKIES_OPTS}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
                entries.reverse()  # oldest first
                log.info(f"Full history: {len(entries)} video(s) found.")
                return entries
        except Exception as e:
            log.error(f"Could not fetch full channel history ({channel_url}): {e}")
            return []

    def _fetch_latest_video_ids(self, channel_url: str, count: int = 15) -> list:
        opts = {
            "extract_flat": True,
            "playlist_items": f"1:{count}",
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {"youtubepot-bgutilhttp": {"base_url": [_BGUTIL_BASE_URL]}},
            **_COOKIES_OPTS,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                return [e for e in (info.get("entries") or []) if e and e.get("id")]
        except Exception as e:
            log.error(f"Could not fetch channel feed ({channel_url}): {e}")
            return []

    def _download_video(self, url: str, title: str,
                        profile: Optional[dict] = None,
                        channel_folder: Optional[str] = None,
                        video_id: Optional[str] = None) -> tuple[Optional[str], dict]:
        saved_path: Optional[str] = None
        extra: dict = {}
        # Throttle progress writes to ~1Hz so a 1080p download doesn't hammer
        # SQLite with thousands of UPDATEs. Captured by closure below.
        last_write_ts: list[float] = [0.0]

        def _write_progress(pct: int, detail: str) -> None:
            if not video_id:
                return
            try:
                conn = _progress_conn()
                conn.execute(
                    "UPDATE download_queue "
                    "   SET progress_pct = ?, progress_detail = ?, "
                    "       updated_at = ? "
                    " WHERE video_id = ?",
                    (max(0, min(100, int(pct))), detail[:200],
                     utcnow_iso(), video_id),
                )
                conn.commit()
            except Exception:  # never let progress logging break a download
                # Drop the cached conn so the next call re-opens cleanly.
                try:
                    if getattr(_PROGRESS_LOCAL, "conn", None) is not None:
                        _PROGRESS_LOCAL.conn.close()
                except Exception:
                    pass
                _PROGRESS_LOCAL.conn = None

        def _hook(d: dict) -> None:
            nonlocal saved_path
            status = d.get("status")
            if status == "finished":
                saved_path = d.get("filename", "")
                _write_progress(100, "merging…")
                last_write_ts[0] = time.time()
                return
            if status != "downloading":
                return
            now = time.time()
            if now - last_write_ts[0] < 1.0:
                return
            last_write_ts[0] = now
            # Cooperative cancel check: dashboard flips download_queue.status
            # to 'cancelled' when the user clicks the X. Cheap query against
            # the same row we'd update anyway.
            if video_id:
                try:
                    conn = _progress_conn()
                    row = conn.execute(
                        "SELECT status FROM download_queue WHERE video_id = ?",
                        (video_id,),
                    ).fetchone()
                    if row and row[0] == "cancelled":
                        log.info(f"[CANCEL] {video_id}: aborting per dashboard request")
                        raise _DownloadCancelled(video_id)
                except _DownloadCancelled:
                    raise
                except Exception:
                    pass  # non-fatal: keep downloading on transient db errors
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = int((done / total) * 100) if total else 0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            speed_s = f"{speed/1_000_000:.1f}MB/s" if speed else "?"
            eta_s = f"{int(eta)}s" if eta else "?"
            _write_progress(pct, f"{pct}% · {speed_s} · ETA {eta_s}")

        # Resolve destination: <root>/<channel_folder>/<video_id>/<title>.<ext>
        # Falls back to <root>/<video_id>/<title>.<ext> when no channel given
        # (preserves legacy layout for callers that don't pass channel info).
        root = _resolve_download_root()
        if channel_folder:
            safe_folder = _sanitize_folder(channel_folder)
            try:
                (root / safe_folder).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                log.warning(f"Could not create channel folder '{safe_folder}': {e}")
                safe_folder = ""
            base = root / safe_folder if safe_folder else root
        else:
            base = root

        ydl_opts = build_ydl_opts(
            profile,
            outtmpl=str(base / "%(id)s" / "%(title)s.%(ext)s"),
            progress_hooks=[_hook],
        )
        # Honor SUBTITLE_LANGS env override when the profile is using
        # legacy/default behavior so existing deployments are unaffected.
        if profile is None:
            ydl_opts["subtitleslangs"] = SUBTITLE_LANGS
        log.info(f"  yt-dlp format: {ydl_opts.get('format')}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True) or {}
                extra = {
                    "title":         info.get("title", ""),
                    "duration":      info.get("duration", 0),
                    "channel_url":   info.get("channel_url", ""),
                    "view_count":    info.get("view_count", 0),
                    "like_count":    info.get("like_count", 0),
                    "comment_count": info.get("comment_count", 0),
                    "upload_date":   info.get("upload_date", ""),
                    "description":   (info.get("description") or "")[:2000],
                    "tags":          info.get("tags") or [],
                    "categories":    info.get("categories") or [],
                    "thumbnail":     info.get("thumbnail", ""),
                    "language":      info.get("language", ""),
                    "chapters":      info.get("chapters") or [],
                    "age_limit":     info.get("age_limit", 0),
                }
        except _DownloadCancelled:
            log.info(f"  Download canceled by user for '{title}'")
            extra["_canceled"] = True
            # Best-effort cleanup of partial files in the per-video dir.
            try:
                if saved_path:
                    parent = Path(saved_path).parent
                    if parent.exists() and parent != root:
                        for p in parent.glob("*"):
                            try:
                                p.unlink()
                            except OSError:
                                pass
                        try:
                            parent.rmdir()
                        except OSError:
                            pass
            except Exception:
                pass
            return None, extra
        except Exception as e:
            log.error(f"Download failed for '{title}': {e}")
            return None, {}

        if saved_path and not Path(saved_path).exists():
            mp4_alt = Path(saved_path).with_suffix(".mp4")
            if mp4_alt.exists():
                saved_path = str(mp4_alt)
            else:
                # yt-dlp's progress hook reports each format separately; the
                # final merged mp4 is never reported via the hook. Fall back to
                # scanning the per-video output directory for the merged file.
                parent = Path(saved_path).parent
                if parent.exists():
                    import re as _re
                    fmt_intermediate = _re.compile(r"\.f\d+$")
                    mp4s = [p for p in sorted(parent.glob("*.mp4"))
                            if not fmt_intermediate.search(p.stem)]
                    if mp4s:
                        saved_path = str(mp4s[0])

        # Always prefer the merged .mp4 over subtitles/info-json that the
        # progress hook may have reported last. Scan the per-video directory
        # for a non-intermediate .mp4 and use it if present.
        if saved_path:
            ext = Path(saved_path).suffix.lower()
            if ext != ".mp4":
                parent = Path(saved_path).parent
                if parent.exists():
                    import re as _re
                    fmt_intermediate = _re.compile(r"\.f\d+$")
                    mp4s = [p for p in sorted(parent.glob("*.mp4"))
                            if not fmt_intermediate.search(p.stem)]
                    if mp4s:
                        log.info(f"Replacing reported '{ext}' path with merged mp4: {mp4s[0].name}")
                        saved_path = str(mp4s[0])

        if not (saved_path and Path(saved_path).exists()):
            log.warning(f"Download finished but file not found for '{title}'")
            return None, extra

        video_dir = Path(saved_path).parent
        thumb_files = sorted(video_dir.glob("*.jpg")) + sorted(video_dir.glob("*.webp"))
        sub_files   = sorted(video_dir.glob("*.vtt")) + sorted(video_dir.glob("*.srt"))
        json_files  = list(video_dir.glob("*.info.json"))
        extra["video_dir"]      = str(video_dir)
        extra["thumbnail_path"] = str(thumb_files[0]) if thumb_files else ""
        extra["subtitle_paths"] = [str(f) for f in sub_files]
        extra["info_json_path"] = str(json_files[0]) if json_files else ""

        log.info(f"  Video:      {Path(saved_path).name}")
        if extra["thumbnail_path"]:
            log.info(f"  Thumbnail:  {Path(extra['thumbnail_path']).name}")
        if extra["subtitle_paths"]:
            log.info(f"  Subtitles ({len(extra['subtitle_paths'])}): "
                     f"{[Path(p).name for p in extra['subtitle_paths']]}")
        if extra["info_json_path"]:
            log.info(f"  Metadata:   {Path(extra['info_json_path']).name}")

        return saved_path, extra

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------
    def _resolve_webhook_urls(self, pipeline_id: int) -> list[tuple[Optional[int], str]]:
        dests = db_get_destinations_for_pipeline(pipeline_id)
        if dests:
            return [(d["id"], d["n8n_webhook_url"]) for d in dests if d.get("n8n_webhook_url")]
        if N8N_WEBHOOK_URL:
            return [(None, N8N_WEBHOOK_URL)]
        return []

    def _filter_dests_by_ledger(
        self,
        dest_pairs: list[tuple[Optional[int], str]],
        video_id: str,
    ) -> list[tuple[Optional[int], str]]:
        """Drop (dest_id, url) pairs where the (video_id, dest_id) is already
        recorded in `upload_ledger` with a non-failed terminal state. Prevents
        duplicate uploads on retries / re-enqueues.

        - Keeps pairs with no ledger row (never tried).
        - Keeps pairs whose only ledger row is 'failed' (allow retry).
        - Keeps pairs with dest_id=None (legacy fallback webhook — can't dedup).
        - Drops pairs in {'queued','uploading','uploaded'}.
        """
        if not dest_pairs or not video_id:
            return dest_pairs
        keepers: list[tuple[Optional[int], str]] = []
        try:
            conn = get_db()
            try:
                for dest_id, url in dest_pairs:
                    if dest_id is None:
                        keepers.append((dest_id, url))
                        continue
                    row = conn.execute(
                        "SELECT status FROM upload_ledger "
                        " WHERE video_id = ? AND destination_id = ?",
                        (video_id, dest_id),
                    ).fetchone()
                    if row is None:
                        keepers.append((dest_id, url))
                        continue
                    status = (row[0] or "").lower()
                    if status in ("failed", "removed"):
                        # Allow retry — clear the row so the upload endpoint's
                        # INSERT-OR-IGNORE doesn't silently no-op later.
                        conn.execute(
                            "DELETE FROM upload_ledger "
                            " WHERE video_id = ? AND destination_id = ?",
                            (video_id, dest_id),
                        )
                        keepers.append((dest_id, url))
                    else:
                        log.info(
                            f"[DEDUP] {video_id} → dest {dest_id}: skipping webhook "
                            f"(ledger status='{status}')"
                        )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:  # never block uploads on a dedup error
            log.warning(f"[DEDUP] ledger check failed for {video_id}: {e}")
            return dest_pairs
        return keepers

    def _retry_stranded_uploads(self, max_jobs: int = 20) -> int:
        """Re-fire webhooks for jobs whose uploads got stranded.

        A 'stranded' job has status='processed' (or 'downloaded'), a
        source_file_path on disk, an enabled destination — but no successful
        upload_results row, no in-flight upload_progress activity, and a
        stale upload_ledger row (queued > UPLOAD_RETRY_AFTER_MIN, or
        uploading > UPLOAD_STALL_AFTER_MIN with no progress writes).

        Closes the gap when n8n is down or a webhook silently dropped.
        Returns the number of webhooks re-fired.
        """
        retry_after = max(1, int(os.getenv("UPLOAD_RETRY_AFTER_MIN", "15")))
        stall_after = max(retry_after, int(os.getenv("UPLOAD_STALL_AFTER_MIN", "30")))

        try:
            conn = get_db()
            try:
                # Step 1: clear stale ledger rows so _filter_dests_by_ledger
                # treats the (video, dest) pair as fresh and lets the retry
                # webhook through.
                conn.execute(
                    "DELETE FROM upload_ledger "
                    " WHERE status='queued' "
                    "   AND updated_at < strftime('%Y-%m-%dT%H:%M:%S','now',?)",
                    (f"-{retry_after} minutes",),
                )
                conn.execute(
                    "DELETE FROM upload_ledger "
                    " WHERE status='uploading' "
                    "   AND updated_at < strftime('%Y-%m-%dT%H:%M:%S','now',?) "
                    "   AND NOT EXISTS ("
                    "       SELECT 1 FROM upload_progress up "
                    "        WHERE up.job_id = upload_ledger.job_id "
                    "          AND up.destination_id = upload_ledger.destination_id "
                    "          AND up.updated_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-5 minutes')"
                    "   )",
                    (f"-{stall_after} minutes",),
                )
                conn.commit()

                # Step 2: candidate jobs.
                rows = conn.execute(
                    """SELECT j.id AS job_id, j.pipeline_id,
                              j.source_file_path AS file_path,
                              v.youtube_video_id AS video_id,
                              v.original_title AS title,
                              v.source_url, v.original_description AS description,
                              v.duration, v.thumbnail_url, v.published_at,
                              v.view_count, v.like_count, v.comment_count,
                              c.id AS channel_pk, c.name AS channel_name,
                              c.channel_id AS channel_external_id,
                              c.url AS channel_url
                         FROM jobs j
                         JOIN videos v ON v.id = j.video_id
                         JOIN channels c ON c.id = v.channel_id
                        WHERE j.status IN ('processed','downloaded')
                          AND j.source_file_path != ''
                          AND j.updated_at <= strftime('%Y-%m-%dT%H:%M:%S','now',?)
                          AND EXISTS (
                              SELECT 1 FROM destinations d
                               WHERE d.pipeline_id = j.pipeline_id AND d.enabled = 1
                          )
                        ORDER BY j.updated_at ASC
                        LIMIT ?""",
                    (f"-{retry_after} minutes", max_jobs),
                ).fetchall()
            finally:
                conn.close()
        except Exception as e:                                  # noqa: BLE001
            log.error(f"_retry_stranded_uploads query failed: {e}", exc_info=True)
            return 0

        fired = 0
        for r in rows:
            if self._stop_event.is_set():
                break
            file_path = r["file_path"] or ""
            if file_path and not os.path.exists(file_path):
                # Source file was cleaned up; n8n can't upload it. Skip silently.
                continue
            dest_pairs = self._filter_dests_by_ledger(
                self._resolve_webhook_urls(r["pipeline_id"]), r["video_id"]
            )
            if not dest_pairs:
                continue
            channel_dict = {
                "id":          r["channel_pk"],
                "name":        r["channel_name"],
                "channel_id":  r["channel_external_id"],
                "url":         r["channel_url"],
                "pipeline_id": r["pipeline_id"],
            }
            extra = {
                "description":   r["description"] or "",
                "duration":      r["duration"] or 0,
                "thumbnail":     r["thumbnail_url"] or "",
                "upload_date":   r["published_at"] or "",
                "view_count":    r["view_count"] or 0,
                "like_count":    r["like_count"] or 0,
                "comment_count": r["comment_count"] or 0,
            }
            for dest_id, webhook_url in dest_pairs:
                log.info(
                    f"[RETRY] re-firing upload webhook job={r['job_id']} "
                    f"dest={dest_id} video={r['video_id']}"
                )
                self._fire_webhook(
                    url=webhook_url,
                    destination_id=dest_id,
                    job_id=r["job_id"],
                    pipeline_id=r["pipeline_id"],
                    channel=channel_dict,
                    video_id=r["video_id"],
                    title=r["title"] or r["video_id"],
                    file_path=file_path,
                    source_url=r["source_url"] or f"https://www.youtube.com/watch?v={r['video_id']}",
                    extra=extra,
                    mode="retry",
                )
                fired += 1
        return fired

    def _fire_webhook(
        self,
        url: str,
        destination_id: Optional[int],
        job_id: int,
        pipeline_id: int,
        channel: dict,
        video_id: str,
        title: str,
        file_path: str,
        source_url: str,
        extra: dict,
        mode: str,
    ) -> None:
        payload = {
            "event":          "download_completed",
            "mode":           mode,
            "job_id":         job_id,
            "pipeline_id":    pipeline_id,
            "destination_id": destination_id,
            "video_id":       video_id,
            "title":          title,
            "file_path":      file_path,
            "source_url":     source_url,
            "channel_name":   channel.get("name", ""),
            "channel_id":     channel.get("channel_id", ""),
            "channel_url":    extra.get("channel_url", channel.get("url", "")),
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "duration":      extra.get("duration", 0),
            "view_count":    extra.get("view_count", 0),
            "like_count":    extra.get("like_count", 0),
            "comment_count": extra.get("comment_count", 0),
            "upload_date":   extra.get("upload_date", ""),
            "description":   extra.get("description", ""),
            "tags":          extra.get("tags", []),
            "categories":    extra.get("categories", []),
            "thumbnail":     extra.get("thumbnail", ""),
            "language":      extra.get("language", ""),
            "chapters":      extra.get("chapters", []),
            "age_limit":     extra.get("age_limit", 0),
            "video_dir":      extra.get("video_dir", ""),
            "thumbnail_path": extra.get("thumbnail_path", ""),
            "subtitle_paths": extra.get("subtitle_paths", []),
            "info_json_path": extra.get("info_json_path", ""),
        }
        # Attach per-destination AI prompt overrides so the n8n workflow can
        # use them (or fall back to its built-in defaults). Empty strings
        # mean "use workflow default" — never break older destinations.
        if destination_id is not None:
            dest = db_get_destination(destination_id)
            if dest:
                payload["ai_enabled"]        = bool(dest.get("ai_enabled", 0))
                payload["ai_model"]          = dest.get("ai_model") or ""
                payload["ai_system_prompt"]  = dest.get("ai_system_prompt") or ""
                payload["ai_user_template"]  = dest.get("ai_user_template") or ""
                payload["default_privacy"]   = dest.get("default_privacy") or "unlisted"
                payload["destination_label"] = dest.get("label") or ""
                payload["destination_platform"] = dest.get("platform") or ""
        try:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            log.info(f"Webhook -> HTTP {resp.status_code} [{mode}] dest={destination_id} '{title}'")
        except requests.exceptions.ConnectionError:
            log.error(f"Webhook connection failed. Is n8n running at {url}?")
        except Exception as e:
            log.error(f"Webhook failed for '{title}': {e}")

    # ------------------------------------------------------------------
    # Core: process a single video entry
    # ------------------------------------------------------------------
    def _process_video(self, channel: dict, entry: dict, mode: str) -> bool:
        if self._stop_event.is_set():
            return False

        video_id  = entry["id"]
        title     = entry.get("title", video_id)
        video_url = (
            entry.get("url")
            or entry.get("webpage_url")
            or f"https://www.youtube.com/watch?v={video_id}"
        )

        log.info(f"[{mode.upper()}] Downloading: {title}")

        if self._dry_run:
            log.info(f"  (dry-run) would download {video_url}")
            return True

        # Resolve download profile for this pipeline (falls back to legacy
        # behavior when no profile/table exists).
        profile = db_get_profile_for_pipeline(channel["pipeline_id"])

        # Pre-flight skip check using anything we already know about the
        # video from the flat scan (duration, live_status). Saves a
        # network round-trip when shorts/lives are filtered out.
        skip_reason = should_skip(profile, entry)
        if skip_reason:
            log.info(f"  Skipping ({skip_reason}) per profile '{(profile or {}).get('name','?')}'")
            return False

        file_path, extra = self._download_video(
            video_url, title, profile=profile,
            channel_folder=channel.get("name") or channel.get("channel_id"),
            video_id=video_id,
        )
        if not file_path:
            return False

        video_pk = db_insert_video(
            channel_pk=channel["id"],
            entry_meta={
                "video_id":      video_id,
                "title":         title,
                "description":   extra.get("description", ""),
                "duration":      extra.get("duration", 0),
                "source_url":    video_url,
                "thumbnail_url": extra.get("thumbnail", ""),
                "published_at":  extra.get("upload_date", ""),
                "view_count":    extra.get("view_count"),
                "like_count":    extra.get("like_count"),
                "comment_count": extra.get("comment_count"),
                "tags":          extra.get("tags"),
                "categories":    extra.get("categories"),
                "language":      extra.get("language"),
            },
        )
        job_id = db_insert_job(
            video_pk=video_pk,
            pipeline_id=channel["pipeline_id"],
            source_file_path=file_path,
        )
        log.info(f"  DB: video.id={video_pk}  job.id={job_id}")

        dest_pairs = self._filter_dests_by_ledger(
            self._resolve_webhook_urls(channel["pipeline_id"]), video_id
        )
        for dest_id, url in dest_pairs:
            self._fire_webhook(
                url=url,
                destination_id=dest_id,
                job_id=job_id,
                pipeline_id=channel["pipeline_id"],
                channel=channel,
                video_id=video_id,
                title=title,
                file_path=file_path,
                source_url=video_url,
                extra=extra,
                mode=mode,
            )

        self._increment_daily_counter(channel)
        return True

    # ------------------------------------------------------------------
    # MODE 1 — BACKFILL
    # ------------------------------------------------------------------
    def _run_backfill(self, channel: dict) -> None:
        name = channel.get("name", channel["channel_id"])
        url  = channel.get("url", "")

        try:
            queue = json.loads(channel.get("backfill_queue") or "[]")
        except json.JSONDecodeError:
            queue = []
        try:
            entry_map = json.loads(channel.get("backfill_entry_map") or "{}")
        except json.JSONDecodeError:
            entry_map = {}

        if not queue and not entry_map:
            log.info(f"[BACKFILL] Building queue for '{name}'...")
            entries = self._fetch_all_video_ids(url)
            pending_ids = [e["id"] for e in entries if not db_video_exists(e["id"])]
            entry_map   = {e["id"]: e for e in entries}
            if not self._dry_run:
                db_update_channel(
                    channel["id"],
                    backfill_queue=pending_ids,
                    backfill_entry_map=entry_map,
                )
            queue = pending_ids
            log.info(f"[BACKFILL] Queue built: {len(queue)} video(s) for '{name}'.")

        if not queue:
            log.info(f"[BACKFILL] '{name}' — empty queue. Switching to MONITOR mode.")
            if not self._dry_run:
                db_update_channel(channel['id'], backfill_complete=1, mode='monitor')
            return

        # Daily-cap switch: each channel can opt out of the per-day limit
        # via the `download_unlimited` column (toggle on the Downloads card).
        # When ON, drain the entire backlog this cycle. When OFF, honour
        # the channel's `daily_limit` minus today's `uploads_today` count.
        unlimited = bool(int(channel.get("download_unlimited") or 0))
        if unlimited:
            slots = len(queue)
            log.info(
                f"[BACKFILL] '{name}' — unlimited mode: processing all "
                f"{len(queue)} remaining video(s)."
            )
        else:
            slots = self._daily_slots_remaining(channel)
            if slots <= 0:
                log.info(
                    f"[BACKFILL] '{name}' — daily cap reached "
                    f"({int(channel.get('uploads_today') or 0)}/"
                    f"{self._get_daily_limit(channel)}). "
                    f"Toggle 'unlimited' on the channel card to bypass."
                )
                return
            log.info(
                f"[BACKFILL] '{name}' — processing up to {slots} video(s) "
                f"today ({len(queue)} remaining)."
            )
        processed = 0
        while queue and not self._stop_event.is_set() and processed < slots:
            video_id = queue[0]
            entry    = entry_map.get(video_id, {'id': video_id})
            self._process_video(channel, entry, mode='backfill')
            queue.pop(0)
            processed += 1
            if not self._dry_run:
                db_update_channel(
                    channel['id'],
                    backfill_queue=queue,
                    last_check=utcnow_iso(),
                )

        log.info(f"[BACKFILL] '{name}' — {processed} processed, {len(queue)} remaining.")

        if not queue:
            log.info(f"[BACKFILL] '{name}' backfill complete! Switching to MONITOR.")
            if not self._dry_run:
                db_update_channel(
                    channel["id"],
                    backfill_complete=1,
                    backfill_queue=[],
                    backfill_entry_map={},
                    mode="monitor",
                )

    # ------------------------------------------------------------------
    # MODE 2 — MONITOR
    # ------------------------------------------------------------------
    def _run_monitor(self, channel: dict) -> None:
        name = channel.get("name", channel["channel_id"])
        url  = channel.get("url", "")

        log.info(f"[MONITOR] Checking: {name}")
        unlimited = bool(int(channel.get("download_unlimited") or 0))
        if unlimited:
            slots = 9999
        else:
            slots = self._daily_slots_remaining(channel)
            if slots <= 0:
                log.info(f"[MONITOR] '{name}' — daily limit reached.")
                return

        entries  = self._fetch_latest_video_ids(url)
        new_ones = [e for e in entries if not db_video_exists(e["id"])]

        if not new_ones:
            log.info(f"[MONITOR] '{name}' — no new videos.")
            if not self._dry_run:
                db_update_channel(channel["id"], last_check=utcnow_iso())
            return

        log.info(f"[MONITOR] '{name}' — {len(new_ones)} new video(s) found.")
        for entry in new_ones[:slots]:
            if self._stop_event.is_set():
                break
            self._process_video(channel, entry, mode="monitor")

        if not self._dry_run:
            db_update_channel(channel["id"], last_check=utcnow_iso())

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------
    def _check_channel(self, channel: dict) -> None:
        if not channel.get("url", ""):
            log.warning(f"Channel '{channel.get('name')}' has no URL — skipping.")
            return
        if int(channel.get("backfill_complete") or 0) == 0:
            self._run_backfill(channel)
        else:
            self._run_monitor(channel)

    # ------------------------------------------------------------------
    # Manual download_queue drain — handles jobs created by the dashboard's
    # dlq-hydrator (status='pending', empty source_file_path). These are
    # videos the user explicitly queued from the catalog/Downloads tab and
    # are NOT subject to the per-channel daily cap.
    # ------------------------------------------------------------------
    def _drain_one_job(self, r: dict) -> tuple[bool, dict]:
        """Download a single job. Called from a thread. Returns (success, r)."""
        title = r["title"] or r["video_id"]
        url   = r["source_url"] or f"https://www.youtube.com/watch?v={r['video_id']}"
        log.info(f"[PENDING] job {r['job_id']}: {title}")

        # Pre-flight: is this video already on disk from a prior successful
        # download? The watcher writes to <root>/<channel>/<video_id>/, and
        # the final merged file is the only non-".fNNN" mp4/mkv/webm in that
        # folder. Skip the network round-trip entirely if found.
        existing_path = self._find_existing_download(
            r.get("channel_name") or r.get("channel_external_id") or "",
            r["video_id"],
        )
        if existing_path:
            log.info(f"[PENDING] job {r['job_id']}: already on disk → {existing_path}")
            r["_file_path"] = existing_path
            r["_extra"]     = {}
            r["_skipped_reason"] = "file already on disk"
            return True, r

        # Mark downloading
        conn = get_db()
        try:
            conn.execute(
                """UPDATE download_queue
                      SET status = 'downloading', updated_at = ?
                    WHERE job_id = ? AND status IN ('hydrated','pending')""",
                (utcnow_iso(), r["job_id"]),
            )
            conn.execute(
                "UPDATE jobs SET status='downloading', updated_at=? WHERE id=?",
                (utcnow_iso(), r["job_id"]),
            )
            conn.commit()
        finally:
            conn.close()

        profile = db_get_profile_for_pipeline(r["pipeline_id"])
        file_path, extra = self._download_video(
            url, title, profile=profile,
            channel_folder=r.get("channel_name") or r.get("channel_external_id"),
            video_id=r.get("video_id"),
        )
        r["_file_path"] = file_path
        r["_extra"]     = extra
        return bool(file_path), r

    @staticmethod
    def _find_existing_download(channel_folder: str, video_id: str) -> Optional[str]:
        """Return the path to a previously-downloaded merged file for this
        video, or None. Looks in <root>/<channel>/<video_id>/ and
        <root>/<video_id>/. The final merged file is any mp4/mkv/webm/m4a
        whose stem does NOT end in `.fNNN` (yt-dlp format-specific intermediate).
        """
        if not video_id:
            return None
        import re as _re
        fmt_intermediate = _re.compile(r"\.f\d+$")
        merged_exts = {".mp4", ".mkv", ".webm", ".m4a"}
        try:
            root = _resolve_download_root()
        except Exception:                                          # noqa: BLE001
            return None
        candidates = []
        if channel_folder:
            safe = _sanitize_folder(channel_folder)
            if safe:
                candidates.append(root / safe / video_id)
        candidates.append(root / video_id)
        for d in candidates:
            try:
                if not d.is_dir():
                    continue
                for p in d.iterdir():
                    if (p.is_file()
                            and p.suffix.lower() in merged_exts
                            and not fmt_intermediate.search(p.stem)
                            and p.stat().st_size > 0):
                        return str(p)
            except OSError:
                continue
        return None

    def _recover_orphaned_jobs(self, max_age_minutes: int = 60) -> int:
        """Mid-loop recovery: reset jobs pinned in 'downloading' that are NOT
        currently in flight in this process. Catches rows orphaned by a
        crashed thread, killed worker, or any code path that failed to mark
        terminal state. Skips jobs younger than ``max_age_minutes`` to avoid
        racing with very-recently-started downloads on other watcher
        instances (single-instance deployments will never trip the age guard
        because their in-flight set already covers them).
        """
        if self._dry_run:
            return 0
        with self._inflight_lock:
            inflight = tuple(self._inflight_jobs)
        cutoff = (datetime.utcnow() - timedelta(minutes=max_age_minutes)).strftime(
            "%Y-%m-%dT%H:%M:%S")
        conn = get_db()
        try:
            try:
                # Build NOT IN clause safely
                if inflight:
                    placeholders = ",".join(["?"] * len(inflight))
                    sql_jobs = (f"UPDATE jobs SET status='pending', updated_at=? "
                                f"WHERE status='downloading' AND updated_at < ? "
                                f"AND id NOT IN ({placeholders})")
                    params = (utcnow_iso(), cutoff, *inflight)
                else:
                    sql_jobs = ("UPDATE jobs SET status='pending', updated_at=? "
                                "WHERE status='downloading' AND updated_at < ?")
                    params = (utcnow_iso(), cutoff)
                cur = conn.execute(sql_jobs, params)
                n_jobs = cur.rowcount or 0
                # Mirror onto download_queue for any rows we just reset
                try:
                    if inflight:
                        sql_dlq = (f"UPDATE download_queue SET status='pending', "
                                   f"updated_at=? WHERE status='downloading' "
                                   f"AND updated_at < ? "
                                   f"AND job_id NOT IN ({placeholders})")
                        conn.execute(sql_dlq, params)
                    else:
                        conn.execute(
                            "UPDATE download_queue SET status='pending', "
                            "updated_at=? WHERE status='downloading' "
                            "AND updated_at < ?",
                            (utcnow_iso(), cutoff),
                        )
                except sqlite3.OperationalError:
                    pass
                conn.commit()
            except Exception:
                try: conn.rollback()
                except Exception: pass
                raise
        finally:
            conn.close()
        if n_jobs:
            log.warning(
                f"[recovery] Reset {n_jobs} orphaned 'downloading' job(s) "
                f"older than {max_age_minutes}m and not in flight."
            )
        return n_jobs

    def _heartbeat(self, status: str, detail: str = "") -> None:
        """Upsert this watcher's row in worker_state. Cheap (~1ms). The
        dashboard reads this to display a 'last seen Xs ago' health widget
        and to declare the watcher 'stale' / 'dead' if it stops heartbeating.
        """
        if self._dry_run:
            return
        # Stash the latest status so the background heartbeat thread can
        # re-emit it even when the main loop is blocked inside a long yt-dlp
        # download (which would otherwise look 'dead' after 5 minutes).
        self._hb_last_status = status
        self._hb_last_detail = detail
        try:
            import os as _os, socket as _socket
            conn = get_db()
            try:
                conn.execute(
                    """INSERT INTO worker_state
                            (worker_id, kind, status, detail, last_beat, pid, host)
                       VALUES ('watcher', 'watcher', ?, ?,
                               strftime('%Y-%m-%dT%H:%M:%S','now'), ?, ?)
                       ON CONFLICT(worker_id) DO UPDATE SET
                         kind='watcher',
                         status=excluded.status,
                         detail=excluded.detail,
                         last_beat=excluded.last_beat,
                         pid=excluded.pid,
                         host=excluded.host""",
                    (status, detail[:500],
                     _os.getpid(), _socket.gethostname()[:64]),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:                                  # noqa: BLE001
            log.debug(f"_heartbeat failed: {e}")

    def _heartbeat_loop(self) -> None:
        """Background thread: keep the heartbeat fresh during long downloads.

        Runs every 30s and re-writes the most recent (status, detail). Without
        this the dashboard marks the watcher 'dead' after 5 minutes whenever
        a single yt-dlp download blocks the main loop for that long.
        """
        while not self._stop_event.is_set():
            # Wait first so we don't double-beat right after a fresh _heartbeat call.
            if self._stop_event.wait(30):
                return
            try:
                self._heartbeat(
                    getattr(self, "_hb_last_status", "busy"),
                    getattr(self, "_hb_last_detail", "working"),
                )
            except Exception as e:                              # noqa: BLE001
                log.debug(f"background heartbeat failed: {e}")

    def _drain_pending_jobs(self, batch: int = 3) -> int:
        """Download up to ``batch`` jobs in 'pending' state in parallel.
        Returns count of jobs successfully transitioned to 'downloaded'.
        """
        if self._dry_run:
            return 0

        # Check global pause flag set by dashboard
        try:
            _pconn = get_db()
            try:
                _prow = _pconn.execute(
                    "SELECT detail FROM worker_state WHERE worker_id='queue_paused'"
                ).fetchone()
                if _prow and (_prow[0] or "0") == "1":
                    log.info("[PENDING] Downloads globally paused — skipping drain cycle.")
                    return 0
            finally:
                _pconn.close()
        except Exception:
            pass

        conn = get_db()
        try:
            try:
                rows = conn.execute(
                    """
                    SELECT j.id AS job_id, j.pipeline_id,
                           v.id AS video_pk, v.youtube_video_id AS video_id,
                           v.original_title AS title, v.source_url,
                           c.id AS channel_pk, c.name AS channel_name,
                           c.channel_id AS channel_external_id, c.url AS channel_url,
                           COALESCE(c.download_priority, 100) AS channel_priority
                      FROM jobs j
                      JOIN videos v ON v.id = j.video_id
                      JOIN channels c ON c.id = v.channel_id
                     WHERE j.status = 'pending'
                       AND (j.source_file_path IS NULL OR j.source_file_path = '')
                     ORDER BY COALESCE(c.download_priority, 100) ASC, j.id ASC
                     LIMIT ?
                    """,
                    (max(1, batch),),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT j.id AS job_id, j.pipeline_id,
                           v.id AS video_pk, v.youtube_video_id AS video_id,
                           v.original_title AS title, v.source_url,
                           c.id AS channel_pk, c.name AS channel_name,
                           c.channel_id AS channel_external_id, c.url AS channel_url
                      FROM jobs j
                      JOIN videos v ON v.id = j.video_id
                      JOIN channels c ON c.id = v.channel_id
                     WHERE j.status = 'pending'
                       AND (j.source_file_path IS NULL OR j.source_file_path = '')
                     ORDER BY j.id ASC
                     LIMIT ?
                    """,
                    (max(1, batch),),
                ).fetchall()
            rows = [dict(r) for r in rows]
        finally:
            conn.close()

        if not rows:
            return 0

        # Read workers count from DB (updated live by dashboard); fall back to env
        try:
            _cfg = get_db()
            try:
                _row = _cfg.execute(
                    "SELECT detail FROM worker_state WHERE worker_id='download_workers'"
                ).fetchone()
                workers = max(1, min(int(_row[0]), 12)) if _row and (_row[0] or "").isdigit() else DOWNLOAD_WORKERS
            finally:
                _cfg.close()
        except Exception:
            workers = DOWNLOAD_WORKERS

        workers = min(workers, len(rows))
        rows = rows[:workers]  # Only submit one batch at a time so worker-count changes take effect each cycle
        log.info(f"[PENDING] Draining {len(rows)} pending job(s) with {workers} parallel worker(s)...")
        drained = 0

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dl") as pool:
            with self._inflight_lock:
                for r in rows:
                    self._inflight_jobs.add(r["job_id"])
            futures = {
                pool.submit(self._drain_one_job, r): r
                for r in rows
                if not self._stop_event.is_set()
            }
            for fut in as_completed(futures):
                if self._stop_event.is_set():
                    break
                try:
                    ok, r = fut.result()
                except Exception as exc:
                    r = futures[fut]
                    log.error(f"[PENDING] job {r['job_id']} raised: {exc}")
                    ok = False

                file_path = r.get("_file_path")
                extra     = r.get("_extra") or {}

                # Cancel: dashboard already set jobs.status='failed' with
                # error_message='canceled by user' and dlq.status='cancelled'.
                # Don't clobber those — just discard from in-flight.
                if extra.get("_canceled"):
                    with self._inflight_lock:
                        self._inflight_jobs.discard(r["job_id"])
                    log.info(f"[CANCEL] job {r['job_id']}: aborted per user request.")
                    continue

                if not ok or not file_path:

                    conn = get_db()
                    try:
                        try:
                            # Auto-retry: bump retry_count and re-queue up to
                            # MAX_DOWNLOAD_RETRIES times. Transient YouTube
                            # errors (rate limit, 5xx, network blips) recover
                            # on the next pending tick. Hard failures still
                            # land in 'failed' once the cap is hit.
                            row = conn.execute(
                                "SELECT retry_count FROM jobs WHERE id=?",
                                (r["job_id"],),
                            ).fetchone()
                            attempts = (row[0] if row else 0) or 0
                            if attempts + 1 < MAX_DOWNLOAD_RETRIES:
                                next_attempts = attempts + 1
                                conn.execute(
                                    "UPDATE jobs SET status='pending', "
                                    "retry_count=?, error_message=?, updated_at=? "
                                    "WHERE id=?",
                                    (next_attempts,
                                     f"transient failure, retry {next_attempts}/"
                                     f"{MAX_DOWNLOAD_RETRIES - 1}",
                                     utcnow_iso(), r["job_id"]),
                                )
                                try:
                                    conn.execute(
                                        "UPDATE download_queue SET status='pending', "
                                        "updated_at=? WHERE job_id=?",
                                        (utcnow_iso(), r["job_id"]),
                                    )
                                except sqlite3.OperationalError:
                                    pass
                                conn.commit()
                                log.warning(
                                    f"[PENDING] job {r['job_id']}: download failed; "
                                    f"re-queued (attempt {next_attempts}/"
                                    f"{MAX_DOWNLOAD_RETRIES - 1})."
                                )
                                with self._inflight_lock:
                                    self._inflight_jobs.discard(r["job_id"])
                                continue
                            # Out of retries — terminal failure.
                            conn.execute(
                                "UPDATE jobs SET status='failed', "
                                "error_message=?, updated_at=? "
                                "WHERE id=?",
                                (f"download failed after {MAX_DOWNLOAD_RETRIES - 1} retries",
                                 utcnow_iso(), r["job_id"]),
                            )
                            # Mirror terminal state onto download_queue so the
                            # dashboard's catalog state helper can rely on it
                            # (jobs.status is authoritative; this keeps the two
                            # tables consistent).
                            try:
                                conn.execute(
                                    "UPDATE download_queue SET status='failed', "
                                    "updated_at=? WHERE job_id=?",
                                    (utcnow_iso(), r["job_id"]),
                                )
                            except sqlite3.OperationalError:
                                pass
                            conn.commit()
                        except Exception:
                            try: conn.rollback()
                            except Exception: pass
                            raise
                    finally:
                        conn.close()
                        with self._inflight_lock:
                            self._inflight_jobs.discard(r["job_id"])
                    log.warning(
                        f"[PENDING] job {r['job_id']}: download failed permanently "
                        f"after {MAX_DOWNLOAD_RETRIES - 1} retries."
                    )
                    continue

                # Update job + enrich video metadata
                # NOTE: The block below MUST stay inside the `for fut in
                # as_completed(...)` loop so each successful job gets its
                # status promoted from 'downloading' → 'downloaded' and its
                # webhooks fired. A historical indentation bug placed the
                # try/finally and webhook loop OUTSIDE the for-loop, so only
                # the LAST job per batch was completed and all others stayed
                # pinned in 'downloading' forever (and a SQLite connection
                # was leaked per iteration).
                conn = get_db()
                try:
                    conn.execute(
                        "UPDATE jobs SET status='downloaded', source_file_path=?, "
                        "updated_at=? WHERE id=?",
                        (file_path, utcnow_iso(), r["job_id"]),
                    )
                    v_updates: list[str] = []
                    v_params: list = []
                    # Title comes from yt-dlp's `info` dict at download time;
                    # for dlq-hydrated jobs the videos row may have been created
                    # with an empty title (catalog wasn't hydrated yet) — fix it.
                    if extra.get("title"):
                        v_updates.append("original_title=?")
                        v_params.append(str(extra["title"])[:500])
                    if extra.get("duration"):
                        v_updates.append("duration=?")
                        v_params.append(int(extra["duration"]))
                    if extra.get("description"):
                        v_updates.append("original_description=?")
                        v_params.append(str(extra["description"])[:2000])
                    if extra.get("thumbnail"):
                        v_updates.append("thumbnail_url=?")
                        v_params.append(extra["thumbnail"])
                    if extra.get("upload_date"):
                        v_updates.append("published_at=?")
                        v_params.append(extra["upload_date"])
                    # Engagement metrics (saved at download time so the dashboard
                    # can render Views/Likes without a catalog re-hydration pass).
                    if extra.get("view_count") is not None:
                        try:
                            v_updates.append("view_count=?")
                            v_params.append(int(extra["view_count"]))
                        except (TypeError, ValueError):
                            pass
                    if extra.get("like_count") is not None:
                        try:
                            v_updates.append("like_count=?")
                            v_params.append(int(extra["like_count"]))
                        except (TypeError, ValueError):
                            pass
                    if extra.get("comment_count") is not None:
                        try:
                            v_updates.append("comment_count=?")
                            v_params.append(int(extra["comment_count"]))
                        except (TypeError, ValueError):
                            pass
                    if extra.get("tags"):
                        try:
                            v_updates.append("tags_json=?")
                            v_params.append(json.dumps(extra["tags"])[:4000])
                        except (TypeError, ValueError):
                            pass
                    if extra.get("categories"):
                        try:
                            v_updates.append("categories_json=?")
                            v_params.append(json.dumps(extra["categories"])[:1000])
                        except (TypeError, ValueError):
                            pass
                    if extra.get("language"):
                        v_updates.append("language=?")
                        v_params.append(str(extra["language"])[:32])
                    if v_updates:
                        v_params.append(r["video_pk"])
                        conn.execute(
                            f"UPDATE videos SET {', '.join(v_updates)} WHERE id=?",
                            tuple(v_params),
                        )
                    # Mirror terminal success onto download_queue.
                    try:
                        conn.execute(
                            "UPDATE download_queue SET status='complete', "
                            "updated_at=? WHERE job_id=?",
                            (utcnow_iso(), r["job_id"]),
                        )
                    except sqlite3.OperationalError:
                        pass
                    conn.commit()
                finally:
                    conn.close()
                    with self._inflight_lock:
                        self._inflight_jobs.discard(r["job_id"])

                # Fire webhooks for every destination on the pipeline
                title     = r["title"] or r["video_id"]
                url       = r["source_url"] or f"https://www.youtube.com/watch?v={r['video_id']}"
                channel_dict = {
                    "id":          r["channel_pk"],
                    "name":        r["channel_name"],
                    "channel_id":  r["channel_external_id"],
                    "url":         r["channel_url"],
                    "pipeline_id": r["pipeline_id"],
                }
                dest_pairs = self._filter_dests_by_ledger(
                    self._resolve_webhook_urls(r["pipeline_id"]), r["video_id"]
                )
                for dest_id, webhook_url in dest_pairs:
                    self._fire_webhook(
                        url=webhook_url,
                        destination_id=dest_id,
                        job_id=r["job_id"],
                        pipeline_id=r["pipeline_id"],
                        channel=channel_dict,
                        video_id=r["video_id"],
                        title=title,
                        file_path=file_path,
                        source_url=url,
                        extra=extra,
                        mode="manual",
                    )
                drained += 1
        return drained

    # ------------------------------------------------------------------
    # File cleanup
    # ------------------------------------------------------------------
    def _cleanup_old_downloads(self) -> None:
        if CLEANUP_TTL_HOURS <= 0 or self._dry_run:
            return
        cutoff = time.time() - CLEANUP_TTL_HOURS * 3600
        deleted = 0
        for f in DOWNLOAD_DIR.glob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    log.info(f"Cleaned up: {f.name}")
                    deleted += 1
                except Exception as e:
                    log.warning(f"Could not delete {f.name}: {e}")
        if deleted:
            log.info(f"Cleanup: removed {deleted} file(s).")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        log.info("=" * 60)
        log.info("  project003 Headless Channel Watcher")
        log.info("=" * 60)
        log.info(f"  DB                : {os.environ.get('DB_PATH', '/data/app.db')}")
        log.info(f"  Download dir      : {DOWNLOAD_DIR}")
        log.info(f"  Fallback webhook  : {N8N_WEBHOOK_URL or '(per-destination only)'}")
        log.info(f"  Check interval    : every {CHECK_INTERVAL} minute(s)")
        log.info(f"  Daily upload cap  : {DAILY_UPLOAD_LIMIT} (per channel default)")
        log.info(f"  Cleanup TTL       : {CLEANUP_TTL_HOURS} hour(s)")
        log.info(f"  Dry-run           : {self._dry_run}")
        log.info(f"  Run-once          : {self._run_once}")
        log.info("=" * 60)

        if not self._dry_run:
            init_db()
            # Initial heartbeat — declares the watcher alive immediately,
            # before any potentially-slow startup work.
            self._heartbeat("idle", "booting")
            # Background heartbeat thread keeps the watcher visible even when
            # the main loop is blocked inside a multi-minute download.
            self._hb_thread = threading.Thread(
                target=self._heartbeat_loop,
                name="watcher-heartbeat",
                daemon=True,
            )
            self._hb_thread.start()
            # ── Startup recovery sweep ────────────────────────────────────
            # If a previous watcher process was killed mid-batch, it left
            # rows pinned in status='downloading' (and download_queue rows
            # in 'downloading') that no live thread is touching. Reset them
            # back to 'pending' so the queue can drain on this run.
            try:
                conn = get_db()
                try:
                    cur = conn.execute(
                        "UPDATE jobs SET status='pending', updated_at=? "
                        "WHERE status='downloading'",
                        (utcnow_iso(),),
                    )
                    n_jobs = cur.rowcount or 0
                    try:
                        cur2 = conn.execute(
                            "UPDATE download_queue SET status='pending', updated_at=? "
                            "WHERE status='downloading'",
                            (utcnow_iso(),),
                        )
                        n_dlq = cur2.rowcount or 0
                    except sqlite3.OperationalError:
                        n_dlq = 0
                    conn.commit()
                finally:
                    conn.close()
                if n_jobs or n_dlq:
                    log.warning(
                        f"[startup] Recovered {n_jobs} orphan job(s) and "
                        f"{n_dlq} download_queue row(s) from prior crash "
                        f"(status downloading → pending)."
                    )
            except Exception as e:
                log.error(f"[startup] Recovery sweep failed: {e}", exc_info=True)

        # Decoupled cadence:
        #   - PENDING-JOB DRAIN runs every PENDING_TICK_S seconds (cheap; one
        #     SQL count + drain when there's work). This is what makes manual
        #     enqueues from the dashboard start downloading within ~20s.
        #   - CHANNEL MONITOR runs every CHECK_INTERVAL minutes (expensive;
        #     hits YouTube). Tracked separately via next_monitor_at.
        PENDING_TICK_S = 20
        next_monitor_at = 0.0   # run channel monitor on first iteration
        next_retry_at = 0.0     # run upload-retry sweep on first iteration
        RETRY_SWEEP_S = max(60, int(os.getenv("UPLOAD_RETRY_SWEEP_S", "300")))
        _monitor_thread: Optional[threading.Thread] = None  # background monitor

        while not self._stop_event.is_set():
            now_ts = time.time()
            # Only start a new monitor cycle if no cycle is already running
            monitor_idle = _monitor_thread is None or not _monitor_thread.is_alive()
            run_monitor = now_ts >= next_monitor_at and monitor_idle
            channels = db_get_active_channels(self._channel_filter) if run_monitor else []
            if run_monitor:
                log.info(f"Loaded {len(channels)} active channel(s) from database.")
                self._heartbeat("busy", f"cycle start: {len(channels)} channel(s)")
            else:
                self._heartbeat("busy", "pending-job tick")

            # ── 1. Drain user-queued (manual / dlq-hydrated) pending jobs FIRST.
            # These take priority over background backfill/monitor cycles.
            try:
                # Mid-loop recovery: reset any rows pinned in 'downloading'
                # that no live thread is actually working on. Cheap insurance
                # against missed terminal-state writes.
                self._recover_orphaned_jobs(max_age_minutes=60)
            except Exception as e:
                log.error(f"Mid-loop recovery sweep failed: {e}", exc_info=True)
            try:
                drained = self._drain_pending_jobs(batch=999)
            except Exception as e:
                log.error(f"Error draining pending jobs: {e}", exc_info=True)
                drained = 0

            # ── 1b. Periodically retry stranded uploads (n8n down, dropped
            # webhooks, etc.). Cheap when nothing is stranded.
            if time.time() >= next_retry_at:
                try:
                    n_retry = self._retry_stranded_uploads()
                    if n_retry:
                        log.info(f"[RETRY] re-fired {n_retry} stranded upload webhook(s)")
                except Exception as e:
                    log.error(f"Stranded-upload retry sweep failed: {e}", exc_info=True)
                next_retry_at = time.time() + RETRY_SWEEP_S

            # ── 2. Run channel backfill / monitor cycle (background thread so
            # the pending-job drain keeps ticking every 20s even while a long
            # backfill is running).
            if run_monitor:
                _channels_snapshot = channels  # captured for the thread closure
                def _monitor_worker(ch_list=_channels_snapshot):
                    for channel in ch_list:
                        if self._stop_event.is_set():
                            break
                        try:
                            self._check_channel(channel)
                        except Exception as e:
                            log.error(
                                f"Unexpected error checking '{channel.get('name')}': {e}",
                                exc_info=True,
                            )
                    self._cleanup_old_downloads()
                _monitor_thread = threading.Thread(
                    target=_monitor_worker, daemon=True, name="monitor-cycle"
                )
                _monitor_thread.start()
                next_monitor_at = time.time() + CHECK_INTERVAL * 60

            if self._run_once:
                log.info("Run-once mode — exiting after one cycle.")
                break

            # If we just drained jobs, tick again immediately to keep the
            # pipeline saturated. Otherwise sleep for PENDING_TICK_S so we
            # still notice newly-enqueued manual jobs within ~20 seconds.
            if drained > 0:
                sleep_s = 1
                detail = f"drained={drained}, ticking again"
            else:
                # Sleep until the next pending-job tick or the next monitor
                # cycle, whichever comes first.
                sleep_s = max(1, min(PENDING_TICK_S,
                                     int(next_monitor_at - time.time()) or PENDING_TICK_S))
                detail = (f"idle; next-tick={sleep_s}s; "
                          f"monitor in {max(0, int(next_monitor_at - time.time()))}s")
            if run_monitor:
                log.info(
                    f"Cycle complete at {datetime.now().strftime('%H:%M:%S')}. "
                    f"Next monitor in {CHECK_INTERVAL} minute(s); pending tick every "
                    f"{PENDING_TICK_S}s."
                )
            self._heartbeat("idle", detail)
            self._stop_event.wait(sleep_s)

        log.info("Watcher stopped cleanly.")

    def stop(self) -> None:
        log.info("Shutdown signal received — stopping after current cycle...")
        self._heartbeat("stopped", "shutdown signal")
        self._stop_event.set()


# ===========================================================================
# Entry point
# ===========================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="project003 headless channel watcher")
    p.add_argument("--once", action="store_true", help="Run a single cycle, then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="Inspect-only: no downloads, no DB writes, no webhooks")
    p.add_argument("--channel", type=int, default=None,
                   help="Process only the channel with this DB id")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    watcher = ChannelWatcher(
        dry_run=args.dry_run,
        run_once=args.once,
        channel_filter=args.channel,
    )

    def _handle_signal(signum, frame):
        watcher.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    watcher.run()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
