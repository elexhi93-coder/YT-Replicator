"""
Video Controller for IDM-YT
Handles video information fetching and format parsing.
"""

import re
import threading
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

from core import (
    URLParser, URLType, ParsedURL,
    FormatParser, VideoFormat, AudioFormat,
    get_logger,
)


logger = get_logger("video_controller")


@dataclass
class VideoInfo:
    """Parsed video information"""
    id: str = ""
    title: str = ""
    description: str = ""
    duration: int = 0
    duration_str: str = ""
    uploader: str = ""
    view_count: int = 0
    view_count_str: str = ""
    upload_date: str = ""
    thumbnail_url: str = ""
    webpage_url: str = ""
    
    # Formats
    video_formats: list = field(default_factory=list)  # List of (display_str, format_id)
    audio_formats: list = field(default_factory=list)  # List of (display_str, format_id)
    
    # Raw data
    raw_info: dict = field(default_factory=dict)


@dataclass
class PlaylistInfo:
    """Parsed playlist information"""
    id: str = ""
    title: str = ""
    description: str = ""
    uploader: str = ""
    video_count: int = 0
    entries: list = field(default_factory=list)  # List of video entries
    
    # Raw data
    raw_info: dict = field(default_factory=dict)


class VideoController:
    """
    Controller for fetching and managing video/playlist information.
    
    Usage:
        controller = VideoController()
        
        # Set callbacks
        controller.on_video_info = lambda info: update_ui(info)
        controller.on_playlist_info = lambda info: show_playlist(info)
        controller.on_error = lambda e: show_error(e)
        controller.on_log = lambda msg: log(msg)
        
        # Fetch info
        controller.fetch_info("https://youtube.com/watch?v=...")
    """
    
    def __init__(
        self,
        on_info_fetched: Optional[Callable[[VideoInfo], None]] = None,
        on_playlist_fetched: Optional[Callable[[PlaylistInfo], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_thumbnail: Optional[Callable[[str], None]] = None,
    ):
        self._fetch_thread: Optional[threading.Thread] = None
        self._cancelled = False

        # URL parser
        self.url_parser = URLParser()

        # Callbacks (supports both old and new naming)
        self.on_video_info: Optional[Callable[[VideoInfo], None]] = on_info_fetched
        self.on_info_fetched: Optional[Callable[[VideoInfo], None]] = on_info_fetched
        self.on_playlist_info: Optional[Callable[[PlaylistInfo], None]] = on_playlist_fetched
        self.on_playlist_fetched: Optional[Callable[[PlaylistInfo], None]] = on_playlist_fetched
        self.on_error: Optional[Callable[[str], None]] = on_error
        self.on_log: Optional[Callable[[str], None]] = on_log
        self.on_thumbnail: Optional[Callable[[str], None]] = on_thumbnail
    
    def _log(self, message: str):
        """Log a message"""
        logger.info(message)
        if self.on_log:
            self.on_log(message)
    
    def _report_error(self, error: str):
        """Report error to listeners"""
        logger.error(error)
        if self.on_error:
            self.on_error(error)
    
    # ===== Public API =====
    
    def fetch_info(self, url: str) -> bool:
        """
        Fetch video or playlist information from URL.
        Returns True if fetch started, False if invalid URL.
        """
        # Parse and validate URL
        parsed = self.url_parser.parse(url)
        
        if parsed.url_type == URLType.UNKNOWN:
            self._report_error("Invalid URL. Please enter a valid video or playlist URL.")
            return False
        
        self._cancelled = False
        
        self._fetch_thread = threading.Thread(
            target=self._fetch_worker,
            args=(url, parsed),
            daemon=True,
        )
        self._fetch_thread.start()
        return True
    
    def cancel(self):
        """Cancel current fetch operation"""
        self._cancelled = True
    
    def parse_url(self, url: str) -> ParsedURL:
        """Parse URL without fetching"""
        return self.url_parser.parse(url)
    
    # ===== Fetch Worker =====
    
    def _fetch_worker(self, url: str, parsed: ParsedURL):
        """Worker thread for fetching video info"""
        try:
            self._log("🔍 Fetching video information...")
            
            # Determine if playlist or single video
            is_playlist = parsed.url_type in (URLType.PLAYLIST, URLType.CHANNEL)
            
            if is_playlist:
                self._fetch_playlist_info(url, parsed)
            else:
                self._fetch_video_info(url, parsed)
        
        except Exception as e:
            if not self._cancelled:
                import traceback
                error_details = traceback.format_exc()
                self._report_error(f"Error fetching info: {str(e)}")
                logger.error(f"Fetch error details:\n{error_details}")
    
    def _fetch_video_info(self, url: str, parsed: ParsedURL):
        """Fetch single video information"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        if self._cancelled:
            return
        
        # Parse into VideoInfo
        video_info = self._parse_video_info(info)
        
        self._log(f"📺 {video_info.title}")
        self._log(f"⏱️ Duration: {video_info.duration_str}")
        self._log(f"👤 {video_info.uploader}")
        self._log(f"👁️ {video_info.view_count_str} views")
        self._log(f"Found {len(video_info.video_formats)} video formats")
        
        # Notify thumbnail
        if video_info.thumbnail_url and self.on_thumbnail:
            self.on_thumbnail(video_info.thumbnail_url)
        
        # Notify listeners
        if self.on_video_info:
            self.on_video_info(video_info)
    
    def _fetch_playlist_info(self, url: str, parsed: ParsedURL):
        """Fetch playlist information"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,  # Don't fetch individual videos
            'playlistend': None,   # Get all videos
            'ignoreerrors': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        if self._cancelled:
            return
        
        # Parse into PlaylistInfo
        playlist_info = self._parse_playlist_info(info)
        
        self._log(f"📑 Playlist: {playlist_info.title}")
        self._log(f"📝 {playlist_info.video_count} videos found")
        
        # Notify listeners
        if self.on_playlist_info:
            self.on_playlist_info(playlist_info)
    
    # ===== Parsing =====
    
    def _parse_video_info(self, info: dict) -> VideoInfo:
        """Parse yt-dlp info dict into VideoInfo"""
        video_info = VideoInfo(
            id=info.get('id', ''),
            title=info.get('title', 'Unknown'),
            description=info.get('description', ''),
            duration=info.get('duration', 0),
            uploader=info.get('uploader', 'Unknown'),
            view_count=info.get('view_count', 0),
            upload_date=info.get('upload_date', ''),
            thumbnail_url=info.get('thumbnail', ''),
            webpage_url=info.get('webpage_url', ''),
            raw_info=info,
        )
        
        # Format duration
        video_info.duration_str = FormatParser.format_duration(video_info.duration)
        
        # Format view count
        video_info.view_count_str = FormatParser.format_views(video_info.view_count)
        
        # Parse formats
        video_info.video_formats = self._parse_video_formats(info.get('formats', []))
        video_info.audio_formats = self._parse_audio_formats(info.get('formats', []))
        
        return video_info
    
    def _parse_playlist_info(self, info: dict) -> PlaylistInfo:
        """Parse yt-dlp info dict into PlaylistInfo"""
        entries = info.get('entries', [])
        
        playlist_info = PlaylistInfo(
            id=info.get('id', ''),
            title=info.get('title', 'Unknown Playlist'),
            description=info.get('description', ''),
            uploader=info.get('uploader', ''),
            video_count=len(entries),
            entries=entries,
            raw_info=info,
        )
        
        return playlist_info
    
    def _parse_video_formats(self, formats: list) -> list:
        """Parse video formats from yt-dlp format list"""
        video_formats = []
        
        for fmt in formats:
            # Skip audio-only
            if fmt.get('vcodec') == 'none':
                continue
            
            height = fmt.get('height')
            if not height:
                continue
            
            fps = fmt.get('fps')
            ext = fmt.get('ext', 'mp4')
            format_note = fmt.get('format_note', '')
            filesize = fmt.get('filesize')
            format_id = fmt.get('format_id', '')
            
            # Build display string
            quality_str = f"{height}p"
            if fps:
                quality_str += f" {fps}fps"
            if format_note:
                quality_str += f" ({format_note})"
            if filesize:
                size_mb = filesize / (1024 * 1024)
                quality_str += f" - {size_mb:.1f}MB"
            quality_str += f" [{ext}]"
            
            video_formats.append((quality_str, format_id))
        
        # Sort by quality (height) descending
        def get_height(fmt_tuple):
            try:
                match = re.search(r'(\d+)p', fmt_tuple[0])
                return int(match.group(1)) if match else 0
            except:
                return 0
        
        video_formats.sort(key=get_height, reverse=True)
        return video_formats
    
    def _parse_audio_formats(self, formats: list) -> list:
        """Parse audio formats from yt-dlp format list"""
        audio_formats = []
        
        for fmt in formats:
            # Skip video formats
            if fmt.get('vcodec') != 'none':
                continue
            
            acodec = fmt.get('acodec', '')
            if acodec == 'none':
                continue
            
            abr = fmt.get('abr')
            ext = fmt.get('ext', 'webm')
            format_id = fmt.get('format_id', '')
            filesize = fmt.get('filesize')
            
            # Build display string
            if abr:
                quality_str = f"{int(abr)}kbps"
            else:
                quality_str = "Audio"
            
            quality_str += f" [{ext}]"
            
            if filesize:
                size_mb = filesize / (1024 * 1024)
                quality_str += f" - {size_mb:.1f}MB"
            
            audio_formats.append((quality_str, format_id))
        
        # Sort by bitrate descending
        def get_bitrate(fmt_tuple):
            try:
                match = re.search(r'(\d+)kbps', fmt_tuple[0])
                return int(match.group(1)) if match else 0
            except:
                return 0
        
        audio_formats.sort(key=get_bitrate, reverse=True)
        return audio_formats
