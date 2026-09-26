from pathlib import Path
from typing import Optional, Dict, Any, List
from plugins.base_plugin import BasePlugin
import urllib.request, io
from PIL import Image

class ThumbnailsVariantsPlugin(BasePlugin):
    id = "thumb_variants"
    name = "Thumbnail Variants (stub)"
    description = "Planned: Download multiple resolution thumbnails (stub)"
    requires_video = True
    supports_playlist = False

    def __init__(self):
        super().__init__()
        self.enabled = False

    def run(self, app_ctx, video_info: Optional[Dict[str, Any]], playlist_entries: Optional[List[Dict[str, Any]]]):
        if not video_info:
            self.log(app_ctx, "No video info; skipping thumbnail variants (stub).")
            return
        self.log(app_ctx, "Thumbnail variants stub executed. No downloads performed.")


def register():
    return ThumbnailsVariantsPlugin()
