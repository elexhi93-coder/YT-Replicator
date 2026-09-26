"""
Base Uploader - Abstract base class for all platform uploaders.

Provides common interface and utilities for video uploads across platforms.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, Any, Dict, List
from pathlib import Path
import threading
import time
import logging

logger = logging.getLogger(__name__)


class UploadStatus(Enum):
    """Status of an upload operation."""
    PENDING = auto()
    AUTHENTICATING = auto()
    PREPARING = auto()
    UPLOADING = auto()
    PROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    PAUSED = auto()


@dataclass
class PlatformCredentials:
    """OAuth credentials for a platform."""
    client_id: str
    client_secret: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expiry: Optional[float] = None
    scopes: List[str] = field(default_factory=list)
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_expired(self) -> bool:
        """Check if access token is expired."""
        if not self.token_expiry:
            return True
        return time.time() >= self.token_expiry - 60  # 1 minute buffer
    
    @property
    def is_authenticated(self) -> bool:
        """Check if we have valid authentication."""
        return bool(self.access_token) and not self.is_expired


@dataclass
class VideoMetadata:
    """Metadata for video upload."""
    title: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    category: str = ""
    privacy: str = "private"  # private, unlisted, public
    thumbnail_path: Optional[str] = None
    language: str = "en"
    
    # === Cross-platform compliance fields ===
    made_for_kids: bool = False  # COPPA compliance (all platforms)
    contains_ai_content: bool = False  # AI/synthetic content disclosure
    has_paid_promotion: bool = False  # Sponsored content disclosure
    
    # === Additional common fields ===
    audio_language: str = "en"  # Spoken language in video
    recording_date: Optional[str] = None  # ISO 8601 date when video was recorded
    allow_embedding: bool = True  # Whether video can be embedded
    
    # === Platform-specific settings dictionaries ===
    # YouTube-specific: license, publicStatsViewable, localizations, location
    youtube_settings: Dict[str, Any] = field(default_factory=dict)
    # Dailymotion-specific: country, geoblocking, hashtags, password, expiry_date
    dailymotion_settings: Dict[str, Any] = field(default_factory=dict)
    # TikTok-specific: disable_duet, disable_stitch, disable_comments
    tiktok_settings: Dict[str, Any] = field(default_factory=dict)
    # Facebook-specific: secret, content_category, unpublished
    facebook_settings: Dict[str, Any] = field(default_factory=dict)
    
    # Schedule upload
    scheduled_time: Optional[float] = None
    
    # Extra data for arbitrary extensions
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'title': self.title,
            'description': self.description,
            'tags': self.tags,
            'category': self.category,
            'privacy': self.privacy,
            'thumbnail_path': self.thumbnail_path,
            'language': self.language,
            'made_for_kids': self.made_for_kids,
            'contains_ai_content': self.contains_ai_content,
            'has_paid_promotion': self.has_paid_promotion,
            'audio_language': self.audio_language,
            'recording_date': self.recording_date,
            'allow_embedding': self.allow_embedding,
            'youtube_settings': self.youtube_settings,
            'dailymotion_settings': self.dailymotion_settings,
            'tiktok_settings': self.tiktok_settings,
            'facebook_settings': self.facebook_settings,
            'scheduled_time': self.scheduled_time,
            'extra_data': self.extra_data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Create from dictionary."""
        return cls(
            title=data.get('title', 'Untitled'),
            description=data.get('description', ''),
            tags=data.get('tags', []),
            category=data.get('category', ''),
            privacy=data.get('privacy', 'private'),
            thumbnail_path=data.get('thumbnail_path'),
            language=data.get('language', 'en'),
            made_for_kids=data.get('made_for_kids', False),
            contains_ai_content=data.get('contains_ai_content', False),
            has_paid_promotion=data.get('has_paid_promotion', False),
            audio_language=data.get('audio_language', 'en'),
            recording_date=data.get('recording_date'),
            allow_embedding=data.get('allow_embedding', True),
            youtube_settings=data.get('youtube_settings', {}),
            dailymotion_settings=data.get('dailymotion_settings', {}),
            tiktok_settings=data.get('tiktok_settings', {}),
            facebook_settings=data.get('facebook_settings', {}),
            scheduled_time=data.get('scheduled_time'),
            extra_data=data.get('extra_data', {})
        )


@dataclass
class UploadProgress:
    """Progress information for an upload."""
    status: UploadStatus
    bytes_uploaded: int = 0
    total_bytes: int = 0
    speed_bps: float = 0.0
    eta_seconds: float = 0.0
    message: str = ""
    
    @property
    def percent(self) -> float:
        """Get upload percentage."""
        if self.total_bytes == 0:
            return 0.0
        return (self.bytes_uploaded / self.total_bytes) * 100
    
    @property
    def speed_formatted(self) -> str:
        """Get formatted speed string."""
        if self.speed_bps < 1024:
            return f"{self.speed_bps:.0f} B/s"
        elif self.speed_bps < 1024 * 1024:
            return f"{self.speed_bps / 1024:.1f} KB/s"
        else:
            return f"{self.speed_bps / (1024 * 1024):.1f} MB/s"
    
    @property
    def eta_formatted(self) -> str:
        """Get formatted ETA string."""
        if self.eta_seconds <= 0:
            return "--:--"
        
        hours = int(self.eta_seconds // 3600)
        minutes = int((self.eta_seconds % 3600) // 60)
        seconds = int(self.eta_seconds % 60)
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


@dataclass
class UploadResult:
    """Result of an upload operation."""
    success: bool
    platform: str
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    upload_time: float = 0.0
    extra_data: Dict[str, Any] = field(default_factory=dict)


class UploadError(Exception):
    """Base exception for upload errors."""
    pass


class AuthenticationError(UploadError):
    """Authentication failed or expired."""
    pass


class RateLimitError(UploadError):
    """API rate limit exceeded."""
    def __init__(self, message: str, retry_after: float = 60.0):
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExceededError(UploadError):
    """Daily/monthly quota exceeded."""
    pass


class BaseUploader(ABC):
    """Abstract base class for platform uploaders."""
    
    PLATFORM_NAME: str = "unknown"
    MAX_FILE_SIZE: int = 0  # bytes, 0 = unlimited
    SUPPORTED_FORMATS: List[str] = []
    MAX_TITLE_LENGTH: int = 100
    MAX_DESCRIPTION_LENGTH: int = 5000
    MAX_TAGS: int = 30
    
    def __init__(self, credentials: PlatformCredentials):
        """
        Initialize uploader with credentials.
        
        Args:
            credentials: OAuth credentials for the platform
        """
        self.credentials = credentials
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._progress_callback: Optional[Callable[[UploadProgress], None]] = None
        self._current_progress = UploadProgress(status=UploadStatus.PENDING)
        
    @property
    @abstractmethod
    def is_authenticated(self) -> bool:
        """Check if uploader is authenticated."""
        pass
    
    @abstractmethod
    def authenticate(self) -> bool:
        """
        Perform authentication flow.
        
        Returns:
            True if authentication successful
        """
        pass
    
    @abstractmethod
    def refresh_token(self) -> bool:
        """
        Refresh the access token.
        
        Returns:
            True if refresh successful
        """
        pass
    
    @abstractmethod
    def upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable[[UploadProgress], None]] = None
    ) -> UploadResult:
        """
        Upload a video to the platform.
        
        Args:
            video_path: Path to the video file
            metadata: Video metadata
            progress_callback: Optional callback for progress updates
            
        Returns:
            UploadResult with success status and video URL
        """
        pass
    
    @abstractmethod
    def get_upload_url(self) -> str:
        """Get the upload endpoint URL."""
        pass
    
    def validate_video(self, video_path: str) -> tuple[bool, str]:
        """
        Validate video file before upload.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        path = Path(video_path)
        
        # Check file exists
        if not path.exists():
            return False, f"File not found: {video_path}"
        
        # Check file size
        file_size = path.stat().st_size
        if self.MAX_FILE_SIZE > 0 and file_size > self.MAX_FILE_SIZE:
            max_size_mb = self.MAX_FILE_SIZE / (1024 * 1024)
            file_size_mb = file_size / (1024 * 1024)
            return False, f"File too large: {file_size_mb:.1f}MB (max: {max_size_mb:.1f}MB)"
        
        # Check format
        if self.SUPPORTED_FORMATS:
            suffix = path.suffix.lower().lstrip('.')
            if suffix not in self.SUPPORTED_FORMATS:
                return False, f"Unsupported format: {suffix}. Supported: {', '.join(self.SUPPORTED_FORMATS)}"
        
        return True, ""
    
    def validate_metadata(self, metadata: VideoMetadata) -> tuple[bool, str]:
        """
        Validate metadata before upload.
        
        Args:
            metadata: Video metadata to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check title
        if not metadata.title:
            return False, "Title is required"
        if len(metadata.title) > self.MAX_TITLE_LENGTH:
            return False, f"Title too long: {len(metadata.title)} chars (max: {self.MAX_TITLE_LENGTH})"
        
        # Check description
        if len(metadata.description) > self.MAX_DESCRIPTION_LENGTH:
            return False, f"Description too long: {len(metadata.description)} chars (max: {self.MAX_DESCRIPTION_LENGTH})"
        
        # Check tags
        if len(metadata.tags) > self.MAX_TAGS:
            return False, f"Too many tags: {len(metadata.tags)} (max: {self.MAX_TAGS})"
        
        return True, ""
    
    def cancel(self):
        """Cancel the current upload."""
        self._cancel_event.set()
        logger.info(f"[{self.PLATFORM_NAME}] Upload cancelled")
    
    def pause(self):
        """Pause the current upload."""
        self._pause_event.set()
        self._update_progress(UploadStatus.PAUSED)
        logger.info(f"[{self.PLATFORM_NAME}] Upload paused")
    
    def resume(self):
        """Resume the current upload."""
        self._pause_event.clear()
        self._update_progress(UploadStatus.UPLOADING)
        logger.info(f"[{self.PLATFORM_NAME}] Upload resumed")
    
    def _check_cancelled(self) -> bool:
        """Check if upload was cancelled."""
        return self._cancel_event.is_set()
    
    def _wait_if_paused(self):
        """Wait while upload is paused."""
        while self._pause_event.is_set() and not self._cancel_event.is_set():
            time.sleep(0.1)
    
    def _update_progress(
        self,
        status: UploadStatus,
        bytes_uploaded: int = None,
        total_bytes: int = None,
        speed: float = None,
        eta: float = None,
        message: str = None
    ):
        """Update and emit progress."""
        if bytes_uploaded is not None:
            self._current_progress.bytes_uploaded = bytes_uploaded
        if total_bytes is not None:
            self._current_progress.total_bytes = total_bytes
        if speed is not None:
            self._current_progress.speed_bps = speed
        if eta is not None:
            self._current_progress.eta_seconds = eta
        if message is not None:
            self._current_progress.message = message
        
        self._current_progress.status = status
        
        if self._progress_callback:
            try:
                self._progress_callback(self._current_progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    def _calculate_speed_and_eta(
        self,
        bytes_uploaded: int,
        total_bytes: int,
        start_time: float
    ) -> tuple[float, float]:
        """
        Calculate upload speed and ETA.
        
        Returns:
            Tuple of (speed_bps, eta_seconds)
        """
        elapsed = time.time() - start_time
        if elapsed <= 0:
            return 0.0, 0.0
        
        speed = bytes_uploaded / elapsed
        remaining = total_bytes - bytes_uploaded
        
        if speed > 0:
            eta = remaining / speed
        else:
            eta = 0.0
        
        return speed, eta
    
    def get_auth_url(self) -> str:
        """
        Get OAuth authorization URL.
        
        Override in subclasses to provide platform-specific URL.
        """
        return ""
    
    def handle_oauth_callback(self, code: str) -> bool:
        """
        Handle OAuth callback with authorization code.
        
        Args:
            code: Authorization code from OAuth flow
            
        Returns:
            True if token exchange successful
        """
        return False
    
    def revoke_access(self) -> bool:
        """
        Revoke access and clear tokens.
        
        Returns:
            True if revocation successful
        """
        self.credentials.access_token = None
        self.credentials.refresh_token = None
        self.credentials.token_expiry = None
        return True
    
    def get_quota_info(self) -> Dict[str, Any]:
        """
        Get current API quota information.
        
        Override in subclasses to provide platform-specific quota info.
        
        Returns:
            Dictionary with quota information
        """
        return {}
    
    def get_user_info(self) -> Dict[str, Any]:
        """
        Get authenticated user information.
        
        Override in subclasses to provide platform-specific user info.
        
        Returns:
            Dictionary with user information
        """
        return {}
    
    def __repr__(self) -> str:
        auth_status = "authenticated" if self.is_authenticated else "not authenticated"
        return f"<{self.__class__.__name__} ({auth_status})>"
