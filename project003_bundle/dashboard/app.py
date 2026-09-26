"""
project003 — Dashboard Flask App
=================================
Single-process Flask service exposing the REST API defined in
`docs/API_CONTRACTS.md` plus HTML pages and an SSE stream.

Per request DB connection (raw sqlite3 via `dashboard.models.get_db()`).
"""
from __future__ import annotations

import http.client
import json
import os
import queue
import re
import socket
import sys
import threading
import time
import csv
import io
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, Response, g, jsonify, redirect, render_template, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from dashboard.models import get_db, init_db  # noqa: E402
except ModuleNotFoundError:
    from models import get_db, init_db  # noqa: E402

try:
    from dashboard import router as routing  # noqa: E402
except ModuleNotFoundError:
    import router as routing  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PORT                = int(os.getenv("PORT", "8080"))
DOCKER_SOCKET       = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
WATCHER_CONTAINER   = os.getenv("WATCHER_CONTAINER",   "project003-watcher")
PROCESSOR_CONTAINER = os.getenv("PROCESSOR_CONTAINER", "project003-processor")
N8N_CONTAINER       = os.getenv("N8N_CONTAINER",       "n8n")
DASHBOARD_CONTAINER = os.getenv("DASHBOARD_CONTAINER", "project003-dashboard")
ALLOWED_CONTAINERS  = {
    "watcher":   WATCHER_CONTAINER,
    "processor": PROCESSOR_CONTAINER,
    "n8n":       N8N_CONTAINER,
    "dashboard": DASHBOARD_CONTAINER,
}

ALLOWED_PLATFORMS = {"youtube", "dailymotion", "facebook", "tiktok"}
ALLOWED_PRIVACY = ("unlisted", "private", "public")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Single source of truth for per-video DOWNLOAD state.
# Returns a dict with keys: key, label, color, bg, terminal, blocks_action.
# Used by the catalog table (checkbox + download cell). Replaces the two
# previously-divergent inline checks that disagreed on what "done" means.
# ---------------------------------------------------------------------------
_DL_STATE_STYLES = {
    "downloaded":  {"label": "✓ downloaded",  "color": "#3fb950", "bg": "#0d2818",  "terminal": True,  "blocks_action": True},
    "downloading": {"label": "⤓ downloading", "color": "#79c0ff", "bg": "#0d2a3a",  "terminal": False, "blocks_action": True},
    "processing":  {"label": "⚙ processing",  "color": "#79c0ff", "bg": "#0d2a3a",  "terminal": False, "blocks_action": True},
    "queued":      {"label": "⏳ queued",      "color": "#d29922", "bg": "#3a2d1d",  "terminal": False, "blocks_action": True},
    "failed":      {"label": "✗ failed",      "color": "#f85149", "bg": "#3a1d1d",  "terminal": True,  "blocks_action": False},
    "unavailable": {"label": "⊘ unavailable", "color": "#8b949e", "bg": "#21262d",  "terminal": True,  "blocks_action": True},
    "ignored":     {"label": "— ignored",     "color": "#6e7681", "bg": "#1c222b",  "terminal": True,  "blocks_action": True},
    "not_started": {"label": "—",             "color": "#8b949e", "bg": "transparent", "terminal": False, "blocks_action": False},
}


def _compute_download_state(row) -> dict:
    """Return the canonical download state for a catalog row.

    Inputs (any subset; missing keys treated as falsy):
      ignored, unavailable_at, is_downloaded, job_status, dlq_status, failed_dlq_id
    Output: {"key": str, "label": str, "color": str, "bg": str,
             "terminal": bool, "blocks_action": bool}

    Priority: ignored > unavailable > job.status (authoritative) >
              is_downloaded flag > dlq.status (transient) > failed marker > none.
    """
    def _get(k):
        try:
            return row[k]
        except (KeyError, IndexError, TypeError):
            return getattr(row, k, None) if not isinstance(row, dict) else None

    if _get("ignored"):
        key = "ignored"
    elif _get("unavailable_at"):
        key = "unavailable"
    else:
        # jobs.status is the authoritative terminal state written by the
        # watcher. download_queue.status is unreliable past 'downloading'
        # because the watcher never advances it (known data quirk).
        js = (_get("job_status") or "").lower()
        if js in ("downloaded", "done", "processed", "processing"):
            key = "downloaded" if js != "processing" else "processing"
        elif js == "downloading":
            key = "downloading"
        elif js == "failed":
            key = "failed"
        elif _get("is_downloaded"):
            key = "downloaded"
        else:
            dlq = (_get("dlq_status") or "").lower()
            if dlq in ("done", "complete"):
                key = "downloaded"
            elif dlq == "downloading":
                key = "downloading"
            elif dlq == "processing":
                key = "processing"
            elif dlq in ("pending", "hydrated"):
                key = "queued"
            elif dlq == "failed" or _get("failed_dlq_id"):
                key = "failed"
            else:
                key = "not_started"
    style = _DL_STATE_STYLES[key]
    return {"key": key, **style}


app.jinja_env.globals["download_state"] = _compute_download_state


@app.before_request
def _open_db():
    g.db = get_db()


@app.teardown_request
def _close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _err(message: str, code: str, status: int = 400):
    return jsonify({"error": message, "code": code}), status


def utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ===========================================================================
# 1.1 Pipelines
# ===========================================================================

PIPELINE_SUMMARY_SQL = """
SELECT
    p.*,
    (SELECT COUNT(*) FROM channels     c WHERE c.pipeline_id = p.id) AS channel_count,
    (SELECT COUNT(*) FROM destinations d WHERE d.pipeline_id = p.id) AS destination_count,
    (SELECT COUNT(*) FROM jobs j
        WHERE j.pipeline_id = p.id
          AND j.status IN ('pending','downloading','downloaded','processing','processed','uploading')
    ) AS jobs_pending,
    (SELECT COUNT(*) FROM jobs j
        WHERE j.pipeline_id = p.id
          AND j.status = 'done'
          AND substr(j.updated_at, 1, 10) = strftime('%Y-%m-%d', 'now')
    ) AS jobs_done_today
FROM pipelines p
"""


@app.get("/api/pipelines")
def api_pipelines_list():
    rows = g.db.execute(PIPELINE_SUMMARY_SQL + " ORDER BY p.id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["active"] = bool(d["active"])
        out.append(d)
    return jsonify(out)


@app.post("/api/pipelines")
def api_pipelines_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return _err("name is required", "MISSING_NAME", 400)
    description = (body.get("description") or "").strip()

    cur = g.db.execute(
        "INSERT INTO pipelines (name, description) VALUES (?, ?)",
        (name, description),
    )
    new_id = cur.lastrowid
    row = g.db.execute("SELECT * FROM pipelines WHERE id = ?", (new_id,)).fetchone()
    d = dict(row)
    d["active"] = bool(d["active"])
    return jsonify(d), 201


@app.get("/api/pipelines/<int:pid>")
def api_pipelines_get(pid: int):
    row = g.db.execute(PIPELINE_SUMMARY_SQL + " WHERE p.id = ?", (pid,)).fetchone()
    if not row:
        return _err("pipeline not found", "NOT_FOUND", 404)
    d = dict(row)
    d["active"] = bool(d["active"])
    return jsonify(d)


@app.put("/api/pipelines/<int:pid>")
def api_pipelines_update(pid: int):
    body = request.get_json(silent=True) or {}
    fields, vals = [], []
    for k in ("name", "description"):
        if k in body:
            fields.append(f"{k} = ?"); vals.append((body[k] or "").strip())
    if "active" in body:
        fields.append("active = ?"); vals.append(1 if body["active"] else 0)
    if "download_profile_id" in body:
        v = body["download_profile_id"]
        # Allow null/empty/0 to clear the FK back to default.
        try:
            v_int = int(v) if v not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            v_int = None
        fields.append("download_profile_id = ?"); vals.append(v_int)
    if fields:
        vals.append(pid)
        cur = g.db.execute(f"UPDATE pipelines SET {', '.join(fields)} WHERE id = ?", tuple(vals))
        if cur.rowcount == 0:
            return _err("pipeline not found", "NOT_FOUND", 404)
    return api_pipelines_get(pid)


@app.delete("/api/pipelines/<int:pid>")
def api_pipelines_delete(pid: int):
    cur = g.db.execute("DELETE FROM pipelines WHERE id = ?", (pid,))
    if cur.rowcount == 0:
        return _err("pipeline not found", "NOT_FOUND", 404)
    return ("", 204)


# ===========================================================================
# 1.2 Channels
# ===========================================================================

CHANNEL_BASE_SQL = """
SELECT
    c.*,
    p.name AS pipeline_name,
    json_array_length(c.backfill_queue) AS backfill_queue_size
FROM channels c
JOIN pipelines p ON p.id = c.pipeline_id
"""


def _serialize_channel(r) -> dict:
    d = dict(r)
    d["active"]            = bool(d.get("active", 0))
    d["backfill_complete"] = bool(d.get("backfill_complete", 0))
    d.pop("backfill_queue", None)
    d.pop("backfill_entry_map", None)
    return d


def _extract_channel_id(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r"/channel/(UC[\w-]{10,})", url)
    if m:
        return m.group(1)
    m = re.search(r"/@([\w.\-]+)", url)
    if m:
        return "@" + m.group(1)
    return None


@app.get("/api/channels")
def api_channels_list():
    pid = request.args.get("pipeline_id", type=int)
    sql, params = CHANNEL_BASE_SQL, ()
    if pid is not None:
        sql += " WHERE c.pipeline_id = ?"; params = (pid,)
    sql += " ORDER BY c.id"
    return jsonify([_serialize_channel(r) for r in g.db.execute(sql, params).fetchall()])


@app.post("/api/channels")
def api_channels_create():
    body = request.get_json(silent=True) or {}
    pid  = body.get("pipeline_id")
    name = (body.get("name") or "").strip()
    url  = (body.get("url") or "").strip()
    mode = (body.get("mode") or "monitor").strip()
    daily_limit = int(body.get("daily_limit") or 10)

    if pid is None or not name or not url:
        return _err("pipeline_id, name, url required", "MISSING_FIELD", 400)
    if mode not in ("backfill", "monitor"):
        return _err("mode must be backfill|monitor", "INVALID_MODE", 400)
    if not (1 <= daily_limit <= 100):
        return _err("daily_limit must be 1..100", "INVALID_DAILY_LIMIT", 400)

    cid = _extract_channel_id(url)
    if not cid:
        return _err("cannot extract channel id from url", "INVALID_URL", 400)
    if not g.db.execute("SELECT 1 FROM pipelines WHERE id = ?", (pid,)).fetchone():
        return _err("pipeline not found", "PIPELINE_NOT_FOUND", 404)
    if g.db.execute("SELECT 1 FROM channels WHERE channel_id = ?", (cid,)).fetchone():
        return _err("channel already exists", "DUPLICATE_CHANNEL", 400)

    cur = g.db.execute(
        """INSERT INTO channels (pipeline_id, name, channel_id, url, mode, daily_limit)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (pid, name, cid, url, mode, daily_limit),
    )
    row = g.db.execute(CHANNEL_BASE_SQL + " WHERE c.id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(_serialize_channel(row)), 201


@app.put("/api/channels/<int:cid>")
def api_channels_update(cid: int):
    body = request.get_json(silent=True) or {}
    fields, vals = [], []
    if "mode" in body:
        if body["mode"] not in ("backfill", "monitor"):
            return _err("mode must be backfill|monitor", "INVALID_MODE", 400)
        fields.append("mode = ?"); vals.append(body["mode"])
    if "daily_limit" in body:
        dl = int(body["daily_limit"])
        if not (1 <= dl <= 100):
            return _err("daily_limit must be 1..100", "INVALID_DAILY_LIMIT", 400)
        fields.append("daily_limit = ?"); vals.append(dl)
    if "active" in body:
        fields.append("active = ?"); vals.append(1 if body["active"] else 0)
    if "name" in body:
        fields.append("name = ?"); vals.append((body["name"] or "").strip())

    if fields:
        vals.append(cid)
        cur = g.db.execute(f"UPDATE channels SET {', '.join(fields)} WHERE id = ?", tuple(vals))
        if cur.rowcount == 0:
            return _err("channel not found", "NOT_FOUND", 404)
    row = g.db.execute(CHANNEL_BASE_SQL + " WHERE c.id = ?", (cid,)).fetchone()
    if not row:
        return _err("channel not found", "NOT_FOUND", 404)
    return jsonify(_serialize_channel(row))


@app.delete("/api/channels/<int:cid>")
def api_channels_delete(cid: int):
    cur = g.db.execute("DELETE FROM channels WHERE id = ?", (cid,))
    if cur.rowcount == 0:
        return _err("channel not found", "NOT_FOUND", 404)
    return ("", 204)


# ===========================================================================
# 1.3 Destinations
# ===========================================================================

# --- n8n workflow name lookup --------------------------------------------
# Scans /app/n8n/*.json once and builds {webhook_path: workflow_name}.
# Cache is invalidated when any workflow file's mtime changes.
_WORKFLOW_DIR = "/app/n8n"
_workflow_cache: dict = {"sig": None, "map": {}}

def _workflow_name_map() -> dict:
    import os, json, glob
    if not os.path.isdir(_WORKFLOW_DIR):
        return {}
    files = sorted(
        f for f in glob.glob(os.path.join(_WORKFLOW_DIR, "*.json"))
        if not os.path.basename(f).endswith((".bak.json", ".old.json", ".disabled.json"))
    )
    sig = tuple((f, os.path.getmtime(f)) for f in files)
    if _workflow_cache["sig"] == sig:
        return _workflow_cache["map"]
    out: dict = {}
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        name = data.get("name") or os.path.basename(f)
        for n in data.get("nodes", []):
            if "webhook" not in (n.get("type") or "").lower():
                continue
            path = (n.get("parameters") or {}).get("path") or ""
            if path and path not in out:
                out[path] = name
    _workflow_cache["sig"] = sig
    _workflow_cache["map"] = out
    return out


def _workflow_name_for_url(url: str) -> str:
    if not url:
        return ""
    # Webhook URL looks like http://n8n:5678/webhook/<path>[/...]
    try:
        from urllib.parse import urlparse
        p = urlparse(url).path or ""
    except Exception:
        p = url
    # Strip the n8n prefix and take the first remaining segment
    for prefix in ("/webhook/", "/webhook-test/"):
        if prefix in p:
            tail = p.split(prefix, 1)[1]
            seg = tail.split("/", 1)[0].split("?", 1)[0]
            return _workflow_name_map().get(seg, "")
    return ""


def _n8n_base_url() -> str:
    """Best-effort guess of the n8n public base URL.

    Strategy:
      1. Env var ``N8N_BASE_URL`` if set (highest priority).
      2. Most-common scheme://host[:port] across existing destinations
         (we just steal whatever the user has been typing).
      3. Fallback to the docker-compose default ``http://n8n:5678``.

    The returned value never has a trailing slash.
    """
    base = (os.getenv("N8N_BASE_URL") or "").strip().rstrip("/")
    if base:
        return base
    try:
        from urllib.parse import urlparse
        from collections import Counter
        rows = g.db.execute(
            "SELECT n8n_webhook_url FROM destinations "
            "WHERE n8n_webhook_url LIKE 'http%'"
        ).fetchall()
        bases: list[str] = []
        for r in rows:
            try:
                u = urlparse(r["n8n_webhook_url"])
                # Only trust URLs that look like real n8n webhooks
                # (the path must contain a /webhook/ or /webhook-test/
                # segment). This filters out junk like youtube.com
                # values from old / mistyped destinations.
                if not (u.scheme and u.netloc):
                    continue
                p = u.path or ""
                if "/webhook/" not in p and "/webhook-test/" not in p:
                    continue
                bases.append(f"{u.scheme}://{u.netloc}")
            except Exception:
                continue
        if bases:
            return Counter(bases).most_common(1)[0][0]
    except Exception:                                                # noqa: BLE001
        pass
    return "http://n8n:5678"


def _list_n8n_workflows() -> list[dict]:
    """Return ``[{name, path, suggested_url, platform_hint}]`` for every
    webhook node we can find in the workflow JSON files. Pure read of the
    cached scan from ``_workflow_name_map()`` — no network call.
    """
    base = _n8n_base_url()
    out: list[dict] = []
    seen_paths: set[str] = set()
    # _workflow_name_map() returns {path: workflow_name}; we need to know
    # the original file too (for de-dup + ordering), but for the dropdown
    # path+name is enough. Re-walk the cache content.
    for path, name in sorted(_workflow_name_map().items(),
                              key=lambda kv: (kv[1] or "").lower()):
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        nm = (name or "").lower()
        hint = ""
        if "youtube" in nm or "yt" in nm.split("-"):
            hint = "youtube"
        elif "tiktok" in nm or "tt" in nm.split("-"):
            hint = "tiktok"
        elif "facebook" in nm or "fb" in nm.split("-"):
            hint = "facebook"
        elif "dailymotion" in nm or "dm" in nm.split("-"):
            hint = "dailymotion"
        out.append({
            "name": name,
            "path": path,
            "suggested_url": f"{base}/webhook/{path}",
            "platform_hint": hint,
        })
    return out


@app.get("/api/n8n/workflows")
def api_n8n_workflows():
    """JSON list of available n8n workflows + suggested webhook URLs.

    Read-only, cached by mtime via :func:`_workflow_name_map`. Used by
    the Pipelines destination form to offer a dropdown alongside the
    manual URL field.
    """
    return jsonify(_list_n8n_workflows())


def _serialize_destination(r) -> dict:
    d = dict(r)
    d["enabled"] = bool(d.get("enabled", 0))
    # PR7: cast bool-ish columns so Jinja {% if %} reads them correctly.
    for col in ("default_comments_enabled", "default_made_for_kids",
                "default_embeddable", "default_notify_subscribers"):
        if col in d:
            d[col] = bool(d[col])
    d["workflow_name"] = _workflow_name_for_url(d.get("n8n_webhook_url") or "")
    return d


@app.get("/api/destinations")
def api_destinations_list():
    pid = request.args.get("pipeline_id", type=int)
    if pid is None:
        return _err("pipeline_id required", "MISSING_PIPELINE_ID", 400)
    rows = g.db.execute(
        "SELECT * FROM destinations WHERE pipeline_id = ? ORDER BY id", (pid,)
    ).fetchall()
    return jsonify([_serialize_destination(r) for r in rows])


@app.post("/api/destinations")
def api_destinations_create():
    body = request.get_json(silent=True) or {}
    pid       = body.get("pipeline_id")
    platform  = (body.get("platform") or "").strip()
    label     = (body.get("label") or "").strip()
    webhook   = (body.get("n8n_webhook_url") or "").strip()
    privacy   = (body.get("default_privacy") or "unlisted").strip().lower()

    if pid is None or not platform or not webhook:
        return _err("pipeline_id, platform, n8n_webhook_url required", "MISSING_FIELD", 400)
    if platform not in ALLOWED_PLATFORMS:
        return _err(f"platform must be one of {sorted(ALLOWED_PLATFORMS)}",
                    "INVALID_PLATFORM", 400)
    if not webhook.startswith(("http://", "https://")):
        return _err("n8n_webhook_url must be http(s)", "INVALID_WEBHOOK_URL", 400)
    if privacy not in ("unlisted", "private", "public"):
        return _err("default_privacy must be unlisted|private|public", "INVALID_PRIVACY", 400)
    if not g.db.execute("SELECT 1 FROM pipelines WHERE id = ?", (pid,)).fetchone():
        return _err("pipeline not found", "PIPELINE_NOT_FOUND", 404)

    cur = g.db.execute(
        """INSERT INTO destinations (pipeline_id, platform, label, n8n_webhook_url, default_privacy)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, platform, label, webhook, privacy),
    )
    row = g.db.execute("SELECT * FROM destinations WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(_serialize_destination(row)), 201


@app.put("/api/destinations/<int:did>")
def api_destinations_update(did: int):
    body = request.get_json(silent=True) or {}
    fields, vals = [], []
    if "label" in body:
        fields.append("label = ?"); vals.append((body["label"] or "").strip())
    if "n8n_webhook_url" in body:
        url = (body["n8n_webhook_url"] or "").strip()
        if not url.startswith(("http://", "https://")):
            return _err("n8n_webhook_url must be http(s)", "INVALID_WEBHOOK_URL", 400)
        fields.append("n8n_webhook_url = ?"); vals.append(url)
    if "enabled" in body:
        fields.append("enabled = ?"); vals.append(1 if body["enabled"] else 0)
    if "default_privacy" in body:
        priv = (body["default_privacy"] or "").strip().lower()
        if priv not in ("unlisted", "private", "public"):
            return _err("default_privacy must be unlisted|private|public", "INVALID_PRIVACY", 400)
        fields.append("default_privacy = ?"); vals.append(priv)
    if "youtube_channel_id" in body:
        v = body["youtube_channel_id"]
        if v in (None, "", 0, "0"):
            fields.append("youtube_channel_id = ?"); vals.append(None)
        else:
            try:
                fields.append("youtube_channel_id = ?"); vals.append(int(v))
            except (TypeError, ValueError):
                return _err("youtube_channel_id must be an integer",
                            "INVALID_CHANNEL_ID", 400)

    if fields:
        vals.append(did)
        cur = g.db.execute(f"UPDATE destinations SET {', '.join(fields)} WHERE id = ?",
                           tuple(vals))
        if cur.rowcount == 0:
            return _err("destination not found", "NOT_FOUND", 404)

    row = g.db.execute("SELECT * FROM destinations WHERE id = ?", (did,)).fetchone()
    if not row:
        return _err("destination not found", "NOT_FOUND", 404)
    return jsonify(_serialize_destination(row))


@app.delete("/api/destinations/<int:did>")
def api_destinations_delete(did: int):
    cur = g.db.execute("DELETE FROM destinations WHERE id = ?", (did,))
    if cur.rowcount == 0:
        return _err("destination not found", "NOT_FOUND", 404)
    return ("", 204)


@app.post("/api/destinations/<int:did>/test")
def api_destinations_test(did: int):
    """Per-destination health probe. Returns a 4-light strip:

      * webhook   - HEAD/GET the webhook URL, expect 2xx/404/405
      * workflow  - matching workflow JSON file exists in the n8n scan
      * channel   - platform=youtube + bound channel has a healthy
                    OAuth project (active, not needs_reauth)
      * scheduler - the picker would actually pick a project for it
                    (n/a when not youtube)

    EXPLICIT user-click only - never auto-polled. No state writes.
    """
    row = g.db.execute(
        "SELECT id, pipeline_id, platform, label, n8n_webhook_url, "
        "       youtube_channel_id, default_privacy "
        "FROM destinations WHERE id = ?",
        (did,),
    ).fetchone()
    if not row:
        return _err("destination not found", "NOT_FOUND", 404)
    d = dict(row)

    result = {
        "webhook":   {"ok": False, "detail": "", "applicable": True},
        "workflow":  {"ok": False, "detail": "", "applicable": True},
        "channel":   {"ok": False, "detail": "", "applicable": True},
        "scheduler": {"ok": False, "detail": "", "applicable": True},
    }

    # ---- 1. Webhook reachability ----
    url = d["n8n_webhook_url"] or ""
    if not url:
        result["webhook"]["detail"] = "no URL configured"
    else:
        try:
            import requests as _rq
            code = None
            try:
                r = _rq.head(url, timeout=4, allow_redirects=True)
                code = r.status_code
                if code in (405, 501):
                    r = _rq.get(url, timeout=4, allow_redirects=True)
                    code = r.status_code
            except _rq.RequestException as e:
                result["webhook"]["detail"] = (
                    f"unreachable: {type(e).__name__}"
                )
            if code is not None:
                if 200 <= code < 300 or code == 404:
                    result["webhook"]["ok"] = True
                    result["webhook"]["detail"] = f"HTTP {code}"
                elif code == 405:
                    result["webhook"]["ok"] = True
                    result["webhook"]["detail"] = (
                        "HTTP 405 (POST-only webhook - normal)"
                    )
                else:
                    result["webhook"]["detail"] = f"HTTP {code}"
        except Exception as e:                                # noqa: BLE001
            result["webhook"]["detail"] = (
                f"error: {type(e).__name__}: {e}"
            )

    # ---- 2. Workflow file present ----
    wf_name = _workflow_name_for_url(url)
    if wf_name:
        result["workflow"]["ok"] = True
        result["workflow"]["detail"] = wf_name
    else:
        result["workflow"]["detail"] = (
            "no matching workflow JSON in scan" if url else "no URL"
        )

    # ---- 3 + 4. Channel + scheduler (youtube only) ----
    if d["platform"] != "youtube":
        result["channel"]["applicable"]   = False
        result["scheduler"]["applicable"] = False
        result["channel"]["detail"]   = "not youtube"
        result["scheduler"]["detail"] = "not youtube"
    else:
        ch_id = d["youtube_channel_id"]
        if ch_id:
            ch = g.db.execute(
                "SELECT id, title, channel_id FROM youtube_channels "
                "WHERE id = ?",
                (int(ch_id),),
            ).fetchone()
            if not ch:
                result["channel"]["detail"] = (
                    f"bound channel id={ch_id} no longer exists"
                )
            else:
                healthy = g.db.execute(
                    "SELECT COUNT(DISTINCT p.id) AS n "
                    "FROM youtube_projects p "
                    "JOIN oauth_tokens t ON t.project_id = p.id "
                    "WHERE t.platform = 'youtube' "
                    "  AND t.youtube_channel_id = ? "
                    "  AND COALESCE(t.needs_reauth, 0) = 0 "
                    "  AND p.active = 1",
                    (int(ch_id),),
                ).fetchone()["n"]
                if healthy > 0:
                    result["channel"]["ok"] = True
                    result["channel"]["detail"] = (
                        f"{healthy} healthy project(s) on "
                        f"'{ch['title']}'"
                    )
                else:
                    result["channel"]["detail"] = (
                        f"channel '{ch['title']}' has no healthy "
                        "projects"
                    )
        else:
            result["channel"]["applicable"] = False
            result["channel"]["detail"] = "any channel (global rotation)"

        # Scheduler eligibility - call the picker if it exists.
        try:
            _picker = None
            try:
                from dashboard import projects as _yt_projects  # type: ignore
                _picker = _yt_projects
            except ModuleNotFoundError:
                try:
                    import projects as _yt_projects  # type: ignore
                    _picker = _yt_projects
                except ModuleNotFoundError:
                    _picker = None
            if _picker is None:
                result["scheduler"]["applicable"] = False
                result["scheduler"]["detail"] = "picker module not found"
            else:
                pick = None
                if ch_id and hasattr(_picker, "pick_active_project_for_channel"):
                    pick = _picker.pick_active_project_for_channel(int(ch_id))
                elif hasattr(_picker, "pick_active_project"):
                    pick = _picker.pick_active_project()
                else:
                    result["scheduler"]["applicable"] = False
                    result["scheduler"]["detail"] = (
                        "no picker function exposed"
                    )
                    pick = "_skip"
                if pick is None:
                    result["scheduler"]["detail"] = (
                        "no eligible project (capped, paused, or quota "
                        "cooldown)"
                    )
                elif pick != "_skip":
                    result["scheduler"]["ok"] = True
                    label = pick.get("label") or pick.get("id") \
                        if isinstance(pick, dict) else str(pick)
                    result["scheduler"]["detail"] = f"next pick: {label}"
        except Exception as e:                                # noqa: BLE001
            result["scheduler"]["detail"] = f"picker error: {e}"

    applicable_results = [v for v in result.values()
                          if v.get("applicable", True)]
    all_ok = bool(applicable_results) and all(
        v["ok"] for v in applicable_results
    )
    if request.headers.get("HX-Request") == "true":
        return render_template(
            "partials/destination_test_result.html",
            did=did, result=result, all_ok=all_ok,
        )
    return jsonify({"ok": all_ok, "checks": result})


# ===========================================================================
# 1.4 Processing steps
# ===========================================================================

def _serialize_step(r) -> dict:
    d = dict(r)
    d["enabled"] = bool(d.get("enabled", 0))
    try:
        d["params"] = json.loads(d.get("params") or "{}")
    except json.JSONDecodeError:
        d["params"] = {}
    return d


@app.get("/api/steps")
def api_steps_list():
    pid = request.args.get("pipeline_id", type=int)
    if pid is None:
        return _err("pipeline_id required", "MISSING_PIPELINE_ID", 400)
    rows = g.db.execute(
        """SELECT s.*, d.label AS destination_label
           FROM processing_steps s
           LEFT JOIN destinations d ON d.id = s.destination_id
           WHERE s.pipeline_id = ?
           ORDER BY s.step_order, s.id""",
        (pid,),
    ).fetchall()
    return jsonify([_serialize_step(r) for r in rows])


@app.post("/api/steps")
def api_steps_create():
    body = request.get_json(silent=True) or {}
    pid       = body.get("pipeline_id")
    step_type = (body.get("step_type") or "").strip()
    if pid is None or not step_type:
        return _err("pipeline_id, step_type required", "MISSING_FIELD", 400)

    dest_id    = body.get("destination_id")
    step_order = int(body.get("step_order", 0))
    params     = body.get("params") or {}
    if not isinstance(params, dict):
        return _err("params must be an object", "INVALID_PARAMS", 400)

    cur = g.db.execute(
        """INSERT INTO processing_steps
                (pipeline_id, destination_id, step_order, step_type, params)
           VALUES (?, ?, ?, ?, ?)""",
        (pid, dest_id, step_order, step_type, json.dumps(params)),
    )
    row = g.db.execute(
        """SELECT s.*, d.label AS destination_label
           FROM processing_steps s
           LEFT JOIN destinations d ON d.id = s.destination_id
           WHERE s.id = ?""",
        (cur.lastrowid,),
    ).fetchone()
    return jsonify(_serialize_step(row)), 201


@app.put("/api/steps/<int:sid>")
def api_steps_update(sid: int):
    body = request.get_json(silent=True) or {}
    fields, vals = [], []
    if "step_order" in body:
        fields.append("step_order = ?"); vals.append(int(body["step_order"]))
    if "params" in body:
        if not isinstance(body["params"], dict):
            return _err("params must be an object", "INVALID_PARAMS", 400)
        fields.append("params = ?"); vals.append(json.dumps(body["params"]))
    if "enabled" in body:
        fields.append("enabled = ?"); vals.append(1 if body["enabled"] else 0)
    if "step_type" in body:
        fields.append("step_type = ?"); vals.append((body["step_type"] or "").strip())

    if fields:
        vals.append(sid)
        cur = g.db.execute(f"UPDATE processing_steps SET {', '.join(fields)} WHERE id = ?",
                           tuple(vals))
        if cur.rowcount == 0:
            return _err("step not found", "NOT_FOUND", 404)

    row = g.db.execute(
        """SELECT s.*, d.label AS destination_label
           FROM processing_steps s
           LEFT JOIN destinations d ON d.id = s.destination_id
           WHERE s.id = ?""",
        (sid,),
    ).fetchone()
    if not row:
        return _err("step not found", "NOT_FOUND", 404)
    return jsonify(_serialize_step(row))


@app.delete("/api/steps/<int:sid>")
def api_steps_delete(sid: int):
    cur = g.db.execute("DELETE FROM processing_steps WHERE id = ?", (sid,))
    if cur.rowcount == 0:
        return _err("step not found", "NOT_FOUND", 404)
    return ("", 204)


# ===========================================================================
# 1.5 Jobs
# ===========================================================================

JOB_LIST_SQL = """
SELECT
    j.*,
    v.youtube_video_id,
    v.original_title,
    p.name AS pipeline_name
FROM jobs j
JOIN videos v    ON v.id = j.video_id
JOIN pipelines p ON p.id = j.pipeline_id
"""


def _serialize_job(r) -> dict:
    d = dict(r)
    outs = g.db.execute(
        """SELECT o.destination_id, d.platform, o.file_path
           FROM job_outputs o
           JOIN destinations d ON d.id = o.destination_id
           WHERE o.job_id = ?""", (d["id"],)).fetchall()
    d["outputs"] = [dict(o) for o in outs]
    ups = g.db.execute(
        "SELECT * FROM upload_results WHERE job_id = ? ORDER BY id", (d["id"],)
    ).fetchall()
    d["upload_results"] = []
    for u in ups:
        ud = dict(u)
        ud["ai_used"] = bool(ud.get("ai_used", 0))
        try:
            ud["ai_tags"] = json.loads(ud.get("ai_tags") or "[]")
        except json.JSONDecodeError:
            ud["ai_tags"] = []
        d["upload_results"].append(ud)
    return d


@app.get("/api/jobs")
@app.get("/api/queue")
def api_jobs_list():
    status = request.args.get("status")
    pid    = request.args.get("pipeline_id", type=int)
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    sql, params = JOB_LIST_SQL, []
    where = []
    if status:
        where.append("j.status = ?"); params.append(status)
    if pid is not None:
        where.append("j.pipeline_id = ?"); params.append(pid)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY j.updated_at DESC, j.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = g.db.execute(sql, tuple(params)).fetchall()
    return jsonify([_serialize_job(r) for r in rows])


@app.get("/api/jobs/<int:jid>")
def api_jobs_get(jid: int):
    row = g.db.execute(JOB_LIST_SQL + " WHERE j.id = ?", (jid,)).fetchone()
    if not row:
        return _err("job not found", "NOT_FOUND", 404)
    return jsonify(_serialize_job(row))


@app.post("/api/jobs")
def api_jobs_create():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    pid = body.get("pipeline_id")
    if not url:
        return _err("url required", "INVALID_URL", 400)
    if pid is None:
        return _err("pipeline_id required", "MISSING_FIELD", 400)
    if not g.db.execute("SELECT 1 FROM pipelines WHERE id = ?", (pid,)).fetchone():
        return _err("pipeline not found", "PIPELINE_NOT_FOUND", 404)

    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url)
    yt_id = m.group(1) if m else url[-11:]

    vrow = g.db.execute(
        "SELECT id FROM videos WHERE youtube_video_id = ?", (yt_id,)
    ).fetchone()
    if vrow:
        video_pk = vrow["id"]
    else:
        chan = g.db.execute(
            "SELECT id FROM channels WHERE pipeline_id = ? LIMIT 1", (pid,)
        ).fetchone()
        if not chan:
            return _err("pipeline has no channels — manual job needs a channel context",
                        "NO_CHANNEL", 400)
        cur = g.db.execute(
            """INSERT INTO videos (channel_id, youtube_video_id, source_url)
               VALUES (?, ?, ?)""",
            (chan["id"], yt_id, url),
        )
        video_pk = cur.lastrowid

    cur = g.db.execute(
        "INSERT INTO jobs (video_id, pipeline_id, status) VALUES (?, ?, 'pending')",
        (video_pk, pid),
    )
    return jsonify({
        "job_id": cur.lastrowid,
        "status": "pending",
        "message": "Job created. Watcher will process it shortly.",
    }), 202


# ===========================================================================
# 1.5a Processor event — called by processor.py to push status updates
# ===========================================================================

@app.post("/api/processor/event")
def api_processor_event():
    """Receive a status notification from the processor container.

    Expected payload::

        {"job_id": 42, "status": "processing"|"processed"|"failed",
         "output_path": "/downloads/foo.mp4"}   # output_path optional

    The endpoint updates the job row and broadcasts an SSE event so the
    dashboard live-updates without polling.
    """
    body = request.get_json(silent=True) or {}
    job_id = body.get("job_id")
    status = (body.get("status") or "").strip()

    if not job_id:
        return _err("job_id required", "MISSING_FIELD", 400)

    allowed = {"processing", "processed", "failed"}
    if status not in allowed:
        return _err(f"status must be one of {sorted(allowed)}", "INVALID_STATUS", 400)

    job = g.db.execute("SELECT id, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        return _err("job not found", "JOB_NOT_FOUND", 404)

    updates: list[str] = ["status = ?"]
    params: list = [status]

    output_path = (body.get("output_path") or "").strip()
    if output_path and status == "processed":
        updates.append("source_file_path = ?")
        params.append(output_path)

    params.append(job_id)
    g.db.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", params)

    # Broadcast live progress via SSE so the dashboard reacts immediately
    _sse_broadcast("job_update", {
        "job_id": job_id,
        "status": status,
        "output_path": output_path or None,
    })

    return jsonify({"ok": True, "job_id": job_id, "status": status})


# ===========================================================================
# 1.5b Test Connection (re-fire webhook for an existing job to validate n8n + YouTube)
# ===========================================================================

@app.post("/api/test/youtube")
def api_test_youtube():
    """Re-fire the n8n webhook for the most recent processed job whose source
    file still exists. Returns the raw n8n response so the user can confirm
    the YouTube credential / workflow are live.
    """
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    body = request.get_json(silent=True) or {}
    job_id = body.get("job_id")

    if job_id:
        row = g.db.execute(
            JOB_LIST_SQL.replace("JOIN videos v", "JOIN videos v")
            .rstrip() + " JOIN channels c ON c.id = v.channel_id WHERE j.id = ?",
            (job_id,),
        ).fetchone()
    else:
        row = g.db.execute(
            JOB_LIST_SQL.rstrip()
            + " JOIN channels c ON c.id = v.channel_id"
            " WHERE j.status IN ('processed','done')"
            "   AND j.source_file_path IS NOT NULL"
            "   AND j.source_file_path <> ''"
            " ORDER BY j.id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return _err("no processed job available to test", "NO_JOB", 404)

    # extract via dict access (sqlite3.Row supports it)
    rd = dict(row)
    src_url = ""
    chan_name = ""
    try:
        src_url = rd.get("source_url") or ""
    except Exception:
        pass
    try:
        chan_name = rd.get("channel_name") or ""
    except Exception:
        pass
    if not src_url or not chan_name:
        v = g.db.execute(
            "SELECT v.source_url, c.name AS channel_name, c.channel_id, c.url AS channel_url"
            "  FROM videos v JOIN channels c ON c.id = v.channel_id"
            " WHERE v.id = ?", (rd["video_id"],),
        ).fetchone()
        if v:
            src_url = src_url or (v["source_url"] or "")
            chan_name = chan_name or (v["channel_name"] or "")
            chan_id_str = v["channel_id"] or ""
            chan_url = v["channel_url"] or ""
        else:
            chan_id_str, chan_url = "", ""
    else:
        chan_id_str, chan_url = "", ""

    dest = g.db.execute(
        "SELECT * FROM destinations WHERE pipeline_id = ? AND enabled = 1 ORDER BY id LIMIT 1",
        (row["pipeline_id"],),
    ).fetchone()
    if not dest:
        return _err("no enabled destination for pipeline", "NO_DEST", 400)

    payload = {
        "event":          "test_connection",
        "mode":           "test",
        "job_id":         row["id"],
        "pipeline_id":    row["pipeline_id"],
        "destination_id": dest["id"],
        "video_id":       row["youtube_video_id"],
        "title":          row["original_title"] or "Connection Test",
        "file_path":      row["source_file_path"],
        "source_url":     src_url,
        "channel_name":   chan_name,
        "channel_id":     chan_id_str,
        "channel_url":    chan_url,
        "timestamp":      utcnow_iso(),
        "duration":       0,
    }
    data = json.dumps(payload).encode("utf-8")
    req = _urlreq.Request(
        dest["n8n_webhook_url"], data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with _urlreq.urlopen(req, timeout=10) as resp:
            return jsonify({
                "ok": True,
                "n8n_status": resp.status,
                "n8n_response": resp.read().decode("utf-8", errors="replace")[:500],
                "job_id": row["id"],
                "destination_id": dest["id"],
                "webhook_url": dest["n8n_webhook_url"],
                "title": payload["title"],
                "hint": "Open n8n Executions tab to watch the workflow run end-to-end.",
            })
    except _urlerr.HTTPError as e:
        return jsonify({
            "ok": False,
            "error": f"n8n returned HTTP {e.code}",
            "detail": e.read().decode("utf-8", errors="replace")[:500],
            "webhook_url": dest["n8n_webhook_url"],
        }), 502
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": type(e).__name__,
            "detail": str(e)[:500],
            "webhook_url": dest["n8n_webhook_url"],
        }), 502


@app.post("/partials/test/youtube")
def partial_test_youtube():
    """HTMX-friendly version: returns rendered HTML status."""
    with app.test_request_context("/api/test/youtube", method="POST", json={}):
        resp = api_test_youtube()
    if isinstance(resp, tuple):
        body_obj, status = resp[0].get_json(), resp[1]
    else:
        body_obj, status = resp.get_json(), 200
    if body_obj.get("ok"):
        return (
            f"<div class='p-3 rounded text-sm' style='background:#0d4429;color:#3fb950'>"
            f"<b>Webhook fired</b> — n8n returned HTTP {body_obj['n8n_status']} for job "
            f"#{body_obj['job_id']} → destination #{body_obj['destination_id']}.<br>"
            f"<span style='opacity:.8'>{body_obj['hint']}</span></div>",
            200,
        )
    # Render the error inline. Always return 200 so HTMX swaps the message
    # into #test-result instead of triggering the global error toast (the
    # rendered HTML already communicates the failure clearly).
    return (
        f"<div class='p-3 rounded text-sm' style='background:#3d1414;color:#f85149'>"
        f"<b>Test failed:</b> {body_obj.get('error','?')}<br>"
        f"<code style='font-size:11px'>{body_obj.get('detail','')}</code></div>",
        200,
    )


# ===========================================================================
# 1.6 History
# ===========================================================================

@app.get("/api/history")
def api_history_list():
    platform = request.args.get("platform")
    status   = request.args.get("status")
    limit    = min(int(request.args.get("limit", 50)), 500)
    offset   = int(request.args.get("offset", 0))

    sql = """
    SELECT
        u.*,
        v.original_title,
        c.name AS channel_name
    FROM upload_results u
    JOIN jobs j     ON j.id = u.job_id
    JOIN videos v   ON v.id = j.video_id
    JOIN channels c ON c.id = v.channel_id
    """
    where, params = [], []
    if platform:
        where.append("u.platform = ?"); params.append(platform)
    if status:
        where.append("u.status = ?"); params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY u.created_at DESC, u.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    out = []
    for r in g.db.execute(sql, tuple(params)).fetchall():
        d = dict(r)
        d["ai_used"] = bool(d.get("ai_used", 0))
        try:
            d["ai_tags"] = json.loads(d.get("ai_tags") or "[]")
        except json.JSONDecodeError:
            d["ai_tags"] = []
        out.append(d)
    return jsonify(out)


# ===========================================================================
# 1.6b Activity (live status of pipeline)
# ===========================================================================

ACTIVITY_SQL = """
SELECT
    j.id           AS job_id,
    j.status       AS job_status,
    j.created_at   AS job_created_at,
    j.updated_at   AS job_updated_at,
    j.error_message,
    v.original_title,
    v.youtube_video_id,
    v.thumbnail_url,
    c.name         AS channel_name,
    p.name         AS pipeline_name
FROM jobs j
JOIN videos v    ON v.id = j.video_id
JOIN channels c  ON c.id = v.channel_id
JOIN pipelines p ON p.id = j.pipeline_id
ORDER BY j.id DESC
LIMIT 25
"""


def _derive_stage(job: dict, ups: list[dict], dest_count: int) -> dict:
    """Map (job.status + upload_results count) to a human stage."""
    st = job["job_status"]
    n_done = len(ups)
    n_ok   = sum(1 for u in ups if u["status"] == "uploaded")
    n_fail = sum(1 for u in ups if u["status"] == "failed")

    if st == "pending":
        return {"stage": "queued", "label": "Queued", "color": "gray"}
    if st == "downloading":
        return {"stage": "downloading", "label": "Downloading from YouTube", "color": "blue"}
    if st == "processing":
        return {"stage": "processing", "label": "Processing video", "color": "blue"}
    if st in ("downloaded", "processed"):
        if dest_count == 0:
            return {"stage": "no_destination", "label": "No destination configured", "color": "yellow"}
        in_flight = bool(job.get("_in_flight_uploads", 0))
        if n_done == 0:
            if in_flight:
                return {"stage": "uploading", "label": "Uploading via n8n…", "color": "amber"}
            return {"stage": "ready", "label": "Ready to upload", "color": "gray"}
        if n_done < dest_count:
            if in_flight:
                return {"stage": "uploading", "label": f"Uploading ({n_done}/{dest_count} done)", "color": "amber"}
            return {"stage": "ready", "label": f"{n_done}/{dest_count} done · awaiting next upload", "color": "gray"}
        if n_fail and not n_ok:
            return {"stage": "failed", "label": "All uploads failed", "color": "red"}
        if n_fail:
            return {"stage": "partial", "label": f"{n_ok} ok, {n_fail} failed", "color": "yellow"}
        return {"stage": "done", "label": "Uploaded", "color": "green"}
    if st == "failed":
        return {"stage": "failed", "label": "Job failed", "color": "red"}
    return {"stage": st, "label": st.title(), "color": "gray"}


def _seconds_since(ts: str) -> int:
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", ""))
        # treat stored ts as UTC (matches strftime('%Y-%m-%dT%H:%M:%S','now'))
        return max(0, int((datetime.utcnow() - dt).total_seconds()))
    except Exception:
        return -1


@app.get("/api/activity")
def api_activity():
    rows = g.db.execute(ACTIVITY_SQL).fetchall()
    # destination count per pipeline (enabled only)
    dest_counts = {
        r["pipeline_id"]: r["n"]
        for r in g.db.execute(
            "SELECT pipeline_id, COUNT(*) AS n FROM destinations WHERE enabled=1 GROUP BY pipeline_id"
        ).fetchall()
    }
    # need pipeline_id per job → fetch separately to keep ACTIVITY_SQL small
    pid_by_job = {
        r["id"]: r["pipeline_id"]
        for r in g.db.execute("SELECT id, pipeline_id FROM jobs ORDER BY id DESC LIMIT 25").fetchall()
    }

    # Detect actually-in-flight uploads so we don't fake-label idle
    # `processed` jobs as "uploading". A job is in flight if EITHER:
    #   * upload_progress has a row in a live stage (n8n writes these), OR
    #   * upload_ledger has a recently-touched row in `uploading` status
    #     (covers the gap when n8n doesn't post progress).
    in_flight_jobs = {
        r["job_id"]
        for r in g.db.execute(
            "SELECT DISTINCT job_id FROM upload_progress "
            "WHERE stage IN ('starting','uploading','processing')"
        ).fetchall()
    }
    in_flight_jobs |= {
        r["job_id"]
        for r in g.db.execute(
            "SELECT DISTINCT job_id FROM upload_ledger "
            "WHERE status = 'uploading' "
            "  AND job_id IS NOT NULL "
            "  AND updated_at >= strftime('%Y-%m-%dT%H:%M:%S','now','-10 minutes')"
        ).fetchall()
    }

    # Batch-fetch all upload_results for the visible jobs in ONE query
    # (was N+1 — one query per active row, up to 25 round-trips).
    job_ids = [r["job_id"] for r in rows]
    ups_by_job: dict[int, list[dict]] = {jid: [] for jid in job_ids}
    if job_ids:
        placeholders = ",".join(["?"] * len(job_ids))
        for u in g.db.execute(
            f"SELECT job_id, destination_id, platform, status, upload_url, "
            f"       ai_title, error_message, created_at "
            f"  FROM upload_results "
            f" WHERE job_id IN ({placeholders}) "
            f" ORDER BY id",
            job_ids,
        ).fetchall():
            ups_by_job.setdefault(u["job_id"], []).append(dict(u))

    active, recent = [], []
    for r in rows:
        d = dict(r)
        ups = ups_by_job.get(d["job_id"], [])
        dc = dest_counts.get(pid_by_job.get(d["job_id"], -1), 0)
        d["_in_flight_uploads"] = 1 if d["job_id"] in in_flight_jobs else 0
        info = _derive_stage(d, ups, dc)
        d.update(info)
        d["uploads"] = ups
        d["seconds_in_state"] = _seconds_since(d["job_updated_at"])
        d["destination_count"] = dc
        if info["stage"] in ("queued", "downloading", "processing", "uploading"):
            active.append(d)
        else:
            recent.append(d)

    # last successful upload
    last_ok = g.db.execute(
        "SELECT u.*, v.original_title, c.name AS channel_name "
        "FROM upload_results u "
        "JOIN jobs j ON j.id=u.job_id "
        "JOIN videos v ON v.id=j.video_id "
        "JOIN channels c ON c.id=v.channel_id "
        "WHERE u.status='uploaded' ORDER BY u.id DESC LIMIT 1"
    ).fetchone()

    return jsonify({
        "active": active,
        "recent": recent[:10],
        "last_uploaded": dict(last_ok) if last_ok else None,
        "summary": {
            "active_count": len(active),
            "uploading_count": sum(1 for a in active if a["stage"] == "uploading"),
            "stuck_count": sum(1 for a in active if a["stage"] == "uploading" and a["seconds_in_state"] > 300),
        },
    })


@app.get("/partials/activity")
def partial_activity():
    """HTMX partial — auto-refreshing live activity panel."""
    data = api_activity().get_json()
    return render_template("partials/activity.html", **data)


# ===========================================================================
# 1.7 Logs (Docker socket)
# ===========================================================================

class _UnixHTTPConn(http.client.HTTPConnection):
    def __init__(self, sock_path: str):
        super().__init__("localhost")
        self._sock_path = sock_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._sock_path)


def _read_container_logs(container: str, tail: int) -> list[str]:
    try:
        conn = _UnixHTTPConn(DOCKER_SOCKET)
        conn.request(
            "GET",
            f"/containers/{container}/logs?stdout=1&stderr=1&tail={tail}&timestamps=0",
            headers={"Host": "localhost"},
        )
        raw = conn.getresponse().read()
        conn.close()
        lines, i = [], 0
        while i + 8 <= len(raw):
            size = int.from_bytes(raw[i + 4:i + 8], "big")
            chunk = raw[i + 8:i + 8 + size].decode("utf-8", errors="replace").rstrip("\n")
            if chunk:
                lines.append(chunk)
            i += 8 + size
        return lines
    except Exception as exc:
        return [f"[dashboard] Could not read {container} logs: {exc}"]


@app.get("/api/logs")
def api_logs():
    target = (request.args.get("container") or "all").lower()
    tail   = min(int(request.args.get("tail", 120)), 500)
    download = request.args.get("download") in ("1", "true", "yes")

    if target == "all":
        targets = list(ALLOWED_CONTAINERS.items())
    elif target in ALLOWED_CONTAINERS:
        targets = [(target, ALLOWED_CONTAINERS[target])]
    else:
        return _err("container must be " + "|".join(list(ALLOWED_CONTAINERS) + ["all"]),
                    "INVALID_CONTAINER", 400)

    out = []
    for name, container in targets:
        for line in _read_container_logs(container, tail):
            out.append({"container": name, "text": line})

    if download:
        body = "\n".join(f"[{x['container']}] {x['text']}" for x in out) + "\n"
        fname = f"{target}-logs.txt"
        return Response(
            body, mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    return jsonify({"lines": out})


@app.get("/partials/logs")
def partial_logs():
    target = (request.args.get("container") or "watcher").lower()
    tail   = min(int(request.args.get("tail", 200)), 500)
    if target not in ALLOWED_CONTAINERS:
        return f"<div style='color:#f85149'>Unknown container: {target}</div>", 400
    lines = _read_container_logs(ALLOWED_CONTAINERS[target], tail)
    return render_template("partials/log_lines.html", lines=lines, container=target)


# ===========================================================================
# 1.8 SSE: live queue stream
# ===========================================================================

_SSE_SUBSCRIBERS: list[queue.Queue] = []


def _sse_broadcast(event: str, data: dict) -> None:
    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    for q in list(_SSE_SUBSCRIBERS):
        try:
            q.put_nowait(msg)
        except Exception:
            pass


@app.get("/api/queue/stream")
def api_queue_stream():
    q: queue.Queue = queue.Queue(maxsize=100)
    _SSE_SUBSCRIBERS.append(q)

    def _gen():
        try:
            yield "event: heartbeat\ndata: {}\n\n"
            last_hb = time.time()
            while True:
                try:
                    msg = q.get(timeout=1.0)
                    yield msg
                except queue.Empty:
                    pass
                if time.time() - last_hb >= 15:
                    yield f"event: heartbeat\ndata: {json.dumps({'ts': utcnow_iso()})}\n\n"
                    last_hb = time.time()
        finally:
            try:
                _SSE_SUBSCRIBERS.remove(q)
            except ValueError:
                pass

    return Response(_gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ===========================================================================
# 1.9 Internal: upload callback (from n8n)
# ===========================================================================

@app.post("/api/callback")
def api_callback():
    body = request.get_json(silent=True) or {}
    job_id = body.get("job_id")
    if job_id is None:
        return _err("job_id required", "MISSING_JOB_ID", 400)
    dest_id = body.get("destination_id")
    if dest_id is None:
        return _err("destination_id required", "MISSING_FIELD", 400)

    job = g.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        return _err("job not found", "JOB_NOT_FOUND", 404)
    dest = g.db.execute("SELECT * FROM destinations WHERE id = ?", (dest_id,)).fetchone()
    if not dest:
        return _err("destination not found", "DESTINATION_NOT_FOUND", 404)

    status = (body.get("status") or "failed").strip()
    platform = body.get("platform") or dest["platform"]
    ai_tags = body.get("ai_tags") or []
    if not isinstance(ai_tags, list):
        ai_tags = []

    g.db.execute(
        """INSERT INTO upload_results
                (job_id, destination_id, platform, status, upload_url, error_message,
                 ai_used, ai_title, ai_description, ai_tags)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id, dest_id, platform, status,
            body.get("upload_url", ""), body.get("error_message", ""),
            1 if body.get("ai_used") else 0,
            body.get("ai_title", ""), body.get("ai_description", ""),
            json.dumps(ai_tags),
        ),
    )

    # Mirror into upload_ledger (cron path). See uploader._record_result for
    # the in-process equivalent. Idempotent + non-fatal on errors.
    try:
        yrow = g.db.execute(
            """SELECT v.youtube_video_id AS yvid
                 FROM jobs j LEFT JOIN videos v ON v.id = j.video_id
                WHERE j.id = ?""",
            (job_id,),
        ).fetchone()
        yvid = (yrow["yvid"] if yrow else "") or ""
        if yvid:
            ledger_status = "uploaded" if status in ("uploaded", "success") else "failed"
            g.db.execute(
                """INSERT OR IGNORE INTO upload_ledger
                        (video_id, destination_id, job_id, status,
                         destination_url, uploaded_at, error_message,
                         triggered_by)
                   VALUES (?, ?, ?, ?, ?,
                           strftime('%Y-%m-%dT%H:%M:%S','now'), ?, 'cron')""",
                (yvid, dest_id, job_id, ledger_status,
                 body.get("upload_url", "") or "", body.get("error_message", "") or ""),
            )
            g.db.execute(
                """UPDATE upload_ledger
                      SET status = ?, job_id = ?, destination_url = ?,
                          error_message = ?,
                          uploaded_at = strftime('%Y-%m-%dT%H:%M:%S','now'),
                          updated_at  = strftime('%Y-%m-%dT%H:%M:%S','now')
                    WHERE video_id = ? AND destination_id = ?""",
                (ledger_status, job_id, body.get("upload_url", "") or "",
                 body.get("error_message", "") or "", yvid, dest_id),
            )
    except Exception:
        pass

    total = g.db.execute(
        "SELECT COUNT(*) AS n FROM destinations WHERE pipeline_id = ? AND enabled = 1",
        (job["pipeline_id"],),
    ).fetchone()["n"]
    done = g.db.execute(
        "SELECT COUNT(*) AS n FROM upload_results WHERE job_id = ?", (job_id,)
    ).fetchone()["n"]
    succ = g.db.execute(
        "SELECT COUNT(*) AS n FROM upload_results WHERE job_id = ? AND status = 'success'",
        (job_id,),
    ).fetchone()["n"]

    if total > 0 and done >= total:
        new_status = "done" if succ == total else ("partial" if succ > 0 else "failed")
        g.db.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
        # PR6: auto-delete disabled by user — do not delete local files after upload.
        # if new_status == "done":
        #     _uploader._maybe_archive_and_cleanup(g.db, job_id, job["pipeline_id"])
    elif job["status"] not in ("done", "partial", "failed"):
        g.db.execute("UPDATE jobs SET status = 'uploading' WHERE id = ?", (job_id,))

    final = g.db.execute("SELECT status, updated_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
    _sse_broadcast("job_update", {
        "job_id": job_id,
        "status": final["status"],
        "updated_at": final["updated_at"],
    })
    return jsonify({"ok": True})


# ===========================================================================
# 1.10 Direct YouTube upload (dashboard-side resumable upload + live progress)
# ===========================================================================
#
# The n8n workflow POSTs here instead of using its built-in YouTube node.
# We perform the resumable upload in a background thread so we can stream
# byte-level progress to the browser via SSE (event=progress).
# OAuth token must be stored first via /oauth/youtube/start.

try:
    from dashboard import uploader as _uploader        # noqa: E402
    from dashboard import oauth_youtube as _oauth_yt   # noqa: E402
    from dashboard import ai_enricher as _ai_enricher  # noqa: E402
except ModuleNotFoundError:
    import uploader as _uploader                       # noqa: E402
    import oauth_youtube as _oauth_yt                  # noqa: E402
    import ai_enricher as _ai_enricher                 # noqa: E402


@app.post("/api/upload/youtube")
def api_upload_youtube():
    """Start a background YouTube upload. Body keys:
        job_id, destination_id, file_path, title,
        description (opt), tags (opt list), category_id (opt, default '22'),
        privacy_status (opt, default 'unlisted'),
        ai_used, ai_title, ai_description, ai_tags."""
    body = request.get_json(silent=True) or {}
    job_id = body.get("job_id")
    dest_id = body.get("destination_id")
    file_path = body.get("file_path")
    title = body.get("title")
    if job_id is None or dest_id is None or not file_path or not title:
        return _err("job_id, destination_id, file_path and title are required",
                    "MISSING_FIELD", 400)

    job = g.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        return _err("job not found", "JOB_NOT_FOUND", 404)
    dest = g.db.execute("SELECT * FROM destinations WHERE id=?", (dest_id,)).fetchone()
    if not dest:
        return _err("destination not found", "DESTINATION_NOT_FOUND", 404)

    # Already uploading? Don't double-start.
    inflight = g.db.execute(
        "SELECT id FROM upload_progress WHERE job_id=? AND destination_id=? "
        "AND stage IN ('starting','uploading','processing')",
        (job_id, dest_id),
    ).fetchone()
    if inflight:
        return _err("upload already in progress for this job/destination",
                    "ALREADY_RUNNING", 409)

    g.db.execute("UPDATE jobs SET status='uploading' WHERE id=?", (job_id,))
    _sse_broadcast("job_update", {"job_id": job_id, "status": "uploading"})

    tags = body.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    # Resolve privacy: explicit body value > destination default > 'unlisted'
    dest_privacy = ""
    try:
        dest_privacy = (dest["default_privacy"] or "").strip()
    except (IndexError, KeyError):
        pass  # column may not exist on legacy DBs
    privacy_status = (
        body.get("privacy_status") or dest_privacy or "unlisted"
    )

    # Resolve AI enrichment.
    # n8n may have already enriched and forwarded ai_used=true with fields.
    # If not, and OPENROUTER_API_KEY is set on the dashboard, do a best-effort
    # call ourselves so ai_used reflects reality regardless of how the upload
    # was triggered (n8n, manual queue, retry, etc.).
    ai_used = bool(body.get("ai_used"))
    ai_title = body.get("ai_title") or ""
    ai_description = body.get("ai_description") or ""
    ai_tags = body.get("ai_tags") or []
    description = body.get("description") or ""
    final_title = title
    if not ai_used and _ai_enricher.is_configured():
        # Pull a channel name hint from the job's pipeline if available.
        channel_name = ""
        try:
            row = g.db.execute(
                """SELECT c.name FROM jobs j
                     LEFT JOIN channels c ON c.pipeline_id = j.pipeline_id
                    WHERE j.id = ?
                    LIMIT 1""",
                (job_id,),
            ).fetchone()
            if row and row[0]:
                channel_name = row[0]
        except Exception:                                       # noqa: BLE001
            pass
        ok, data, reason = _ai_enricher.enrich(title, channel_name)
        print(f"[ai_enricher] job={job_id} ok={ok} reason={reason}", flush=True)
        if ok and data:
            ai_used = True
            ai_title = data["youtube_title"]
            ai_description = data["youtube_description"]
            ai_tags = data["youtube_tags"]
            # Apply enriched values to the actual upload too.
            final_title = ai_title or title
            description = ai_description or description
            if not tags:
                tags = ai_tags

    _uploader.upload_youtube_async(
        job_id=int(job_id),
        destination_id=int(dest_id),
        file_path=file_path,
        title=final_title,
        description=description,
        tags=tags,
        category_id=str(body.get("category_id") or "22"),
        privacy_status=privacy_status,
        ai_used=ai_used,
        ai_title=ai_title,
        ai_description=ai_description,
        ai_tags=ai_tags,
        broadcast=_sse_broadcast,
    )
    return jsonify({"ok": True, "job_id": job_id, "destination_id": dest_id,
                    "message": "upload started", "ai_used": ai_used})


@app.get("/api/ai/status")
def api_ai_status():
    """Report whether dashboard-side AI enrichment is configured."""
    return jsonify({
        "enabled": _ai_enricher.is_configured(),
        "has_api_key": bool(os.getenv("OPENROUTER_API_KEY")),
        "model": os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free"),
    })


@app.post("/api/upload/cancel/<int:job_id>/<int:dest_id>")
def api_upload_cancel(job_id: int, dest_id: int):
    _uploader.request_cancel(job_id, dest_id)
    return jsonify({"ok": True})


@app.get("/api/upload/active")
def api_upload_active():
    rows = g.db.execute(
        "SELECT * FROM upload_progress "
        "WHERE stage NOT IN ('done','failed','canceled') "
        "AND datetime(updated_at) > datetime('now', '-90 seconds') "
        "ORDER BY started_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        bt, bu = d["bytes_total"] or 0, d["bytes_uploaded"] or 0
        d["percent"] = round((bu / bt * 100), 1) if bt else 0.0
        out.append(d)
    return jsonify({"active_uploads": out})


# ---- OAuth ---------------------------------------------------------------

@app.get("/oauth/youtube/status")
def oauth_youtube_status():
    return jsonify(_oauth_yt.get_status())


@app.get("/oauth/youtube/start")
def oauth_youtube_start():
    try:
        pid_raw = request.args.get("project_id", "").strip()
        pid = int(pid_raw) if pid_raw else None
        url, _state = _oauth_yt.build_auth_url(project_id=pid)
    except RuntimeError as e:
        return _err(str(e), "OAUTH_NOT_CONFIGURED", 500)
    except ValueError:
        return _err("project_id must be an integer", "BAD_PROJECT_ID", 400)
    return redirect(url)


@app.get("/oauth/youtube/reauth_next")
def oauth_youtube_reauth_next():
    """Find the next project whose token needs re-auth and redirect into
    the OAuth start flow for it. When no more dead tokens remain, returns
    to /projects with ?reauth_done=1. Useful as a 'Reconnect all' button
    that the user can click between sequential authorizations.
    """
    after_raw = (request.args.get("after") or "").strip()
    after = int(after_raw) if after_raw.isdigit() else 0
    row = g.db.execute(
        "SELECT project_id FROM oauth_tokens "
        "WHERE platform='youtube' AND needs_reauth=1 AND project_id > ? "
        "ORDER BY project_id LIMIT 1",
        (after,),
    ).fetchone()
    if not row or not row["project_id"]:
        return redirect("/projects?reauth_done=1")
    return redirect(f"/oauth/youtube/start?project_id={int(row['project_id'])}")


@app.get("/oauth/youtube/callback")
def oauth_youtube_callback():
    code = request.args.get("code")
    err = request.args.get("error")
    if err:
        return f"<h2>OAuth error</h2><pre>{err}</pre>", 400
    if not code:
        return _err("missing ?code", "MISSING_CODE", 400)
    try:
        row = _oauth_yt.exchange_code(code, state=request.args.get("state"))
    except Exception as e:
        return f"<h2>Token exchange failed</h2><pre>{type(e).__name__}: {e}</pre>", 500
    # Clear any prior needs_reauth flag for this token — the user just
    # successfully re-authorized.
    try:
        g.db.execute(
            "UPDATE oauth_tokens SET needs_reauth=0, last_error='' WHERE id=?",
            (row.get("id"),),
        )
    except Exception:                                                # noqa: BLE001
        pass
    label = row.get("account_label") or "(unknown)"
    pid = row.get("project_id") or 0
    # Auto-jump into the next dead token if one exists, so the user can
    # walk through all re-auths in one sitting.
    next_row = g.db.execute(
        "SELECT project_id FROM oauth_tokens "
        "WHERE platform='youtube' AND needs_reauth=1 AND project_id > ? "
        "ORDER BY project_id LIMIT 1",
        (int(pid),),
    ).fetchone()
    next_link = (f"/oauth/youtube/start?project_id={int(next_row['project_id'])}"
                 if next_row and next_row['project_id'] else "/projects")
    next_text = ("Continue to next dead token →"
                 if next_row and next_row['project_id']
                 else "← Back to /projects")
    return (
        f"<html><body style='font-family:sans-serif;padding:2rem;background:#0d1117;color:#c9d1d9'>"
        f"<h2 style='color:#3fb950'>✓ YouTube connected</h2>"
        f"<p>Account: <b>{label}</b></p>"
        f"<p><a href='{next_link}' style='color:#58a6ff'>{next_text}</a></p>"
        f"</body></html>"
    )


# ---------------------------------------------------------------------------
# 1.10b — YouTube Cloud-project rotation
# Multiple projects → rotate uploads across them, ~6 uploads/day each.
# ---------------------------------------------------------------------------
try:
    from dashboard import projects as _yt_projects   # noqa: E402
except ModuleNotFoundError:
    import projects as _yt_projects                  # type: ignore  # noqa: E402


@app.get("/projects")
def page_projects():
    return _render_or_stub("projects.html", "YouTube Projects")


@app.get("/partials/projects/list")
def partial_projects_list():
    items = _yt_projects.list_projects(g.db)
    # Annotate each with its connected channel (if any).
    for it in items:
        row = g.db.execute(
            "SELECT account_label, updated_at, youtube_channel_id "
            "FROM oauth_tokens "
            "WHERE platform='youtube' AND project_id=? ORDER BY id DESC LIMIT 1",
            (it["id"],),
        ).fetchone()
        it["account_label"] = row["account_label"] if row else ""
        it["token_updated_at"] = row["updated_at"] if row else ""
        it["youtube_channel_id"] = (row["youtube_channel_id"]
                                    if row else None)
    return render_template("partials/projects_list.html", items=items)


@app.get("/partials/projects/by_channel")
def partial_projects_by_channel():
    """Group projects by their bound YouTube channel.

    Returns one card per channel + an "Unbound" bucket for projects whose
    OAuth token hasn't been issued yet (or whose channel detection is
    pending). Each card shows fleet capacity (sum of caps), uploads used
    today, next-pick badge, and per-project rows.
    """
    items = _yt_projects.list_projects(g.db)

    # ---- Annotate each project with channel + token info ----------------
    project_meta: dict[int, dict] = {}
    for it in items:
        row = g.db.execute(
            "SELECT id AS token_id, account_label, updated_at, "
            "       youtube_channel_id, last_refreshed_at, token_expiry, "
            "       needs_reauth, last_error, created_at "
            "FROM oauth_tokens "
            "WHERE platform='youtube' AND project_id=? ORDER BY id DESC LIMIT 1",
            (it["id"],),
        ).fetchone()
        it["account_label"]      = row["account_label"]      if row else ""
        it["token_updated_at"]   = row["updated_at"]         if row else ""
        it["youtube_channel_id"] = (row["youtube_channel_id"] if row else None)
        it["last_refreshed_at"]  = (row["last_refreshed_at"] if row else "")
        it["token_expiry"]       = (row["token_expiry"]      if row else "")
        it["needs_reauth"]       = bool(row["needs_reauth"]) if row else False
        it["last_error"]         = (row["last_error"]        if row else "")
        it["token_created_at"]   = (row["created_at"]        if row else "")
        project_meta[int(it["id"])] = it

    # ---- Build channel map (id -> dict) ---------------------------------
    channel_rows = g.db.execute(
        "SELECT * FROM youtube_channels ORDER BY title COLLATE NOCASE"
    ).fetchall()
    channels: dict[int, dict] = {int(r["id"]): dict(r) for r in channel_rows}

    # ---- Bucket projects by channel ------------------------------------
    buckets: dict[object, dict] = {}
    for it in items:
        ch_id = it.get("youtube_channel_id")
        key = int(ch_id) if ch_id else "_unbound"
        if key not in buckets:
            if key == "_unbound":
                buckets[key] = {
                    "channel": None,
                    "projects": [],
                    "cap_total": 0,
                    "used_total": 0,
                    "next_pick_id": None,
                }
            else:
                buckets[key] = {
                    "channel": channels.get(int(ch_id), {
                        "id": int(ch_id),
                        "title": "(unknown channel)",
                        "channel_id": "",
                        "thumbnail_url": "",
                        "owner_email": "",
                    }),
                    "projects": [],
                    "cap_total": 0,
                    "used_total": 0,
                    "next_pick_id": None,
                }
        b = buckets[key]
        b["projects"].append(it)
        b["cap_total"]  += int(it["daily_cap"] or 0)
        b["used_total"] += int(it["uploads_today"] or 0)

    # ---- Compute next-pick per channel (mirror picker logic) -----------
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    for key, b in buckets.items():
        if key == "_unbound":
            continue
        eligible = []
        for p in b["projects"]:
            if not p["active"]:
                continue
            if p.get("needs_reauth"):
                continue
            if p.get("quota_resets_at") and p["quota_resets_at"] > now_iso:
                continue
            if int(p["uploads_today"]) >= int(p["daily_cap"]):
                continue
            eligible.append(p)
        if eligible:
            eligible.sort(key=lambda p: (int(p["uploads_today"]),
                                          p.get("last_used_at") or ""))
            b["next_pick_id"] = int(eligible[0]["id"])

    # ---- Sort: channels alphabetically, _unbound last ------------------
    sorted_buckets = []
    for key, b in buckets.items():
        if key == "_unbound":
            continue
        sorted_buckets.append(b)
    sorted_buckets.sort(key=lambda b: (b["channel"].get("title") or "").lower())
    if "_unbound" in buckets:
        sorted_buckets.append(buckets["_unbound"])

    return render_template("partials/projects_by_channel.html",
                           buckets=sorted_buckets)


@app.get("/partials/projects/reauth_summary")
def partial_projects_reauth_summary():
    """Tiny banner partial: shows a 'Reconnect all' CTA when any YouTube
    OAuth token is flagged as needs_reauth=1. Polled every 30s on /projects.
    Renders an empty string when nothing is wrong (so the banner area
    silently disappears).
    """
    rows = g.db.execute(
        "SELECT t.project_id, p.label "
        "FROM oauth_tokens t LEFT JOIN youtube_projects p ON p.id = t.project_id "
        "WHERE t.platform='youtube' AND t.needs_reauth=1 "
        "ORDER BY t.project_id"
    ).fetchall()
    if not rows:
        return ""
    first_pid = next((r["project_id"] for r in rows if r["project_id"]), None)
    labels = [r["label"] or f"#{r['project_id']}" for r in rows if r["project_id"]]
    return (
        f'<div class="rounded border border-red-700 bg-red-900/20 px-3 py-2 '
        f'text-sm text-red-200 flex items-center justify-between gap-3">'
        f'<div>'
        f'  <strong>{len(rows)} project token(s) need re-authorization.</strong> '
        f'  <span class="text-red-300/80">Likely causes: 7-day Testing-mode '
        f'  expiry, 6-month inactivity, or a rotated client secret.</span>'
        f'  <div class="text-[11px] mt-0.5 truncate text-red-300/70">'
        f'    {", ".join(labels[:8])}{"…" if len(labels) > 8 else ""}'
        f'  </div>'
        f'</div>'
        + (f'<a href="/oauth/youtube/start?project_id={int(first_pid)}" '
           f'   class="shrink-0 px-3 py-1.5 rounded bg-red-600 hover:bg-red-500 '
           f'   text-white text-sm font-medium">Reconnect all →</a>'
           if first_pid else "")
        + '</div>'
    )


@app.post("/api/projects")
def api_create_project():
    """Accept either JSON {label, client_id, client_secret, daily_cap} OR
    one or more Google Cloud OAuth client JSON files under field
    'secrets_json' (multiple supported via <input multiple>). When several
    files are uploaded, each becomes its own project row, with labels
    auto-derived from the JSON's project_id field unless an explicit
    label_prefix is supplied (in which case files become PREFIX-A, -B…).
    """
    label = ""
    client_id = ""
    client_secret = ""
    daily_cap = 6

    # Path A: file upload (one or many)
    files = []
    if "secrets_json" in request.files:
        files = [f for f in request.files.getlist("secrets_json")
                 if f and f.filename]

    if files:
        cap_raw = (request.form.get("daily_cap", "") or "").strip()
        if cap_raw:
            try:
                daily_cap = max(1, int(cap_raw))
            except ValueError:
                daily_cap = 6
        label_prefix = (request.form.get("label_prefix", "") or "").strip()
        # Use a single label override only when exactly ONE file uploaded.
        single_label = (request.form.get("label", "") or "").strip()

        created: list[int] = []
        errors: list[str] = []
        for idx, fobj in enumerate(files):
            try:
                raw = fobj.read().decode("utf-8")
                data = json.loads(raw)
                block = data.get("web") or data.get("installed") or {}
                cid = (block.get("client_id") or "").strip()
                csec = (block.get("client_secret") or "").strip()
                if not (cid and csec):
                    errors.append(f"{fobj.filename}: missing client_id/secret")
                    continue
                if label_prefix:
                    suffix = chr(ord("A") + idx) if idx < 26 else str(idx + 1)
                    this_label = f"{label_prefix}-{suffix}"
                elif single_label and len(files) == 1:
                    this_label = single_label
                else:
                    this_label = (block.get("project_id") or
                                  fobj.filename.rsplit(".", 1)[0])
                pid = _yt_projects.add_project(this_label, cid, csec, daily_cap)
                created.append(pid)
            except Exception as e:                                # noqa: BLE001
                errors.append(f"{fobj.filename}: {e}")

        if request.form:
            # Browser submission → return to /projects with a flash-style
            # query param the page can surface.
            from urllib.parse import urlencode
            qs = urlencode({
                "added": len(created),
                "errors": "; ".join(errors)[:500] if errors else "",
            })
            return redirect(f"/projects?{qs}")
        return jsonify({"ok": True, "created": created, "errors": errors})

    # Path B: JSON body or form fields (single project).
    body = request.get_json(silent=True) or request.form.to_dict()
    label = (body.get("label") or "").strip()
    client_id = (body.get("client_id") or "").strip()
    client_secret = (body.get("client_secret") or "").strip()
    try:
        daily_cap = max(1, int(body.get("daily_cap") or 6))
    except (TypeError, ValueError):
        daily_cap = 6

    if not (client_id and client_secret):
        return _err("client_id and client_secret are required",
                    "MISSING_CREDS", 400)

    try:
        pid = _yt_projects.add_project(label, client_id, client_secret, daily_cap)
    except Exception as e:                                        # noqa: BLE001
        return _err(str(e), "ADD_FAILED", 500)

    if request.form:
        return redirect("/projects")
    return jsonify({"ok": True, "id": pid})


@app.post("/api/projects/<int:pid>/delete")
def api_delete_project(pid: int):
    _yt_projects.delete_project(pid)
    return redirect("/projects") if request.form else jsonify({"ok": True})


@app.post("/api/projects/<int:pid>/toggle")
def api_toggle_project(pid: int):
    proj = _yt_projects.get_project(pid)
    if not proj:
        return _err("not found", "NOT_FOUND", 404)
    _yt_projects.set_active(pid, not bool(proj["active"]))
    return redirect("/projects") if request.form else jsonify({"ok": True})


@app.post("/api/projects/<int:pid>/reset_counter")
def api_reset_project_counter(pid: int):
    """Manually clear today's counter and quota cooldown (admin override)."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE youtube_projects SET uploads_today=0, quota_resets_at='', "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%S','now') WHERE id=?",
            (pid,),
        )
    finally:
        conn.close()
    return redirect("/projects") if request.form else jsonify({"ok": True})


@app.get("/partials/active_uploads")
def partial_active_uploads():
    rows = g.db.execute(
        "SELECT up.*, v.original_title, c.name AS channel_name, "
        "       v.youtube_video_id AS source_video_id "
        "FROM upload_progress up "
        "JOIN jobs j ON j.id=up.job_id "
        "JOIN videos v ON v.id=j.video_id "
        "JOIN channels c ON c.id=v.channel_id "
        "WHERE up.stage NOT IN ('done','failed','canceled') "
        "AND datetime(up.updated_at) > datetime('now', '-90 seconds') "
        "ORDER BY up.started_at DESC"
    ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        bt = d["bytes_total"] or 0
        bu = d["bytes_uploaded"] or 0
        d["percent"] = round((bu / bt * 100), 1) if bt else 0.0
        d["mb_total"] = round(bt / 1024 / 1024, 1)
        d["mb_uploaded"] = round(bu / 1024 / 1024, 1)
        d["mbps"] = round((d["speed_bps"] or 0) / 1024 / 1024, 2)
        items.append(d)
    return render_template("partials/active_uploads.html",
                           items=items,
                           recent=_recent_upload_results(g.db, limit=5),
                           youtube_status=_oauth_yt.get_status())


def _recent_upload_results(conn: sqlite3.Connection, limit: int = 3) -> list[dict]:
    # Dedup by (job_id, destination_id): hide superseded retries so a job
    # that eventually succeeded doesn't show its earlier failures.
    rows = conn.execute(
        """SELECT ur.created_at, ur.status, ur.upload_url,
                  v.original_title AS title
             FROM upload_results ur
             JOIN (
                SELECT job_id, destination_id, MAX(id) AS max_id
                  FROM upload_results
                 GROUP BY job_id, destination_id
             ) latest
               ON latest.max_id = ur.id
        LEFT JOIN jobs j  ON j.id = ur.job_id
        LEFT JOIN videos v ON v.id = j.video_id
            ORDER BY ur.id DESC
            LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ===========================================================================
# 1.11 Uploads tab — manual one-click + bulk + backfill
# ===========================================================================
#
# Three surfaces share a single "kick off an async YouTube upload" helper:
#   * /api/uploads/manual   — single or list of (job, destination) targets
#   * /api/uploads/bulk     — same payload shape, distinct route name
#   * backfill worker       — iterates all ready rows automatically
#
# All paths funnel into _enqueue_upload(), which performs the same
# AI-enrichment + uploader.upload_youtube_async work as /api/upload/youtube
# but reads file_path/title from the DB instead of trusting the caller.

# ---- Backfill global state (module-level; single worker thread) ----------
_backfill_state: dict = {
    "running": False,
    "paused": False,
    "total": 0,
    "done": 0,
    "failed": 0,
    "current": None,                # {"job_id":..., "dest_label":...}
    "recent": [],                   # last ~20 results
    "last_finished_at": "",
    "thread": None,
    "stop_flag": False,
}
_backfill_lock = threading.Lock()


def _ready_to_upload_rows(
    conn: sqlite3.Connection,
    limit: int = 500,
    sort: str = "date_desc",
) -> list[dict]:
    """Each row = (job, destination) pair where:
       * job has a source_file_path on disk (download finished)
       * the destination is enabled and on the same pipeline
       * no successful upload_results row exists for that pair
       * no in-flight upload_progress row exists for that pair
    """
    rows = conn.execute(
        """
        SELECT
            j.id              AS job_id,
            j.pipeline_id     AS pipeline_id,
            j.source_file_path AS file_path,
            j.status          AS job_status,
            j.updated_at      AS downloaded_at,
            v.original_title  AS raw_original_title,
            v.youtube_video_id AS source_video_id,
            v.duration         AS v_duration,
            v.published_at     AS v_published_at,
            v.thumbnail_url    AS v_thumbnail,
            v.view_count       AS v_view_count,
            v.like_count       AS v_like_count,
            c.name            AS channel_name,
            d.id              AS destination_id,
            d.platform        AS platform,
            d.label           AS dest_label,
            d.default_privacy AS privacy,
            (SELECT cv.upload_date FROM catalog_videos cv
              WHERE cv.video_id = v.youtube_video_id
              ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_upload_date,
            (SELECT cv.view_count FROM catalog_videos cv
              WHERE cv.video_id = v.youtube_video_id
              ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_view_count,
            (SELECT cv.like_count FROM catalog_videos cv
              WHERE cv.video_id = v.youtube_video_id
              ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_like_count,
            (SELECT cv.duration_sec FROM catalog_videos cv
              WHERE cv.video_id = v.youtube_video_id
              ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_duration_sec,
            (SELECT cv.thumbnail_url FROM catalog_videos cv
              WHERE cv.video_id = v.youtube_video_id
              ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_thumbnail,
            (SELECT cv.title FROM catalog_videos cv
              WHERE cv.video_id = v.youtube_video_id
              ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_title,
            (SELECT ur.error_message FROM upload_results ur
              WHERE ur.job_id = j.id AND ur.destination_id = d.id
              ORDER BY ur.id DESC LIMIT 1) AS last_error
        FROM jobs j
        JOIN videos v        ON v.id = j.video_id
        LEFT JOIN channels c ON c.id = v.channel_id
        JOIN destinations d  ON d.pipeline_id = j.pipeline_id AND d.enabled = 1
        WHERE j.source_file_path != ''
          AND j.status IN ('downloaded','processed','done','partial','failed','uploading')
          AND COALESCE(v.archived_at, '') = ''
          AND j.id = (
              SELECT MAX(j2.id) FROM jobs j2
               WHERE j2.video_id = j.video_id
                 AND j2.source_file_path != ''
                 AND j2.status IN ('downloaded','processed','done','partial','failed','uploading')
          )
          AND NOT EXISTS (
              SELECT 1 FROM upload_results ur
               WHERE ur.job_id = j.id
                 AND ur.destination_id = d.id
                 AND ur.status IN ('uploaded','success')
          )
          AND NOT EXISTS (
              SELECT 1 FROM upload_progress up
               WHERE up.job_id = j.id
                 AND up.destination_id = d.id
                 AND up.stage IN ('starting','uploading','processing')
          )
        ORDER BY j.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    out = []
    downloads_root = os.getenv("DOWNLOADS_DIR", "/shared/downloads")
    for r in rows:
        d = dict(r)
        # Resolve path: cron writes "/downloads/..." (its own mount); inside
        # the dashboard container the same volume is at $DOWNLOADS_DIR.
        # Also tolerate already-correct or relative paths.
        fp = d["file_path"] or ""
        if fp.startswith("/downloads/"):
            fp = downloads_root.rstrip("/") + fp[len("/downloads"):]
        elif fp and not os.path.isabs(fp):
            fp = os.path.join(downloads_root, fp)
        size = 0
        try:
            if fp and os.path.exists(fp):
                size = os.path.getsize(fp)
        except OSError:
            pass
        d["abs_file_path"] = fp
        d["size_bytes"] = size
        d["size_h"] = _human_bytes(size) if size else "—"
        # original_title is sometimes stored as the bare video-id (watcher didn't
        # populate it); prefer catalog_videos.title when that happens.
        raw_title = d.get("raw_original_title") or ""
        vid_id    = d.get("source_video_id") or ""
        cv_title  = d.get("cv_title") or ""
        if raw_title and raw_title != vid_id:
            d["title"] = raw_title
        elif cv_title:
            d["title"] = cv_title
        else:
            d["title"] = raw_title or os.path.basename(fp) or f"job {d['job_id']}"
        # Display-friendly metadata (videos row first, catalog as fallback).
        d["disp_thumb"] = d.get("cv_thumbnail") or d.get("v_thumbnail") or ""
        d["disp_duration"] = _fmt_duration(
            d.get("cv_duration_sec") or d.get("v_duration")
        )
        d["disp_views"] = _fmt_views(
            d.get("v_view_count") if d.get("v_view_count") is not None
            else d.get("cv_view_count")
        )
        d["disp_likes"] = _fmt_views(
            d.get("v_like_count") if d.get("v_like_count") is not None
            else d.get("cv_like_count")
        )
        d["disp_upload_date"] = _fmt_upload_date(
            d.get("cv_upload_date") or d.get("v_published_at")
        )
        meta = _probe_video_meta(fp)
        d["disp_resolution"] = meta.get("resolution", "")
        d["disp_format"] = meta.get("format", "")
        d["disp_vcodec"] = meta.get("vcodec", "")
        d["disp_res_long"] = meta.get("res_long", "")
        out.append(d)

    # Apply sort
    _SORT_REVERSE = {"date_desc", "duration_desc", "size_desc"}
    if sort in ("date_asc", "date_desc"):
        out.sort(
            key=lambda x: x.get("cv_upload_date") or x.get("v_published_at") or "",
            reverse=(sort in _SORT_REVERSE),
        )
    elif sort in ("duration_asc", "duration_desc"):
        out.sort(
            key=lambda x: x.get("cv_duration_sec") or x.get("v_duration") or 0,
            reverse=(sort in _SORT_REVERSE),
        )
    elif sort in ("size_asc", "size_desc"):
        out.sort(
            key=lambda x: x.get("size_bytes") or 0,
            reverse=(sort in _SORT_REVERSE),
        )
    # else: keep SQL default (downloaded_at DESC)

    return out


def _human_bytes(n: int) -> str:
    n = int(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _enqueue_upload(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    destination_id: int,
    privacy_override: str = "",
    use_ai: bool = True,
    overrides: Optional[dict] = None,
) -> tuple[bool, str]:
    """Kick off a single async YouTube upload. Returns (ok, message).
       Mirrors the heart of /api/upload/youtube but pulls file/title from DB.
    """
    job  = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        return False, "job not found"
    dest = conn.execute("SELECT * FROM destinations WHERE id=?", (destination_id,)).fetchone()
    if not dest:
        return False, "destination not found"
    if dest["pipeline_id"] != job["pipeline_id"]:
        return False, "destination/job pipeline mismatch"

    # Already uploading?
    inflight = conn.execute(
        "SELECT id FROM upload_progress WHERE job_id=? AND destination_id=? "
        "AND stage IN ('starting','uploading','processing')",
        (job_id, destination_id),
    ).fetchone()
    if inflight:
        return False, "already in progress"

    fp = job["source_file_path"] or ""
    downloads_root = os.getenv("DOWNLOADS_DIR", "/shared/downloads")
    if fp.startswith("/downloads/"):
        fp = downloads_root.rstrip("/") + fp[len("/downloads"):]
    elif fp and not os.path.isabs(fp):
        fp = os.path.join(downloads_root, fp)
    if not fp or not os.path.exists(fp):
        return False, f"file missing: {fp or '(empty)'}"

    vid = conn.execute(
        "SELECT v.original_title, c.name AS channel_name "
        "FROM videos v LEFT JOIN channels c ON c.id=v.channel_id "
        "WHERE v.id=?", (job["video_id"],)
    ).fetchone()
    title = (vid["original_title"] if vid else "") or os.path.basename(fp)
    channel_name = (vid["channel_name"] if vid else "") or ""

    privacy = (privacy_override or "").strip()
    if not privacy:
        try:
            privacy = (dest["default_privacy"] or "").strip() or "unlisted"
        except (IndexError, KeyError):
            privacy = "unlisted"

    # AI enrich (best effort, only if requested & configured)
    ai_used = False
    ai_title = ai_description = ""
    ai_tags: list = []
    final_title = title
    description = ""
    if use_ai and _ai_enricher.is_configured():
        ok, data, reason = _ai_enricher.enrich(title, channel_name)
        print(f"[ai_enricher][manual] job={job_id} ok={ok} reason={reason}", flush=True)
        if ok and data:
            ai_used = True
            ai_title = data["youtube_title"]
            ai_description = data["youtube_description"]
            ai_tags = data["youtube_tags"]
            final_title = ai_title or title
            description = ai_description or ""

    conn.execute("UPDATE jobs SET status='uploading' WHERE id=?", (job_id,))
    conn.commit()
    _sse_broadcast("job_update", {"job_id": job_id, "status": "uploading"})

    _uploader.upload_youtube_async(
        job_id=int(job_id),
        destination_id=int(destination_id),
        file_path=fp,
        title=final_title,
        description=description,
        tags=list(ai_tags),
        category_id="22",
        privacy_status=privacy,
        ai_used=ai_used,
        ai_title=ai_title,
        ai_description=ai_description,
        ai_tags=ai_tags,
        broadcast=_sse_broadcast,
        overrides=overrides or {},
    )
    return True, "started"


# ---- HTML partials -------------------------------------------------------

@app.get("/partials/uploads/ready")
def partial_uploads_ready():
    sort = request.args.get("sort", "date_desc")
    channel_filter = request.args.get("channel_filter", "")
    # Validate sort value to prevent unexpected behaviour
    _valid_sorts = {"date_desc", "date_asc", "duration_desc", "duration_asc", "size_desc", "size_asc"}
    if sort not in _valid_sorts:
        sort = "date_desc"

    items = _ready_to_upload_rows(g.db, sort=sort)
    # Collect distinct channel names before applying filter (for the dropdown)
    channels = sorted({it["channel_name"] for it in items if it.get("channel_name")})
    if channel_filter:
        items = [it for it in items if it.get("channel_name") == channel_filter]
    total = len(items)
    return render_template(
        "partials/uploads_ready.html",
        items=items,
        total=total,
        sort=sort,
        channel_filter=channel_filter,
        channels=channels,
    )


@app.get("/partials/uploads/recent")
def partial_uploads_recent():
    # Dedupe by (job_id, destination_id): show only the LATEST attempt per
    # target. Hides earlier failed retries once a successful upload exists
    # (or once a newer attempt supersedes them).
    rows = g.db.execute(
        """SELECT ur.*, v.original_title AS title,
                  v.youtube_video_id AS source_video_id,
                  v.duration AS v_duration,
                  v.published_at AS v_published_at,
                  v.thumbnail_url AS v_thumbnail,
                  v.view_count   AS v_view_count,
                  v.like_count   AS v_like_count,
                  c.name AS channel_name,
                  d.label AS dest_label,
                  j.source_file_path AS file_path,
                  (SELECT cv.upload_date FROM catalog_videos cv
                    WHERE cv.video_id = v.youtube_video_id
                    ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_upload_date,
                  (SELECT cv.view_count FROM catalog_videos cv
                    WHERE cv.video_id = v.youtube_video_id
                    ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_view_count,
                  (SELECT cv.duration_sec FROM catalog_videos cv
                    WHERE cv.video_id = v.youtube_video_id
                    ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_duration_sec,
                  (SELECT cv.thumbnail_url FROM catalog_videos cv
                    WHERE cv.video_id = v.youtube_video_id
                    ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_thumbnail
             FROM upload_results ur
             JOIN (
                SELECT job_id, destination_id, MAX(id) AS max_id
                  FROM upload_results
                 GROUP BY job_id, destination_id
             ) latest
               ON latest.max_id = ur.id
        LEFT JOIN jobs j  ON j.id = ur.job_id
        LEFT JOIN videos v ON v.id = j.video_id
        LEFT JOIN channels c ON c.id = v.channel_id
        LEFT JOIN destinations d ON d.id = ur.destination_id
            ORDER BY ur.id DESC
            LIMIT 10"""
    ).fetchall()
    enriched = []
    downloads_root = os.getenv("DOWNLOADS_DIR", "/shared/downloads")
    for r in rows:
        d = dict(r)
        d["disp_thumb"] = d.get("cv_thumbnail") or d.get("v_thumbnail") or ""
        d["disp_duration"] = _fmt_duration(
            d.get("cv_duration_sec") or d.get("v_duration")
        )
        d["disp_views"] = _fmt_views(
            d.get("v_view_count") if d.get("v_view_count") is not None
            else d.get("cv_view_count")
        )
        d["disp_upload_date"] = _fmt_upload_date(
            d.get("cv_upload_date") or d.get("v_published_at")
        )
        # Resolution/format from sibling .info.json (file may be gone after
        # cleanup — _probe_video_meta returns {} silently in that case).
        fp = d.get("file_path") or ""
        if fp.startswith("/downloads/"):
            fp = downloads_root.rstrip("/") + fp[len("/downloads"):]
        meta = _probe_video_meta(fp)
        d["disp_resolution"] = meta.get("resolution", "")
        d["disp_format"] = meta.get("format", "")
        d["disp_vcodec"] = meta.get("vcodec", "")
        d["disp_res_long"] = meta.get("res_long", "")
        enriched.append(d)
    return render_template(
        "partials/uploads_recent.html", rows=enriched
    )


# --------------------------------------------------------------------------
# Cancel / un-cancel a *failed* upload_results row.
#
# Pure status flip — no file deletion, no DB row removal. Reversible.
# A 'cancelled' row hides the Retry button on the recent list and is
# ignored by all retry / requeue paths (the quota retry sweep only
# touches status='deferred', not 'failed' or 'cancelled', so this is
# automatic). Re-renders the recent partial so the UI updates in place.
# --------------------------------------------------------------------------
@app.post("/partials/uploads/<int:urid>/cancel")
def partial_upload_result_cancel(urid: int):
    row = g.db.execute(
        "SELECT id, status FROM upload_results WHERE id = ?", (urid,),
    ).fetchone()
    if not row:
        return _err("upload result not found", "NOT_FOUND", 404)
    if row["status"] != "failed":
        return _err(
            f"only 'failed' uploads can be cancelled (current: {row['status']})",
            "INVALID_STATE", 400,
        )
    g.db.execute(
        "UPDATE upload_results SET status = 'cancelled' WHERE id = ?",
        (urid,),
    )
    return partial_uploads_recent()


@app.post("/partials/uploads/<int:urid>/uncancel")
def partial_upload_result_uncancel(urid: int):
    row = g.db.execute(
        "SELECT id, status FROM upload_results WHERE id = ?", (urid,),
    ).fetchone()
    if not row:
        return _err("upload result not found", "NOT_FOUND", 404)
    if row["status"] != "cancelled":
        return _err(
            f"only 'cancelled' uploads can be un-cancelled (current: {row['status']})",
            "INVALID_STATE", 400,
        )
    g.db.execute(
        "UPDATE upload_results SET status = 'failed' WHERE id = ?",
        (urid,),
    )
    return partial_uploads_recent()


@app.get("/partials/uploads/backfill")
def partial_uploads_backfill():
    with _backfill_lock:
        st = dict(_backfill_state)
        st["recent"] = list(st["recent"])[-10:]
    st["pending_count"] = len(_ready_to_upload_rows(g.db, limit=500))
    return render_template("partials/uploads_backfill.html", state=st)


# ---- API: manual & bulk --------------------------------------------------

def _coerce_targets(body: dict) -> list[tuple[int, int]]:
    """Normalize accepted shapes:
         {targets: [{job_id, destination_id}, ...]}
         {job_id: X, destination_ids: [Y, Z]}
       Returns list of (job_id, destination_id) tuples.
    """
    out: list[tuple[int, int]] = []
    if isinstance(body.get("targets"), list):
        for t in body["targets"]:
            try:
                out.append((int(t["job_id"]), int(t["destination_id"])))
            except (KeyError, TypeError, ValueError):
                continue
    elif body.get("job_id") is not None and isinstance(body.get("destination_ids"), list):
        try:
            jid = int(body["job_id"])
        except (TypeError, ValueError):
            return []
        for d in body["destination_ids"]:
            try:
                out.append((jid, int(d)))
            except (TypeError, ValueError):
                continue
    elif body.get("job_id") is not None and body.get("destination_id") is not None:
        try:
            out.append((int(body["job_id"]), int(body["destination_id"])))
        except (TypeError, ValueError):
            return []
    return out


@app.post("/api/uploads/manual")
def api_uploads_manual():
    body = request.get_json(silent=True) or {}
    targets = _coerce_targets(body)
    if not targets:
        return _err("no valid targets", "MISSING_TARGETS", 400)
    privacy = (body.get("privacy") or "").strip()
    use_ai = bool(body.get("use_ai", True))

    # PR7+: parse per-batch upload overrides from the toolbar. Empty / missing
    # means "keep per-destination default".
    def _tri(val) -> Optional[bool]:
        if val is None:
            return None
        s = str(val).strip().lower()
        if s in ("", "default", "none"):
            return None
        if s in ("1", "true", "on", "yes"):
            return True
        if s in ("0", "false", "off", "no"):
            return False
        return None

    overrides: dict = {}
    for k in ("comments_enabled", "made_for_kids",
              "embeddable", "notify_subscribers"):
        v = _tri(body.get(k))
        if v is not None:
            overrides[k] = v
    raw_tags = (body.get("tags_extra") or "").strip()
    if raw_tags:
        overrides["tags_extra"] = [
            t.strip() for t in raw_tags.split(",") if t.strip()
        ]
    cat = (body.get("category_id") or "").strip()
    if cat:
        if not cat.isdigit():
            return _err("category_id must be numeric", "INVALID_CATEGORY", 400)
        overrides["category_id"] = cat

    started, skipped = [], []
    for jid, did in targets:
        ok, msg = _enqueue_upload(
            g.db, job_id=jid, destination_id=did,
            privacy_override=privacy, use_ai=use_ai,
            overrides=overrides,
        )
        (started if ok else skipped).append(
            {"job_id": jid, "destination_id": did, "message": msg}
        )
    return jsonify({"ok": True, "started": started, "skipped": skipped})


# Alias kept distinct so the bulk form can target it explicitly.
@app.post("/api/uploads/bulk")
def api_uploads_bulk():
    return api_uploads_manual()


# ---- API: backfill -------------------------------------------------------

def _backfill_loop():
    """Drain ready rows one at a time; respects pause/cancel."""
    print("[backfill] worker started", flush=True)
    conn = get_db()
    try:
        while True:
            with _backfill_lock:
                if _backfill_state["stop_flag"]:
                    break
                paused = _backfill_state["paused"]
            if paused:
                time.sleep(2)
                continue

            row = _ready_to_upload_rows(conn, limit=1)
            if not row:
                # Nothing more to do.
                break
            r = row[0]
            jid, did, label = r["job_id"], r["destination_id"], r["dest_label"]

            with _backfill_lock:
                _backfill_state["current"] = {"job_id": jid, "dest_label": label}

            ok, msg = _enqueue_upload(conn, job_id=jid, destination_id=did, use_ai=True)
            if not ok:
                with _backfill_lock:
                    _backfill_state["failed"] += 1
                    _backfill_state["recent"].append({
                        "ok": False, "at": utcnow_iso(),
                        "job_id": jid, "dest_label": label,
                        "url": "", "error": msg,
                    })
                continue

            # Wait for the upload_progress row to clear (terminal state).
            terminal = False
            for _ in range(60 * 60):   # max 1h per upload
                with _backfill_lock:
                    if _backfill_state["stop_flag"]:
                        terminal = True
                        break
                time.sleep(2)
                up = conn.execute(
                    "SELECT stage FROM upload_progress WHERE job_id=? AND destination_id=?",
                    (jid, did),
                ).fetchone()
                if not up or (up["stage"] in ("done", "failed", "canceled")):
                    terminal = True
                    break
            ur = conn.execute(
                "SELECT status, upload_url, error_message FROM upload_results "
                "WHERE job_id=? AND destination_id=? ORDER BY id DESC LIMIT 1",
                (jid, did),
            ).fetchone()
            success = bool(ur and ur["status"] in ("uploaded", "success"))
            with _backfill_lock:
                if success:
                    _backfill_state["done"] += 1
                else:
                    _backfill_state["failed"] += 1
                _backfill_state["recent"].append({
                    "ok": success, "at": utcnow_iso(),
                    "job_id": jid, "dest_label": label,
                    "url": (ur["upload_url"] if ur else "") or "",
                    "error": (ur["error_message"] if ur else "") or "",
                })
                _backfill_state["current"] = None
            if not terminal:
                break
    except Exception as e:                                       # noqa: BLE001
        print(f"[backfill] crashed: {type(e).__name__}: {e}", flush=True)
    finally:
        conn.close()
        with _backfill_lock:
            _backfill_state["running"] = False
            _backfill_state["current"] = None
            _backfill_state["last_finished_at"] = utcnow_iso()
            _backfill_state["stop_flag"] = False
        print("[backfill] worker stopped", flush=True)


@app.post("/api/uploads/backfill/start")
def api_uploads_backfill_start():
    with _backfill_lock:
        if _backfill_state["running"]:
            # Coming out of pause is the same call.
            _backfill_state["paused"] = False
            return jsonify({"ok": True, "message": "resumed"})
        # Reset counters for a new run.
        pending = len(_ready_to_upload_rows(g.db, limit=500))
        _backfill_state.update({
            "running": True,
            "paused": False,
            "total": pending,
            "done": 0,
            "failed": 0,
            "current": None,
            "recent": [],
            "stop_flag": False,
        })
        t = threading.Thread(
            target=_backfill_loop,
            name="backfill-worker", daemon=True,
        )
        _backfill_state["thread"] = t
        t.start()
    return jsonify({"ok": True, "message": "started", "pending": pending})


@app.post("/api/uploads/backfill/pause")
def api_uploads_backfill_pause():
    with _backfill_lock:
        if not _backfill_state["running"]:
            return _err("not running", "NOT_RUNNING", 409)
        _backfill_state["paused"] = True
    return jsonify({"ok": True, "message": "paused"})


@app.post("/api/uploads/backfill/cancel")
def api_uploads_backfill_cancel():
    with _backfill_lock:
        _backfill_state["stop_flag"] = True
        _backfill_state["paused"] = False
    return jsonify({"ok": True, "message": "cancel requested"})


@app.get("/api/uploads/backfill/status")
def api_uploads_backfill_status():
    with _backfill_lock:
        st = dict(_backfill_state)
        st.pop("thread", None)
        st["recent"] = list(st["recent"])[-20:]
    return jsonify(st)


# ===========================================================================
# HTMX partial routes — return HTML fragments for the pipelines page
# ===========================================================================

def _all_pipelines_for_view() -> list[dict]:
    rows = g.db.execute(PIPELINE_SUMMARY_SQL + " ORDER BY p.id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["active"] = bool(d["active"])
        out.append(d)
    return out


def _one_pipeline_for_view(pid: int) -> Optional[dict]:
    row = g.db.execute(PIPELINE_SUMMARY_SQL + " WHERE p.id = ?", (pid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["active"] = bool(d["active"])
    return d


def _channels_for_pipeline(pid: int) -> list[dict]:
    rows = g.db.execute(
        CHANNEL_BASE_SQL + " WHERE c.pipeline_id = ? ORDER BY c.id", (pid,)
    ).fetchall()
    return [_serialize_channel(r) for r in rows]


def _destinations_for_pipeline(pid: int) -> list[dict]:
    rows = g.db.execute(
        "SELECT d.*, c.title AS yt_channel_title, c.thumbnail_url AS yt_channel_thumb "
        "FROM destinations d "
        "LEFT JOIN youtube_channels c ON c.id = d.youtube_channel_id "
        "WHERE d.pipeline_id = ? ORDER BY d.id",
        (pid,),
    ).fetchall()
    return [_serialize_destination(r) for r in rows]


def _all_youtube_channels() -> list[dict]:
    """Return all detected YouTube channels (id, title, owner_email,
    thumbnail_url) for populating destination dropdowns."""
    try:
        rows = g.db.execute(
            "SELECT id, channel_id, title, owner_email, thumbnail_url "
            "FROM youtube_channels ORDER BY title COLLATE NOCASE"
        ).fetchall()
    except Exception:                                                # noqa: BLE001
        return []
    return [dict(r) for r in rows]


# --- queue ----------------------------------------------------------------

QUEUE_ACTIVE_STATUSES = (
    "pending", "downloading", "downloaded",
    "processing", "processed", "uploading",
)

QUEUE_ROW_SQL = """
SELECT
    j.id              AS job_id,
    j.status          AS status,
    j.updated_at      AS updated_at,
    j.created_at      AS created_at,
    v.original_title  AS video_title,
    v.youtube_video_id AS youtube_video_id,
    c.name            AS channel_name,
    p.name            AS pipeline_name,
    p.id              AS pipeline_id
FROM jobs j
JOIN videos v    ON v.id = j.video_id
JOIN channels c  ON c.id = v.channel_id
JOIN pipelines p ON p.id = j.pipeline_id
"""


def _queue_active_rows(limit: int = 50) -> tuple[list[dict], int]:
    placeholders = ",".join(["?"] * len(QUEUE_ACTIVE_STATUSES))
    sql = QUEUE_ROW_SQL + (
        f" WHERE j.status IN ({placeholders}) "
        f" ORDER BY j.updated_at DESC, j.id DESC LIMIT ?"
    )
    rows = g.db.execute(sql, (*QUEUE_ACTIVE_STATUSES, limit)).fetchall()
    total = g.db.execute(
        f"SELECT COUNT(*) AS n FROM jobs WHERE status IN ({placeholders})",
        QUEUE_ACTIVE_STATUSES,
    ).fetchone()["n"]
    return [dict(r) for r in rows], int(total)


def _queue_recent_rows(limit: int = 25) -> list[dict]:
    sql = QUEUE_ROW_SQL + (
        " WHERE j.status IN ('done','partial','failed') "
        " ORDER BY j.updated_at DESC, j.id DESC LIMIT ?"
    )
    rows = g.db.execute(sql, (limit,)).fetchall()
    return [dict(r) for r in rows]


def _queue_counts() -> dict:
    rows = g.db.execute(
        "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
    ).fetchall()
    by_status = {r["status"]: r["n"] for r in rows}
    # Split `processed` (waiting for upload) into its own bucket so the UI
    # doesn't claim 50+ jobs are "processing" when nothing is happening.
    return {
        "pending":     by_status.get("pending", 0),
        "downloading": by_status.get("downloading", 0) + by_status.get("downloaded", 0),
        "processing":  by_status.get("processing", 0),
        "ready":       by_status.get("processed", 0),
        "uploading":   by_status.get("uploading", 0),
        "done_today": g.db.execute(
            "SELECT COUNT(*) AS n FROM jobs "
            "WHERE status = 'done' "
            "  AND substr(updated_at, 1, 10) = strftime('%Y-%m-%d', 'now')"
        ).fetchone()["n"],
        "failed_today": g.db.execute(
            "SELECT COUNT(*) AS n FROM jobs "
            "WHERE status = 'failed' "
            "  AND substr(updated_at, 1, 10) = strftime('%Y-%m-%d', 'now')"
        ).fetchone()["n"],
    }


def _cron_queued_breakdown() -> dict:
    """Stats on un-promoted, cron-enqueued ledger rows.

    These are the rows the router auto-creates and that the manual rollback
    button can safely delete (no job has been started yet).
    """
    rows = g.db.execute(
        """SELECT cv.source_id            AS source_id,
                  COALESCE(s.name, '?')   AS source_name,
                  ul.destination_id       AS destination_id,
                  COALESCE(d.label, '?')  AS destination_label,
                  COUNT(*)                AS n
             FROM upload_ledger ul
             LEFT JOIN catalog_videos cv ON cv.video_id = ul.video_id
             LEFT JOIN sources       s   ON s.id = cv.source_id
             LEFT JOIN destinations  d   ON d.id = ul.destination_id
            WHERE ul.status = 'queued'
              AND ul.triggered_by = 'cron'
              AND ul.job_id IS NULL
              AND COALESCE(ul.destination_url, '') = ''
            GROUP BY cv.source_id, ul.destination_id
            ORDER BY n DESC""",
    ).fetchall()
    total = sum(r["n"] for r in rows)
    return {"total": total, "groups": [dict(r) for r in rows]}


def _do_cron_rollback(source_id: int | None, destination_id: int | None) -> int:
    """Delete un-promoted cron-queued rows. Returns rows removed.

    `source_id`/`destination_id` are optional filters. None means "all".
    """
    where = ["status = 'queued'", "triggered_by = 'cron'",
             "job_id IS NULL", "COALESCE(destination_url, '') = ''"]
    params: list = []
    if destination_id is not None:
        where.append("destination_id = ?")
        params.append(destination_id)
    if source_id is not None:
        where.append("video_id IN (SELECT video_id FROM catalog_videos "
                     "WHERE source_id = ?)")
        params.append(source_id)
    sql = f"DELETE FROM upload_ledger WHERE {' AND '.join(where)}"
    cur = g.db.execute(sql, params)
    g.db.commit()
    return int(cur.rowcount or 0)


@app.post("/api/ledger/rollback")
def api_ledger_rollback():
    """Roll back un-promoted cron-queued ledger rows.

    Optional query/form params: source_id, destination_id. Both omitted
    means "roll back ALL cron-queued rows (no started job)".
    """
    def _opt(key: str) -> int | None:
        raw = (request.values.get(key) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None
    sid = _opt("source_id")
    did = _opt("destination_id")
    deleted = _do_cron_rollback(sid, did)
    return jsonify({"deleted": deleted, "source_id": sid, "destination_id": did})


@app.get("/partials/queue/cron-rollback")
def partial_queue_cron_rollback():
    """Render just the rollback widget (used for HTMX refresh after action)."""
    return render_template(
        "partials/queue_cron_rollback.html",
        cron=_cron_queued_breakdown(),
    )


@app.post("/partials/queue/cron-rollback")
def partial_queue_cron_rollback_submit():
    def _opt(key: str) -> int | None:
        raw = (request.values.get(key) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None
    deleted = _do_cron_rollback(_opt("source_id"), _opt("destination_id"))
    # Re-render the widget with a flash banner.
    return render_template(
        "partials/queue_cron_rollback.html",
        cron=_cron_queued_breakdown(),
        flash=f"Rolled back {deleted} row(s).",
    )


def _recent_ledger_activity(limit: int = 20) -> list[dict]:
    """Most recent upload_ledger rows for the activity widget.

    Joins title from catalog_videos and label from destinations.
    """
    rows = g.db.execute(
        """SELECT ul.id            AS ledger_id,
                  ul.video_id      AS video_id,
                  ul.destination_id AS destination_id,
                  ul.status        AS status,
                  ul.triggered_by  AS triggered_by,
                  ul.created_at    AS created_at,
                  ul.updated_at    AS updated_at,
                  ul.uploaded_at   AS uploaded_at,
                  COALESCE(cv.title, '?') AS title,
                  COALESCE(d.label, '?')  AS destination_label
             FROM upload_ledger ul
             LEFT JOIN catalog_videos cv ON cv.video_id = ul.video_id
             LEFT JOIN destinations  d   ON d.id = ul.destination_id
            ORDER BY COALESCE(ul.updated_at, ul.created_at) DESC, ul.id DESC
            LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/partials/queue")
def partial_queue():
    active, active_total = _queue_active_rows()
    return render_template(
        "partials/queue_content.html",
        active=active,
        active_total=active_total,
        recent=_queue_recent_rows(),
        counts=_queue_counts(),
        cron=_cron_queued_breakdown(),
        ledger_activity=_recent_ledger_activity(),
        dlq=_download_queue_summary(),
    )


@app.get("/partials/queue/ledger-activity")
def partial_queue_ledger_activity():
    """Standalone refresh endpoint for the ledger activity widget."""
    return render_template(
        "partials/queue_ledger_activity.html",
        ledger_activity=_recent_ledger_activity(),
    )


def _download_queue_summary(recent_limit: int = 10) -> dict:
    """Counts per status + recent rows for the download_queue widget."""
    counts_rows = g.db.execute(
        "SELECT status, COUNT(*) AS n FROM download_queue GROUP BY status"
    ).fetchall()
    counts = {r["status"]: int(r["n"]) for r in counts_rows}
    total = sum(counts.values())
    recent = g.db.execute(
        """SELECT dq.id, dq.video_id, dq.status, dq.triggered_by,
                  dq.created_at, dq.updated_at, dq.error_message,
                  dq.job_id, dq.profile_id,
                  COALESCE(cv.title, '?') AS title,
                  COALESCE(s.name, '?')   AS source_label
             FROM download_queue dq
             LEFT JOIN catalog_videos cv ON cv.video_id = dq.video_id
             LEFT JOIN sources s         ON s.id        = dq.source_id
            ORDER BY COALESCE(dq.updated_at, dq.created_at) DESC, dq.id DESC
            LIMIT ?""",
        (recent_limit,),
    ).fetchall()
    return {
        "counts": counts,
        "total":  total,
        "recent": [dict(r) for r in recent],
    }


@app.get("/partials/queue/download-queue")
def partial_queue_download_queue():
    """Standalone refresh endpoint for the download-queue widget."""
    # Opportunistically reconcile complete rows whenever the widget renders.
    try:
        _dlq_sync_terminal(g.db)
    except Exception:
        pass
    return render_template(
        "partials/queue_download_queue.html",
        dlq=_download_queue_summary(),
    )


@app.get("/api/download-queue")
def api_download_queue():
    """JSON view of the download_queue (for tooling / future workers)."""
    return jsonify(_download_queue_summary(recent_limit=50))


# ---------------------------------------------------------------------------
# Slice 4b: download_queue hydrator + terminal sync
# ---------------------------------------------------------------------------
# Bridges the routing era (sources/destinations/download_queue) to the
# legacy jobs/watcher pipeline. Pure opt-in -- nothing auto-runs unless the
# user invokes the hydrate endpoint or POSTs the widget button.

class HydrateError(Exception):
    """Raised when a single download_queue row cannot be hydrated."""


def _hydrate_one_dlq_row(
    conn: sqlite3.Connection, dlq_row: sqlite3.Row
) -> int:
    """Materialize a `jobs` row from a `pending` download_queue row.

    Returns the new job_id. Raises HydrateError on any precondition failure.
    The caller commits.
    """
    if dlq_row["status"] != "pending":
        raise HydrateError(f"dlq #{dlq_row['id']} is {dlq_row['status']}, not pending")

    source_id = dlq_row["source_id"]

    # If source_id is missing, try to infer it from catalog_videos.
    if source_id is None:
        cv = conn.execute(
            "SELECT source_id FROM catalog_videos WHERE video_id = ? AND source_id IS NOT NULL LIMIT 1",
            (dlq_row["video_id"],),
        ).fetchone()
        if cv:
            source_id = cv["source_id"]
            conn.execute(
                "UPDATE download_queue SET source_id = ? WHERE id = ?",
                (source_id, dlq_row["id"]),
            )
        else:
            raise HydrateError(
                f"dlq #{dlq_row['id']} has no source_id and video_id "
                f"{dlq_row['video_id']!r} is not in catalog_videos"
            )

    src = conn.execute(
        "SELECT id, pipeline_id FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if not src:
        raise HydrateError(f"source #{source_id} not found")
    pipeline_id = src["pipeline_id"]
    if pipeline_id is None:
        raise HydrateError(
            f"source #{source_id} has no pipeline_id -- cannot create job. "
            "Attach the source to a pipeline first."
        )

    # Pick any channel under the pipeline as the FK target for videos.
    chan = conn.execute(
        "SELECT id FROM channels WHERE pipeline_id = ? LIMIT 1", (pipeline_id,)
    ).fetchone()
    if not chan:
        raise HydrateError(
            f"pipeline #{pipeline_id} has no channels -- videos.channel_id "
            "is NOT NULL, so we cannot create a job"
        )

    yt_id = dlq_row["video_id"]
    vrow = conn.execute(
        "SELECT id FROM videos WHERE youtube_video_id = ?", (yt_id,)
    ).fetchone()
    if vrow:
        video_pk = int(vrow["id"])
    else:
        # Borrow title from catalog_videos when present.
        cv = conn.execute(
            "SELECT title FROM catalog_videos WHERE video_id = ?", (yt_id,)
        ).fetchone()
        title = (cv["title"] if cv else "") or ""
        cur = conn.execute(
            """INSERT INTO videos (channel_id, youtube_video_id, original_title,
                                   source_url)
               VALUES (?, ?, ?, ?)""",
            (chan["id"], yt_id, title, f"https://www.youtube.com/watch?v={yt_id}"),
        )
        video_pk = int(cur.lastrowid)

    # Guard: if a non-failed job already exists for this video, reuse it
    # rather than creating a duplicate. This prevents the clean-and-rescan
    # + hydrator cycle from generating multiple jobs for the same video.
    active_job = conn.execute(
        "SELECT id FROM jobs WHERE video_id = ? AND status NOT IN ('failed') "
        "ORDER BY id DESC LIMIT 1",
        (video_pk,),
    ).fetchone()
    if active_job:
        job_id = int(active_job["id"])
        conn.execute(
            """UPDATE download_queue
                  SET status = 'hydrated',
                      job_id = ?,
                      error_message = '',
                      updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
                WHERE id = ?""",
            (job_id, dlq_row["id"]),
        )
        return job_id

    cur = conn.execute(
        "INSERT INTO jobs (video_id, pipeline_id, status) VALUES (?, ?, 'pending')",
        (video_pk, pipeline_id),
    )
    job_id = int(cur.lastrowid)

    conn.execute(
        """UPDATE download_queue
              SET status = 'hydrated',
                  job_id = ?,
                  error_message = '',
                  updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = ?""",
        (job_id, dlq_row["id"]),
    )
    return job_id


def hydrate_download_queue(
    conn: sqlite3.Connection, limit: int = 10
) -> dict:
    """Hydrate up to ``limit`` pending download_queue rows.

    Returns a stats dict: {hydrated, errors, error_rows: [{dlq_id, reason}]}
    Caller commits.
    """
    rows = conn.execute(
        "SELECT * FROM download_queue WHERE status='pending' "
        "ORDER BY id LIMIT ?",
        (max(1, int(limit)),),
    ).fetchall()
    hydrated = 0
    error_rows: list[dict] = []
    for r in rows:
        try:
            _hydrate_one_dlq_row(conn, r)
            hydrated += 1
        except HydrateError as e:
            conn.execute(
                """UPDATE download_queue
                      SET error_message = ?,
                          updated_at    = strftime('%Y-%m-%dT%H:%M:%S','now')
                    WHERE id = ?""",
                (str(e)[:500], r["id"]),
            )
            error_rows.append({"dlq_id": int(r["id"]), "reason": str(e)})
    return {
        "hydrated":   hydrated,
        "errors":     len(error_rows),
        "error_rows": error_rows,
        "considered": len(rows),
    }


def _dlq_sync_terminal(conn: sqlite3.Connection) -> int:
    """Mark dlq rows 'complete' / 'failed' once all their ledger rows are
    in a terminal state.

    For each dlq row in ('hydrated','downloading'):
      - If at least one ledger row for that video_id is 'uploaded' AND every
        ledger row is in ('uploaded','failed','removed'), mark 'complete'.
      - Else if every ledger row is in ('failed','removed') and there's at
        least one 'failed', mark 'failed'.
      - Otherwise, leave it alone.

    Returns number of dlq rows transitioned. Caller commits.
    """
    rows = conn.execute(
        """SELECT id, video_id FROM download_queue
            WHERE status IN ('hydrated','downloading','pending')"""
    ).fetchall()
    transitioned = 0
    for r in rows:
        ledger = conn.execute(
            "SELECT status FROM upload_ledger WHERE video_id = ?",
            (r["video_id"],),
        ).fetchall()
        if not ledger:
            continue
        statuses = {row["status"] for row in ledger}
        if statuses and statuses.issubset({"uploaded", "failed", "removed"}):
            new_status = "complete" if "uploaded" in statuses else "failed"
            err = "" if new_status == "complete" else "all ledger rows failed/removed"
            conn.execute(
                """UPDATE download_queue
                      SET status = ?,
                          error_message = ?,
                          updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
                    WHERE id = ?""",
                (new_status, err, r["id"]),
            )
            transitioned += 1
    if transitioned:
        conn.commit()
    return transitioned


@app.post("/api/download-queue/hydrate")
def api_download_queue_hydrate():
    """Hydrate up to N pending dlq rows. Body or query: limit=10."""
    try:
        limit = int(request.args.get("limit") or
                    (request.get_json(silent=True) or {}).get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    stats = hydrate_download_queue(g.db, limit=limit)
    g.db.commit()
    return jsonify(stats)


@app.post("/partials/queue/download-queue/hydrate")
def partial_queue_download_queue_hydrate():
    """HTMX endpoint: hydrate then re-render the widget."""
    try:
        limit = int(request.form.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    try:
        stats = hydrate_download_queue(g.db, limit=limit)
        g.db.commit()
    except Exception as exc:                                     # noqa: BLE001
        stats = {"hydrated": 0, "errors": 1,
                 "error_rows": [{"dlq_id": 0, "reason": str(exc)}]}
    return render_template(
        "partials/queue_download_queue.html",
        dlq=_download_queue_summary(),
        last_hydrate=stats,
    )


@app.get("/partials/queue/manual-form")
def partial_queue_manual_form():
    return render_template(
        "partials/queue_manual_form.html",
        pipelines=_all_pipelines_for_view(),
    )


@app.post("/partials/queue/manual")
def partial_queue_manual_submit():
    url = (request.form.get("url") or "").strip()
    try:
        pid = int(request.form.get("pipeline_id") or 0)
    except ValueError:
        pid = 0
    if not url or not pid:
        return ("<p class='text-sm' style='color:#f85149'>URL and pipeline are required.</p>", 400)
    if not g.db.execute("SELECT 1 FROM pipelines WHERE id = ?", (pid,)).fetchone():
        return ("<p class='text-sm' style='color:#f85149'>Pipeline not found.</p>", 404)

    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url)
    yt_id = m.group(1) if m else url[-11:]
    vrow = g.db.execute(
        "SELECT id FROM videos WHERE youtube_video_id = ?", (yt_id,)
    ).fetchone()
    if vrow:
        video_pk = vrow["id"]
        # PR6: warn (and block by default) if this video was archived after a
        # successful upload. User can override with the "force" checkbox.
        try:
            arch = g.db.execute(
                "SELECT COALESCE(archived_at, '') AS a FROM videos WHERE id = ?",
                (video_pk,),
            ).fetchone()
        except sqlite3.OperationalError:
            arch = None
        force = (request.form.get("force") or "").strip().lower() in ("1","on","true","yes")
        if arch and arch["a"] and not force:
            return (
                "<div class='text-sm' style='color:#d29922'>"
                f"⚠ This video ({yt_id}) was already uploaded and its local "
                "files were auto-deleted on " + str(arch["a"]) + " "
                "(only a DB timestamp is kept, no raw file is stored).<br>"
                "Re-queueing will re-download it. To proceed, re-submit with "
                "<code>force=1</code> or tick the “force re-download” box."
                "</div>",
                409,
            )
    else:
        chan = g.db.execute(
            "SELECT id FROM channels WHERE pipeline_id = ? LIMIT 1", (pid,)
        ).fetchone()
        if not chan:
            return ("<p class='text-sm' style='color:#f85149'>Pipeline has no channels.</p>", 400)
        cur = g.db.execute(
            "INSERT INTO videos (channel_id, youtube_video_id, source_url) VALUES (?, ?, ?)",
            (chan["id"], yt_id, url),
        )
        video_pk = cur.lastrowid

    cur = g.db.execute(
        "INSERT INTO jobs (video_id, pipeline_id, status) VALUES (?, ?, 'pending')",
        (video_pk, pid),
    )
    _sse_broadcast("job_update", {
        "job_id": cur.lastrowid, "status": "pending", "updated_at": utcnow_iso(),
    })
    return (
        f"<p class='text-sm' style='color:#3fb950'>Job #{cur.lastrowid} queued.</p>",
        201,
    )


@app.get("/partials/pipelines")
def partial_pipeline_list():
    return render_template("partials/pipeline_list.html",
                           pipelines=_all_pipelines_for_view())


@app.get("/partials/pipelines/new-form")
def partial_new_pipeline_form():
    return render_template("partials/new_pipeline_form.html")


@app.post("/partials/pipelines")
def partial_pipeline_create():
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    if not name:
        return ("<p class='text-sm' style='color:#f85149'>Name is required.</p>", 400)
    g.db.execute("INSERT INTO pipelines (name, description) VALUES (?, ?)",
                 (name, description))
    return render_template("partials/pipeline_list.html",
                           pipelines=_all_pipelines_for_view())


@app.delete("/partials/pipelines/<int:pid>")
def partial_pipeline_delete(pid: int):
    g.db.execute("DELETE FROM pipelines WHERE id = ?", (pid,))
    return render_template("partials/pipeline_list.html",
                           pipelines=_all_pipelines_for_view())


@app.post("/partials/pipelines/<int:pid>/toggle")
def partial_pipeline_toggle(pid: int):
    row = g.db.execute("SELECT active FROM pipelines WHERE id = ?", (pid,)).fetchone()
    if not row:
        return ("<li>Pipeline not found.</li>", 404)
    new_active = 0 if row["active"] else 1
    g.db.execute("UPDATE pipelines SET active = ? WHERE id = ?", (new_active, pid))
    p = _one_pipeline_for_view(pid)
    return render_template("partials/pipeline_card.html", p=p)


@app.get("/partials/pipelines/<int:pid>/panel")
def partial_pipeline_panel(pid: int):
    return render_template("partials/pipeline_panel.html", pid=pid)


@app.post("/partials/pipelines/<int:pid>/auto_delete")
def partial_pipeline_auto_delete(pid: int):
    """PR6: toggle 'auto-delete local files after a successful upload'.
    Re-renders the card. Deliberately does NOT touch already-archived rows."""
    row = g.db.execute(
        "SELECT COALESCE(auto_delete_after_upload, 0) AS cur "
        "FROM pipelines WHERE id = ?", (pid,)
    ).fetchone()
    if not row:
        return ("<li>Pipeline not found.</li>", 404)
    new_val = 0 if row["cur"] else 1
    g.db.execute(
        "UPDATE pipelines SET auto_delete_after_upload = ? WHERE id = ?",
        (new_val, pid),
    )
    p = _one_pipeline_for_view(pid)
    return render_template("partials/pipeline_card.html", p=p)


# ---------------------------------------------------------------------------
# Download profiles (CRUD + per-pipeline assignment)
# ---------------------------------------------------------------------------
_PROFILE_COLS = (
    "name", "description", "max_height", "container", "video_codec",
    "audio_codec", "audio_only", "write_subs", "write_auto_subs",
    "sub_langs", "embed_subs", "write_thumbnail", "embed_thumbnail",
    "embed_chapters", "skip_shorts", "shorts_max_seconds", "skip_live",
    "custom_format", "is_default",
)
_PROFILE_BOOL_COLS = {
    "audio_only", "write_subs", "write_auto_subs", "embed_subs",
    "write_thumbnail", "embed_thumbnail", "embed_chapters",
    "skip_shorts", "skip_live", "is_default",
}
_PROFILE_INT_COLS = {"max_height", "shorts_max_seconds"}


def _coerce_profile_value(col: str, v):
    if col in _PROFILE_BOOL_COLS:
        return 1 if (v in (1, True, "1", "true", "on", "yes")) else 0
    if col in _PROFILE_INT_COLS:
        try:
            return int(v) if v not in (None, "") else 0
        except (TypeError, ValueError):
            return 0
    return (v or "") if isinstance(v, str) else ("" if v is None else str(v))


def _serialize_profile(row) -> dict:
    d = dict(row)
    for k in _PROFILE_BOOL_COLS:
        if k in d:
            d[k] = bool(d[k])
    return d


@app.get("/api/download_profiles")
def api_profiles_list():
    rows = g.db.execute(
        "SELECT * FROM download_profiles ORDER BY is_default DESC, name"
    ).fetchall()
    return jsonify([_serialize_profile(r) for r in rows])


@app.get("/api/download_profiles/<int:pid>")
def api_profiles_get(pid: int):
    row = g.db.execute("SELECT * FROM download_profiles WHERE id = ?", (pid,)).fetchone()
    if not row:
        return _err("profile not found", "NOT_FOUND", 404)
    return jsonify(_serialize_profile(row))


@app.post("/api/download_profiles")
def api_profiles_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return _err("name is required", "MISSING_NAME", 400)
    cols, vals = ["name"], [name]
    for c in _PROFILE_COLS:
        if c == "name":
            continue
        if c in body:
            cols.append(c); vals.append(_coerce_profile_value(c, body[c]))
    placeholders = ",".join("?" * len(cols))
    cur = g.db.execute(
        f"INSERT INTO download_profiles ({','.join(cols)}) VALUES ({placeholders})",
        tuple(vals),
    )
    new_id = cur.lastrowid
    row = g.db.execute("SELECT * FROM download_profiles WHERE id = ?", (new_id,)).fetchone()
    return jsonify(_serialize_profile(row)), 201


@app.put("/api/download_profiles/<int:pid>")
def api_profiles_update(pid: int):
    body = request.get_json(silent=True) or {}
    fields, vals = [], []
    for c in _PROFILE_COLS:
        if c in body:
            fields.append(f"{c} = ?"); vals.append(_coerce_profile_value(c, body[c]))
    if not fields:
        return api_profiles_get(pid)
    fields.append("updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')")
    vals.append(pid)
    cur = g.db.execute(
        f"UPDATE download_profiles SET {', '.join(fields)} WHERE id = ?", tuple(vals)
    )
    if cur.rowcount == 0:
        return _err("profile not found", "NOT_FOUND", 404)
    return api_profiles_get(pid)


@app.delete("/api/download_profiles/<int:pid>")
def api_profiles_delete(pid: int):
    row = g.db.execute(
        "SELECT is_default FROM download_profiles WHERE id = ?", (pid,)
    ).fetchone()
    if not row:
        return _err("profile not found", "NOT_FOUND", 404)
    if row["is_default"]:
        return _err("cannot delete the default profile", "PROTECTED", 409)
    g.db.execute("DELETE FROM download_profiles WHERE id = ?", (pid,))
    return ("", 204)


# ---------------------------------------------------------------------------
# Download profiles — HTMX page + partial routes
# ---------------------------------------------------------------------------
def _profile_render_list():
    rows = g.db.execute(
        "SELECT * FROM download_profiles ORDER BY is_default DESC, name"
    ).fetchall()
    profiles = [_serialize_profile(r) for r in rows]
    return render_template("partials/profile_list.html", profiles=profiles)


@app.get("/profiles")
def page_profiles():
    return _render_or_stub("profiles.html", "Download Profiles")


@app.get("/partials/profiles/list")
def partial_profiles_list():
    return _profile_render_list()


@app.get("/partials/profiles/new")
def partial_profiles_new():
    return render_template("partials/profile_form.html", profile=None)


@app.get("/partials/profiles/<int:pid>/edit")
def partial_profiles_edit(pid: int):
    row = g.db.execute(
        "SELECT * FROM download_profiles WHERE id = ?", (pid,)
    ).fetchone()
    if not row:
        return ("profile not found", 404)
    return render_template(
        "partials/profile_form.html", profile=_serialize_profile(row)
    )


def _profile_form_payload() -> dict:
    """Translate an HTMX form submit into the column->value map used by
    the existing JSON CRUD helpers. Unchecked checkboxes are absent from
    the form, so we explicitly default every bool col to 0."""
    out: dict = {}
    form = request.form
    for c in _PROFILE_COLS:
        if c in _PROFILE_BOOL_COLS:
            out[c] = 1 if form.get(c) in ("1", "on", "true", "yes") else 0
        elif c in form:
            out[c] = _coerce_profile_value(c, form.get(c))
    return out


@app.post("/partials/profiles")
def partial_profiles_create():
    payload = _profile_form_payload()
    name = (payload.get("name") or "").strip()
    if not name:
        return ("name is required", 400)
    cols = list(payload.keys())
    placeholders = ",".join("?" * len(cols))
    g.db.execute(
        f"INSERT INTO download_profiles ({','.join(cols)}) VALUES ({placeholders})",
        tuple(payload[c] for c in cols),
    )
    return _profile_render_list()


@app.post("/partials/profiles/<int:pid>")
def partial_profiles_update(pid: int):
    row = g.db.execute(
        "SELECT id FROM download_profiles WHERE id = ?", (pid,)
    ).fetchone()
    if not row:
        return ("profile not found", 404)
    payload = _profile_form_payload()
    if not payload:
        return _profile_render_list()
    fields = [f"{c} = ?" for c in payload.keys()]
    fields.append("updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')")
    vals = list(payload.values()) + [pid]
    g.db.execute(
        f"UPDATE download_profiles SET {', '.join(fields)} WHERE id = ?",
        tuple(vals),
    )
    return _profile_render_list()


@app.delete("/partials/profiles/<int:pid>")
def partial_profiles_delete(pid: int):
    row = g.db.execute(
        "SELECT is_default FROM download_profiles WHERE id = ?", (pid,)
    ).fetchone()
    if not row:
        return ("profile not found", 404)
    if row["is_default"]:
        return ("cannot delete the default profile", 409)
    g.db.execute("DELETE FROM download_profiles WHERE id = ?", (pid,))
    return _profile_render_list()


@app.get("/partials/pipelines/<int:pid>/download_profile")
def partial_pipeline_download_profile(pid: int):
    """Render the download-profile dropdown for a pipeline."""
    pipeline = g.db.execute(
        "SELECT id, download_profile_id FROM pipelines WHERE id = ?", (pid,)
    ).fetchone()
    if not pipeline:
        return ("<p>Pipeline not found.</p>", 404)
    profiles = g.db.execute(
        "SELECT id, name, is_default FROM download_profiles ORDER BY is_default DESC, name"
    ).fetchall()
    return render_template(
        "partials/download_profile_select.html",
        pid=pid,
        current_id=pipeline["download_profile_id"],
        profiles=[dict(r) for r in profiles],
    )


@app.post("/partials/pipelines/<int:pid>/download_profile")
def partial_pipeline_download_profile_set(pid: int):
    raw = (request.form.get("download_profile_id") or "").strip()
    try:
        v = int(raw) if raw and raw != "0" else None
    except ValueError:
        v = None
    cur = g.db.execute(
        "UPDATE pipelines SET download_profile_id = ? WHERE id = ?", (v, pid)
    )
    if cur.rowcount == 0:
        return ("<p>Pipeline not found.</p>", 404)
    return partial_pipeline_download_profile(pid)


@app.get("/partials/pipelines/<int:pid>/channels")
def partial_channel_list(pid: int):
    return render_template("partials/channel_list.html",
                           pid=pid, channels=_channels_for_pipeline(pid),
                           available_sources=_available_sources_for_pipeline(pid))


def _available_sources_for_pipeline(pid: int) -> list[dict]:
    """Return all `sources` rows annotated with attachment status against
    the existing `channels` table (PR4a — channel-picker dropdown).

    Each row gets:
      - `attached_here`  : True if a channels row with this channel_id exists
                           AND is in the current pipeline
      - `attached_other` : True if attached to a *different* pipeline
      - `attached_pipeline_name` : that other pipeline's name (or empty)

    Read-only and idempotent. Sources whose `external_id` is NULL or which
    aren't channels (kind='playlist') are excluded — channels table only
    accepts UC… ids today.
    """
    try:
        rows = g.db.execute(
            "SELECT s.id, s.name, s.url, s.external_id, s.kind, "
            "       s.pipeline_id AS source_pipeline_id, "
            "       s.total_known, s.last_scanned_at, "
            "       p.name AS source_pipeline_name "
            "FROM sources s "
            "LEFT JOIN pipelines p ON p.id = s.pipeline_id "
            "WHERE s.kind = 'channel' AND s.external_id IS NOT NULL "
            "      AND s.external_id <> '' "
            "ORDER BY s.name COLLATE NOCASE"
        ).fetchall()
    except Exception:                                                # noqa: BLE001
        return []

    # Map: channel_id (UC…) -> pipeline_id of the channels-table row
    attached_map: dict[str, int] = {}
    try:
        for r in g.db.execute(
            "SELECT channel_id, pipeline_id FROM channels"
        ).fetchall():
            if r["channel_id"]:
                attached_map[r["channel_id"]] = r["pipeline_id"]
    except Exception:                                                # noqa: BLE001
        attached_map = {}

    out: list[dict] = []
    for r in rows:
        d = dict(r)
        ext = d["external_id"]
        attached_pid = attached_map.get(ext)
        d["attached_here"]  = (attached_pid == pid)
        d["attached_other"] = (attached_pid is not None and attached_pid != pid)
        out.append(d)
    return out


@app.get("/api/sources/available")
def api_sources_available():
    """JSON variant of `_available_sources_for_pipeline()` for any front-end
    that wants to render its own picker (e.g. future blueprints, scripts)."""
    pid = request.args.get("pipeline_id", type=int)
    if pid is None:
        return _err("pipeline_id required", "MISSING_PIPELINE_ID", 400)
    return jsonify(_available_sources_for_pipeline(pid))


@app.post("/partials/pipelines/<int:pid>/channels")
def partial_channel_create(pid: int):
    name = (request.form.get("name") or "").strip()
    url  = (request.form.get("url") or "").strip()
    mode = (request.form.get("mode") or "monitor").strip()
    try:
        daily_limit = int(request.form.get("daily_limit") or 10)
    except ValueError:
        daily_limit = 10

    if not name or not url:
        return ("<p class='text-sm' style='color:#f85149'>Name and URL are required.</p>", 400)
    if mode not in ("backfill", "monitor"):
        return ("<p class='text-sm' style='color:#f85149'>Invalid mode.</p>", 400)
    if not (1 <= daily_limit <= 100):
        return ("<p class='text-sm' style='color:#f85149'>daily_limit must be 1..100.</p>", 400)

    cid = _extract_channel_id(url)
    if not cid:
        return ("<p class='text-sm' style='color:#f85149'>Cannot extract channel id from URL.</p>", 400)
    if not g.db.execute("SELECT 1 FROM pipelines WHERE id = ?", (pid,)).fetchone():
        return ("<p class='text-sm' style='color:#f85149'>Pipeline not found.</p>", 404)
    if g.db.execute("SELECT 1 FROM channels WHERE channel_id = ?", (cid,)).fetchone():
        return ("<p class='text-sm' style='color:#f85149'>Channel already exists.</p>", 400)

    g.db.execute(
        """INSERT INTO channels (pipeline_id, name, channel_id, url, mode, daily_limit)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (pid, name, cid, url, mode, daily_limit),
    )
    return render_template("partials/channel_list.html",
                           pid=pid, channels=_channels_for_pipeline(pid),
                           available_sources=_available_sources_for_pipeline(pid))


@app.delete("/partials/channels/<int:cid>")
def partial_channel_delete(cid: int):
    pid = request.args.get("pipeline_id", type=int)
    if pid is None:
        row = g.db.execute("SELECT pipeline_id FROM channels WHERE id = ?", (cid,)).fetchone()
        pid = row["pipeline_id"] if row else None
    g.db.execute("DELETE FROM channels WHERE id = ?", (cid,))
    if pid is None:
        return ""
    return render_template("partials/channel_list.html",
                           pid=pid, channels=_channels_for_pipeline(pid),
                           available_sources=_available_sources_for_pipeline(pid))


@app.get("/partials/pipelines/<int:pid>/destinations")
def partial_destination_list(pid: int):
    return render_template("partials/destination_list.html",
                           pid=pid,
                           destinations=_destinations_for_pipeline(pid),
                           yt_channels=_all_youtube_channels(),
                           n8n_workflows=_list_n8n_workflows())


@app.post("/partials/pipelines/<int:pid>/destinations")
def partial_destination_create(pid: int):
    platform = (request.form.get("platform") or "").strip()
    label    = (request.form.get("label") or "").strip()
    webhook  = (request.form.get("n8n_webhook_url") or "").strip()
    privacy  = (request.form.get("default_privacy") or "unlisted").strip().lower()
    yt_chan_raw = (request.form.get("youtube_channel_id") or "").strip()
    yt_chan_id = int(yt_chan_raw) if yt_chan_raw.isdigit() else None

    if not platform or not webhook:
        return ("<p class='text-sm' style='color:#f85149'>Platform and webhook URL are required.</p>", 400)
    if platform not in ALLOWED_PLATFORMS:
        return ("<p class='text-sm' style='color:#f85149'>Invalid platform.</p>", 400)
    if privacy not in ALLOWED_PRIVACY:
        return ("<p class='text-sm' style='color:#f85149'>Invalid privacy.</p>", 400)
    if not webhook.startswith(("http://", "https://")):
        return ("<p class='text-sm' style='color:#f85149'>Webhook URL must be http(s).</p>", 400)
    if not g.db.execute("SELECT 1 FROM pipelines WHERE id = ?", (pid,)).fetchone():
        return ("<p class='text-sm' style='color:#f85149'>Pipeline not found.</p>", 404)

    g.db.execute(
        """INSERT INTO destinations (pipeline_id, platform, label, n8n_webhook_url,
                                     default_privacy, youtube_channel_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (pid, platform, label, webhook, privacy, yt_chan_id),
    )
    return render_template("partials/destination_list.html",
                           pid=pid,
                           destinations=_destinations_for_pipeline(pid),
                           yt_channels=_all_youtube_channels(),
                           n8n_workflows=_list_n8n_workflows())


@app.post("/partials/destinations/<int:did>/channel")
def partial_destination_set_channel(did: int):
    """Bind (or unbind, if value is empty) a destination to a YouTube channel."""
    raw = (request.form.get("youtube_channel_id") or "").strip()
    chan_id = int(raw) if raw.isdigit() else None
    row = g.db.execute("SELECT pipeline_id FROM destinations WHERE id = ?", (did,)).fetchone()
    if not row:
        return ("", 404)
    g.db.execute("UPDATE destinations SET youtube_channel_id = ? WHERE id = ?",
                 (chan_id, did))
    return render_template("partials/destination_list.html",
                           pid=row["pipeline_id"],
                           destinations=_destinations_for_pipeline(row["pipeline_id"]),
                           yt_channels=_all_youtube_channels(),
                           n8n_workflows=_list_n8n_workflows())


@app.post("/partials/destinations/<int:did>/privacy")
def partial_destination_set_privacy(did: int):
    privacy = (request.form.get("default_privacy") or "").strip().lower()
    if privacy not in ALLOWED_PRIVACY:
        return ("<span class='text-xs' style='color:#f85149'>bad value</span>", 400)
    row = g.db.execute("SELECT pipeline_id FROM destinations WHERE id = ?", (did,)).fetchone()
    if not row:
        return ("", 404)
    g.db.execute("UPDATE destinations SET default_privacy = ? WHERE id = ?", (privacy, did))
    return render_template("partials/destination_list.html",
                           pid=row["pipeline_id"],
                           destinations=_destinations_for_pipeline(row["pipeline_id"]),
                           yt_channels=_all_youtube_channels(),
                           n8n_workflows=_list_n8n_workflows())


# ---- PR7: per-destination upload defaults ---------------------------------

@app.get("/partials/destinations/<int:did>/options-form")
def partial_destination_options_form(did: int):
    """Render the inline editor for per-destination upload defaults."""
    row = g.db.execute(
        "SELECT id, pipeline_id, label, platform, "
        "       default_comments_enabled, default_made_for_kids, "
        "       default_tags, default_category_id, "
        "       default_embeddable, default_notify_subscribers "
        "  FROM destinations WHERE id = ?", (did,)
    ).fetchone()
    if not row:
        return ("", 404)
    return render_template("partials/destination_options_form.html",
                           d=_serialize_destination(row))


@app.post("/partials/destinations/<int:did>/options")
def partial_destination_set_options(did: int):
    """Persist the upload defaults edited by the form above. Re-renders
    the destination list so the badge on the Options button updates."""
    row = g.db.execute(
        "SELECT pipeline_id FROM destinations WHERE id = ?", (did,)
    ).fetchone()
    if not row:
        return ("", 404)

    f = request.form
    comments      = 1 if f.get("comments_enabled")   else 0
    kids          = 1 if f.get("made_for_kids")      else 0
    embeddable    = 1 if f.get("embeddable")         else 0
    notify        = 1 if f.get("notify_subscribers") else 0
    raw_tags      = (f.get("tags") or "").strip()
    # Normalize: collapse whitespace, drop empties.
    tags_clean = ",".join(
        t.strip() for t in raw_tags.split(",") if t.strip()
    )
    cat = (f.get("category_id") or "").strip()
    if cat and not cat.isdigit():
        return ("<p class='text-xs' style='color:#f85149'>"
                "category_id must be numeric (e.g. 22). Leave blank to skip."
                "</p>", 400)

    g.db.execute(
        "UPDATE destinations SET "
        "  default_comments_enabled  = ?, "
        "  default_made_for_kids     = ?, "
        "  default_tags              = ?, "
        "  default_category_id       = ?, "
        "  default_embeddable        = ?, "
        "  default_notify_subscribers= ?  "
        "WHERE id = ?",
        (comments, kids, tags_clean, cat, embeddable, notify, did),
    )
    return render_template("partials/destination_list.html",
                           pid=row["pipeline_id"],
                           destinations=_destinations_for_pipeline(row["pipeline_id"]),
                           yt_channels=_all_youtube_channels(),
                           n8n_workflows=_list_n8n_workflows())


@app.get("/partials/destinations/<int:did>/ai-form")
def partial_destination_ai_form(did: int):
    """Render the per-destination AI prompt editor inline."""
    row = g.db.execute(
        "SELECT id, pipeline_id, label, ai_enabled, ai_model, "
        "ai_system_prompt, ai_user_template "
        "FROM destinations WHERE id = ?", (did,)
    ).fetchone()
    if not row:
        return ("", 404)
    return render_template("partials/destination_ai_form.html",
                           d=dict(row))


@app.post("/partials/destinations/<int:did>/ai")
def partial_destination_set_ai(did: int):
    """Save AI prompt overrides for a destination."""
    row = g.db.execute(
        "SELECT pipeline_id FROM destinations WHERE id = ?", (did,)
    ).fetchone()
    if not row:
        return ("", 404)
    ai_enabled = 1 if request.form.get("ai_enabled") in ("1", "on", "true") else 0
    ai_model   = (request.form.get("ai_model") or "").strip()[:200]
    ai_system  = (request.form.get("ai_system_prompt") or "").strip()[:4000]
    ai_user    = (request.form.get("ai_user_template") or "").strip()[:2000]
    g.db.execute(
        """UPDATE destinations
              SET ai_enabled = ?, ai_model = ?,
                  ai_system_prompt = ?, ai_user_template = ?
            WHERE id = ?""",
        (ai_enabled, ai_model, ai_system, ai_user, did),
    )
    # Re-render the destination list so the user sees the updated state.
    return render_template("partials/destination_list.html",
                           pid=row["pipeline_id"],
                           destinations=_destinations_for_pipeline(row["pipeline_id"]),
                           yt_channels=_all_youtube_channels(),
                           n8n_workflows=_list_n8n_workflows())


@app.delete("/partials/destinations/<int:did>")
def partial_destination_delete(did: int):
    pid = request.args.get("pipeline_id", type=int)
    if pid is None:
        row = g.db.execute("SELECT pipeline_id FROM destinations WHERE id = ?", (did,)).fetchone()
        pid = row["pipeline_id"] if row else None
    g.db.execute("DELETE FROM destinations WHERE id = ?", (did,))
    if pid is None:
        return ""
    return render_template("partials/destination_list.html",
                           pid=pid, destinations=_destinations_for_pipeline(pid),
                           yt_channels=_all_youtube_channels(),
                           n8n_workflows=_list_n8n_workflows())


# --- history --------------------------------------------------------------

def _history_filter_values():
    platform = (request.args.get("platform") or "").strip()
    status = (request.args.get("status") or "").strip()
    qstr = (request.args.get("q") or "").strip()
    where, params = [], []
    if platform:
        where.append("u.platform = ?"); params.append(platform)
    if status:
        where.append("u.status = ?");   params.append(status)
    if qstr:
        where.append(
            "(v.original_title LIKE ? OR u.ai_title LIKE ? OR c.name LIKE ? "
            "OR v.youtube_video_id LIKE ?)"
        )
        like = f"%{qstr}%"
        params.extend([like, like, like, like])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    return platform, status, qstr, where_sql, params


def _history_export_rows(where_sql: str, params: list):
    return g.db.execute(
        "SELECT u.created_at, c.name AS channel_name, d.id AS destination_id, "
        "d.label AS destination_label, v.youtube_video_id, u.platform, u.status, "
        "u.upload_url, u.error_message, u.ai_used, u.ai_title, u.ai_description, "
        "u.ai_tags, v.original_title "
        "FROM upload_results u "
        "JOIN jobs j     ON j.id = u.job_id "
        "JOIN videos v   ON v.id = j.video_id "
        "JOIN channels c ON c.id = v.channel_id "
        "JOIN destinations d ON d.id = u.destination_id "
        + where_sql
        + " ORDER BY u.created_at DESC, u.id DESC",
        tuple(params),
    ).fetchall()


def _ensure_video(channel_id: int, youtube_video_id: str, original_title: str = "") -> int:
    row = g.db.execute(
        "SELECT id, original_title FROM videos WHERE youtube_video_id = ?",
        (youtube_video_id,),
    ).fetchone()
    if row:
        if not row["original_title"] and original_title:
            g.db.execute(
                "UPDATE videos SET original_title = ? WHERE id = ?",
                (original_title, row["id"]),
            )
        return row["id"]
    cur = g.db.execute(
        "INSERT INTO videos (channel_id, youtube_video_id, original_title, created_at) "
        "VALUES (?, ?, ?, ?)",
        (channel_id, youtube_video_id, original_title or "", utcnow_iso()),
    )
    return cur.lastrowid


def _ensure_job(video_pk: int, pipeline_id: int) -> int:
    row = g.db.execute(
        "SELECT id FROM jobs WHERE video_id = ? AND pipeline_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (video_pk, pipeline_id),
    ).fetchone()
    if row:
        return row["id"]
    cur = g.db.execute(
        "INSERT INTO jobs (video_id, pipeline_id, status, source_file_path, created_at, updated_at) "
        "VALUES (?, ?, 'downloaded', '', ?, ?)",
        (video_pk, pipeline_id, utcnow_iso(), utcnow_iso()),
    )
    return cur.lastrowid


def _insert_upload_result(job_id: int, destination_id: int, platform: str,
                          status: str, upload_url: str, error_message: str,
                          ai_used: int, ai_title: str, ai_description: str,
                          ai_tags: str, created_at: str) -> None:
    g.db.execute(
        "INSERT INTO upload_results (job_id, destination_id, platform, status, upload_url, "
        "error_message, ai_used, ai_title, ai_description, ai_tags, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            job_id, destination_id, platform, status, upload_url or "",
            error_message or "", ai_used, ai_title or "",
            ai_description or "", ai_tags or "[]", created_at,
        ),
    )


@app.get("/partials/history")
def partial_history():
    platform, status, qstr, where_sql, params = _history_filter_values()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        limit = 50
    offset = (page - 1) * limit

    total = g.db.execute(
        "SELECT COUNT(*) AS n "
        "FROM upload_results u "
        "JOIN jobs j     ON j.id = u.job_id "
        "JOIN videos v   ON v.id = j.video_id "
        "JOIN channels c ON c.id = v.channel_id "
        + where_sql,
        tuple(params),
    ).fetchone()["n"]

    rows = g.db.execute(
        "SELECT u.*, v.original_title, v.youtube_video_id, c.name AS channel_name "
        "FROM upload_results u "
        "JOIN jobs j     ON j.id = u.job_id "
        "JOIN videos v   ON v.id = j.video_id "
        "JOIN channels c ON c.id = v.channel_id "
        + where_sql
        + " ORDER BY u.created_at DESC, u.id DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    ).fetchall()

    pages = max(1, (total + limit - 1) // limit)
    qs_pairs = [
        ("platform", platform), ("status", status), ("q", qstr), ("limit", str(limit)),
    ]
    qs = "&".join(f"{k}={v}" for k, v in qs_pairs if v)

    return render_template(
        "partials/history_table.html",
        rows=[dict(r) for r in rows],
        total=total, page=page, pages=pages, limit=limit,
        params=qs,
    )


@app.get("/api/history/export.csv")
def api_history_export_csv():
    _, _, _, where_sql, params = _history_filter_values()
    rows = _history_export_rows(where_sql, params)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "created_at", "channel_name", "destination_id", "destination_label",
        "youtube_video_id", "platform", "status", "upload_url", "error_message",
        "ai_used", "ai_title", "ai_description", "ai_tags", "original_title",
    ])
    for row in rows:
        writer.writerow([
            row["created_at"], row["channel_name"], row["destination_id"],
            row["destination_label"], row["youtube_video_id"], row["platform"],
            row["status"], row["upload_url"], row["error_message"],
            row["ai_used"], row["ai_title"], row["ai_description"],
            row["ai_tags"], row["original_title"],
        ])

    filename = f"history_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/history/import")
def api_history_import_csv():
    file = request.files.get("csv_file")
    destination_id = request.form.get("destination_id")
    default_dest_id = None
    if destination_id:
        try:
            default_dest_id = int(destination_id)
        except ValueError:
            default_dest_id = None

    if not file or not file.filename:
        return redirect(url_for("page_history", imported=0, errors="missing_file"))

    try:
        csv_text = io.TextIOWrapper(file.stream, encoding="utf-8", errors="replace")
        reader = csv.DictReader(csv_text)
    except Exception:
        return redirect(url_for("page_history", imported=0, errors="invalid_csv"))

    imported = 0
    errors = []
    for row in reader:
        youtube_video_id = (row.get("youtube_video_id") or "").strip()
        if not youtube_video_id:
            errors.append("missing_youtube_video_id")
            continue

        channel_id = None
        if row.get("channel_id"):
            try:
                channel_id = int(row["channel_id"])
            except ValueError:
                channel_id = None
        if not channel_id and row.get("channel_name"):
            channel = g.db.execute(
                "SELECT id FROM channels WHERE name = ? LIMIT 1",
                (row["channel_name"].strip(),),
            ).fetchone()
            channel_id = channel["id"] if channel else None

        if not channel_id:
            errors.append(f"channel_missing_for_{youtube_video_id}")
            continue

        dest_id = default_dest_id
        if row.get("destination_id"):
            try:
                dest_id = int(row["destination_id"])
            except ValueError:
                dest_id = default_dest_id

        if not dest_id:
            errors.append(f"destination_missing_for_{youtube_video_id}")
            continue

        dest = g.db.execute(
            "SELECT id, platform, pipeline_id FROM destinations WHERE id = ?",
            (dest_id,),
        ).fetchone()
        if not dest:
            errors.append(f"destination_not_found_for_{youtube_video_id}")
            continue

        platform = (row.get("platform") or dest["platform"] or "").strip() or dest["platform"]
        status = (row.get("status") or "failed").strip() or "failed"
        created_at = (row.get("created_at") or "").strip() or utcnow_iso()
        try:
            created_at = datetime.fromisoformat(created_at).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            created_at = utcnow_iso()

        video_pk = _ensure_video(channel_id, youtube_video_id, row.get("original_title") or "")
        job_pk = _ensure_job(video_pk, dest["pipeline_id"])
        _insert_upload_result(
            job_pk,
            dest["id"],
            platform,
            status,
            row.get("upload_url") or "",
            row.get("error_message") or "",
            1 if str(row.get("ai_used") or "").strip().lower() in ("1", "true", "yes") else 0,
            row.get("ai_title") or "",
            row.get("ai_description") or "",
            row.get("ai_tags") or "[]",
            created_at,
        )
        imported += 1

    g.db.commit()
    return redirect(
        url_for(
            "page_history",
            imported=imported,
            errors=",".join(errors) if errors else "",
        )
    )


@app.post("/api/history/manual")
def api_history_manual_record():
    channel_id = request.form.get("channel_id")
    destination_id = request.form.get("destination_id")
    youtube_video_id = (request.form.get("youtube_video_id") or "").strip()
    if not channel_id or not destination_id or not youtube_video_id:
        return redirect(url_for("page_history", manual_added=0, errors="missing_fields"))

    try:
        channel_id = int(channel_id)
        destination_id = int(destination_id)
    except ValueError:
        return redirect(url_for("page_history", manual_added=0, errors="invalid_ids"))

    channel = g.db.execute("SELECT id FROM channels WHERE id = ?", (channel_id,)).fetchone()
    destination = g.db.execute(
        "SELECT id, platform, pipeline_id FROM destinations WHERE id = ?",
        (destination_id,),
    ).fetchone()
    if not channel or not destination:
        return redirect(url_for("page_history", manual_added=0, errors="channel_or_destination_not_found"))

    platform = (request.form.get("platform") or destination["platform"] or "").strip() or destination["platform"]
    status = (request.form.get("status") or "failed").strip() or "failed"
    created_at = (request.form.get("created_at") or "").strip() or utcnow_iso()
    try:
        created_at = datetime.fromisoformat(created_at).strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        created_at = utcnow_iso()

    video_pk = _ensure_video(channel_id, youtube_video_id, request.form.get("original_title") or "")
    job_pk = _ensure_job(video_pk, destination["pipeline_id"])
    _insert_upload_result(
        job_pk,
        destination_id,
        platform,
        status,
        request.form.get("upload_url") or "",
        request.form.get("error_message") or "",
        1 if (request.form.get("ai_used") or "") == "1" else 0,
        request.form.get("ai_title") or "",
        request.form.get("ai_description") or "",
        request.form.get("ai_tags") or "[]",
        created_at,
    )
    g.db.commit()
    return redirect(url_for("page_history", manual_added=1))


# ===========================================================================
# Sources & Catalog (FEATURE_CATALOG_AND_BACKFILL.md — P1)
# ===========================================================================

try:
    from dashboard.sources import parse_source_url, scan_source, hydrate_catalog, SourceUrlError  # noqa: E402
except ModuleNotFoundError:
    from sources import parse_source_url, scan_source, hydrate_catalog, SourceUrlError  # noqa: E402


def _serialize_source(r) -> dict:
    d = dict(r)
    return d


@app.get("/api/sources")
def api_sources_list():
    rows = g.db.execute(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM catalog_videos c
                    WHERE c.source_id = s.id AND c.unavailable_at IS NULL) AS catalog_count,
                  (SELECT COUNT(*) FROM catalog_videos c
                    JOIN upload_ledger l ON l.video_id = c.video_id
                    WHERE c.source_id = s.id AND l.status = 'uploaded') AS uploaded_count
             FROM sources s
            ORDER BY s.created_at DESC"""
    ).fetchall()
    return jsonify([_serialize_source(r) for r in rows])


@app.post("/api/sources")
def api_sources_create():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    name = (body.get("name") or "").strip()
    pipeline_id = body.get("pipeline_id")

    try:
        kind, ext_id, canonical = parse_source_url(url)
    except SourceUrlError as exc:
        return _err(str(exc), "INVALID_URL", 400)

    # Default name from URL if user didn't provide one (will be patched on first scan)
    display_name = name or canonical

    # Reject obvious dup
    if ext_id:
        dup = g.db.execute(
            "SELECT id FROM sources WHERE external_id = ?", (ext_id,)
        ).fetchone()
        if dup:
            return _err("Source already exists", "DUPLICATE", 409)
    else:
        # @handle URLs don't have an external_id yet (resolved on first scan).
        # Fall back to canonical-URL dedup so we don't insert duplicate rows.
        dup = g.db.execute(
            "SELECT id FROM sources WHERE url = ?", (canonical,)
        ).fetchone()
        if dup:
            return _err("Source already exists", "DUPLICATE", 409)

    try:
        cur = g.db.execute(
            """INSERT INTO sources (kind, url, external_id, name, pipeline_id)
               VALUES (?, ?, ?, ?, ?)""",
            (kind, canonical, ext_id, display_name, pipeline_id),
        )
    except sqlite3.IntegrityError as exc:
        # Race-safe net: partial unique index on external_id (or any other
        # constraint) raises here even when the explicit dup check missed it.
        msg = str(exc).lower()
        if "unique" in msg or "constraint" in msg:
            return _err("Source already exists", "DUPLICATE", 409)
        return _err(f"Could not create source: {exc}", "DB_ERROR", 400)
    new_id = cur.lastrowid
    row = g.db.execute("SELECT * FROM sources WHERE id = ?", (new_id,)).fetchone()
    return jsonify(_serialize_source(row)), 201


@app.delete("/api/sources/<int:sid>")
def api_sources_delete(sid: int):
    g.db.execute("DELETE FROM sources WHERE id = ?", (sid,))
    return ("", 204)


@app.post("/api/sources/<int:sid>/scan")
def api_sources_scan(sid: int):
    # Verify the source exists synchronously so callers get a clean 404.
    row = g.db.execute("SELECT id FROM sources WHERE id = ?", (sid,)).fetchone()
    if not row:
        return _err("Source not found", "NOT_FOUND", 404)
    jid, already = _enqueue_scan(sid)
    body = {
        "ok": True, "job_id": jid, "source_id": sid,
        "status": "running" if already else "pending",
        "already_running": already,
        "poll_url": f"/api/scan-jobs/{jid}",
    }
    return jsonify(body), 202


@app.post("/api/sources/<int:sid>/hydrate")
def api_sources_hydrate(sid: int):
    try:
        limit = int(request.args.get("limit", "25"))
    except ValueError:
        limit = 25
    try:
        result = hydrate_catalog(g.db, sid, limit=limit)
    except Exception as exc:                                     # noqa: BLE001
        return _err(f"Hydrate failed: {exc}", "HYDRATE_FAILED", 502)
    return jsonify(result)


@app.get("/api/sources/<int:sid>/catalog")
def api_sources_catalog(sid: int):
    try:
        page = max(int(request.args.get("page", "1")), 1)
        per_page = min(max(int(request.args.get("per_page", "50")), 1), 200)
    except ValueError:
        return _err("Invalid pagination", "BAD_REQUEST", 400)
    offset = (page - 1) * per_page

    include_ignored = request.args.get("ignored", "0") == "1"
    where = ["c.source_id = ?", "c.unavailable_at IS NULL"]
    params: list = [sid]
    if not include_ignored:
        where.append("c.ignored = 0")

    where_sql = " AND ".join(where)
    total = g.db.execute(
        f"SELECT COUNT(*) FROM catalog_videos c WHERE {where_sql}", params
    ).fetchone()[0]

    rows = g.db.execute(
        f"""SELECT c.*,
                   (SELECT l.status FROM upload_ledger l
                     WHERE l.video_id = c.video_id
                     ORDER BY l.uploaded_at DESC LIMIT 1) AS upload_status
              FROM catalog_videos c
             WHERE {where_sql}
             ORDER BY COALESCE(c.upload_date, '0000-00-00') DESC, c.id DESC
             LIMIT ? OFFSET ?""",
        (*params, per_page, offset),
    ).fetchall()

    return jsonify({
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": offset + len(rows) < total,
        "rows": [dict(r) for r in rows],
    })


# ----- HTMX partials -------------------------------------------------------

def _dlq_counts_by_source() -> dict[int, dict[str, int]]:
    """{source_id: {status: count, ...}} for non-empty sources."""
    out: dict[int, dict[str, int]] = {}
    for r in g.db.execute(
        "SELECT source_id, status, COUNT(*) AS n FROM download_queue "
        "GROUP BY source_id, status"
    ):
        out.setdefault(r["source_id"], {})[r["status"]] = r["n"]
    return out


def _all_sources_for_view() -> list[dict]:
    rows = g.db.execute(
        """SELECT s.*,
                  p.name AS pipeline_name,
                  (SELECT COUNT(*) FROM catalog_videos c
                    WHERE c.source_id = s.id AND c.unavailable_at IS NULL) AS catalog_count,
                  (SELECT COUNT(*) FROM catalog_videos c
                    JOIN upload_ledger l ON l.video_id = c.video_id
                    WHERE c.source_id = s.id AND l.status = 'uploaded') AS uploaded_count
             FROM sources s
             LEFT JOIN pipelines p ON p.id = s.pipeline_id
            ORDER BY s.created_at DESC"""
    ).fetchall()
    dlq_by_src = _dlq_counts_by_source()
    out = []
    for r in rows:
        d = _serialize_source(r)
        d["dlq_counts"] = dlq_by_src.get(r["id"], {})
        sjid = _scan_in_progress(r["id"])
        d["scan_in_progress"] = sjid is not None
        d["scan_job_id"] = sjid
        out.append(d)
    return out


@app.get("/partials/sources")
def partial_sources_list():
    return render_template(
        "partials/source_list.html",
        sources=_all_sources_for_view(),
        pipelines=_all_pipelines_for_view(),
    )


@app.post("/partials/sources")
def partial_sources_create():
    url = (request.form.get("url") or "").strip()
    name = (request.form.get("name") or "").strip()
    pipeline_raw = (request.form.get("pipeline_id") or "").strip()
    pipeline_id = None
    if pipeline_raw:
        try:
            pipeline_id = int(pipeline_raw)
        except ValueError:
            pipeline_id = None

    if pipeline_id is not None:
        has_pipeline = g.db.execute(
            "SELECT 1 FROM pipelines WHERE id = ?", (pipeline_id,)
        ).fetchone()
        if not has_pipeline:
            return render_template(
                "partials/source_list.html",
                sources=_all_sources_for_view(),
                pipelines=_all_pipelines_for_view(),
                error="Selected pipeline does not exist",
            )

    try:
        kind, ext_id, canonical = parse_source_url(url)
    except SourceUrlError as exc:
        # Render the list with an error banner
        return render_template(
            "partials/source_list.html",
            sources=_all_sources_for_view(),
            pipelines=_all_pipelines_for_view(),
            error=str(exc),
        )
    if ext_id:
        dup = g.db.execute(
            "SELECT id FROM sources WHERE external_id = ?", (ext_id,)
        ).fetchone()
        if dup:
            return render_template(
                "partials/source_list.html",
                sources=_all_sources_for_view(),
                pipelines=_all_pipelines_for_view(),
                error="Source already exists",
            )
    else:
        dup = g.db.execute(
            "SELECT id FROM sources WHERE url = ?", (canonical,)
        ).fetchone()
        if dup:
            return render_template(
                "partials/source_list.html",
                sources=_all_sources_for_view(),
                pipelines=_all_pipelines_for_view(),
                error="Source already exists",
            )
    try:
        g.db.execute(
            """INSERT INTO sources (kind, url, external_id, name, pipeline_id)
               VALUES (?, ?, ?, ?, ?)""",
            (kind, canonical, ext_id, name or canonical, pipeline_id),
        )
    except sqlite3.IntegrityError as exc:
        msg = str(exc).lower()
        err = "Source already exists" if ("unique" in msg or "constraint" in msg) else f"Could not create source: {exc}"
        return render_template(
            "partials/source_list.html",
            sources=_all_sources_for_view(),
            pipelines=_all_pipelines_for_view(),
            error=err,
        )
    return render_template(
        "partials/source_list.html",
        sources=_all_sources_for_view(),
        pipelines=_all_pipelines_for_view(),
    )


@app.delete("/partials/sources/<int:sid>")
def partial_sources_delete(sid: int):
    g.db.execute("DELETE FROM sources WHERE id = ?", (sid,))
    return render_template(
        "partials/source_list.html",
        sources=_all_sources_for_view(),
        pipelines=_all_pipelines_for_view(),
    )


@app.post("/partials/sources/<int:sid>/pipeline")
def partial_sources_set_pipeline(sid: int):
    pipeline_raw = (request.form.get("pipeline_id") or "").strip()
    pipeline_id = None
    if pipeline_raw:
        try:
            pipeline_id = int(pipeline_raw)
        except ValueError:
            return render_template(
                "partials/source_list.html",
                sources=_all_sources_for_view(),
                pipelines=_all_pipelines_for_view(),
                error="Invalid pipeline selection",
            )

    if pipeline_id is not None:
        has_pipeline = g.db.execute(
            "SELECT 1 FROM pipelines WHERE id = ?", (pipeline_id,)
        ).fetchone()
        if not has_pipeline:
            return render_template(
                "partials/source_list.html",
                sources=_all_sources_for_view(),
                pipelines=_all_pipelines_for_view(),
                error="Selected pipeline does not exist",
            )

    cur = g.db.execute(
        "UPDATE sources SET pipeline_id = ? WHERE id = ?",
        (pipeline_id, sid),
    )
    if cur.rowcount == 0:
        return render_template(
            "partials/source_list.html",
            sources=_all_sources_for_view(),
            pipelines=_all_pipelines_for_view(),
            error="Source not found",
        )

    return render_template(
        "partials/source_list.html",
        sources=_all_sources_for_view(),
        pipelines=_all_pipelines_for_view(),
    )


@app.post("/partials/sources/<int:sid>/scan")
def partial_sources_scan(sid: int):
    error = None
    row = g.db.execute("SELECT id FROM sources WHERE id = ?", (sid,)).fetchone()
    if not row:
        error = "Source not found"
    else:
        # Fire-and-forget: the source row will show a "scanning…" badge and
        # the panel auto-polls until completion.
        _enqueue_scan(sid)
    return render_template(
        "partials/source_list.html",
        sources=_all_sources_for_view(),
        pipelines=_all_pipelines_for_view(),
        error=error,
    )


@app.post("/partials/sources/<int:sid>/hydrate")
def partial_sources_hydrate(sid: int):
    """Hydrate up to N rows then re-render the catalog table."""
    try:
        limit = int(request.args.get("limit", "25"))
    except ValueError:
        limit = 25
    try:
        hydrate_catalog(g.db, sid, limit=limit)
    except Exception:                                            # noqa: BLE001
        pass  # surface via re-rendered table; counts will tell the story
    # delegate to the catalog partial to refresh
    return partial_source_catalog(sid)


# ===========================================================================
# P6 — Background hydrate worker
# ===========================================================================

_HYDRATE_BATCH       = int(os.environ.get("HYDRATE_BATCH", "10"))
_HYDRATE_INTERVAL    = int(os.environ.get("HYDRATE_INTERVAL_SEC", "60"))
_HYDRATE_IDLE_SLEEP  = int(os.environ.get("HYDRATE_IDLE_SLEEP_SEC", "300"))
_HYDRATE_ENABLED     = os.environ.get("HYDRATE_WORKER_ENABLED", "1") == "1"

_hydrate_state = {
    "running": False,
    "last_run_at": None,
    "last_source_id": None,
    "last_hydrated": 0,
    "last_failed": 0,
    "last_error": None,
    "total_hydrated": 0,
}
_hydrate_state_lock = threading.Lock()


def _hydrate_worker_loop():
    """Daemon loop. Picks the source with the most un-hydrated rows and
    hydrates a small batch, then sleeps. Sleeps longer when idle.
    """
    try:
        from dashboard.models import get_db as _get_db
        from dashboard.sources import hydrate_catalog as _hydrate
    except ModuleNotFoundError:
        from models import get_db as _get_db
        from sources import hydrate_catalog as _hydrate

    print(f"[hydrate-worker] starting (batch={_HYDRATE_BATCH}, "
          f"interval={_HYDRATE_INTERVAL}s, idle={_HYDRATE_IDLE_SLEEP}s)", flush=True)

    while True:
        sleep_for = _HYDRATE_INTERVAL
        try:
            conn = _get_db()
            try:
                row = conn.execute(
                    """SELECT source_id, COUNT(*) AS n
                         FROM catalog_videos
                        WHERE (hydrated_at IS NULL OR (view_count IS NULL AND upload_date IS NULL))
                          AND unavailable_at IS NULL
                     GROUP BY source_id
                     ORDER BY n DESC
                        LIMIT 1"""
                ).fetchone()
                if not row:
                    sleep_for = _HYDRATE_IDLE_SLEEP
                else:
                    sid = int(row["source_id"])
                    with _hydrate_state_lock:
                        _hydrate_state["running"] = True
                        _hydrate_state["last_source_id"] = sid
                    res = _hydrate(conn, sid, limit=_HYDRATE_BATCH)
                    with _hydrate_state_lock:
                        _hydrate_state["last_run_at"] = utcnow_iso()
                        _hydrate_state["last_hydrated"] = int(res.get("hydrated", 0))
                        _hydrate_state["last_failed"] = int(res.get("failed", 0))
                        _hydrate_state["total_hydrated"] += int(res.get("hydrated", 0))
                        _hydrate_state["last_error"] = None
                        _hydrate_state["running"] = False
            finally:
                conn.close()
        except Exception as e:                                   # noqa: BLE001
            with _hydrate_state_lock:
                _hydrate_state["running"] = False
                _hydrate_state["last_error"] = f"{type(e).__name__}: {e}"
            print(f"[hydrate-worker] error: {type(e).__name__}: {e}", flush=True)
            sleep_for = _HYDRATE_INTERVAL
        time.sleep(sleep_for)


def _start_hydrate_worker_once():
    if not _HYDRATE_ENABLED:
        print("[hydrate-worker] disabled (HYDRATE_WORKER_ENABLED=0)", flush=True)
        return
    if getattr(_start_hydrate_worker_once, "_started", False):
        return
    _start_hydrate_worker_once._started = True  # type: ignore[attr-defined]
    t = threading.Thread(target=_hydrate_worker_loop, name="hydrate-worker", daemon=True)
    t.start()


# ===========================================================================
# Async source-scan jobs — non-blocking POST /…/scan
# ===========================================================================
# scan_source() can take 15-60s on yt-dlp. Running it in the request thread
# blocks the worker and the user's browser. We enqueue it onto a small
# ThreadPoolExecutor and return the source list immediately; the source row
# shows a "scanning…" badge that polls the status endpoint until done.
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor

_scan_jobs: dict[int, dict] = {}                  # job_id -> job record
_scan_jobs_by_source: dict[int, int] = {}         # sid    -> in-flight job_id
_scan_jobs_lock = threading.Lock()
_scan_jobs_seq = 0
_SCAN_EXECUTOR_SIZE = int(os.environ.get("SCAN_WORKERS", "2"))
_scan_executor = _ThreadPoolExecutor(
    max_workers=_SCAN_EXECUTOR_SIZE, thread_name_prefix="scan"
)


def _run_scan_job(jid: int, sid: int) -> None:
    """Worker body. Opens its own DB connection (g.db is request-scoped)."""
    try:
        from dashboard.models import get_db as _get_db
        from dashboard.sources import scan_source as _scan
        from dashboard import router as _routing
    except ModuleNotFoundError:
        from models import get_db as _get_db                       # type: ignore
        from sources import scan_source as _scan                   # type: ignore
        import router as _routing                                  # type: ignore

    with _scan_jobs_lock:
        j = _scan_jobs.get(jid)
        if j:
            j["status"] = "running"

    conn = None
    try:
        conn = _get_db()
        result = _scan(conn, sid)
        new_ids = result.get("new_video_ids") or []
        routed = {"matched": 0, "enqueued": 0, "skipped": 0, "no_match": 0}
        if new_ids:
            try:
                stats = _routing.route_and_enqueue(
                    conn, sid, video_ids=new_ids, triggered_by="cron"
                )
                conn.commit()
                routed = {
                    "matched":         stats.matched,
                    "enqueued":        stats.enqueued,
                    "skipped":         stats.skipped,
                    "no_match":        stats.no_match,
                    "download_queued": getattr(stats, "download_queued", 0),
                }
            except Exception as exc:                               # noqa: BLE001
                print(f"[scan->route] error for source {sid}: {exc}", flush=True)
        with _scan_jobs_lock:
            j = _scan_jobs.get(jid)
            if j:
                j["status"] = "done"
                j["result"] = result
                j["routed"] = routed
                j["finished_at"] = utcnow_iso()
    except LookupError:
        with _scan_jobs_lock:
            j = _scan_jobs.get(jid)
            if j:
                j["status"] = "error"
                j["error"] = "Source not found"
                j["finished_at"] = utcnow_iso()
    except Exception as exc:                                       # noqa: BLE001
        with _scan_jobs_lock:
            j = _scan_jobs.get(jid)
            if j:
                j["status"] = "error"
                j["error"] = f"{type(exc).__name__}: {exc}"
                j["finished_at"] = utcnow_iso()
        print(f"[scan-job {jid}] error for source {sid}: {exc}", flush=True)
    finally:
        with _scan_jobs_lock:
            # Clear in-flight marker so the next click can enqueue again.
            if _scan_jobs_by_source.get(sid) == jid:
                _scan_jobs_by_source.pop(sid, None)
            # Bound the registry. The status endpoint may still query this
            # job_id for a few seconds after completion, so keep a buffer
            # of recent jobs but prune anything older once we exceed cap.
            if len(_scan_jobs) > 200:
                keep = sorted(_scan_jobs.keys())[-100:]
                for old in list(_scan_jobs.keys()):
                    if old not in keep:
                        _scan_jobs.pop(old, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:                                      # noqa: BLE001
                pass


def _enqueue_scan(sid: int) -> tuple[int, bool]:
    """Enqueue a scan job for `sid`. Returns (job_id, was_already_running)."""
    global _scan_jobs_seq
    with _scan_jobs_lock:
        existing = _scan_jobs_by_source.get(sid)
        if existing is not None:
            j = _scan_jobs.get(existing)
            if j and j["status"] in ("pending", "running"):
                return existing, True
        _scan_jobs_seq += 1
        jid = _scan_jobs_seq
        _scan_jobs[jid] = {
            "id": jid, "sid": sid, "status": "pending",
            "started_at": utcnow_iso(), "finished_at": None,
            "result": None, "routed": None, "error": None,
        }
        _scan_jobs_by_source[sid] = jid
    _scan_executor.submit(_run_scan_job, jid, sid)
    return jid, False


def _scan_in_progress(sid: int) -> Optional[int]:
    """Return job_id if a scan is pending/running for `sid`, else None."""
    with _scan_jobs_lock:
        jid = _scan_jobs_by_source.get(sid)
        if jid is None:
            return None
        j = _scan_jobs.get(jid)
        if j and j["status"] in ("pending", "running"):
            return jid
        return None


def _any_scan_in_progress() -> bool:
    with _scan_jobs_lock:
        return any(
            (_scan_jobs.get(jid) or {}).get("status") in ("pending", "running")
            for jid in _scan_jobs_by_source.values()
        )


def _scan_job_snapshot(jid: int) -> Optional[dict]:
    with _scan_jobs_lock:
        j = _scan_jobs.get(jid)
        return dict(j) if j else None


@app.get("/api/scan-jobs/<int:jid>")
def api_scan_job_status(jid: int):
    snap = _scan_job_snapshot(jid)
    if snap is None:
        return _err("scan job not found", "NOT_FOUND", 404)
    return jsonify(snap)


@app.get("/api/hydrate/status")
def api_hydrate_status():
    """Return the current background-hydrate worker status as JSON."""
    with _hydrate_state_lock:
        snap = dict(_hydrate_state)
    snap["enabled"] = _HYDRATE_ENABLED
    snap["batch"] = _HYDRATE_BATCH
    snap["interval_sec"] = _HYDRATE_INTERVAL
    # Total un-hydrated across all sources
    row = g.db.execute(
        "SELECT COUNT(*) FROM catalog_videos "
        "WHERE (hydrated_at IS NULL OR (view_count IS NULL AND upload_date IS NULL)) AND unavailable_at IS NULL"
    ).fetchone()
    snap["unhydrated_total"] = int(row[0]) if row else 0
    return jsonify(snap)


@app.post("/api/quota/retry")
def api_quota_retry_now():
    """Manually trigger the deferred-upload retry sweep.

    Useful when the user knows the quota has reset and doesn't want to wait
    for the next periodic sweep (every QUOTA_RETRY_INTERVAL_SEC seconds).
    Returns the number of uploads that were re-queued.
    """
    try:
        n = _uploader.sweep_deferred_uploads(broadcast=_sse_broadcast)
        return jsonify({"ok": True, "requeued": n})
    except Exception as e:                                          # noqa: BLE001
        return _err(f"sweep failed: {type(e).__name__}: {e}",
                    "SWEEP_FAILED", 500)


@app.get("/api/quota/status")
def api_quota_status():
    """Return current quota markers (one row per destination with an active
    or recent quota-exceeded marker) and a count of pending deferred uploads.
    """
    rows = g.db.execute(
        """SELECT dq.destination_id,
                  d.label AS destination_name,
                  d.platform,
                  dq.quota_exceeded_at,
                  dq.quota_resets_at,
                  dq.updated_at
             FROM destination_quota dq
             JOIN destinations d ON d.id = dq.destination_id
            WHERE dq.quota_exceeded_at IS NOT NULL
               OR dq.quota_resets_at IS NOT NULL
            ORDER BY dq.updated_at DESC"""
    ).fetchall()
    deferred_total = g.db.execute(
        "SELECT COUNT(*) FROM upload_results WHERE status='deferred'"
    ).fetchone()[0]
    return jsonify({
        "deferred_total": int(deferred_total or 0),
        "destinations": [dict(r) for r in rows],
        "retry_enabled": _QUOTA_RETRY_ENABLED,
        "retry_interval_sec": _QUOTA_RETRY_INTERVAL,
    })


@app.get("/partials/quota/banner")
def partial_quota_banner():
    """Inline banner shown on the Queue page when a destination has hit
    YouTube's daily upload quota. Renders empty markup when nothing is
    deferred and no active quota markers exist (so the page stays clean).
    """
    rows = g.db.execute(
        """SELECT dq.destination_id,
                  d.label AS destination_name,
                  d.platform,
                  dq.quota_exceeded_at,
                  dq.quota_resets_at
             FROM destination_quota dq
             JOIN destinations d ON d.id = dq.destination_id
            WHERE dq.quota_exceeded_at IS NOT NULL
               OR dq.quota_resets_at IS NOT NULL
            ORDER BY dq.updated_at DESC"""
    ).fetchall()
    deferred_total = g.db.execute(
        "SELECT COUNT(*) FROM upload_results WHERE status='deferred'"
    ).fetchone()[0]
    # Also count recent uploadLimitExceeded ledger errors in the last hour as a
    # fallback signal — destination_quota markers may not always be set.
    recent_quota_failures = g.db.execute(
        """SELECT COUNT(*) FROM upload_ledger
            WHERE status='failed'
              AND error_message LIKE '%uploadLimitExceeded%'
              AND updated_at >= datetime('now', '-1 hour')"""
    ).fetchone()[0]
    if not rows and not deferred_total and not recent_quota_failures:
        return ""  # nothing to show
    return render_template(
        "partials/quota_banner.html",
        rows=[dict(r) for r in rows],
        deferred_total=int(deferred_total or 0),
        recent_quota_failures=int(recent_quota_failures or 0),
    )


@app.get("/partials/hydrate/badge")
def partial_hydrate_badge():
    """Small auto-refreshing badge for the catalog header."""
    with _hydrate_state_lock:
        snap = dict(_hydrate_state)
    return render_template(
        "partials/hydrate_badge.html",
        state=snap,
        enabled=_HYDRATE_ENABLED,
        batch=_HYDRATE_BATCH,
        interval=_HYDRATE_INTERVAL,
    )


def _format_duration(sec) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _format_views(n) -> str:
    if n is None or n == "":
        return ""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n/1000:.1f}K".replace(".0K", "K")
    if n < 1_000_000_000:
        return f"{n/1_000_000:.1f}M".replace(".0M", "M")
    return f"{n/1_000_000_000:.1f}B".replace(".0B", "B")


def _parse_catalog_filters(args, sid: int) -> tuple[str, list, dict]:
    """Parse catalog filter query params into (where_sql, params, filters_dict).

    Used by both the HTML catalog endpoint and the CSV export so they stay in sync.
    """
    q          = (args.get("q") or "").strip()
    status     = (args.get("status") or "").strip().lower()
    dl_state   = (args.get("dl_state") or "").strip().lower()
    starred    = args.get("starred") == "1"
    hide_shorts = args.get("hide_shorts") == "1"
    try:
        min_dur = int(args.get("min_duration") or 0)
    except ValueError:
        min_dur = 0
    try:
        max_dur = int(args.get("max_duration") or 0)
    except ValueError:
        max_dur = 0
    sort  = (args.get("sort") or "upload_date").lower()
    order = "ASC" if (args.get("order") or "desc").lower() == "asc" else "DESC"

    where = ["c.source_id = ?", "c.unavailable_at IS NULL", "c.ignored = 0"]
    params: list = [sid]
    if q:
        where.append("LOWER(c.title) LIKE ?")
        params.append(f"%{q.lower()}%")
    if starred:
        where.append("c.starred = 1")
    if hide_shorts:
        where.append("(c.duration_sec IS NULL OR c.duration_sec >= 65)")
    if min_dur > 0:
        where.append("c.duration_sec >= ?")
        params.append(min_dur)
    if max_dur > 0:
        where.append("c.duration_sec <= ?")
        params.append(max_dur)
    if status == "never":
        where.append(
            "NOT EXISTS (SELECT 1 FROM upload_ledger l WHERE l.video_id = c.video_id)"
        )
    elif status in ("queued", "uploading", "uploaded", "failed"):
        where.append(
            "EXISTS (SELECT 1 FROM upload_ledger l "
            "WHERE l.video_id = c.video_id AND l.status = ?)"
        )
        params.append(status)

    # Download-state filter (matches the unified download_state pills shown
    # on each row). Mirrors the precedence in _compute_download_state.
    if dl_state == "downloaded":
        where.append(
            "EXISTS (SELECT 1 FROM download_queue dq "
            "LEFT JOIN jobs j ON j.id = dq.job_id "
            "WHERE dq.video_id = c.video_id "
            "AND (dq.status = 'complete' "
            "OR j.status IN ('done','downloaded','processed','processing')))"
        )
    elif dl_state == "downloading":
        where.append(
            "EXISTS (SELECT 1 FROM download_queue dq "
            "LEFT JOIN jobs j ON j.id = dq.job_id "
            "WHERE dq.video_id = c.video_id "
            "AND j.status = 'downloading')"
        )
    elif dl_state == "queued":
        where.append(
            "EXISTS (SELECT 1 FROM download_queue dq "
            "LEFT JOIN jobs j ON j.id = dq.job_id "
            "WHERE dq.video_id = c.video_id "
            "AND (dq.status IN ('pending','hydrated') OR j.status = 'pending'))"
        )
    elif dl_state == "failed":
        where.append(
            "EXISTS (SELECT 1 FROM download_queue dq "
            "LEFT JOIN jobs j ON j.id = dq.job_id "
            "WHERE dq.video_id = c.video_id "
            "AND (dq.status = 'failed' OR j.status = 'failed'))"
        )
    elif dl_state == "not_started":
        where.append(
            "NOT EXISTS (SELECT 1 FROM download_queue dq "
            "WHERE dq.video_id = c.video_id)"
        )

    sort_col = {
        "upload_date": "COALESCE(c.upload_date, '0000-00-00')",
        "duration":    "COALESCE(c.duration_sec, 0)",
        "title":       "LOWER(c.title)",
        "views":       "COALESCE(c.view_count, 0)",
    }.get(sort, "COALESCE(c.upload_date, '0000-00-00')")

    filters = {
        "q": q, "status": status, "dl_state": dl_state,
        "starred": starred, "hide_shorts": hide_shorts,
        "min_duration": min_dur, "max_duration": max_dur,
        "sort": sort, "order": order.lower(),
        "_sort_col": sort_col, "_order": order,
    }
    return " AND ".join(where), params, filters


@app.get("/partials/sources/<int:sid>/catalog")
def partial_source_catalog(sid: int):
    try:
        page = max(int(request.args.get("page", "1")), 1)
        per_page = min(max(int(request.args.get("per_page", "50")), 1), 200)
    except ValueError:
        page, per_page = 1, 50
    offset = (page - 1) * per_page

    src = g.db.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()
    if not src:
        return ("Source not found", 404)

    where_sql, params, filters = _parse_catalog_filters(request.args, sid)
    sort_col = filters["_sort_col"]
    order = filters["_order"]

    total = g.db.execute(
        f"SELECT COUNT(*) FROM catalog_videos c WHERE {where_sql}",
        tuple(params),
    ).fetchone()[0]

    rows = g.db.execute(
        f"""SELECT c.*,
                  (SELECT l.status FROM upload_ledger l
                    WHERE l.video_id = c.video_id
                    ORDER BY l.uploaded_at DESC LIMIT 1) AS upload_status,
                  (SELECT l.id FROM upload_ledger l
                    WHERE l.video_id = c.video_id
                      AND l.triggered_by = 'manual'
                      AND l.status = 'queued'
                      AND l.job_id IS NULL
                    ORDER BY l.id DESC LIMIT 1) AS pending_ledger_id,
                  (SELECT l.created_at FROM upload_ledger l
                    WHERE l.video_id = c.video_id
                      AND l.triggered_by = 'manual'
                      AND l.status = 'queued'
                      AND l.job_id IS NULL
                    ORDER BY l.id DESC LIMIT 1) AS pending_created_at,
                  (SELECT 1 FROM download_queue dq
                    LEFT JOIN jobs j ON j.id = dq.job_id
                    WHERE dq.video_id = c.video_id
                      AND (dq.status = 'complete' OR j.status IN ('done','downloaded','processed','processing'))
                    LIMIT 1) AS is_downloaded,
                  (SELECT dq.status FROM download_queue dq
                    WHERE dq.video_id = c.video_id
                    ORDER BY dq.id DESC LIMIT 1) AS dlq_status,
                  (SELECT j.status FROM download_queue dq
                    LEFT JOIN jobs j ON j.id = dq.job_id
                    WHERE dq.video_id = c.video_id
                    ORDER BY dq.id DESC LIMIT 1) AS job_status,
                  (SELECT dq.id FROM download_queue dq
                    LEFT JOIN jobs j ON j.id = dq.job_id
                    WHERE dq.video_id = c.video_id
                      AND (dq.status = 'failed' OR j.status = 'failed')
                    ORDER BY dq.id DESC LIMIT 1) AS failed_dlq_id
             FROM catalog_videos c
            WHERE {where_sql}
            ORDER BY {sort_col} {order}, c.id DESC
            LIMIT ? OFFSET ?""",
        tuple(params) + (per_page, offset),
    ).fetchall()

    unhydrated = g.db.execute(
        "SELECT COUNT(*) FROM catalog_videos WHERE source_id = ? "
        "AND (hydrated_at IS NULL OR (view_count IS NULL AND upload_date IS NULL)) AND unavailable_at IS NULL",
        (sid,),
    ).fetchone()[0]

    # Destinations available for this source's pipeline (for the per-row dropdown)
    destinations: list[dict] = []
    if src["pipeline_id"]:
        dest_rows = g.db.execute(
            "SELECT id, platform, label, color_tag FROM destinations "
            "WHERE pipeline_id = ? AND enabled = 1 ORDER BY platform, label, id",
            (src["pipeline_id"],),
        ).fetchall()
        destinations = [dict(d) for d in dest_rows]

    return render_template(
        "partials/catalog_table.html",
        source=dict(src),
        rows=[dict(r) for r in rows],
        destinations=destinations,
        filters=filters,
        page=page,
        per_page=per_page,
        total=total,
        has_more=offset + len(rows) < total,
        unhydrated=unhydrated,
        format_duration=_format_duration,
        format_views=_format_views,
    )


# ===========================================================================
# P5 — Catalog polish: star/ignore toggles + CSV export
# ===========================================================================

# ---- Disk-usage helpers ---------------------------------------------------
_DISK_USAGE_CACHE: dict[int, tuple[float, int, int]] = {}   # sid -> (expires_at, bytes, files)
_DISK_USAGE_TTL_S = 300

_FORBIDDEN_FS_CHARS = '<>:"/\\|?*'

def _sanitize_folder_name(name: str) -> str:
    """Mirror of headless_watcher._sanitize_folder so the dashboard can
    locate the same folder paths the watcher creates."""
    if not name:
        return "_unknown"
    cleaned = "".join(c for c in str(name)
                      if c not in _FORBIDDEN_FS_CHARS and ord(c) >= 32)
    cleaned = " ".join(cleaned.split()).strip(" .")
    if len(cleaned) > 100:
        cleaned = cleaned[:100].rstrip(" .")
    return cleaned or "_unknown"


def _human_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024
    return f"{f:.1f} PB"


def _find_video_on_disk(source_row: dict, video_id: str) -> Optional[str]:
    """Mirror of headless_watcher._find_existing_download. Returns the path
    to a previously-downloaded merged file for this video under this
    source's folder, or None. Used to short-circuit at queue-time so the
    UI doesn't flicker through 'queued' → 'downloaded' for files that are
    already present.
    """
    if not video_id:
        return None
    import re as _re
    fmt_intermediate = _re.compile(r"\.f\d+$")
    merged_exts = {".mp4", ".mkv", ".webm", ".m4a"}
    root = os.getenv("DOWNLOADS_DIR", "/shared/downloads")
    candidates = []
    name = source_row.get("name") or ""
    ext_id = source_row.get("external_id") or ""
    if name:
        candidates.append(os.path.join(root, _sanitize_folder_name(name), video_id))
    if ext_id:
        candidates.append(os.path.join(root, _sanitize_folder_name(ext_id), video_id))
    candidates.append(os.path.join(root, video_id))
    for d in candidates:
        try:
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                fpath = os.path.join(d, fname)
                if not os.path.isfile(fpath):
                    continue
                stem, ext = os.path.splitext(fname)
                if (ext.lower() in merged_exts
                        and not fmt_intermediate.search(stem)
                        and os.path.getsize(fpath) > 0):
                    return fpath
        except OSError:
            continue
    return None


def _source_disk_usage(source_row: dict) -> tuple[int, int]:
    """Return (total_bytes, file_count) for the on-disk download folder of
    this source. Walks <DOWNLOADS_DIR>/<sanitized name>/ and falls back to
    <DOWNLOADS_DIR>/<external_id>/ if the name folder doesn't exist.
    Cached per source for ``_DISK_USAGE_TTL_S`` seconds.
    """
    import time as _time
    sid = int(source_row["id"])
    now = _time.time()
    cached = _DISK_USAGE_CACHE.get(sid)
    if cached and cached[0] > now:
        return cached[1], cached[2]

    root = os.getenv("DOWNLOADS_DIR", "/shared/downloads")
    candidates = []
    name = source_row.get("name") or ""
    ext_id = source_row.get("external_id") or ""
    if name:
        candidates.append(os.path.join(root, _sanitize_folder_name(name)))
    if ext_id:
        candidates.append(os.path.join(root, _sanitize_folder_name(ext_id)))

    total_bytes = 0
    file_count = 0
    for d in candidates:
        if not os.path.isdir(d):
            continue
        try:
            for dirpath, _dirs, files in os.walk(d):
                for f in files:
                    try:
                        st = os.stat(os.path.join(dirpath, f))
                        total_bytes += st.st_size
                        file_count += 1
                    except OSError:
                        continue
        except OSError:
            continue
        break  # first existing candidate wins

    _DISK_USAGE_CACHE[sid] = (now + _DISK_USAGE_TTL_S, total_bytes, file_count)
    return total_bytes, file_count


@app.get("/partials/sources/<int:sid>/disk-usage")
def partial_source_disk_usage(sid: int):
    """Tiny HTMX-loaded badge: 'X.Y GB · N files' for this source's folder."""
    src = g.db.execute(
        "SELECT id, name, external_id FROM sources WHERE id = ?", (sid,)
    ).fetchone()
    if not src:
        return ("", 404)
    nocache = request.args.get("refresh") == "1"
    if nocache:
        _DISK_USAGE_CACHE.pop(sid, None)
    total_bytes, file_count = _source_disk_usage(dict(src))
    if file_count == 0:
        return (
            "<span class='text-xs' style='color: var(--text-muted);' "
            "title='No downloads on disk yet'>0 B</span>",
            200,
        )
    return (
        f"<span class='text-xs' style='color: var(--text-muted);' "
        f"title='Total size of {file_count} file(s) under this source\\'s download folder. "
        f"Cached for {_DISK_USAGE_TTL_S//60}m — append ?refresh=1 to force.'>"
        f"💾 {_human_bytes(total_bytes)} · {file_count} file{'' if file_count == 1 else 's'}</span>",
        200,
    )


@app.post("/api/catalog/<int:cid>/toggle_star")
def api_catalog_toggle_star(cid: int):
    """Flip the starred flag and return the updated star cell HTML."""
    row = g.db.execute(
        "SELECT id, starred FROM catalog_videos WHERE id = ?", (cid,)
    ).fetchone()
    if not row:
        return ("Not found", 404)
    new_val = 0 if row["starred"] else 1
    g.db.execute("UPDATE catalog_videos SET starred = ? WHERE id = ?", (new_val, cid))
    g.db.commit()
    return render_template(
        "partials/catalog_star_cell.html", catalog_id=cid, starred=new_val
    )


@app.post("/api/catalog/<int:cid>/toggle_ignore")
def api_catalog_toggle_ignore(cid: int):
    """Mark a row ignored. Returns empty body — caller swaps the row out via HTMX."""
    row = g.db.execute(
        "SELECT id FROM catalog_videos WHERE id = ?", (cid,)
    ).fetchone()
    if not row:
        return ("Not found", 404)
    g.db.execute("UPDATE catalog_videos SET ignored = 1 WHERE id = ?", (cid,))
    g.db.commit()
    return ("", 200)


@app.get("/api/sources/<int:sid>/catalog/export.csv")
def api_catalog_export_csv(sid: int):
    """CSV export honoring the same filter params as the HTML catalog view."""
    src = g.db.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()
    if not src:
        return ("Source not found", 404)

    where_sql, params, filters = _parse_catalog_filters(request.args, sid)
    sort_col = filters["_sort_col"]
    order = filters["_order"]

    rows = g.db.execute(
        f"""SELECT c.video_id, c.title, c.duration_sec, c.upload_date, c.view_count,
                   c.like_count, c.live_status, c.starred,
                   (SELECT l.status FROM upload_ledger l
                     WHERE l.video_id = c.video_id
                     ORDER BY l.uploaded_at DESC LIMIT 1) AS upload_status,
                   c.first_seen_at, c.last_seen_at
              FROM catalog_videos c
             WHERE {where_sql}
             ORDER BY {sort_col} {order}, c.id DESC""",
        tuple(params),
    ).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "video_id", "url", "title", "duration_sec", "upload_date", "view_count",
        "like_count", "live_status", "starred", "upload_status",
        "first_seen_at", "last_seen_at",
    ])
    for r in rows:
        w.writerow([
            r["video_id"],
            f"https://www.youtube.com/watch?v={r['video_id']}",
            r["title"] or "",
            r["duration_sec"] if r["duration_sec"] is not None else "",
            r["upload_date"] or "",
            r["view_count"] if r["view_count"] is not None else "",
            r["like_count"] if r["like_count"] is not None else "",
            r["live_status"] or "",
            int(r["starred"] or 0),
            r["upload_status"] or "",
            r["first_seen_at"] or "",
            r["last_seen_at"] or "",
        ])
    fname = f"catalog_source{sid}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ===========================================================================
# P5 — Routing rules: matrix of (source, conditions) -> destination/profile
# ===========================================================================

@app.get("/api/routing/rules")
def api_routing_rules_list():
    """List all routing rules. Optional filter: ?source_id=N or ?destination_id=N."""
    where = ["1=1"]
    params: list = []
    sid = request.args.get("source_id")
    if sid and sid.isdigit():
        where.append("(source_id = ? OR source_id IS NULL)")
        params.append(int(sid))
    did = request.args.get("destination_id")
    if did and did.isdigit():
        where.append("destination_id = ?")
        params.append(int(did))
    rows = g.db.execute(
        "SELECT * FROM routing_rules WHERE " + " AND ".join(where)
        + " ORDER BY priority ASC, id ASC",
        params,
    ).fetchall()
    return jsonify({"rules": [dict(r) for r in rows]})


def _rule_form_payload() -> dict:
    """Translate an HTMX form submit into a clean dict for INSERT/UPDATE.

    Unchecked checkboxes are absent from the form body -- coerce to 0.
    Empty source_id / profile_id stay NULL.
    """
    f = request.form
    def _opt_int(name):
        v = (f.get(name) or "").strip()
        return int(v) if v.lstrip("-").isdigit() else None
    def _int(name, default=0):
        v = (f.get(name) or "").strip()
        return int(v) if v.lstrip("-").isdigit() else default
    def _bool(name):
        return 1 if f.get(name) in ("1", "on", "true", "yes") else 0
    def _tags_to_json(name):
        """Accept comma-separated UI input or JSON; store as JSON array string.

        Empty input stays as empty string (= no tag filter).
        """
        raw = (f.get(name) or "").strip()
        if not raw:
            return ""
        # already JSON?
        if raw.startswith("["):
            try:
                v = json.loads(raw)
                if isinstance(v, list):
                    cleaned = [str(t).strip() for t in v if str(t).strip()]
                    return json.dumps(cleaned) if cleaned else ""
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        # comma-separated
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return json.dumps(parts) if parts else ""
    sid = _opt_int("source_id")
    if sid == 0:  # 0 = global (NULL source_id)
        sid = None
    return {
        "source_id":      sid,
        "destination_id": _int("destination_id", 0),
        "profile_id":     _opt_int("profile_id"),
        "priority":       _int("priority", 100),
        "enabled":        _bool("enabled"),
        "title_regex":    (f.get("title_regex") or "").strip(),
        "title_excludes": (f.get("title_excludes") or "").strip(),
        "min_duration":   _int("min_duration", 0),
        "max_duration":   _int("max_duration", 0),
        "skip_shorts":    _bool("skip_shorts"),
        "skip_live":      _bool("skip_live"),
        "tags_any":       _tags_to_json("tags_any"),
        "label":          (f.get("label") or "").strip(),
    }


@app.post("/api/routing/rules")
def api_routing_rules_create():
    p = _rule_form_payload() if request.form else (request.get_json(silent=True) or {})
    if not p.get("destination_id"):
        return _err("destination_id required", "MISSING_FIELD", 400)
    cur = g.db.execute(
        """INSERT INTO routing_rules
                (source_id, destination_id, profile_id, priority, enabled,
                 title_regex, title_excludes, min_duration, max_duration,
                 skip_shorts, skip_live, tags_any, label)
           VALUES (:source_id, :destination_id, :profile_id, :priority, :enabled,
                   :title_regex, :title_excludes, :min_duration, :max_duration,
                   :skip_shorts, :skip_live, :tags_any, :label)""",
        p,
    )
    g.db.commit()
    new_id = int(cur.lastrowid)
    row = g.db.execute("SELECT * FROM routing_rules WHERE id = ?", (new_id,)).fetchone()
    return jsonify(dict(row)), 201


@app.post("/api/routing/rules/<int:rid>")
def api_routing_rules_update(rid: int):
    existing = g.db.execute(
        "SELECT id FROM routing_rules WHERE id = ?", (rid,)
    ).fetchone()
    if not existing:
        return _err("rule not found", "NOT_FOUND", 404)
    p = _rule_form_payload() if request.form else (request.get_json(silent=True) or {})
    p["id"] = rid
    g.db.execute(
        """UPDATE routing_rules SET
                source_id      = :source_id,
                destination_id = :destination_id,
                profile_id     = :profile_id,
                priority       = :priority,
                enabled        = :enabled,
                title_regex    = :title_regex,
                title_excludes = :title_excludes,
                min_duration   = :min_duration,
                max_duration   = :max_duration,
                skip_shorts    = :skip_shorts,
                skip_live      = :skip_live,
                tags_any       = :tags_any,
                label          = :label,
                updated_at     = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = :id""",
        p,
    )
    g.db.commit()
    row = g.db.execute("SELECT * FROM routing_rules WHERE id = ?", (rid,)).fetchone()
    return jsonify(dict(row))


@app.delete("/api/routing/rules/<int:rid>")
def api_routing_rules_delete(rid: int):
    n = g.db.execute("DELETE FROM routing_rules WHERE id = ?", (rid,)).rowcount
    g.db.commit()
    if not n:
        return _err("rule not found", "NOT_FOUND", 404)
    return jsonify({"ok": True, "deleted": rid})


@app.get("/api/routing/test/<video_id>")
def api_routing_test(video_id: str):
    """Evaluate all rules against a single catalog video. Returns the
    matching destinations + per-rule reject reasons (for the UI's 'test'
    button).
    """
    v = g.db.execute(
        """SELECT video_id, source_id, title, duration_sec, live_status,
                  tags_json
             FROM catalog_videos WHERE video_id = ? LIMIT 1""",
        (video_id,),
    ).fetchone()
    if not v:
        return _err("video not found in catalog", "NOT_FOUND", 404)
    result = routing.evaluate_video(g.db, v)
    return jsonify({
        "video_id": result.video_id,
        "matches": [m._asdict() for m in result.matches],
        "rejects": [r._asdict() for r in result.rejects],
    })


@app.post("/api/routing/run/<int:source_id>")
def api_routing_run(source_id: int):
    """Re-evaluate all rules against the catalog for `source_id` and
    enqueue ledger rows for any matches that aren't already queued/uploaded.
    """
    src = g.db.execute(
        "SELECT id FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if not src:
        return _err("source not found", "NOT_FOUND", 404)
    triggered_by = (request.args.get("triggered_by") or "cron").strip()
    if triggered_by not in ("cron", "manual", "backfill"):
        triggered_by = "cron"
    stats = routing.route_and_enqueue(g.db, source_id, triggered_by=triggered_by)
    g.db.commit()
    return jsonify({
        "source_id":       source_id,
        "triggered_by":    triggered_by,
        "matched":         stats.matched,
        "enqueued":        stats.enqueued,
        "skipped":         stats.skipped,
        "no_match":        stats.no_match,
        "download_queued": stats.download_queued,
    })


@app.get("/api/routing/preview/<int:source_id>")
def api_routing_preview(source_id: int):
    """Dry-run: evaluate rules against the catalog WITHOUT writing.

    Returns counts + a sample of would-enqueue / already-in-ledger /
    no-match videos so the user can sanity-check before committing.
    """
    src = g.db.execute(
        "SELECT id, name FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if not src:
        return _err("source not found", "NOT_FOUND", 404)
    sample_limit = int((request.args.get("sample") or "20").strip() or "20")
    sample_limit = max(1, min(sample_limit, 100))

    videos = g.db.execute(
        """SELECT video_id, source_id, title, duration_sec, live_status,
                  tags_json
             FROM catalog_videos
            WHERE source_id = ? AND ignored = 0""",
        (source_id,),
    ).fetchall()

    matched = enqueued = skipped = no_match = 0
    would_enqueue: list[dict] = []
    would_skip: list[dict] = []
    no_match_sample: list[dict] = []

    for v in videos:
        result = routing.evaluate_video(g.db, v)
        if not result.matches:
            no_match += 1
            if len(no_match_sample) < sample_limit:
                no_match_sample.append({
                    "video_id": v["video_id"],
                    "title":    v["title"],
                })
            continue
        matched += len(result.matches)
        for m in result.matches:
            existing = g.db.execute(
                """SELECT status FROM upload_ledger
                    WHERE video_id = ? AND destination_id = ?
                    LIMIT 1""",
                (v["video_id"], m.destination_id),
            ).fetchone()
            if existing:
                skipped += 1
                if len(would_skip) < sample_limit:
                    would_skip.append({
                        "video_id":       v["video_id"],
                        "title":          v["title"],
                        "destination_id": m.destination_id,
                        "rule_id":        m.rule_id,
                        "rule_label":     m.rule_label,
                        "ledger_status":  existing["status"],
                    })
            else:
                enqueued += 1
                if len(would_enqueue) < sample_limit:
                    would_enqueue.append({
                        "video_id":       v["video_id"],
                        "title":          v["title"],
                        "destination_id": m.destination_id,
                        "rule_id":        m.rule_id,
                        "rule_label":     m.rule_label,
                    })
    return jsonify({
        "source_id":       source_id,
        "source_name":     src["name"],
        "total_videos":    len(videos),
        "matched":         matched,
        "would_enqueue":   enqueued,
        "would_skip":      skipped,
        "no_match":        no_match,
        "sample": {
            "would_enqueue": would_enqueue,
            "would_skip":    would_skip,
            "no_match":      no_match_sample,
        },
    })


# ---------------------------------------------------------------------------
# Routing UI (HTMX partials)
# ---------------------------------------------------------------------------

def _summarize_rule(r) -> str:
    """One-line human summary of a routing_rules row, for hover tooltips.

    Format: 'pri=10 [enabled] regex=/x/ min=60s skip_live tags=a,b -> profile=2'
    """
    parts: list[str] = [f"pri={r['priority']}"]
    parts.append("enabled" if r["enabled"] else "disabled")
    if r["title_regex"]:
        parts.append(f"regex=/{r['title_regex']}/")
    if r["title_excludes"]:
        parts.append(f"exclude=/{r['title_excludes']}/")
    if r["min_duration"]:
        parts.append(f"min={r['min_duration']}s")
    if r["max_duration"]:
        parts.append(f"max={r['max_duration']}s")
    if r["skip_shorts"]:
        parts.append("skip_shorts")
    if r["skip_live"]:
        parts.append("skip_live")
    raw_tags = (r["tags_any"] or "").strip()
    if raw_tags:
        try:
            v = json.loads(raw_tags)
            if isinstance(v, list):
                parts.append("tags=" + ",".join(str(t) for t in v))
            else:
                parts.append(f"tags={raw_tags}")
        except (TypeError, ValueError, json.JSONDecodeError):
            parts.append(f"tags={raw_tags}")
    if r["profile_id"]:
        parts.append(f"-> profile={r['profile_id']}")
    label = (r["label"] or "").strip()
    head = f"#{r['id']}" + (f" {label}" if label else "")
    return head + " — " + " ".join(parts)


def _routing_render_side(source_id: int, destination_id: int):
    """Render the side panel for a (source_id, destination_id) cell.

    source_id == 0 means "global" (rules with source_id IS NULL).
    """
    if source_id == 0:
        source = None
        rules = g.db.execute(
            """SELECT * FROM routing_rules
                WHERE source_id IS NULL AND destination_id = ?
                ORDER BY priority ASC, id ASC""",
            (destination_id,),
        ).fetchall()
    else:
        source = g.db.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if not source:
            return _err("source not found", "NOT_FOUND", 404)
        rules = g.db.execute(
            """SELECT * FROM routing_rules
                WHERE source_id = ? AND destination_id = ?
                ORDER BY priority ASC, id ASC""",
            (source_id, destination_id),
        ).fetchall()
    destination = g.db.execute(
        "SELECT * FROM destinations WHERE id = ?", (destination_id,)
    ).fetchone()
    if not destination:
        return _err("destination not found", "NOT_FOUND", 404)
    # Pretty-print tags_any (JSON) for each rule for the table cell.
    rule_tag_display = {}
    for r in rules:
        raw = (r["tags_any"] or "").strip()
        if not raw:
            continue
        try:
            v = json.loads(raw)
            if isinstance(v, list):
                rule_tag_display[r["id"]] = ", ".join(str(t) for t in v)
        except (TypeError, ValueError, json.JSONDecodeError):
            rule_tag_display[r["id"]] = raw
    # Recent catalog videos for the "Test against video" picker.
    if source_id == 0:
        recent_videos = g.db.execute(
            """SELECT video_id, title FROM catalog_videos
                WHERE ignored = 0
                ORDER BY COALESCE(upload_date, '') DESC, id DESC
                LIMIT 50"""
        ).fetchall()
    else:
        recent_videos = g.db.execute(
            """SELECT video_id, title FROM catalog_videos
                WHERE source_id = ? AND ignored = 0
                ORDER BY COALESCE(upload_date, '') DESC, id DESC
                LIMIT 50""",
            (source_id,),
        ).fetchall()
    return render_template(
        "partials/routing_side.html",
        source=source,
        destination=destination,
        rules=rules,
        rule_tag_display=rule_tag_display,
        recent_videos=recent_videos,
    )


def _routing_render_form(rule_row, source_id: int, destination_id: int):
    profiles = g.db.execute(
        "SELECT id, name FROM download_profiles ORDER BY id"
    ).fetchall()
    # Convert stored JSON tags_any -> comma-separated string for the input.
    tags_any_display = ""
    if rule_row is not None and (rule_row["tags_any"] or "").strip():
        try:
            v = json.loads(rule_row["tags_any"])
            if isinstance(v, list):
                tags_any_display = ", ".join(str(t) for t in v)
        except (TypeError, ValueError, json.JSONDecodeError):
            tags_any_display = rule_row["tags_any"]
    return render_template(
        "partials/routing_rule_form.html",
        rule=rule_row,
        source_id=source_id,
        destination_id=destination_id,
        profiles=profiles,
        tags_any_display=tags_any_display,
    )


@app.get("/routing")
def page_routing():
    return _render_or_stub("routing.html", "Routing")


@app.get("/partials/routing/matrix")
def partial_routing_matrix():
    sources = g.db.execute(
        "SELECT * FROM sources ORDER BY COALESCE(name, '')"
    ).fetchall()
    destinations = g.db.execute(
        "SELECT * FROM destinations ORDER BY COALESCE(label, ''), id"
    ).fetchall()
    rows = g.db.execute(
        """SELECT source_id, destination_id, COUNT(*) AS n
             FROM routing_rules
            WHERE source_id IS NOT NULL
            GROUP BY source_id, destination_id"""
    ).fetchall()
    rule_counts = {(r["source_id"], r["destination_id"]): r["n"] for r in rows}
    # Top-priority rule per (sid, did) for hover-tooltip summary.
    top_rows = g.db.execute(
        """SELECT r.* FROM routing_rules r
            WHERE r.source_id IS NOT NULL
              AND r.id = (
                SELECT id FROM routing_rules r2
                 WHERE r2.source_id = r.source_id
                   AND r2.destination_id = r.destination_id
                 ORDER BY r2.priority ASC, r2.id ASC
                 LIMIT 1
              )"""
    ).fetchall()
    rule_top_summary = {
        (r["source_id"], r["destination_id"]): _summarize_rule(r)
        for r in top_rows
    }
    global_rules = g.db.execute(
        """SELECT * FROM routing_rules
            WHERE source_id IS NULL
            ORDER BY priority ASC, id ASC"""
    ).fetchall()
    return render_template(
        "partials/routing_matrix.html",
        sources=sources,
        destinations=destinations,
        rule_counts=rule_counts,
        rule_top_summary=rule_top_summary,
        global_rules=global_rules,
    )


@app.get("/partials/routing/cell/<int:sid>/<int:did>")
def partial_routing_cell(sid: int, did: int):
    return _routing_render_side(sid, did)


_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def _extract_video_id(raw: str) -> str:
    """Accept a bare 11-char YouTube id OR a full URL; return the id."""
    s = (raw or "").strip()
    if not s:
        return ""
    if len(s) == 11 and re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    m = _YT_ID_RE.search(s)
    return m.group(1) if m else s


@app.get("/partials/routing/test/<int:sid>/<int:did>")
def partial_routing_test(sid: int, did: int):
    """Evaluate one catalog video against rules; show per-rule results
    filtered to this destination. Renders a small panel injected into
    the side panel's #rule-test-slot.
    """
    raw = request.args.get("video_id", "") or ""
    video_id = _extract_video_id(raw)
    destination = g.db.execute(
        "SELECT * FROM destinations WHERE id = ?", (did,)
    ).fetchone()
    if not destination:
        return _err("destination not found", "NOT_FOUND", 404)
    if not video_id:
        return render_template(
            "partials/routing_test.html",
            error="Enter a video id or URL.",
            destination=destination, source_id=sid,
        )
    v = g.db.execute(
        """SELECT video_id, source_id, title, duration_sec, live_status,
                  tags_json, upload_date
             FROM catalog_videos WHERE video_id = ? LIMIT 1""",
        (video_id,),
    ).fetchone()
    if not v:
        return render_template(
            "partials/routing_test.html",
            error=f"Video {video_id!r} not in catalog.",
            destination=destination, source_id=sid,
        )
    result = routing.evaluate_video(g.db, v)
    # Filter to this destination only.
    matches = [m for m in result.matches if m.destination_id == did]
    rejects = [r for r in result.rejects if r.destination_id == did]
    # Ledger status (if any) for this (video, destination).
    led = g.db.execute(
        """SELECT id, status, triggered_by, created_at FROM upload_ledger
            WHERE video_id = ? AND destination_id = ? LIMIT 1""",
        (video_id, did),
    ).fetchone()
    return render_template(
        "partials/routing_test.html",
        video=v, destination=destination, source_id=sid,
        matches=matches, rejects=rejects, ledger=led,
        all_matches=result.matches,  # for cross-destination hint
    )


@app.get("/partials/routing/rules/new")
def partial_routing_rule_new():
    sid = int(request.args.get("source_id", "0") or 0)
    did = int(request.args.get("destination_id", "0") or 0)
    return _routing_render_form(None, sid, did)


@app.get("/partials/routing/rules/<int:rid>/edit")
def partial_routing_rule_edit(rid: int):
    row = g.db.execute("SELECT * FROM routing_rules WHERE id = ?", (rid,)).fetchone()
    if not row:
        return _err("rule not found", "NOT_FOUND", 404)
    return _routing_render_form(row, row["source_id"] or 0, row["destination_id"])


@app.post("/partials/routing/rules")
def partial_routing_rule_create():
    p = _rule_form_payload()
    if not p.get("destination_id"):
        return _err("destination_id required", "MISSING_FIELD", 400)
    g.db.execute(
        """INSERT INTO routing_rules
                (source_id, destination_id, profile_id, priority, enabled,
                 title_regex, title_excludes, min_duration, max_duration,
                 skip_shorts, skip_live, tags_any, label)
           VALUES (:source_id, :destination_id, :profile_id, :priority, :enabled,
                   :title_regex, :title_excludes, :min_duration, :max_duration,
                   :skip_shorts, :skip_live, :tags_any, :label)""",
        p,
    )
    g.db.commit()
    return _routing_render_side(p["source_id"] or 0, p["destination_id"])


@app.post("/partials/routing/rules/<int:rid>")
def partial_routing_rule_update(rid: int):
    existing = g.db.execute(
        "SELECT id FROM routing_rules WHERE id = ?", (rid,)
    ).fetchone()
    if not existing:
        return _err("rule not found", "NOT_FOUND", 404)
    p = _rule_form_payload()
    p["id"] = rid
    g.db.execute(
        """UPDATE routing_rules SET
                source_id      = :source_id,
                destination_id = :destination_id,
                profile_id     = :profile_id,
                priority       = :priority,
                enabled        = :enabled,
                title_regex    = :title_regex,
                title_excludes = :title_excludes,
                min_duration   = :min_duration,
                max_duration   = :max_duration,
                skip_shorts    = :skip_shorts,
                skip_live      = :skip_live,
                tags_any       = :tags_any,
                label          = :label,
                updated_at     = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = :id""",
        p,
    )
    g.db.commit()
    return _routing_render_side(p["source_id"] or 0, p["destination_id"])


@app.delete("/partials/routing/rules/<int:rid>")
def partial_routing_rule_delete(rid: int):
    row = g.db.execute(
        "SELECT source_id, destination_id FROM routing_rules WHERE id = ?", (rid,)
    ).fetchone()
    if not row:
        return _err("rule not found", "NOT_FOUND", 404)
    g.db.execute("DELETE FROM routing_rules WHERE id = ?", (rid,))
    g.db.commit()
    return _routing_render_side(row["source_id"] or 0, row["destination_id"])


@app.get("/partials/routing/preview/<int:source_id>")
def partial_routing_preview(source_id: int):
    """Render the dry-run preview panel for a source."""
    src = g.db.execute(
        "SELECT id, name FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if not src:
        return _err("source not found", "NOT_FOUND", 404)

    videos = g.db.execute(
        """SELECT video_id, source_id, title, duration_sec, live_status,
                  tags_json
             FROM catalog_videos
            WHERE source_id = ? AND ignored = 0""",
        (source_id,),
    ).fetchall()

    matched = enqueued = skipped = no_match = 0
    would_enqueue: list[dict] = []
    would_skip: list[dict] = []
    sample_limit = 25

    for v in videos:
        result = routing.evaluate_video(g.db, v)
        if not result.matches:
            no_match += 1
            continue
        matched += len(result.matches)
        for m in result.matches:
            existing = g.db.execute(
                """SELECT status FROM upload_ledger
                    WHERE video_id = ? AND destination_id = ?
                    LIMIT 1""",
                (v["video_id"], m.destination_id),
            ).fetchone()
            if existing:
                skipped += 1
                if len(would_skip) < sample_limit:
                    would_skip.append({
                        "video_id": v["video_id"],
                        "title":    v["title"],
                        "destination_id": m.destination_id,
                        "rule_label":     m.rule_label,
                        "ledger_status":  existing["status"],
                    })
            else:
                enqueued += 1
                if len(would_enqueue) < sample_limit:
                    would_enqueue.append({
                        "video_id": v["video_id"],
                        "title":    v["title"],
                        "destination_id": m.destination_id,
                        "rule_label":     m.rule_label,
                    })

    return render_template(
        "partials/routing_preview.html",
        source=src,
        total_videos=len(videos),
        matched=matched,
        would_enqueue=enqueued,
        would_skip=skipped,
        no_match=no_match,
        sample_enqueue=would_enqueue,
        sample_skip=would_skip,
        sample_limit=sample_limit,
    )


# ===========================================================================
# P4 — Manual catalog enqueue (with 30-second soft-undo + quota)
# ===========================================================================

_UNDO_WINDOW_SECONDS = 30
_DEFAULT_DAILY_MAX = 6


def _ledger_quota_status(conn, dest_id: int) -> tuple[int, int, int]:
    """Return (used_24h, daily_max, remaining) for a destination."""
    row = conn.execute(
        "SELECT daily_max FROM destination_quota WHERE destination_id = ?", (dest_id,)
    ).fetchone()
    daily_max = int(row["daily_max"]) if row else _DEFAULT_DAILY_MAX
    used = conn.execute(
        """SELECT COUNT(*) FROM upload_ledger
            WHERE destination_id = ?
              AND status IN ('queued','uploading','uploaded')
              AND uploaded_at > datetime('now', '-1 day')""",
        (dest_id,),
    ).fetchone()[0]
    return int(used), daily_max, max(0, daily_max - int(used))


def _promote_manual_enqueue(ledger_id: int) -> None:
    """Called ~30s after a manual enqueue.

    If the ledger row still exists in 'queued' state with no job_id, create
    the actual `videos` (if needed) and `jobs` rows so n8n picks it up, then
    link the ledger to the job. If the user undid (row deleted) we no-op.
    """
    conn = get_db()
    try:
        led = conn.execute(
            """SELECT * FROM upload_ledger
                WHERE id = ?
                  AND triggered_by = 'manual'
                  AND status = 'queued'
                  AND job_id IS NULL""",
            (ledger_id,),
        ).fetchone()
        if not led:
            return  # canceled or already promoted
        dest = conn.execute(
            "SELECT pipeline_id FROM destinations WHERE id = ?",
            (led["destination_id"],),
        ).fetchone()
        if not dest or not dest["pipeline_id"]:
            return
        pid = int(dest["pipeline_id"])
        yvid = led["video_id"]
        v = conn.execute(
            "SELECT id FROM videos WHERE youtube_video_id = ?", (yvid,)
        ).fetchone()
        if v:
            video_pk = int(v["id"])
        else:
            chan = conn.execute(
                "SELECT id FROM channels WHERE pipeline_id = ? LIMIT 1", (pid,)
            ).fetchone()
            if not chan:
                return
            cur = conn.execute(
                "INSERT INTO videos (channel_id, youtube_video_id, source_url) "
                "VALUES (?, ?, ?)",
                (int(chan["id"]), yvid, f"https://youtu.be/{yvid}"),
            )
            video_pk = int(cur.lastrowid)
        cur = conn.execute(
            "INSERT INTO jobs (video_id, pipeline_id, status) VALUES (?, ?, 'pending')",
            (video_pk, pid),
        )
        job_id = int(cur.lastrowid)
        conn.execute(
            """UPDATE upload_ledger
                  SET job_id = ?,
                      updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
                WHERE id = ?""",
            (job_id, ledger_id),
        )
    except Exception:
        # Promotion failures must not crash the timer thread.
        pass
    finally:
        conn.close()


def _render_status_cell(video_id: str, upload_status: str | None,
                        pending_ledger_id: int | None,
                        pending_created_at: str | None) -> str:
    """Return the HTML for the per-row status cell after enqueue/cancel.

    Mirrors the markup in `partials/catalog_table.html`. Wrapped in
    `data-video-id` so we can target it with hx-swap-oob if needed.
    """
    return render_template(
        "partials/catalog_status_cell.html",
        video_id=video_id,
        upload_status=upload_status,
        pending_ledger_id=pending_ledger_id,
        pending_created_at=pending_created_at,
        undo_window=_UNDO_WINDOW_SECONDS,
    )


@app.post("/partials/catalog/download")
def partial_catalog_download():
    """Manually queue ONE catalog video for download (no upload yet).

    Body (form): video_id, source_id. Inserts a `download_queue` row in
    'pending' status — picked up by the watcher on its next cycle. Returns
    a small HTML pill for the row's Action cell.
    """
    yvid = (request.form.get("video_id") or "").strip()
    source_id_raw = request.form.get("source_id")
    source_id = int(source_id_raw) if (source_id_raw or "").isdigit() else None
    if not yvid or not source_id:
        return ("<span class='text-xs' style='color:#f85149;'>missing fields</span>", 400)

    # Already in-flight or downloaded?
    if g.db.execute(
        "SELECT 1 FROM videos WHERE youtube_video_id = ? LIMIT 1", (yvid,),
    ).fetchone():
        return ("<span class='text-xs' style='color:#3fb950;'>✓ in library</span>", 200)
    existing = g.db.execute(
        """SELECT status FROM download_queue
            WHERE video_id = ?
              AND status IN ('pending','downloading','processing','done','hydrated')
            ORDER BY id DESC LIMIT 1""",
        (yvid,),
    ).fetchone()
    if existing:
        return (
            f"<span class='text-xs' style='color:#d29922;'>queued ({existing['status']})</span>",
            200,
        )

    # Disk-skip: file already present on disk from a prior download. Mark
    # 'complete' immediately (no watcher round-trip) so the catalog pill
    # flips straight to '✓ downloaded' on next refresh.
    src_row = g.db.execute(
        "SELECT id, name, external_id FROM sources WHERE id = ?", (source_id,),
    ).fetchone()
    if src_row:
        on_disk = _find_video_on_disk(dict(src_row), yvid)
        if on_disk:
            g.db.execute(
                """INSERT OR IGNORE INTO download_queue
                        (video_id, source_id, status, triggered_by, updated_at)
                   VALUES (?, ?, 'complete', 'manual', ?)""",
                (yvid, source_id, utcnow_iso()),
            )
            g.db.commit()
            return (
                "<span class='text-xs px-1.5 py-0.5 rounded' "
                "style='background:#0f2419;color:#3fb950;border:1px solid #30363d;' "
                f"title='Already on disk: {on_disk}'>✓ already on disk</span>",
                200,
            )

    # Retry path: if the latest dlq row for this video is 'failed' (or its
    # linked job is 'failed'), RESET it in place rather than inserting a
    # second dlq row. Cleaner audit trail and clears the prior error_message.
    failed = g.db.execute(
        """SELECT dq.id AS dlq_id, dq.job_id
             FROM download_queue dq
             LEFT JOIN jobs j ON j.id = dq.job_id
            WHERE dq.video_id = ?
              AND (dq.status = 'failed' OR j.status = 'failed')
            ORDER BY dq.id DESC LIMIT 1""",
        (yvid,),
    ).fetchone()
    if failed:
        now = utcnow_iso()
        g.db.execute(
            "UPDATE download_queue SET status='pending', updated_at=? WHERE id=?",
            (now, failed["dlq_id"]),
        )
        if failed["job_id"]:
            g.db.execute(
                "UPDATE jobs SET status='pending', error_message='', updated_at=? "
                "WHERE id=?",
                (now, failed["job_id"]),
            )
        g.db.commit()
        return (
            "<span class='text-xs px-1.5 py-0.5 rounded' "
            "style='background:#122b40;color:#58a6ff;border:1px solid #30363d;'>"
            "↻ retrying</span>",
            200,
        )

    g.db.execute(
        """INSERT OR IGNORE INTO download_queue
                (video_id, source_id, status, triggered_by)
           VALUES (?, ?, 'pending', 'manual')""",
        (yvid, source_id),
    )
    g.db.commit()
    return (
        "<span class='text-xs px-1.5 py-0.5 rounded' "
        "style='background:#122b40;color:#58a6ff;border:1px solid #30363d;'>"
        "⤓ queued</span>",
        200,
    )


@app.post("/partials/catalog/download/bulk")
def partial_catalog_download_bulk():
    """Bulk-queue selected catalog video_ids for download.

    Form fields:
      source_id          int
      video_ids          repeated str (multi-checkbox values)

    Returns a small HTML summary pill (HTMX swaps it into a banner).
    """
    source_id_raw = request.form.get("source_id")
    source_id = int(source_id_raw) if (source_id_raw or "").isdigit() else None
    yvids = [v.strip() for v in request.form.getlist("video_ids") if v and v.strip()]
    if not source_id or not yvids:
        return ("<span class='text-xs' style='color:#f85149;'>nothing selected</span>", 400)

    queued = 0
    skipped = 0
    on_disk_count = 0
    src_row = g.db.execute(
        "SELECT id, name, external_id FROM sources WHERE id = ?", (source_id,),
    ).fetchone()
    src_dict = dict(src_row) if src_row else None
    for yvid in yvids:
        if g.db.execute(
            "SELECT 1 FROM videos WHERE youtube_video_id = ? LIMIT 1", (yvid,),
        ).fetchone():
            skipped += 1
            continue
        if g.db.execute(
            """SELECT 1 FROM download_queue
                WHERE video_id = ?
                  AND status IN ('pending','downloading','processing','done','hydrated')
                LIMIT 1""",
            (yvid,),
        ).fetchone():
            skipped += 1
            continue
        # Disk-skip
        if src_dict and _find_video_on_disk(src_dict, yvid):
            g.db.execute(
                """INSERT OR IGNORE INTO download_queue
                        (video_id, source_id, status, triggered_by, updated_at)
                   VALUES (?, ?, 'complete', 'manual', ?)""",
                (yvid, source_id, utcnow_iso()),
            )
            on_disk_count += 1
            continue
        cur = g.db.execute(
            """INSERT OR IGNORE INTO download_queue
                    (video_id, source_id, status, triggered_by)
               VALUES (?, ?, 'pending', 'manual')""",
            (yvid, source_id),
        )
        if cur.rowcount > 0:
            queued += 1
        else:
            skipped += 1
    g.db.commit()
    color = "#3fb950" if (queued or on_disk_count) else "#d29922"
    parts = [f"⤓ queued {queued}"]
    if on_disk_count:
        parts.append(f"✓ on-disk {on_disk_count}")
    if skipped:
        parts.append(f"skipped {skipped}")
    return (
        f"<span class='text-xs px-2 py-1 rounded' "
        f"style='background:#0d1117;color:{color};border:1px solid #30363d;'>"
        + " · ".join(parts)
        + "</span>",
        200,
    )


@app.post("/partials/catalog/enqueue")
def partial_catalog_enqueue():
    """HTMX endpoint. Body (form): video_id, destination_id.

    Returns the replacement HTML for the row's status cell (yellow "Undo" badge).
    """
    yvid = (request.form.get("video_id") or "").strip()
    try:
        dest_id = int(request.form.get("destination_id") or 0)
    except ValueError:
        dest_id = 0
    source_id_raw = request.form.get("source_id")
    source_id = int(source_id_raw) if (source_id_raw or "").isdigit() else None

    if not yvid or not dest_id:
        return ("<span class='text-xs' style='color:#f85149;'>missing fields</span>", 400)
    dest = g.db.execute(
        "SELECT id, pipeline_id, platform, label FROM destinations WHERE id = ?",
        (dest_id,),
    ).fetchone()
    if not dest:
        return ("<span class='text-xs' style='color:#f85149;'>destination not found</span>", 404)

    # Dedup against the ledger
    existing = g.db.execute(
        """SELECT status FROM upload_ledger
            WHERE video_id = ? AND destination_id = ?
              AND status IN ('queued','uploading','uploaded')
            LIMIT 1""",
        (yvid, dest_id),
    ).fetchone()
    if existing:
        return (
            f"<span class='text-xs' style='color:#f85149;'>already {existing['status']}</span>",
            409,
        )

    # Quota check
    used, daily_max, remaining = _ledger_quota_status(g.db, dest_id)
    if remaining <= 0:
        return (
            f"<span class='text-xs' style='color:#f85149;' "
            f"title='Quota for this destination is {daily_max}/day; {used} used in last 24h'>"
            f"quota exceeded ({used}/{daily_max})</span>",
            429,
        )

    # Insert ledger row in 'queued' state — no job_id yet
    cur = g.db.execute(
        """INSERT INTO upload_ledger
                (video_id, destination_id, status, source_id, triggered_by,
                 destination_url, uploaded_at, error_message)
           VALUES (?, ?, 'queued', ?, 'manual', '',
                   strftime('%Y-%m-%dT%H:%M:%S','now'), '')""",
        (yvid, dest_id, source_id),
    )
    ledger_id = int(cur.lastrowid)
    created_at = g.db.execute(
        "SELECT created_at FROM upload_ledger WHERE id = ?", (ledger_id,)
    ).fetchone()["created_at"]

    # Schedule promote-to-job after the soft-undo window
    t = threading.Timer(
        float(_UNDO_WINDOW_SECONDS), _promote_manual_enqueue, args=(ledger_id,)
    )
    t.daemon = True
    t.start()

    return _render_status_cell(yvid, "queued", ledger_id, created_at)


@app.post("/partials/catalog/cancel/<int:ledger_id>")
def partial_catalog_cancel(ledger_id: int):
    """HTMX endpoint. Cancel a manual enqueue still in its undo window."""
    led = g.db.execute(
        "SELECT * FROM upload_ledger WHERE id = ? AND triggered_by = 'manual'",
        (ledger_id,),
    ).fetchone()
    if not led:
        return ("<span class='text-xs' style='color:#f85149;'>not found</span>", 404)
    if led["status"] != "queued" or led["job_id"] is not None:
        return (
            f"<span class='text-xs' style='color:#f85149;'>too late ({led['status']})</span>",
            409,
        )
    yvid = led["video_id"]
    g.db.execute("DELETE FROM upload_ledger WHERE id = ?", (ledger_id,))
    # Restore "— never" (or whatever the latest non-pending status was)
    latest = g.db.execute(
        """SELECT status FROM upload_ledger
            WHERE video_id = ?
            ORDER BY uploaded_at DESC LIMIT 1""",
        (yvid,),
    ).fetchone()
    return _render_status_cell(yvid, latest["status"] if latest else None, None, None)


_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


def _extract_youtube_id(value: str) -> str:
    """Extract an 11-char YouTube video ID from a URL, or return it bare."""
    if not value:
        return ""
    s = value.strip()
    m = _YT_ID_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    return ""


@app.post("/partials/catalog/mark-uploaded")
def partial_catalog_mark_uploaded():
    """HTMX endpoint. Record that the user uploaded this video manually
    (e.g. via YouTube Studio drag-and-drop) so the auto-dispatcher won't
    re-upload it.

    Body (form): video_id, destination_id, source_id (optional)
    Header (hx-prompt): the manual YouTube URL or video ID (optional but
    strongly encouraged so the row links to the live video).
    """
    yvid = (request.form.get("video_id") or "").strip()
    try:
        dest_id = int(request.form.get("destination_id") or 0)
    except ValueError:
        dest_id = 0
    source_id_raw = request.form.get("source_id")
    source_id = int(source_id_raw) if (source_id_raw or "").isdigit() else None

    if not yvid or not dest_id:
        return ("<span class='text-xs' style='color:#f85149;'>missing fields</span>", 400)

    raw_url = (request.headers.get("HX-Prompt") or "").strip()
    dest_video_id = _extract_youtube_id(raw_url)
    # If they pasted just an ID, normalize to a watch URL for the badge link.
    if raw_url and not raw_url.startswith("http") and dest_video_id:
        url_to_store = f"https://www.youtube.com/watch?v={dest_video_id}"
    else:
        url_to_store = raw_url

    dest = g.db.execute(
        "SELECT id FROM destinations WHERE id = ?", (dest_id,)
    ).fetchone()
    if not dest:
        return ("<span class='text-xs' style='color:#f85149;'>destination not found</span>", 404)

    # Upsert the ledger row to 'uploaded' / triggered_by='manual'.
    # If a queued/uploading row exists from a prior auto-attempt, this
    # overwrites it (the manual upload supersedes the bot).
    g.db.execute(
        """INSERT INTO upload_ledger
                (video_id, destination_id, status, source_id, triggered_by,
                 destination_url, destination_video_id, uploaded_at,
                 error_message)
           VALUES (?, ?, 'uploaded', ?, 'manual', ?, ?,
                   strftime('%Y-%m-%dT%H:%M:%S','now'), '')
           ON CONFLICT(video_id, destination_id) DO UPDATE SET
                status               = 'uploaded',
                triggered_by         = 'manual',
                destination_url      = excluded.destination_url,
                destination_video_id = excluded.destination_video_id,
                uploaded_at          = strftime('%Y-%m-%dT%H:%M:%S','now'),
                error_message        = '',
                updated_at           = strftime('%Y-%m-%dT%H:%M:%S','now'),
                source_id            = COALESCE(upload_ledger.source_id,
                                                excluded.source_id)""",
        (yvid, dest_id, source_id, url_to_store, dest_video_id),
    )
    g.db.commit()

    return _render_status_cell(yvid, "uploaded", None, None)


# ===========================================================================
# Pages — HTML stubs for now (real templates in Step 3.2+)
# ===========================================================================

def _stub_page(title: str) -> str:
    return (
        f"<!doctype html><html><head><title>{title} — project003</title></head>"
        f"<body style='font-family:system-ui;padding:2rem;background:#0d1117;color:#c9d1d9'>"
        f"<h1>{title}</h1>"
        f"<p>Page coming in Step 3.2+. The API behind it is live.</p>"
        f"<ul style='line-height:1.8'>"
        f"<li><a href='/pipelines' style='color:#58a6ff'>/pipelines</a></li>"
        f"<li><a href='/queue' style='color:#58a6ff'>/queue</a></li>"
        f"<li><a href='/history' style='color:#58a6ff'>/history</a></li>"
        f"<li><a href='/logs' style='color:#58a6ff'>/logs</a></li>"
        f"</ul></body></html>"
    )


def _render_or_stub(template_name: str, title: str):
    tpl = Path(app.root_path) / "templates" / template_name
    if tpl.exists():
        return render_template(template_name)
    return _stub_page(title)


@app.get("/")
def page_root():
    return redirect(url_for("page_pipelines"))


@app.get("/pipelines")
def page_pipelines():
    return _render_or_stub("pipelines.html", "Pipelines")


@app.get("/queue")
def page_queue():
    return _render_or_stub("queue.html", "Queue")


@app.get("/uploads")
def page_uploads():
    return _render_or_stub("uploads.html", "Uploads")


@app.get("/history")
def page_history():
    channels = [dict(r) for r in g.db.execute(
        "SELECT id, name FROM channels ORDER BY name"
    ).fetchall()]
    destinations = [dict(r) for r in g.db.execute(
        "SELECT id, label, platform FROM destinations ORDER BY label"
    ).fetchall()]
    return render_template(
        "history.html",
        channels=channels,
        destinations=destinations,
    )


@app.get("/logs")
def page_logs():
    return _render_or_stub("logs.html", "Logs")


@app.get("/sources")
def page_sources():
    tpl = Path(app.root_path) / "templates" / "sources.html"
    if tpl.exists():
        return render_template(
            "sources.html",
            pipelines=_all_pipelines_for_view(),
        )
    return _stub_page("Sources")


@app.get("/sources/<int:sid>")
def page_source_catalog(sid: int):
    src = g.db.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()
    if not src:
        return ("Source not found", 404)
    tpl = Path(app.root_path) / "templates" / "catalog.html"
    if tpl.exists():
        return render_template("catalog.html", source=dict(src))
    return _stub_page(f"Catalog: {src['name']}")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "ts": utcnow_iso()})


# ===========================================================================
# Worker state (heartbeat registry)
# ===========================================================================

# Thresholds (seconds since last_beat) used to compute display status.
_WORKER_STALE_AFTER_S = 60
_WORKER_DEAD_AFTER_S  = 300


def heartbeat_worker(
    worker_id: str,
    *,
    kind: str = "",
    status: str = "idle",
    detail: str = "",
    pid: int = 0,
    host: str = "",
    db: sqlite3.Connection | None = None,
) -> None:
    """Upsert a heartbeat row for ``worker_id``.

    Workers should call this periodically (or on every job boundary).
    Status must be one of: idle, busy, error, stopped.
    """
    if status not in ("idle", "busy", "error", "stopped"):
        raise ValueError(f"invalid worker status: {status!r}")
    conn = db if db is not None else get_db()
    conn.execute(
        """INSERT INTO worker_state (worker_id, kind, status, detail, last_beat, pid, host)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%S','now'), ?, ?)
           ON CONFLICT(worker_id) DO UPDATE SET
             kind      = excluded.kind,
             status    = excluded.status,
             detail    = excluded.detail,
             last_beat = excluded.last_beat,
             pid       = excluded.pid,
             host      = excluded.host""",
        (worker_id, kind, status, detail, pid, host),
    )
    if db is None:
        conn.commit()


def _worker_state_rows() -> list[dict]:
    """Return all worker_state rows with computed display status + age."""
    rows = g.db.execute(
        """SELECT worker_id, kind, status, detail, last_beat, started_at, pid, host,
                  CAST(
                    (julianday('now') - julianday(last_beat)) * 86400.0
                    AS INTEGER
                  ) AS age_s
             FROM worker_state
            WHERE kind != 'setting'
            ORDER BY worker_id"""
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        age = int(d.get("age_s") or 0)
        if age < 0:
            age = 0
        if d["status"] == "stopped":
            display = "stopped"
        elif d["status"] == "error":
            display = "error"
        elif age >= _WORKER_DEAD_AFTER_S:
            display = "dead"
        elif age >= _WORKER_STALE_AFTER_S:
            display = "stale"
        else:
            display = d["status"]  # idle | busy
        d["display_status"] = display
        d["age_s"] = age
        out.append(d)
    return out


@app.get("/api/workers")
def api_workers_list():
    """JSON list of all worker heartbeats."""
    return jsonify({"workers": _worker_state_rows()})


@app.get("/partials/worker-status")
def partial_worker_status():
    """Compact header widget: counts of busy / idle / stale / dead workers."""
    rows = _worker_state_rows()
    counts = {"busy": 0, "idle": 0, "stale": 0, "dead": 0, "error": 0, "stopped": 0}
    for r in rows:
        counts[r["display_status"]] = counts.get(r["display_status"], 0) + 1
    # Download-pool capacity / utilisation. The header had no view of the
    # actual concurrent download slots — only of distinct heartbeating
    # processes — which made "1 busy" look wrong while 5 downloads ran.
    try:
        ws = g.db.execute(
            "SELECT detail FROM worker_state WHERE worker_id='download_workers'"
        ).fetchone()
        dl_capacity = int(ws["detail"]) if ws and (ws["detail"] or "").isdigit() else 0
    except (TypeError, ValueError):
        dl_capacity = 0
    try:
        dl_active = int(g.db.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'downloading'"
        ).fetchone()[0])
    except Exception:                                                # noqa: BLE001
        dl_active = 0
    return render_template(
        "partials/worker_status.html",
        workers=rows,
        counts=counts,
        total=len(rows),
        dl_capacity=dl_capacity,
        dl_active=dl_active,
    )


@app.before_request
def _dashboard_self_heartbeat():
    """Heartbeat the 'dashboard' worker on every incoming request.

    Cheap: a single UPSERT touches one row. Gives the header widget
    something to display even before background workers are wired in.
    """
    # Skip for the heartbeat endpoint itself to avoid noise; also skip static.
    p = request.path or ""
    if p.startswith("/partials/worker-status") or p.startswith("/api/workers"):
        return None
    try:
        heartbeat_worker(
            "dashboard",
            kind="web",
            status="busy",
            detail=f"{request.method} {p}"[:80],
            db=g.db,
        )
    except Exception:
        # Heartbeat failure must never break a request.
        pass
    return None


# ===========================================================================
# Bootstrap
# ===========================================================================

init_db()


def _startup_youtube_channel_backfill() -> None:
    """One-shot: enrich existing oauth_tokens rows with their channel UCxxx.

    Network-bound (calls Google) so runs in a daemon thread to avoid
    delaying app startup. Idempotent — skips rows already bound.
    """
    import threading

    def _worker():
        try:
            try:
                from dashboard.youtube_channels import backfill_unbound_tokens
            except ModuleNotFoundError:
                from youtube_channels import backfill_unbound_tokens  # type: ignore
            stats = backfill_unbound_tokens(verbose=True)
            print(f"[startup] youtube_channels backfill: {stats}", flush=True)
        except Exception as e:
            print(f"[startup] youtube_channels backfill failed: {e}", flush=True)

    threading.Thread(target=_worker, daemon=True,
                     name="yt-channel-backfill").start()


_startup_youtube_channel_backfill()


def _startup_recovery_sweep() -> None:
    """Recover state after a container restart killed in-flight uploads.

    1. `upload_progress` rows in non-terminal stages are orphaned threads
       (the thread died with the previous container). Mark the matching
       jobs back to 'processed' so they can be re-uploaded, and drop the
       progress rows.
    2. Delete on-disk folders for videos whose latest upload_result is
       'uploaded' (covers the gap before AUTO_CLEANUP_AFTER_UPLOAD existed).
    """
    import os, shutil, sqlite3 as _sqlite3
    try:
        from dashboard.models import get_db as _get_db
    except ModuleNotFoundError:
        from models import get_db as _get_db
    conn = _get_db()
    try:
        # ---- 1) Orphaned upload_progress rows --------------------------
        rows = conn.execute(
            "SELECT job_id FROM upload_progress "
            "WHERE stage IN ('starting','uploading','processing')"
        ).fetchall()
        orphaned_jobs = [r["job_id"] for r in rows]
        if orphaned_jobs:
            qs = ",".join("?" * len(orphaned_jobs))
            conn.execute(
                f"DELETE FROM upload_progress WHERE job_id IN ({qs})",
                orphaned_jobs,
            )
            # Reset only jobs without a successful upload_result.
            conn.execute(
                f"UPDATE jobs SET status='processed' "
                f"WHERE id IN ({qs}) AND status='uploading' "
                f"AND id NOT IN (SELECT job_id FROM upload_results WHERE status='uploaded')",
                orphaned_jobs,
            )
            conn.commit()
            print(f"[startup] reset {len(orphaned_jobs)} orphaned upload(s): {orphaned_jobs}", flush=True)

        # ---- 1b) Zombie jobs: status='uploading' with no progress row ---
        zombies = conn.execute(
            "SELECT id FROM jobs WHERE status='uploading' "
            "AND id NOT IN (SELECT job_id FROM upload_progress) "
            "AND id NOT IN (SELECT job_id FROM upload_results WHERE status='uploaded')"
        ).fetchall()
        if zombies:
            zids = [r["id"] for r in zombies]
            qs = ",".join("?" * len(zids))
            conn.execute(
                f"UPDATE jobs SET status='processed' WHERE id IN ({qs})",
                zids,
            )
            conn.commit()
            print(f"[startup] reset {len(zids)} zombie job(s): {zids}", flush=True)

        # ---- 2) One-time on-disk cleanup of already-uploaded folders ---
        if os.getenv("AUTO_CLEANUP_AFTER_UPLOAD", "1") == "1":
            uploaded = conn.execute(
                "SELECT DISTINCT v.youtube_video_id ytid "
                "FROM upload_results ur "
                "JOIN jobs j   ON j.id = ur.job_id "
                "JOIN videos v ON v.id = j.video_id "
                "WHERE ur.status='uploaded'"
            ).fetchall()
            removed = 0
            for r in uploaded:
                ytid = r["ytid"]
                if not ytid:
                    continue
                folder = f"/shared/downloads/{ytid}"
                if os.path.isdir(folder):
                    shutil.rmtree(folder, ignore_errors=True)
                    removed += 1
            if removed:
                print(f"[startup] cleaned {removed} already-uploaded folder(s)", flush=True)
    except Exception as e:
        print(f"[startup] recovery sweep failed: {type(e).__name__}: {e}", flush=True)
    finally:
        conn.close()


# ===========================================================================
# Quota retry sweep — periodically re-queues uploads that were deferred
# because the destination's daily YouTube API quota was exhausted. Runs once
# the destination's `quota_resets_at` has passed.
# ===========================================================================

_QUOTA_RETRY_ENABLED  = os.getenv("QUOTA_RETRY_ENABLED", "1") == "1"
_QUOTA_RETRY_INTERVAL = int(os.getenv("QUOTA_RETRY_INTERVAL_SEC", "900"))  # 15 min


def _quota_retry_loop() -> None:
    while True:
        try:
            n = _uploader.sweep_deferred_uploads(broadcast=_sse_broadcast)
            if n:
                print(f"[quota-retry] re-queued {n} deferred upload(s)", flush=True)
        except Exception as e:                                      # noqa: BLE001
            print(f"[quota-retry] sweep failed: {type(e).__name__}: {e}",
                  flush=True)
        time.sleep(_QUOTA_RETRY_INTERVAL)


def _start_quota_retry_worker_once() -> None:
    if not _QUOTA_RETRY_ENABLED:
        print("[quota-retry] disabled (QUOTA_RETRY_ENABLED=0)", flush=True)
        return
    if getattr(_start_quota_retry_worker_once, "_started", False):
        return
    _start_quota_retry_worker_once._started = True  # type: ignore[attr-defined]
    t = threading.Thread(target=_quota_retry_loop, name="quota-retry",
                         daemon=True)
    t.start()
    print(f"[quota-retry] started (interval={_QUOTA_RETRY_INTERVAL}s)", flush=True)


# ===========================================================================
# DLQ hydrator — periodically materializes pending download_queue rows into
# `jobs` rows so the watcher container picks them up. Idempotent and bounded
# by `_DLQ_HYDRATE_BATCH` per tick.
# ===========================================================================

_DLQ_HYDRATE_ENABLED  = os.getenv("DLQ_HYDRATE_ENABLED", "1") == "1"
_DLQ_HYDRATE_INTERVAL = int(os.getenv("DLQ_HYDRATE_INTERVAL_SEC", "30"))
_DLQ_HYDRATE_IDLE     = int(os.getenv("DLQ_HYDRATE_IDLE_SEC", "30"))
_DLQ_HYDRATE_BATCH    = int(os.getenv("DLQ_HYDRATE_BATCH", "10"))


def _dlq_hydrate_loop() -> None:
    print(f"[dlq-hydrator] starting (batch={_DLQ_HYDRATE_BATCH}, "
          f"interval={_DLQ_HYDRATE_INTERVAL}s, idle={_DLQ_HYDRATE_IDLE}s)",
          flush=True)
    try:
        from dashboard.models import get_db as _get_db
    except ModuleNotFoundError:
        from models import get_db as _get_db

    while True:
        sleep_for = _DLQ_HYDRATE_INTERVAL
        conn = None
        try:
            conn = _get_db()
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM download_queue WHERE status='pending'"
            ).fetchone()["n"]

            if pending == 0:
                # Still call terminal-sync occasionally to flip
                # hydrated -> complete/failed for finished work.
                try:
                    n = _dlq_sync_terminal(conn)
                    if n:
                        print(f"[dlq-hydrator] synced {n} terminal row(s)",
                              flush=True)
                except Exception as e:                           # noqa: BLE001
                    print(f"[dlq-hydrator] terminal-sync error: "
                          f"{type(e).__name__}: {e}", flush=True)

                heartbeat_worker(
                    "dlq-hydrator", kind="hydrator",
                    status="idle", detail="no pending rows", db=conn,
                )
                conn.commit()
                sleep_for = _DLQ_HYDRATE_IDLE
            else:
                heartbeat_worker(
                    "dlq-hydrator", kind="hydrator",
                    status="busy",
                    detail=f"hydrating up to {_DLQ_HYDRATE_BATCH} of {pending}",
                    db=conn,
                )
                stats = hydrate_download_queue(conn, limit=_DLQ_HYDRATE_BATCH)
                conn.commit()
                if stats["hydrated"] or stats["errors"]:
                    print(
                        f"[dlq-hydrator] hydrated={stats['hydrated']} "
                        f"errors={stats['errors']} "
                        f"considered={stats['considered']}",
                        flush=True,
                    )
                # Also opportunistically reconcile finished work.
                try:
                    _dlq_sync_terminal(conn)
                except Exception:                                # noqa: BLE001
                    pass
                heartbeat_worker(
                    "dlq-hydrator", kind="hydrator",
                    status="idle",
                    detail=f"last batch: hydrated={stats['hydrated']} "
                           f"errors={stats['errors']}",
                    db=conn,
                )
                conn.commit()
        except Exception as e:                                   # noqa: BLE001
            print(f"[dlq-hydrator] error: {type(e).__name__}: {e}", flush=True)
            try:
                if conn is not None:
                    heartbeat_worker(
                        "dlq-hydrator", kind="hydrator",
                        status="error", detail=f"{type(e).__name__}: {e}"[:80],
                        db=conn,
                    )
                    conn.commit()
            except Exception:
                pass
            sleep_for = _DLQ_HYDRATE_INTERVAL
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        time.sleep(sleep_for)


def _start_dlq_hydrate_worker_once() -> None:
    if not _DLQ_HYDRATE_ENABLED:
        print("[dlq-hydrator] disabled (DLQ_HYDRATE_ENABLED=0)", flush=True)
        return
    if getattr(_start_dlq_hydrate_worker_once, "_started", False):
        return
    _start_dlq_hydrate_worker_once._started = True  # type: ignore[attr-defined]
    t = threading.Thread(target=_dlq_hydrate_loop, name="dlq-hydrator",
                         daemon=True)
    t.start()


# ===========================================================================
# Downloads tab — channel-trigger UI, file CRUD, job retry/cancel
# ===========================================================================

DOWNLOADS_ROOT = Path(os.getenv("DOWNLOADS_ROOT", "/shared/downloads"))


def _safe_downloads_path(rel: str) -> Optional[Path]:
    """Resolve a user-supplied relative path under DOWNLOADS_ROOT.

    Returns the resolved Path if it stays inside DOWNLOADS_ROOT,
    otherwise None (path-traversal guard). Empty/None returns the root.
    """
    rel = (rel or "").strip().lstrip("/\\")
    if not rel or rel == ".":
        return DOWNLOADS_ROOT
    try:
        target = (DOWNLOADS_ROOT / rel).resolve()
        root = DOWNLOADS_ROOT.resolve()
        target.relative_to(root)
        return target
    except (ValueError, OSError):
        return None


def _human_size(n: int) -> str:
    n = float(max(0, int(n)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def _list_downloads_dir(rel: str = "") -> dict:
    """Return {cwd, parent, entries[]} for the downloads browser."""
    target = _safe_downloads_path(rel)
    if target is None or not target.exists():
        return {"cwd": rel, "parent": None, "entries": [], "error": "not found"}
    if target.is_file():
        # Treat file as its parent dir
        target = target.parent
    root = DOWNLOADS_ROOT.resolve()
    cwd_rel = "" if target == root else str(target.relative_to(root)).replace("\\", "/")
    parent_rel: Optional[str] = None
    if target != root:
        p = target.parent
        parent_rel = "" if p == root else str(p.relative_to(root)).replace("\\", "/")

    entries: list[dict] = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                st = child.stat()
            except OSError:
                continue
            is_dir = child.is_dir()
            if is_dir:
                size = 0
                count = 0
                try:
                    for sub in child.rglob("*"):
                        if sub.is_file():
                            try:
                                size += sub.stat().st_size
                                count += 1
                            except OSError:
                                pass
                except OSError:
                    pass
            else:
                size = st.st_size
                count = 1
            child_rel = str(child.relative_to(root)).replace("\\", "/")
            entries.append({
                "name":      child.name,
                "rel_path":  child_rel,
                "is_dir":    is_dir,
                "size":      size,
                "size_h":    _human_size(size),
                "count":     count,
                "mtime":     datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    except OSError as e:
        return {"cwd": cwd_rel, "parent": parent_rel, "entries": [],
                "error": str(e)}
    return {"cwd": cwd_rel, "parent": parent_rel, "entries": entries, "error": None}

def _ensure_channel_priority_column() -> None:
    """Ensure channels.download_priority exists (lazy runtime migration).

    This keeps the Downloads page working even before a full app restart
    triggers models.init_db migrations.
    """
    if getattr(_ensure_channel_priority_column, "_done", False):
        return
    cols = {
        r["name"]
        for r in g.db.execute("PRAGMA table_info(channels)").fetchall()
    }
    if "download_priority" not in cols:
        g.db.execute(
            "ALTER TABLE channels "
            "ADD COLUMN download_priority INTEGER NOT NULL DEFAULT 100"
        )
        g.db.commit()
    _ensure_channel_priority_column._done = True  # type: ignore[attr-defined]


def _channels_with_stats(pipeline_id: Optional[int] = None) -> list[dict]:
    _ensure_channel_priority_column()
    sql = """SELECT c.id, c.name, c.url, c.pipeline_id, c.daily_limit,
                    c.uploads_today, c.backfill_complete, c.backfill_queue,
                    c.download_unlimited, c.active,
              COALESCE(c.download_priority, 100) AS download_priority,
                    p.name AS pipeline_name
               FROM channels c
               LEFT JOIN pipelines p ON p.id = c.pipeline_id
          WHERE (
              c.active = 1
             OR COALESCE(c.uploads_today, 0) > 0
             OR EXISTS (
                SELECT 1 FROM videos v
                 WHERE v.channel_id = c.id
             )
             OR EXISTS (
                SELECT 1 FROM videos v
                JOIN jobs j ON j.video_id = v.id
                 WHERE v.channel_id = c.id
             )
             OR EXISTS (
                SELECT 1 FROM download_queue dq
                JOIN videos v2 ON v2.id = dq.video_id
                 WHERE v2.channel_id = c.id
             )
          )"""
    params: tuple = ()
    if pipeline_id is not None:
        sql += " AND c.pipeline_id = ?"
        params = (pipeline_id,)
    sql += " ORDER BY COALESCE(c.download_priority, 100) ASC, c.name COLLATE NOCASE"

    rows = g.db.execute(sql, params).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            backfill_q = json.loads(d.get("backfill_queue") or "[]")
        except (json.JSONDecodeError, TypeError):
            backfill_q = []
        d["backfill_remaining"] = len(backfill_q)
        # job counts grouped by status for this channel
        counts = {"pending": 0, "downloaded": 0, "processing": 0,
                  "processed": 0, "uploading": 0, "done": 0, "failed": 0,
                  "partial": 0}
        for jr in g.db.execute(
            """SELECT j.status, COUNT(*) AS n
                 FROM jobs j JOIN videos v ON v.id = j.video_id
                WHERE v.channel_id = ?
                GROUP BY j.status""",
            (d["id"],),
        ).fetchall():
            counts[jr["status"]] = jr["n"]
        d["job_counts"] = counts
        d["has_activity"] = bool(sum(int(v or 0) for v in counts.values()))
        out.append(d)
    return out


@app.get("/downloads")
def page_downloads():
    selected_pipeline_id = request.args.get("pipeline_id", type=int)

    # Read current workers setting from DB
    row = g.db.execute(
        "SELECT detail FROM worker_state WHERE worker_id='download_workers'"
    ).fetchone()
    try:
        download_workers = max(1, min(int((row or ["2"])[0]), 12))
    except (TypeError, ValueError):
        download_workers = 2

    # Read global pause state
    prow = g.db.execute(
        "SELECT detail FROM worker_state WHERE worker_id='queue_paused'"
    ).fetchone()
    queue_paused = bool(prow and (prow[0] or "0") == "1")

    # Read current downloads-root override (if any) from DB
    row2 = g.db.execute(
        "SELECT detail FROM worker_state WHERE worker_id='downloads_root'"
    ).fetchone()
    downloads_root_override = (row2[0] if row2 and row2[0] else "") or ""
    downloads_root_default = os.getenv("DOWNLOAD_DIR", "/downloads")
    # What the watcher will actually use right now (best-effort check)
    effective = downloads_root_override or downloads_root_default
    try:
        effective_exists = Path(effective).exists() and Path(effective).is_dir()
    except OSError:
        effective_exists = False

    tpl = Path(app.root_path) / "templates" / "downloads.html"
    if tpl.exists():
        return render_template(
            "downloads.html",
            download_workers=download_workers,
            queue_paused=queue_paused,
            downloads_root_override=downloads_root_override,
            downloads_root_default=downloads_root_default,
            downloads_root_effective=effective,
            downloads_root_effective_exists=effective_exists,
            quick_locations=_quick_locations(),
            host_mount_diagnostics=_host_mount_diagnostics(),
            pipelines=_all_pipelines_for_view(),
            selected_pipeline_id=selected_pipeline_id,
            channels=_channels_with_stats(selected_pipeline_id),
        )
    return _stub_page("Downloads")


@app.post("/api/settings/download-workers")
def api_set_download_workers():
    """Persist download worker count to DB so the watcher picks it up live."""
    try:
        n = max(1, min(int(request.form.get("live-workers-select", 2)), 12))
    except (TypeError, ValueError):
        n = 2
    g.db.execute(
        """INSERT INTO worker_state
               (worker_id, kind, status, detail, last_beat, started_at, pid, host)
           VALUES ('download_workers','setting','idle',?,
                   strftime('%Y-%m-%dT%H:%M:%S','now'),
                   strftime('%Y-%m-%dT%H:%M:%S','now'),0,'')
           ON CONFLICT(worker_id) DO UPDATE
               SET detail=excluded.detail,
                   last_beat=excluded.last_beat""",
        (str(n),),
    )
    g.db.commit()
    return ("", 204)


@app.post("/api/settings/downloads-root")
def api_set_downloads_root():
    """Persist a downloads-root path override to the DB.

    The watcher reads this via _resolve_download_root() each download cycle
    and validates that the path exists inside its container before using it.
    Returns an HTML fragment (HTMX swap) summarizing the saved state.
    """
    raw = (request.form.get("downloads_root", "") or "").strip()
    # Normalize: strip trailing slashes, normalize separators
    val = raw.rstrip("/\\").replace("\\", "/")

    # If user pasted a dashboard-visible path, translate to watcher path so the
    # watcher can find it. Also detect Windows host paths and warn.
    is_windows_host = bool(val) and (
        len(val) >= 2 and val[1] == ":" and val[0].isalpha()
    )
    windows_converted = False
    if is_windows_host:
        # Convert host-style path (e.g. E:/N8N) into mounted container path
        # expected by dashboard + watcher when host drives are bind-mounted.
        drive = val[0].lower()
        remainder = val[2:].lstrip("/")
        val = f"/host/{drive}/{remainder}" if remainder else f"/host/{drive}"
        windows_converted = True

    translated = _translate_to_watcher_path(val) if val else val
    if translated != val:
        app.logger.info("downloads-root: translated dashboard path %s -> %s", val, translated)
    val_to_save = translated

    g.db.execute(
        """INSERT INTO worker_state
               (worker_id, kind, status, detail, last_beat, started_at, pid, host)
           VALUES ('downloads_root','setting','idle',?,
                   strftime('%Y-%m-%dT%H:%M:%S','now'),
                   strftime('%Y-%m-%dT%H:%M:%S','now'),0,'')
           ON CONFLICT(worker_id) DO UPDATE
               SET detail=excluded.detail,
                   last_beat=excluded.last_beat""",
        (val_to_save,),
    )
    g.db.commit()

    default = os.getenv("DOWNLOAD_DIR", "/downloads")
    effective = val_to_save or default
    # Check the dashboard's view (translate back) since the dashboard can't see
    # the watcher's filesystem directly.
    dashboard_view = effective
    for d_root, w_root in DASHBOARD_TO_WATCHER_MAP.items():
        if effective == w_root or effective.startswith(w_root + "/"):
            dashboard_view = d_root + effective[len(w_root):]
            break
    try:
        exists = Path(dashboard_view).exists() and Path(dashboard_view).is_dir()
    except OSError:
        exists = False

    if windows_converted:
        if exists:
            return (
                f"<div class='text-xs mt-2 p-2 rounded' "
                f"style='background:#0f2d1a;color:#3fb950;border:1px solid #1f6f43;'>"
                f"✓ Saved. Converted <code>{raw}</code> to container path "
                f"<code>{effective}</code>. New downloads will use this folder.</div>"
            )
        return (
            f"<div class='text-xs mt-2 p-2 rounded space-y-1' "
            f"style='background:#2d2208;color:#d29922;border:1px solid #5c3d0a;'>"
            f"<div><strong>⚠ Saved and converted.</strong> "
            f"<code>{raw}</code> -> <code>{effective}</code></div>"
            f"<div style='color:#8b949e;'>If this path is still not visible, ensure your "
            f"host drive is mounted in both <code>dashboard</code> and <code>watcher</code> "
            f"services, then run <code>docker compose up -d</code>.</div>"
            f"</div>"
        )
    if not val_to_save:
        return (
            f"<div class='text-xs mt-2' style='color:#7d8590'>"
            f"Override cleared — using default <code>{default}</code>.</div>"
        )
    if exists:
        return (
            f"<div class='text-xs mt-2' style='color:#3fb950'>"
            f"✓ Saved. Watcher will write new downloads to "
            f"<code>{effective}</code> on its next cycle.</div>"
        )
    return (
        f"<div class='text-xs mt-2' style='color:#d29922'>"
        f"⚠ Saved <code>{effective}</code>, but it's not visible from the "
        f"dashboard container. It may still work if the watcher has its own "
        f"bind mount. Otherwise add the path to <code>docker-compose.yml</code> "
        f"and run <code>docker compose up -d</code>.</div>"
    )


# ---------------------------------------------------------------------------
# Folder browser for the Storage Location picker
# ---------------------------------------------------------------------------
# The dashboard container sees host paths under /shared/downloads, but the
# watcher container sees the same host folder under /downloads. Translate
# dashboard paths -> watcher paths when saving.
DASHBOARD_TO_WATCHER_MAP = {
    "/shared/downloads": "/downloads",
}


def _translate_to_watcher_path(dashboard_path: str) -> str:
    """Convert a dashboard-visible path to the equivalent watcher path."""
    if not dashboard_path:
        return dashboard_path
    p = dashboard_path.replace("\\", "/").rstrip("/") or "/"
    for d_root, w_root in DASHBOARD_TO_WATCHER_MAP.items():
        if p == d_root or p.startswith(d_root + "/"):
            return w_root + p[len(d_root):]
    return p


def _quick_locations() -> list[dict]:
    """
    Suggested starting points for the folder browser.
    Reads /proc/mounts to discover actual bind mounts from the host
    (external drives, NAS shares, etc.) alongside well-known paths.
    """
    out: list[dict] = []
    seen: set[str] = set()

    # ── 1. Parse /proc/mounts for real bind mounts ──────────────────────────
    # On Docker-for-Windows the host bind mounts show up as "overlay" or with
    # the Windows share prefix; we include any mount point that exists and
    # isn't a kernel pseudo-fs.
    _SKIP_FS = {
        "proc", "sysfs", "devtmpfs", "cgroup", "cgroup2", "tmpfs",
        "devpts", "mqueue", "hugetlbfs", "pstore", "nsfs", "securityfs",
        "fusectl", "configfs", "tracefs", "debugfs",
    }
    _SKIP_MNT = {"/proc", "/sys", "/dev", "/run", "/tmp"}
    try:
        with open("/proc/mounts", "r") as _f:
            for _line in _f:
                _parts = _line.split()
                if len(_parts) < 3:
                    continue
                _dev, _mnt, _fstype = _parts[0], _parts[1], _parts[2]
                if _fstype in _SKIP_FS:
                    continue
                if any(_mnt == s or _mnt.startswith(s + "/") for s in _SKIP_MNT):
                    continue
                if _mnt in seen:
                    continue
                try:
                    p = Path(_mnt)
                    if p.exists() and p.is_dir():
                        # Build a readable label from the device / path
                        if _mnt == "/":
                            lbl = "Root filesystem (/)"
                        elif _mnt.startswith("/shared/"):
                            lbl = f"Shared volume  {_mnt}"
                        elif _mnt.startswith("/mnt/"):
                            lbl = f"Mount  {_mnt}"
                        elif _mnt.startswith("/media/"):
                            lbl = f"Media  {_mnt}"
                        elif _mnt.startswith("/external"):
                            lbl = f"External  {_mnt}"
                        else:
                            lbl = _mnt
                        out.append({"path": _mnt, "label": lbl})
                        seen.add(_mnt)
                except OSError:
                    pass
    except (OSError, IOError):
        pass  # /proc/mounts not available (e.g. non-Linux host)

    # ── 2. Always include well-known fallbacks if they exist ─────────────────
    _ALWAYS = [
        ("/shared/downloads", "Downloads (default)"),
        ("/downloads",         "Downloads (/downloads)"),
        ("/host/c",            "Host C drive (/host/c)"),
        ("/host/d",            "Host D drive (/host/d)"),
        ("/host/e",            "Host E drive (/host/e)"),
        ("/host",              "All mounted host drives (/host)"),
        ("/external",          "External (/external)"),
        ("/mnt",               "Mounts (/mnt)"),
        ("/media",             "Removable media (/media)"),
        ("/",                  "Root filesystem (/)"),
    ]
    for _path, _label in _ALWAYS:
        if _path not in seen:
            try:
                if Path(_path).exists() and Path(_path).is_dir():
                    out.append({"path": _path, "label": _label})
                    seen.add(_path)
            except OSError:
                pass

    # Sort: root last, rest alphabetically by path
    out.sort(key=lambda x: (x["path"] == "/", x["path"]))
    return out


def _host_mount_diagnostics() -> list[dict]:
    """Return quick status checks for expected host/volume mount points."""
    checks = [
        ("/host", "Host root"),
        ("/host/c", "Host C"),
        ("/host/d", "Host D"),
        ("/host/e", "Host E"),
        ("/shared/downloads", "Shared downloads"),
        ("/downloads", "Watcher downloads path"),
    ]
    out: list[dict] = []
    for p, label in checks:
        status = "missing"
        detail = "not mounted"
        try:
            path = Path(p)
            if path.exists():
                if path.is_dir():
                    # Test readability by listing at least one entry.
                    try:
                        first = next(path.iterdir(), None)
                        status = "ok"
                        detail = "readable"
                        if first is None:
                            detail = "readable (empty)"
                    except (OSError, PermissionError) as ex:
                        status = "warn"
                        detail = f"mounted but unreadable: {ex}"
                else:
                    status = "warn"
                    detail = "mounted but not a directory"
        except OSError as ex:
            status = "warn"
            detail = f"check failed: {ex}"
        out.append({"path": p, "label": label, "status": status, "detail": detail})
    return out


@app.get("/api/storage/browse")
def api_storage_browse():
    """List subdirectories of the requested path. Returns an HTMX fragment.

    Query params:
        path   — directory to list (default: / so ALL mounts are visible)
        q      — optional case-insensitive name filter
        jump   — jump directly to an arbitrary absolute path (typed by user)
    """
    # Prefer host mount root so users see machine drives first (c/e/...)
    default_start = "/host" if Path("/host").exists() and Path("/host").is_dir() else "/"

    # A "jump" overrides the path param
    jump_raw = (request.args.get("jump") or "").strip()
    raw = jump_raw or (request.args.get("path") or default_start).strip()
    query = (request.args.get("q") or "").strip().lower()

    # Normalize
    raw_norm = raw.replace("\\", "/").rstrip("/") or "/"
    try:
        target = Path(raw_norm).resolve()
    except OSError:
        target = Path("/")

    path_not_found = not target.exists() or not target.is_dir()

    if path_not_found:
        # Show a helpful error with mount-point suggestions
        def _mount_link(m: dict) -> str:
            p, lbl = m["path"], m["label"]
            return (
                f"<a hx-get='/api/storage/browse?path={p}' "
                f"hx-target='#storage-browser' hx-swap='innerHTML' "
                f"class='block px-3 py-1 text-xs cursor-pointer hover:bg-gray-800 font-mono' "
                f"style='color:#58a6ff;border-bottom:1px solid #21262d;'>"
                f"📁 {p}  <span style='color:#8b949e;'>— {lbl}</span></a>"
            )
        mounts_html = "".join(_mount_link(m) for m in _quick_locations())
        return (
            f"<div class='space-y-2'>"
            f"<div class='text-xs p-2 rounded' "
            f"style='background:#3a1d1d;color:#f85149;border:1px solid #5d2828;'>"
            f"Path not found in container: <code>{target}</code>"
            f"</div>"
            f"{_jump_input_html(str(target), query)}"
            f"<div class='text-xs' style='color:#8b949e;'>Available locations:</div>"
            f"<div class='rounded' style='background:#0d1117;border:1px solid #30363d;'>"
            f"{mounts_html}"
            f"</div></div>"
        )

    # Standard Linux OS directories — hide these at root since they're
    # container internals, not storage locations the user cares about.
    _LINUX_OS_DIRS = {
        "bin", "boot", "dev", "etc", "lib", "lib32", "lib64", "libx32",
        "proc", "root", "run", "sbin", "srv", "sys", "tmp", "usr", "var",
    }

    # Gather subdirectories (sorted, hidden ones last)
    # At root `/` we filter out OS dirs so only useful mount points are shown.
    at_root = str(target) == "/"
    try:
        entries: list[str] = []
        for child in target.iterdir():
            try:
                if not child.is_dir():
                    continue
                name = child.name
                if at_root and not query and name in _LINUX_OS_DIRS:
                    continue  # skip container OS dirs when browsing root
                if query and query not in name.lower():
                    continue
                entries.append(name)
            except OSError:
                continue
        entries.sort(key=lambda n: (n.startswith("."), n.lower()))
    except PermissionError:
        return (
            f"<div class='text-xs p-2 rounded' "
            f"style='background:#3a1d1d;color:#f85149;border:1px solid #5d2828;'>"
            f"Permission denied: <code>{target}</code></div>"
        )

    parent = str(target.parent) if str(target) != "/" else None
    watcher_path = _translate_to_watcher_path(str(target))

    parts: list[str] = []
    parts.append("<div class='space-y-2'>")

    # ── Header: current path + "Use this folder" ────────────────────────────
    root_hint = (
        "<div class='text-xs mt-1' style='color:#d29922;'>"
        "Showing storage volumes only — OS system dirs hidden. "
        "Use the jump input or filter to navigate anywhere.</div>"
        if at_root else ""
    )
    parts.append(
        f"<div class='flex items-start gap-2 p-2 rounded' "
        f"style='background:#0d1117;border:1px solid #30363d;'>"
        f"<div class='flex-1 min-w-0'>"
        f"<div class='text-xs' style='color:#8b949e;'>Current folder (dashboard view)</div>"
        f"<div class='text-xs font-mono break-all' style='color:#e6edf3;'>{target}</div>"
        f"<div class='text-xs mt-1' style='color:#8b949e;'>Watcher will see this as</div>"
        f"<div class='text-xs font-mono break-all' style='color:#3fb950;'>{watcher_path}</div>"
        f"{root_hint}"
        f"</div>"
        f"<button type='button' "
        f"onclick=\"document.querySelector('input[name=downloads_root]').value='{watcher_path}';"
        f"closeFolderBrowser();\" "
        f"class='text-xs px-3 py-1.5 rounded font-medium whitespace-nowrap' "
        f"style='background:#238636;color:#fff;border:1px solid #2ea043;'>"
        f"✓ Use this folder</button>"
        f"</div>"
    )

    # ── Jump-to-path input ───────────────────────────────────────────────────
    parts.append(_jump_input_html(str(target), query))

    # ── Filter input (name search within current dir) ────────────────────────
    parts.append(
        f"<input type='text' name='q' value='{query}' "
        f"placeholder='Filter folders by name…' "
        f"class='w-full rounded px-2 py-1 text-xs font-mono' "
        f"style='background:#0d1117;color:#e6edf3;border:1px solid #30363d;' "
        f"hx-get='/api/storage/browse' "
        f"hx-trigger='keyup changed delay:200ms' "
        f"hx-target='#storage-browser' "
        f"hx-swap='innerHTML' "
        f"hx-include=\"[name='path']\" />"
    )
    parts.append(f"<input type='hidden' name='path' value='{target}' />")

    # ── Navigation list ──────────────────────────────────────────────────────
    parts.append(
        "<div class='rounded' style='background:#0d1117;border:1px solid #30363d;"
        "max-height:340px;overflow:auto;'>"
    )
    if parent:
        parts.append(
            f"<a hx-get='/api/storage/browse?path={parent}' "
            f"hx-target='#storage-browser' hx-swap='innerHTML' "
            f"class='block px-3 py-1.5 text-xs cursor-pointer hover:bg-gray-800' "
            f"style='color:#58a6ff;border-bottom:1px solid #30363d;'>"
            f"⬆ .. (up to {parent})</a>"
        )
    if not entries:
        parts.append(
            "<div class='px-3 py-3 text-xs' style='color:#8b949e;'>"
            + (
                "No storage volumes or custom mount points found at /. "
                "Use the Jump input above to navigate to a path directly."
                if at_root and not query
                else "No subdirectories" + (" matching filter" if query else "") + "."
            )
            + "</div>"
        )
    else:
        for name in entries:
            child_path = str(target / name).replace("\\", "/")
            parts.append(
                f"<a hx-get='/api/storage/browse?path={child_path}' "
                f"hx-target='#storage-browser' hx-swap='innerHTML' "
                f"class='block px-3 py-1.5 text-xs cursor-pointer hover:bg-gray-800 font-mono' "
                f"style='color:#e6edf3;border-bottom:1px solid #21262d;'>"
                f"📁 {name}</a>"
            )
    parts.append("</div>")

    # ── Quick-jump to known mount points (if at root or they are different) ──
    if str(target) == "/":
        locs = _quick_locations()
        if locs:
            parts.append(
                "<div class='text-xs pt-1' style='color:#8b949e;'>Quick jump to mount:</div>"
            )
            parts.append(
                "<div class='flex flex-wrap gap-1'>"
            )
            for loc in locs:
                loc_path = loc["path"]
                if loc_path == "/":
                    continue
                parts.append(
                    f"<a hx-get='/api/storage/browse?path={loc_path}' "
                    f"hx-target='#storage-browser' hx-swap='innerHTML' "
                    f"class='text-xs px-2 py-0.5 rounded cursor-pointer font-mono' "
                    f"style='background:#0d1117;color:#58a6ff;border:1px solid #30363d;'>"
                    f"{loc_path}</a>"
                )
            parts.append("</div>")

    parts.append("</div>")
    return "".join(parts)


def _jump_input_html(current_path: str, current_q: str) -> str:
    """Render the 'Jump to path' input row for the folder browser."""
    return (
        f"<div class='flex gap-1 items-center'>"
        f"<input type='text' id='browse-jump-input' "
        f"placeholder='Jump to any path…  e.g. /mnt/external or /external' "
        f"class='flex-1 rounded px-2 py-1 text-xs font-mono' "
        f"style='background:#0d1117;color:#e6edf3;border:1px solid #30363d;' "
        f"hx-get='/api/storage/browse' "
        f"hx-trigger='keydown[key==\"Enter\"]' "
        f"hx-target='#storage-browser' "
        f"hx-swap='innerHTML' "
        f"hx-vals='js:{{\"jump\": event.target.value}}' />"
        f"<button type='button' "
        f"onclick=\"htmx.ajax('GET','/api/storage/browse?jump='+document.getElementById('browse-jump-input').value,"
        f"{{target:'#storage-browser',swap:'innerHTML'}})\" "
        f"class='text-xs px-2 py-1 rounded' "
        f"style='background:#21262d;color:#58a6ff;border:1px solid #30363d;'>Go</button>"
        f"</div>"
    )


@app.get("/docs/external-storage")
def docs_external_storage():
    """Serve the External Storage Guide as a styled HTML page."""
    # docs/ lives at the project root, two levels up from this file
    guide_path = Path(__file__).resolve().parent.parent / "docs" / "EXTERNAL_STORAGE_GUIDE.md"
    try:
        text = guide_path.read_text(encoding="utf-8")
    except OSError:
        text = "External Storage Guide not found."
    # Minimal styled wrapper — no extra deps; render markdown as <pre>
    safe = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>External Storage Guide</title>"
        "<style>"
        "body{background:#0d1117;color:#e6edf3;font:14px/1.55 -apple-system,Segoe UI,sans-serif;"
        "max-width:860px;margin:2em auto;padding:1em 2em;}"
        "pre{white-space:pre-wrap;word-wrap:break-word;font:13px/1.55 'Cascadia Mono',Consolas,monospace;}"
        "code{background:#161b22;padding:1px 4px;border-radius:3px;}"
        "</style>"
        f"<pre>{safe}</pre>"
    )


# ===========================================================================
# Active downloads view — combines DB job state with on-disk file size.
# Lets the user see what's REALLY downloading right now (not stale rows).
# ===========================================================================
def _scan_video_dir_size(channel_name: str, video_id: str) -> tuple[int, Optional[float]]:
    """Return (total_bytes, latest_mtime_epoch) for a video's download dir.
    Returns (0, None) if the dir does not exist yet."""
    root = Path(os.getenv("DOWNLOADS_DIR", "/shared/downloads"))
    candidates = []
    if channel_name:
        # Try "<root>/<channel_name>/<video_id>" — sanitized version unknown,
        # so just try a few common shapes.
        candidates.append(root / channel_name / video_id)
        # Fallback: walk channel dir for matching video_id
    candidates.append(root / video_id)
    candidates.append(root / f"job_{video_id}")
    # Direct match first
    for d in candidates:
        try:
            if d.is_dir():
                total = 0
                latest = 0.0
                for p in d.iterdir():
                    try:
                        st = p.stat()
                        total += st.st_size
                        if st.st_mtime > latest:
                            latest = st.st_mtime
                    except OSError:
                        continue
                return total, (latest or None)
        except OSError:
            continue
    # Last resort: walk all channel dirs (slower)
    if channel_name:
        try:
            for chan_dir in root.iterdir():
                cand = chan_dir / video_id
                if cand.is_dir():
                    total = 0
                    latest = 0.0
                    for p in cand.iterdir():
                        try:
                            st = p.stat()
                            total += st.st_size
                            if st.st_mtime > latest:
                                latest = st.st_mtime
                        except OSError:
                            continue
                    return total, (latest or None)
        except OSError:
            pass
    return 0, None


def _format_bytes(n: int) -> str:
    if n is None or n <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def _format_age(secs: float) -> str:
    if secs is None:
        return "—"
    s = int(secs)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


@app.get("/partials/downloads/active")
def partial_downloads_active():
    """Live download view: shows what is ACTIVELY downloading right now
    based on disk activity, plus what's queued, plus stuck/orphaned rows.
    Refreshable; safe to poll every few seconds.
    """
    import time as _time
    now = _time.time()
    stale_threshold = int(request.args.get("stale_minutes", "10")) * 60

    # All non-terminal jobs joined with metadata
    rows = g.db.execute(
        """SELECT j.id AS job_id, j.status AS job_status,
                  j.source_file_path, j.error_message,
                  j.created_at AS j_created, j.updated_at AS j_updated,
                  v.youtube_video_id AS video_id,
                  v.original_title AS title,
                  COALESCE(cv.thumbnail_url, v.thumbnail_url) AS thumbnail_url,
                  COALESCE(cv.duration_sec, v.duration) AS duration_sec,
                  c.id AS channel_id, c.name AS channel_name,
                  dq.id AS dq_id, dq.status AS dq_status,
                  dq.triggered_by, dq.updated_at AS dq_updated
             FROM jobs j
             JOIN videos v ON v.id = j.video_id
             LEFT JOIN channels c ON c.id = v.channel_id
             LEFT JOIN catalog_videos cv ON cv.video_id = v.youtube_video_id
             LEFT JOIN download_queue dq ON dq.job_id = j.id
            WHERE j.status IN ('pending','downloading','downloaded','processing')
            ORDER BY j.updated_at DESC, j.id DESC
            LIMIT 200"""
    ).fetchall()

    active = []     # actually downloading right now (recent disk activity)
    queued = []     # waiting for a worker slot
    stuck = []      # job marked downloading but no recent activity (orphaned)
    completed_unfinished = []  # downloaded but processor hasn't moved them

    for r in rows:
        d = dict(r)
        # On-disk progress
        size_bytes, mtime = _scan_video_dir_size(d.get("channel_name") or "", d["video_id"])
        d["bytes_on_disk"] = size_bytes
        d["bytes_human"] = _format_bytes(size_bytes)
        d["last_disk_age_sec"] = (now - mtime) if mtime else None
        d["last_disk_age_human"] = _format_age(d["last_disk_age_sec"]) if mtime else "no files yet"

        # DB age
        try:
            from datetime import datetime as _dt
            db_ts = _dt.fromisoformat(d["j_updated"]).timestamp()
            d["db_age_sec"] = now - db_ts
        except (ValueError, TypeError):
            d["db_age_sec"] = None

        # Bucket
        if d["job_status"] in ("downloaded", "processing"):
            completed_unfinished.append(d)
        elif d["job_status"] == "downloading":
            # Active = disk file modified in last 90 seconds
            if mtime and (now - mtime) < 90:
                active.append(d)
            elif d["db_age_sec"] is not None and d["db_age_sec"] > stale_threshold:
                stuck.append(d)
            else:
                queued.append(d)
        else:  # pending
            queued.append(d)

    # Free worker slots
    try:
        ws = g.db.execute(
            "SELECT detail FROM worker_state WHERE worker_id='download_workers'"
        ).fetchone()
        max_workers = int(ws["detail"]) if ws and (ws["detail"] or "").isdigit() else 5
    except (TypeError, ValueError):
        max_workers = 5

    counts = {
        "active": len(active),
        "queued": len(queued),
        "stuck": len(stuck),
        "completed_unfinished": len(completed_unfinished),
        "max_workers": max_workers,
        "free_slots": max(0, max_workers - len(active)),
    }

    # Failed-job summary (terminal jobs whose dlq row is also failed —
    # i.e. eligible for one-click retry without disturbing intentional
    # abandons). Grouped by error_message for triage.
    failed_total = g.db.execute(
        """SELECT COUNT(*) FROM jobs j
            JOIN download_queue dq ON dq.job_id = j.id
           WHERE j.status='failed' AND dq.status='failed'"""
    ).fetchone()[0]
    failure_reasons = []
    if failed_total:
        failure_reasons = [dict(r) for r in g.db.execute(
            """SELECT COALESCE(NULLIF(j.error_message, ''), '(no message)') AS reason,
                      COUNT(*) AS n
                 FROM jobs j
                 JOIN download_queue dq ON dq.job_id = j.id
                WHERE j.status='failed' AND dq.status='failed'
             GROUP BY reason
             ORDER BY n DESC
             LIMIT 5"""
        ).fetchall()]
    counts["failed_total"] = failed_total

    # Global pause state
    try:
        _prow = g.db.execute(
            "SELECT detail FROM worker_state WHERE worker_id='queue_paused'"
        ).fetchone()
        queue_paused = bool(_prow and (_prow[0] or "0") == "1")
    except Exception:
        queue_paused = False

    return render_template(
        "partials/downloads_active.html",
        active=active, queued=queued, stuck=stuck,
        completed_unfinished=completed_unfinished,
        counts=counts,
        failure_reasons=failure_reasons,
        format_duration=_format_duration,
        queue_paused=queue_paused,
    )


@app.post("/downloads/active/cleanup-stuck")
def downloads_active_cleanup_stuck():
    """Mark jobs stuck in 'downloading' for > N minutes as failed and
    reset their download_queue rows to pending so the hydrator re-creates
    fresh jobs. Called by the 'Clean stuck' button on the Monitor tab."""
    minutes = int(request.form.get("minutes") or 30)
    minutes = max(5, min(minutes, 1440))
    cur = g.db.execute(
        f"""UPDATE jobs
              SET status = 'failed',
                  error_message = 'auto-marked stuck (no progress > {minutes}m)',
                  updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE status = 'downloading'
              AND (julianday('now') - julianday(updated_at)) * 24 * 60 > ?""",
        (minutes,),
    )
    cleaned = cur.rowcount
    # Reset matching DLQ rows back to pending so they re-hydrate fresh
    g.db.execute(
        """UPDATE download_queue
              SET status='pending', job_id=NULL,
                  error_message='auto-reset after stuck cleanup',
                  updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE status='downloading'
              AND job_id IN (
                SELECT id FROM jobs
                 WHERE status='failed'
                   AND error_message LIKE 'auto-marked stuck%'
              )"""
    )
    g.db.commit()
    return (
        f"<span style='color:#3fb950;font-size:11px;font-weight:600;'>"
        f"\u2713 cleaned {cleaned} stuck job(s)</span>",
        200,
    )


@app.post("/downloads/active/retry-failed")
def downloads_active_retry_failed():
    """Bulk-retry every failed job whose download_queue row is also 'failed'.

    Mirrors the per-row Retry path: retires the old job (audit trail),
    resets the dlq row to 'pending' with job_id=NULL so the watcher's
    hydrator picks it up and creates a fresh job. Does NOT delete on-disk
    files (yt-dlp will overwrite/resume on next attempt).

    Optional form arg: error_substr — limit retry to jobs whose
    error_message contains this substring (used by the failure-reasons
    grouping to allow targeted retries).
    """
    substr = (request.form.get("error_substr") or "").strip()
    if substr:
        rows = g.db.execute(
            """SELECT j.id AS job_id, dq.id AS dq_id
                 FROM jobs j
                 JOIN download_queue dq ON dq.job_id = j.id
                WHERE j.status='failed' AND dq.status='failed'
                  AND COALESCE(j.error_message,'') LIKE ?""",
            (f"%{substr}%",),
        ).fetchall()
    else:
        rows = g.db.execute(
            """SELECT j.id AS job_id, dq.id AS dq_id
                 FROM jobs j
                 JOIN download_queue dq ON dq.job_id = j.id
                WHERE j.status='failed' AND dq.status='failed'"""
        ).fetchall()

    if not rows:
        return (
            "<span style='color:#8b949e;font-size:11px;'>nothing to retry</span>",
            200,
        )

    job_ids = [r["job_id"] for r in rows]
    dq_ids  = [r["dq_id"]  for r in rows]

    # Retire old jobs (audit trail).
    g.db.executemany(
        """UPDATE jobs
              SET error_message = COALESCE(error_message,'') || ' | retried by user',
                  updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = ?""",
        [(jid,) for jid in job_ids],
    )
    # Reset DLQ rows to pending so the hydrator re-creates fresh jobs.
    g.db.executemany(
        """UPDATE download_queue
              SET status='pending', job_id=NULL,
                  error_message='retried by user',
                  updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = ?""",
        [(did,) for did in dq_ids],
    )
    g.db.commit()
    return (
        f"<span style='color:#3fb950;font-size:11px;font-weight:600;'>"
        f"\u21bb requeued {len(rows)} failed job(s)</span>",
        200,
    )


@app.post("/downloads/active/clean-and-rescan")
def downloads_active_clean_and_rescan():
    """Nuke failed downloads and re-queue every catalog video that is not
    yet successfully downloaded.

    Steps (all in one DB transaction + best-effort disk cleanup):
      1. Collect every failed job's video_id.
      2. Delete partial download folders for those videos (safe: scoped to
         DOWNLOADS_DIR + filtered by video_id, no shell expansion).
      3. Delete the failed download_queue rows AND their failed jobs (full
         wipe — a fresh hydrator pass will create new ones).
      4. For every catalog_videos row that has no successful download
         (no job in 'downloaded'/'done'/'processed'/'processing' AND no
         dlq row in 'pending'/'hydrated'/'downloading'/'complete'), insert
         a fresh download_queue 'pending' row.

    Optional form arg: source_id — limit to a single source.
    """
    src_raw = request.form.get("source_id")
    source_id = int(src_raw) if (src_raw or "").isdigit() else None

    # 1. Collect failed video_ids (scoped to source if given).
    if source_id:
        failed_rows = g.db.execute(
            """SELECT DISTINCT v.youtube_video_id AS vid, c.name AS chan
                 FROM jobs j
                 JOIN videos v ON v.id = j.video_id
                 LEFT JOIN channels c ON c.id = v.channel_id
                 JOIN download_queue dq ON dq.job_id = j.id
                WHERE j.status='failed' AND dq.status='failed'
                  AND dq.source_id = ?""",
            (source_id,),
        ).fetchall()
    else:
        failed_rows = g.db.execute(
            """SELECT DISTINCT v.youtube_video_id AS vid, c.name AS chan
                 FROM jobs j
                 JOIN videos v ON v.id = j.video_id
                 LEFT JOIN channels c ON c.id = v.channel_id
                 JOIN download_queue dq ON dq.job_id = j.id
                WHERE j.status='failed' AND dq.status='failed'"""
        ).fetchall()

    # 2. Delete partial folders. Bounded to DOWNLOADS_DIR via .resolve()
    #    + relative_to() check (path traversal defense).
    import shutil
    root = Path(os.getenv("DOWNLOADS_DIR", "/shared/downloads")).resolve()
    deleted_dirs = 0
    for r in failed_rows:
        vid = r["vid"]
        chan = r["chan"] or ""
        candidates = []
        if chan:
            candidates.append(root / chan / vid)
        candidates.append(root / vid)
        for d in candidates:
            try:
                d_resolved = d.resolve()
                d_resolved.relative_to(root)  # raises if outside
                if d_resolved.is_dir():
                    shutil.rmtree(d_resolved)
                    deleted_dirs += 1
                    break
            except (ValueError, OSError):
                continue

    # 3. Wipe failed dlq rows + failed jobs (scoped if requested).
    if source_id:
        cur_dq = g.db.execute(
            """DELETE FROM download_queue
                WHERE status='failed' AND source_id = ?""",
            (source_id,),
        )
    else:
        cur_dq = g.db.execute(
            "DELETE FROM download_queue WHERE status='failed'"
        )
    wiped_dq = cur_dq.rowcount
    # Orphaned failed jobs (no dlq link or dlq already gone).
    cur_j = g.db.execute(
        """DELETE FROM jobs
            WHERE status='failed'
              AND id NOT IN (SELECT job_id FROM download_queue WHERE job_id IS NOT NULL)"""
    )
    wiped_jobs = cur_j.rowcount

    # 4. Re-queue missing catalog videos.
    if source_id:
        missing = g.db.execute(
            """SELECT cv.video_id, cv.source_id
                 FROM catalog_videos cv
                WHERE cv.source_id = ?
                  AND cv.unavailable_at IS NULL
                  AND cv.ignored = 0
                  AND NOT EXISTS (
                        SELECT 1 FROM download_queue dq
                         WHERE dq.video_id = cv.video_id
                           AND dq.status IN ('pending','hydrated','downloading','complete','processing')
                  )""",
            (source_id,),
        ).fetchall()
    else:
        missing = g.db.execute(
            """SELECT cv.video_id, cv.source_id
                 FROM catalog_videos cv
                WHERE cv.unavailable_at IS NULL
                  AND cv.ignored = 0
                  AND NOT EXISTS (
                        SELECT 1 FROM download_queue dq
                         WHERE dq.video_id = cv.video_id
                           AND dq.status IN ('pending','hydrated','downloading','complete','processing')
                  )"""
        ).fetchall()

    queued = 0
    for m in missing:
        cur = g.db.execute(
            """INSERT OR IGNORE INTO download_queue
                    (video_id, source_id, status, triggered_by)
               VALUES (?, ?, 'pending', 'rescan')""",
            (m["video_id"], m["source_id"]),
        )
        if cur.rowcount > 0:
            queued += 1
    g.db.commit()

    return (
        f"<span style='color:#3fb950;font-size:11px;font-weight:600;'>"
        f"\u2713 wiped {wiped_dq} dlq + {wiped_jobs} job(s), "
        f"deleted {deleted_dirs} folder(s), queued {queued} missing video(s)"
        f"</span>",
        200,
    )


@app.post("/downloads/active/cancel-job/<int:job_id>")
def downloads_active_cancel_job(job_id: int):
    """Cancel a single in-flight job. Marks job + DLQ as failed."""
    g.db.execute(
        """UPDATE jobs
              SET status='failed', error_message='canceled by user',
                  updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = ? AND status IN ('pending','downloading','downloaded','processing')""",
        (job_id,),
    )
    g.db.execute(
        """UPDATE download_queue
              SET status='failed', error_message='canceled by user',
                  updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE job_id = ? AND status NOT IN ('complete','failed')""",
        (job_id,),
    )
    g.db.commit()
    return (
        "<span style='color:#f85149;font-size:11px;font-weight:600;'>\u2716 canceled</span>",
        200,
    )


@app.get("/partials/downloads/live")
def partial_downloads_live():
    """Live download progress panel — called every 4s via HTMX polling."""
    # Active rows: pending, hydrated, downloading
    active = g.db.execute(
        """SELECT dq.id, dq.video_id, dq.status, dq.triggered_by,
                  dq.created_at, dq.updated_at, dq.job_id, dq.error_message,
                  j.status AS job_status,
                  COALESCE(cv.title, v.original_title, dq.video_id) AS title,
                  cv.thumbnail_url,
                  cv.duration_sec,
                  COALESCE(s.name, '?') AS source_label
             FROM download_queue dq
             LEFT JOIN jobs j          ON j.id = dq.job_id
             LEFT JOIN catalog_videos cv ON cv.video_id = dq.video_id
             LEFT JOIN videos v        ON v.youtube_video_id = dq.video_id
             LEFT JOIN sources s       ON s.id = dq.source_id
            WHERE dq.status IN ('pending', 'hydrated', 'downloading')
            ORDER BY CASE dq.status
                       WHEN 'downloading' THEN 0
                       WHEN 'hydrated'    THEN 1
                       ELSE 2 END,
                     dq.id ASC
            LIMIT 50"""
    ).fetchall()
    # Recent completed (last 20)
    recent = g.db.execute(
        """SELECT dq.id, dq.video_id, dq.status, dq.triggered_by,
                  dq.updated_at, dq.job_id, dq.error_message,
                  COALESCE(cv.title, v.original_title, dq.video_id) AS title,
                  cv.thumbnail_url
             FROM download_queue dq
             LEFT JOIN catalog_videos cv ON cv.video_id = dq.video_id
             LEFT JOIN videos v          ON v.youtube_video_id = dq.video_id
            WHERE dq.status IN ('complete', 'failed')
            ORDER BY dq.updated_at DESC, dq.id DESC
            LIMIT 20"""
    ).fetchall()
    # Counts
    counts = {
        r["status"]: int(r["n"])
        for r in g.db.execute(
            "SELECT status, COUNT(*) n FROM download_queue GROUP BY status"
        ).fetchall()
    }
    # Watcher logs (last 30 lines)
    log_lines = _read_container_logs(WATCHER_CONTAINER, 30)
    return render_template(
        "partials/downloads_live.html",
        active=[dict(r) for r in active],
        recent=[dict(r) for r in recent],
        counts=counts,
        log_lines=log_lines,
        format_duration=_format_duration,
    )


@app.get("/partials/downloads/stats")
def partial_downloads_stats():
    """Live job counts summary bar for the Downloads tab header."""
    rows = g.db.execute(
        """SELECT status, COUNT(*) AS n FROM jobs
            WHERE status IN (
              'pending','downloading','downloaded',
              'processing','processed','uploading',
              'failed','partial'
            )
            GROUP BY status"""
    ).fetchall()
    counts: dict = {r["status"]: r["n"] for r in rows}
    # Aggregate 'done' from processed/downloaded that are terminal successes
    done_rows = g.db.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status='done'"
    ).fetchone()
    counts["done"] = (done_rows["n"] if done_rows else 0)
    return render_template("partials/downloads_stats.html", counts=counts)


@app.get("/partials/downloads/sources")
def partial_downloads_sources():
    selected_pipeline_id = request.args.get("pipeline_id", type=int)
    return render_template(
        "partials/downloads_sources.html",
        channels=_channels_with_stats(selected_pipeline_id),
        selected_pipeline_id=selected_pipeline_id,
    )


@app.get("/partials/downloads/files")
def partial_downloads_files():
    rel = request.args.get("path", "")
    return render_template(
        "partials/downloads_files.html",
        listing=_list_downloads_dir(rel),
    )


_DOWNLOADS_JOBS_SQL = """
    SELECT j.id, j.status, j.source_file_path, j.error_message,
           j.retry_count, j.created_at, j.updated_at,
           v.youtube_video_id, v.original_title, v.source_url,
           v.duration AS v_duration,
           v.published_at AS v_published_at,
           v.thumbnail_url AS v_thumbnail,
           v.view_count   AS v_view_count,
           v.like_count   AS v_like_count,
           c.name AS channel_name, c.id AS channel_id,
           p.name AS pipeline_name,
           (SELECT cv.upload_date FROM catalog_videos cv
             WHERE cv.video_id = v.youtube_video_id
             ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_upload_date,
           (SELECT cv.view_count FROM catalog_videos cv
             WHERE cv.video_id = v.youtube_video_id
             ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_view_count,
           (SELECT cv.like_count FROM catalog_videos cv
             WHERE cv.video_id = v.youtube_video_id
             ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_like_count,
           (SELECT cv.duration_sec FROM catalog_videos cv
             WHERE cv.video_id = v.youtube_video_id
             ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_duration_sec,
           (SELECT cv.thumbnail_url FROM catalog_videos cv
             WHERE cv.video_id = v.youtube_video_id
             ORDER BY cv.last_seen_at DESC LIMIT 1) AS cv_thumbnail,
           (SELECT dq.progress_pct FROM download_queue dq
             WHERE dq.video_id = v.youtube_video_id LIMIT 1) AS dq_progress_pct,
           (SELECT dq.progress_detail FROM download_queue dq
             WHERE dq.video_id = v.youtube_video_id LIMIT 1) AS dq_progress_detail,
           (SELECT l.status FROM upload_ledger l
             WHERE l.video_id = v.youtube_video_id
             ORDER BY l.uploaded_at DESC LIMIT 1) AS upload_status
      FROM jobs j
      JOIN videos v ON v.id = j.video_id
      LEFT JOIN channels c ON c.id = v.channel_id
      LEFT JOIN pipelines p ON p.id = j.pipeline_id
     WHERE j.status IN ('pending','downloading','downloaded',
                        'processing','processed','uploading',
                        'failed','partial')
     ORDER BY
       CASE j.status
         WHEN 'downloading' THEN 0
         WHEN 'uploading'   THEN 1
         WHEN 'processing'  THEN 2
         WHEN 'pending'     THEN 3
         WHEN 'downloaded'  THEN 4
         WHEN 'processed'   THEN 5
         WHEN 'partial'     THEN 6
         WHEN 'failed'      THEN 7
         ELSE 99
       END,
       j.id DESC
     LIMIT 100
"""


def _query_downloads_jobs(conn):
    rows = conn.execute(_DOWNLOADS_JOBS_SQL).fetchall()
    return [_enrich_download_job(dict(r)) for r in rows]


@app.get("/partials/downloads/jobs")
def partial_downloads_jobs():
    """Active + recent jobs across all pipelines."""
    return render_template(
        "partials/downloads_jobs.html",
        jobs=_query_downloads_jobs(g.db),
    )


@app.get("/partials/downloads/tick")
def partial_downloads_tick():
    """Combined 5s poll target for the Downloads page.

    Replaces the two separate polls (`/partials/downloads/active` and
    `/partials/downloads/jobs`) with a single request that returns the
    active panel as the primary swap and the jobs panel as an htmx OOB
    swap (`hx-swap-oob="innerHTML"`). Halves the per-tick HTTP traffic.
    Both fragment endpoints remain available for manual refresh / direct
    callers.
    """
    active_html = partial_downloads_active()
    jobs_html = render_template(
        "partials/downloads_jobs.html",
        jobs=_query_downloads_jobs(g.db),
    )
    return (
        active_html
        + '<div id="downloads-jobs" hx-swap-oob="innerHTML">'
        + jobs_html
        + "</div>"
    )


def _fmt_bytes(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024.0
        i += 1
    return f"{f:.1f} {units[i]}" if i else f"{int(f)} {units[i]}"


def _fmt_duration(sec):
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_views(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _fmt_upload_date(s):
    """Accept 'YYYY-MM-DD' or ISO timestamp; return 'YYYY-MM-DD'."""
    if not s:
        return ""
    s = str(s)
    return s[:10]


# Tiny in-process cache: avoids re-reading the same .info.json on every
# render. Keyed by absolute file path; entries are small dicts.
# Bounded LRU to prevent unbounded growth as catalog scales: oldest entries
# are evicted when we exceed _VIDEO_META_CACHE_MAX. Tracked insertion order
# via the dict itself (Python 3.7+ preserves insertion order).
_VIDEO_META_CACHE: dict[str, dict] = {}
_VIDEO_META_CACHE_MAX = 2048


def _probe_video_meta(abs_file_path: str) -> dict:
    """Read width/height/codec/container from a sibling `.info.json`.

    Returns ``{"resolution": "1080p", "format": "MP4", "vcodec": "...", ...}``
    with empty strings for any missing fields. Safe to call with a missing
    path or a missing info file.
    """
    if not abs_file_path:
        return {}
    cached = _VIDEO_META_CACHE.get(abs_file_path)
    if cached is not None:
        return cached
    out: dict = {}
    try:
        d = os.path.dirname(abs_file_path)
        if d and os.path.isdir(d):
            for name in os.listdir(d):
                if name.endswith(".info.json"):
                    with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                        info = json.load(f)
                    h = info.get("height") or 0
                    w = info.get("width") or 0
                    ext = (info.get("ext") or "").upper()
                    vcodec = (info.get("vcodec") or "").split(".")[0] or ""
                    if h:
                        out["resolution"] = f"{int(h)}p"
                    elif w:
                        out["resolution"] = f"{int(w)}w"
                    if ext:
                        out["format"] = ext
                    if vcodec and vcodec != "none":
                        out["vcodec"] = vcodec
                    out["res_long"] = (
                        f"{int(w)}x{int(h)}" if w and h else ""
                    )
                    break
        # Fallback from filename extension only.
        if "format" not in out and abs_file_path:
            ext = os.path.splitext(abs_file_path)[1].lstrip(".").upper()
            if ext:
                out["format"] = ext
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    # LRU eviction: drop oldest entry once we exceed cap. Keeps memory
    # bounded under churn (e.g. catalog browsing across thousands of videos).
    if len(_VIDEO_META_CACHE) >= _VIDEO_META_CACHE_MAX:
        try:
            _VIDEO_META_CACHE.pop(next(iter(_VIDEO_META_CACHE)))
        except StopIteration:
            pass
    _VIDEO_META_CACHE[abs_file_path] = out
    return out


def _enrich_download_job(j):
    """Add display-ready fields to a job row dict."""
    # Best metadata wins (catalog hydration is freshest).
    j["disp_duration"] = _fmt_duration(
        j.get("cv_duration_sec") or j.get("v_duration")
    )
    j["disp_views"] = _fmt_views(
        j.get("v_view_count") if j.get("v_view_count") is not None
        else j.get("cv_view_count")
    )
    j["disp_likes"] = _fmt_views(
        j.get("v_like_count") if j.get("v_like_count") is not None
        else j.get("cv_like_count")
    )
    j["disp_upload_date"] = _fmt_upload_date(
        j.get("cv_upload_date") or j.get("v_published_at")
    )
    j["disp_thumb"] = j.get("cv_thumbnail") or j.get("v_thumbnail") or ""
    if j.get("upload_status") == "uploaded" and j.get("status") in ("done", "downloaded", "processed"):
        j["display_status"] = "uploaded"
    else:
        j["display_status"] = j.get("status")
    # File size from disk if the file is materialized.
    size_bytes = 0
    fp = j.get("source_file_path") or ""
    if fp:
        downloads_root = os.getenv("DOWNLOADS_DIR", "/shared/downloads")
        if fp.startswith("/downloads/"):
            local = downloads_root.rstrip("/") + fp[len("/downloads"):]
        elif not os.path.isabs(fp):
            local = os.path.join(downloads_root, fp)
        else:
            local = fp
        try:
            if os.path.isfile(local):
                size_bytes = os.path.getsize(local)
        except OSError:
            size_bytes = 0
    j["disp_size"] = _fmt_bytes(size_bytes)
    j["disp_size_bytes"] = size_bytes
    # Short relative timestamp for "Updated".
    j["disp_updated"] = (j.get("updated_at") or "")[:19].replace("T", " ")
    j["disp_created"] = (j.get("created_at") or "")[:19].replace("T", " ")
    return j


@app.post("/api/downloads/pause")
def api_downloads_pause():
    """Pause all downloads globally (watcher stops starting new jobs)."""
    g.db.execute(
        """INSERT INTO worker_state
               (worker_id, kind, status, detail, last_beat, started_at, pid, host)
           VALUES ('queue_paused','setting','idle','1',
                   strftime('%Y-%m-%dT%H:%M:%S','now'),
                   strftime('%Y-%m-%dT%H:%M:%S','now'),0,'')
           ON CONFLICT(worker_id) DO UPDATE
               SET detail=excluded.detail, last_beat=excluded.last_beat""",
    )
    g.db.commit()
    return ("", 204)


@app.post("/api/downloads/resume")
def api_downloads_resume():
    """Resume all downloads globally."""
    g.db.execute(
        """INSERT INTO worker_state
               (worker_id, kind, status, detail, last_beat, started_at, pid, host)
           VALUES ('queue_paused','setting','idle','0',
                   strftime('%Y-%m-%dT%H:%M:%S','now'),
                   strftime('%Y-%m-%dT%H:%M:%S','now'),0,'')
           ON CONFLICT(worker_id) DO UPDATE
               SET detail=excluded.detail, last_beat=excluded.last_beat""",
    )
    g.db.commit()
    return ("", 204)


@app.post("/downloads/channels/<int:channel_id>/toggle-active")
def downloads_toggle_active(channel_id: int):
    """Pause or resume a single channel (flips channels.active)."""
    chan = g.db.execute(
        "SELECT id, active FROM channels WHERE id = ?",
        (channel_id,),
    ).fetchone()
    if not chan:
        return ("Channel not found", 404)
    new_val = 0 if int(chan["active"] or 1) else 1
    g.db.execute(
        "UPDATE channels SET active = ? WHERE id = ?",
        (new_val, channel_id),
    )
    g.db.commit()
    selected_pipeline_id = request.form.get("pipeline_id", type=int)
    return render_template(
        "partials/downloads_sources.html",
        channels=_channels_with_stats(selected_pipeline_id),
        selected_pipeline_id=selected_pipeline_id,
        flash=(f"Channel #{channel_id} is now "
               f"{'ACTIVE — watcher will pick it up next cycle' if new_val else 'PAUSED — watcher will skip it'}."),
    )


@app.post("/downloads/channels/<int:channel_id>/toggle-unlimited")
def downloads_toggle_unlimited(channel_id: int):
    """Flip the per-channel ``download_unlimited`` flag (0/1).

    When ON the watcher drains the entire backfill queue every cycle and
    ignores the channel's daily_limit. When OFF the daily cap applies as
    before. Returns the refreshed channel-card grid.
    """
    chan = g.db.execute(
        "SELECT id, download_unlimited FROM channels WHERE id = ?",
        (channel_id,),
    ).fetchone()
    if not chan:
        return ("Channel not found", 404)
    new_val = 0 if int(chan["download_unlimited"] or 0) else 1
    g.db.execute(
        "UPDATE channels SET download_unlimited = ? WHERE id = ?",
        (new_val, channel_id),
    )
    g.db.commit()
    selected_pipeline_id = request.form.get("pipeline_id", type=int)
    return render_template(
        "partials/downloads_sources.html",
        channels=_channels_with_stats(selected_pipeline_id),
        selected_pipeline_id=selected_pipeline_id,
        flash=(f"Channel #{channel_id}: download cap is now "
               f"{'UNLIMITED' if new_val else 'enforced'}."),
    )


@app.post("/downloads/channels/<int:channel_id>/priority")
def downloads_set_channel_priority(channel_id: int):
    """Set per-channel download priority (lower number = higher priority)."""
    _ensure_channel_priority_column()
    chan = g.db.execute(
        "SELECT id FROM channels WHERE id = ?",
        (channel_id,),
    ).fetchone()
    if not chan:
        return ("Channel not found", 404)

    try:
        priority = int(request.form.get("priority") or 100)
    except (TypeError, ValueError):
        priority = 100
    priority = max(1, min(priority, 9999))

    g.db.execute(
        "UPDATE channels SET download_priority = ? WHERE id = ?",
        (priority, channel_id),
    )
    g.db.commit()

    selected_pipeline_id = request.form.get("pipeline_id", type=int)
    return render_template(
        "partials/downloads_sources.html",
        channels=_channels_with_stats(selected_pipeline_id),
        selected_pipeline_id=selected_pipeline_id,
        flash=f"Priority updated for channel #{channel_id}: {priority}.",
    )


@app.post("/downloads/trigger/<int:channel_id>")
def downloads_trigger_channel(channel_id: int):
    """Queue up to ``count`` items from a channel into download_queue.

    Order priority:
      1. If `catalog_videos` rows exist for this channel's source, use them
         (sorted by upload_date asc/desc per `direction`). This is the most
         reliable ordering since each row has a verified upload_date.
      2. Else use the channel's stored backfill_queue (slice from front
         for 'newest', from back for 'oldest').
      3. Else fall back to a fresh yt-dlp scan (uses `playlistreverse` for
         oldest-first).

    Form params:
      count      int   1..50          (default 5)
      direction  str   'newest'|'oldest'   (default 'newest')
    """
    try:
        count = int(request.form.get("count") or request.args.get("count") or 5)
    except (TypeError, ValueError):
        count = 5
    count = max(1, min(500, count))

    direction = (request.form.get("direction")
                 or request.args.get("direction") or "newest").lower()
    if direction not in ("newest", "oldest"):
        direction = "newest"

    chan = g.db.execute(
        "SELECT * FROM channels WHERE id = ?", (channel_id,)
    ).fetchone()
    if not chan:
        return ("Channel not found", 404)

    # Find or create the matching `sources` row up front so we can also
    # query its catalog if available.
    src = g.db.execute(
        "SELECT id FROM sources WHERE external_id = ? OR url = ? LIMIT 1",
        (chan["channel_id"], chan["url"]),
    ).fetchone()
    if not src:
        cur = g.db.execute(
            """INSERT INTO sources (kind, url, external_id, name, pipeline_id)
               VALUES ('channel', ?, ?, ?, ?)""",
            (chan["url"], chan["channel_id"], chan["name"], chan["pipeline_id"]),
        )
        source_id = cur.lastrowid
    else:
        source_id = src["id"]
        g.db.execute(
            "UPDATE sources SET pipeline_id = COALESCE(pipeline_id, ?) WHERE id = ?",
            (chan["pipeline_id"], source_id),
        )

    ids: list[str] = []
    order_source = ""

    # ---- Preferred: catalog_videos with verified upload_date -------------
    sql_order = "ASC" if direction == "oldest" else "DESC"
    cat_rows = g.db.execute(
        f"""SELECT video_id FROM catalog_videos
            WHERE source_id = ?
              AND unavailable_at IS NULL
              AND ignored = 0
              AND NOT EXISTS (
                SELECT 1 FROM upload_ledger l
                 WHERE l.video_id = catalog_videos.video_id
                   AND l.status IN ('uploaded','queued','uploading')
              )
              AND NOT EXISTS (
                SELECT 1 FROM download_queue dq
                 LEFT JOIN jobs j ON j.id = dq.job_id
                 WHERE dq.video_id = catalog_videos.video_id
                   AND (dq.status IN ('pending','hydrated','downloading','processing','complete')
                        OR j.status IN ('done','processed'))
              )
            ORDER BY COALESCE(upload_date, '0000-00-00') {sql_order}, id {sql_order}
            LIMIT ?""",
        (source_id, max(count * 3, count + 50)),  # pull more than needed; we re-filter below
    ).fetchall()
    if cat_rows:
        ids = [r["video_id"] for r in cat_rows]
        order_source = "catalog"

    # ---- Fallback: stored backfill_queue --------------------------------
    if not ids:
        try:
            stored = json.loads(chan["backfill_queue"] or "[]")
        except (json.JSONDecodeError, TypeError):
            stored = []
        if stored:
            if direction == "oldest":
                ids = list(reversed(stored))
            else:
                ids = list(stored)
            order_source = "backfill_queue"

    # ---- Last resort: live yt-dlp flat scan -----------------------------
    if not ids:
        try:
            import yt_dlp as _ytdlp
            opts = {
                "extract_flat": True, "quiet": True, "no_warnings": True,
                "playlist_items": f"1:{count}",
                "playlistreverse": (direction == "oldest"),
            }
            with _ytdlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(chan["url"], download=False) or {}
            ids = [e.get("id") for e in (info.get("entries") or [])
                   if e and e.get("id")]
            order_source = "yt-dlp scan"
        except Exception as e:                                   # noqa: BLE001
            return (f"yt-dlp scan failed: {e}", 502)

    enqueued = 0
    skipped = 0
    for vid in ids[:count]:
        # Skip if a non-failed ledger row already exists.
        existing = g.db.execute(
            """SELECT 1 FROM upload_ledger
                WHERE video_id = ? AND status IN ('uploaded','queued','uploading')
                LIMIT 1""",
            (vid,),
        ).fetchone()
        if existing:
            skipped += 1
            continue
        cur = g.db.execute(
            """INSERT OR IGNORE INTO download_queue
                    (video_id, source_id, status, triggered_by)
               VALUES (?, ?, 'pending', 'manual')""",
            (vid, source_id),
        )
        if cur.rowcount > 0:
            enqueued += 1
        else:
            skipped += 1
    g.db.commit()

    direction_label = "oldest first" if direction == "oldest" else "newest first"
    selected_pipeline_id = request.form.get("pipeline_id", type=int)
    return render_template(
        "partials/downloads_sources.html",
        channels=_channels_with_stats(selected_pipeline_id),
        selected_pipeline_id=selected_pipeline_id,
        flash=(f"Queued {enqueued} video(s) for '{chan['name']}' "
               f"[{direction_label}, source: {order_source}]"
               + (f" ({skipped} skipped)" if skipped else "")),
    )


# ===========================================================================
# Channel-videos browser (Videos sub-tab)
# ===========================================================================
def _resolve_channel_source_id(chan_row) -> Optional[int]:
    """Return ``channels.source_id``, lazily creating/linking on first use.

    Since the channels↔sources FK migration, every channels row has a
    ``source_id``. This helper exists only as a safety net for legacy rows
    that pre-date the migration: it canonicalises the URL via
    ``parse_source_url``, finds (or creates) the matching sources row,
    persists the FK, and returns the id.
    """
    # Fast path — FK already set by migration.
    try:
        sid = chan_row["source_id"]
    except (KeyError, IndexError):
        sid = None
    if sid:
        return sid

    try:
        from dashboard.sources import parse_source_url, SourceUrlError  # noqa: WPS433
    except ImportError:
        from sources import parse_source_url, SourceUrlError  # noqa: WPS433

    raw_url = chan_row["url"] or ""
    try:
        _kind, _ext, canonical_url = parse_source_url(raw_url)
    except SourceUrlError:
        canonical_url = raw_url

    src = g.db.execute(
        "SELECT id, url FROM sources "
        "WHERE external_id = ? OR url = ? OR url = ? LIMIT 1",
        (chan_row["channel_id"], canonical_url, raw_url),
    ).fetchone()
    if src:
        if canonical_url and src["url"] != canonical_url:
            g.db.execute(
                "UPDATE sources SET url = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%S','now') "
                "WHERE id = ?",
                (canonical_url, src["id"]),
            )
        src_id = src["id"]
    else:
        cur = g.db.execute(
            """INSERT INTO sources (kind, url, external_id, name, pipeline_id)
               VALUES ('channel', ?, ?, ?, ?)""",
            (canonical_url, chan_row["channel_id"],
             chan_row["name"], chan_row["pipeline_id"]),
        )
        src_id = cur.lastrowid

    # Persist the FK so future calls hit the fast path.
    g.db.execute(
        "UPDATE channels SET source_id = ? WHERE id = ?",
        (src_id, chan_row["id"]),
    )
    g.db.commit()
    return src_id


@app.get("/partials/downloads/channel-videos")
def partial_downloads_channel_videos():
    """List videos for one channel with per-row download buttons."""
    channel_id = request.args.get("channel_id", type=int)
    if not channel_id:
        return ("<p style='color:#8b949e'>Pick a channel above to see its videos.</p>", 200)

    chan = g.db.execute(
        "SELECT * FROM channels WHERE id = ?", (channel_id,)
    ).fetchone()
    if not chan:
        return ("Channel not found", 404)

    order = (request.args.get("order") or "newest").lower()
    if order not in ("newest", "oldest"):
        order = "newest"
    sql_order = "ASC" if order == "oldest" else "DESC"

    try:
        page = max(int(request.args.get("page", "1")), 1)
        per_page = min(max(int(request.args.get("per_page", "50")), 1), 200)
    except ValueError:
        page, per_page = 1, 50
    offset = (page - 1) * per_page

    src_id = _resolve_channel_source_id(chan)

    total = g.db.execute(
        "SELECT COUNT(*) FROM catalog_videos WHERE source_id = ? "
        "AND unavailable_at IS NULL AND ignored = 0",
        (src_id,),
    ).fetchone()[0]

    rows = g.db.execute(
        f"""SELECT c.id, c.video_id, c.title, c.duration_sec,
                  c.upload_date, c.thumbnail_url, c.view_count,
                  (SELECT 1 FROM download_queue dq
                    LEFT JOIN jobs j ON j.id = dq.job_id
                    WHERE dq.video_id = c.video_id
                      AND (dq.status = 'complete' OR j.status IN ('done','processed'))
                    LIMIT 1) AS is_downloaded,
                  (SELECT dq.status FROM download_queue dq
                    WHERE dq.video_id = c.video_id
                    ORDER BY dq.id DESC LIMIT 1) AS dlq_status,
                  (SELECT j.status FROM download_queue dq
                    LEFT JOIN jobs j ON j.id = dq.job_id
                    WHERE dq.video_id = c.video_id
                    ORDER BY dq.id DESC LIMIT 1) AS job_status,
                  (SELECT dq.id FROM download_queue dq
                    LEFT JOIN jobs j ON j.id = dq.job_id
                    WHERE dq.video_id = c.video_id
                      AND (dq.status = 'failed' OR j.status = 'failed')
                    ORDER BY dq.id DESC LIMIT 1) AS failed_dlq_id,
                  (SELECT l.status FROM upload_ledger l
                    WHERE l.video_id = c.video_id
                    ORDER BY l.created_at DESC LIMIT 1) AS upload_status,
                  (SELECT 1 FROM videos v WHERE v.youtube_video_id = c.video_id LIMIT 1) AS has_history
             FROM catalog_videos c
            WHERE c.source_id = ?
              AND c.unavailable_at IS NULL
              AND c.ignored = 0
            ORDER BY COALESCE(c.upload_date, '0000-00-00') {sql_order},
                     c.id {sql_order}
            LIMIT ? OFFSET ?""",
        (src_id, per_page, offset),
    ).fetchall()

    return render_template(
        "partials/downloads_channel_videos.html",
        channel=dict(chan),
        rows=[dict(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
        order=order,
        has_more=offset + len(rows) < total,
        format_duration=_format_duration,
        format_views=_format_views,
    )


@app.post("/downloads/queue-video/<int:channel_id>/<video_id>")
def downloads_queue_single_video(channel_id: int, video_id: str):
    """Queue ONE specific video for download."""
    if not video_id or len(video_id) > 32:
        return ("Bad video_id", 400)

    chan = g.db.execute(
        "SELECT * FROM channels WHERE id = ?", (channel_id,)
    ).fetchone()
    if not chan:
        return ("Channel not found", 404)

    src_id = _resolve_channel_source_id(chan)

    # Skip if already in upload ledger as non-failed
    existing_ul = g.db.execute(
        """SELECT 1 FROM upload_ledger
            WHERE video_id = ? AND status IN ('uploaded','queued','uploading') LIMIT 1""",
        (video_id,),
    ).fetchone()
    if existing_ul:
        return ("<span style='color:#d29922;font-size:11px;'>already in ledger</span>", 200)

    force_download = request.args.get("force") == "1"
    history_exists = g.db.execute(
        "SELECT 1 FROM videos WHERE youtube_video_id = ? LIMIT 1",
        (video_id,),
    ).fetchone()
    if history_exists and not force_download:
        return (
            "<span style='color:#d29922;font-size:11px;'>history match — check Force to download</span>",
            200,
        )

    cur = g.db.execute(
        """INSERT OR IGNORE INTO download_queue
                (video_id, source_id, status, triggered_by)
           VALUES (?, ?, 'pending', 'manual')""",
        (video_id, src_id),
    )
    g.db.commit()

    if cur.rowcount > 0:
        return ("<span style='color:#3fb950;font-size:11px;font-weight:600;'>\u2713 queued</span>", 200)
    # Already in download_queue — show its status
    existing = g.db.execute(
        "SELECT status FROM download_queue WHERE video_id = ? ORDER BY id DESC LIMIT 1",
        (video_id,),
    ).fetchone()
    label = (existing["status"] if existing else "exists")
    return (f"<span style='color:#8b949e;font-size:11px;'>{label}</span>", 200)


@app.post("/downloads/retry-video/<int:channel_id>/<video_id>")
def downloads_retry_single_video(channel_id: int, video_id: str):
    """Retry the most-recent failed download for a video (Videos sub-tab)."""
    if not video_id or len(video_id) > 32:
        return ("Bad video_id", 400)

    chan = g.db.execute(
        "SELECT * FROM channels WHERE id = ?", (channel_id,)
    ).fetchone()
    if not chan:
        return ("Channel not found", 404)

    # Find latest failed-or-stuck DLQ row for this video
    dq = g.db.execute(
        """SELECT dq.id, dq.job_id FROM download_queue dq
            LEFT JOIN jobs j ON j.id = dq.job_id
            WHERE dq.video_id = ?
              AND (dq.status = 'failed' OR j.status = 'failed')
            ORDER BY dq.id DESC LIMIT 1""",
        (video_id,),
    ).fetchone()
    if not dq:
        return ("<span style='color:#f85149;font-size:11px;'>no failed row</span>", 200)

    # 1. Delete the download folder for this video (removes partials)
    downloads_root = Path(os.getenv("DOWNLOADS_ROOT", "/shared/downloads"))
    folder = (downloads_root / video_id).resolve()
    try:
        folder.relative_to(downloads_root.resolve())
        if folder.exists() and folder.is_dir():
            import shutil
            shutil.rmtree(folder)
    except (ValueError, OSError):
        pass

    # 2. Retire the old job row (audit trail)
    if dq["job_id"]:
        g.db.execute(
            """UPDATE jobs SET status = 'failed',
                  error_message = 'retried by user — superseded',
                  updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
                WHERE id = ?""",
            (dq["job_id"],),
        )

    # 3. Reset the DLQ row to pending so the hydrator picks it up
    g.db.execute(
        """UPDATE download_queue
              SET status='pending', job_id=NULL, error_message='',
                  updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = ?""",
        (dq["id"],),
    )
    g.db.commit()

    return ("<span style='color:#58a6ff;font-size:11px;font-weight:600;'>\u21bb retrying</span>", 200)


@app.post("/partials/downloads/live/retry/<int:dlq_id>")
def downloads_live_retry(dlq_id: int):
    """Delete partial files for a failed DLQ row and re-queue from scratch."""
    dq = g.db.execute(
        "SELECT id, video_id, job_id, status FROM download_queue WHERE id = ?",
        (dlq_id,),
    ).fetchone()
    if not dq:
        return ("Not found", 404)
    if dq["status"] not in ("failed", "complete"):
        return ("Only failed/complete rows can be retried", 400)

    video_id = dq["video_id"]
    job_id   = dq["job_id"]

    # 1. Delete the download folder for this video (removes partials + any files)
    downloads_root = Path(os.getenv("DOWNLOADS_ROOT", "/shared/downloads"))
    folder = (downloads_root / video_id).resolve()
    try:
        folder.relative_to(downloads_root.resolve())  # path-traversal guard
        if folder.exists() and folder.is_dir():
            import shutil
            shutil.rmtree(folder)
    except ValueError:
        pass  # outside root — skip

    # 2. Also remove from videos table so it won't be treated as "already downloaded"
    g.db.execute("DELETE FROM videos WHERE youtube_video_id = ?", (video_id,))

    # 3. Retire the old job row (don't delete — keeps audit trail)
    if job_id:
        g.db.execute(
            """UPDATE jobs
                  SET status = 'failed',
                      error_message = 'retried by user — superseded',
                      updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
                WHERE id = ?""",
            (job_id,),
        )

    # 4. Reset the DLQ row to pending so the hydrator creates a fresh job
    g.db.execute(
        """UPDATE download_queue
              SET status        = 'pending',
                  job_id        = NULL,
                  error_message = '',
                  updated_at    = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = ?""",
        (dlq_id,),
    )
    g.db.commit()

    # Return refreshed live panel
    active = g.db.execute(
        """SELECT dq.id, dq.video_id, dq.status, dq.triggered_by,
                  dq.created_at, dq.updated_at, dq.job_id, dq.error_message,
                  j.status AS job_status,
                  COALESCE(cv.title, v.original_title, dq.video_id) AS title,
                  cv.thumbnail_url, cv.duration_sec,
                  COALESCE(s.name, '?') AS source_label
             FROM download_queue dq
             LEFT JOIN jobs j           ON j.id = dq.job_id
             LEFT JOIN catalog_videos cv ON cv.video_id = dq.video_id
             LEFT JOIN videos v         ON v.youtube_video_id = dq.video_id
             LEFT JOIN sources s        ON s.id = dq.source_id
            WHERE dq.status IN ('pending','hydrated','downloading')
            ORDER BY CASE dq.status WHEN 'downloading' THEN 0 WHEN 'hydrated' THEN 1 ELSE 2 END, dq.id
            LIMIT 50"""
    ).fetchall()
    recent = g.db.execute(
        """SELECT dq.id, dq.video_id, dq.status, dq.triggered_by,
                  dq.updated_at, dq.job_id, dq.error_message,
                  COALESCE(cv.title, v.original_title, dq.video_id) AS title,
                  cv.thumbnail_url
             FROM download_queue dq
             LEFT JOIN catalog_videos cv ON cv.video_id = dq.video_id
             LEFT JOIN videos v          ON v.youtube_video_id = dq.video_id
            WHERE dq.status IN ('complete','failed')
            ORDER BY dq.updated_at DESC, dq.id DESC
            LIMIT 20"""
    ).fetchall()
    counts = {
        r["status"]: int(r["n"])
        for r in g.db.execute(
            "SELECT status, COUNT(*) n FROM download_queue GROUP BY status"
        ).fetchall()
    }
    return render_template(
        "partials/downloads_live.html",
        active=[dict(r) for r in active],
        recent=[dict(r) for r in recent],
        counts=counts,
        log_lines=_read_container_logs(WATCHER_CONTAINER, 30),
        format_duration=_format_duration,
        flash=f"Re-queued {video_id} — partial files deleted.",
    )


@app.post("/downloads/jobs/<int:job_id>/retry")
def downloads_job_retry(job_id: int):
    g.db.execute(
        """UPDATE jobs
              SET status='pending', source_file_path='', error_message='',
                  retry_count = retry_count + 1,
                  updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = ?""",
        (job_id,),
    )
    g.db.commit()
    return render_template(
        "partials/downloads_jobs.html",
        jobs=_query_downloads_jobs(g.db),
        flash=f"Job {job_id} re-queued",
    )


@app.post("/downloads/jobs/<int:job_id>/cancel")
def downloads_job_cancel(job_id: int):
    # Look up the job's video so we can flag the in-flight download
    # in download_queue. The watcher's progress hook polls dlq.status
    # each tick and raises CancelledError when it sees 'cancelled',
    # which aborts yt-dlp cleanly mid-stream.
    row = g.db.execute(
        "SELECT v.youtube_video_id AS video_id, j.status "
        "  FROM jobs j JOIN videos v ON v.id = j.video_id "
        " WHERE j.id = ?",
        (job_id,),
    ).fetchone()
    g.db.execute(
        """UPDATE jobs
              SET status='failed', error_message='canceled by user',
                  updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
            WHERE id = ? AND status IN ('pending','downloading','downloaded',
                                        'processing','processed','partial')""",
        (job_id,),
    )
    if row and row["video_id"]:
        g.db.execute(
            """UPDATE download_queue
                  SET status='cancelled',
                      error_message='canceled by user',
                      updated_at = strftime('%Y-%m-%dT%H:%M:%S','now')
                WHERE video_id = ?
                  AND status IN ('pending','hydrated','downloading')""",
            (row["video_id"],),
        )
    g.db.commit()
    return render_template(
        "partials/downloads_jobs.html",
        jobs=_query_downloads_jobs(g.db),
        flash=f"Job {job_id} canceled",
    )


@app.post("/downloads/files/delete")
def downloads_files_delete():
    rel = request.form.get("path", "")
    target = _safe_downloads_path(rel)
    parent_rel = (request.form.get("parent") or "").strip()
    if target is None or not target.exists():
        return render_template(
            "partials/downloads_files.html",
            listing=_list_downloads_dir(parent_rel),
            flash="Path not found",
            flash_type="error",
        )
    if target.resolve() == DOWNLOADS_ROOT.resolve():
        return render_template(
            "partials/downloads_files.html",
            listing=_list_downloads_dir(parent_rel),
            flash="Refusing to delete the root downloads directory",
            flash_type="error",
        )
    try:
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
            msg = f"Deleted folder: {target.name}"
        else:
            target.unlink()
            msg = f"Deleted file: {target.name}"
    except OSError as e:
        return render_template(
            "partials/downloads_files.html",
            listing=_list_downloads_dir(parent_rel),
            flash=f"Delete failed: {e}",
            flash_type="error",
        )
    return render_template(
        "partials/downloads_files.html",
        listing=_list_downloads_dir(parent_rel),
        flash=msg,
        flash_type="success",
    )


# ===========================================================================
# Admin page — factory reset + lightweight cleanups
# ===========================================================================

@app.get("/admin")
def page_admin():
    return render_template("admin.html")


@app.get("/admin/credentials")
def admin_credentials_partial():
    """HTMX partial — show all YouTube projects with their client_id and linked account."""
    rows = g.db.execute(
        """
        SELECT
            p.id          AS pid,
            p.label       AS label,
            p.client_id   AS client_id,
            p.daily_cap   AS daily_cap,
            p.updated_at  AS updated_at,
            t.id          AS tid,
            t.account_label AS account_label,
            t.needs_reauth  AS needs_reauth,
            t.last_error    AS last_error,
            t.last_refreshed_at AS last_refreshed_at
        FROM youtube_projects p
        LEFT JOIN oauth_tokens t ON t.project_id = p.id AND t.platform = 'youtube'
        ORDER BY p.label, p.id, t.id
        """
    ).fetchall()

    if not rows:
        return (
            "<p style='color:#8b949e;font-size:13px;'>No YouTube projects configured.</p>",
            200,
        )

    def _mask(cid: str) -> str:
        if not cid:
            return "(none)"
        # Format is usually "numbers-randomchars.apps.googleusercontent.com"
        parts = cid.split("-", 1)
        proj_num = parts[0] if parts else cid[:12]
        suffix = cid[-12:] if len(cid) > 24 else ""
        return f"{proj_num}-…{suffix}"

    html = ""
    prev_pid = None
    for r in rows:
        pid = r["pid"]
        if pid != prev_pid:
            prev_pid = pid
            cid_masked = _mask(r["client_id"] or "")
            cid_full   = (r["client_id"] or "").replace("'", "&#39;")
            needs_reauth = bool(r["needs_reauth"])
            status_color = "#f85149" if needs_reauth else "#3fb950"
            status_text  = "needs re-auth" if needs_reauth else "ok"
            account = r["account_label"] or "(not connected)"
            last_err = (r["last_error"] or "").split("\n")[0][:100]
            label_safe = (r["label"] or "").replace("'", "&#39;")
            html += (
                f"<div id='cred-row-{pid}' style='padding:10px 0;border-bottom:1px solid #21262d;'>"
                # Row 1: name + badge + buttons
                f"  <div style='display:grid;grid-template-columns:1fr auto;gap:8px;align-items:start;'>"
                f"    <div>"
                f"      <div style='font-size:13px;font-weight:600;color:#f0f6fc;'>"
                f"        {r['label']}"
                f"        <span style='font-size:10px;font-weight:400;margin-left:6px;"
                f"               padding:1px 6px;border-radius:99px;border:1px solid {status_color};"
                f"               color:{status_color};'>{status_text}</span>"
                f"      </div>"
                f"      <div style='font-size:11px;color:#8b949e;margin-top:2px;font-family:monospace;'>"
                f"        client_id: {cid_masked}"
                f"      </div>"
                f"      <div style='font-size:11px;color:#8b949e;margin-top:1px;'>"
                f"        account: <span style='color:#c9d1d9;'>{account}</span>"
                f"      </div>"
                + (
                    f"      <div style='font-size:10px;color:#f85149;margin-top:2px;'>⚠ {last_err}</div>"
                    if last_err and needs_reauth else ""
                )
                + f"    </div>"
                # Action buttons column
                f"    <div style='display:flex;flex-direction:column;gap:6px;align-items:flex-end;'>"
                f"      <a href='/oauth/youtube/start?project_id={pid}'"
                f"         style='font-size:11px;padding:4px 10px;border-radius:6px;"
                f"                border:1px solid #388bfd;color:#79c0ff;background:#0c1a2e;"
                f"                text-decoration:none;white-space:nowrap;'>"
                f"        🔑 Re-authorize"
                f"      </a>"
                f"      <button onclick=\"credToggleEdit({pid})\""
                f"              style='font-size:11px;padding:4px 10px;border-radius:6px;"
                f"                     border:1px solid #30363d;color:#8b949e;background:#161b22;"
                f"                     cursor:pointer;white-space:nowrap;'>"
                f"        ✏ Edit secret"
                f"      </button>"
                f"    </div>"
                f"  </div>"
                # Inline edit form (hidden by default)
                f"  <div id='cred-edit-{pid}' style='display:none;margin-top:10px;"
                f"       padding:10px;border-radius:6px;background:#0d1117;border:1px solid #30363d;'>"
                f"    <div style='font-size:11px;color:#8b949e;margin-bottom:6px;'>"
                f"      Update OAuth credentials for <strong style='color:#f0f6fc;'>{label_safe}</strong>."
                f"      Paste the new value from Google Cloud Console → APIs &amp; Services → Credentials."
                f"    </div>"
                f"    <label style='font-size:11px;color:#8b949e;display:block;margin-bottom:2px;'>Client ID (leave blank to keep existing)</label>"
                f"    <input id='cred-cid-{pid}' type='text' placeholder='622965513741-....apps.googleusercontent.com'"
                f"           value='{cid_full}'"
                f"           style='width:100%;box-sizing:border-box;padding:5px 8px;border-radius:5px;"
                f"                  border:1px solid #30363d;background:#161b22;color:#c9d1d9;"
                f"                  font-family:monospace;font-size:11px;margin-bottom:8px;'/>"
                f"    <label style='font-size:11px;color:#8b949e;display:block;margin-bottom:2px;'>Client Secret (leave blank to keep existing)</label>"
                f"    <input id='cred-sec-{pid}' type='text' placeholder='GOCSPX-…'"
                f"           style='width:100%;box-sizing:border-box;padding:5px 8px;border-radius:5px;"
                f"                  border:1px solid #30363d;background:#161b22;color:#c9d1d9;"
                f"                  font-family:monospace;font-size:11px;margin-bottom:8px;'/>"
                f"    <div style='display:flex;gap:8px;'>"
                f"      <button onclick=\"credSave({pid})\""
                f"              id='cred-save-{pid}'"
                f"              style='font-size:11px;padding:5px 14px;border-radius:6px;"
                f"                     border:1px solid #3fb950;color:#3fb950;background:#0a1c0a;"
                f"                     cursor:pointer;'>"
                f"        💾 Save"
                f"      </button>"
                f"      <button onclick=\"credToggleEdit({pid})\""
                f"              style='font-size:11px;padding:5px 14px;border-radius:6px;"
                f"                     border:1px solid #30363d;color:#8b949e;background:transparent;"
                f"                     cursor:pointer;'>"
                f"        Cancel"
                f"      </button>"
                f"      <span id='cred-msg-{pid}' style='font-size:11px;align-self:center;'></span>"
                f"    </div>"
                f"  </div>"
                f"</div>"
            )

    # Append JS helpers once at the end
    html += """
<script>
function credToggleEdit(pid) {
  var el = document.getElementById('cred-edit-' + pid);
  if (!el) return;
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
  if (el.style.display === 'block') {
    var sec = document.getElementById('cred-sec-' + pid);
    if (sec) sec.focus();
  }
}
function credSave(pid) {
  var cid = (document.getElementById('cred-cid-' + pid) || {}).value || '';
  var sec = (document.getElementById('cred-sec-' + pid) || {}).value || '';
  if (!cid.trim() && !sec.trim()) {
    var msg = document.getElementById('cred-msg-' + pid);
    if (msg) { msg.style.color='#f85149'; msg.textContent = 'Enter at least one value.'; }
    return;
  }
  var btn = document.getElementById('cred-save-' + pid);
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
  fetch('/admin/credentials/' + pid + '/update', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({client_id: cid.trim() || null, client_secret: sec.trim() || null})
  })
  .then(function(r){ return r.json(); })
  .then(function(data) {
    var msg = document.getElementById('cred-msg-' + pid);
    if (data.ok) {
      if (msg) { msg.style.color='#3fb950'; msg.textContent = '✓ Saved! Now click Re-authorize.'; }
      var secEl = document.getElementById('cred-sec-' + pid);
      if (secEl) secEl.value = '';
      if (btn) { btn.disabled = false; btn.textContent = '💾 Save'; }
    } else {
      if (msg) { msg.style.color='#f85149'; msg.textContent = data.error || 'Error saving.'; }
      if (btn) { btn.disabled = false; btn.textContent = '💾 Save'; }
    }
  })
  .catch(function(e) {
    var msg = document.getElementById('cred-msg-' + pid);
    if (msg) { msg.style.color='#f85149'; msg.textContent = 'Network error: ' + e; }
    if (btn) { btn.disabled = false; btn.textContent = '💾 Save'; }
  });
}
</script>
"""
    return (html, 200)


@app.post("/admin/credentials/<int:pid>/update")
def admin_credentials_update(pid: int):
    """Update client_id and/or client_secret for a YouTube project."""
    body = request.get_json(silent=True) or {}
    new_secret = (body.get("client_secret") or "").strip()
    new_client_id = (body.get("client_id") or "").strip()

    if not new_secret and not new_client_id:
        return _err("Provide at least client_secret or client_id", "MISSING_FIELD", 400)

    row = g.db.execute(
        "SELECT id, label FROM youtube_projects WHERE id = ?", (pid,)
    ).fetchone()
    if not row:
        return _err("Project not found", "NOT_FOUND", 404)

    if new_secret and new_client_id:
        g.db.execute(
            "UPDATE youtube_projects SET client_id=?, client_secret=?, updated_at=datetime('now') WHERE id=?",
            (new_client_id, new_secret, pid),
        )
    elif new_secret:
        g.db.execute(
            "UPDATE youtube_projects SET client_secret=?, updated_at=datetime('now') WHERE id=?",
            (new_secret, pid),
        )
    else:
        g.db.execute(
            "UPDATE youtube_projects SET client_id=?, updated_at=datetime('now') WHERE id=?",
            (new_client_id, pid),
        )
    g.db.commit()
    return jsonify({"ok": True, "label": row["label"]})


@app.post("/admin/factory-reset")
def admin_factory_reset():
    """Wipe all operational data; preserve configuration tables.

    Preserved: pipelines, sources, destinations, download_profiles,
               routing_rules, channels, youtube_projects, oauth_tokens,
               youtube_channels, worker_state.

    Wiped:     catalog_videos, download_queue, jobs, job_outputs,
               upload_results, upload_progress, upload_ledger,
               destination_quota, videos.

    Optional: also delete files under DOWNLOADS_DIR (wipe_disk=1).
    """
    wipe_disk = request.form.get("wipe_disk") == "1"

    try:
        # Operational tables — order respects FK constraints.
        for tbl in (
            "upload_progress",
            "upload_results",
            "upload_ledger",
            "job_outputs",
            "jobs",
            "download_queue",
            "catalog_videos",
            "destination_quota",
            "videos",
        ):
            g.db.execute(f"DELETE FROM {tbl}")

        # Reset channel download counters so backfill starts fresh.
        g.db.execute(
            "UPDATE channels SET uploads_today=0, backfill_queue='[]', "
            "backfill_entry_map='{}', backfill_complete=0, mode='backfill'"
        )

        g.db.commit()

        wiped_files = 0
        if wipe_disk:
            import shutil
            root = Path(os.getenv("DOWNLOADS_DIR", "/shared/downloads"))
            if root.is_dir():
                for child in root.iterdir():
                    try:
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                        wiped_files += 1
                    except OSError:
                        pass

        disk_note = f" + {wiped_files} disk item(s)" if wipe_disk else ""
        return (
            f"<span style='color:#3fb950;font-size:13px;font-weight:600;'>"
            f"✓ Factory reset complete{disk_note}. All pipelines/sources/destinations preserved."
            f"</span>",
            200,
        )
    except Exception as exc:
        g.db.rollback()
        return (str(exc), 500)


@app.post("/admin/clear-failed")
def admin_clear_failed():
    """Delete all failed jobs and their DLQ rows."""
    try:
        g.db.execute(
            "DELETE FROM download_queue WHERE status='failed'"
        )
        g.db.execute(
            """DELETE FROM jobs WHERE status='failed'
                 AND id NOT IN (
                     SELECT job_id FROM download_queue
                      WHERE job_id IS NOT NULL
                 )"""
        )
        # Also nuke orphaned failed jobs with no DLQ link.
        g.db.execute("DELETE FROM jobs WHERE status='failed'")
        g.db.commit()
        return ("✓ Failed jobs cleared.", 200)
    except Exception as exc:
        g.db.rollback()
        return (str(exc), 500)


@app.post("/admin/clear-upload-history")
def admin_clear_upload_history():
    """Wipe upload_results, upload_progress, upload_ledger."""
    try:
        g.db.execute("DELETE FROM upload_progress")
        g.db.execute("DELETE FROM upload_results")
        g.db.execute("DELETE FROM upload_ledger")
        g.db.commit()
        return ("✓ Upload history cleared.", 200)
    except Exception as exc:
        g.db.rollback()
        return (str(exc), 500)


@app.post("/admin/reset-hydration")
def admin_reset_hydration():
    """Clear hydrated_at so all catalog rows are re-hydrated next pass."""
    try:
        n = g.db.execute(
            "UPDATE catalog_videos SET hydrated_at=NULL"
        ).rowcount
        g.db.commit()
        return (f"✓ Reset {n} catalog row(s) — hydration will restart.", 200)
    except Exception as exc:
        g.db.rollback()
        return (str(exc), 500)


@app.get("/admin/bad-tokens")
def admin_bad_tokens_partial():
    """HTMX partial: list of zombie/invalid OAuth tokens."""
    rows = g.db.execute(
        """
        SELECT t.id AS tid, t.project_id, t.needs_reauth,
               t.last_error,
               COALESCE(p.label, '(project deleted)') AS label,
               p.id AS pid
          FROM oauth_tokens t
          LEFT JOIN youtube_projects p ON p.id = t.project_id
         WHERE t.needs_reauth = 1
            OR p.id IS NULL
         ORDER BY t.id
        """
    ).fetchall()

    if not rows:
        return (
            "<p style='color:#3fb950;font-size:13px;'>No bad tokens — all clear.</p>",
            200,
        )

    items = ""
    for r in rows:
        err_short = (r["last_error"] or "orphaned / no project").split("\n")[0][:80]
        items += (
            f"<div style='display:flex;align-items:center;justify-content:space-between;"
            f"gap:12px;padding:8px 0;border-bottom:1px solid #21262d;'>"
            f"  <div>"
            f"    <span style='color:#f0f6fc;font-size:13px;font-weight:600;'>Token #{r['tid']}</span>"
            f"    <span style='color:#8b949e;font-size:12px;margin-left:8px;'>project #{r['project_id']} — {r['label']}</span><br>"
            f"    <span style='color:#f85149;font-size:11px;'>{err_short}</span>"
            f"  </div>"
            f"  <button hx-post='/admin/delete-token/{r['tid']}'"
            f"          hx-target='#bad-tokens-list' hx-swap='innerHTML'"
            f"          style='padding:4px 12px;border-radius:6px;border:1px solid #f85149;"
            f"                 background:#3d1a1a;color:#f85149;font-size:12px;cursor:pointer;white-space:nowrap;'"
            f"          hx-confirm='Delete token #{r['tid']} and its project?'>"
            f"    Delete"
            f"  </button>"
            f"</div>"
        )
    return (items, 200)


@app.post("/admin/delete-token/<int:tid>")
def admin_delete_token(tid: int):
    """Delete a specific OAuth token and its linked youtube_project (if any)."""
    try:
        row = g.db.execute(
            "SELECT project_id FROM oauth_tokens WHERE id=?", (tid,)
        ).fetchone()
        if row and row["project_id"]:
            g.db.execute(
                "DELETE FROM youtube_projects WHERE id=?", (row["project_id"],)
            )
        g.db.execute("DELETE FROM oauth_tokens WHERE id=?", (tid,))
        g.db.commit()
        # Return refreshed list
        return admin_bad_tokens_partial()
    except Exception as exc:
        g.db.rollback()
        return (str(exc), 500)


@app.post("/admin/clear-bad-tokens")
def admin_clear_bad_tokens():
    """Bulk delete all needs_reauth tokens + orphaned tokens + their projects."""
    try:
        # Projects linked to bad tokens
        g.db.execute(
            """DELETE FROM youtube_projects WHERE id IN (
                   SELECT project_id FROM oauth_tokens
                    WHERE needs_reauth=1 AND project_id IS NOT NULL
               )"""
        )
        # All bad tokens (needs_reauth=1 or orphaned)
        g.db.execute(
            """DELETE FROM oauth_tokens
                WHERE needs_reauth=1
                   OR project_id IS NULL
                   OR project_id NOT IN (SELECT id FROM youtube_projects)"""
        )
        g.db.commit()
        return (
            "<p style='color:#3fb950;font-size:13px;'>✓ All bad tokens cleared.</p>",
            200,
        )
    except Exception as exc:
        g.db.rollback()
        return (str(exc), 500)


_startup_recovery_sweep()
_start_hydrate_worker_once()
_start_quota_retry_worker_once()
_start_dlq_hydrate_worker_once()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
