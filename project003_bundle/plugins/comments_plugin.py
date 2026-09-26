from pathlib import Path
from typing import Optional, Dict, Any, List
from plugins.base_plugin import BasePlugin

class CommentsPlugin(BasePlugin):
    id = "comments"
    name = "Comments Export (stub)"
    description = "Planned: Export top-level comments to JSON (stub)"
    requires_video = True
    supports_playlist = False

    def __init__(self):
        super().__init__()
        self.enabled = False

    def run(self, app_ctx, video_info: Optional[Dict[str, Any]], playlist_entries: Optional[List[Dict[str, Any]]]):
        if not video_info:
            self.log(app_ctx, "No video info; skipping comments (stub).")
            return
        # Future: Use yt-dlp to extract 'comments' when available or API integration.
        self.log(app_ctx, "Comments export stub executed. Nothing written yet.")


def register():
    return CommentsPlugin()
