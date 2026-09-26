"""
project003 — YouTube resumable uploader with live progress.

Runs in a background thread per upload. Every 1 MB chunk:
  - updates `upload_progress` row in DB
  - calls a broadcast callback (for SSE)

When done, writes upload_results row, deletes the progress row,
and marks the job done/partial/failed (caller's job — the API endpoint).
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

try:
    from dashboard.models import get_db
except ModuleNotFoundError:
    from models import get_db

# Lazy imports for googleapis (only present in dashboard container)
_HTTP_CHUNK_SIZE = 1024 * 1024  # 1 MB chunks

# Thumbnail support: yt-dlp downloads thumbnails as siblings of the video file.
# We look for these extensions in the same directory and upload the first match
# to YouTube via youtube.thumbnails().set() after the video upload completes.
# YouTube accepts JPEG/PNG/BMP/GIF up to 2MB. WebP is converted to JPEG
# in-memory using Pillow (added to dashboard Dockerfile).
_THUMB_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_THUMB_MAX_BYTES = 2 * 1024 * 1024  # 2 MB YouTube limit


def _find_sibling_thumbnail(video_path: str) -> Optional[str]:
    """Return path to a thumbnail in the same directory as ``video_path``,
    preferring already-supported formats (.jpg, .png) over .webp.
    Returns None if no thumbnail file is found.
    """
    try:
        d = os.path.dirname(video_path)
        if not d or not os.path.isdir(d):
            return None
        # Two-pass: first prefer non-webp, then fall back to webp.
        for ext in (".jpg", ".jpeg", ".png"):
            for f in os.listdir(d):
                if f.lower().endswith(ext):
                    return os.path.join(d, f)
        for f in os.listdir(d):
            if f.lower().endswith(".webp"):
                return os.path.join(d, f)
    except Exception:
        pass
    return None


def _ensure_jpeg_thumbnail(thumb_path: str) -> Optional[str]:
    """If ``thumb_path`` is already JPEG/PNG and <= 2MB, return it as-is.
    Otherwise convert (or compress) to a JPEG sibling and return that path.
    Returns None if conversion fails (Pillow missing, unreadable, etc.).
    """
    try:
        size = os.path.getsize(thumb_path)
        ext = os.path.splitext(thumb_path)[1].lower()
        if ext in (".jpg", ".jpeg", ".png") and size <= _THUMB_MAX_BYTES:
            return thumb_path
        # Need conversion (webp) or compression (over 2MB).
        from PIL import Image  # local import — Pillow only in dashboard image
        # Write to /tmp because the downloads volume is mounted read-only
        # in the dashboard container (the watcher owns writes).
        import tempfile
        fd, out = tempfile.mkstemp(prefix="yt_thumb_", suffix=".jpg")
        os.close(fd)
        with Image.open(thumb_path) as im:
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGB")
            quality = 90
            im.save(out, "JPEG", quality=quality, optimize=True)
            # If still too big, drop quality progressively.
            while os.path.getsize(out) > _THUMB_MAX_BYTES and quality > 50:
                quality -= 10
                im.save(out, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(out) > _THUMB_MAX_BYTES:
            try:
                os.remove(out)
            except Exception:
                pass
            return None  # giving up — user will see no thumbnail set
        return out
    except Exception as e:
        print(f"[uploader] thumbnail conversion failed: "
              f"{type(e).__name__}: {e}", flush=True)
        return None


def _set_youtube_thumbnail(youtube, video_id: str, video_path: str) -> str:
    """Try to set a custom thumbnail on the freshly uploaded video.
    Returns a short status string for logging. Never raises — a thumbnail
    failure must not fail the whole upload.
    """
    if not video_id:
        return "skip:no-video-id"
    raw = _find_sibling_thumbnail(video_path)
    if not raw:
        return "skip:no-sibling-thumbnail"
    final = _ensure_jpeg_thumbnail(raw)
    if not final:
        return "skip:conversion-failed"
    try:
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(final, mimetype="image/jpeg", resumable=False)
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        return f"ok:{os.path.basename(final)}"
    except Exception as e:
        return f"fail:{type(e).__name__}:{str(e)[:120]}"
    finally:
        # Clean up the temp converted JPEG (only if we created one in /tmp).
        if final and final != raw and final.startswith("/tmp/yt_thumb_"):
            try:
                os.remove(final)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Public state
# ---------------------------------------------------------------------------

# Cancel flags: { (job_id, destination_id): True } — uploader checks between chunks.
_CANCEL_FLAGS: dict[tuple[int, int], bool] = {}
_CANCEL_LOCK = threading.Lock()

# Single-worker queue lock (process one upload at a time → respects YT quota).
_UPLOAD_LOCK = threading.Lock()


def request_cancel(job_id: int, destination_id: int) -> None:
    with _CANCEL_LOCK:
        _CANCEL_FLAGS[(job_id, destination_id)] = True


def _is_canceled(job_id: int, destination_id: int) -> bool:
    with _CANCEL_LOCK:
        return _CANCEL_FLAGS.get((job_id, destination_id), False)


def _clear_cancel(job_id: int, destination_id: int) -> None:
    with _CANCEL_LOCK:
        _CANCEL_FLAGS.pop((job_id, destination_id), None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Quota tracking (YouTube Data API daily quota)
# ---------------------------------------------------------------------------
# YouTube quota resets at midnight Pacific Time (US/Pacific = UTC-8 standard,
# UTC-7 daylight). We approximate as next 08:00 UTC — close enough for
# deferral purposes (off by at most 1 hour during DST transitions).
def _next_quota_reset_iso() -> str:
    now = datetime.utcnow()
    reset = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= reset:
        reset = reset + timedelta(days=1)
    return reset.strftime("%Y-%m-%dT%H:%M:%S")


def _is_quota_exceeded_error(exc: BaseException) -> bool:
    """True if the exception looks like a YouTube quota-exceeded HttpError.

    Catches three distinct YouTube-side limits:
      * HTTP 403 quotaExceeded — Google Cloud project daily API quota
      * HTTP 403 with 'quota' in message — same, alternate format
      * HTTP 400 'uploadLimitExceeded' / 'number of videos they may upload' —
        per-CHANNEL daily upload count limit (15/day for unverified channels).
        Adding more Google Cloud projects does NOT help with this — the limit
        is per YouTube channel. Defer until tomorrow.
    """
    msg = str(exc).lower()
    if "quotaexceeded" in msg or "quota exceeded" in msg or "daily limit" in msg:
        return True
    if "uploadlimitexceeded" in msg or "number of videos they may upload" in msg:
        return True
    # googleapiclient.errors.HttpError has a `resp.status` attribute.
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 403 and "quota" in msg:
        return True
    if status == 400 and ("upload" in msg and ("limit" in msg or "exceed" in msg)):
        return True
    return False


def _is_quota_currently_exceeded(destination_id: int) -> bool:
    """True if this destination has an active quota-exceeded marker that
    has not yet expired. Returns False on any DB error (fail-open)."""
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT quota_resets_at FROM destination_quota WHERE destination_id=?",
                (destination_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row or not row["quota_resets_at"]:
            return False
        return row["quota_resets_at"] > _utcnow_iso()
    except Exception:
        return False


def _mark_quota_exceeded(destination_id: int) -> str:
    """Record that this destination hit quota. Returns the ISO reset time."""
    reset_at = _next_quota_reset_iso()
    try:
        conn = get_db()
        try:
            conn.execute(
                """INSERT INTO destination_quota
                        (destination_id, quota_exceeded_at, quota_resets_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(destination_id) DO UPDATE SET
                        quota_exceeded_at = excluded.quota_exceeded_at,
                        quota_resets_at   = excluded.quota_resets_at,
                        updated_at        = excluded.updated_at""",
                (destination_id, _utcnow_iso(), reset_at, _utcnow_iso()),
            )
        finally:
            conn.close()
    except Exception:
        pass
    return reset_at


def _clear_quota_marker(destination_id: int) -> None:
    """Clear quota markers for this destination (called by the retry sweep
    once the reset time has passed). Best-effort."""
    try:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE destination_quota "
                "   SET quota_exceeded_at = NULL, "
                "       quota_resets_at   = NULL, "
                "       updated_at        = ? "
                " WHERE destination_id = ?",
                (_utcnow_iso(), destination_id),
            )
        finally:
            conn.close()
    except Exception:
        pass


def sweep_deferred_uploads(
    broadcast: Optional[Callable[[str, dict], None]] = None,
) -> int:
    """Re-trigger upload for any destinations whose quota has reset.

    Scans `upload_results` for rows with status='deferred' whose destination
    has either no active quota marker or a `quota_resets_at` that has passed.
    For each such row:
      * delete the deferred result row + matching ledger row
      * clear the quota marker for the destination
      * call `upload_youtube_async()` to re-upload

    Returns the number of uploads re-queued. Safe to call concurrently with
    in-flight uploads (uploader holds `_UPLOAD_LOCK`).
    """
    now = _utcnow_iso()
    requeued = 0
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT ur.id            AS result_id,
                      ur.job_id         AS job_id,
                      ur.destination_id AS destination_id,
                      ur.ai_used        AS ai_used,
                      ur.ai_title       AS ai_title,
                      ur.ai_description AS ai_description,
                      ur.ai_tags        AS ai_tags,
                      v.original_title  AS title,
                      v.youtube_video_id AS yvid,
                      j.source_file_path AS source_file_path,
                      jo.file_path      AS output_path,
                      d.default_privacy AS default_privacy,
                      dq.quota_resets_at AS quota_resets_at
                 FROM upload_results ur
                 JOIN jobs j         ON j.id = ur.job_id
                 JOIN videos v       ON v.id = j.video_id
                 JOIN destinations d ON d.id = ur.destination_id
                 LEFT JOIN job_outputs jo
                        ON jo.job_id = ur.job_id
                       AND jo.destination_id = ur.destination_id
                 LEFT JOIN destination_quota dq
                        ON dq.destination_id = ur.destination_id
                WHERE ur.status = 'deferred'
                  AND (dq.quota_resets_at IS NULL
                       OR dq.quota_resets_at <= ?)
                ORDER BY ur.id ASC""",
            (now,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    # Group by destination so we only clear each marker once.
    cleared: set[int] = set()

    for r in rows:
        job_id = int(r["job_id"])
        dest_id = int(r["destination_id"])
        result_id = int(r["result_id"])
        file_path = r["output_path"] or r["source_file_path"] or ""
        if not file_path:
            print(f"[retry-sweep] job={job_id} dest={dest_id} skipped: no file_path",
                  flush=True)
            continue

        # Clear the deferred result row + matching ledger row + quota marker.
        conn = get_db()
        try:
            conn.execute("DELETE FROM upload_results WHERE id = ?", (result_id,))
            yvid = r["yvid"] or ""
            if yvid:
                conn.execute(
                    "DELETE FROM upload_ledger "
                    " WHERE video_id = ? AND destination_id = ? "
                    "   AND status IN ('failed', 'removed')",
                    (yvid, dest_id),
                )
            conn.execute(
                "UPDATE jobs SET status = 'uploading' WHERE id = ?", (job_id,)
            )
        finally:
            conn.close()

        if dest_id not in cleared:
            _clear_quota_marker(dest_id)
            cleared.add(dest_id)

        try:
            ai_tags_list = json.loads(r["ai_tags"] or "[]")
            if not isinstance(ai_tags_list, list):
                ai_tags_list = []
        except Exception:
            ai_tags_list = []

        ai_used = bool(r["ai_used"])
        ai_title = r["ai_title"] or ""
        ai_description = r["ai_description"] or ""
        final_title = ai_title or (r["title"] or "Untitled")
        description = ai_description or ""
        tags = ai_tags_list
        privacy_status = (r["default_privacy"] or "").strip() or "unlisted"

        print(f"[retry-sweep] re-queueing job={job_id} dest={dest_id} "
              f"file={file_path}", flush=True)

        upload_youtube_async(
            job_id=job_id,
            destination_id=dest_id,
            file_path=file_path,
            title=final_title,
            description=description,
            tags=tags,
            category_id="22",
            privacy_status=privacy_status,
            ai_used=ai_used,
            ai_title=ai_title,
            ai_description=ai_description,
            ai_tags=ai_tags_list,
            broadcast=broadcast,
        )
        requeued += 1

    return requeued


def _cleanup_local_files(file_path: str) -> str:
    """Delete the uploaded video + the entire per-video folder it lives in.
    Returns a short status string for logging. Best-effort, never raises."""
    if os.getenv("AUTO_CLEANUP_AFTER_UPLOAD", "1") != "1":
        return "disabled"
    try:
        if not file_path or not os.path.isfile(file_path):
            return "no-file"
        folder = os.path.dirname(file_path)
        # Safety guard: only nuke folders under the downloads mount.
        roots = ("/shared/downloads/", "/downloads/")
        if not any(folder.startswith(r) for r in roots):
            return f"unsafe-path:{folder}"
        # Remove the whole per-video folder (mp4 + thumb + subs + json).
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        return f"removed:{folder}"
    except Exception as e:
        return f"error:{type(e).__name__}:{e}"


def _upsert_progress(
    job_id: int,
    destination_id: int,
    **fields,
) -> None:
    """Insert or update the live-progress row."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM upload_progress WHERE job_id=? AND destination_id=?",
            (job_id, destination_id),
        ).fetchone()
        fields["updated_at"] = _utcnow_iso()
        if existing:
            cols = ", ".join(f"{k}=?" for k in fields)
            params = list(fields.values()) + [existing["id"]]
            conn.execute(f"UPDATE upload_progress SET {cols} WHERE id=?", params)
        else:
            fields["job_id"] = job_id
            fields["destination_id"] = destination_id
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            conn.execute(
                f"INSERT INTO upload_progress ({cols}) VALUES ({placeholders})",
                list(fields.values()),
            )
    finally:
        conn.close()


def _delete_progress(job_id: int, destination_id: int) -> None:
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM upload_progress WHERE job_id=? AND destination_id=?",
            (job_id, destination_id),
        )
    finally:
        conn.close()


def _record_result(
    job_id: int,
    destination_id: int,
    platform: str,
    status: str,
    upload_url: str = "",
    error_message: str = "",
    ai_used: bool = False,
    ai_title: str = "",
    ai_description: str = "",
    ai_tags: Optional[list] = None,
) -> None:
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO upload_results
                    (job_id, destination_id, platform, status, upload_url, error_message,
                     ai_used, ai_title, ai_description, ai_tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id, destination_id, platform, status,
                upload_url, error_message,
                1 if ai_used else 0,
                ai_title or "", ai_description or "",
                json.dumps(ai_tags or []),
            ),
        )
        # Mirror into upload_ledger so the catalog "uploaded" badge reflects
        # cron uploads in real time. Idempotent via UNIQUE(video_id, destination_id);
        # we use INSERT OR IGNORE then UPDATE to refresh status on retries.
        try:
            row = conn.execute(
                """SELECT v.youtube_video_id AS yvid
                     FROM jobs j
                     LEFT JOIN videos v ON v.id = j.video_id
                    WHERE j.id = ?""",
                (job_id,),
            ).fetchone()
            yvid = (row["yvid"] if row else "") or ""
            if yvid:
                # Ledger CHECK constraint only allows queued/uploading/
                # uploaded/failed/removed. Map 'deferred' -> 'failed' so the
                # row is recorded; the retry sweep will overwrite it with
                # 'uploaded' once the destination's quota resets.
                if status in ("uploaded", "success"):
                    ledger_status = "uploaded"
                else:
                    ledger_status = "failed"
                conn.execute(
                    """INSERT OR IGNORE INTO upload_ledger
                            (video_id, destination_id, job_id, status,
                             destination_url, uploaded_at, error_message,
                             triggered_by)
                       VALUES (?, ?, ?, ?, ?,
                               strftime('%Y-%m-%dT%H:%M:%S', 'now'), ?, 'cron')""",
                    (yvid, destination_id, job_id, ledger_status,
                     upload_url or "", error_message or ""),
                )
                # If a row already existed (e.g. earlier failure), refresh it
                conn.execute(
                    """UPDATE upload_ledger
                          SET status = ?, job_id = ?, destination_url = ?,
                              error_message = ?,
                              uploaded_at = strftime('%Y-%m-%dT%H:%M:%S', 'now'),
                              updated_at  = strftime('%Y-%m-%dT%H:%M:%S', 'now')
                        WHERE video_id = ? AND destination_id = ?""",
                    (ledger_status, job_id, upload_url or "",
                     error_message or "", yvid, destination_id),
                )
        except Exception:
            # Ledger mirroring must never break the upload pipeline.
            pass
    finally:
        conn.close()


def _finalize_job_status(job_id: int) -> str:
    """Mark job done/partial/failed based on total destinations vs upload_results."""
    conn = get_db()
    try:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            return ""
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM destinations WHERE pipeline_id=? AND enabled=1",
            (job["pipeline_id"],),
        ).fetchone()["n"]
        done = conn.execute(
            "SELECT COUNT(*) AS n FROM upload_results WHERE job_id=?", (job_id,)
        ).fetchone()["n"]
        succ = conn.execute(
            "SELECT COUNT(*) AS n FROM upload_results "
            "WHERE job_id=? AND status IN ('uploaded','success')",
            (job_id,),
        ).fetchone()["n"]
        deferred = conn.execute(
            "SELECT COUNT(*) AS n FROM upload_results "
            "WHERE job_id=? AND status='deferred'",
            (job_id,),
        ).fetchone()["n"]
        if total > 0 and done >= total:
            if succ == total:
                new_status = "done"
            elif deferred > 0 and (succ + deferred) == total:
                # All non-success outcomes are quota deferrals — retry later.
                new_status = "deferred"
            elif succ > 0:
                new_status = "partial"
            else:
                new_status = "failed"
        else:
            new_status = "uploading"
        if new_status in ("failed", "partial"):
            err_row = conn.execute(
                "SELECT error_message FROM upload_results "
                "WHERE job_id=? AND status NOT IN ('uploaded','success') "
                "AND COALESCE(error_message,'') <> '' "
                "ORDER BY id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            err_msg = (err_row["error_message"] if err_row else "") or ""
            conn.execute(
                "UPDATE jobs SET status=?, error_message=? WHERE id=?",
                (new_status, err_msg, job_id),
            )
        else:
            conn.execute("UPDATE jobs SET status=? WHERE id=?", (new_status, job_id))
        # PR6: auto-delete disabled by user — do not delete local files after upload.
        # if new_status == "done":
        #     _maybe_archive_and_cleanup(conn, job_id, job["pipeline_id"])
        return new_status
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PR6: auto-delete after all-destinations-uploaded + mark video archived
# ---------------------------------------------------------------------------
#
# Called from _finalize_job_status (in-process YouTube path) and from
# /api/upload/result (cron / n8n callback path) once a job reaches
# 'done'. Idempotent — re-running on an already-archived video is a no-op.
# Set videos.archived_at FIRST, files SECOND: even if the file delete
# fails (permission, race), the archive marker remains so the watcher
# never re-downloads.

# Sidecar extensions to nuke alongside the main video file. Anything not
# on this list is left in place so we never accidentally trash unrelated
# content the user dropped into the same folder.
_AUTODELETE_EXTS = (
    ".mp4", ".mkv", ".webm", ".mov", ".m4v",
    ".info.json", ".description",
    ".jpg", ".jpeg", ".png", ".webp",
    ".vtt", ".srt", ".ass",
    ".part", ".ytdl",
)

# Subfolder names yt-dlp / our pipeline create per job. Removed only when
# they end up empty after the per-file pass.
_AUTODELETE_FOLDER_PREFIXES = ("job_",)


def _maybe_archive_and_cleanup(conn, job_id: int, pipeline_id: int) -> None:
    """If the pipeline opts in, archive the video and delete its files.

    Pre-conditions enforced by caller: job already marked 'done' (every
    enabled destination produced an 'uploaded' upload_results row).
    """
    pl = conn.execute(
        "SELECT auto_delete_after_upload FROM pipelines WHERE id = ?",
        (pipeline_id,),
    ).fetchone()
    if not pl or not int(pl["auto_delete_after_upload"] or 0):
        return  # feature off for this pipeline
    job = conn.execute(
        "SELECT id, video_id, source_file_path FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not job:
        return
    video_id = job["video_id"]
    file_path = job["source_file_path"] or ""
    # 1. Mark archived BEFORE touching disk — this guarantees the watcher
    #    won't re-download even if the rmtree below trips on a perm error.
    if video_id:
        conn.execute(
            "UPDATE videos SET archived_at = "
            "strftime('%Y-%m-%dT%H:%M:%S', 'now') "
            "WHERE id = ? AND COALESCE(archived_at, '') = ''",
            (video_id,),
        )
    # 2. Delete files on disk. Translate /downloads/... to host path.
    removed = _delete_video_files(file_path)
    print(f"[autodelete] job={job_id} video_id={video_id} archived; "
          f"removed {removed} item(s) under '{file_path}'", flush=True)


def _delete_video_files(source_file_path: str) -> int:
    """Best-effort delete of the main file + sidecars + empty folder.

    Returns count of filesystem entries (files + dirs) that were removed.
    Safe to call with an empty / missing path.
    """
    if not source_file_path:
        return 0
    # Translate the in-container ledger path to the actual mount root.
    downloads_root = os.getenv("DOWNLOADS_DIR", "/shared/downloads")
    fp = source_file_path
    if fp.startswith("/downloads/"):
        fp = downloads_root.rstrip("/") + fp[len("/downloads"):]
    if not os.path.isabs(fp):
        return 0
    folder = os.path.dirname(fp)
    if not folder or not os.path.isdir(folder):
        return 0
    removed = 0
    # Pass 1: remove every file in the folder whose extension matches our
    # allow-list (lower-cased compare; handles ".info.json" via endswith).
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for nm in names:
        full = os.path.join(folder, nm)
        if not os.path.isfile(full):
            continue
        low = nm.lower()
        if any(low.endswith(ext) for ext in _AUTODELETE_EXTS):
            try:
                os.remove(full)
                removed += 1
            except OSError:
                pass
    # Pass 2: rmdir the per-video folder ONLY if it is now empty. This
    # guarantees we never blow away a folder the user (or a future
    # plugin) populated with unrelated files.
    try:
        if not os.listdir(folder):
            os.rmdir(folder)
            removed += 1
    except OSError:
        pass
    # Pass 3: also clean up any sibling job_xxx/ folder that yt-dlp may
    # have left behind under the same channel directory.
    try:
        parent = os.path.dirname(folder)
        if parent and os.path.isdir(parent):
            for nm in os.listdir(parent):
                full = os.path.join(parent, nm)
                if (os.path.isdir(full)
                        and any(nm.startswith(p) for p in _AUTODELETE_FOLDER_PREFIXES)
                        and not os.listdir(full)):
                    try:
                        os.rmdir(full)
                        removed += 1
                    except OSError:
                        pass
    except OSError:
        pass
    return removed


# ---------------------------------------------------------------------------
# OAuth credentials loader (uses the dashboard's stored token)
# ---------------------------------------------------------------------------

def _load_youtube_credentials(project_id: Optional[int] = None):
    """Load a stored YouTube OAuth token (refreshing if expired).

    If `project_id` is given, load the token authorized for that specific
    Google Cloud project, and use that project's client_id/client_secret.
    Otherwise behaves like the legacy single-token loader (newest row,
    env-var client credentials).
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest

    conn = get_db()
    try:
        if project_id:
            row = conn.execute(
                "SELECT * FROM oauth_tokens WHERE platform='youtube' AND project_id=? "
                "ORDER BY id DESC LIMIT 1",
                (int(project_id),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM oauth_tokens WHERE platform='youtube' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
    finally:
        conn.close()
    if not row:
        if project_id:
            raise RuntimeError(
                f"No YouTube OAuth token stored for project id={project_id}. "
                f"Visit /projects to authorize that project."
            )
        raise RuntimeError(
            "No YouTube OAuth token stored. "
            "Visit /oauth/youtube/start in the dashboard to authorize."
        )

    # Resolve client_id/client_secret: prefer the project bound to the token,
    # falling back to env vars for legacy tokens with project_id IS NULL.
    client_id = client_secret = ""
    token_project_id = row["project_id"] if "project_id" in row.keys() else None
    if token_project_id:
        try:
            from dashboard import projects as _yt_projects  # type: ignore
        except ModuleNotFoundError:
            import projects as _yt_projects  # type: ignore
        proj = _yt_projects.get_project(int(token_project_id))
        if proj:
            client_id = proj["client_id"]
            client_secret = proj["client_secret"]
    if not (client_id and client_secret):
        client_id     = os.getenv("YOUTUBE_CLIENT_ID", "")
        client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    if not (client_id and client_secret):
        raise RuntimeError(
            "No OAuth client credentials available "
            "(no project bound and YOUTUBE_CLIENT_ID/SECRET env vars not set)."
        )

    expiry = None
    if row["token_expiry"]:
        try:
            expiry = datetime.fromisoformat(row["token_expiry"].replace("Z", ""))
        except Exception:
            expiry = None

    creds = Credentials(
        token=row["access_token"],
        refresh_token=row["refresh_token"] or None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=(row["scopes"] or "").split() or ["https://www.googleapis.com/auth/youtube.upload"],
    )
    if expiry:
        creds.expiry = expiry

    if not creds.valid:
        if creds.refresh_token:
            try:
                creds.refresh(GoogleRequest())
            except Exception as refresh_exc:                          # noqa: BLE001
                # Most common dead-token reasons:
                #   * invalid_grant — refresh token revoked, expired
                #     (7-day Testing-mode), or owner removed access
                #   * invalid_client — OAuth client secret rotated/deleted
                # Mark the row so the dashboard can prompt for re-auth
                # instead of retrying every upload.
                err_msg = str(refresh_exc)
                conn2 = get_db()
                try:
                    conn2.execute(
                        "UPDATE oauth_tokens SET needs_reauth=1, "
                        "last_error=?, updated_at=? WHERE id=?",
                        (err_msg[:500], _utcnow_iso(), row["id"]),
                    )
                finally:
                    conn2.close()
                raise RuntimeError(
                    f"OAuth refresh failed for token id={row['id']} "
                    f"(project_id={token_project_id}): {err_msg}. "
                    f"Visit /projects and click 'Reconnect' to re-authorize."
                ) from refresh_exc
            # Persist the new access token + expiry, stamp last_refreshed_at,
            # and clear any previous needs_reauth flag (token just healed).
            conn = get_db()
            try:
                conn.execute(
                    "UPDATE oauth_tokens SET access_token=?, token_expiry=?, "
                    "last_refreshed_at=?, updated_at=?, "
                    "needs_reauth=0, last_error='' "
                    "WHERE id=?",
                    (
                        creds.token,
                        creds.expiry.strftime("%Y-%m-%dT%H:%M:%S") if creds.expiry else "",
                        _utcnow_iso(),
                        _utcnow_iso(),
                        row["id"],
                    ),
                )
            finally:
                conn.close()
        else:
            raise RuntimeError("OAuth token expired and no refresh token available — re-authorize.")

    return creds


# ---------------------------------------------------------------------------
# Main upload entry point
# ---------------------------------------------------------------------------

def upload_youtube_async(
    job_id: int,
    destination_id: int,
    file_path: str,
    title: str,
    description: str = "",
    tags: Optional[list] = None,
    category_id: str = "22",
    privacy_status: str = "unlisted",
    ai_used: bool = False,
    ai_title: str = "",
    ai_description: str = "",
    ai_tags: Optional[list] = None,
    broadcast: Optional[Callable[[str, dict], None]] = None,
    overrides: Optional[dict] = None,
) -> threading.Thread:
    """Spawn a background upload thread. Returns the thread (already started).

    overrides (PR7+): per-call overrides that win over per-destination DB
    defaults. Recognized keys (any may be omitted = use destination default):
      comments_enabled   : bool
      made_for_kids      : bool
      embeddable         : bool
      notify_subscribers : bool
      tags_extra         : list[str]   (appended on top of dest default_tags)
      category_id        : str         (numeric YouTube category)
    """
    t = threading.Thread(
        target=_upload_youtube_worker,
        args=(job_id, destination_id, file_path, title, description, tags or [],
              category_id, privacy_status,
              ai_used, ai_title, ai_description, ai_tags or [],
              broadcast, overrides or {}),
        daemon=True,
        name=f"yt-upload-{job_id}-{destination_id}",
    )
    t.start()
    return t


def _upload_youtube_worker(
    job_id: int,
    destination_id: int,
    file_path: str,
    title: str,
    description: str,
    tags: list,
    category_id: str,
    privacy_status: str,
    ai_used: bool,
    ai_title: str,
    ai_description: str,
    ai_tags: list,
    broadcast: Optional[Callable[[str, dict], None]],
    overrides: Optional[dict] = None,
) -> None:
    def _bcast(event: str, data: dict) -> None:
        if broadcast:
            try:
                broadcast(event, data)
            except Exception:
                pass

    # Acquire single-worker lock so uploads run sequentially.
    with _UPLOAD_LOCK:
        try:
            _clear_cancel(job_id, destination_id)

            # Pre-flight: if this destination is currently quota-exceeded,
            # defer the upload instead of consuming an API call.
            if _is_quota_currently_exceeded(destination_id):
                msg = "YouTube quota exceeded; deferred until quota resets."
                _record_result(
                    job_id, destination_id, "youtube", "deferred",
                    error_message=msg,
                    ai_used=ai_used, ai_title=ai_title,
                    ai_description=ai_description, ai_tags=ai_tags,
                )
                _bcast("upload_done", {
                    "job_id": job_id, "destination_id": destination_id,
                    "platform": "youtube", "status": "deferred",
                    "error": msg, "title": title,
                })
                return

            # Resolve & validate file.
            file_path = (file_path or "").replace("\\", "/")
            # Translate watcher path -> dashboard mount.
            if file_path.startswith("/downloads/"):
                file_path = "/shared/downloads/" + file_path[len("/downloads/"):]

            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            bytes_total = os.path.getsize(file_path)
            _upsert_progress(
                job_id, destination_id,
                platform="youtube",
                title=title,
                file_path=file_path,
                bytes_total=bytes_total,
                bytes_uploaded=0,
                speed_bps=0,
                eta_seconds=0,
                stage="starting",
                started_at=_utcnow_iso(),
            )
            _bcast("progress", {
                "job_id": job_id, "destination_id": destination_id,
                "stage": "starting", "title": title,
                "bytes_total": bytes_total, "bytes_uploaded": 0,
                "percent": 0.0, "speed_bps": 0, "eta_seconds": 0,
            })

            # ---- Build YouTube client ----
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            # Pick the next available Google Cloud project (rotation).
            # Falls back to legacy single-token mode if no projects configured.
            try:
                from dashboard import projects as _yt_projects  # type: ignore
            except ModuleNotFoundError:
                import projects as _yt_projects  # type: ignore
            # If the destination is bound to a specific YouTube channel,
            # restrict rotation to projects authorized for THAT channel —
            # otherwise we risk uploading to the wrong channel under a
            # multi-channel account. Falls back to global picker when
            # the destination predates the youtube_channel_id column.
            dest_channel_id: Optional[int] = None
            try:
                _conn = get_db()
                try:
                    _drow = _conn.execute(
                        "SELECT youtube_channel_id FROM destinations WHERE id=?",
                        (destination_id,),
                    ).fetchone()
                    if _drow and _drow["youtube_channel_id"]:
                        dest_channel_id = int(_drow["youtube_channel_id"])
                finally:
                    _conn.close()
            except Exception:
                dest_channel_id = None
            if dest_channel_id:
                picked_project = _yt_projects.pick_active_project_for_channel(
                    dest_channel_id
                )
            else:
                picked_project = _yt_projects.pick_active_project()
            if picked_project is None and _yt_projects.list_projects():
                # Projects exist but all are exhausted/inactive.
                msg = ("All configured YouTube projects have hit their daily "
                       "upload cap. Add another project on /projects or wait "
                       "for the next quota reset (08:00 UTC).")
                _record_result(
                    job_id, destination_id, "youtube", "deferred",
                    error_message=msg,
                    ai_used=ai_used, ai_title=ai_title,
                    ai_description=ai_description, ai_tags=ai_tags,
                )
                _delete_progress(job_id, destination_id)
                _bcast("upload_done", {
                    "job_id": job_id, "destination_id": destination_id,
                    "platform": "youtube", "status": "deferred",
                    "error": msg, "title": title,
                })
                return

            project_id_used = picked_project["id"] if picked_project else None
            if picked_project:
                print(
                    f"[uploader] job={job_id} using project "
                    f"id={project_id_used} '{picked_project['label']}' "
                    f"({picked_project['uploads_today']}/{picked_project['daily_cap']} today)",
                    flush=True,
                )

            creds = _load_youtube_credentials(project_id=project_id_used)
            youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

            # ---- PR7: pull per-destination upload defaults --------------
            # Done here so we don't need to thread 6 extra kwargs through
            # every call site. Falls back to YouTube's platform defaults
            # if columns are missing (legacy DB) or rows are NULL.
            dest_opts = {
                "comments_enabled":   True,
                "made_for_kids":      False,
                "tags_extra":         [],
                "category_id":        None,
                "embeddable":         True,
                "notify_subscribers": True,
            }
            try:
                conn_d = get_db()
                drow = conn_d.execute(
                    "SELECT default_comments_enabled, default_made_for_kids, "
                    "       default_tags, default_category_id, "
                    "       default_embeddable, default_notify_subscribers "
                    "  FROM destinations WHERE id = ?",
                    (destination_id,),
                ).fetchone()
                if drow:
                    dest_opts["comments_enabled"]   = bool(drow["default_comments_enabled"])
                    dest_opts["made_for_kids"]      = bool(drow["default_made_for_kids"])
                    raw_tags = (drow["default_tags"] or "").strip()
                    if raw_tags:
                        dest_opts["tags_extra"] = [
                            t.strip() for t in raw_tags.split(",") if t.strip()
                        ]
                    cid = (drow["default_category_id"] or "").strip()
                    if cid:
                        dest_opts["category_id"] = cid
                    dest_opts["embeddable"]         = bool(drow["default_embeddable"])
                    dest_opts["notify_subscribers"] = bool(drow["default_notify_subscribers"])
            except Exception as _e:                              # noqa: BLE001
                print(f"[uploader] dest opts fallback ({type(_e).__name__}): {_e}",
                      flush=True)

            # PR7+: apply per-call overrides on top of per-destination defaults.
            ov = overrides or {}
            for k in ("comments_enabled", "made_for_kids",
                      "embeddable", "notify_subscribers"):
                if k in ov and ov[k] is not None:
                    dest_opts[k] = bool(ov[k])
            if ov.get("category_id"):
                dest_opts["category_id"] = str(ov["category_id"]).strip()
            ov_extra = ov.get("tags_extra")
            if isinstance(ov_extra, list) and ov_extra:
                # Append after the destination's tags_extra so user-supplied
                # batch tags come last (after AI tags + dest defaults).
                dest_opts["tags_extra"] = list(dest_opts["tags_extra"]) + list(ov_extra)

            # Merge tags: caller-provided tags first, then per-destination
            # extras, de-duplicated case-insensitively while preserving order.
            merged_tags = list(tags or [])
            seen_lower = {t.lower() for t in merged_tags}
            for t in dest_opts["tags_extra"]:
                if t.lower() not in seen_lower:
                    merged_tags.append(t)
                    seen_lower.add(t.lower())
            effective_category = dest_opts["category_id"] or str(category_id)

            body = {
                "snippet": {
                    "title": (title or "Untitled")[:100],
                    "description": description or "",
                    "tags": merged_tags,
                    "categoryId": effective_category,
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": dest_opts["made_for_kids"],
                    "embeddable": dest_opts["embeddable"],
                },
            }

            media = MediaFileUpload(
                file_path,
                chunksize=_HTTP_CHUNK_SIZE,
                resumable=True,
                mimetype="video/*",
            )

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
                notifySubscribers=dest_opts["notify_subscribers"],
            )
            # NOTE on comments_enabled: YouTube Data API v3 does NOT expose a
            # per-video "disable comments" field on videos.insert / .update.
            # That setting lives in YouTube Studio (or the deprecated Partner
            # API). We persist the flag on the destination so downstream
            # n8n workflows / a future Studio-cookie integration can apply
            # it; here we only log when it's OFF so the user knows to act.
            if not dest_opts["comments_enabled"]:
                print(
                    f"[uploader] job={job_id} dest={destination_id} "
                    f"comments_enabled=False stored — apply manually in "
                    f"YouTube Studio or via n8n (not exposed by Data API v3).",
                    flush=True,
                )

            # ---- Chunked upload loop ----
            response = None
            t_start = time.monotonic()
            t_last = t_start
            bytes_last = 0

            _upsert_progress(job_id, destination_id, stage="uploading")

            while response is None:
                if _is_canceled(job_id, destination_id):
                    _upsert_progress(job_id, destination_id, stage="canceled",
                                     error_message="Canceled by user")
                    _bcast("progress", {
                        "job_id": job_id, "destination_id": destination_id,
                        "stage": "canceled",
                    })
                    _record_result(job_id, destination_id, "youtube", "failed",
                                   error_message="Canceled by user",
                                   ai_used=ai_used, ai_title=ai_title,
                                   ai_description=ai_description, ai_tags=ai_tags)
                    _delete_progress(job_id, destination_id)
                    new_status = _finalize_job_status(job_id)
                    _bcast("job_update", {"job_id": job_id, "status": new_status})
                    return

                status, response = request.next_chunk(num_retries=3)
                now = time.monotonic()
                if status:
                    bytes_uploaded = status.resumable_progress
                    elapsed = max(now - t_last, 0.001)
                    speed_bps = int((bytes_uploaded - bytes_last) / elapsed) if elapsed > 0 else 0
                    remain = max(bytes_total - bytes_uploaded, 0)
                    eta = int(remain / speed_bps) if speed_bps > 0 else 0
                    bytes_last = bytes_uploaded
                    t_last = now
                    pct = (bytes_uploaded / bytes_total * 100) if bytes_total else 0.0

                    _upsert_progress(
                        job_id, destination_id,
                        bytes_uploaded=bytes_uploaded,
                        speed_bps=speed_bps,
                        eta_seconds=eta,
                        stage="uploading",
                    )
                    _bcast("progress", {
                        "job_id": job_id, "destination_id": destination_id,
                        "stage": "uploading", "title": title,
                        "bytes_total": bytes_total,
                        "bytes_uploaded": bytes_uploaded,
                        "percent": round(pct, 1),
                        "speed_bps": speed_bps,
                        "eta_seconds": eta,
                    })

            # ---- Upload complete ----
            video_id = response.get("id", "")
            video_url = f"https://youtu.be/{video_id}" if video_id else ""

            _upsert_progress(
                job_id, destination_id,
                bytes_uploaded=bytes_total,
                speed_bps=0,
                eta_seconds=0,
                stage="done",
                youtube_video_id=video_id,
            )
            _bcast("progress", {
                "job_id": job_id, "destination_id": destination_id,
                "stage": "done", "title": title,
                "bytes_total": bytes_total, "bytes_uploaded": bytes_total,
                "percent": 100.0, "speed_bps": 0, "eta_seconds": 0,
                "youtube_video_id": video_id, "upload_url": video_url,
            })

            _record_result(
                job_id, destination_id, "youtube", "uploaded",
                upload_url=video_url, error_message="",
                ai_used=ai_used, ai_title=ai_title,
                ai_description=ai_description, ai_tags=ai_tags,
            )
            _delete_progress(job_id, destination_id)

            # Bump the rotating project counter so subsequent uploads
            # round-robin across all configured Google Cloud projects.
            if project_id_used:
                try:
                    _yt_projects.record_upload(project_id_used)
                except Exception as _exc:
                    print(f"[uploader] record_upload failed: {_exc}", flush=True)

            # Best-effort: upload the sibling thumbnail (yt-dlp downloads
            # it next to the .mp4). Failures are logged but never raised —
            # the video upload itself has already succeeded.
            thumb_status = _set_youtube_thumbnail(youtube, video_id, file_path)
            print(f"[uploader] job={job_id} thumbnail: {thumb_status}",
                  flush=True)

            # Auto-clean local files to free disk (controlled by env var).
            cleanup_status = _cleanup_local_files(file_path)
            print(f"[uploader] job={job_id} cleanup: {cleanup_status}", flush=True)

            new_status = _finalize_job_status(job_id)
            _bcast("job_update", {"job_id": job_id, "status": new_status,
                                  "upload_url": video_url})
            _bcast("upload_done", {
                "job_id": job_id, "destination_id": destination_id,
                "platform": "youtube", "status": "uploaded",
                "upload_url": video_url, "title": title,
            })

        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            quota_hit = _is_quota_exceeded_error(e)
            if quota_hit:
                reset_at = _mark_quota_exceeded(destination_id)
                err = f"YouTube quota exceeded; deferred until {reset_at}Z."
                # Also mark the project itself so the rotation skips it.
                if 'project_id_used' in locals() and project_id_used:
                    try:
                        _yt_projects.mark_quota_exceeded(project_id_used)
                    except Exception:
                        pass
            try:
                _upsert_progress(
                    job_id, destination_id,
                    stage="deferred" if quota_hit else "failed",
                    error_message=err,
                )
                _bcast("progress", {
                    "job_id": job_id, "destination_id": destination_id,
                    "stage": "deferred" if quota_hit else "failed", "error": err,
                })
                _record_result(
                    job_id, destination_id, "youtube",
                    "deferred" if quota_hit else "failed",
                    error_message=err,
                    ai_used=ai_used, ai_title=ai_title,
                    ai_description=ai_description, ai_tags=ai_tags,
                )
                _delete_progress(job_id, destination_id)
                new_status = _finalize_job_status(job_id)
                _bcast("job_update", {"job_id": job_id, "status": new_status,
                                      "error": err})
                _bcast("upload_done", {
                    "job_id": job_id, "destination_id": destination_id,
                    "platform": "youtube",
                    "status": "deferred" if quota_hit else "failed",
                    "error": err,
                })
            except Exception:
                pass
