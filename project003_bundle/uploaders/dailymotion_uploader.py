"""
Dailymotion Uploader - Upload videos to Dailymotion.

Requires OAuth 2.0 credentials with manage_videos scope.
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
import urllib.request
import urllib.parse
import urllib.error
import mimetypes

from .base_uploader import (
    BaseUploader,
    PlatformCredentials,
    VideoMetadata,
    UploadProgress,
    UploadResult,
    UploadStatus,
    UploadError,
    AuthenticationError,
    RateLimitError,
    QuotaExceededError
)

logger = logging.getLogger(__name__)


class DailymotionUploader(BaseUploader):
    """Dailymotion video uploader."""
    
    PLATFORM_NAME = "Dailymotion"
    MAX_FILE_SIZE = 60 * 60 * 1024 * 1024  # 60 minutes at ~1GB/hr ≈ 1GB default
    SUPPORTED_FORMATS = [
        'mp4', 'avi', 'wmv', 'mov', 'flv', 'webm', 'mkv',
        '3gp', 'mpeg', 'mpg', 'm4v', 'ogv'
    ]
    MAX_TITLE_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 3000
    MAX_TAGS = 100
    
    # API endpoints
    API_BASE = "https://api.dailymotion.com"
    UPLOAD_URL = "https://upload.dailymotion.com/v4/upload"
    
    # Video categories (channels)
    CATEGORIES = {
        'animals': 'Animals',
        'auto': 'Auto & Vehicles',
        'creation': 'Creation',
        'fun': 'Fun',
        'kids': 'Kids',
        'lifestyle': 'Lifestyle',
        'music': 'Music',
        'news': 'News & Politics',
        'people': 'People',
        'school': 'School',
        'shortfilms': 'Short Films',
        'sport': 'Sport',
        'tech': 'Tech',
        'travel': 'Travel',
        'tv': 'TV',
        'webcam': 'Webcam',
        'videogames': 'Video Games'
    }
    
    def __init__(self, credentials: PlatformCredentials):
        """Initialize Dailymotion uploader."""
        super().__init__(credentials)
        self._chunk_size = 10 * 1024 * 1024  # 10 MB chunks
    
    @property
    def is_authenticated(self) -> bool:
        """Check if uploader is authenticated."""
        return self.credentials.is_authenticated
    
    def authenticate(self) -> bool:
        """
        Perform authentication flow.
        
        Note: Use AuthManager for full OAuth flow.
        """
        if self.credentials.access_token:
            try:
                self.get_user_info()
                return True
            except AuthenticationError:
                return False
        return False
    
    def refresh_token(self) -> bool:
        """Refresh the access token."""
        if not self.credentials.refresh_token:
            return False
        
        data = {
            'client_id': self.credentials.client_id,
            'client_secret': self.credentials.client_secret,
            'refresh_token': self.credentials.refresh_token,
            'grant_type': 'refresh_token'
        }
        
        try:
            encoded = urllib.parse.urlencode(data).encode()
            req = urllib.request.Request(
                f"{self.API_BASE}/oauth/token",
                data=encoded,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                token_data = json.loads(response.read().decode())
            
            self.credentials.access_token = token_data['access_token']
            self.credentials.token_expiry = time.time() + token_data.get('expires_in', 3600)
            
            if 'refresh_token' in token_data:
                self.credentials.refresh_token = token_data['refresh_token']
            
            return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False
    
    def get_upload_url(self) -> str:
        """Get the upload endpoint URL."""
        return self.UPLOAD_URL
    
    def upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable[[UploadProgress], None]] = None
    ) -> UploadResult:
        """
        Upload a video to Dailymotion.
        
        Dailymotion uses a 2-step process:
        1. Upload file to upload server
        2. Create video with upload URL
        
        Args:
            video_path: Path to the video file
            metadata: Video metadata
            progress_callback: Optional callback for progress updates
            
        Returns:
            UploadResult with video URL
        """
        self._progress_callback = progress_callback
        self._cancel_event.clear()
        self._pause_event.clear()
        
        start_time = time.time()
        
        # Validate video and metadata
        valid, error = self.validate_video(video_path)
        if not valid:
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=error
            )
        
        valid, error = self.validate_metadata(metadata)
        if not valid:
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=error
            )
        
        # Check authentication
        if not self.is_authenticated:
            if self.credentials.refresh_token:
                if not self.refresh_token():
                    return UploadResult(
                        success=False,
                        platform=self.PLATFORM_NAME,
                        error_message="Authentication expired. Please re-authenticate."
                    )
            else:
                return UploadResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error_message="Not authenticated with Dailymotion."
                )
        
        try:
            # Step 1: Get upload URL
            self._update_progress(UploadStatus.PREPARING, message="Getting upload URL...")
            upload_url = self._get_upload_url()
            
            if not upload_url:
                return UploadResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error_message="Failed to get upload URL"
                )
            
            # Step 2: Upload file
            self._update_progress(UploadStatus.UPLOADING, message="Uploading video...")
            upload_result = self._upload_file(video_path, upload_url)
            
            if not upload_result:
                return UploadResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error_message="File upload failed"
                )
            
            # Step 3: Create video with metadata
            self._update_progress(UploadStatus.PROCESSING, message="Creating video...")
            video_data = self._create_video(upload_result['url'], metadata)
            
            if not video_data:
                return UploadResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error_message="Failed to create video"
                )
            
            # Set thumbnail if provided
            if metadata.thumbnail_path and os.path.exists(metadata.thumbnail_path):
                self._update_progress(UploadStatus.PROCESSING, message="Setting thumbnail...")
                self._set_thumbnail(video_data['id'], metadata.thumbnail_path)
            
            self._update_progress(UploadStatus.COMPLETED, message="Upload complete!")
            
            upload_time = time.time() - start_time
            video_url = f"https://www.dailymotion.com/video/{video_data['id']}"
            
            return UploadResult(
                success=True,
                platform=self.PLATFORM_NAME,
                video_id=video_data['id'],
                video_url=video_url,
                upload_time=upload_time,
                extra_data=video_data
            )
            
        except QuotaExceededError as e:
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=f"Dailymotion quota exceeded: {e}"
            )
        except RateLimitError as e:
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=f"Rate limited. Retry after {e.retry_after}s"
            )
        except AuthenticationError as e:
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=f"Authentication error: {e}"
            )
        except Exception as e:
            logger.exception("Dailymotion upload failed")
            self._update_progress(UploadStatus.FAILED, message=str(e))
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=str(e)
            )
    
    def _get_upload_url(self) -> Optional[str]:
        """Get upload URL from Dailymotion."""
        url = f"{self.API_BASE}/file/upload"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}'
        }
        
        try:
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                return data.get('upload_url')
                
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return None
    
    def _upload_file(
        self,
        video_path: str,
        upload_url: str
    ) -> Optional[Dict[str, Any]]:
        """Upload file to Dailymotion upload server."""
        file_size = os.path.getsize(video_path)
        filename = os.path.basename(video_path)
        
        # Create multipart form data
        boundary = '----WebKitFormBoundary' + str(int(time.time() * 1000))
        
        start_time = time.time()
        bytes_uploaded = 0
        
        self._update_progress(
            UploadStatus.UPLOADING,
            bytes_uploaded=0,
            total_bytes=file_size
        )
        
        try:
            with open(video_path, 'rb') as f:
                file_data = f.read()
            
            # Build multipart body
            body_parts = []
            body_parts.append(f'--{boundary}'.encode())
            body_parts.append(
                f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode()
            )
            body_parts.append(b'Content-Type: video/mp4')
            body_parts.append(b'')
            body_parts.append(file_data)
            body_parts.append(f'--{boundary}--'.encode())
            
            body = b'\r\n'.join(body_parts)
            
            headers = {
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'Content-Length': str(len(body))
            }
            
            req = urllib.request.Request(upload_url, data=body, headers=headers)
            
            with urllib.request.urlopen(req, timeout=600) as response:
                result = json.loads(response.read().decode())
                
                self._update_progress(
                    UploadStatus.UPLOADING,
                    bytes_uploaded=file_size,
                    total_bytes=file_size
                )
                
                return result
                
        except Exception as e:
            logger.error(f"File upload failed: {e}")
            return None
    
    def _create_video(
        self,
        upload_url: str,
        metadata: VideoMetadata
    ) -> Optional[Dict[str, Any]]:
        """Create video with metadata after upload."""
        url = f"{self.API_BASE}/me/videos"
        
        # Map privacy
        privacy_map = {
            'public': 'public',
            'private': 'private',
            'unlisted': 'password'  # Dailymotion uses password for unlisted
        }
        
        data = {
            'url': upload_url,
            'title': metadata.title,
            'description': metadata.description,
            'tags': ','.join(metadata.tags),
            'private': metadata.privacy != 'public'
        }
        
        # Add channel/category
        if metadata.category:
            channel = self._get_channel_id(metadata.category)
            if channel:
                data['channel'] = channel
        
        # === Cross-platform compliance fields ===
        # Made for kids (COPPA compliance)
        data['is_created_for_kids'] = metadata.made_for_kids
        
        # AI content disclosure
        if metadata.contains_ai_content:
            data['stream_altered_with_ai'] = True
        
        # Embedding control
        data['allow_embed'] = metadata.allow_embedding
        
        # Language from common field
        data['language'] = metadata.language
        
        # === Dailymotion-specific settings ===
        dm_settings = metadata.dailymotion_settings
        if dm_settings:
            # Country (ISO 3166-1 alpha-2)
            if 'country' in dm_settings:
                data['country'] = dm_settings['country']
            
            # Override language from platform settings
            if 'language' in dm_settings:
                data['language'] = dm_settings['language']
            
            # Explicit content flag
            if 'explicit' in dm_settings:
                data['explicit'] = dm_settings['explicit']
            
            # Geoblocking - list of countries to allow or deny
            # Format: '+US,+CA' (allow) or '-FR,-DE' (deny)
            if 'geoblocking' in dm_settings:
                data['geoblocking'] = dm_settings['geoblocking']
            
            # Hashtags (separate from tags)
            if 'hashtags' in dm_settings:
                if isinstance(dm_settings['hashtags'], list):
                    data['hashtags'] = ','.join(dm_settings['hashtags'])
                else:
                    data['hashtags'] = dm_settings['hashtags']
            
            # Password protection (for private/unlisted videos)
            if 'password' in dm_settings and dm_settings['password']:
                data['password'] = dm_settings['password']
            
            # Expiry date (Unix timestamp when video should be removed)
            if 'expiry_date' in dm_settings:
                data['expiry_date'] = int(dm_settings['expiry_date'])
            
            # Whether video can be added to playlists
            if 'allowed_in_playlists' in dm_settings:
                data['allowed_in_playlists'] = dm_settings['allowed_in_playlists']
            
            # Custom classification values (up to 3)
            if 'custom_classification' in dm_settings:
                data['custom_classification'] = dm_settings['custom_classification']
            
            # Override made_for_kids if explicitly set
            if 'is_created_for_kids' in dm_settings:
                data['is_created_for_kids'] = dm_settings['is_created_for_kids']
            
            # Override AI content flag
            if 'stream_altered_with_ai' in dm_settings:
                data['stream_altered_with_ai'] = dm_settings['stream_altered_with_ai']
        
        # Scheduled publish
        if metadata.scheduled_time:
            data['publish_date'] = int(metadata.scheduled_time)
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        try:
            encoded = urllib.parse.urlencode(data).encode()
            req = urllib.request.Request(url, data=encoded, headers=headers, method='POST')
            
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode())
                
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return None
    
    def _set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """Set custom thumbnail for a video."""
        try:
            # First get thumbnail upload URL
            url = f"{self.API_BASE}/file/upload?target=thumbnail&id={video_id}"
            
            headers = {
                'Authorization': f'Bearer {self.credentials.access_token}'
            }
            
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                upload_info = json.loads(response.read().decode())
                upload_url = upload_info.get('upload_url')
            
            if not upload_url:
                return False
            
            # Upload thumbnail
            with open(thumbnail_path, 'rb') as f:
                thumbnail_data = f.read()
            
            filename = os.path.basename(thumbnail_path)
            boundary = '----WebKitFormBoundary' + str(int(time.time() * 1000))
            
            body_parts = []
            body_parts.append(f'--{boundary}'.encode())
            body_parts.append(
                f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode()
            )
            body_parts.append(b'Content-Type: image/jpeg')
            body_parts.append(b'')
            body_parts.append(thumbnail_data)
            body_parts.append(f'--{boundary}--'.encode())
            
            body = b'\r\n'.join(body_parts)
            
            headers = {
                'Content-Type': f'multipart/form-data; boundary={boundary}'
            }
            
            req = urllib.request.Request(upload_url, data=body, headers=headers)
            
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode())
                thumbnail_url = result.get('url')
            
            if not thumbnail_url:
                return False
            
            # Set thumbnail on video
            video_url = f"{self.API_BASE}/video/{video_id}"
            data = urllib.parse.urlencode({'thumbnail_url': thumbnail_url}).encode()
            
            req = urllib.request.Request(
                video_url,
                data=data,
                headers={
                    'Authorization': f'Bearer {self.credentials.access_token}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.getcode() == 200
                
        except Exception as e:
            logger.error(f"Failed to set thumbnail: {e}")
            return False
    
    def _get_channel_id(self, category_name: str) -> Optional[str]:
        """Get Dailymotion channel ID from name."""
        for channel_id, name in self.CATEGORIES.items():
            if category_name.lower() in name.lower() or name.lower() in category_name.lower():
                return channel_id
        return None
    
    def _handle_api_error(self, error: urllib.error.HTTPError):
        """Handle Dailymotion API errors."""
        try:
            error_body = json.loads(error.read().decode())
            error_info = error_body.get('error', {})
            message = error_info.get('message', str(error))
            error_type = error_info.get('type', '')
            
            if error_type == 'access_forbidden':
                raise AuthenticationError(message)
            elif error_type == 'rate_limit_exceeded':
                raise RateLimitError(message, retry_after=60)
            elif error_type == 'upload_limit_exceeded':
                raise QuotaExceededError(message)
            
            raise UploadError(message)
            
        except json.JSONDecodeError:
            raise UploadError(f"HTTP {error.code}: {error.reason}")
    
    def get_user_info(self) -> Dict[str, Any]:
        """Get authenticated user info."""
        url = f"{self.API_BASE}/me?fields=id,screenname,avatar_80_url,videos_total"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}'
        }
        
        try:
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            return {
                'id': data.get('id'),
                'username': data.get('screenname'),
                'avatar': data.get('avatar_80_url'),
                'video_count': data.get('videos_total')
            }
            
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return {}
    
    def get_quota_info(self) -> Dict[str, Any]:
        """Get current upload quota."""
        url = f"{self.API_BASE}/me?fields=limits"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}'
        }
        
        try:
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            return data.get('limits', {})
            
        except Exception:
            return {}
    
    def delete_video(self, video_id: str) -> bool:
        """Delete an uploaded video."""
        url = f"{self.API_BASE}/video/{video_id}"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}'
        }
        
        try:
            req = urllib.request.Request(url, headers=headers, method='DELETE')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.getcode() == 200
                
        except urllib.error.HTTPError:
            return False
    
    def update_video(
        self,
        video_id: str,
        metadata: VideoMetadata
    ) -> bool:
        """Update video metadata."""
        url = f"{self.API_BASE}/video/{video_id}"
        
        data = {
            'title': metadata.title,
            'description': metadata.description,
            'tags': ','.join(metadata.tags),
            'private': metadata.privacy != 'public'
        }
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        try:
            encoded = urllib.parse.urlencode(data).encode()
            req = urllib.request.Request(url, data=encoded, headers=headers, method='POST')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.getcode() == 200
                
        except urllib.error.HTTPError:
            return False
