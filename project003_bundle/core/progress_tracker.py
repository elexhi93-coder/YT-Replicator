"""
Progress Tracker Component
Tracks download progress and notifies via callbacks.
"""

import time
import threading
from typing import Callable, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class ProgressState(Enum):
    """Current state of the progress tracker"""
    IDLE = "idle"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"  # Post-processing (e.g., converting to MP3)
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class ProgressInfo:
    """Information about current download progress"""
    state: ProgressState = ProgressState.IDLE
    
    # Progress values (0.0 to 1.0)
    progress: float = 0.0
    
    # Speed and ETA
    speed: Optional[str] = None  # e.g., "1.5 MB/s"
    speed_bytes: Optional[float] = None  # bytes per second
    eta: Optional[str] = None  # e.g., "2:30"
    eta_seconds: Optional[int] = None
    
    # Size info
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    
    # File info
    filename: str = ""
    
    # Status message
    message: str = ""
    
    # Error info
    error: Optional[str] = None
    
    # Timing
    start_time: Optional[float] = None
    elapsed_seconds: float = 0.0
    
    @property
    def progress_percent(self) -> float:
        """Get progress as percentage (0-100)"""
        return self.progress * 100
    
    @property
    def downloaded_str(self) -> str:
        """Get downloaded size as human-readable string"""
        return self._format_bytes(self.downloaded_bytes)
    
    @property
    def total_str(self) -> str:
        """Get total size as human-readable string"""
        return self._format_bytes(self.total_bytes) if self.total_bytes else "Unknown"
    
    @staticmethod
    def _format_bytes(size: Optional[int]) -> str:
        """Format bytes as human-readable string"""
        if size is None:
            return "Unknown"
        
        for unit in ['B', 'KB', 'MB', 'GB']:
            if abs(size) < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"


@dataclass
class ProgressTrackerConfig:
    """Configuration for progress tracker"""
    update_interval_ms: int = 100  # Minimum time between updates
    smooth_progress: bool = True  # Smooth progress bar updates


class ProgressTracker:
    """
    Tracks download progress and provides callbacks for UI updates.
    
    Usage:
        def on_progress(info: ProgressInfo):
            progress_bar['value'] = info.progress_percent
            status_label['text'] = info.message
        
        tracker = ProgressTracker(on_progress=on_progress)
        
        # Use with yt-dlp
        ydl_opts = {
            'progress_hooks': [tracker.yt_dlp_hook],
            ...
        }
    """
    
    def __init__(
        self,
        on_progress: Optional[Callable[[ProgressInfo], None]] = None,
        on_state_change: Optional[Callable[[ProgressState], None]] = None,
        on_complete: Optional[Callable[[ProgressInfo], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        config: Optional[ProgressTrackerConfig] = None,
    ):
        """
        Initialize progress tracker.
        
        Args:
            on_progress: Callback for progress updates
            on_state_change: Callback when state changes
            on_complete: Callback when download completes
            on_error: Callback on error
            config: Optional configuration
        """
        self.on_progress = on_progress
        self.on_state_change = on_state_change
        self.on_complete = on_complete
        self.on_error = on_error
        self.config = config or ProgressTrackerConfig()
        
        self._info = ProgressInfo()
        self._last_update_time = 0.0
        self._lock = threading.Lock()
    
    @property
    def current_info(self) -> ProgressInfo:
        """Get current progress info"""
        with self._lock:
            return self._info
    
    @property
    def state(self) -> ProgressState:
        """Get current state"""
        return self._info.state
    
    def reset(self):
        """Reset tracker to initial state"""
        with self._lock:
            self._info = ProgressInfo()
            self._last_update_time = 0.0
    
    def set_state(self, state: ProgressState, message: str = ""):
        """
        Set current state.
        
        Args:
            state: New state
            message: Optional status message
        """
        old_state = self._info.state
        
        with self._lock:
            self._info.state = state
            self._info.message = message
            
            if state == ProgressState.DOWNLOADING and self._info.start_time is None:
                self._info.start_time = time.time()
        
        if old_state != state and self.on_state_change:
            self.on_state_change(state)
        
        self._notify_progress()
    
    def update(
        self,
        progress: Optional[float] = None,
        downloaded_bytes: Optional[int] = None,
        total_bytes: Optional[int] = None,
        speed: Optional[str] = None,
        speed_bytes: Optional[float] = None,
        eta: Optional[str] = None,
        eta_seconds: Optional[int] = None,
        filename: Optional[str] = None,
        message: Optional[str] = None,
    ):
        """
        Update progress information.
        
        Args:
            progress: Progress value (0.0 to 1.0)
            downloaded_bytes: Bytes downloaded
            total_bytes: Total bytes to download
            speed: Speed string
            speed_bytes: Speed in bytes/second
            eta: ETA string
            eta_seconds: ETA in seconds
            filename: Current filename
            message: Status message
        """
        with self._lock:
            if progress is not None:
                if self.config.smooth_progress:
                    # Smooth progress (never go backwards)
                    self._info.progress = max(self._info.progress, progress)
                else:
                    self._info.progress = progress
            
            if downloaded_bytes is not None:
                self._info.downloaded_bytes = downloaded_bytes
            
            if total_bytes is not None:
                self._info.total_bytes = total_bytes
            
            if speed is not None:
                self._info.speed = speed
            
            if speed_bytes is not None:
                self._info.speed_bytes = speed_bytes
            
            if eta is not None:
                self._info.eta = eta
            
            if eta_seconds is not None:
                self._info.eta_seconds = eta_seconds
            
            if filename is not None:
                self._info.filename = filename
            
            if message is not None:
                self._info.message = message
            
            # Update elapsed time
            if self._info.start_time:
                self._info.elapsed_seconds = time.time() - self._info.start_time
        
        self._notify_progress()
    
    def complete(self, message: str = "Download complete"):
        """Mark download as complete"""
        with self._lock:
            self._info.state = ProgressState.COMPLETED
            self._info.progress = 1.0
            self._info.message = message
        
        if self.on_state_change:
            self.on_state_change(ProgressState.COMPLETED)
        
        if self.on_complete:
            self.on_complete(self._info)
        
        self._notify_progress(force=True)
    
    def error(self, error_message: str):
        """Mark download as failed"""
        with self._lock:
            self._info.state = ProgressState.ERROR
            self._info.error = error_message
            self._info.message = f"Error: {error_message}"
        
        if self.on_state_change:
            self.on_state_change(ProgressState.ERROR)
        
        if self.on_error:
            self.on_error(error_message)
        
        self._notify_progress(force=True)
    
    def cancel(self):
        """Mark download as cancelled"""
        with self._lock:
            self._info.state = ProgressState.CANCELLED
            self._info.message = "Download cancelled"
        
        if self.on_state_change:
            self.on_state_change(ProgressState.CANCELLED)
        
        self._notify_progress(force=True)
    
    def _notify_progress(self, force: bool = False):
        """Notify progress callback with rate limiting"""
        now = time.time()
        
        # Rate limit updates
        if not force and (now - self._last_update_time) < (self.config.update_interval_ms / 1000.0):
            return
        
        self._last_update_time = now
        
        if self.on_progress:
            self.on_progress(self._info)
    
    def yt_dlp_hook(self, d: dict):
        """
        Progress hook for yt-dlp.
        
        Usage:
            ydl_opts = {
                'progress_hooks': [tracker.yt_dlp_hook],
            }
        """
        status = d.get('status')
        
        if status == 'downloading':
            self.set_state(ProgressState.DOWNLOADING)
            
            # Extract progress info
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            
            progress = None
            if total and total > 0:
                progress = downloaded / total
            
            # Parse speed
            speed = d.get('_speed_str', d.get('speed'))
            speed_bytes = d.get('speed')
            if isinstance(speed, (int, float)):
                speed = f"{speed / (1024*1024):.1f} MB/s"
            
            # Parse ETA
            eta = d.get('_eta_str', d.get('eta'))
            eta_seconds = d.get('eta')
            if isinstance(eta, (int, float)):
                mins, secs = divmod(int(eta), 60)
                eta = f"{mins}:{secs:02d}"
            
            # Get filename
            filename = d.get('filename', '')
            
            # Build message
            message = f"Downloading: {d.get('_percent_str', '').strip()}"
            if speed:
                message += f" at {speed}"
            if eta:
                message += f" ETA: {eta}"
            
            self.update(
                progress=progress,
                downloaded_bytes=downloaded,
                total_bytes=total,
                speed=str(speed) if speed else None,
                speed_bytes=speed_bytes if isinstance(speed_bytes, (int, float)) else None,
                eta=str(eta) if eta else None,
                eta_seconds=eta_seconds if isinstance(eta_seconds, int) else None,
                filename=filename,
                message=message,
            )
        
        elif status == 'finished':
            self.set_state(ProgressState.PROCESSING, "Processing...")
        
        elif status == 'error':
            self.error(d.get('error', 'Unknown error'))
    
    def yt_dlp_postprocessor_hook(self, d: dict):
        """
        Post-processor hook for yt-dlp.
        
        Usage:
            ydl_opts = {
                'postprocessor_hooks': [tracker.yt_dlp_postprocessor_hook],
            }
        """
        status = d.get('status')
        postprocessor = d.get('postprocessor', 'Unknown')
        
        if status == 'started':
            self.set_state(ProgressState.PROCESSING, f"Processing: {postprocessor}")
        
        elif status == 'finished':
            # Post-processing complete - but download might have more steps
            self.update(message=f"Completed: {postprocessor}")


class MultiProgressTracker:
    """
    Tracks progress for multiple concurrent downloads.
    """
    
    def __init__(
        self,
        on_item_progress: Optional[Callable[[int, ProgressInfo], None]] = None,
        on_overall_progress: Optional[Callable[[float, int, int], None]] = None,
    ):
        """
        Initialize multi-progress tracker.
        
        Args:
            on_item_progress: Callback for individual item progress (index, info)
            on_overall_progress: Callback for overall progress (progress, completed, total)
        """
        self.on_item_progress = on_item_progress
        self.on_overall_progress = on_overall_progress
        
        self._trackers: dict[int, ProgressTracker] = {}
        self._total_items = 0
        self._completed_items = 0
        self._lock = threading.Lock()
    
    def create_tracker(self, index: int, total_items: int) -> ProgressTracker:
        """
        Create a tracker for a specific download.
        
        Args:
            index: Index of this download
            total_items: Total number of downloads
            
        Returns:
            ProgressTracker for this download
        """
        with self._lock:
            self._total_items = total_items
        
        def on_progress(info: ProgressInfo):
            if self.on_item_progress:
                self.on_item_progress(index, info)
            self._update_overall()
        
        def on_complete(info: ProgressInfo):
            with self._lock:
                self._completed_items += 1
            self._update_overall()
        
        tracker = ProgressTracker(
            on_progress=on_progress,
            on_complete=on_complete,
        )
        
        with self._lock:
            self._trackers[index] = tracker
        
        return tracker
    
    def _update_overall(self):
        """Update overall progress"""
        if not self.on_overall_progress:
            return
        
        with self._lock:
            if self._total_items == 0:
                progress = 0.0
            else:
                # Average progress across all trackers
                total_progress = sum(
                    t.current_info.progress for t in self._trackers.values()
                )
                progress = total_progress / self._total_items
            
            self.on_overall_progress(
                progress,
                self._completed_items,
                self._total_items
            )
    
    def reset(self):
        """Reset all trackers"""
        with self._lock:
            self._trackers.clear()
            self._total_items = 0
            self._completed_items = 0
