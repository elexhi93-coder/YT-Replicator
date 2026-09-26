# FEATURE — Download Settings (per-pipeline / per-channel)

> Status: **Blueprint / RFC** — not implemented yet.
> Owner: dashboard team.
> Inspired by: the IDM-YT desktop app (`video_downloader.py`).
> Related: [FEATURE_CATALOG_AND_BACKFILL.md](FEATURE_CATALOG_AND_BACKFILL.md) — the probe endpoint defined here is consumed by the catalog hydrate flow.
> Created: 2026-04-26.

## 1. Motivation

Today, every video downloaded by `headless_watcher.py` uses the same
hard-coded yt-dlp options:

```python
"format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
"merge_output_format": "mp4",
"writesubtitles": True,
"writeautomaticsub": True,
"subtitleslangs": SUBTITLE_LANGS,    # constant
"writethumbnail": True,
"convert_thumbnails": "jpg",
"writeinfojson": True,
```

Limitations:

- No way to cap resolution (we always pull the largest mp4 — wastes
  disk + bandwidth for shorts/talking-head channels).
- No way to disable subtitles / thumbnails / info-json per channel.
- No way to prefer a specific codec (avc1 / vp9 / av1) or container.
- Operator can't probe a URL to see what's available before committing.

The IDM-YT desktop app already solves these for the single-video flow.
We want the same expressiveness in the dashboard, adapted to our
**unattended pipeline** model.

## 2. Goals & Non-Goals

### Goals
1. Per-pipeline default download preferences, editable from the UI.
2. Per-channel override (optional — empty fields fall back to pipeline).
3. A pure helper that turns prefs → yt-dlp options dict.
4. A `POST /api/yt/probe` endpoint that returns the available formats
   for any URL (mirrors what IDM-YT shows in its dropdown).
5. Backwards compatible: missing rows / NULL fields → today's behaviour.

### Non-Goals (v1)
- Per-video override at fetch time (the watcher runs unattended).
- Audio-only mode (we always upload video).
- Multiple format profiles per pipeline (one default + per-channel
  override is enough for the manhua/shorts use case).
- Editing arbitrary yt-dlp options through the UI — we expose a small
  curated set; advanced users can edit `extra_yt_dlp_opts` JSON if they
  really need it (escape hatch).

## 3. Reference: what IDM-YT exposes

From [`video_downloader.py`](../../../IDM-YT/video_downloader.py):

| Knob | IDM-YT default | Source line(s) |
|---|---|---|
| Video quality (resolution + fps) | best from probe | `~1280 video_format_combo` |
| Output container | `mp4` (also mov/avi/webm/flv/3gp/mkv) | `~108 output_formats` |
| Audio container/bitrate | `mp3 320` if FFmpeg, else original | `~454 audio_format_combo` |
| Thumbnail format | `jpg` (also png/webp) | `~487 thumb_format_combo` |
| Subtitles toggle + langs + format | on, multi-lang, `best/srt/vtt` | `~520 subs_frame` |
| Info JSON | always on | implicit |

The probe call is `yt_dlp.YoutubeDL({...}).extract_info(url, download=False)`
followed by walking `info['formats']` and building friendly labels like
`1080p 60fps (premium) - 245.3MB [mp4]`.

## 4. Data Model

### 4.1 New table: `download_settings`

One row per pipeline. Per-channel override stored as a row with `channel_id`
populated and `pipeline_id = NULL` (or both populated — we'll fix in §6).
**Decision: separate `pipeline_id` and `channel_id` columns, exactly one
must be NOT NULL.**

```sql
CREATE TABLE IF NOT EXISTS download_settings (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id          INTEGER REFERENCES pipelines(id) ON DELETE CASCADE,
    channel_id           INTEGER REFERENCES channels(id)  ON DELETE CASCADE,

    -- Video
    max_height           INTEGER,             -- 2160|1440|1080|720|480|360|NULL=best
    container            TEXT,                -- 'mp4'|'mkv'|'webm'|NULL=auto
    codec_pref           TEXT,                -- 'any'|'avc1'|'vp9'|'av1'|NULL='any'
    fps_cap              INTEGER,             -- e.g. 30|60|NULL=any

    -- Sidecars
    download_subtitles   INTEGER NOT NULL DEFAULT 1,   -- 0|1
    subtitle_langs       TEXT,                          -- csv: 'en,es,fr'|NULL=current default
    subtitle_format      TEXT,                          -- 'best'|'srt'|'vtt'|NULL='vtt'
    download_thumbnail   INTEGER NOT NULL DEFAULT 1,
    thumbnail_format     TEXT,                          -- 'jpg'|'png'|'webp'|NULL='jpg'
    write_info_json      INTEGER NOT NULL DEFAULT 1,

    -- Escape hatch
    extra_ydl_opts_json  TEXT,                          -- JSON object merged last

    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (
      (pipeline_id IS NOT NULL AND channel_id IS NULL) OR
      (pipeline_id IS NULL     AND channel_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dl_settings_pipeline
    ON download_settings(pipeline_id) WHERE pipeline_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_dl_settings_channel
    ON download_settings(channel_id)  WHERE channel_id  IS NOT NULL;
```

Notes:

- All format-related columns are **nullable** → NULL means "inherit".
- The two boolean toggles default to `1` to preserve current behaviour.
- The CHECK + partial unique indexes guarantee at most one settings row
  per pipeline and one per channel.

### 4.2 Resolution algorithm (what the watcher actually uses)

```
effective(channel, field) =
    coalesce(
        download_settings WHERE channel_id  = channel.id  -> field,
        download_settings WHERE pipeline_id = channel.pipeline_id -> field,
        BUILT_IN_DEFAULT[field]
    )
```

Built-in defaults (= today's hard-coded behaviour):

| Field | Default |
|---|---|
| `max_height` | NULL → "best" |
| `container` | `mp4` |
| `codec_pref` | `any` |
| `fps_cap` | NULL |
| `download_subtitles` | `1` |
| `subtitle_langs` | current `SUBTITLE_LANGS` constant |
| `subtitle_format` | `vtt` |
| `download_thumbnail` | `1` |
| `thumbnail_format` | `jpg` |
| `write_info_json` | `1` |
| `extra_ydl_opts_json` | NULL |

## 5. Format-selector translator

New module: `dashboard/download_prefs.py`.

```python
# Pseudocode
def build_format_selector(prefs: dict) -> str:
    height = prefs.get("max_height")        # int or None
    codec  = prefs.get("codec_pref") or "any"
    cont   = prefs.get("container") or "mp4"
    fps    = prefs.get("fps_cap")

    h = f"[height<={height}]" if height else ""
    f = f"[fps<={fps}]"       if fps    else ""
    v = {
        "any":  "",
        "avc1": "[vcodec^=avc1]",
        "vp9":  "[vcodec^=vp09]",
        "av1":  "[vcodec^=av01]",
    }[codec]

    # Prefer split video+audio in the requested container, fall back gracefully
    audio = "[ext=m4a]" if cont == "mp4" else ""
    return (
        f"bestvideo{h}{f}{v}[ext={cont}]+bestaudio{audio}"
        f"/bestvideo{h}{f}{v}+bestaudio"
        f"/best{h}{f}[ext={cont}]"
        f"/best{h}{f}"
        f"/best"
    )


def build_ydl_opts(prefs: dict, outtmpl: str) -> dict:
    opts = {
        "format": build_format_selector(prefs),
        "merge_output_format": prefs.get("container") or "mp4",
        "outtmpl": outtmpl,
        "writeinfojson": bool(prefs.get("write_info_json", 1)),
    }
    if prefs.get("download_subtitles", 1):
        opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": (prefs.get("subtitle_langs") or "en").split(","),
            "subtitlesformat": prefs.get("subtitle_format") or "vtt",
        })
    if prefs.get("download_thumbnail", 1):
        opts.update({
            "writethumbnail": True,
            "convert_thumbnails": prefs.get("thumbnail_format") or "jpg",
        })
    extra = prefs.get("extra_ydl_opts_json")
    if extra:
        try:
            opts.update(json.loads(extra))
        except Exception:
            pass   # invalid JSON ignored, don't break the watcher
    return opts
```

Pure functions → unit-testable with no DB.

### 5.1 Wire-in point

`headless_watcher.py::_download_video` currently builds `ydl_opts` inline.
After the feature lands it becomes:

```python
prefs = resolve_download_prefs(channel_id=channel["id"])
ydl_opts = build_ydl_opts(prefs, outtmpl=str(DOWNLOAD_DIR / "%(id)s" / "%(title)s.%(ext)s"))
ydl_opts["progress_hooks"] = [_hook]
```

Backwards compatibility: when no `download_settings` row exists,
`resolve_download_prefs` returns the BUILT_IN_DEFAULT dict → `build_ydl_opts`
produces exactly today's options.

## 6. HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/download_settings?pipeline_id=N`   | Get pipeline-level prefs (or built-in defaults if none) |
| GET  | `/api/download_settings?channel_id=N`    | Get channel-level prefs (or {} if none — no fallback at the API layer) |
| GET  | `/api/download_settings/effective?channel_id=N` | Get the **resolved** dict the watcher would use |
| PUT  | `/api/download_settings`                 | Upsert a row. Body: `{pipeline_id|channel_id, ...fields}` |
| DELETE | `/api/download_settings`               | Delete by `{pipeline_id|channel_id}` (revert to inherit) |
| POST | `/api/yt/probe`                          | Body: `{url}`. Calls `extract_info(download=False)` and returns format list |

### 6.1 `POST /api/yt/probe` response shape

```json
{
  "url": "https://...",
  "title": "...",
  "duration": 612,
  "uploader": "...",
  "formats": [
    {
      "format_id": "137",
      "ext": "mp4",
      "vcodec": "avc1.640028",
      "acodec": "none",
      "height": 1080,
      "fps": 30,
      "filesize": 245829312,
      "format_note": "1080p",
      "label": "1080p (avc1) — 234.4 MB [mp4]"
    },
    ...
  ]
}
```

Sorted by `height DESC` then `fps DESC`. Filter out audio-only formats by
default (toggle via `?include_audio=1`).

**Security:** validate URL is `http(s)://`, run with a 30 s timeout,
short-circuit if the host isn't `youtube.com` / `youtu.be` / `youtube-nocookie.com`
(prevents the probe endpoint from being used as an SSRF tool against the
internal network).

## 7. UI

Lives in the existing pipeline panel.

```
┌─ Pipeline: ManhuaNova ──────────────────────────┐
│ Channels:        [+]                           │
│  • UCxxxx — Channel A   [override ⚙]           │
│  • UCyyyy — Channel B                          │
│                                                │
│ Destinations: …                                │
│                                                │
│ ▼ Download settings (default for this pipeline)│
│  Max resolution   [ 1080p   ▼ ]               │
│  Container        [ mp4     ▼ ]               │
│  Codec preference [ any     ▼ ]               │
│  FPS cap          [ none    ▼ ]               │
│  ☑ Subtitles      langs [en,es]  fmt [vtt ▼]  │
│  ☑ Thumbnail      fmt   [jpg ▼]               │
│  ☑ Info JSON                                   │
│  ▸ Advanced (extra yt-dlp opts JSON)          │
│                                                │
│  [Probe URL: ____________ ]  [Probe]          │
│   → shows table of available formats           │
└────────────────────────────────────────────────┘
```

Per-channel override opens the same form prefilled with the channel
row (or empty = inherit). Empty form on save = DELETE the row.

All form actions go through HTMX partial endpoints (consistent with the
existing destinations UI):

- `GET  /partials/pipelines/<pid>/download_settings`
- `POST /partials/pipelines/<pid>/download_settings`
- `GET  /partials/channels/<cid>/download_settings`
- `POST /partials/channels/<cid>/download_settings`
- `POST /partials/yt/probe`  (returns an HTML table of formats)

## 8. Migration & Backwards Compatibility

1. `models.py::init_db()` adds the `CREATE TABLE IF NOT EXISTS` block
   for `download_settings` + the two partial unique indexes.
2. No data migration needed — empty table = pre-feature behaviour.
3. `_startup_recovery_sweep` is unchanged; it doesn't touch this table.
4. Watcher Dockerfile unchanged — only `headless_watcher.py` reads from
   the new table; the import is local (`from download_prefs import …`)
   and the file is copied as part of the watcher build context. **Action:**
   confirm `download_prefs.py` is included in the watcher image or
   re-implemented there (see §10 risk).

## 9. Testing

| Layer | Tests |
|---|---|
| `build_format_selector` | parametrized: each combo of height × codec × container × fps produces the expected string |
| `build_ydl_opts`        | toggles produce/omit the right keys; `extra_ydl_opts_json` invalid JSON is silently ignored; valid JSON merges last |
| `resolve_download_prefs`| channel row > pipeline row > built-in default precedence |
| `/api/yt/probe`         | rejects non-YouTube URL with 400; happy path returns sorted formats |
| HTMX partial            | save → reload renders the new values |

Add to `tests/` alongside the existing `test_phase4.py` style.

## 10. Risks / Open Questions

1. **Two containers reading the same module.** `download_prefs.py` is a
   pure helper — easiest path is to put it under a `dashboard/`-shared
   path and `COPY` it into both the dashboard and watcher images. We
   could also publish it as a tiny shared package. **Decision: dual COPY
   for now**, revisit if more shared code emerges.
2. **Probe latency.** `extract_info(download=False)` on cold cache can
   take 3–10 s. Run on a thread pool, return JSON; don't block the
   request thread for too long. Add a 30 s hard timeout.
3. **YouTube rate limiting on probe.** Probing the same URL repeatedly
   can trigger 429. v1: no caching; if it bites us, add an LRU keyed on
   URL with 5-minute TTL.
4. **"max_height" vs adaptive streams.** yt-dlp's `[height<=N]` works
   reliably for YouTube. Premium 4K formats with no audio variant are
   already handled by the fallback chain in §5.
5. **Container choice and merge.** Selecting `webm` while the video stream
   is avc1 forces a remux that needs FFmpeg. We ship FFmpeg in the watcher
   already — verify path resolution still works.

## 11. Phasing / Build Order

| Phase | Scope | Effort |
|---|---|---|
| **P0 — schema & helper** | Add table + `download_prefs.py` + unit tests. No UI yet. Watcher still uses hard-coded opts. | S |
| **P1 — wire watcher**    | `headless_watcher` reads through `resolve_download_prefs`. Built-in defaults preserve today's behaviour. | S |
| **P2 — pipeline UI**     | HTMX form for pipeline-level prefs only. | M |
| **P3 — probe endpoint**  | `/api/yt/probe` + small "Probe URL" widget on the pipeline form. | M |
| **P4 — channel override**| Same form on each channel row, empty = inherit. | S |
| **P5 — polish**          | "Advanced" extra-opts editor with JSON validation; per-pipeline export/import of the prefs row. | S |

Recommend shipping **P0 → P2** in one PR (skeleton + minimum useful UI),
then P3 / P4 separately.

## 12. Out-of-scope (parking lot)

- Audio-only export profile.
- Per-video override at watch-list-add time.
- Format profiles ("4K archive" vs "720p shorts" preset library).
- Cookie-based authenticated download (member-only videos) — separate feature.
- Bandwidth throttling / concurrent-download cap — belongs in a queue/scheduler RFC, not here.
