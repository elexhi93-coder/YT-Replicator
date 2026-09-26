"""
project003 — Dashboard-side AI metadata enrichment fallback.

Why this module exists
----------------------
The n8n workflow has its own `AI: Enrich Metadata` node, but it is optional
and silently falls back to ``ai_used=False`` if the OpenRouter credential is
not configured (or the API call fails). Result: every row in
``upload_results`` ends up with ``ai_used=0`` and there is no visible signal
about *why*.

This module gives the dashboard a self-contained way to call the same
OpenRouter endpoint when:

  * the inbound /api/upload/youtube body did not include ai data, AND
  * the ``OPENROUTER_API_KEY`` environment variable is set on the dashboard
    container.

It is intentionally:
  * **Best-effort** — never raises into the upload path; failures return
    ``(False, None, "<reason>")`` so the upload still proceeds with the
    original title/description.
  * **Cheap** — short timeout, single HTTP request, no retries.
  * **Toggleable** — set ``AI_ENRICH_ENABLED=0`` to disable entirely.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Optional, Tuple


_DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")
_TIMEOUT = float(os.getenv("AI_ENRICH_TIMEOUT", "20"))
_ENABLED = os.getenv("AI_ENRICH_ENABLED", "1") not in ("0", "false", "False", "")


_SYSTEM_PROMPT = (
    "You are a YouTube SEO expert. Return ONLY a raw JSON object (no markdown) "
    "with keys: youtube_title (string, max 100 chars), "
    "youtube_description (string, 150-300 chars), "
    "youtube_tags (array of 10-15 strings)."
)


def is_configured() -> bool:
    """True iff the dashboard has everything needed to call OpenRouter."""
    return _ENABLED and bool(os.getenv("OPENROUTER_API_KEY"))


def enrich(title: str, channel_name: str = "") -> Tuple[bool, Optional[dict], str]:
    """Attempt one OpenRouter completion.

    Returns ``(ok, data, reason)``:
      * ``ok=True``  → ``data`` is ``{youtube_title, youtube_description, youtube_tags}``.
      * ``ok=False`` → ``data is None``; ``reason`` describes why (for logging).

    Never raises. Safe to call from any request handler.
    """
    if not _ENABLED:
        return (False, None, "disabled")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return (False, None, "no_api_key")
    if not title:
        return (False, None, "no_title")

    payload = {
        "model": _DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Title: {title}\nChannel: {channel_name or '(unknown)'}"},
        ],
        "temperature": 0.7,
        "max_tokens": 600,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/project003",
            "X-Title": "project003 Channel Replicator",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return (False, None, f"http_{e.code}")
    except urllib.error.URLError as e:
        return (False, None, f"url_error:{e.reason}")
    except Exception as e:                                       # noqa: BLE001
        return (False, None, f"exception:{type(e).__name__}")

    try:
        envelope = json.loads(raw)
        content = envelope["choices"][0]["message"]["content"]
        # Strip code-fences if present.
        cleaned = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return (False, None, f"parse_error:{type(e).__name__}")

    # Sanity-check shape.
    title_out = (data.get("youtube_title") or "").strip()
    desc_out = (data.get("youtube_description") or "").strip()
    tags_out = data.get("youtube_tags") or []
    if not title_out or not isinstance(tags_out, list):
        return (False, None, "bad_shape")

    return (True, {
        "youtube_title": title_out[:100],
        "youtube_description": desc_out[:4900],
        "youtube_tags": [str(t)[:30] for t in tags_out if t][:15],
    }, "ok")
