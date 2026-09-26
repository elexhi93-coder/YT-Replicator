"""
n8n Webhook Integration for IDM-YT
Fires HTTP POST payloads to n8n webhook URLs after download events.

Each channel can have its own webhook URL for per-channel routing in n8n.
A global fallback webhook URL is used if no per-channel URL is set.

Payload schema sent to n8n:
{
    "event":        "download_completed",
    "title":        "Video Title",
    "file_path":    "C:/Users/.../Downloads/Video Title.mp4",
    "source_url":   "https://www.youtube.com/watch?v=...",
    "channel_name": "Channel Name",
    "channel_id":   "UCxxxx",
    "channel_url":  "https://www.youtube.com/@Channel",
    "duration":     847,
    "timestamp":    "2026-04-18T14:30:00",
    "extra":        {}   # Optional extra fields
}
"""

import json
import threading
import logging
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, Callable, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# Config file stores global + per-channel webhook URLs
WEBHOOK_CONFIG_FILE = Path(__file__).parent / "n8n_webhook_config.json"


class WebhookConfig:
    """Manages global and per-channel webhook URLs."""

    def __init__(self):
        self.global_url: str = ""
        self.enabled: bool = True
        self.channel_urls: Dict[str, str] = {}   # {channel_id: webhook_url}
        self._load()

    def _load(self):
        """Load config from disk."""
        try:
            if WEBHOOK_CONFIG_FILE.exists():
                with open(WEBHOOK_CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.global_url = data.get("global_url", "")
                self.enabled = data.get("enabled", True)
                self.channel_urls = data.get("channel_urls", {})
        except Exception as e:
            logger.warning(f"Could not load webhook config: {e}")

    def save(self):
        """Persist config to disk."""
        try:
            data = {
                "global_url": self.global_url,
                "enabled": self.enabled,
                "channel_urls": self.channel_urls,
            }
            with open(WEBHOOK_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save webhook config: {e}")

    def get_url_for_channel(self, channel_id: str) -> str:
        """
        Return the webhook URL for a specific channel.
        Falls back to the global URL if none is set for that channel.
        """
        return self.channel_urls.get(channel_id, "") or self.global_url

    def set_channel_url(self, channel_id: str, url: str):
        """Set a per-channel webhook URL."""
        self.channel_urls[channel_id] = url
        self.save()

    def remove_channel_url(self, channel_id: str):
        """Remove a per-channel webhook URL (falls back to global)."""
        self.channel_urls.pop(channel_id, None)
        self.save()


# Singleton config instance
_config = WebhookConfig()


def get_config() -> WebhookConfig:
    """Return the global webhook config instance."""
    return _config


def fire_webhook(
    video_data: Dict[str, Any],
    file_path: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Fire a webhook POST to n8n in a background thread (non-blocking).

    Args:
        video_data: Dict with keys: url, title, channel, channel_id,
                    channel_url, duration (optional)
        file_path:  Local path where the file was saved
        log_callback: Optional callable for logging to the GUI
    """
    if not _config.enabled:
        return

    channel_id = video_data.get("channel_id", "")
    webhook_url = _config.get_url_for_channel(channel_id)

    if not webhook_url:
        return  # No webhook configured — silently skip

    payload = {
        "event": "download_completed",
        "title": video_data.get("title", "Unknown"),
        "file_path": file_path or "",
        "source_url": video_data.get("url", ""),
        "channel_name": video_data.get("channel", "Unknown"),
        "channel_id": channel_id,
        "channel_url": video_data.get("channel_url", ""),
        "duration": video_data.get("duration", 0),
        "timestamp": datetime.now().isoformat(),
        "extra": video_data.get("extra", {}),
    }

    def _send():
        try:
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = resp.getcode()
            msg = f"🔗 n8n webhook fired → {webhook_url} (HTTP {status})"
            logger.info(msg)
            if log_callback:
                log_callback(msg)
        except urllib.error.HTTPError as e:
            msg = f"⚠️ n8n webhook HTTP error: {e.code} {e.reason}"
            logger.warning(msg)
            if log_callback:
                log_callback(msg)
        except Exception as e:
            msg = f"⚠️ n8n webhook failed: {e}"
            logger.warning(msg)
            if log_callback:
                log_callback(msg)

    threading.Thread(target=_send, daemon=True).start()
