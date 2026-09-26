from __future__ import annotations

"""
YT-Replicator — SSRF and URL Whitelist Validator.

Prevents Server-Side Request Forgery by ensuring all source and ingestion
URLs adhere strictly to verified YouTube endpoints.
"""

import re
from urllib.parse import urlparse
from core.exceptions import SSRFSecurityError

YOUTUBE_ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

# Regex to match YouTube video IDs (11 chars: alphanumeric, -, _)
YOUTUBE_VIDEO_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def validate_youtube_url(url: str) -> str:
    """Validate that a URL is a legitimate YouTube endpoint.

    Raises SSRFSecurityError if the URL targets a private IP, internal host,
    or non-YouTube domain.
    Returns the normalized URL if valid.
    """
    url = (url or "").strip()
    if not url:
        raise SSRFSecurityError("Empty URL provided")

    # Add default scheme if omitted
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise SSRFSecurityError(f"Disallowed URL scheme: {parsed.scheme}")

    hostname = (parsed.hostname or "").lower()
    if hostname not in YOUTUBE_ALLOWED_HOSTS:
        raise SSRFSecurityError(
            f"SSRF violation: host '{hostname}' is not in YouTube allow-list",
            details={"hostname": hostname, "url": url},
        )

    return url


def extract_video_id(url_or_id: str) -> str | None:
    """Extract and validate an 11-character YouTube video ID.

    Accepts raw video IDs (e.g. 'dQw4w9WgXcQ') or full YouTube URLs.
    """
    val = (url_or_id or "").strip()
    if YOUTUBE_VIDEO_ID_REGEX.match(val):
        return val

    try:
        parsed = urlparse(val if val.startswith(("http://", "https://")) else f"https://{val}")
        if parsed.hostname == "youtu.be":
            vid = parsed.path.lstrip("/").split("/")[0]
            if YOUTUBE_VIDEO_ID_REGEX.match(vid):
                return vid
        elif parsed.hostname in YOUTUBE_ALLOWED_HOSTS:
            from urllib.parse import parse_qs
            query = parse_qs(parsed.query)
            if "v" in query and query["v"]:
                vid = query["v"][0]
                if YOUTUBE_VIDEO_ID_REGEX.match(vid):
                    return vid
            # Short URLs (/shorts/VIDEO_ID)
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "v"):
                if YOUTUBE_VIDEO_ID_REGEX.match(parts[1]):
                    return parts[1]
    except Exception:
        pass

    return None
