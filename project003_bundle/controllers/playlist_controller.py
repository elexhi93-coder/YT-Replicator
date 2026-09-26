"""
Playlist Controller for IDM-YT
Handles playlist-specific operations including batch downloads.
"""

import threading
import time
from typing import Optional, Callable, List
from dataclasses import dataclass, field

import yt_dlp

from core import (
    DownloadType, DownloadStatus,
    get_logger,
)

from .download_controller import DownloadController, DownloadConfig, DownloadProgress


logger = get_logger("playlist_controller")


@dataclass
class PlaylistItem:
    """Represents a single item in a playlist"""
    index: int
    id: str
    title: str
    duration: int = 0
    duration_str: str = ""
    url: str = ""
    thumbnail_url: str = ""
    uploader: str = ""
    
    # Download state
    selected: bool = True
    status: DownloadStatus = DownloadStatus.PENDING
    progress: float = 0.0
    error_message: str = ""


@dataclass
class PlaylistDownloadProgress:
    """Progress for entire playlist download"""
    current_index: int = 0
    total_count: int = 0
    current_title: str = ""
    current_progress: float = 0.0
    completed_count: int = 0
    failed_count: int = 0
    overall_progress: float = 0.0


class PlaylistController:
    """
    Controller for managing playlist operations.
    
    Usage:
        controller = PlaylistController()
        
        # Set callbacks
        controller.on_progress = lambda p: update_progress(p)
        controller.on_item_complete = lambda item: mark_done(item)
        controller.on_complete = lambda: show_done()
        
        # Start batch download
        items = [PlaylistItem(...), ...]
        controller.start_download(items, config)
    """
    
    def __init__(
        self,
        ffmpeg_available: bool = False,
        on_item_progress: Optional[Callable[[int, "DownloadProgress"], None]] = None,
        on_item_complete: Optional[Callable[[int, str], None]] = None,
        on_all_complete: Optional[Callable[[int], None]] = None,
        on_error: Optional[Callable[[int, str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        self.ffmpeg_available = ffmpeg_available
        self._download_thread: Optional[threading.Thread] = None
        self._cancelled = False

        # Download controller for individual items
        self._download_controller = DownloadController(ffmpeg_available)

        # Callbacks (support both controller-style and main_window-style names)
        self.on_progress: Optional[Callable[[PlaylistDownloadProgress], None]] = None
        self.on_item_start: Optional[Callable[[PlaylistItem], None]] = None
        self.on_item_complete: Optional[Callable[[PlaylistItem], None]] = None
        self.on_item_error: Optional[Callable[[PlaylistItem, str], None]] = None
        self.on_complete: Optional[Callable[[], None]] = None
        self.on_log: Optional[Callable[[str], None]] = on_log

        # Compatibility callbacks expected by MainWindow
        self.on_item_progress: Optional[Callable[[int, "DownloadProgress"], None]] = on_item_progress
        self.on_item_complete_indexed: Optional[Callable[[int, str], None]] = on_item_complete
        self.on_all_complete: Optional[Callable[[int], None]] = on_all_complete
        self.on_error_indexed: Optional[Callable[[int, str], None]] = on_error
    
    def _log(self, message: str):
        """Log a message"""
        logger.info(message)
        if self.on_log:
            self.on_log(message)
    
    # ===== Public API =====
    
    def start_download(
        self,
        items: List[PlaylistItem],
        output_path: str,
        download_type: DownloadType = DownloadType.VIDEO,
        format_id: Optional[str] = None,
        output_format: str = "mp4",
        concurrent_fragments: int = 4,
        use_aria2c: bool = False,
        aria2c_connections: int = 16,
    ) -> bool:
        """
        Start downloading selected playlist items.
        Returns True if started, False if already busy.
        """
        if self._download_thread and self._download_thread.is_alive():
            self._log("⚠️ Download already in progress")
            return False
        
        # Filter to selected items only
        selected_items = [item for item in items if item.selected]
        
        if not selected_items:
            self._log("⚠️ No items selected")
            return False
        
        self._cancelled = False
        
        # Build config template
        config_template = DownloadConfig(
            url="",  # Will be set per-item
            output_path=output_path,
            download_type=download_type,
            format_id=format_id,
            output_format=output_format,
            concurrent_fragments=concurrent_fragments,
            use_aria2c=use_aria2c,
            aria2c_connections=aria2c_connections,
        )
        
        self._download_thread = threading.Thread(
            target=self._download_worker,
            args=(selected_items, config_template),
            daemon=True,
        )
        self._download_thread.start()
        
        self._log(f"📑 Starting playlist download: {len(selected_items)} videos")
        return True
    
    def cancel(self):
        """Cancel current playlist download"""
        self._cancelled = True
        self._download_controller.cancel()
        self._log("🛑 Cancelling playlist download...")
    
    def is_busy(self) -> bool:
        """Check if controller is currently downloading"""
        return self._download_thread is not None and self._download_thread.is_alive()
    
    # ===== Download Worker =====
    
    def _download_worker(self, items: List[PlaylistItem], config_template: DownloadConfig):
        """Worker thread for playlist download"""
        total_count = len(items)
        completed_count = 0
        failed_count = 0
        
        for idx, item in enumerate(items, 1):
            if self._cancelled:
                break
            
            # Update item status
            item.status = DownloadStatus.DOWNLOADING
            
            # Notify item start
            if self.on_item_start:
                self.on_item_start(item)
            
            self._log(f"[{idx}/{total_count}] Downloading: {item.title}")
            
            # Build config for this item
            item_config = DownloadConfig(
                url=item.url or f"https://www.youtube.com/watch?v={item.id}",
                output_path=config_template.output_path,
                download_type=config_template.download_type,
                format_id=config_template.format_id,
                output_format=config_template.output_format,
                concurrent_fragments=config_template.concurrent_fragments,
                use_aria2c=config_template.use_aria2c,
                aria2c_connections=config_template.aria2c_connections,
            )
            
            # Download with progress tracking
            success = self._download_item(item, item_config, idx, total_count)
            
            if success:
                completed_count += 1
                item.status = DownloadStatus.COMPLETED
                item.progress = 100.0
                
                if self.on_item_complete:
                    self.on_item_complete(item)
                
                self._log(f"✅ [{idx}/{total_count}] Completed: {item.title}")
            else:
                failed_count += 1
                item.status = DownloadStatus.FAILED
                
                if self.on_item_error:
                    self.on_item_error(item, item.error_message)
                
                self._log(f"❌ [{idx}/{total_count}] Failed: {item.title}")
            
            # Report overall progress
            self._report_overall_progress(idx, total_count, item.title, completed_count, failed_count)
        
        # Completed
        if not self._cancelled:
            self._log(f"📑 Playlist download complete: {completed_count} succeeded, {failed_count} failed")
            if self.on_complete:
                self.on_complete()
    
    def _download_item(
        self, 
        item: PlaylistItem, 
        config: DownloadConfig,
        current_idx: int,
        total_count: int,
    ) -> bool:
        """Download a single playlist item"""
        success = False
        error_event = threading.Event()
        
        def on_progress(progress: DownloadProgress):
            item.progress = progress.percent
            self._report_overall_progress(
                current_idx, total_count, item.title, 0, 0, progress.percent
            )
        
        def on_complete():
            nonlocal success
            success = True
        
        def on_error(error: str):
            item.error_message = error
            error_event.set()
        
        # Setup callbacks
        self._download_controller.on_progress = on_progress
        self._download_controller.on_complete = on_complete
        self._download_controller.on_error = on_error
        
        # Start download
        self._download_controller.start_download(config)
        
        # Wait for completion
        while self._download_controller.is_busy():
            if self._cancelled:
                self._download_controller.cancel()
                break
            time.sleep(0.1)
        
        return success
    
    def _report_overall_progress(
        self,
        current_idx: int,
        total_count: int,
        current_title: str,
        completed_count: int,
        failed_count: int,
        current_progress: float = 0.0,
    ):
        """Report overall playlist progress"""
        if not self.on_progress:
            return
        
        # Calculate overall progress
        completed_progress = (current_idx - 1) / total_count * 100
        current_item_contribution = (current_progress / 100) * (1 / total_count) * 100
        overall_progress = completed_progress + current_item_contribution
        
        progress = PlaylistDownloadProgress(
            current_index=current_idx,
            total_count=total_count,
            current_title=current_title,
            current_progress=current_progress,
            completed_count=completed_count,
            failed_count=failed_count,
            overall_progress=overall_progress,
        )
        
        self.on_progress(progress)
