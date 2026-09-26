"""
Uploaders Package - Multi-platform video upload support.

Supports uploading to:
- YouTube (via Data API v3)
- Dailymotion (via Partner API)
- TikTok (via Content Posting API)
- Facebook (via Graph API)

Usage:
    from uploaders import UploadManager, Platform, VideoMetadata
    from uploaders.upload_window import show_upload_window
    
    # Create manager
    manager = UploadManager()
    
    # Configure platforms
    manager.configure_platform(
        Platform.YOUTUBE,
        client_id='your_client_id',
        client_secret='your_client_secret'
    )
    
    # Add upload
    metadata = VideoMetadata(
        title='My Video',
        description='Video description',
        tags=['tag1', 'tag2'],
        privacy='private'
    )
    
    job = manager.add_upload(
        video_path='/path/to/video.mp4',
        metadata=metadata,
        platforms=[Platform.YOUTUBE, Platform.DAILYMOTION]
    )
    
    # Start processing
    manager.start()
    
    # Or show GUI
    show_upload_window(parent_window, manager)
"""

from .base_uploader import (
    BaseUploader,
    UploadStatus,
    UploadResult,
    VideoMetadata,
    UploadProgress,
    PlatformCredentials,
    UploadError,
    AuthenticationError,
    RateLimitError,
    QuotaExceededError
)
from .auth_manager import AuthManager, OAuthFlow, TokenStore, OAuthProvider
from .youtube_uploader import YouTubeUploader
from .dailymotion_uploader import DailymotionUploader
from .tiktok_uploader import TikTokUploader
from .facebook_uploader import FacebookUploader
from .upload_manager import UploadManager, UploadJob, UploadQueue, JobStatus, Platform

__all__ = [
    # Base classes
    'BaseUploader',
    'UploadStatus',
    'UploadResult',
    'VideoMetadata',
    'UploadProgress',
    'PlatformCredentials',
    
    # Exceptions
    'UploadError',
    'AuthenticationError',
    'RateLimitError',
    'QuotaExceededError',
    
    # Auth
    'AuthManager',
    'OAuthFlow',
    'TokenStore',
    'OAuthProvider',
    
    # Platform uploaders
    'YouTubeUploader',
    'DailymotionUploader',
    'TikTokUploader',
    'FacebookUploader',
    
    # Manager
    'UploadManager',
    'UploadJob',
    'UploadQueue',
    'JobStatus',
    'Platform'
]
