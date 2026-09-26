"""
Facebook Uploader - Upload videos to Facebook Pages and profiles.

Uses Facebook Graph API for video uploads.
Requires OAuth 2.0 credentials with publish_video scope.
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


class FacebookUploader(BaseUploader):
    """Facebook video uploader using Graph API."""
    
    PLATFORM_NAME = "Facebook"
    MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB
    SUPPORTED_FORMATS = [
        'mp4', 'mov', 'avi', 'wmv', 'flv', 'webm', 'mkv',
        '3gp', 'mpeg', 'mpg', 'm4v', 'ogv'
    ]
    MAX_TITLE_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 63206  # Facebook limit
    MAX_TAGS = 0  # Facebook doesn't use tags in the same way
    
    # API endpoints
    API_VERSION = "v18.0"
    API_BASE = f"https://graph.facebook.com/{API_VERSION}"
    UPLOAD_BASE = f"https://graph-video.facebook.com/{API_VERSION}"
    
    def __init__(
        self,
        credentials: PlatformCredentials,
        page_id: Optional[str] = None
    ):
        """
        Initialize Facebook uploader.
        
        Args:
            credentials: OAuth credentials
            page_id: Optional Facebook Page ID for page uploads
        """
        super().__init__(credentials)
        self.page_id = page_id
        self._page_access_token: Optional[str] = None
        self._chunk_size = 50 * 1024 * 1024  # 50 MB chunks
    
    @property
    def is_authenticated(self) -> bool:
        """Check if uploader is authenticated."""
        return self.credentials.is_authenticated
    
    @property
    def target_id(self) -> str:
        """Get the target ID for uploads (page or user)."""
        return self.page_id or 'me'
    
    def authenticate(self) -> bool:
        """
        Perform authentication flow.
        
        Note: Use AuthManager for full OAuth flow.
        """
        if self.credentials.access_token:
            try:
                self.get_user_info()
                
                # If page_id is set, get page access token
                if self.page_id:
                    self._get_page_access_token()
                
                return True
            except AuthenticationError:
                return False
        return False
    
    def refresh_token(self) -> bool:
        """
        Refresh the access token.
        
        Note: Facebook long-lived tokens don't need traditional refresh.
        """
        # Facebook uses long-lived tokens that need to be exchanged
        if not self.credentials.access_token:
            return False
        
        try:
            url = (
                f"{self.API_BASE}/oauth/access_token?"
                f"grant_type=fb_exchange_token&"
                f"client_id={self.credentials.client_id}&"
                f"client_secret={self.credentials.client_secret}&"
                f"fb_exchange_token={self.credentials.access_token}"
            )
            
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            self.credentials.access_token = data['access_token']
            self.credentials.token_expiry = time.time() + data.get('expires_in', 5184000)
            
            return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False
    
    def get_upload_url(self) -> str:
        """Get the upload endpoint URL."""
        return f"{self.UPLOAD_BASE}/{self.target_id}/videos"
    
    def _get_page_access_token(self) -> bool:
        """Get access token for a specific page."""
        if not self.page_id:
            return False
        
        try:
            url = f"{self.API_BASE}/me/accounts?access_token={self.credentials.access_token}"
            
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            for page in data.get('data', []):
                if page['id'] == self.page_id:
                    self._page_access_token = page['access_token']
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Failed to get page access token: {e}")
            return False
    
    def _get_access_token(self) -> str:
        """Get the appropriate access token (page or user)."""
        if self.page_id and self._page_access_token:
            return self._page_access_token
        return self.credentials.access_token
    
    def upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable[[UploadProgress], None]] = None
    ) -> UploadResult:
        """
        Upload a video to Facebook.
        
        Uses resumable upload for large files.
        
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
                    error_message="Not authenticated with Facebook."
                )
        
        try:
            file_size = os.path.getsize(video_path)
            
            # Use resumable upload for files > 1GB, otherwise simple upload
            if file_size > 1 * 1024 * 1024 * 1024:
                result = self._upload_resumable(video_path, metadata)
            else:
                result = self._upload_simple(video_path, metadata)
            
            if result:
                self._update_progress(UploadStatus.COMPLETED, message="Upload complete!")
                
                upload_time = time.time() - start_time
                video_id = result.get('id') or result.get('video_id')
                
                # Build video URL
                if self.page_id:
                    video_url = f"https://www.facebook.com/{self.page_id}/videos/{video_id}"
                else:
                    video_url = f"https://www.facebook.com/watch/?v={video_id}"
                
                return UploadResult(
                    success=True,
                    platform=self.PLATFORM_NAME,
                    video_id=video_id,
                    video_url=video_url,
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
                error_message=f"Facebook quota exceeded: {e}"
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
            logger.exception("Facebook upload failed")
            self._update_progress(UploadStatus.FAILED, message=str(e))
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=str(e)
            )
    
    def _upload_simple(
        self,
        video_path: str,
        metadata: VideoMetadata
    ) -> Optional[Dict[str, Any]]:
        """Simple upload for smaller videos (< 1GB)."""
        self._update_progress(UploadStatus.PREPARING, message="Preparing upload...")
        
        file_size = os.path.getsize(video_path)
        filename = os.path.basename(video_path)
        access_token = self._get_access_token()
        
        # Create multipart form data
        boundary = '----WebKitFormBoundary' + str(int(time.time() * 1000))
        
        self._update_progress(
            UploadStatus.UPLOADING,
            bytes_uploaded=0,
            total_bytes=file_size,
            message="Uploading video..."
        )
        
        try:
            with open(video_path, 'rb') as f:
                video_data = f.read()
            
            # Build multipart body
            body_parts = []
            
            # Access token
            body_parts.append(f'--{boundary}'.encode())
            body_parts.append(b'Content-Disposition: form-data; name="access_token"')
            body_parts.append(b'')
            body_parts.append(access_token.encode())
            
            # Title
            body_parts.append(f'--{boundary}'.encode())
            body_parts.append(b'Content-Disposition: form-data; name="title"')
            body_parts.append(b'')
            body_parts.append(metadata.title.encode())
            
            # Description
            body_parts.append(f'--{boundary}'.encode())
            body_parts.append(b'Content-Disposition: form-data; name="description"')
            body_parts.append(b'')
            body_parts.append(metadata.description.encode())
            
            # Privacy
            privacy_value = self._map_privacy(metadata.privacy)
            body_parts.append(f'--{boundary}'.encode())
            body_parts.append(b'Content-Disposition: form-data; name="privacy"')
            body_parts.append(b'')
            body_parts.append(json.dumps(privacy_value).encode())
            
            # Facebook-specific settings
            fb_settings = metadata.facebook_settings
            
            # === Cross-platform compliance fields ===
            # Embeddable setting
            if not metadata.allow_embedding:
                body_parts.append(f'--{boundary}'.encode())
                body_parts.append(b'Content-Disposition: form-data; name="embeddable"')
                body_parts.append(b'')
                body_parts.append(b'false')
            
            # === Facebook-specific settings ===
            if fb_settings:
                # Secret video (unlisted, only accessible via direct link)
                if fb_settings.get('secret'):
                    body_parts.append(f'--{boundary}'.encode())
                    body_parts.append(b'Content-Disposition: form-data; name="secret"')
                    body_parts.append(b'')
                    body_parts.append(b'true')
                
                # Unpublished (draft) video
                if fb_settings.get('unpublished'):
                    body_parts.append(f'--{boundary}'.encode())
                    body_parts.append(b'Content-Disposition: form-data; name="unpublished"')
                    body_parts.append(b'')
                    body_parts.append(b'true')
                
                # Content category
                if 'content_category' in fb_settings:
                    body_parts.append(f'--{boundary}'.encode())
                    body_parts.append(b'Content-Disposition: form-data; name="content_category"')
                    body_parts.append(b'')
                    body_parts.append(fb_settings['content_category'].encode())
                
                # Sponsor ID for branded content
                if 'sponsor_id' in fb_settings:
                    body_parts.append(f'--{boundary}'.encode())
                    body_parts.append(b'Content-Disposition: form-data; name="sponsor_id"')
                    body_parts.append(b'')
                    body_parts.append(fb_settings['sponsor_id'].encode())
                
                # Targeting (for pages)
                if 'targeting' in fb_settings:
                    body_parts.append(f'--{boundary}'.encode())
                    body_parts.append(b'Content-Disposition: form-data; name="targeting"')
                    body_parts.append(b'')
                    body_parts.append(json.dumps(fb_settings['targeting']).encode())
                
                # Feed targeting (age, location, etc.)
                if 'feed_targeting' in fb_settings:
                    body_parts.append(f'--{boundary}'.encode())
                    body_parts.append(b'Content-Disposition: form-data; name="feed_targeting"')
                    body_parts.append(b'')
                    body_parts.append(json.dumps(fb_settings['feed_targeting']).encode())
                
                # Backdated time (for historical posts)
                if 'backdated_time' in fb_settings:
                    body_parts.append(f'--{boundary}'.encode())
                    body_parts.append(b'Content-Disposition: form-data; name="backdated_time"')
                    body_parts.append(b'')
                    body_parts.append(str(fb_settings['backdated_time']).encode())
            
            # Scheduled publish time
            if metadata.scheduled_time:
                body_parts.append(f'--{boundary}'.encode())
                body_parts.append(b'Content-Disposition: form-data; name="scheduled_publish_time"')
                body_parts.append(b'')
                body_parts.append(str(int(metadata.scheduled_time)).encode())
                
                body_parts.append(f'--{boundary}'.encode())
                body_parts.append(b'Content-Disposition: form-data; name="published"')
                body_parts.append(b'')
                body_parts.append(b'false')
            
            # Video file
            body_parts.append(f'--{boundary}'.encode())
            body_parts.append(
                f'Content-Disposition: form-data; name="source"; filename="{filename}"'.encode()
            )
            body_parts.append(b'Content-Type: video/mp4')
            body_parts.append(b'')
            body_parts.append(video_data)
            
            body_parts.append(f'--{boundary}--'.encode())
            
            body = b'\r\n'.join(body_parts)
            
            url = f"{self.UPLOAD_BASE}/{self.target_id}/videos"
            
            headers = {
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'Content-Length': str(len(body))
            }
            
            req = urllib.request.Request(url, data=body, headers=headers, method='POST')
            
            with urllib.request.urlopen(req, timeout=1800) as response:
                result = json.loads(response.read().decode())
            
            self._update_progress(
                UploadStatus.UPLOADING,
                bytes_uploaded=file_size,
                total_bytes=file_size
            )
            
            return result
            
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return None
    
    def _upload_resumable(
        self,
        video_path: str,
        metadata: VideoMetadata
    ) -> Optional[Dict[str, Any]]:
        """Resumable upload for large videos (> 1GB)."""
        self._update_progress(UploadStatus.PREPARING, message="Initializing resumable upload...")
        
        file_size = os.path.getsize(video_path)
        access_token = self._get_access_token()
        
        # Step 1: Start upload session
        start_url = f"{self.UPLOAD_BASE}/{self.target_id}/videos"
        
        start_params = {
            'access_token': access_token,
            'upload_phase': 'start',
            'file_size': file_size
        }
        
        try:
            start_data = urllib.parse.urlencode(start_params).encode()
            req = urllib.request.Request(start_url, data=start_data, method='POST')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                start_result = json.loads(response.read().decode())
            
            upload_session_id = start_result['upload_session_id']
            video_id = start_result['video_id']
            
            # Step 2: Upload chunks
            self._update_progress(
                UploadStatus.UPLOADING,
                bytes_uploaded=0,
                total_bytes=file_size,
                message="Uploading video chunks..."
            )
            
            start_time = time.time()
            start_offset = 0
            
            with open(video_path, 'rb') as f:
                while start_offset < file_size:
                    # Check for cancel
                    if self._check_cancelled():
                        self._update_progress(UploadStatus.CANCELLED)
                        return None
                    
                    # Wait if paused
                    self._wait_if_paused()
                    
                    chunk = f.read(self._chunk_size)
                    if not chunk:
                        break
                    
                    # Upload chunk
                    chunk_result = self._upload_chunk(
                        upload_session_id,
                        start_offset,
                        chunk,
                        access_token
                    )
                    
                    if not chunk_result:
                        return None
                    
                    # Get next offset from response
                    start_offset = int(chunk_result.get('start_offset', start_offset + len(chunk)))
                    f.seek(start_offset)
                    
                    # Calculate speed and ETA
                    speed, eta = self._calculate_speed_and_eta(
                        start_offset, file_size, start_time
                    )
                    
                    self._update_progress(
                        UploadStatus.UPLOADING,
                        bytes_uploaded=start_offset,
                        total_bytes=file_size,
                        speed=speed,
                        eta=eta
                    )
            
            # Step 3: Finish upload
            self._update_progress(UploadStatus.PROCESSING, message="Finalizing upload...")
            
            finish_params = {
                'access_token': access_token,
                'upload_phase': 'finish',
                'upload_session_id': upload_session_id,
                'title': metadata.title,
                'description': metadata.description,
                'privacy': json.dumps(self._map_privacy(metadata.privacy))
            }
            
            if metadata.scheduled_time:
                finish_params['scheduled_publish_time'] = int(metadata.scheduled_time)
                finish_params['published'] = 'false'
            
            finish_data = urllib.parse.urlencode(finish_params).encode()
            req = urllib.request.Request(start_url, data=finish_data, method='POST')
            
            with urllib.request.urlopen(req, timeout=60) as response:
                finish_result = json.loads(response.read().decode())
            
            return {'id': video_id, **finish_result}
            
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return None
    
    def _upload_chunk(
        self,
        session_id: str,
        start_offset: int,
        chunk: bytes,
        access_token: str
    ) -> Optional[Dict[str, Any]]:
        """Upload a single chunk."""
        boundary = '----WebKitFormBoundary' + str(int(time.time() * 1000))
        
        body_parts = []
        
        body_parts.append(f'--{boundary}'.encode())
        body_parts.append(b'Content-Disposition: form-data; name="access_token"')
        body_parts.append(b'')
        body_parts.append(access_token.encode())
        
        body_parts.append(f'--{boundary}'.encode())
        body_parts.append(b'Content-Disposition: form-data; name="upload_phase"')
        body_parts.append(b'')
        body_parts.append(b'transfer')
        
        body_parts.append(f'--{boundary}'.encode())
        body_parts.append(b'Content-Disposition: form-data; name="upload_session_id"')
        body_parts.append(b'')
        body_parts.append(session_id.encode())
        
        body_parts.append(f'--{boundary}'.encode())
        body_parts.append(b'Content-Disposition: form-data; name="start_offset"')
        body_parts.append(b'')
        body_parts.append(str(start_offset).encode())
        
        body_parts.append(f'--{boundary}'.encode())
        body_parts.append(b'Content-Disposition: form-data; name="video_file_chunk"; filename="chunk"')
        body_parts.append(b'Content-Type: application/octet-stream')
        body_parts.append(b'')
        body_parts.append(chunk)
        
        body_parts.append(f'--{boundary}--'.encode())
        
        body = b'\r\n'.join(body_parts)
        
        url = f"{self.UPLOAD_BASE}/{self.target_id}/videos"
        
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}'
        }
        
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method='POST')
            
            with urllib.request.urlopen(req, timeout=300) as response:
                return json.loads(response.read().decode())
                
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return None
    
    def _map_privacy(self, privacy: str) -> Dict[str, str]:
        """Map privacy setting to Facebook format."""
        privacy_map = {
            'public': {'value': 'EVERYONE'},
            'private': {'value': 'SELF'},
            'unlisted': {'value': 'CUSTOM', 'allow': 'SELF'}
        }
        return privacy_map.get(privacy, {'value': 'SELF'})
    
    def _handle_api_error(self, error: urllib.error.HTTPError):
        """Handle Facebook API errors."""
        try:
            error_body = json.loads(error.read().decode())
            error_info = error_body.get('error', {})
            message = error_info.get('message', str(error))
            code = error_info.get('code', 0)
            
            if code in (190, 102):  # OAuth errors
                raise AuthenticationError(message)
            elif code == 4:  # Rate limit
                raise RateLimitError(message, retry_after=600)
            elif code == 17:  # Quota exceeded
                raise QuotaExceededError(message)
            
            raise UploadError(message)
            
        except json.JSONDecodeError:
            raise UploadError(f"HTTP {error.code}: {error.reason}")
    
    def get_user_info(self) -> Dict[str, Any]:
        """Get authenticated user info."""
        url = f"{self.API_BASE}/me?fields=id,name,picture&access_token={self.credentials.access_token}"
        
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            return {
                'id': data.get('id'),
                'name': data.get('name'),
                'picture': data.get('picture', {}).get('data', {}).get('url')
            }
            
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return {}
    
    def get_pages(self) -> List[Dict[str, Any]]:
        """Get list of pages the user manages."""
        url = f"{self.API_BASE}/me/accounts?access_token={self.credentials.access_token}"
        
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            return [
                {
                    'id': page['id'],
                    'name': page['name'],
                    'category': page.get('category')
                }
                for page in data.get('data', [])
            ]
            
        except Exception:
            return []
    
    def set_page(self, page_id: str) -> bool:
        """Set the target page for uploads."""
        self.page_id = page_id
        return self._get_page_access_token()
    
    def get_quota_info(self) -> Dict[str, Any]:
        """Get current API quota information."""
        return {
            'max_video_size': '10 GB',
            'max_video_length': '240 minutes',
            'rate_limits': 'Varies by app'
        }
    
    def delete_video(self, video_id: str) -> bool:
        """Delete an uploaded video."""
        url = f"{self.API_BASE}/{video_id}?access_token={self._get_access_token()}"
        
        try:
            req = urllib.request.Request(url, method='DELETE')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                return result.get('success', False)
                
        except urllib.error.HTTPError:
            return False
    
    def update_video(
        self,
        video_id: str,
        metadata: VideoMetadata
    ) -> bool:
        """Update video metadata."""
        url = f"{self.API_BASE}/{video_id}"
        
        params = {
            'access_token': self._get_access_token(),
            'title': metadata.title,
            'description': metadata.description,
            'privacy': json.dumps(self._map_privacy(metadata.privacy))
        }
        
        try:
            data = urllib.parse.urlencode(params).encode()
            req = urllib.request.Request(url, data=data, method='POST')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                return result.get('success', False)
                
        except urllib.error.HTTPError:
            return False
    
    def get_video_insights(self, video_id: str) -> Dict[str, Any]:
        """Get video insights/analytics."""
        url = (
            f"{self.API_BASE}/{video_id}/video_insights?"
            f"access_token={self._get_access_token()}"
        )
        
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            insights = {}
            for item in data.get('data', []):
                name = item.get('name')
                values = item.get('values', [{}])
                if values:
                    insights[name] = values[0].get('value')
            
            return insights
            
        except Exception:
            return {}
