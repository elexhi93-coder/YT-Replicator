"""
Download Manager for IDM-YT Video Downloader
Handles all download operations with proper error handling and retry logic
"""

import os
import time
import random
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import yt_dlp

from .enums import DownloadType, DownloadStatus
from .config import DownloadOptions, AppConfig


@dataclass
class DownloadProgress:
    """Progress information for a download"""
    status: DownloadStatus
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0  # bytes per second
    eta: int = 0  # seconds remaining
    filename: str = ""
    
    @property
    def speed_str(self) -> str:
        """Get formatted speed string"""
        if self.speed <= 0:
            return "0 B/s"
        if self.speed >= 1_048_576:
            return f"{self.speed / 1_048_576:.1f} MB/s"
        elif self.speed >= 1024:
            return f"{self.speed / 1024:.1f} KB/s"
        return f"{self.speed:.0f} B/s"
    
    @property
    def eta_str(self) -> str:
        """Get formatted ETA string"""
        if self.eta <= 0:
            return "--:--"
        hours, remainder = divmod(int(self.eta), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    
    @property
    def size_str(self) -> str:
        """Get formatted size progress string"""
        def fmt(b):
            if b >= 1_073_741_824:
                return f"{b/1_073_741_824:.1f}GB"
            elif b >= 1_048_576:
                return f"{b/1_048_576:.1f}MB"
            elif b >= 1024:
                return f"{b/1024:.1f}KB"
            return f"{b}B"
        
        if self.total_bytes:
            return f"{fmt(self.downloaded_bytes)}/{fmt(self.total_bytes)}"
        return fmt(self.downloaded_bytes)


@dataclass
class DownloadResult:
    """Result of a download operation"""
    success: bool
    url: str
    output_path: Optional[Path] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


class DownloadManager:
    """
    Manages video/audio downloads with retry logic and progress tracking.
    
    This class encapsulates all download functionality and can be used
    independently of the GUI.
    """
    
    def __init__(self, config: Optional[AppConfig] = None):
        """
        Initialize the download manager.
        
        Args:
            config: Application configuration (uses defaults if not provided)
        """
        self.config = config or AppConfig()
        self._cancel_flag = False
        self._pause_flag = False
        self._current_download: Optional[threading.Thread] = None
        self._progress_callback: Optional[Callable[[DownloadProgress], None]] = None
        self._log_callback: Optional[Callable[[str], None]] = None
    
    def set_progress_callback(self, callback: Callable[[DownloadProgress], None]):
        """Set callback for progress updates"""
        self._progress_callback = callback
    
    def set_log_callback(self, callback: Callable[[str], None]):
        """Set callback for log messages"""
        self._log_callback = callback
    
    def _log(self, message: str):
        """Log a message"""
        if self._log_callback:
            self._log_callback(message)
    
    def _update_progress(self, progress: DownloadProgress):
        """Update download progress"""
        if self._progress_callback:
            self._progress_callback(progress)
    
    def cancel(self):
        """Cancel the current download"""
        self._cancel_flag = True
        self._log("Download cancelled by user")
    
    def pause(self):
        """Pause the current download"""
        self._pause_flag = True
        self._log("Download paused")
    
    def resume(self):
        """Resume the paused download"""
        self._pause_flag = False
        self._log("Download resumed")
    
    def download(
        self,
        url: str,
        options: DownloadOptions,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    ) -> DownloadResult:
        """
        Download a video/audio file.
        
        Args:
            url: Video URL to download
            options: Download options
            progress_callback: Optional callback for progress updates
            
        Returns:
            DownloadResult with success status and details
        """
        start_time = time.time()
        self._cancel_flag = False
        self._pause_flag = False
        
        if progress_callback:
            self._progress_callback = progress_callback
        
        # Create progress hook for yt-dlp
        def ydl_progress_hook(d: Dict[str, Any]):
            if self._cancel_flag:
                raise Exception("Download cancelled")
            
            while self._pause_flag:
                time.sleep(0.5)
            
            if d['status'] == 'downloading':
                progress = DownloadProgress(
                    status=DownloadStatus.DOWNLOADING,
                    downloaded_bytes=d.get('downloaded_bytes', 0),
                    total_bytes=d.get('total_bytes') or d.get('total_bytes_estimate', 0),
                    speed=d.get('speed', 0) or 0,
                    eta=d.get('eta', 0) or 0,
                    filename=d.get('filename', ''),
                )
                
                if progress.total_bytes:
                    progress.percent = (progress.downloaded_bytes / progress.total_bytes) * 100
                
                self._update_progress(progress)
                
            elif d['status'] == 'finished':
                progress = DownloadProgress(
                    status=DownloadStatus.PROCESSING,
                    percent=100.0,
                    filename=d.get('filename', ''),
                )
                self._update_progress(progress)
        
        try:
            # Build yt-dlp options
            ydl_opts = options.to_ydl_opts(progress_hook=ydl_progress_hook)
            
            # Perform download with retry logic
            self._download_with_backoff(
                ydl_opts=ydl_opts,
                url=url,
                is_subtitles=(options.download_type == "subtitles"),
            )
            
            duration = time.time() - start_time
            
            # Report success
            self._update_progress(DownloadProgress(
                status=DownloadStatus.COMPLETED,
                percent=100.0,
            ))
            
            return DownloadResult(
                success=True,
                url=url,
                output_path=options.output_path,
                duration_seconds=duration,
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = str(e)
            
            self._log(f"Download failed: {error_msg}")
            self._update_progress(DownloadProgress(
                status=DownloadStatus.FAILED,
            ))
            
            return DownloadResult(
                success=False,
                url=url,
                error_message=error_msg,
                duration_seconds=duration,
            )
    
    def _download_with_backoff(
        self,
        ydl_opts: Dict[str, Any],
        url: str,
        is_subtitles: bool = False,
    ):
        """
        Download with exponential backoff for rate limiting.
        
        Args:
            ydl_opts: yt-dlp options dictionary
            url: URL to download
            is_subtitles: Whether downloading subtitles (more prone to rate limits)
        """
        max_attempts = self.config.max_retries if is_subtitles else 2
        base_sleep = self.config.base_backoff_sleep
        max_sleep = self.config.max_backoff_sleep
        
        for attempt in range(max_attempts):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                return
                
            except Exception as e:
                error_msg = str(e)
                is_rate_limited = 'HTTP Error 429' in error_msg or 'Too Many Requests' in error_msg
                
                if is_rate_limited and attempt < max_attempts - 1:
                    # Calculate delay with jitter
                    delay = min(max_sleep, base_sleep * (2 ** attempt) * random.uniform(1.0, 1.6))
                    self._log(f"⏳ Rate limited (429). Retrying in {delay:.1f}s... (attempt {attempt + 1}/{max_attempts})")
                    time.sleep(delay)
                    continue
                
                raise
    
    def download_batch(
        self,
        items: List[Dict[str, Any]],
        base_options: DownloadOptions,
        progress_callback: Optional[Callable[[int, int, DownloadProgress], None]] = None,
    ) -> List[DownloadResult]:
        """
        Download multiple items.
        
        Args:
            items: List of items with 'url' and optional 'title' keys
            base_options: Base download options to use
            progress_callback: Optional callback (current_index, total, progress)
            
        Returns:
            List of DownloadResult for each item
        """
        results = []
        total = len(items)
        
        for idx, item in enumerate(items, 1):
            if self._cancel_flag:
                results.append(DownloadResult(
                    success=False,
                    url=item.get('url', ''),
                    error_message="Cancelled by user",
                ))
                continue
            
            url = item.get('url') or item.get('webpage_url', '')
            if not url and item.get('id'):
                url = f"https://www.youtube.com/watch?v={item['id']}"
            
            title = item.get('title', 'Unknown')
            self._log(f"[{idx}/{total}] Downloading: {title}")
            
            # Create options copy for this item
            item_options = DownloadOptions(
                url=url,
                download_type=base_options.download_type,
                video_format_id=base_options.video_format_id,
                audio_format=base_options.audio_format,
                mp3_bitrate=base_options.mp3_bitrate,
                output_path=base_options.output_path,
                filename_template=base_options.filename_template,
            )
            
            def batch_progress(p: DownloadProgress):
                if progress_callback:
                    progress_callback(idx, total, p)
            
            result = self.download(url, item_options, batch_progress)
            results.append(result)
            
            if result.success:
                self._log(f"✅ [{idx}/{total}] Completed: {title}")
            else:
                self._log(f"❌ [{idx}/{total}] Failed: {title} - {result.error_message}")
        
        return results
    
    @staticmethod
    def check_ffmpeg() -> bool:
        """
        Check if FFmpeg is available.
        
        Returns:
            True if FFmpeg is available, False otherwise
        """
        import shutil
        import subprocess
        
        # Check portable FFmpeg first
        app_dir = Path(__file__).parent.parent
        portable_ffmpeg = app_dir / "ffmpeg" / "bin" / "ffmpeg.exe"
        
        if portable_ffmpeg.exists():
            # Add to PATH
            ffmpeg_bin_dir = str(portable_ffmpeg.parent)
            if ffmpeg_bin_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = ffmpeg_bin_dir + os.pathsep + os.environ.get('PATH', '')
            return True
        
        # Check system PATH
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except:
            return shutil.which('ffmpeg') is not None
