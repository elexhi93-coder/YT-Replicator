from __future__ import annotations

"""youtube.http — the module's only network seam.

The adapter above this file never sees a socket, a status code or a Google
error shape; it sees this protocol, and every failure arrives already
translated into `youtube.errors`. That is what lets the whole module be tested
without a network (`FakeHttp` in the tests) and what keeps a Google API change
from rippling into `delivery`.

The resumable upload is three calls, not one: `initiate` opens a session and
returns the URL to PUT bytes to, `upload_chunk` sends one Content-Range, and
`finalize` reads the finished video. Progress is reported after each chunk, so
a 4 GB video shows movement instead of a spinner.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

#: YouTube's daily allowance (10 000 units) and what an upload costs. These
#: are the platform's published numbers, restated in one place so the quota
#: arithmetic in `api.py` can be read without a lookup.
DAILY_UNIT_LIMIT = 10_000
UPLOAD_UNIT_COST = 1_600
METADATA_UNIT_COST = 50
THUMBNAIL_UNIT_COST = 50

#: Chunk size for the resumable upload. 8 MiB is Google's recommended
#: multiple; it keeps a dropped connection cheap to retry.
CHUNK_BYTES = 8 * 1024 * 1024

from youtube.errors import PlatformUnavailable

_API_ROOT = "https://www.googleapis.com/youtube/v3"
_UPLOAD_ROOT = "https://www.googleapis.com/upload/youtube/v3"


@dataclass(frozen=True)
class HttpResponse:
    """A translated response: the status, the parsed body, the raw text."""

    status: int
    body: dict
    text: str = ""
    headers: dict | None = None


class YouTubeHttp(Protocol):
    """The calls the adapter makes. Implementations must translate errors."""

    def get_json(self, url: str, *, headers: dict, timeout: float = 30.0) -> HttpResponse: ...

    def post_json(
        self, url: str, payload: dict, *, headers: dict, timeout: float = 30.0
    ) -> HttpResponse: ...

    def post_bytes(
        self,
        url: str,
        payload: bytes,
        *,
        headers: dict,
        timeout: float = 120.0,
    ) -> HttpResponse: ...


class UrllibHttp:
    """The real transport. It never raises an HTTP error: it translates one.

    A raw `urllib.error.HTTPError` escaping into the adapter would mean every
    call site repeats the same status-code mapping, and one of them would
    eventually get it wrong.
    """

    def __init__(self, *, opener=None, sleep=time.sleep) -> None:
        self._opener = opener or urllib.request.urlopen
        self._sleep = sleep

    def get_json(self, url: str, *, headers: dict, timeout: float = 30.0) -> HttpResponse:
        return self._send("GET", url, None, headers, timeout)

    def post_json(
        self, url: str, payload: dict, *, headers: dict, timeout: float = 30.0
    ) -> HttpResponse:
        return self._send(
            "POST",
            url,
            json.dumps(payload).encode("utf-8"),
            {**headers, "Content-Type": "application/json"},
            timeout,
        )

    def post_bytes(
        self, url: str, payload: bytes, *, headers: dict, timeout: float = 120.0
    ) -> HttpResponse:
        return self._send("POST", url, payload, headers, timeout)

    def _send(
        self, method: str, url: str, payload, headers: dict, timeout: float
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=payload, method=method)
        for name, value in headers.items():
            request.add_header(name, value)
        try:
            with self._opener(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", "replace")
                return HttpResponse(
                    status=getattr(response, "status", 200),
                    body=_parse(text),
                    text=text,
                    headers=dict(response.headers or {}),
                )
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            return HttpResponse(
                status=exc.code, body=_parse(text), text=text,
                headers=dict(exc.headers or {}),
            )
        except TimeoutError as exc:
            raise PlatformUnavailable(f"YouTube request timed out: {exc}") from exc
        except OSError as exc:
            raise PlatformUnavailable(f"YouTube request failed: {exc}") from exc


def _parse(text: str) -> dict:
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = [
    "CHUNK_BYTES",
    "DAILY_UNIT_LIMIT",
    "METADATA_UNIT_COST",
    "THUMBNAIL_UNIT_COST",
    "UPLOAD_UNIT_COST",
    "HttpResponse",
    "UrllibHttp",
    "YouTubeHttp",
]
