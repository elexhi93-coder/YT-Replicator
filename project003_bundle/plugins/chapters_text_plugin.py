from pathlib import Path
from typing import Optional, Dict, Any, List
from plugins.base_plugin import BasePlugin
import json

class ChaptersTextPlugin(BasePlugin):
    id = "chapters_text"
    name = "Chapters Text Export"
    description = "Export chapters to a human-readable .chapters.txt file"
    requires_video = True
    supports_playlist = False

    def __init__(self):
        super().__init__()
        self.enabled = False  # default off

    def run(self, app_ctx, video_info: Optional[Dict[str, Any]], playlist_entries: Optional[List[Dict[str, Any]]]):
        if not video_info:
            self.log(app_ctx, "No video info; skipping chapters export.")
            return
        chapters = video_info.get('chapters')
        if not chapters:
            self.log(app_ctx, "No chapters data found.")
            return
        title = video_info.get('title', 'video')
        safe_title = ''.join(ch for ch in title if ch not in '\\/:*?"<>|' )[:150]
        out_dir = Path(getattr(app_ctx, 'download_path', Path.home() / 'Downloads'))
        txt_path = out_dir / f"{safe_title}.chapters.txt"
        try:
            lines = []
            for ch in chapters:
                start = ch.get('start_time', 0)
                end = ch.get('end_time', start)
                title_ch = ch.get('title', '')
                # format times as HH:MM:SS
                def fmt(t):
                    t = int(t)
                    h, m = divmod(t, 3600)
                    m, s = divmod(m, 60)
                    if h:
                        return f"{h:02d}:{m:02d}:{s:02d}"
                    return f"{m:02d}:{s:02d}"
                lines.append(f"{fmt(start)} - {fmt(end)} | {title_ch}")
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.log(app_ctx, f"Chapters text exported: {txt_path.name} ({len(lines)} entries)")
        except Exception as e:
            self.log(app_ctx, f"Error writing chapters text: {e}")

def register():
    return ChaptersTextPlugin()
