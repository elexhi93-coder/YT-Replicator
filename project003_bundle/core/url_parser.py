"""
URL Parser for IDM-YT Video Downloader
Parses and classifies video URLs from various platforms
"""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dataclasses import dataclass

from .enums import URLType


@dataclass
class ParsedURL:
    """Parsed URL information"""
    original_url: str
    cleaned_url: str
    url_type: URLType
    video_id: Optional[str] = None
    playlist_id: Optional[str] = None
    channel_id: Optional[str] = None
    channel_handle: Optional[str] = None
    platform: str = "unknown"
    
    @property
    def is_youtube(self) -> bool:
        return self.platform == "youtube"
    
    @property
    def is_collection(self) -> bool:
        return self.url_type.is_collection


class URLParser:
    """
    Parses and classifies video URLs from various platforms.
    Supports YouTube, Vimeo, Dailymotion, Twitch, and more.
    """
    
    # Regex patterns for URL detection
    YOUTUBE_PATTERNS = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]
    
    YOUTUBE_PLAYLIST_PATTERN = r'[?&]list=([a-zA-Z0-9_-]+)'
    YOUTUBE_CHANNEL_PATTERNS = [
        r'(?:https?://)?(?:www\.)?youtube\.com/@([a-zA-Z0-9_-]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/channel/([a-zA-Z0-9_-]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/c/([a-zA-Z0-9_-]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/user/([a-zA-Z0-9_-]+)',
    ]
    
    VIDEO_URL_PATTERN = re.compile(
        r'(https?://)?(www\.)?(youtube|youtu|vimeo|dailymotion|twitch)\.(com|be|tv)/',
        re.IGNORECASE
    )
    
    @classmethod
    def parse(cls, url: str) -> ParsedURL:
        """
        Parse a video URL and extract all relevant information.
        
        Args:
            url: Raw URL string
            
        Returns:
            ParsedURL with extracted information
        """
        url = url.strip()
        
        # Detect platform
        platform = cls._detect_platform(url)
        
        if platform == "youtube":
            return cls._parse_youtube(url)
        elif platform == "vimeo":
            return cls._parse_vimeo(url)
        else:
            return ParsedURL(
                original_url=url,
                cleaned_url=url,
                url_type=URLType.UNKNOWN,
                platform=platform,
            )
    
    @classmethod
    def _detect_platform(cls, url: str) -> str:
        """Detect the video platform from URL"""
        url_lower = url.lower()
        
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return "youtube"
        elif 'vimeo.com' in url_lower:
            return "vimeo"
        elif 'dailymotion.com' in url_lower:
            return "dailymotion"
        elif 'twitch.tv' in url_lower:
            return "twitch"
        
        return "unknown"
    
    @classmethod
    def _parse_youtube(cls, url: str) -> ParsedURL:
        """Parse YouTube URL"""
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        video_id = None
        playlist_id = None
        channel_id = None
        channel_handle = None
        url_type = URLType.UNKNOWN
        
        # Extract video ID
        for pattern in cls.YOUTUBE_PATTERNS:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break
        
        # Also check 'v' parameter
        if not video_id and 'v' in params:
            video_id = params['v'][0]
        
        # Extract playlist ID
        if 'list' in params:
            playlist_id = params['list'][0]
        
        # Check for channel URLs
        for pattern in cls.YOUTUBE_CHANNEL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                identifier = match.group(1)
                if '/@' in url or pattern == cls.YOUTUBE_CHANNEL_PATTERNS[0]:
                    channel_handle = identifier
                else:
                    channel_id = identifier
                break
        
        # Determine URL type
        if channel_handle or channel_id:
            if '/shorts' in url:
                url_type = URLType.CHANNEL_SHORTS
            elif '/streams' in url:
                url_type = URLType.CHANNEL_STREAMS
            elif '/videos' in url:
                url_type = URLType.CHANNEL_VIDEOS
            else:
                url_type = URLType.CHANNEL
        elif playlist_id:
            url_type = URLType.PLAYLIST
        elif video_id:
            url_type = URLType.SINGLE_VIDEO
        
        # Build cleaned URL
        cleaned_url = cls._clean_youtube_url(url, url_type, video_id, playlist_id)
        
        return ParsedURL(
            original_url=url,
            cleaned_url=cleaned_url,
            url_type=url_type,
            video_id=video_id,
            playlist_id=playlist_id,
            channel_id=channel_id,
            channel_handle=channel_handle,
            platform="youtube",
        )
    
    @classmethod
    def _parse_vimeo(cls, url: str) -> ParsedURL:
        """Parse Vimeo URL"""
        match = re.search(r'vimeo\.com/(\d+)', url)
        video_id = match.group(1) if match else None
        
        return ParsedURL(
            original_url=url,
            cleaned_url=url,
            url_type=URLType.SINGLE_VIDEO if video_id else URLType.UNKNOWN,
            video_id=video_id,
            platform="vimeo",
        )
    
    @classmethod
    def _clean_youtube_url(
        cls,
        url: str,
        url_type: URLType,
        video_id: Optional[str],
        playlist_id: Optional[str],
    ) -> str:
        """
        Clean YouTube URL by removing unnecessary parameters.
        
        Args:
            url: Original URL
            url_type: Detected URL type
            video_id: Extracted video ID
            playlist_id: Extracted playlist ID
            
        Returns:
            Cleaned URL string
        """
        if url_type == URLType.SINGLE_VIDEO and video_id:
            # Single video - remove playlist parameter
            return f"https://www.youtube.com/watch?v={video_id}"
        
        elif url_type == URLType.PLAYLIST and playlist_id:
            return f"https://www.youtube.com/playlist?list={playlist_id}"
        
        elif url_type.is_channel:
            # Ensure channel URL ends with proper tab
            parsed = urlparse(url)
            path = parsed.path.rstrip('/')
            
            if url_type == URLType.CHANNEL_VIDEOS:
                if not path.endswith('/videos'):
                    path = f"{path}/videos"
            elif url_type == URLType.CHANNEL_SHORTS:
                if not path.endswith('/shorts'):
                    path = f"{path}/shorts"
            elif url_type == URLType.CHANNEL_STREAMS:
                if not path.endswith('/streams'):
                    path = f"{path}/streams"
            else:
                # Default to videos tab
                if not path.endswith(('/videos', '/shorts', '/streams')):
                    path = f"{path}/videos"
            
            return urlunparse((
                'https',
                'www.youtube.com',
                path,
                '', '', '',
            ))
        
        return url
    
    @classmethod
    def is_valid_video_url(cls, url: str) -> bool:
        """
        Check if a string is a valid video URL.
        
        Args:
            url: URL string to check
            
        Returns:
            True if valid video URL, False otherwise
        """
        if not url or not isinstance(url, str):
            return False
        
        return bool(cls.VIDEO_URL_PATTERN.search(url))
    
    @classmethod
    def extract_from_text(cls, text: str) -> list:
        """
        Extract all video URLs from a text block.
        
        Args:
            text: Text that may contain URLs
            
        Returns:
            List of extracted URLs
        """
        # General URL pattern
        url_pattern = re.compile(
            r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|vimeo\.com|'
            r'dailymotion\.com|twitch\.tv)/[^\s<>"\']+',
            re.IGNORECASE
        )
        
        matches = url_pattern.findall(text)
        
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for url in matches:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        
        return unique
