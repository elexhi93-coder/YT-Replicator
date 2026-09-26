# IDM-YT Core Module
# Refactored components for better maintainability

from .enums import DownloadType, VideoQuality, AudioQuality, URLType, DownloadStatus, SubtitleFormat
from .config import AppConfig, DownloadOptions
from .format_parser import FormatParser, VideoFormat, AudioFormat
from .download_manager import DownloadManager, DownloadProgress, DownloadResult
from .url_parser import URLParser, ParsedURL
from .clipboard_monitor import ClipboardMonitor, ClipboardMonitorConfig, ClipboardURLExtractor
from .video_fetcher import VideoInfoFetcher, VideoInfo, FetchResult, FetchStatus, FetcherConfig, BatchVideoFetcher
from .progress_tracker import ProgressTracker, ProgressInfo, ProgressState, ProgressTrackerConfig, MultiProgressTracker
from .logging_config import IDMLogger, LogConfig, LogLevel, get_logger
from .exceptions import (
    IDMError, ErrorCategory, ErrorContext,
    NetworkError, ConnectionError, TimeoutError, RateLimitError,
    VideoNotFoundError, PlaylistNotFoundError, PrivateVideoError, 
    AgeRestrictedError, GeoBlockedError,
    FormatError, FormatNotAvailableError, FFmpegError, FFmpegNotFoundError,
    StorageError, DiskFullError, PermissionError, FileExistsError,
    ExtractionError, UnsupportedURLError, PluginError,
    DownloadError, DownloadCancelledError,
    classify_yt_dlp_error,
)
from .download_queue import DownloadQueue, QueueItem, QueuePriority, QueueStats
from .settings import (
    AppSettings, WindowSettings, DownloadSettings, ClipboardSettings,
    UISettings, PluginSettings, SettingsManager,
)

# New architecture components
from .events import (
    EventType, Event, EventBus, EventHandler,
    on_event, emit,
    DownloadProgressData, DownloadCompletedData, DownloadFailedData,
    VideoFetchedData, LogMessageData,
)
from .state_machine import (
    DownloadState, StateTransition, StateContext, StateMachineError,
    DownloadStateMachine, MultiDownloadStateMachine,
)
from .container import (
    Container, ContainerError, ServiceLifetime, ServiceDescriptor,
    AppContainer, get_container, set_container, resolve, inject,
    create_app_container,
)

__all__ = [
    # Enums
    'DownloadType',
    'VideoQuality', 
    'AudioQuality',
    'URLType',
    'DownloadStatus',
    'SubtitleFormat',
    # Config
    'AppConfig',
    'DownloadOptions',
    # Format parsing
    'FormatParser',
    'VideoFormat',
    'AudioFormat',
    # Download management
    'DownloadManager',
    'DownloadProgress',
    'DownloadResult',
    # URL parsing
    'URLParser',
    'ParsedURL',
    # Clipboard monitoring
    'ClipboardMonitor',
    'ClipboardMonitorConfig',
    'ClipboardURLExtractor',
    # Video fetching
    'VideoInfoFetcher',
    'VideoInfo',
    'FetchResult',
    'FetchStatus',
    'FetcherConfig',
    'BatchVideoFetcher',
    # Progress tracking
    'ProgressTracker',
    'ProgressInfo',
    'ProgressState',
    'ProgressTrackerConfig',
    'MultiProgressTracker',
    # Logging
    'IDMLogger',
    'LogConfig',
    'LogLevel',
    'get_logger',
    # Exceptions
    'IDMError',
    'ErrorCategory',
    'ErrorContext',
    'NetworkError',
    'ConnectionError',
    'TimeoutError',
    'RateLimitError',
    'VideoNotFoundError',
    'PlaylistNotFoundError',
    'PrivateVideoError',
    'AgeRestrictedError',
    'GeoBlockedError',
    'FormatError',
    'FormatNotAvailableError',
    'FFmpegError',
    'FFmpegNotFoundError',
    'StorageError',
    'DiskFullError',
    'PermissionError',
    'FileExistsError',
    'ExtractionError',
    'UnsupportedURLError',
    'PluginError',
    'DownloadError',
    'DownloadCancelledError',
    'classify_yt_dlp_error',
    # Download Queue
    'DownloadQueue',
    'QueueItem',
    'QueuePriority',
    'QueueStats',
    # Settings
    'AppSettings',
    'WindowSettings',
    'DownloadSettings',
    'ClipboardSettings',
    'UISettings',
    'PluginSettings',
    'SettingsManager',
    # Events
    'EventType',
    'Event',
    'EventBus',
    'EventHandler',
    'on_event',
    'emit',
    'DownloadProgressData',
    'DownloadCompletedData',
    'DownloadFailedData',
    'VideoFetchedData',
    'LogMessageData',
    # State Machine
    'DownloadState',
    'StateTransition',
    'StateContext',
    'StateMachineError',
    'DownloadStateMachine',
    'MultiDownloadStateMachine',
    # Dependency Injection
    'Container',
    'ContainerError',
    'ServiceLifetime',
    'ServiceDescriptor',
    'AppContainer',
    'get_container',
    'set_container',
    'resolve',
    'inject',
    'create_app_container',
]
