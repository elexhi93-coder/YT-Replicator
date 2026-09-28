from __future__ import annotations

"""
sources.provider — v1 YouTube SourceProvider over yt-dlp (Pillar 0 port A).

Only this module imports yt-dlp. Every extractor call is flat (no media
bytes), bounded in time, and never retried internally — retry belongs to
`jobs` (Pillar 0 R3/R6). Typed errors only: resolution failures are
`SourceUnresolvable`, throttles are `HydrationRateLimited` (transient),
missing extractors are `ProviderUnavailable` (transient).

No database writes here (Pillar 0 R2). The provider returns DTOs and
`sources.api` decides what gets persisted.
"""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Iterator

from core.api import (
    MaterializedMedia,
    MaterializeRequest,
    ResolvedSource,
    SourceItem,
    SourceItemDetail,
    SourceRef,
    VideoRef,
    now_utc,
)
from sources.errors import (
    HydrationRateLimited,
    ItemGone,
    ProviderUnavailable,
    SourceUnresolvable,
)
from sources.urls import normalize_source_url

_YTDLP_TIMEOUT_SEC = 300
_HYDRATE_TIMEOUT_SEC = 30

# yt-dlp speaks `is_live`/`post_live`; the port speaks `live`/`was_live`.
_LIVE_STATUS = {"is_live": "live", "post_live": "was_live"}


def _run_ytdlp(args: list[str], timeout: int) -> dict:
    """Run yt-dlp and parse its single-document output.

    The caller owns the flags (`-J` for a full dump, `--skip-download`, …) so
    the invocation mode is visible at the call site; this only adds the
    boilerplate timeout and the error translation.
    """
    if shutil.which("yt-dlp") is None:
        raise ProviderUnavailable("yt-dlp executable is not installed.")
    try:
        proc = subprocess.run(
            ["yt-dlp", "--no-warnings", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderUnavailable(f"yt-dlp timed out: {exc}") from exc
    except OSError as exc:
        raise ProviderUnavailable(f"yt-dlp failed to run: {exc}") from exc
    if proc.returncode != 0:
        _raise_for_stderr(proc.stderr or "")
    try:
        parsed = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SourceUnresolvable(f"yt-dlp returned unparseable output: {exc}") from exc
    return parsed if isinstance(parsed, dict) else {}


def _to_epoch(value: object) -> datetime | None:
    """yt-dlp timestamps to a UTC datetime; anything unusable becomes None."""
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(float(str(value)), tz=timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _to_item(row: dict) -> SourceItem | None:
    """Map one flat yt-dlp row to a `SourceItem`; None if it has no video id."""
    video_id = str(row.get("id") or "").strip()
    if not video_id:
        return None
    live_status = str(row.get("live_status") or "not_live")
    thumbnail = row.get("thumbnail")
    duration = row.get("duration")
    return SourceItem(
        video_id=video_id,
        title=str(row.get("title") or ""),
        published_at=_to_epoch(row.get("timestamp")),
        duration_sec=int(duration) if duration else None,
        thumbnail_url=str(thumbnail) if thumbnail else None,
        live_status=_LIVE_STATUS.get(live_status, live_status),
        availability=str(row.get("availability") or "unknown"),
    )


def source_provider_factory():
    """The `SourceProvider` binding the port registry installs (Pillar 0 §4)."""
    return YouTubeSourceProvider()


class YouTubeSourceProvider:
    """Port A over yt-dlp — the only place that shells out to it."""

    def resolve(self, raw_url: str) -> ResolvedSource:
        """Turn operator input into a canonical identity. Never retries (R6)."""
        normalized = normalize_source_url(raw_url)
        # A playlist or a /channel/UC… URL already carries its canonical id, so
        # resolving it costs no round trip. Only a handle needs the platform.
        if normalized.external_id:
            return ResolvedSource(
                kind=normalized.kind,
                external_id=normalized.external_id,
                canonical_url=normalized.url,
                title=None,
            )
        info = _run_ytdlp(["-J", normalized.url], _YTDLP_TIMEOUT_SEC)
        external_id = str(
            info.get("channel_id") or info.get("uploader_id") or info.get("id") or ""
        )
        if not external_id:
            raise SourceUnresolvable(f"{raw_url!r} resolved to no channel id.")
        return ResolvedSource(
            kind="channel",
            external_id=external_id,
            canonical_url=normalized.url,
            title=info.get("channel") or info.get("uploader") or None,
        )

    def scan(self, source: SourceRef, since: datetime | None) -> Iterator[SourceItem]:
        """Flat, metadata-only enumeration (INV-7: never touch media bytes)."""
        for row in _run_ytdlp_lines(
            ["--flat-playlist", "--dump-json", source.url], _YTDLP_TIMEOUT_SEC
        ):
            item = _to_item(row)
            if item is not None:
                yield item

    def hydrate(self, item: VideoRef) -> SourceItemDetail:
        """One expensive per-video call: description, tags, counts (Pillar 1 §4)."""
        info = _run_ytdlp(
            [
                "--skip-download",
                "-J",
                f"https://www.youtube.com/watch?v={item.video_id}",
            ],
            _HYDRATE_TIMEOUT_SEC,
        )
        return SourceItemDetail(
            video_id=item.video_id,
            description=info.get("description"),
            tags=tuple(str(tag) for tag in (info.get("tags") or [])),
            category_id=info.get("category_id") or None,
            view_count=info.get("view_count"),
            like_count=info.get("like_count"),
            hydrated_at=now_utc(),
        )

    def materialize(self, request: MaterializeRequest) -> MaterializedMedia:
        """Deliberately unimplemented here — downloads are `media`'s (U11).

        Port A declares the method so the contract is complete, but file
        bytes belong to the `media` module (docs/04 §2), and INV-7 keeps
        `sources` to metadata only.
        """
        raise NotImplementedError(
            "Materialization belongs to the media module (U11), not sources."
        )


def _raise_for_stderr(stderr: str) -> None:
    """Map a yt-dlp failure to one typed error (Pillar 0 R1)."""
    text = (stderr or "").lower()
    if "429" in text or "too many requests" in text:
        raise HydrationRateLimited("YouTube throttled the request (HTTP 429).")
    if "private" in text or "unavailable" in text or "not found" in text:
        raise ItemGone(text.strip() or "item unavailable")
    raise SourceUnresolvable(text.strip() or "source could not be resolved")


def _run_ytdlp_lines(args: list[str], timeout: int) -> list[dict]:
    """Run yt-dlp for a *playlist* and return one dict per line (NDJSON).

    `--flat-playlist` emits newline-delimited JSON, not a single document, so
    it cannot go through `_run_ytdlp`. A blank line is not an error; an
    unparseable one is, because it means yt-dlp is not what we think it is.
    """
    if shutil.which("yt-dlp") is None:
        raise ProviderUnavailable("yt-dlp executable is not installed.")
    try:
        proc = subprocess.run(
            ["yt-dlp", "--no-warnings", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderUnavailable(f"yt-dlp timed out: {exc}") from exc
    except OSError as exc:
        raise ProviderUnavailable(f"yt-dlp failed to run: {exc}") from exc
    if proc.returncode != 0:
        _raise_for_stderr(proc.stderr or "")
    rows: list[dict] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SourceUnresolvable(
                f"yt-dlp returned unparseable output: {exc}"
            ) from exc
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows
