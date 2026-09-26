# IDM-YT Views Package
# UI components separated from business logic

from .components import (
    VideoInfoPanel,
    FormatSelector,
    ProgressPanel,
    LogPanel,
    SpeedOptionsPanel,
)
from .dialogs import (
    PlaylistDialog,
    SettingsDialog,
    AboutDialog,
)

__all__ = [
    # Components
    'VideoInfoPanel',
    'FormatSelector',
    'ProgressPanel',
    'LogPanel',
    'SpeedOptionsPanel',
    # Dialogs
    'PlaylistDialog',
    'SettingsDialog',
    'AboutDialog',
]
