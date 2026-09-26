"""
Processor — polls `jobs` for status='downloaded' and runs FFmpeg pipeline steps.

Spec: docs/PROCESSING_PIPELINE.md (9 step types)
Schema: docs/DATABASE_SCHEMA.md  (jobs / processing_steps / destinations / job_outputs)

Flow per job:
  1. Claim: status='downloaded' -> 'processing'
  2. Apply enabled processing_steps WHERE destination_id IS NULL  -> intermediate.mp4
  3. For each enabled destination of the pipeline:
       Apply enabled steps WHERE destination_id = <dest>  -> <platform>.mp4
       Insert job_outputs row
  4. Set status='processed' (or 'failed' on any FFmpeg error)
  5. Optionally notify the dashboard.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Iterable, Optional

DB_PATH        = os.environ.get("DB_PATH",        "/data/app.db")
DOWNLOADS_PATH = os.environ.get("DOWNLOADS_PATH", "/downloads")
DASHBOARD_URL  = os.environ.get("DASHBOARD_URL",  "http://dashboard:8080")
POLL_INTERVAL  = int(os.environ.get("POLL_INTERVAL", "5"))

# Graceful shutdown signal — set by SIGTERM/SIGINT, polled by main loop.
_shutdown_event = threading.Event()


def detect_gpu() -> bool:
    """Return True if ffmpeg in this container has NVENC encoders compiled in.

    Note: presence of an encoder doesn't guarantee a working NVIDIA GPU is
    accessible at runtime — that depends on the host's `--gpus all` flag and
    drivers. The reencode step has a libx264 fallback if NVENC fails.
    """
    try:
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return False
    return "nvenc" in (res.stdout or "")


# USE_GPU may be force-disabled or force-enabled via env; otherwise auto-detect.
_force = os.environ.get("USE_GPU", "").lower()
if _force in ("0", "false", "no", "off"):
    USE_GPU = False
elif _force in ("1", "true", "yes", "on"):
    USE_GPU = True
else:
    USE_GPU = detect_gpu()

try:
    import requests  # noqa: F401
    _HAS_REQUESTS = True
except Exception:
    _HAS_REQUESTS = False


# ---------------------------------------------------------------------------
# DB / utility
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # DELETE journal mode for portability with Docker Desktop bind mounts
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return conn


def utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def log(msg: str, level: str = "INFO") -> None:
    print(f"{utcnow_iso()} [{level}] {msg}", flush=True)


def _safe_under(path: str, root: str) -> bool:
    try:
        return str(Path(path).resolve()).startswith(str(Path(root).resolve()))
    except Exception:
        return False


def _sanitize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "x"


# ---------------------------------------------------------------------------
# FFmpeg runner
# ---------------------------------------------------------------------------

class FFmpegError(RuntimeError):
    pass


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    """Run ffmpeg with -y. Raises FFmpegError on non-zero exit."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    log("ffmpeg " + " ".join(args), "DEBUG")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise FFmpegError(res.stderr.strip()[-500:] or "(no stderr)")
    return res


def video_codec_for(codec: str) -> str:
    codec = (codec or "h264").lower()
    if codec == "h265":
        return "hevc_nvenc" if USE_GPU else "libx265"
    if codec == "vp9":
        return "libvpx-vp9"
    return "h264_nvenc" if USE_GPU else "libx264"


# ---------------------------------------------------------------------------
# Tables of constants (from PROCESSING_PIPELINE.md)
# ---------------------------------------------------------------------------

CROP_FORMULAS = {
    "16:9": "crop=iw:iw*9/16:0:(ih-iw*9/16)/2",
    "9:16": "crop=ih*9/16:ih:(iw-ih*9/16)/2:0",
    "1:1":  "crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2",
    "4:5":  "crop=iw:iw*5/4:0:(ih-iw*5/4)/2",
}

RESOLUTIONS = {
    "2160p": (3840, 2160),
    "1080p": (1920, 1080),
    "720p":  (1280, 720),
    "480p":  (854, 480),
}

POSITIONS = {
    "tl":     "{m}:{m}",
    "tr":     "main_w-overlay_w-{m}:{m}",
    "bl":     "{m}:main_h-overlay_h-{m}",
    "br":     "main_w-overlay_w-{m}:main_h-overlay_h-{m}",
    "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
}


# ---------------------------------------------------------------------------
# Step handlers — each: (in_path, out_path, params) -> bool (True if ran)
# ---------------------------------------------------------------------------

def step_trim(in_path, out_path, p):
    start = float(p.get("start", 0) or 0)
    end = p.get("end")
    if start == 0 and end is None:
        return False
    args = ["-ss", str(start), "-i", in_path]
    if end is not None:
        args += ["-to", str(float(end))]
    args += ["-c", "copy", out_path]
    run_ffmpeg(args)
    return True


def step_crop(in_path, out_path, p):
    aspect = (p.get("aspect_ratio") or "9:16").strip()
    formula = CROP_FORMULAS.get(aspect)
    if not formula:
        raise FFmpegError(f"unsupported aspect_ratio: {aspect}")
    run_ffmpeg(["-i", in_path, "-vf", formula, "-c:a", "copy", out_path])
    return True


def step_watermark(in_path, out_path, p):
    img = p.get("image_path") or ""
    if not img or not Path(img).exists():
        log(f"watermark: image_path missing ({img!r}); SKIP", "WARN")
        return False
    pos = (p.get("position") or "br").lower()
    if pos not in POSITIONS:
        raise FFmpegError(f"unsupported position: {pos}")
    margin = int(p.get("margin", 20))
    scale = float(p.get("scale", 0.1))
    opacity = float(p.get("opacity", 0.8))
    pos_expr = POSITIONS[pos].format(m=margin)
    fc = (
        f"[1:v]scale=iw*{scale}:-1,format=rgba,colorchannelmixer=aa={opacity}[logo];"
        f"[0:v][logo]overlay={pos_expr}"
    )
    run_ffmpeg(["-i", in_path, "-i", img, "-filter_complex", fc, "-c:a", "copy", out_path])
    return True


def step_text_overlay(in_path, out_path, p):
    text = (p.get("text") or "").replace("'", r"\'").replace(":", r"\:")
    if not text:
        return False
    pos = (p.get("position") or "br").lower()
    margin = int(p.get("margin", 20))
    fs = int(p.get("font_size", 36))
    fc = p.get("font_color", "white")
    oc = p.get("outline_color", "black")
    ow = int(p.get("outline_width", 2))
    op = float(p.get("opacity", 0.9))
    x_expr, y_expr = {
        "tl":     (f"{margin}", f"{margin}"),
        "tr":     (f"w-tw-{margin}", f"{margin}"),
        "bl":     (f"{margin}", f"h-th-{margin}"),
        "br":     (f"w-tw-{margin}", f"h-th-{margin}"),
        "center": ("(w-tw)/2", "(h-th)/2"),
    }.get(pos, (f"w-tw-{margin}", f"h-th-{margin}"))
    vf = (
        f"drawtext=text='{text}':fontsize={fs}:fontcolor={fc}@{op}:"
        f"borderw={ow}:bordercolor={oc}:x={x_expr}:y={y_expr}"
    )
    run_ffmpeg(["-i", in_path, "-vf", vf, "-c:a", "copy", out_path])
    return True


def _concat(a, b, out_path):
    fc = "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]"
    run_ffmpeg(["-i", a, "-i", b, "-filter_complex", fc,
                "-map", "[v]", "-map", "[a]",
                "-c:v", video_codec_for("h264"), "-c:a", "aac", out_path])


def step_intro(in_path, out_path, p):
    fp = p.get("file_path") or ""
    if not fp or not Path(fp).exists():
        log(f"intro: file_path missing ({fp!r}); SKIP", "WARN")
        return False
    _concat(fp, in_path, out_path)
    return True


def step_outro(in_path, out_path, p):
    fp = p.get("file_path") or ""
    if not fp or not Path(fp).exists():
        log(f"outro: file_path missing ({fp!r}); SKIP", "WARN")
        return False
    _concat(in_path, fp, out_path)
    return True


def step_normalize_audio(in_path, out_path, p):
    I = float(p.get("target_lufs", -14))
    TP = float(p.get("true_peak", -1.0))
    LRA = float(p.get("lra", 11.0))
    pass1 = subprocess.run(
        ["ffmpeg", "-y", "-i", in_path,
         "-af", f"loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    measured = {}
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", pass1.stderr or "", re.DOTALL)
    if m:
        try:
            measured = json.loads(m.group(0))
        except Exception:
            measured = {}
    if not measured:
        run_ffmpeg(["-i", in_path, "-af", f"loudnorm=I={I}:TP={TP}:LRA={LRA}",
                    "-c:v", "copy", out_path])
        return True
    af = (
        f"loudnorm=I={I}:TP={TP}:LRA={LRA}:"
        f"measured_I={measured.get('input_i', I)}:"
        f"measured_TP={measured.get('input_tp', TP)}:"
        f"measured_LRA={measured.get('input_lra', LRA)}:"
        f"measured_thresh={measured.get('input_thresh', '-30')}:"
        f"offset={measured.get('target_offset', '0')}:linear=true"
    )
    run_ffmpeg(["-i", in_path, "-af", af, "-c:v", "copy", out_path])
    return True


def step_reencode(in_path, out_path, p):
    codec = (p.get("codec") or "h264").lower()
    res = p.get("resolution")
    crf = int(p.get("crf", 23))
    bitrate = p.get("bitrate")
    a_codec = (p.get("audio_codec") or "aac").lower()
    a_br = int(p.get("audio_bitrate", 192))
    preset = p.get("preset") or "medium"

    args = ["-i", in_path, "-c:v", video_codec_for(codec)]
    if USE_GPU and codec in ("h264", "h265"):
        args += ["-cq", str(crf), "-preset", "p4"]
    else:
        args += ["-crf", str(crf), "-preset", preset]
    if bitrate:
        args += ["-b:v", f"{int(bitrate)}k"]
    if res in RESOLUTIONS:
        w, h = RESOLUTIONS[res]
        args += ["-vf", f"scale={w}:{h}"]
    if a_codec == "copy":
        args += ["-c:a", "copy"]
    else:
        args += ["-c:a", a_codec, "-b:a", f"{a_br}k"]
    args += [out_path]

    try:
        run_ffmpeg(args)
    except FFmpegError as e:
        if USE_GPU and codec in ("h264", "h265"):
            log(f"NVENC failed ({e}); retrying with libx264", "WARN")
            args2 = ["-i", in_path, "-c:v", "libx264" if codec == "h264" else "libx265",
                     "-crf", str(crf), "-preset", preset]
            if res in RESOLUTIONS:
                w, h = RESOLUTIONS[res]
                args2 += ["-vf", f"scale={w}:{h}"]
            args2 += (["-c:a", "copy"] if a_codec == "copy"
                      else ["-c:a", a_codec, "-b:a", f"{a_br}k"])
            args2 += [out_path]
            run_ffmpeg(args2)
        else:
            raise
    return True


def step_resize(in_path, out_path, p):
    w = int(p.get("width", 1920))
    h = int(p.get("height", 1080))
    pad = p.get("pad_color", "black")
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={pad}")
    run_ffmpeg(["-i", in_path, "-vf", vf, "-c:a", "copy", out_path])
    return True


STEP_HANDLERS = {
    "trim":            step_trim,
    "crop":            step_crop,
    "watermark":       step_watermark,
    "text_overlay":    step_text_overlay,
    "intro":           step_intro,
    "outro":           step_outro,
    "normalize_audio": step_normalize_audio,
    "reencode":        step_reencode,
    "resize":          step_resize,
}


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _apply_steps(steps: Iterable[sqlite3.Row], src: str, work_dir: Path,
                 prefix: str) -> str:
    current = src
    idx = 0
    for st in steps:
        if not st["enabled"]:
            continue
        try:
            params = json.loads(st["params"] or "{}")
        except Exception:
            params = {}
        handler = STEP_HANDLERS.get(st["step_type"])
        if handler is None:
            log(f"unknown step_type {st['step_type']!r}; SKIP", "WARN")
            continue
        out = work_dir / f"{prefix}_{idx:02d}_{st['step_type']}.mp4"
        idx += 1
        log(f"step {st['step_type']} -> {out.name}")
        ran = handler(current, str(out), params)
        if ran:
            current = str(out)
        elif out.exists():
            try: out.unlink()
            except Exception: pass
    return current


def claim_job(db, jid):
    cur = db.execute(
        "UPDATE jobs SET status='processing', updated_at=? "
        "WHERE id=? AND status='downloaded'",
        (utcnow_iso(), jid),
    )
    return cur.rowcount > 0


def mark_failed(db, jid, msg):
    db.execute(
        "UPDATE jobs SET status='failed', error_message=?, updated_at=? WHERE id=?",
        (msg[-500:], utcnow_iso(), jid),
    )


def mark_processed(db, jid):
    db.execute(
        "UPDATE jobs SET status='processed', error_message='', updated_at=? WHERE id=?",
        (utcnow_iso(), jid),
    )


def notify_dashboard(job_id: int, status: str, output_path: Optional[str] = None) -> None:
    if not _HAS_REQUESTS:
        return
    try:
        requests.post(
            f"{DASHBOARD_URL}/api/processor/event",
            json={"job_id": job_id, "status": status, "output_path": output_path},
            timeout=3,
        )
    except Exception:
        pass


def process_job(db, job):
    jid = job["id"]
    src = job["source_file_path"]
    if not src or not Path(src).exists() or not _safe_under(src, DOWNLOADS_PATH):
        mark_failed(db, jid, f"invalid source_file_path: {src!r}")
        log(f"job {jid}: invalid source {src!r}", "ERROR")
        return

    if not claim_job(db, jid):
        return
    notify_dashboard(jid, "processing")
    log(f"job {jid}: claimed (pipeline_id={job['pipeline_id']})")

    work_dir = Path(DOWNLOADS_PATH) / f"job_{jid}"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        global_steps = db.execute(
            "SELECT * FROM processing_steps "
            "WHERE pipeline_id=? AND destination_id IS NULL AND enabled=1 "
            "ORDER BY step_order ASC, id ASC",
            (job["pipeline_id"],),
        ).fetchall()
        intermediate = _apply_steps(global_steps, src, work_dir, "intermediate")
        if intermediate != src:
            final_inter = work_dir / "intermediate.mp4"
            if Path(intermediate) != final_inter:
                shutil.move(intermediate, final_inter)
                intermediate = str(final_inter)
        log(f"job {jid}: intermediate -> {intermediate}")

        dests = db.execute(
            "SELECT * FROM destinations WHERE pipeline_id=? AND enabled=1 ORDER BY id ASC",
            (job["pipeline_id"],),
        ).fetchall()
        if not dests:
            raise FFmpegError("no enabled destinations for pipeline")

        for dest in dests:
            dest_steps = db.execute(
                "SELECT * FROM processing_steps "
                "WHERE pipeline_id=? AND destination_id=? AND enabled=1 "
                "ORDER BY step_order ASC, id ASC",
                (job["pipeline_id"], dest["id"]),
            ).fetchall()
            platform = _sanitize(dest["platform"])
            final_out = work_dir / f"{platform}.mp4"

            chained = _apply_steps(dest_steps, intermediate, work_dir, platform)
            if chained != str(final_out):
                if Path(chained) == Path(intermediate):
                    shutil.copy2(chained, final_out)
                else:
                    shutil.move(chained, final_out)

            size = final_out.stat().st_size if final_out.exists() else 0
            db.execute(
                "INSERT INTO job_outputs (job_id, destination_id, file_path, file_size_bytes, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (jid, dest["id"], str(final_out), size, utcnow_iso()),
            )
            log(f"job {jid}: dest {dest['platform']} -> {final_out} ({size} bytes)")

        # cleanup scratch files
        for f in list(work_dir.glob("intermediate_*_*.mp4")) + list(work_dir.glob("*_[0-9][0-9]_*.mp4")):
            try: f.unlink()
            except Exception: pass

        mark_processed(db, jid)
        notify_dashboard(jid, "processed")
        log(f"job {jid}: processed")

    except FFmpegError as e:
        mark_failed(db, jid, str(e))
        notify_dashboard(jid, "failed")
        log(f"job {jid}: FAILED — {e}", "ERROR")
    except Exception as e:
        mark_failed(db, jid, f"{type(e).__name__}: {e}")
        notify_dashboard(jid, "failed")
        log(f"job {jid}: CRASH — {e}\n{traceback.format_exc()}", "ERROR")


def poll_jobs(db):
    rows = db.execute(
        "SELECT * FROM jobs WHERE status='downloaded' ORDER BY id ASC"
    ).fetchall()
    for job in rows:
        process_job(db, job)
    return len(rows)


def main():
    mode = "ENABLED (h264_nvenc)" if USE_GPU else "DISABLED (libx264 fallback)"
    log(f"Processor started. DB={DB_PATH} DOWNLOADS={DOWNLOADS_PATH}")
    log(f"GPU encoding: {mode}")

    def _handle_signal(signum, _frame):
        log(f"Shutdown signal {signum} received \u2014 finishing current job then exiting...")
        _shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    db = get_db()
    try:
        while not _shutdown_event.is_set():
            try:
                poll_jobs(db)
            except sqlite3.Error as e:
                log(f"DB error: {e}", "ERROR")
                try: db.close()
                except Exception: pass
                if _shutdown_event.wait(POLL_INTERVAL):
                    break
                db = get_db()
                continue
            # Interruptible sleep — wakes immediately on shutdown signal.
            if _shutdown_event.wait(POLL_INTERVAL):
                break
        log("Processor stopped cleanly.")
        sys.exit(0)
    except KeyboardInterrupt:
        log("Processor stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
