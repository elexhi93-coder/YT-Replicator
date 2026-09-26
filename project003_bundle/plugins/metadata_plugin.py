import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

from plugins.base_plugin import BasePlugin

class MetadataPlugin(BasePlugin):
    id = "metadata"
    name = "Metadata Export"
    description = "Save description, info JSON, chapters if available"
    requires_video = True
    supports_playlist = False

    def run(self, app_ctx, video_info: Optional[Dict[str, Any]], playlist_entries):
        if not video_info:
            self.log(app_ctx, "No video info available; skipping.")
            return
        out_dir = Path(getattr(app_ctx, 'download_path', Path.home() / 'Downloads'))
        title = video_info.get('title', 'unknown_title')
        safe_title = ''.join(ch for ch in title if ch not in '\\/:*?"<>|' )[:150]
        base_path = out_dir / safe_title
        try:
            # Description
            desc = video_info.get('description')
            if desc:
                with open(f"{base_path}.description.txt", 'w', encoding='utf-8') as f:
                    f.write(desc)
                self.log(app_ctx, "Description saved.")
            else:
                self.log(app_ctx, "No description.")
            # Info JSON
            info_path = f"{base_path}.info.json"
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(video_info, f, ensure_ascii=False, indent=2)
            self.log(app_ctx, "Info JSON saved.")
            # Chapters
            chapters = video_info.get('chapters')
            if chapters:
                with open(f"{base_path}.chapters.json", 'w', encoding='utf-8') as f:
                    json.dump(chapters, f, ensure_ascii=False, indent=2)
                self.log(app_ctx, f"Chapters saved ({len(chapters)}).")
            else:
                self.log(app_ctx, "No chapters found.")
        except Exception as e:
            self.log(app_ctx, f"Error exporting metadata: {e}")


def register():
    return MetadataPlugin()
