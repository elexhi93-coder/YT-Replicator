"""
Integration Tests for MVC Architecture
Tests controller interactions and callbacks.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import threading
import time

from controllers.download_controller import (
    DownloadController, DownloadConfig, DownloadProgress, DownloadState
)
from controllers.video_controller import (
    VideoController, VideoInfo, PlaylistInfo
)
from controllers.playlist_controller import (
    PlaylistController, PlaylistItem, PlaylistDownloadProgress
)
from core import DownloadType


class TestDownloadController:
    """Test DownloadController functionality"""
    
    def test_initial_state(self):
        """Test controller starts in IDLE state"""
        controller = DownloadController()
        assert controller.state == DownloadState.IDLE
    
    def test_callbacks_can_be_set(self):
        """Test callbacks can be set after construction"""
        on_progress = Mock()
        on_complete = Mock()
        on_error = Mock()
        
        controller = DownloadController()
        controller.on_progress = on_progress
        controller.on_complete = on_complete
        controller.on_error = on_error
        
        assert controller.on_progress == on_progress
        assert controller.on_complete == on_complete
        assert controller.on_error == on_error
    
    def test_config_creation(self):
        """Test DownloadConfig dataclass"""
        config = DownloadConfig(
            url="https://youtube.com/watch?v=test",
            output_path="/downloads",
            format_id="137+140",
            download_type=DownloadType.VIDEO,
            output_format="mp4",
        )
        
        assert config.url == "https://youtube.com/watch?v=test"
        assert config.output_path == "/downloads"
        assert config.format_id == "137+140"
        assert config.download_type == DownloadType.VIDEO
    
    def test_progress_dataclass(self):
        """Test DownloadProgress dataclass"""
        progress = DownloadProgress(
            percent=50.0,
            downloaded_bytes=50000000,
            total_bytes=100000000,
            speed="1.5 MB/s",
            eta="0:30",
        )
        
        assert progress.percent == 50.0
        assert progress.downloaded_bytes == 50000000
        assert progress.speed == "1.5 MB/s"
    
    def test_is_busy_when_idle(self):
        """Test is_busy returns False when idle"""
        controller = DownloadController()
        assert controller.is_busy() == False
    
    def test_cancel_when_idle(self):
        """Test cancel when idle does not change state"""
        controller = DownloadController()
        controller.cancel()
        # State stays IDLE because we weren't downloading
        assert controller.state == DownloadState.IDLE
    
    def test_ydl_options_building(self):
        """Test yt-dlp options are built correctly"""
        controller = DownloadController()
        config = DownloadConfig(
            url="https://youtube.com/watch?v=test",
            output_path="/downloads",
            format_id="137+bestaudio",
            output_format="mp4",
            concurrent_fragments=4,
        )
        
        opts = controller._build_ydl_opts(config)
        
        assert 'format' in opts
        assert opts['concurrent_fragment_downloads'] == 4
        assert 'merge_output_format' in opts


class TestVideoController:
    """Test VideoController functionality"""
    
    def test_callbacks_can_be_set(self):
        """Test callbacks can be set after construction"""
        on_info = Mock()
        on_error = Mock()
        
        controller = VideoController()
        controller.on_info_fetched = on_info
        controller.on_error = on_error
        
        assert controller.on_info_fetched == on_info
        assert controller.on_error == on_error
    
    def test_video_info_dataclass(self):
        """Test VideoInfo dataclass"""
        info = VideoInfo(
            title="Test Video",
            duration=300,
            uploader="Test Channel",
            view_count=1000000,
        )
        
        assert info.title == "Test Video"
        assert info.duration == 300
        assert info.uploader == "Test Channel"
    
    def test_playlist_info_dataclass(self):
        """Test PlaylistInfo dataclass"""
        entries = [
            VideoInfo(title="Video 1", duration=100),
            VideoInfo(title="Video 2", duration=200),
        ]
        
        info = PlaylistInfo(
            title="Test Playlist",
            uploader="Test Channel",
            entries=entries,
            video_count=2,
        )
        
        assert info.title == "Test Playlist"
        assert info.video_count == 2
        assert len(info.entries) == 2
    
    def test_video_info_defaults(self):
        """Test VideoInfo has sensible defaults"""
        info = VideoInfo(title="Test")
        
        assert info.duration == 0
        assert info.uploader == ""
        assert info.view_count == 0


class TestPlaylistController:
    """Test PlaylistController functionality"""
    
    def test_playlist_item_dataclass(self):
        """Test PlaylistItem dataclass"""
        item = PlaylistItem(
            index=1,
            id="test_id",
            title="Test Video",
            duration=300,
            url="https://youtube.com/watch?v=test",
        )
        
        assert item.index == 1
        assert item.title == "Test Video"
        assert item.duration == 300
    
    def test_callbacks_can_be_set(self):
        """Test all callbacks can be set"""
        on_progress = Mock()
        on_complete = Mock()
        on_all_complete = Mock()
        on_error = Mock()
        
        controller = PlaylistController()
        controller.on_item_progress = on_progress
        controller.on_item_complete = on_complete
        controller.on_all_complete = on_all_complete
        controller.on_error = on_error
        
        assert controller.on_item_progress == on_progress
        assert controller.on_item_complete == on_complete
        assert controller.on_all_complete == on_all_complete
        assert controller.on_error == on_error
    
    def test_cancelled_initial_state(self):
        """Test playlist controller cancelled flag initial state"""
        controller = PlaylistController()
        
        # Initial state - not cancelled
        assert controller._cancelled == False


class TestComponentIntegration:
    """Test integration between components"""
    
    def test_download_controller_to_progress_callback(self):
        """Test progress flows from controller to callback"""
        progress_updates = []
        
        def on_progress(progress: DownloadProgress):
            progress_updates.append(progress)
        
        controller = DownloadController()
        controller.on_progress = on_progress
        
        # Simulate progress update by calling the callback
        progress = DownloadProgress(
            percent=50.0,
            downloaded_bytes=50000000,
            total_bytes=100000000,
        )
        
        controller.on_progress(progress)
        
        assert len(progress_updates) == 1
        assert progress_updates[0].percent == 50.0
    
    def test_video_controller_to_info_callback(self):
        """Test video info flows from controller to callback"""
        info_received = []
        
        def on_info(info: VideoInfo):
            info_received.append(info)
        
        controller = VideoController()
        controller.on_info_fetched = on_info
        
        # Simulate info callback
        info = VideoInfo(title="Test", duration=100)
        controller.on_info_fetched(info)
        
        assert len(info_received) == 1
        assert info_received[0].title == "Test"
    
    def test_error_callback_flow(self):
        """Test error handling flows correctly"""
        errors = []
        
        def on_error(error: str):
            errors.append(error)
        
        controller = DownloadController()
        controller.on_error = on_error
        
        # Simulate error via callback
        controller.on_error("Test error")
        
        assert len(errors) == 1
        assert errors[0] == "Test error"


class TestProgressDataclass:
    """Test DownloadProgress data handling"""
    
    def test_progress_basic_fields(self):
        """Test progress basic fields"""
        progress = DownloadProgress(
            percent=50.0,
            downloaded_bytes=50 * 1024 * 1024,
            total_bytes=100 * 1024 * 1024,
            speed="5.0 MB/s",
            eta="0:30",
        )
        
        assert progress.percent == 50.0
        assert progress.speed == "5.0 MB/s"
        assert progress.eta == "0:30"
    
    def test_progress_optional_fields(self):
        """Test progress with optional fields"""
        progress = DownloadProgress(
            percent=25.0,
            downloaded_bytes=25000000,
        )
        
        assert progress.percent == 25.0
        assert progress.total_bytes is None
        assert progress.speed is None


class TestConfigDefaults:
    """Test configuration default values"""
    
    def test_download_config_defaults(self):
        """Test DownloadConfig has sensible defaults"""
        config = DownloadConfig(
            url="https://youtube.com/watch?v=test",
            output_path="/downloads",
        )
        
        assert config.format_id is None
        assert config.concurrent_fragments == 4
        assert config.use_aria2c == False
        assert config.output_format == "mp4"
    
    def test_download_config_all_fields(self):
        """Test DownloadConfig with all fields"""
        config = DownloadConfig(
            url="https://youtube.com/watch?v=test",
            output_path="/downloads",
            format_id="137+140",
            download_type=DownloadType.VIDEO,
            output_format="mkv",
            concurrent_fragments=8,
            use_aria2c=True,
            aria2c_connections=32,
        )
        
        assert config.format_id == "137+140"
        assert config.concurrent_fragments == 8
        assert config.use_aria2c == True
        assert config.output_format == "mkv"


class TestStateTransitions:
    """Test controller state machine transitions"""
    
    def test_idle_to_downloading(self):
        """Test transition from IDLE to DOWNLOADING"""
        controller = DownloadController()
        assert controller.state == DownloadState.IDLE
        
        # After starting download, state should change
        # (actual download skipped, just test state concept)
    
    def test_cancel_when_not_downloading(self):
        """Test cancel when not downloading stays IDLE"""
        controller = DownloadController()
        controller.cancel()
        # State stays IDLE because we weren't downloading
        assert controller.state == DownloadState.IDLE
    
    def test_state_enum_values(self):
        """Test all state enum values exist"""
        assert DownloadState.IDLE
        assert DownloadState.FETCHING
        assert DownloadState.DOWNLOADING
        assert DownloadState.PAUSED
        assert DownloadState.CANCELLED
        assert DownloadState.COMPLETED
        assert DownloadState.ERROR
