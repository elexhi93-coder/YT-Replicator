from typing import Optional, Dict, Any, List
from plugins.base_plugin import BasePlugin

class SponsorBlockPlugin(BasePlugin):
    id = "sponsorblock"
    name = "SponsorBlock Segments (stub)"
    description = "Prepare to export SponsorBlock segments to JSON/CSV (stub)"
    requires_video = True
    supports_playlist = False

    def __init__(self):
        super().__init__()
        self.enabled = False  # default off; planned feature

    def run(self, app_ctx, video_info: Optional[Dict[str, Any]], playlist_entries: Optional[List[Dict[str, Any]]]):
        # Stub: no external calls yet. This logs intent and exits.
        if not video_info:
            self.log(app_ctx, "No video info; skipping SponsorBlock (stub).")
            return
        self.log(app_ctx, "SponsorBlock export is a stub. No action performed.")


def register():
    return SponsorBlockPlugin()
