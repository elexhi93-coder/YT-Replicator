from __future__ import annotations

"""
credentials.http — the module's only network seam.

Every outbound call in `credentials` goes through an object with two methods,
`post_form()` and `get_json()`. Tests inject a fake (see
`tests/test_credentials.py`) so no test ever touches the network, and the real
implementation is one place to inspect when something cannot reach Google.

`urllib` is deliberate: the app already ships `urllib` for `youtube`'s OAuth
dance in the legacy, and adding `requests` for four calls is not worth a
dependency the operator has to trust.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping

USER_AGENT = "YT-Replicator/0.1 (+https://github.com/elexhi93-coder/YT-Replicator)"


@dataclass(frozen=True)
class HttpResponse:
    """A response reduced to what the OAuth layer actually needs."""

    status: int
    body: dict[str, Any] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    text: str = ""

    @property
    def location(self) -> str:
        """`Location` header (uploads) or `Range` header (resumable queries)."""
        for key, value in self.headers.items():
            if key.lower() == "location":
                return value
        return ""


class HttpClient:
    """Interface implemented by `UrllibHttpClient` and by test doubles."""

    def post_form(
        self,
        url: str,
        data: Mapping[str, str],
        timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:  # pragma: no cover - interface
        raise NotImplementedError

    def get_json(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:  # pragma: no cover - interface
        raise NotImplementedError


def _decode(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


class UrllibHttpClient(HttpClient):
    """Real transport. Reads the body and status; never raises on 4xx/5xx."""

    def post_form(
        self,
        url: str,
        data: Mapping[str, str],
        timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        payload = urllib.parse.urlencode(dict(data)).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        return self._send(request, timeout, headers)

    def get_json(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        request = urllib.request.Request(url, method="GET")
        return self._send(request, timeout, headers)

    def _send(
        self,
        request: urllib.request.Request,
        timeout: float,
        headers: Mapping[str, str] | None,
    ) -> HttpResponse:
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Accept", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return HttpResponse(
                    status=int(response.status),
                    body=_decode(raw),
                    headers=dict(response.headers.items()),
                    text=raw.decode("utf-8", errors="replace"),
                )
        except urllib.error.HTTPError as exc:  # 4xx/5xx: a normal outcome here
            raw = exc.read()
            return HttpResponse(
                status=int(exc.code),
                body=_decode(raw),
                headers=dict(exc.headers.items()) if exc.headers else {},
                text=raw.decode("utf-8", errors="replace"),
            )
        except urllib.error.URLError as exc:
            # No HTTP status at all: surface it as status 0 so callers can
            # classify it as a transient network failure (`NetworkError`).
            return HttpResponse(status=0, body={"error": "url_error", "detail": str(exc)})
