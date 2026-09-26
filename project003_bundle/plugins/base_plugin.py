import abc
from typing import Any, Dict, Optional

class BasePlugin(abc.ABC):
    """Abstract base class for extension plugins."""
    id: str = "base"
    name: str = "Base Plugin"
    description: str = ""
    requires_video: bool = True  # needs single video_info
    supports_playlist: bool = True  # can operate on playlist entries

    def __init__(self):
        self.enabled: bool = True

    @abc.abstractmethod
    def run(self, app_ctx: Any, video_info: Optional[Dict[str, Any]], playlist_entries: Optional[list]) -> None:
        """Execute plugin logic.
        app_ctx: reference to main GUI instance for logging/path access
        video_info: info dict for current video (or None if not fetched)
        playlist_entries: list of playlist entries (may be empty or None)
        """
        raise NotImplementedError

    def log(self, app_ctx: Any, message: str) -> None:
        if hasattr(app_ctx, 'log_message'):
            app_ctx.log_message(f"[EXT:{self.id}] {message}")
        else:
            print(f"[EXT:{self.id}] {message}")
