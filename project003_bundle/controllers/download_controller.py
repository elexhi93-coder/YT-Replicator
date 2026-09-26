"""
Download Controller for IDM-YT
Handles all download operations, separated from UI logic.
"""

import os
import re
import time
import threading
from pathlib import Path
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum, auto

import yt_dlp

from core import (
    DownloadType, DownloadStatus, URLParser, URLType,
    FormatParser, ProgressTracker, ProgressInfo,
    IDMError, RateLimitError, classify_yt_dlp_error,
    get_logger,
)


logger = get_logger("download_controller")


class DownloadState(Enum):
    """Current state of the download controller"""
    IDLE = auto()
    FETCHING = auto()
    DOWNLOADING = auto()
    PAUSED = auto()
    CANCELLED = auto()
    COMPLETED = auto()
    ERROR = auto()


@dataclass
class DownloadConfig:
    """Configuration for a download operation"""
    url: str
    output_path: str
    download_type: DownloadType = DownloadType.VIDEO
    format_id: Optional[str] = None
    output_format: str = "mp4"
    
    # Parallel download settings
    concurrent_fragments: int = 4
    use_aria2c: bool = False
    aria2c_connections: int = 16
    
    # Audio settings
    audio_codec: str = "mp3"
    audio_quality: str = "320"
    
    # Subtitle settings
    subtitle_langs: list = field(default_factory=lambda: ["en"])
    auto_subtitles: bool = False
    subtitle_format: str = "srt"
    
    # Thumbnail settings
    convert_thumbnail_jpg: bool = True
    
    # Retry settings
    max_retries: int = 5
    base_sleep: float = 2.0
    max_sleep: float = 20.0


@dataclass
class DownloadProgress:
    """Progress information for a download"""
    status: str = ""
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed: Optional[str] = None
    eta: Optional[str] = None
    filename: Optional[str] = None


class DownloadController:
    """
    Controller for managing video downloads.
    Separates download logic from GUI.
    
    Usage:
        controller = DownloadController()
        
        # Set callbacks for progress updates
        controller.on_progress = lambda p: print(f"{p.percent}%")
        controller.on_complete = lambda: print("Done!")
        controller.on_error = lambda e: print(f"Error: {e}")
        controller.on_log = lambda msg: print(msg)
        
        # Start download
        controller.start_download(config)
        
        # Cancel if needed
        controller.cancel()
    """
    
    def __init__(
        self,
        ffmpeg_available: bool = False,
        on_progress: Optional[Callable[["DownloadProgress"], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_state_change: Optional[Callable[[DownloadState], None]] = None,
    ):
        self.ffmpeg_available = ffmpeg_available
        self.state = DownloadState.IDLE
        
        # Current operation
        self._download_thread: Optional[threading.Thread] = None
        self._cancelled = False
        self._current_config: Optional[DownloadConfig] = None
        
        # Callbacks (can be supplied at construction or set later)
        self.on_progress: Optional[Callable[[DownloadProgress], None]] = on_progress
        self.on_complete: Optional[Callable[[], None]] = on_complete
        self.on_error: Optional[Callable[[str], None]] = on_error
        self.on_log: Optional[Callable[[str], None]] = on_log
        self.on_state_change: Optional[Callable[[DownloadState], None]] = on_state_change
    
    def _set_state(self, state: DownloadState):
        """Update state and notify listeners"""
        self.state = state
        if self.on_state_change:
            self.on_state_change(state)
    
    def _log(self, message: str):
        """Log a message"""
        logger.info(message)
        if self.on_log:
            self.on_log(message)
    
    def _report_progress(self, progress: DownloadProgress):
        """Report progress to listeners"""
        if self.on_progress:
            self.on_progress(progress)
    
    def _report_error(self, error: str):
        """Report error to listeners"""
        logger.error(error)
        if self.on_error:
            self.on_error(error)
    
    # ===== Public API =====
    
    def start_download(self, config: DownloadConfig) -> bool:
        """
        Start a download with the given configuration.
        Returns True if download started, False if already busy.
        """
        if self.state == DownloadState.DOWNLOADING:
            self._log("⚠️ Download already in progress")
            return False
        
        self._current_config = config
        self._cancelled = False
        self._set_state(DownloadState.DOWNLOADING)
        
        self._download_thread = threading.Thread(
            target=self._download_worker,
            args=(config,),
            daemon=True,
        )
        self._download_thread.start()
        return True
    
    def cancel(self):
        """Cancel the current download"""
        if self.state == DownloadState.DOWNLOADING:
            self._cancelled = True
            self._log("🛑 Cancelling download...")
            self._set_state(DownloadState.CANCELLED)
    
    def is_busy(self) -> bool:
        """Check if controller is currently downloading"""
        return self.state == DownloadState.DOWNLOADING
    
    # ===== Download Worker =====
    
    def _download_worker(self, config: DownloadConfig):
        """Worker thread for download operation"""
        try:
            ydl_opts = self._build_ydl_opts(config)
            
            # Execute download with retry logic
            self._download_with_backoff(ydl_opts, config)
            
            if not self._cancelled:
                self._set_state(DownloadState.COMPLETED)
                self._log("✅ Download completed!")
                if self.on_complete:
                    self.on_complete()
        
        except Exception as e:
            if self._cancelled:
                return
            
            self._set_state(DownloadState.ERROR)
            error_msg = str(e)
            self._report_error(f"❌ Download failed: {error_msg}")
    
    def _build_ydl_opts(self, config: DownloadConfig) -> dict:
        """Build yt-dlp options from config"""
        ydl_opts = {
            'outtmpl': os.path.join(config.output_path, '%(title)s.%(ext)s'),
            'progress_hooks': [self._progress_hook],
        }
        
        # Parallel download settings
        if config.concurrent_fragments > 1:
            ydl_opts['concurrent_fragment_downloads'] = config.concurrent_fragments
            self._log(f"⚡ Using {config.concurrent_fragments} parallel connections")
        
        # aria2c external downloader
        if config.use_aria2c:
            ydl_opts['external_downloader'] = 'aria2c'
            ydl_opts['external_downloader_args'] = {
                'aria2c': [
                    f'-x{config.aria2c_connections}',
                    f'-s{config.aria2c_connections}',
                    '-k1M',
                    '--file-allocation=none',
                ]
            }
            self._log(f"⚡ Using aria2c with {config.aria2c_connections} connections")
        
        # Type-specific options
        if config.download_type == DownloadType.THUMBNAIL:
            ydl_opts.update({
                'skip_download': True,
                'writethumbnail': True,
            })
            if config.convert_thumbnail_jpg:
                ydl_opts['convert_thumbnails'] = 'jpg'
            self._log("🖼️ Downloading thumbnail only")
        
        elif config.download_type == DownloadType.AUDIO:
            self._configure_audio_opts(ydl_opts, config)
        
        elif config.download_type == DownloadType.VIDEO:
            self._configure_video_opts(ydl_opts, config)
        
        elif config.download_type == DownloadType.SUBTITLES:
            self._configure_subtitle_opts(ydl_opts, config)
        
        return ydl_opts
    
    def _configure_video_opts(self, ydl_opts: dict, config: DownloadConfig):
        """Configure options for video download"""
        format_id = config.format_id or "bestvideo"
        
        # Merge video with best audio (DASH streams are video-only)
        ydl_opts['format'] = f"{format_id}+bestaudio/best"
        ydl_opts['merge_output_format'] = config.output_format
        
        if self.ffmpeg_available:
            self._log(f"🔊 Merging video with audio → {config.output_format.upper()}")
        else:
            self._log("⚠️ FFmpeg not found - audio may be missing!")
    
    def _configure_audio_opts(self, ydl_opts: dict, config: DownloadConfig):
        """Configure options for audio download"""
        if config.audio_codec == "mp3" and self.ffmpeg_available:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': config.audio_quality,
                }],
            })
            self._log(f"🎵 Converting to MP3 ({config.audio_quality} kbps)")
        else:
            ydl_opts['format'] = config.format_id or 'bestaudio/best'
            if config.audio_codec == "mp3" and not self.ffmpeg_available:
                self._log("⚠️ FFmpeg not available - downloading in original format")
    
    def _configure_subtitle_opts(self, ydl_opts: dict, config: DownloadConfig):
        """Configure options for subtitle download"""
        ydl_opts.update({
            'skip_download': True,
            'writesubtitles': True,
            'subtitleslangs': config.subtitle_langs,
        })
        
        if config.auto_subtitles:
            ydl_opts['writeautomaticsub'] = True
        
        if config.subtitle_format and config.subtitle_format != 'best':
            ydl_opts['subtitlesformat'] = config.subtitle_format
        
        self._log(f"💬 Downloading subtitles: {', '.join(config.subtitle_langs)}")
    
    def _progress_hook(self, d: dict):
        """yt-dlp progress callback"""
        if self._cancelled:
            raise Exception("Download cancelled")
        
        status = d.get('status', '')
        progress = DownloadProgress(status=status)
        
        if status == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            
            if total > 0:
                progress.percent = (downloaded / total) * 100
            
            progress.downloaded_bytes = downloaded
            progress.total_bytes = total
            progress.speed = d.get('_speed_str', '')
            progress.eta = d.get('_eta_str', '')
            progress.filename = d.get('filename', '')
        
        elif status == 'finished':
            progress.percent = 100
            progress.filename = d.get('filename', '')
        
        self._report_progress(progress)
    
    def _download_with_backoff(self, ydl_opts: dict, config: DownloadConfig):
        """Execute download with exponential backoff for rate limiting"""
        max_attempts = config.max_retries
        base_sleep = config.base_sleep
        max_sleep = config.max_sleep
        
        for attempt in range(1, max_attempts + 1):
            if self._cancelled:
                return
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([config.url])
                return  # Success
            
            except yt_dlp.utils.DownloadError as e:
                error_str = str(e).lower()
                
                # Check for rate limiting
                if '429' in error_str or 'too many requests' in error_str:
                    if attempt < max_attempts:
                        delay = min(base_sleep * (2 ** (attempt - 1)), max_sleep)
                        self._log(f"⏳ Rate limited. Retrying in {delay:.1f}s... (attempt {attempt}/{max_attempts})")
                        time.sleep(delay)
                        continue
                
                # Non-retryable error
                raise
    
    # ===== Utility Methods =====
    
    def check_aria2c(self) -> bool:
        """Check if aria2c is available"""
        import shutil
        return shutil.which('aria2c') is not None
