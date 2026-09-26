# Plugin System

This app supports optional extensions ("plugins") that can be enabled/disabled and run from the main window.

- Location: `plugins/`
- Contract: each module must export a `register()` function that returns an instance of a class deriving from `BasePlugin`.
- Discovery: the app scans `plugins` package for modules and imports any that provide `register()`.
- Execution: from the main window, toggle the plugin checkboxes under "Extensions (Plugins)" and click "Run Enabled Extensions".

## Base interface

```
class BasePlugin(abc.ABC):
    id: str
    name: str
    description: str = ""
    requires_video: bool = True        # needs a single video info
    supports_playlist: bool = True     # can run on a playlist context

    def __init__(self):
        self.enabled: bool = True

    @abc.abstractmethod
    def run(self, app_ctx, video_info: Optional[dict], playlist_entries: Optional[list]) -> None:
        ...

    def log(self, app_ctx, message: str) -> None:
        # helper to log to the main UI
```

`app_ctx` is the main window instance. Useful attributes:

- `app_ctx.download_path`: current output folder
- `app_ctx.log_message(msg: str)`: add a log line in UI
- `app_ctx.ffmpeg_available`: whether ffmpeg is detected
- `app_ctx.video_info`: latest fetched single video info (dict)
- `app_ctx.is_playlist`: whether current context is a playlist
- `app_ctx.playlist_entries`: list of entries when in playlist context

## Minimal plugin skeleton

Create a new file under `plugins/` (e.g., `my_plugin.py`):

```python
from pathlib import Path
from typing import Optional, Dict, Any
from plugins.base_plugin import BasePlugin

class MyPlugin(BasePlugin):
    id = "my_plugin"
    name = "My Example Plugin"
    description = "Does something cool"
    requires_video = True
    supports_playlist = False

    def __init__(self):
        super().__init__()
        self.enabled = False  # default off

    def run(self, app_ctx, video_info: Optional[Dict[str, Any]], playlist_entries):
        if not video_info:
            self.log(app_ctx, "No video; skipping")
            return
        out_dir = Path(app_ctx.download_path)
        self.log(app_ctx, f"Would write files to: {out_dir}")


def register():
    return MyPlugin()
```

Restart or reopen the app if you add new files while it’s running.

## Existing plugins

- `metadata_plugin.py` — exports description, full info JSON, and chapters JSON
- `playlist_index_plugin.py` — exports playlist items to CSV and JSON
- `chapters_text_plugin.py` — exports chapters to a `.chapters.txt` file (human‑readable)

## Good practices

- Keep plugins fast and avoid blocking UI; where heavy work is needed, start a background thread and log periodic updates.
- Write to the `download_path` by default.
- Prefer small, focused plugins over giant all‑in‑one plugins.
- Wrap file I/O in try/except and report concise errors via `self.log(...)`.

## Troubleshooting

- If a plugin doesn’t appear in the list, ensure the file is under `plugins/`, imports succeed, and that `register()` returns a `BasePlugin` instance.
- If a plugin needs third‑party packages, document them and guard imports with friendly error messages so the app remains usable.
