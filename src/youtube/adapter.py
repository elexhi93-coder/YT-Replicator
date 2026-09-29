"""youtube.adapter — the DestinationPlatform port (Pillar 0 Port B).

Everything YouTube-shaped stops here. Above this module there is no status
code, no Google error body and no `googleapiclient` type: the adapter returns
the frozen DTOs from `core.api` and raises the typed errors from
`youtube.errors`, so `delivery` (U10) can be written and tested against a fake
adapter instead of a live channel.

Three behaviours are worth naming:

* **Quota is a first-class error, not a 403 to be parsed later.** A
  `quotaExceeded` becomes `QuotaExhausted`, which `core` classifies as
  transient, so the job is rescheduled for after the Pacific reset instead of
  failing the video.
* **A revoked token is permanent.** Retrying it is how the legacy ended up
  uploading to the wrong channel (D-23).
* **The resumable upload reports progress per chunk**, so a large file shows
  movement, and a dropped connection costs one chunk rather than the upload.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.api import (
    AuthState,
    DestinationVideoDTO,
    InventoryBatch,
    PROVENANCE_MARKER_REGEX,
    UploadOutcome,
    UploadRequest,
)
from youtube.errors import (
    PlatformUnavailable,
    QuotaExhausted,
    Throttled,
    TokenRevoked,
    UploadNotFound,
    UploadRejected,
)
from youtube.http import CHUNK_BYTES, YouTubeHttp

#: The provenance marker is a suffix line. We *extract* it here; `delivery`
#: *interprets* it — Pillar 0 R5 keeps parsing in the caller.
_MARKER_RE = re.compile(r"\[ref:[A-Za-z0-9_-]{11}:\d+\]$")


def translate_error(status: int, body: dict) -> Exception:
    """Map an HTTP status and Google error body to a typed error.

    The whole translation lives in one function so it can be read at once and
    tested exhaustively. The alternative is a status-code branch repeated at
    every call site, where one of them will eventually disagree with the rest.
    """
    block = body.get("error")
    block = block if isinstance(block, dict) else {}
    reason = ""
    for detail in block.get("errors") or []:
        if isinstance(detail, dict) and detail.get("reason"):
            reason = str(detail["reason"])
            break
    reason = reason or str(block.get("status") or "")
    message = str(block.get("message") or body.get("error") or "")

    if status == 429:
        return Throttled(f"YouTube throttled the request: {message}"[:500])
    if status == 401:
        return TokenRevoked("The channel's authorization is no longer valid.")
    if status == 404:
        return UploadNotFound("YouTube has no such upload session or video.")
    if status == 403 and reason == "quotaExceeded":
        return QuotaExhausted("The daily upload quota is spent.")
    if status == 403 and reason in ("forbidden", "youtubeSignupRequired"):
        return TokenRevoked(f"Channel not permitted to upload: {message}"[:500])
    if status in (500, 502, 503, 504):
        return PlatformUnavailable(f"YouTube returned {status}.")
    if status >= 400:
        return UploadRejected(f"YouTube refused the request: {message}"[:500])
    return PlatformUnavailable(f"Unexpected YouTube response ({status}).")


class YouTubePlatform:
    """Port B over the YouTube Data API v3.

    The transport is injected, so the whole adapter is exercised offline. The
    token is never passed in: it comes from `credentials.api.valid_access_token`
    at call time, which is U05's single documented way to obtain one and the
    only way that cannot skip the proactive-refresh rule.
    """

    def __init__(self, *, http: YouTubeHttp | None = None) -> None:
        from youtube.api import default_http

        self._http = http if http is not None else default_http()

    # -- auth -----------------------------------------------------------------

    def probe_auth(self, channel) -> AuthState:
        """Ask Google who the token belongs to; a 200 is proof, a 401 is not.

        The port's abstract signature is `probe_auth(credentials: bytes)`; this
        takes the channel instead, because the encrypted bundle is only ever
        unwrapped inside `credentials.api` (CONTRACT §5.2). No plaintext secret
        appears in any signature here either way.
        """
        from credentials.api import valid_access_token

        token = valid_access_token(channel)
        response = self._call(
            "GET",
            "https://www.googleapis.com/youtube/v3/channels"
            f"?part=snippet&id={channel.channel_id}",
            token,
        )
        items = response.body.get("items") or []
        snippet = items[0].get("snippet", {}) if items else {}
        return AuthState(
            state="valid",
            channel_id=str(snippet.get("channelId") or channel.channel_id),
            channel_title=snippet.get("title") or channel.title or None,
            scopes=tuple(channel.scopes or ()),
            expires_at=channel.token_expires_at,
            refreshed_bundle=None,
        )

    # -- inventory ------------------------------------------------------------

    def sync_inventory(self, channel, cursor: str | None = None, *, token=None):
        """One page of what the channel holds, with the API's own page token.

        Resuming from the cursor means a sync interrupted at page 40 continues
        at page 40 instead of re-listing the channel from the beginning.
        """
        url = (
            "https://www.googleapis.com/youtube/v3/playlistItems"
            f"?part=snippet,contentDetails&playlistId={channel.external_channel_id}"
            "&maxResults=50"
        )
        if cursor:
            url = f"{url}&pageToken={cursor}"
        response = self._call("GET", url, token)
        return InventoryBatch(
            items=tuple(_to_inventory_item(row) for row in response.body.get("items") or []),
            next_cursor=response.body.get("nextPageToken"),
        )

    # -- upload ---------------------------------------------------------------

    def upload(
        self,
        request: UploadRequest,
        *,
        token: str,
        on_progress=None,
    ) -> UploadOutcome:
        """Upload in chunks, reporting progress after each one.

        A dropped connection costs one chunk rather than the whole upload,
        because the session URL is still valid — that is the point of the
        resumable protocol.
        """
        session_url = self._initiate(request, token)
        size = Path(request.media_path).stat().st_size
        sent = 0
        while sent < size:
            end = min(sent + CHUNK_BYTES, size)
            self._http.post_bytes(
                session_url,
                _slice(request.media_path, sent, end),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Range": f"bytes {sent}-{end - 1}/{size}",
                    "Content-Length": str(end - sent),
                },
                timeout=300.0,
            )
            sent = end
            if on_progress is not None:
                on_progress(sent, size)
        return self._finalize(session_url, token)

    def unit_cost_for_upload(self) -> int:
        """What one upload costs against the daily allowance."""
        from youtube.http import METADATA_UNIT_COST, UPLOAD_UNIT_COST

        return UPLOAD_UNIT_COST + METADATA_UNIT_COST

    # -- internals ------------------------------------------------------------

    def _initiate(self, request: UploadRequest, token: str) -> str:
        body = {
            "snippet": {"title": request.title, "description": request.description},
            "status": {
                "privacyStatus": request.privacy,
                "selfDeclaredMadeForKids": request.made_for_kids,
                "containsSyntheticMedia": request.contains_synthetic_media,
            },
        }
        if request.tags:
            body["snippet"]["tags"] = list(request.tags)
        if request.category_id:
            body["snippet"]["categoryId"] = request.category_id
        response = self._call(
            "POST",
            "https://www.googleapis.com/upload/youtube/v3/videos"
            "?uploadType=resumable&part=snippet,status",
            token,
            payload=body,
        )
        headers = response.headers or {}
        location = headers.get("Location") or headers.get("location")
        if not location:
            raise PlatformUnavailable("YouTube did not return an upload session URL.")
        return str(location)

    def _finalize(self, session_url: str, token: str) -> UploadOutcome:
        response = self._call("POST", session_url, token, payload={})
        video_id = str(response.body.get("id") or "")
        if not video_id:
            raise PlatformUnavailable("YouTube returned no video id after upload.")
        status = response.body.get("status") or {}
        return UploadOutcome(
            destination_video_id=video_id,
            destination_url=f"https://youtu.be/{video_id}",
            privacy=str(status.get("privacyStatus") or "unknown"),
            units_used=0,
            http_status=response.status,
            raw_error_code=None,
            thumbnail_uploaded=False,
        )

    def _call(
        self,
        method: str,
        url: str,
        token,
        *,
        payload: dict | None = None,
        headers: dict | None = None,
    ):
        merged = {"Authorization": f"Bearer {token or ''}"}
        merged.update(headers or {})
        if method == "GET":
            response = self._http.get_json(url, headers=merged)
        else:
            response = self._http.post_json(url, payload or {}, headers=merged)
        if response.status >= 400:
            raise translate_error(response.status, response.body)
        return response


def _to_inventory_item(row: dict):
    """One `playlistItems` row to the port's DTO — no raw Google type escapes."""
    snippet = row.get("snippet") or {}
    description = str(snippet.get("description") or "")
    marker = _MARKER_RE.search(description) or PROVENANCE_MARKER_REGEX.search(description)
    return DestinationVideoDTO(
        destination_video_id=str(
            (snippet.get("resourceId") or {}).get("videoId") or ""
        ),
        title=str(snippet.get("title") or ""),
        description_excerpt=description[:500],
        published_at=None,  # playlistItems omits it; the video fetch carries it
        privacy_status=str(snippet.get("privacyStatus") or "unknown"),
        duration_sec=None,
        marker=marker.group(0) if marker else None,
    )


def _slice(path, start: int, end: int) -> bytes:
    with Path(path).open("rb") as handle:
        handle.seek(start)
        return handle.read(end - start)


__all__ = ["YouTubePlatform", "translate_error"]
