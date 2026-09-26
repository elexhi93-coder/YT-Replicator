"""
project003 — YouTube OAuth2 helper for the dashboard.

Flow:
  1) User opens /oauth/youtube/start  → redirected to Google consent screen.
  2) Google redirects back to /oauth/youtube/callback?code=...
  3) We exchange the code for tokens, store them in `oauth_tokens`.

Env vars required:
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REDIRECT_URI   (e.g. http://localhost:8080/oauth/youtube/callback)
"""
from __future__ import annotations

import os
# Google may grant *additional* scopes (e.g. youtube.force-ssl, youtubepartner)
# beyond what we requested; oauthlib treats that as an error unless we relax.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # http://localhost
from datetime import datetime
from typing import Optional

try:
    from dashboard.models import get_db
    from dashboard import projects as yt_projects
except ModuleNotFoundError:
    from models import get_db
    import projects as yt_projects  # type: ignore

YT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    # Lets us read the Google account's email + display name on first auth
    # so we can show "owner: studio@gmail.com" on the channel card. Cheap
    # and the user already sees these in the consent screen.
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

# Module-level cache for the PKCE code_verifier produced during the auth-URL
# build, which must be replayed during the token exchange. Single-user app, so
# a simple dict keyed by `state` is enough.
_PKCE_CACHE: dict[str, str] = {}


def _utcnow_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _client_config(project_id: Optional[int] = None) -> dict:
    """Return the OAuth web client config for either a stored project
    (preferred) or the legacy env-var fallback.
    """
    cid = csec = ""
    if project_id:
        proj = yt_projects.get_project(int(project_id))
        if not proj:
            raise RuntimeError(f"YouTube project id={project_id} not found.")
        cid, csec = proj["client_id"], proj["client_secret"]
    if not (cid and csec):
        cid = os.getenv("YOUTUBE_CLIENT_ID", "")
        csec = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    if not (cid and csec):
        raise RuntimeError(
            "No YouTube OAuth client configured. Add a project on /projects "
            "or set YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET."
        )
    return {
        "web": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _redirect_uri() -> str:
    return os.getenv(
        "YOUTUBE_REDIRECT_URI",
        "http://localhost:8080/oauth/youtube/callback",
    )


def build_auth_url(project_id: Optional[int] = None) -> tuple[str, str]:
    """Return (auth_url, state). State should be stored in session/cookie.

    `project_id` selects which YouTube Cloud project's client_id/secret to
    use; if omitted, falls back to YOUTUBE_CLIENT_ID env vars.
    """
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        _client_config(project_id),
        scopes=YT_SCOPES,
        redirect_uri=_redirect_uri(),
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force refresh_token
    )
    if project_id:
        _PKCE_CACHE[f"_proj:{state}"] = str(int(project_id))
        _PKCE_CACHE["_last_proj"] = str(int(project_id))
    # Cache the auto-generated PKCE verifier so we can replay it on exchange.
    if getattr(flow, "code_verifier", None):
        _PKCE_CACHE[state] = flow.code_verifier
        _PKCE_CACHE["_last"] = flow.code_verifier  # fallback if state lost
    return auth_url, state


def exchange_code(code: str, state: str | None = None) -> dict:
    """Exchange auth code for tokens, persist in DB. Returns the row dict."""
    from google_auth_oauthlib.flow import Flow
    project_id_str = (state and _PKCE_CACHE.get(f"_proj:{state}")) or _PKCE_CACHE.get("_last_proj")
    project_id = int(project_id_str) if project_id_str else None
    flow = Flow.from_client_config(
        _client_config(project_id),
        scopes=YT_SCOPES,
        redirect_uri=_redirect_uri(),
    )
    # Replay the PKCE verifier so Google accepts the exchange.
    verifier = (state and _PKCE_CACHE.get(state)) or _PKCE_CACHE.get("_last")
    if verifier:
        flow.code_verifier = verifier
    flow.fetch_token(code=code)
    creds = flow.credentials

    expiry = creds.expiry.strftime("%Y-%m-%dT%H:%M:%S") if creds.expiry else ""
    scopes_str = " ".join(creds.scopes or YT_SCOPES)

    # Probe Google for the channel + owner identity behind this token.
    # 1 quota unit (channels.list) + free (userinfo). Best-effort: a
    # failure here does not block storing the token.
    detected = {"channel_id": "", "title": "", "thumbnail_url": "",
                "owner_email": "", "owner_display_name": ""}
    try:
        try:
            from dashboard.youtube_channels import detect_from_credentials
        except ModuleNotFoundError:
            from youtube_channels import detect_from_credentials  # type: ignore
        detected = detect_from_credentials(creds)
    except Exception:
        pass
    account_label = detected.get("title") or ""
    youtube_channel_row_id: Optional[int] = None
    if detected.get("channel_id"):
        try:
            try:
                from dashboard.youtube_channels import upsert_channel
            except ModuleNotFoundError:
                from youtube_channels import upsert_channel  # type: ignore
            youtube_channel_row_id = upsert_channel(**detected)
        except Exception:
            youtube_channel_row_id = None

    conn = get_db()
    try:
        # One token row per (platform, project_id). project_id may be NULL
        # for legacy env-var-only setups.
        if project_id:
            existing = conn.execute(
                "SELECT id FROM oauth_tokens WHERE platform='youtube' AND project_id=?",
                (project_id,),
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM oauth_tokens WHERE platform='youtube' AND project_id IS NULL"
            ).fetchone()
        if existing:
            conn.execute(
                """UPDATE oauth_tokens SET
                       access_token=?, refresh_token=?, token_expiry=?,
                       scopes=?, account_label=?, project_id=?,
                       youtube_channel_id=?, last_refreshed_at=?,
                       updated_at=?
                   WHERE id=?""",
                (
                    creds.token,
                    creds.refresh_token or "",
                    expiry,
                    scopes_str,
                    account_label,
                    project_id,
                    youtube_channel_row_id,
                    _utcnow_iso(),
                    _utcnow_iso(),
                    existing["id"],
                ),
            )
            row_id = existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO oauth_tokens
                       (platform, account_label, access_token, refresh_token,
                        token_expiry, scopes, project_id,
                        youtube_channel_id, last_refreshed_at)
                   VALUES ('youtube', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    account_label,
                    creds.token,
                    creds.refresh_token or "",
                    expiry,
                    scopes_str,
                    project_id,
                    youtube_channel_row_id,
                    _utcnow_iso(),
                ),
            )
            row_id = cur.lastrowid
        # Mirror the channel binding onto the project row so the projects
        # list can group/filter by channel without a JOIN.
        if project_id and youtube_channel_row_id:
            conn.execute(
                "UPDATE youtube_projects SET youtube_channel_id=?, updated_at=? "
                "WHERE id=?",
                (youtube_channel_row_id, _utcnow_iso(), project_id),
            )
        row = conn.execute(
            "SELECT * FROM oauth_tokens WHERE id=?", (row_id,)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def get_status() -> dict:
    """Return whether at least one YT token is stored.

    Aggregates across projects: `connected` is True if any token exists,
    `accounts` lists every connected (channel, project) pair.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT t.*, p.label AS project_label "
            "  FROM oauth_tokens t "
            "  LEFT JOIN youtube_projects p ON p.id = t.project_id "
            " WHERE t.platform='youtube' "
            " ORDER BY t.id ASC"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {"connected": False, "accounts": []}
    accounts = [
        {
            "id": r["id"],
            "label": r["account_label"] or "(unknown)",
            "project_id": r["project_id"],
            "project_label": r["project_label"] or "(env var fallback)",
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]
    primary = rows[0]
    return {
        "connected": True,
        "account_label": primary["account_label"] or "(unknown)",
        "updated_at": primary["updated_at"],
        "accounts": accounts,
    }
