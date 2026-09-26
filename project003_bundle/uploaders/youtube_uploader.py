"""
YouTube Uploader - Upload videos to YouTube using Data API v3.

Requires OAuth 2.0 credentials with youtube.upload scope.
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


class YouTubeUploader(BaseUploader):
    """YouTube video uploader using Data API v3."""
    
    PLATFORM_NAME = "YouTube"
    MAX_FILE_SIZE = 256 * 1024 * 1024 * 1024  # 256 GB
    SUPPORTED_FORMATS = [
        'mp4', 'avi', 'wmv', 'mov', 'flv', 'webm', 'mkv',
        '3gp', 'mpeg', 'mpg', 'm4v'
    ]
    MAX_TITLE_LENGTH = 100
    MAX_DESCRIPTION_LENGTH = 5000
    MAX_TAGS = 500  # Total characters, not count
    
    # API endpoints
    API_BASE = "https://www.googleapis.com/youtube/v3"
    UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
    
    # Video categories
    CATEGORIES = {
        'Film & Animation': '1',
        'Autos & Vehicles': '2',
        'Music': '10',
        'Pets & Animals': '15',
        'Sports': '17',
        'Short Movies': '18',
        'Travel & Events': '19',
        'Gaming': '20',
        'Videoblogging': '21',
        'People & Blogs': '22',
        'Comedy': '23',
        'Entertainment': '24',
        'News & Politics': '25',
        'Howto & Style': '26',
        'Education': '27',
        'Science & Technology': '28',
        'Nonprofits & Activism': '29',
        'Movies': '30',
        'Anime/Animation': '31',
        'Action/Adventure': '32',
        'Classics': '33',
        'Documentary': '35',
        'Drama': '36',
        'Family': '37',
        'Foreign': '38',
        'Horror': '39',
        'Sci-Fi/Fantasy': '40',
        'Thriller': '41',
        'Shorts': '42',
        'Shows': '43',
        'Trailers': '44'
    }
    
    def __init__(self, credentials: PlatformCredentials):
        """Initialize YouTube uploader."""
        super().__init__(credentials)
        self._upload_session_url: Optional[str] = None
        self._chunk_size = 5 * 1024 * 1024  # 5 MB chunks
    
    @property
    def is_authenticated(self) -> bool:
        """Check if uploader is authenticated."""
        return self.credentials.is_authenticated
    
    def authenticate(self) -> bool:
        """
        Perform authentication flow.
        
        Note: Use AuthManager for full OAuth flow.
        This method assumes tokens are already set.
        """
        if self.credentials.access_token:
            # Verify token by making a test request
            try:
                self.get_user_info()
                return True
            except AuthenticationError:
                return False
        return False
    
    def refresh_token(self) -> bool:
        """
        Refresh the access token.
        
        Note: Use AuthManager for token refresh.
        """
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
                'https://oauth2.googleapis.com/token',
                data=encoded,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                token_data = json.loads(response.read().decode())
            
            self.credentials.access_token = token_data['access_token']
            self.credentials.token_expiry = time.time() + token_data.get('expires_in', 3600)
            
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
        Upload a video to YouTube.
        
        Uses resumable upload protocol for reliability.
        
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
                    error_message="Not authenticated with YouTube."
                )
        
        try:
            self._update_progress(UploadStatus.PREPARING, message="Preparing upload...")
            
            # Initialize resumable upload
            session_url = self._init_resumable_upload(video_path, metadata)
            if not session_url:
                return UploadResult(
                    success=False,
                    platform=self.PLATFORM_NAME,
                    error_message="Failed to initialize upload session"
                )
            
            self._upload_session_url = session_url
            
            # Upload file in chunks
            self._update_progress(UploadStatus.UPLOADING, message="Uploading video...")
            result = self._upload_file_resumable(video_path, session_url)
            
            if result:
                # Set thumbnail if provided
                if metadata.thumbnail_path and os.path.exists(metadata.thumbnail_path):
                    self._update_progress(UploadStatus.PROCESSING, message="Setting thumbnail...")
                    self._set_thumbnail(result['id'], metadata.thumbnail_path)
                
                self._update_progress(UploadStatus.COMPLETED, message="Upload complete!")
                
                upload_time = time.time() - start_time
                video_url = f"https://www.youtube.com/watch?v={result['id']}"
                
                return UploadResult(
                    success=True,
                    platform=self.PLATFORM_NAME,
                    video_id=result['id'],
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
                error_message=f"YouTube quota exceeded: {e}"
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
            logger.exception("YouTube upload failed")
            self._update_progress(UploadStatus.FAILED, message=str(e))
            return UploadResult(
                success=False,
                platform=self.PLATFORM_NAME,
                error_message=str(e)
            )
    
    def _init_resumable_upload(
        self,
        video_path: str,
        metadata: VideoMetadata
    ) -> Optional[str]:
        """
        Initialize a resumable upload session.
        
        Returns:
            Session URL for resumable upload
        """
        # Build video resource
        body = {
            'snippet': {
                'title': metadata.title,
                'description': metadata.description,
                'tags': metadata.tags,
                'categoryId': self._get_category_id(metadata.category),
                'defaultLanguage': metadata.language,
                'defaultAudioLanguage': metadata.audio_language or metadata.language
            },
            'status': {
                'privacyStatus': metadata.privacy,
                'selfDeclaredMadeForKids': metadata.made_for_kids,
                'embeddable': metadata.allow_embedding
            }
        }
        
        # === Cross-platform compliance fields ===
        # AI/Synthetic content disclosure (YouTube requirement since 2024)
        if metadata.contains_ai_content:
            body['status']['containsSyntheticMedia'] = True
        
        # Paid promotion disclosure
        if metadata.has_paid_promotion:
            body['paidProductPlacementDetails'] = {
                'hasPaidProductPlacement': True
            }
        
        # Recording date
        if metadata.recording_date:
            body['recordingDetails'] = {
                'recordingDate': metadata.recording_date
            }
        
        # === YouTube-specific settings ===
        yt_settings = metadata.youtube_settings
        if yt_settings:
            # License: 'youtube' (standard) or 'creativeCommon'
            if 'license' in yt_settings:
                body['status']['license'] = yt_settings['license']
            
            # Whether extended video statistics are publicly viewable
            if 'publicStatsViewable' in yt_settings:
                body['status']['publicStatsViewable'] = yt_settings['publicStatsViewable']
            
            # Multi-language localizations
            if 'localizations' in yt_settings and yt_settings['localizations']:
                body['localizations'] = yt_settings['localizations']
                # Example format: {'es': {'title': 'Título', 'description': 'Descripción'}}
            
            # Recording location (latitude/longitude)
            if 'location' in yt_settings:
                if 'recordingDetails' not in body:
                    body['recordingDetails'] = {}
                body['recordingDetails']['location'] = yt_settings['location']
                # Example: {'latitude': 37.7749, 'longitude': -122.4194}
            
            # Override made_for_kids if explicitly set in platform settings
            if 'madeForKids' in yt_settings:
                body['status']['selfDeclaredMadeForKids'] = yt_settings['madeForKids']
            
            # Override embeddable if explicitly set
            if 'embeddable' in yt_settings:
                body['status']['embeddable'] = yt_settings['embeddable']
        
        # Handle scheduled uploads
        if metadata.scheduled_time and metadata.privacy == 'private':
            body['status']['privacyStatus'] = 'private'
            body['status']['publishAt'] = time.strftime(
                '%Y-%m-%dT%H:%M:%S.000Z',
                time.gmtime(metadata.scheduled_time)
            )
        
        # Get file size and MIME type
        file_size = os.path.getsize(video_path)
        mime_type, _ = mimetypes.guess_type(video_path)
        if not mime_type:
            mime_type = 'video/mp4'
        
        # Build request - include all parts we're using
        # snippet, status are always included
        # recordingDetails for recording date/location
        # localizations for multi-language metadata
        # paidProductPlacementDetails for sponsorship disclosure
        parts = ['snippet', 'status']
        if 'recordingDetails' in body:
            parts.append('recordingDetails')
        if 'localizations' in body:
            parts.append('localizations')
        if 'paidProductPlacementDetails' in body:
            # Note: This is part of status in newer API versions
            pass
        
        url = f"{self.UPLOAD_URL}?uploadType=resumable&part={','.join(parts)}"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}',
            'Content-Type': 'application/json; charset=UTF-8',
            'X-Upload-Content-Type': mime_type,
            'X-Upload-Content-Length': str(file_size)
        }
        
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode(),
                headers=headers,
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                # Get session URL from Location header
                return response.headers.get('Location')
                
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return None
    
    def _upload_file_resumable(
        self,
        video_path: str,
        session_url: str
    ) -> Optional[Dict[str, Any]]:
        """
        Upload file using resumable upload protocol.
        
        Returns:
            Video resource dict if successful
        """
        file_size = os.path.getsize(video_path)
        mime_type, _ = mimetypes.guess_type(video_path)
        if not mime_type:
            mime_type = 'video/mp4'
        
        bytes_uploaded = 0
        start_time = time.time()
        
        self._update_progress(
            UploadStatus.UPLOADING,
            bytes_uploaded=0,
            total_bytes=file_size
        )
        
        with open(video_path, 'rb') as f:
            while bytes_uploaded < file_size:
                # Check for cancel
                if self._check_cancelled():
                    self._update_progress(UploadStatus.CANCELLED)
                    return None
                
                # Wait if paused
                self._wait_if_paused()
                
                # Read chunk
                chunk = f.read(self._chunk_size)
                if not chunk:
                    break
                
                chunk_size = len(chunk)
                start_byte = bytes_uploaded
                end_byte = bytes_uploaded + chunk_size - 1
                
                headers = {
                    'Content-Type': mime_type,
                    'Content-Length': str(chunk_size),
                    'Content-Range': f'bytes {start_byte}-{end_byte}/{file_size}'
                }
                
                try:
                    req = urllib.request.Request(
                        session_url,
                        data=chunk,
                        headers=headers,
                        method='PUT'
                    )
                    
                    with urllib.request.urlopen(req, timeout=120) as response:
                        status_code = response.getcode()
                        
                        if status_code in (200, 201):
                            # Upload complete
                            return json.loads(response.read().decode())
                        elif status_code == 308:
                            # Resume incomplete - continue
                            pass
                    
                except urllib.error.HTTPError as e:
                    if e.code == 308:
                        # Resume incomplete - get range and continue
                        range_header = e.headers.get('Range')
                        if range_header:
                            uploaded = int(range_header.split('-')[1]) + 1
                            bytes_uploaded = uploaded
                            f.seek(uploaded)
                            continue
                    else:
                        self._handle_api_error(e)
                        return None
                
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
        
        return None
    
    def _set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """Set custom thumbnail for a video."""
        try:
            with open(thumbnail_path, 'rb') as f:
                thumbnail_data = f.read()
            
            mime_type, _ = mimetypes.guess_type(thumbnail_path)
            if not mime_type:
                mime_type = 'image/jpeg'
            
            url = f"{self.API_BASE}/thumbnails/set?videoId={video_id}"
            
            headers = {
                'Authorization': f'Bearer {self.credentials.access_token}',
                'Content-Type': mime_type
            }
            
            req = urllib.request.Request(
                url,
                data=thumbnail_data,
                headers=headers,
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.getcode() == 200
                
        except Exception as e:
            logger.error(f"Failed to set thumbnail: {e}")
            return False
    
    def _get_category_id(self, category_name: str) -> str:
        """Get YouTube category ID from name."""
        if category_name in self.CATEGORIES:
            return self.CATEGORIES[category_name]
        
        # Try to find partial match
        for name, id_ in self.CATEGORIES.items():
            if category_name.lower() in name.lower():
                return id_
        
        return '22'  # Default to "People & Blogs"
    
    def _handle_api_error(self, error: urllib.error.HTTPError):
        """Handle YouTube API errors."""
        try:
            error_body = json.loads(error.read().decode())
            error_info = error_body.get('error', {})
            message = error_info.get('message', str(error))
            errors = error_info.get('errors', [])
            
            if errors:
                reason = errors[0].get('reason', '')
                
                if reason == 'quotaExceeded':
                    raise QuotaExceededError(message)
                elif reason in ('rateLimitExceeded', 'userRateLimitExceeded'):
                    raise RateLimitError(message, retry_after=60)
                elif reason in ('authError', 'forbidden', 'unauthorized'):
                    raise AuthenticationError(message)
            
            raise UploadError(message)
            
        except json.JSONDecodeError:
            raise UploadError(f"HTTP {error.code}: {error.reason}")
    
    def get_user_info(self) -> Dict[str, Any]:
        """Get authenticated user's channel info."""
        url = f"{self.API_BASE}/channels?part=snippet,statistics&mine=true"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}'
        }
        
        try:
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            if data.get('items'):
                channel = data['items'][0]
                return {
                    'id': channel['id'],
                    'title': channel['snippet']['title'],
                    'description': channel['snippet'].get('description', ''),
                    'thumbnail': channel['snippet']['thumbnails']['default']['url'],
                    'subscriber_count': channel['statistics'].get('subscriberCount'),
                    'video_count': channel['statistics'].get('videoCount')
                }
            
            return {}
            
        except urllib.error.HTTPError as e:
            self._handle_api_error(e)
            return {}
    
    def get_quota_info(self) -> Dict[str, Any]:
        """
        Get current API quota information.
        
        Note: YouTube API doesn't provide direct quota info.
        This returns general quota limits.
        """
        return {
            'daily_quota': 10000,
            'upload_cost': 1600,  # Units per upload
            'estimated_uploads_remaining': 'Unknown'
        }
    
    def get_video_status(self, video_id: str) -> Dict[str, Any]:
        """Get processing status of an uploaded video."""
        url = f"{self.API_BASE}/videos?part=processingDetails,status&id={video_id}"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}'
        }
        
        try:
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
            
            if data.get('items'):
                video = data['items'][0]
                return {
                    'upload_status': video['status'].get('uploadStatus'),
                    'privacy_status': video['status'].get('privacyStatus'),
                    'processing_status': video.get('processingDetails', {}).get('processingStatus'),
                    'processing_progress': video.get('processingDetails', {}).get('processingProgress', {})
                }
            
            return {}
            
        except urllib.error.HTTPError:
            return {}
    
    def delete_video(self, video_id: str) -> bool:
        """Delete an uploaded video."""
        url = f"{self.API_BASE}/videos?id={video_id}"
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}'
        }
        
        try:
            req = urllib.request.Request(url, headers=headers, method='DELETE')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.getcode() == 204
                
        except urllib.error.HTTPError:
            return False
    
    def update_video(
        self,
        video_id: str,
        metadata: VideoMetadata
    ) -> bool:
        """Update video metadata."""
        url = f"{self.API_BASE}/videos?part=snippet,status"
        
        body = {
            'id': video_id,
            'snippet': {
                'title': metadata.title,
                'description': metadata.description,
                'tags': metadata.tags,
                'categoryId': self._get_category_id(metadata.category)
            },
            'status': {
                'privacyStatus': metadata.privacy
            }
        }
        
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode(),
                headers=headers,
                method='PUT'
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.getcode() == 200
                
        except urllib.error.HTTPError:
            return False
