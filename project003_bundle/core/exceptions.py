"""
Custom Exceptions for IDM-YT Video Downloader
Provides structured error handling with actionable messages.
"""

from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum, auto


class ErrorCategory(Enum):
    """Categories of errors for UI handling"""
    NETWORK = auto()      # Network/connection issues
    AUTH = auto()         # Authentication/permissions
    FORMAT = auto()       # Format/codec issues
    STORAGE = auto()      # Disk/file issues
    RATE_LIMIT = auto()   # Rate limiting (429)
    NOT_FOUND = auto()    # Video/playlist not found
    EXTRACTION = auto()   # yt-dlp extraction errors
    CONFIG = auto()       # Configuration errors
    PLUGIN = auto()       # Plugin errors
    UNKNOWN = auto()      # Unclassified errors


@dataclass
class ErrorContext:
    """Context information for errors"""
    url: Optional[str] = None
    video_id: Optional[str] = None
    playlist_id: Optional[str] = None
    format_id: Optional[str] = None
    filename: Optional[str] = None
    attempt: int = 0
    max_attempts: int = 0
    extra: dict = None
    
    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


class IDMError(Exception):
    """
    Base exception for all IDM-YT errors.
    
    Attributes:
        message: Human-readable error message
        category: Error category for UI handling
        context: Additional context about the error
        recoverable: Whether the error can be retried
        user_message: User-friendly message for display
    """
    
    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        context: Optional[ErrorContext] = None,
        recoverable: bool = False,
        user_message: Optional[str] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.context = context or ErrorContext()
        self.recoverable = recoverable
        self.user_message = user_message or message
        self.cause = cause
    
    def __str__(self) -> str:
        return self.message
    
    @property
    def icon(self) -> str:
        """Get icon for error category"""
        icons = {
            ErrorCategory.NETWORK: "🌐",
            ErrorCategory.AUTH: "🔒",
            ErrorCategory.FORMAT: "📦",
            ErrorCategory.STORAGE: "💾",
            ErrorCategory.RATE_LIMIT: "⏱️",
            ErrorCategory.NOT_FOUND: "🔍",
            ErrorCategory.EXTRACTION: "⚠️",
            ErrorCategory.CONFIG: "⚙️",
            ErrorCategory.PLUGIN: "🔌",
            ErrorCategory.UNKNOWN: "❓",
        }
        return icons.get(self.category, "❓")


# Network Errors
class NetworkError(IDMError):
    """Network-related errors (connection, timeout, etc.)"""
    
    def __init__(self, message: str, category: ErrorCategory = ErrorCategory.NETWORK, recoverable: bool = True, **kwargs):
        super().__init__(
            message=message,
            category=category,
            recoverable=recoverable,
            **kwargs
        )


class ConnectionError(NetworkError):
    """Failed to establish connection"""
    
    def __init__(self, url: str, cause: Optional[Exception] = None):
        super().__init__(
            message=f"Failed to connect to server",
            context=ErrorContext(url=url),
            user_message="Unable to connect. Please check your internet connection.",
            cause=cause,
        )


class TimeoutError(NetworkError):
    """Request timed out"""
    
    def __init__(self, url: str, timeout: int = 30):
        super().__init__(
            message=f"Request timed out after {timeout} seconds",
            context=ErrorContext(url=url, extra={"timeout": timeout}),
            user_message=f"Request timed out. The server might be slow or unavailable.",
        )


class RateLimitError(NetworkError):
    """Rate limited (HTTP 429)"""
    
    def __init__(
        self,
        url: str,
        retry_after: Optional[int] = None,
        attempt: int = 0,
        max_attempts: int = 5,
    ):
        msg = "Rate limited by server (HTTP 429)"
        if retry_after:
            msg += f", retry after {retry_after}s"
        
        super().__init__(
            message=msg,
            category=ErrorCategory.RATE_LIMIT,
            context=ErrorContext(
                url=url,
                attempt=attempt,
                max_attempts=max_attempts,
                extra={"retry_after": retry_after}
            ),
            user_message="Too many requests. Waiting before retrying...",
            recoverable=True,
        )
        self.retry_after = retry_after


# Video/Content Errors
class VideoNotFoundError(IDMError):
    """Video or playlist not found"""
    
    def __init__(self, url: str, video_id: Optional[str] = None):
        super().__init__(
            message=f"Video not found: {video_id or url}",
            category=ErrorCategory.NOT_FOUND,
            context=ErrorContext(url=url, video_id=video_id),
            user_message="Video not found. It may have been deleted or made private.",
            recoverable=False,
        )


class PlaylistNotFoundError(IDMError):
    """Playlist not found"""
    
    def __init__(self, url: str, playlist_id: Optional[str] = None):
        super().__init__(
            message=f"Playlist not found: {playlist_id or url}",
            category=ErrorCategory.NOT_FOUND,
            context=ErrorContext(url=url, playlist_id=playlist_id),
            user_message="Playlist not found. It may have been deleted or made private.",
            recoverable=False,
        )


class PrivateVideoError(IDMError):
    """Video is private or requires authentication"""
    
    def __init__(self, url: str, video_id: Optional[str] = None):
        super().__init__(
            message=f"Video is private: {video_id or url}",
            category=ErrorCategory.AUTH,
            context=ErrorContext(url=url, video_id=video_id),
            user_message="This video is private and cannot be downloaded.",
            recoverable=False,
        )


class AgeRestrictedError(IDMError):
    """Video is age-restricted"""
    
    def __init__(self, url: str, video_id: Optional[str] = None):
        super().__init__(
            message=f"Video is age-restricted: {video_id or url}",
            category=ErrorCategory.AUTH,
            context=ErrorContext(url=url, video_id=video_id),
            user_message="This video is age-restricted. Login may be required.",
            recoverable=False,
        )


class GeoBlockedError(IDMError):
    """Video is geo-blocked"""
    
    def __init__(self, url: str, video_id: Optional[str] = None, country: Optional[str] = None):
        super().__init__(
            message=f"Video is geo-blocked: {video_id or url}",
            category=ErrorCategory.AUTH,
            context=ErrorContext(url=url, video_id=video_id, extra={"country": country}),
            user_message="This video is not available in your region.",
            recoverable=False,
        )


# Format Errors
class FormatError(IDMError):
    """Format-related errors"""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.FORMAT,
            **kwargs
        )


class FormatNotAvailableError(FormatError):
    """Requested format not available"""
    
    def __init__(self, format_id: str, url: str):
        super().__init__(
            message=f"Format '{format_id}' not available",
            context=ErrorContext(url=url, format_id=format_id),
            user_message=f"The requested quality is not available for this video.",
            recoverable=False,
        )


class FFmpegError(FormatError):
    """FFmpeg-related errors"""
    
    def __init__(self, message: str, operation: str = "conversion"):
        super().__init__(
            message=f"FFmpeg error during {operation}: {message}",
            context=ErrorContext(extra={"operation": operation}),
            user_message=f"Audio/video processing failed. Ensure FFmpeg is installed correctly.",
            recoverable=False,
        )


class FFmpegNotFoundError(FFmpegError):
    """FFmpeg not installed"""
    
    def __init__(self):
        super().__init__(
            message="FFmpeg not found",
            operation="initialization",
        )
        self.user_message = "FFmpeg is not installed. MP3 conversion requires FFmpeg."


# Storage Errors
class StorageError(IDMError):
    """Storage-related errors"""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.STORAGE,
            **kwargs
        )


class DiskFullError(StorageError):
    """Disk is full"""
    
    def __init__(self, path: str, required_bytes: Optional[int] = None):
        super().__init__(
            message=f"Disk full: {path}",
            context=ErrorContext(filename=path, extra={"required_bytes": required_bytes}),
            user_message="Not enough disk space. Free up some space and try again.",
            recoverable=False,
        )


class PermissionError(StorageError):
    """Permission denied"""
    
    def __init__(self, path: str, operation: str = "write"):
        super().__init__(
            message=f"Permission denied: {operation} to {path}",
            context=ErrorContext(filename=path, extra={"operation": operation}),
            user_message=f"Permission denied. Check folder permissions.",
            recoverable=False,
        )


class FileExistsError(StorageError):
    """File already exists"""
    
    def __init__(self, path: str):
        super().__init__(
            message=f"File already exists: {path}",
            context=ErrorContext(filename=path),
            user_message="A file with this name already exists.",
            recoverable=True,  # Can be resolved by overwrite option
        )


# Extraction Errors
class ExtractionError(IDMError):
    """yt-dlp extraction errors"""
    
    def __init__(self, message: str, url: str, cause: Optional[Exception] = None):
        super().__init__(
            message=f"Extraction failed: {message}",
            category=ErrorCategory.EXTRACTION,
            context=ErrorContext(url=url),
            user_message="Failed to extract video information. The URL might be invalid.",
            recoverable=False,
            cause=cause,
        )


class UnsupportedURLError(ExtractionError):
    """URL not supported"""
    
    def __init__(self, url: str):
        super().__init__(
            message=f"Unsupported URL: {url}",
            url=url,
        )
        self.user_message = "This URL is not supported. Please use YouTube, Vimeo, or other supported sites."


# Plugin Errors
class PluginError(IDMError):
    """Plugin-related errors"""
    
    def __init__(self, plugin_name: str, message: str, cause: Optional[Exception] = None):
        super().__init__(
            message=f"Plugin '{plugin_name}' error: {message}",
            category=ErrorCategory.PLUGIN,
            context=ErrorContext(extra={"plugin_name": plugin_name}),
            user_message=f"Plugin '{plugin_name}' encountered an error.",
            recoverable=True,
            cause=cause,
        )


class PluginNotFoundError(PluginError):
    """Plugin not found"""
    
    def __init__(self, plugin_name: str):
        super().__init__(
            plugin_name=plugin_name,
            message="Plugin not found",
        )
        self.recoverable = False


# Download Errors
class DownloadError(IDMError):
    """Download operation errors"""
    
    def __init__(self, message: str, url: str, recoverable: bool = True, **kwargs):
        super().__init__(
            message=f"Download failed: {message}",
            context=ErrorContext(url=url),
            recoverable=recoverable,
            **kwargs
        )


class DownloadCancelledError(DownloadError):
    """Download was cancelled by user"""
    
    def __init__(self, url: str):
        super().__init__(
            message="Download cancelled",
            url=url,
            category=ErrorCategory.UNKNOWN,
            user_message="Download was cancelled.",
            recoverable=False,
        )


# Utility Functions
def classify_yt_dlp_error(error: Exception, url: str = "") -> IDMError:
    """
    Classify a yt-dlp exception into an appropriate IDMError.
    
    Args:
        error: The original exception
        url: The URL being processed
        
    Returns:
        Appropriate IDMError subclass
    """
    error_msg = str(error).lower()
    
    # Rate limiting
    if "429" in error_msg or "too many requests" in error_msg:
        return RateLimitError(url=url)
    
    # Not found
    if "video unavailable" in error_msg or "not found" in error_msg:
        return VideoNotFoundError(url=url)
    
    # Private/Auth
    if "private video" in error_msg:
        return PrivateVideoError(url=url)
    
    if "age" in error_msg and "restrict" in error_msg:
        return AgeRestrictedError(url=url)
    
    if "geo" in error_msg or "country" in error_msg:
        return GeoBlockedError(url=url)
    
    # Network
    if "timeout" in error_msg:
        return TimeoutError(url=url)
    
    if "connection" in error_msg or "network" in error_msg:
        return ConnectionError(url=url, cause=error)
    
    # Format
    if "format" in error_msg and "not available" in error_msg:
        return FormatNotAvailableError(format_id="requested", url=url)
    
    if "ffmpeg" in error_msg:
        return FFmpegError(message=str(error))
    
    # Generic extraction error
    return ExtractionError(message=str(error), url=url, cause=error)
