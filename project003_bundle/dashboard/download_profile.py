"""
project003 — Download profile helper.

Translates a ``download_profiles`` row into a fully-formed yt-dlp options dict.
Used by the watcher (and any other downloader) so format/quality/subtitle
choices are configurable per-pipeline instead of hard-coded.

A profile is a plain dict (or sqlite3.Row) with these keys — see
``dashboard/models.py`` for the schema & defaults:

  max_height, container, video_codec, audio_codec, audio_only,
  write_subs, write_auto_subs, sub_langs, embed_subs,
  write_thumbnail, embed_thumbnail, embed_chapters,
  skip_shorts, shorts_max_seconds, skip_live, custom_format

The functions here are pure: no DB I/O, no side-effects. They never raise
on bad input — unknown values fall back to safe defaults so the watcher
never crashes mid-batch because of a fat-fingered profile.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional


# Legacy fallback identical to the pre-feature hard-coded value.
_LEGACY_FORMAT = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

_VALID_CONTAINERS = {"mp4", "webm", "mkv", "best"}
_VALID_VCODECS = {"avc1", "vp9", "av01", "any"}
_VALID_ACODECS = {"m4a", "opus", "mp3", "any"}


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return False


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _as_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def build_format_string(profile: Mapping[str, Any]) -> str:
    """Build the yt-dlp ``format`` selector for a profile.

    Order of precedence:
      1. ``custom_format`` (raw escape hatch) wins if non-empty.
      2. ``audio_only`` -> ``bestaudio[ext=...]`` chain.
      3. Otherwise build a ``bestvideo[...]+bestaudio[...]`` chain honoring
         max_height / container / video_codec / audio_codec.
    """
    custom = _as_str(profile.get("custom_format"))
    if custom:
        return custom

    if _as_bool(profile.get("audio_only")):
        acodec = _as_str(profile.get("audio_codec"), "m4a")
        if acodec not in _VALID_ACODECS or acodec == "any":
            return "bestaudio/best"
        # Map our shorthand to yt-dlp's ext filter where possible.
        ext_map = {"m4a": "m4a", "opus": "webm", "mp3": "mp3"}
        ext = ext_map.get(acodec, "m4a")
        return f"bestaudio[ext={ext}]/bestaudio/best"

    height = _as_int(profile.get("max_height"))
    container = _as_str(profile.get("container"), "mp4")
    if container not in _VALID_CONTAINERS:
        container = "mp4"
    vcodec = _as_str(profile.get("video_codec"), "any")
    if vcodec not in _VALID_VCODECS:
        vcodec = "any"
    acodec = _as_str(profile.get("audio_codec"), "m4a")
    if acodec not in _VALID_ACODECS:
        acodec = "m4a"

    # Build video selector filters.
    v_filters: list[str] = []
    if container != "best":
        v_filters.append(f"ext={container}")
    if vcodec != "any":
        v_filters.append(f"vcodec^={vcodec}")
    if height > 0:
        v_filters.append(f"height<={height}")
    v_sel = "bestvideo"
    if v_filters:
        v_sel += "[" + "][".join(v_filters) + "]"

    # Audio selector.
    if acodec == "any":
        a_sel = "bestaudio"
    else:
        ext_map = {"m4a": "m4a", "opus": "webm", "mp3": "mp3"}
        a_sel = f"bestaudio[ext={ext_map.get(acodec,'m4a')}]"

    # Fallback chain: preferred -> any combined -> any height-capped -> best.
    parts = [f"{v_sel}+{a_sel}"]
    if container != "best":
        parts.append(f"best[ext={container}]" + (f"[height<={height}]" if height > 0 else ""))
    if height > 0:
        parts.append(f"best[height<={height}]")
    parts.append("best")
    return "/".join(parts)


import os as _os

# ---------------------------------------------------------------------------
# Cookie file — mount /cookies/cookies.txt into the container and set this
# env var so every yt-dlp call authenticates automatically.
# YOUTUBE_COOKIES_FILE=/cookies/cookies.txt  (set in docker-compose / .env)
# ---------------------------------------------------------------------------
_COOKIES_FILE: str = _os.getenv("YOUTUBE_COOKIES_FILE", "")

# bgutil PO Token provider — talks to the bgutil-provider Docker sidecar
# (brainicism/bgutil-ytdlp-pot-provider) at BGUTIL_BASE_URL (default port 4416).
_BGUTIL_BASE_URL: str = _os.getenv("BGUTIL_BASE_URL", "http://bgutil-provider:4416")


def build_ydl_opts(
    profile: Optional[Mapping[str, Any]],
    *,
    outtmpl: str,
    progress_hooks: Optional[list] = None,
) -> dict:
    """Return a complete yt-dlp options dict for ``profile``.

    ``profile=None`` returns the legacy hard-coded behavior so callers can
    safely no-op when no profile is configured for a pipeline.
    """
    base: dict = {
        "outtmpl": outtmpl,
        "quiet": False,
        "no_warnings": False,
        "writeinfojson": True,
        # Prevent indefinite hangs on slow/stalled YouTube HTTP reads.
        "socket_timeout": 60,
        "retries": 5,
        "fragment_retries": 5,
        # Download each video using N parallel HTTP fragment workers —
        # fully utilises a high-bandwidth connection (500 Mbps+).
        "concurrent_fragment_downloads": int(_os.getenv("FRAGMENT_WORKERS", "4")),
        # Small random sleep between requests to reduce 429 / bot-check rate.
        "sleep_interval_requests": 1,
        "max_sleep_interval_requests": 3,
        # bgutil PO Token extractor arg — auto-fetches Proof-of-Origin tokens
        # from the bgutil-provider sidecar so YouTube doesn't block the request.
        "extractor_args": {
            "youtubepot-bgutilhttp": {"base_url": [_BGUTIL_BASE_URL]},
        },
    }
    # Inject cookies file if provided — fixes YouTube bot-detection / 429.
    if _COOKIES_FILE and _os.path.isfile(_COOKIES_FILE):
        base["cookiefile"] = _COOKIES_FILE
    if progress_hooks:
        base["progress_hooks"] = progress_hooks

    if profile is None:
        base.update({
            "format": _LEGACY_FORMAT,
            "merge_output_format": "mp4",
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "subtitlesformat": "vtt",
            "writethumbnail": True,
            "convert_thumbnails": "jpg",
        })
        return base

    base["format"] = build_format_string(profile)

    container = _as_str(profile.get("container"), "mp4")
    if container in ("mp4", "webm", "mkv"):
        base["merge_output_format"] = container

    audio_only = _as_bool(profile.get("audio_only"))
    if audio_only:
        base["postprocessors"] = base.get("postprocessors", []) + [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": _as_str(profile.get("audio_codec"), "m4a"),
        }]

    # Subtitles.
    base["writesubtitles"] = _as_bool(profile.get("write_subs"))
    base["writeautomaticsub"] = _as_bool(profile.get("write_auto_subs"))
    langs = [s.strip() for s in _as_str(profile.get("sub_langs"), "en").split(",") if s.strip()]
    base["subtitleslangs"] = langs or ["en"]
    base["subtitlesformat"] = "vtt"
    if _as_bool(profile.get("embed_subs")):
        base.setdefault("postprocessors", []).append({"key": "FFmpegEmbedSubtitle"})

    # Thumbnail.
    base["writethumbnail"] = _as_bool(profile.get("write_thumbnail"))
    base["convert_thumbnails"] = "jpg"
    if _as_bool(profile.get("embed_thumbnail")):
        base.setdefault("postprocessors", []).append({"key": "EmbedThumbnail"})

    # Chapters.
    if _as_bool(profile.get("embed_chapters")):
        base.setdefault("postprocessors", []).append({"key": "FFmpegMetadata", "add_chapters": True})

    # Skip live / premieres via match_filter.
    skip_live = _as_bool(profile.get("skip_live"))
    skip_shorts = _as_bool(profile.get("skip_shorts"))
    shorts_max = _as_int(profile.get("shorts_max_seconds"), 60)

    if skip_live or skip_shorts:
        def _match_filter(info_dict: dict, *, incomplete: bool = False) -> Optional[str]:
            if skip_live:
                if info_dict.get("is_live") or info_dict.get("live_status") in (
                    "is_live", "is_upcoming", "post_live"
                ):
                    return "skip: live or premiere"
            if skip_shorts:
                dur = info_dict.get("duration") or 0
                if dur and dur < shorts_max:
                    return f"skip: shorts (<{shorts_max}s)"
            return None
        base["match_filter"] = _match_filter

    return base


def should_skip(profile: Optional[Mapping[str, Any]], info: Mapping[str, Any]) -> Optional[str]:
    """Pre-flight check used before invoking yt-dlp at all.

    Returns a human-readable reason string if the video should be skipped,
    or ``None`` if it's eligible. Mirrors ``match_filter`` but lets callers
    avoid wasted network round-trips when info is already available.
    """
    if not profile:
        return None
    if _as_bool(profile.get("skip_live")):
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
            return "live or premiere"
    if _as_bool(profile.get("skip_shorts")):
        dur = info.get("duration") or 0
        if dur and dur < _as_int(profile.get("shorts_max_seconds"), 60):
            return "shorts"
    return None
