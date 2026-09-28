from __future__ import annotations

"""
sources.urls — the two guards every operator-supplied URL passes (INV-7).

Pure functions, no I/O, so they are cheap to test and impossible to bypass by
accident: `normalize_source_url()` is the *only* way an inbound URL becomes a
`ResolvedSource` request, and it validates the SSRF allow-list first.

Rules (Pillar 1 §4):

1. Scheme must be `https` (or a bare handle, which becomes `https://www.youtube.com/@handle`).
2. Host must be on the allow-list below — IP literals, `localhost` and every
   other domain are rejected before a request could ever be made.
3. Channel URLs get a `/videos` suffix unless the path already selects a tab
   (`/videos`, `/streams`, `/shorts`): this is the legacy's fix for a channel
   that silently returns shorts or nothing.
4. `list=PL…` means playlist; `/channel/UC…` means channel with a known id.
   Handles (`/@name`, `/c/name`, `/user/name`) are kept as candidates and have
   their canonical id resolved by the provider.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from core.api import is_safe_ssrf_url
from sources.errors import SourceUrlInvalid

ALLOWED_HOSTS: tuple[str, ...] = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
)

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
PLAYLIST_ID_RE = re.compile(r"^(PL|UU|OL|FL)[A-Za-z0-9_-]+$")
_HANDLE_PREFIXES = ("@", "c/", "user/")
_TAB_SUFFIXES = ("/videos", "/streams", "/shorts")


@dataclass(frozen=True)
class NormalizedSource:
    """The safe, canonical shape of an operator's input."""

    kind: str                      # 'channel' | 'playlist'
    external_id: str | None        # known canonical id, else None (resolved later)
    url: str                       # normalised URL, safe to fetch
    raw: str                       # exactly what the operator typed


def to_https(raw: str) -> str:
    """Accept `@handle`, `youtube.com/@x` and full URLs; reject everything else."""
    candidate = (raw or "").strip()
    if not candidate:
        raise SourceUrlInvalid("Enter a YouTube channel or playlist URL.")
    if candidate.startswith("@"):
        candidate = f"https://www.youtube.com/{candidate}"
    elif not candidate.lower().startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    if candidate.lower().startswith("http://"):
        raise SourceUrlInvalid("Only https URLs are accepted.")
    return candidate


def normalize_source_url(raw: str) -> NormalizedSource:
    """Validate and canonicalise an operator URL. Raises `SourceUrlInvalid`."""
    candidate = to_https(raw)
    if not is_safe_ssrf_url(candidate, ALLOWED_HOSTS):
        raise SourceUrlInvalid(
            f"{raw!r} is not an allowed YouTube URL. Use a youtube.com channel or "
            "playlist link, or an @handle."
        )

    parsed = urlparse(candidate)
    query = parse_qs(parsed.query)
    path = parsed.path.rstrip("/") or ""

    playlist_ids = query.get("list") or []
    if playlist_ids and PLAYLIST_ID_RE.match(playlist_ids[0]):
        playlist_id = playlist_ids[0]
        return NormalizedSource(
            kind="playlist",
            external_id=playlist_id,
            url=f"https://www.youtube.com/playlist?list={playlist_id}",
            raw=raw,
        )

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        raise SourceUrlInvalid(
            f"{raw!r} has no channel, handle or playlist in it."
        )

    first = segments[0]
    if first == "channel" and len(segments) >= 2 and CHANNEL_ID_RE.match(segments[1]):
        return _channel(segments[1], raw)
    if first.startswith(_HANDLE_PREFIXES):
        return _channel(None, raw, url=_with_videos_tab(candidate))
    if first in ("playlist", "watch", "shorts", "embed"):
        raise SourceUrlInvalid(
            "A single video is not a source. Register a channel or playlist."
        )
    raise SourceUrlInvalid(
        f"{raw!r} is not a channel, handle or playlist URL."
    )


def _channel(external_id: str | None, raw: str, url: str | None = None) -> NormalizedSource:
    return NormalizedSource(
        kind="channel",
        external_id=external_id,
        url=url or f"https://www.youtube.com/channel/{external_id}",
        raw=raw,
    )


def _with_videos_tab(url: str) -> str:
    """Channel URLs get `/videos` so a scan cannot pick up a tab by accident."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith(_TAB_SUFFIXES):
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    return f"{parsed.scheme}://{parsed.netloc}{path}/videos"
