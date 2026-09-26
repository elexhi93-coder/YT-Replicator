import csv
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from plugins.base_plugin import BasePlugin

class PlaylistIndexPlugin(BasePlugin):
    id = "playlist_index"
    name = "Playlist Index Export"
    description = "Export playlist entries to CSV and JSON"
    requires_video = False
    supports_playlist = True

    def run(self, app_ctx, video_info: Optional[Dict[str, Any]], playlist_entries: Optional[List[Dict[str, Any]]]):
        if not playlist_entries:
            self.log(app_ctx, "No playlist entries available; skipping.")
            return
        out_dir = Path(getattr(app_ctx, 'download_path', Path.home() / 'Downloads'))
        csv_path = out_dir / "playlist_index.csv"
        json_path = out_dir / "playlist_index.json"
        try:
            # Write CSV
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["#", "Title", "Duration", "URL"])
                for i, e in enumerate(playlist_entries, 1):
                    dur = e.get('duration') or ''
                    url = e.get('webpage_url') or e.get('url') or ''
                    writer.writerow([i, e.get('title', ''), dur, url])
            # Write JSON
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(playlist_entries, f, ensure_ascii=False, indent=2)
            self.log(app_ctx, f"Playlist index exported ({len(playlist_entries)} entries).")
        except Exception as e:
            self.log(app_ctx, f"Error exporting playlist index: {e}")


def register():
    return PlaylistIndexPlugin()
