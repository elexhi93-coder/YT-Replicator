"""
TikTok Uploader - Upload videos to TikTok.

Uses TikTok's Content Posting API for video uploads.
Requires OAuth 2.0 credentials with video.publish scope.
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


class TikTokUploader(BaseUploader):
    """TikTok video uploader using Content Posting API."""
    
    PLATFORM_NAME = "TikTok"
    MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024  # 4 GB
    SUPPORTED_FORMATS = ['mp4', 'webm', 'mov']
    MAX_TITLE_LENGTH = 150  # TikTok caption limit
    MAX_DESCRIPTION_LENGTH = 2200
    MAX_TAGS = 30
    
    # API endpoints
    API_BASE = "https://open.tiktokapis.com/v2"
    
    # Video aspect ratios
    ASPECT_RATIOS = {
        'portrait': '9:16',  # Recommended
        'landscape': '16:9',
        'square': '1:1'
    }
    
    def __init__(self, credentials: PlatformCredentials):
        """Initialize TikTok uploader."""
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
            'client_key': self.credentials.client_id,
            'client_secret': self.credentials.client_secret,
            'refresh_token': self.credentials.refresh_token,
            'grant_type': 'refresh_token'
        }
        
        try:
            encoded = urllib.parse.urlencode(data).encode()
            req = urllib.request.Request(
                f"{self.API_BASE}/oauth/token/",
                data=encoded,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                token_data = json.loads(response.read().decode())
            
            self.credentials.access_token = token_data['access_token']
            self.credentials.token_expiry = time.time() + token_data.get('expires_in', 86400)
            
            if 'refresh_token' in token_data:
                self.credentials.refresh_token = token_data['refresh_token']
            
            return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False
    
    def get_upload_url(self) -> str:
        """Get the upload endpoint URL."""
        return f"{self.API_BASE}/post/publish/video/init/"
    
    def upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable[[UploadProgress], None]] = None
    ) -> UploadResult:
        """
        Upload a video to TikTok.
        
        TikTok uses a multi-step upload process:
        1. Initialize upload session
        2. Upload video file (chunked for large files)
        3. Publish video
        
        Args:
            video_path: Path to the video file
            metadata: Video metadata (title becomes caption)
            progress_callback: Optional callback for progress updates
            
        Returns:
            UploadResult with publish_id
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
                    error_message="Not authenticated with TikTok."
                )
        
        try:
            file_size = os.path.getsize(video_path)
            
            # Determine upload method based on file size
            if file_size < 64 * 1024 * 1024:  # Less than 64 MB
                result = self._upload_direct(video_path, metadata)
            else:
                result = self._upload_chunked(video_path, metadata)
            
            if result:
                self._update_progress(UploadStatus.COMPLETED, message="Upload complete!")
                
                upload_time = time.time() - start_time
                
                return UploadResult(
                    success=True,
                    platform=self.PLATFORM_NAME,
                    video_id=result.get('publish_id'),
                    video_url=None,  # TikTok doesn't return URL immediately
                    upload_time=upload_time,
                    extra_data=result
                )
            else:
                return UploadResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error_message="Upload failed"
                )
            
        except QuotaExceededError as e:
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=f"TikTok quota exceeded: {e}"
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
            logger.exception("TikTok upload failed")
            self._update_progress(UploadStatus.FAILED, message=str(e))
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=str(e)
            )
    
    def _upload_direct(
        self,
        video_path: str,
        metadata: VideoMetadata
    ) -> Optional[Dict[str, Any]]:
        """Direct upload for small videos (< 64MB)."""
        self._update_progress(UploadStatus.PREPARING, message="Initializing upload...")
        
        file_size = os.path.getsize(video_path)
        
        # Build caption with hashtags
        caption = self._build_caption(metadata)
        
        # Build post_info with TikTok-specific settings
        tt_settings = metadata.tiktok_settings
        
        post_info = {
            'title': caption,
            'privacy_level': self._map_privacy(metadata.privacy),
            'disable_duet': tt_settings.get('disable_duet', False),
            'disable_comment': tt_settings.get('disable_comment', False),
            'disable_stitch': tt_settings.get('disable_stitch', False)
        }
        
        # Additional TikTok-specific options
        # Brand content toggle (requires business account)
        if tt_settings.get('brand_content_toggle'):
            post_info['brand_content_toggle'] = True
        
        # Brand organic toggle (for organic branded content)
        if tt_settings.get('brand_organic_toggle'):
            post_info['brand_organic_toggle'] = True
        
        # Disclose video is AI-generated (content disclosure)
        if metadata.contains_ai_content or tt_settings.get('is_aigc'):
            post_info['is_aigc'] = True
        
        # Initialize upload
        init_body = {
            'post_info': post_info,
            'source_info': {
                'source': 'FILE_UPLOAD',
                'video_size': file_size
            }
        }
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}',
            'Content-Type': 'application/json; charset=UTF-8'
        }
        
        try:
            req = urllib.request.Request(
                f"{self.API_BASE}/post/publish/video/init/",
                data=json.dumps(init_body).encode(),
                headers=headers,
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                init_data = json.loads(response.read().decode())
            
            if init_data.get('error', {}).get('code') != 'ok':
                error_msg = init_data.get('error', {}).get('message', 'Unknown error')
                raise UploadError(f"Init failed: {error_msg}")
            
            publish_id = init_data['data']['publish_id']
            upload_url = init_data['data']['upload_url']
            
            # Upload file
            self._update_progress(
                UploadStatus.UPLOADING,
                bytes_uploaded=0,
                total_bytes=file_size,
                message="Uploading video..."
            )
            
            with open(video_path, 'rb') as f:
                video_data = f.read()
            
            upload_headers = {
                'Content-Type': 'video/mp4',
                'Content-Length': str(file_size),
                'Content-Range': f'bytes 0-{file_size-1}/{file_size}'
            }
            
            req = urllib.request.Request(
                upload_url,
                data=video_data,
                headers=upload_headers,
                method='PUT'
            )
            
            with urllib.request.urlopen(req, timeout=600) as response:
                if response.getcode() not in (200, 201):
                    raise UploadError(f"Upload failed with status {response.getcode()}")
            
            self._update_progress(
                UploadStatus.UPLOADING,
                bytes_uploaded=file_size,
                total_bytes=file_size
            )
            
            # Check publish status
            return self._check_publish_status(publish_id)
            
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return None
    
    def _upload_chunked(
        self,
        video_path: str,
        metadata: VideoMetadata
    ) -> Optional[Dict[str, Any]]:
        """Chunked upload for large videos (>= 64MB)."""
        self._update_progress(UploadStatus.PREPARING, message="Initializing chunked upload...")
        
        file_size = os.path.getsize(video_path)
        chunk_count = (file_size + self._chunk_size - 1) // self._chunk_size
        
        # Build caption with hashtags
        caption = self._build_caption(metadata)
        
        # Build post_info with TikTok-specific settings
        tt_settings = metadata.tiktok_settings
        
        post_info = {
            'title': caption,
            'privacy_level': self._map_privacy(metadata.privacy),
            'disable_duet': tt_settings.get('disable_duet', False),
            'disable_comment': tt_settings.get('disable_comment', False),
            'disable_stitch': tt_settings.get('disable_stitch', False)
        }
        
        # Additional TikTok-specific options
        if tt_settings.get('brand_content_toggle'):
            post_info['brand_content_toggle'] = True
        if tt_settings.get('brand_organic_toggle'):
            post_info['brand_organic_toggle'] = True
        if metadata.contains_ai_content or tt_settings.get('is_aigc'):
            post_info['is_aigc'] = True
        
        # Initialize chunked upload
        init_body = {
            'post_info': post_info,
            'source_info': {
                'source': 'FILE_UPLOAD',
                'video_size': file_size,
                'chunk_size': self._chunk_size,
                'total_chunk_count': chunk_count
            }
        }
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}',
            'Content-Type': 'application/json; charset=UTF-8'
        }
        
        try:
            req = urllib.request.Request(
                f"{self.API_BASE}/post/publish/video/init/",
                data=json.dumps(init_body).encode(),
                headers=headers,
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                init_data = json.loads(response.read().decode())
            
            if init_data.get('error', {}).get('code') != 'ok':
                error_msg = init_data.get('error', {}).get('message', 'Unknown error')
                raise UploadError(f"Init failed: {error_msg}")
            
            publish_id = init_data['data']['publish_id']
            upload_url = init_data['data']['upload_url']
            
            # Upload chunks
            self._update_progress(
                UploadStatus.UPLOADING,
                bytes_uploaded=0,
                total_bytes=file_size,
                message="Uploading video chunks..."
            )
            
            start_time = time.time()
            bytes_uploaded = 0
            
            with open(video_path, 'rb') as f:
                for chunk_index in range(chunk_count):
                    # Check for cancel
                    if self._check_cancelled():
                        self._update_progress(UploadStatus.CANCELLED)
                        return None
                    
                    # Wait if paused
                    self._wait_if_paused()
                    
                    chunk_data = f.read(self._chunk_size)
                    chunk_size = len(chunk_data)
                    start_byte = chunk_index * self._chunk_size
                    end_byte = start_byte + chunk_size - 1
                    
                    upload_headers = {
                        'Content-Type': 'video/mp4',
                        'Content-Length': str(chunk_size),
                        'Content-Range': f'bytes {start_byte}-{end_byte}/{file_size}'
                    }
                    
                    req = urllib.request.Request(
                        upload_url,
                        data=chunk_data,
                        headers=upload_headers,
                        method='PUT'
                    )
                    
                    with urllib.request.urlopen(req, timeout=120) as response:
                        pass
                    
                    bytes_uploaded += chunk_size
                    
                    # Calculate speed and ETA
                    speed, eta = self._calculate_speed_and_eta(
                        bytes_uploaded, file_size, start_time
                    )
                    
                    self._update_progress(
                        UploadStatus.UPLOADING,
                        bytes_uploaded=bytes_uploaded,
                        total_bytes=file_size,
                        speed=speed,
                        eta=eta
                    )
            
            # Check publish status
            return self._check_publish_status(publish_id)
            
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return None
    
    def _build_caption(self, metadata: VideoMetadata) -> str:
        """Build TikTok caption with hashtags."""
        caption = metadata.title
        
        # Add hashtags from tags
        if metadata.tags:
            hashtags = ' '.join([
                f'#{tag.replace(" ", "").replace("#", "")}'
                for tag in metadata.tags[:10]  # TikTok recommends max 10 hashtags
            ])
            
            # Ensure we don't exceed caption limit
            if len(caption) + len(hashtags) + 1 <= self.MAX_TITLE_LENGTH:
                caption = f"{caption} {hashtags}"
        
        return caption[:self.MAX_TITLE_LENGTH]
    
    def _map_privacy(self, privacy: str) -> str:
        """Map privacy setting to TikTok values."""
        privacy_map = {
            'public': 'PUBLIC_TO_EVERYONE',
            'private': 'SELF_ONLY',
            'unlisted': 'MUTUAL_FOLLOW_FRIENDS'  # Closest equivalent
        }
        return privacy_map.get(privacy, 'SELF_ONLY')
    
    def _check_publish_status(
        self,
        publish_id: str,
        max_retries: int = 30
    ) -> Optional[Dict[str, Any]]:
        """Check video publish status."""
        self._update_progress(UploadStatus.PROCESSING, message="Processing video...")
        
        url = f"{self.API_BASE}/post/publish/status/fetch/"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}',
            'Content-Type': 'application/json'
        }
        
        body = {'publish_id': publish_id}
        
        for attempt in range(max_retries):
            if self._check_cancelled():
                return None
            
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(body).encode(),
                    headers=headers,
                    method='POST'
                )
                
                with urllib.request.urlopen(req, timeout=30) as response:
                    status_data = json.loads(response.read().decode())
                
                if status_data.get('error', {}).get('code') != 'ok':
                    error_msg = status_data.get('error', {}).get('message', 'Unknown error')
                    raise UploadError(f"Status check failed: {error_msg}")
                
                status = status_data.get('data', {}).get('status')
                
                if status == 'PUBLISH_COMPLETE':
                    return {
                        'publish_id': publish_id,
                        'status': status
                    }
                elif status in ('FAILED', 'PUBLISH_FAILED'):
                    fail_reason = status_data.get('data', {}).get('fail_reason', 'Unknown')
                    raise UploadError(f"Publish failed: {fail_reason}")
                
                # Still processing, wait and retry
                time.sleep(2)
                
            except urllib.error.HTTPError as e:
                self._handle_api_error(e)
                return None
        
        # Timeout - return partial success
        return {
            'publish_id': publish_id,
            'status': 'PROCESSING'
        }
    
    def _handle_api_error(self, error: urllib.error.HTTPError):
        """Handle TikTok API errors."""
        try:
            error_body = json.loads(error.read().decode())
            error_info = error_body.get('error', {})
            message = error_info.get('message', str(error))
            code = error_info.get('code', '')
            
            if code in ('access_token_invalid', 'token_expired'):
                raise AuthenticationError(message)
            elif code == 'rate_limit_exceeded':
                raise RateLimitError(message, retry_after=60)
            elif code == 'quota_exceeded':
                raise QuotaExceededError(message)
            
            raise UploadError(message)
            
        except json.JSONDecodeError:
            raise UploadError(f"HTTP {error.code}: {error.reason}")
    
    def get_user_info(self) -> Dict[str, Any]:
        """Get authenticated user info."""
        url = f"{self.API_BASE}/user/info/?fields=open_id,union_id,avatar_url,display_name"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}'
        }
        
        try:
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            if data.get('error', {}).get('code') != 'ok':
                raise AuthenticationError("Failed to get user info")
            
            user_data = data.get('data', {}).get('user', {})
            return {
                'id': user_data.get('open_id'),
                'union_id': user_data.get('union_id'),
                'username': user_data.get('display_name'),
                'avatar': user_data.get('avatar_url')
            }
            
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return {}
    
    def get_quota_info(self) -> Dict[str, Any]:
        """Get current API quota information."""
        # TikTok has daily posting limits
        return {
            'daily_post_limit': 'Varies by account status',
            'max_video_duration': '10 minutes',
            'max_file_size': '4 GB'
        }
