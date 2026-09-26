"""
Main Application Controller for IDM-YT
Coordinates all application logic, separated from UI.
"""

import threading
from typing import Optional, Callable, Any, Dict, List
from dataclasses import dataclass
from pathlib import Path
import logging

from core import (
    DownloadType, DownloadStatus, URLParser, URLType, ParsedURL,
    FormatParser, VideoFormat, AudioFormat,
    VideoInfoFetcher, VideoInfo, FetchResult, FetchStatus,
    DownloadManager, DownloadProgress, DownloadResult,
    ClipboardMonitor, ClipboardMonitorConfig,
    IDMError, classify_yt_dlp_error,
    get_logger,
)
from core.events import EventBus, EventType, Event, LogMessageData
from core.state_machine import DownloadStateMachine, DownloadState, MultiDownloadStateMachine
from core.container import Container, get_container

logger = get_logger("main_controller")


@dataclass
class AppState:
    """Current application state"""
    current_url: str = ""
    video_info: Optional[Dict] = None
    is_playlist: bool = False
    playlist_entries: List[Dict] = None
    download_path: str = ""
    download_type: DownloadType = DownloadType.VIDEO
    selected_format: Optional[str] = None
    
    def __post_init__(self):
        if self.playlist_entries is None:
            self.playlist_entries = []
        if not self.download_path:
            self.download_path = str(Path.home() / "Downloads")


class MainController:
    """
    Main application controller.
    
    Responsibilities:
    - Coordinate between UI and business logic
    - Manage application state
    - Handle user actions
    - Emit events for UI updates
    
    Usage:
        controller = MainController()
        
        # Set up event listeners in UI
        EventBus.subscribe(EventType.VIDEO_FETCH_COMPLETED, update_ui)
        EventBus.subscribe(EventType.DOWNLOAD_PROGRESS, update_progress_bar)
        
        # Call controller methods from UI
        controller.fetch_video(url)
        controller.start_download(format_id, output_path)
    """
    
    def __init__(self, container: Optional[Container] = None):
        """
        Initialize the controller.
        
        Args:
            container: DI container (uses global if not provided)
        """
        self.container = container or get_container()
        self.state = AppState()
        self.state_machine = DownloadStateMachine()
        self.multi_state_machine = MultiDownloadStateMachine()
        
        # Get services from container
        self._url_parser = URLParser()
        self._format_parser = FormatParser()
        self._fetcher: Optional[VideoInfoFetcher] = None
        self._download_manager: Optional[DownloadManager] = None
        
        # Threading
        self._fetch_thread: Optional[threading.Thread] = None
        self._download_thread: Optional[threading.Thread] = None
        self._cancel_flag = threading.Event()
        
        # Set up state machine callbacks
        self.state_machine.on_state_change(self._on_state_change)
        
        logger.info("MainController initialized")
    
    def _get_fetcher(self) -> VideoInfoFetcher:
        """Lazy load video fetcher"""
        if self._fetcher is None:
            try:
                self._fetcher = self.container.resolve(VideoInfoFetcher)
            except:
                self._fetcher = VideoInfoFetcher()
        return self._fetcher
    
    def _get_download_manager(self) -> DownloadManager:
        """Lazy load download manager"""
        if self._download_manager is None:
            try:
                self._download_manager = self.container.resolve(DownloadManager)
            except:
                self._download_manager = DownloadManager()
        return self._download_manager
    
    def _on_state_change(self, old_state: DownloadState, new_state: DownloadState, context) -> None:
        """Handle state machine transitions"""
        logger.debug(f"State changed: {old_state.name} -> {new_state.name}")
        
        # Emit UI status update
        status_messages = {
            DownloadState.IDLE: "Ready",
            DownloadState.FETCHING: "Fetching video info...",
            DownloadState.READY: "Ready to download",
            DownloadState.DOWNLOADING: "Downloading...",
            DownloadState.PAUSED: "Download paused",
            DownloadState.PROCESSING: "Processing...",
            DownloadState.COMPLETED: "Download completed!",
            DownloadState.FAILED: f"Failed: {context.error_message or 'Unknown error'}",
            DownloadState.CANCELLED: "Cancelled",
        }
        
        EventBus.emit(
            EventType.UI_STATUS_UPDATE,
            data={"status": status_messages.get(new_state, str(new_state))},
            source="MainController"
        )
    
    def log(self, message: str, level: str = "info") -> None:
        """Emit a log message event"""
        EventBus.emit(
            EventType.UI_LOG_MESSAGE,
            data=LogMessageData(message=message, level=level),
            source="MainController"
        )
    
    # URL Handling
    def parse_url(self, url: str) -> Optional[ParsedURL]:
        """Parse and validate a URL"""
        try:
            return self._url_parser.parse(url)
        except Exception as e:
            logger.warning(f"URL parse error: {e}")
            return None
    
    def is_valid_url(self, url: str) -> bool:
        """Check if URL is valid for downloading"""
        parsed = self.parse_url(url)
        return parsed is not None and parsed.url_type != URLType.UNKNOWN
    
    # Video Fetching
    def fetch_video(self, url: str) -> None:
        """
        Fetch video information asynchronously.
        
        Emits:
            VIDEO_FETCH_STARTED
            VIDEO_FETCH_COMPLETED or VIDEO_FETCH_FAILED
        """
        if not url:
            self.log("Please enter a URL", "warning")
            return
        
        if not self.state_machine.can_fetch():
            self.log("Cannot fetch: another operation is in progress", "warning")
            return
        
        self.state.current_url = url
        self.state_machine.fetch(url=url)
        
        def do_fetch():
            try:
                self.log(f"Fetching video info from: {url}")
                
                fetcher = self._get_fetcher()
                result = fetcher.fetch(url)
                
                if result.status == FetchStatus.SUCCESS:
                    self.state.video_info = result.video_info
                    self.state.is_playlist = result.video_info.get('_type') == 'playlist'
                    
                    if self.state.is_playlist:
                        self.state.playlist_entries = result.video_info.get('entries', [])
                        self.log(f"📑 Playlist detected: {len(self.state.playlist_entries)} videos")
                        EventBus.emit(EventType.PLAYLIST_DETECTED, data=result.video_info)
                    
                    self.state_machine.fetched(title=result.video_info.get('title', 'Unknown'))
                    
                    EventBus.emit(
                        EventType.VIDEO_FETCH_COMPLETED,
                        data=result.video_info,
                        source="MainController"
                    )
                    
                    self.log(f"✅ Fetched: {result.video_info.get('title', 'Unknown')}")
                else:
                    raise Exception(result.error_message or "Failed to fetch video info")
                    
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Fetch error: {error_msg}")
                self.state_machine.fail(error_message=error_msg)
                
                EventBus.emit(
                    EventType.VIDEO_FETCH_FAILED,
                    data={"url": url, "error": error_msg},
                    source="MainController"
                )
                
                self.log(f"❌ Error: {error_msg}", "error")
        
        self._fetch_thread = threading.Thread(target=do_fetch, daemon=True)
        self._fetch_thread.start()
    
    def get_available_formats(self) -> Dict[str, List]:
        """Get available video and audio formats from fetched info"""
        if not self.state.video_info:
            return {"video": [], "audio": []}
        
        formats = self.state.video_info.get('formats', [])
        
        # Parse formats
        video_formats = self._format_parser.parse_video_formats(formats)
        audio_formats = self._format_parser.parse_audio_formats(formats)
        
        return {
            "video": video_formats,
            "audio": audio_formats,
        }
    
    # Download Operations
    def start_download(
        self,
        format_id: Optional[str] = None,
        output_path: Optional[str] = None,
        download_type: DownloadType = DownloadType.VIDEO,
        **options
    ) -> None:
        """
        Start downloading the current video.
        
        Args:
            format_id: Format ID to download
            output_path: Output directory
            download_type: Type of download (video, audio, etc.)
            **options: Additional download options
            
        Emits:
            DOWNLOAD_STARTED
            DOWNLOAD_PROGRESS
            DOWNLOAD_COMPLETED or DOWNLOAD_FAILED
        """
        if not self.state.video_info:
            self.log("Please fetch video info first", "warning")
            return
        
        if not self.state_machine.can_start():
            self.log("Cannot start: invalid state", "warning")
            return
        
        self.state.download_type = download_type
        self.state.selected_format = format_id
        if output_path:
            self.state.download_path = output_path
        
        self._cancel_flag.clear()
        self.state_machine.start()
        
        def do_download():
            try:
                url = self.state.current_url
                title = self.state.video_info.get('title', 'Unknown')
                
                self.log(f"⬇️ Starting download: {title}")
                
                manager = self._get_download_manager()
                
                # Set up progress callback
                def on_progress(progress: DownloadProgress):
                    if self._cancel_flag.is_set():
                        raise Exception("Download cancelled")
                    
                    self.state_machine.update_progress(progress.percent)
                    
                    EventBus.emit(
                        EventType.DOWNLOAD_PROGRESS,
                        data={
                            "percent": progress.percent,
                            "speed": progress.speed_str,
                            "eta": progress.eta_str,
                            "size": progress.size_str,
                        },
                        source="MainController"
                    )
                
                manager.set_progress_callback(on_progress)
                
                # Build options
                download_opts = {
                    "format_id": format_id,
                    "output_path": self.state.download_path,
                    "download_type": download_type,
                    **options,
                }
                
                result = manager.download(url, **download_opts)
                
                if result.success:
                    self.state_machine.complete()
                    
                    EventBus.emit(
                        EventType.DOWNLOAD_COMPLETED,
                        data={
                            "url": url,
                            "title": title,
                            "output_path": str(result.output_path),
                        },
                        source="MainController"
                    )
                    
                    self.log(f"✅ Download completed: {title}")
                else:
                    raise Exception(result.error_message or "Download failed")
                    
            except Exception as e:
                error_msg = str(e)
                if "cancelled" in error_msg.lower():
                    self.state_machine.cancel()
                    self.log("⏹️ Download cancelled")
                else:
                    logger.error(f"Download error: {error_msg}")
                    self.state_machine.fail(error_message=error_msg)
                    
                    EventBus.emit(
                        EventType.DOWNLOAD_FAILED,
                        data={"error": error_msg},
                        source="MainController"
                    )
                    
                    self.log(f"❌ Download failed: {error_msg}", "error")
        
        self._download_thread = threading.Thread(target=do_download, daemon=True)
        self._download_thread.start()
    
    def pause_download(self) -> bool:
        """Pause the current download"""
        if self.state_machine.can_pause():
            self.state_machine.pause()
            manager = self._get_download_manager()
            manager.pause()
            self.log("⏸️ Download paused")
            return True
        return False
    
    def resume_download(self) -> bool:
        """Resume the current download"""
        if self.state_machine.can_resume():
            self.state_machine.resume()
            manager = self._get_download_manager()
            manager.resume()
            self.log("▶️ Download resumed")
            return True
        return False
    
    def cancel_download(self) -> bool:
        """Cancel the current download"""
        if self.state_machine.can_cancel():
            self._cancel_flag.set()
            manager = self._get_download_manager()
            manager.cancel()
            self.state_machine.cancel()
            self.log("⏹️ Download cancelled")
            return True
        return False
    
    def reset(self) -> None:
        """Reset the controller to initial state"""
        self._cancel_flag.set()
        self.state_machine.reset()
        self.state = AppState()
        self.log("Reset complete")
    
    # Playlist Operations
    def get_playlist_entries(self) -> List[Dict]:
        """Get playlist entries"""
        return self.state.playlist_entries
    
    def select_playlist_items(self, indices: List[int]) -> None:
        """Select specific playlist items for download"""
        selected = [
            self.state.playlist_entries[i]
            for i in indices
            if i < len(self.state.playlist_entries)
        ]
        
        EventBus.emit(
            EventType.PLAYLIST_SELECTION_CHANGED,
            data={"selected": selected, "count": len(selected)},
            source="MainController"
        )
    
    def download_playlist(
        self,
        entries: List[Dict],
        output_path: str,
        **options
    ) -> None:
        """
        Download multiple videos from a playlist.
        
        Emits:
            BATCH_STARTED
            BATCH_PROGRESS
            BATCH_COMPLETED
        """
        if not entries:
            self.log("No items selected", "warning")
            return
        
        total = len(entries)
        self.log(f"📑 Starting playlist download: {total} videos")
        
        EventBus.emit(
            EventType.BATCH_STARTED,
            data={"total": total},
            source="MainController"
        )
        
        def do_batch_download():
            completed = 0
            failed = 0
            
            for i, entry in enumerate(entries):
                if self._cancel_flag.is_set():
                    break
                
                try:
                    url = entry.get('url') or entry.get('webpage_url')
                    if not url:
                        continue
                    
                    title = entry.get('title', f'Video {i+1}')
                    self.log(f"⬇️ [{i+1}/{total}] {title}")
                    
                    # Create state machine for this download
                    fsm = self.multi_state_machine.get_or_create(str(i))
                    fsm.start()
                    
                    manager = self._get_download_manager()
                    result = manager.download(url, output_path=output_path, **options)
                    
                    if result.success:
                        fsm.complete()
                        completed += 1
                    else:
                        fsm.fail(error_message=result.error_message)
                        failed += 1
                    
                    EventBus.emit(
                        EventType.BATCH_PROGRESS,
                        data={
                            "current": i + 1,
                            "total": total,
                            "completed": completed,
                            "failed": failed,
                        },
                        source="MainController"
                    )
                    
                except Exception as e:
                    failed += 1
                    logger.error(f"Batch download error: {e}")
            
            EventBus.emit(
                EventType.BATCH_COMPLETED,
                data={"total": total, "completed": completed, "failed": failed},
                source="MainController"
            )
            
            self.log(f"✅ Playlist complete: {completed}/{total} succeeded, {failed} failed")
        
        thread = threading.Thread(target=do_batch_download, daemon=True)
        thread.start()
    
    # Properties
    @property
    def is_fetching(self) -> bool:
        return self.state_machine.state == DownloadState.FETCHING
    
    @property
    def is_downloading(self) -> bool:
        return self.state_machine.state == DownloadState.DOWNLOADING
    
    @property
    def is_paused(self) -> bool:
        return self.state_machine.state == DownloadState.PAUSED
    
    @property
    def can_download(self) -> bool:
        return self.state_machine.can_start() and self.state.video_info is not None
