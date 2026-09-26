"""
Unit Tests for Phase 2 Components
ClipboardMonitor, VideoInfoFetcher, ProgressTracker
"""

import pytest
import time
import threading
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.clipboard_monitor import ClipboardMonitor, ClipboardMonitorConfig, ClipboardURLExtractor
from core.video_fetcher import VideoInfoFetcher, VideoInfo, FetchResult, FetchStatus, FetcherConfig
from core.progress_tracker import ProgressTracker, ProgressInfo, ProgressState, ProgressTrackerConfig


class TestClipboardMonitorConfig:
    """Tests for ClipboardMonitorConfig"""
    
    def test_default_values(self):
        config = ClipboardMonitorConfig()
        assert config.check_interval_ms == 1000
        assert config.enabled == True
        assert config.auto_paste_when_empty == True
    
    def test_custom_values(self):
        config = ClipboardMonitorConfig(
            check_interval_ms=500,
            enabled=False,
            auto_paste_when_empty=False,
        )
        assert config.check_interval_ms == 500
        assert config.enabled == False


class TestClipboardMonitor:
    """Tests for ClipboardMonitor"""
    
    def test_initialization(self):
        detected_urls = []
        
        monitor = ClipboardMonitor(
            on_url_detected=lambda url, auto: detected_urls.append(url),
            get_current_url=lambda: "",
        )
        
        assert monitor.enabled == True
        assert monitor.get_last_detected_url() == ""
    
    def test_enable_disable(self):
        monitor = ClipboardMonitor(
            on_url_detected=lambda url, auto: None,
            get_current_url=lambda: "",
        )
        
        monitor.enabled = False
        assert monitor.enabled == False
        
        monitor.enabled = True
        assert monitor.enabled == True
    
    def test_clear_history(self):
        monitor = ClipboardMonitor(
            on_url_detected=lambda url, auto: None,
            get_current_url=lambda: "",
        )
        
        monitor._last_clipboard_url = "https://youtube.com/watch?v=test"
        monitor.clear_history()
        assert monitor.get_last_detected_url() == ""


class TestClipboardURLExtractor:
    """Tests for ClipboardURLExtractor"""
    
    def test_extract_all(self):
        text = """
        Check out these videos:
        https://www.youtube.com/watch?v=abc123
        https://youtu.be/def456
        https://vimeo.com/789012
        """
        urls = ClipboardURLExtractor.extract_all(text)
        assert len(urls) == 3
    
    def test_extract_first(self):
        text = "Video: https://www.youtube.com/watch?v=test Another: https://youtu.be/xyz"
        url = ClipboardURLExtractor.extract_first(text)
        assert "youtube.com" in url or "youtu.be" in url
    
    def test_extract_from_empty(self):
        assert ClipboardURLExtractor.extract_all("") == []
        assert ClipboardURLExtractor.extract_first("") is None


class TestVideoInfo:
    """Tests for VideoInfo dataclass"""
    
    def test_from_yt_dlp_single_video(self):
        info_dict = {
            'id': 'test123',
            'title': 'Test Video',
            'duration': 120,
            'uploader': 'Test Channel',
            'view_count': 1000,
            'thumbnail': 'https://example.com/thumb.jpg',
            'formats': [{'format_id': '137'}],
        }
        
        video_info = VideoInfo.from_yt_dlp(info_dict)
        
        assert video_info.video_id == 'test123'
        assert video_info.title == 'Test Video'
        assert video_info.duration == 120
        assert video_info.uploader == 'Test Channel'
        assert video_info.is_playlist == False
    
    def test_from_yt_dlp_playlist(self):
        info_dict = {
            '_type': 'playlist',
            'id': 'PLtest',
            'title': 'Test Playlist',
            'entries': [{'id': 'vid1'}, {'id': 'vid2'}],
            'uploader': 'Playlist Creator',
        }
        
        video_info = VideoInfo.from_yt_dlp(info_dict)
        
        assert video_info.is_playlist == True
        assert video_info.playlist_count == 2
        assert video_info.playlist_title == 'Test Playlist'


class TestFetchResult:
    """Tests for FetchResult dataclass"""
    
    def test_success_result(self):
        result = FetchResult(
            status=FetchStatus.SUCCESS,
            video_info=VideoInfo(video_id='test', title='Test'),
            url='https://youtube.com/watch?v=test',
        )
        
        assert result.is_success == True
        assert result.is_playlist == False
    
    def test_error_result(self):
        result = FetchResult(
            status=FetchStatus.ERROR,
            error_message='Network error',
            url='https://youtube.com/watch?v=test',
        )
        
        assert result.is_success == False
        assert result.error_message == 'Network error'


class TestFetcherConfig:
    """Tests for FetcherConfig"""
    
    def test_to_ydl_opts(self):
        config = FetcherConfig(
            quiet=True,
            retries=5,
            socket_timeout=60,
        )
        
        opts = config.to_ydl_opts()
        
        assert opts['quiet'] == True
        assert opts['retries'] == 5
        assert opts['socket_timeout'] == 60


class TestVideoInfoFetcher:
    """Tests for VideoInfoFetcher"""
    
    def test_initialization(self):
        fetcher = VideoInfoFetcher()
        assert fetcher.is_fetching() == False
    
    def test_custom_config(self):
        config = FetcherConfig(retries=10)
        fetcher = VideoInfoFetcher(config=config)
        assert fetcher.config.retries == 10
    
    def test_cancel(self):
        fetcher = VideoInfoFetcher()
        fetcher.cancel()
        assert fetcher._cancelled == True


class TestProgressInfo:
    """Tests for ProgressInfo dataclass"""
    
    def test_default_values(self):
        info = ProgressInfo()
        assert info.state == ProgressState.IDLE
        assert info.progress == 0.0
        assert info.progress_percent == 0.0
    
    def test_progress_percent(self):
        info = ProgressInfo(progress=0.75)
        assert info.progress_percent == 75.0
    
    def test_format_bytes(self):
        info = ProgressInfo()
        assert "KB" in info._format_bytes(2048)
        assert "MB" in info._format_bytes(5242880)
        assert "GB" in info._format_bytes(1610612736)
    
    def test_downloaded_str(self):
        info = ProgressInfo(downloaded_bytes=1048576)  # 1 MB
        assert "MB" in info.downloaded_str


class TestProgressTracker:
    """Tests for ProgressTracker"""
    
    def test_initialization(self):
        tracker = ProgressTracker()
        assert tracker.state == ProgressState.IDLE
        assert tracker.current_info.progress == 0.0
    
    def test_set_state(self):
        states = []
        tracker = ProgressTracker(
            on_state_change=lambda s: states.append(s)
        )
        
        tracker.set_state(ProgressState.DOWNLOADING, "Starting download")
        
        assert tracker.state == ProgressState.DOWNLOADING
        assert ProgressState.DOWNLOADING in states
    
    def test_update_progress(self):
        progress_values = []
        tracker = ProgressTracker(
            on_progress=lambda info: progress_values.append(info.progress)
        )
        
        tracker.update(progress=0.5)
        
        assert tracker.current_info.progress == 0.5
    
    def test_smooth_progress(self):
        tracker = ProgressTracker(
            config=ProgressTrackerConfig(smooth_progress=True)
        )
        
        tracker.update(progress=0.5)
        tracker.update(progress=0.3)  # Should not go backwards
        
        assert tracker.current_info.progress == 0.5  # Stays at 0.5
    
    def test_complete(self):
        completed = []
        tracker = ProgressTracker(
            on_complete=lambda info: completed.append(info)
        )
        
        tracker.complete("Done!")
        
        assert tracker.state == ProgressState.COMPLETED
        assert tracker.current_info.progress == 1.0
        assert len(completed) == 1
    
    def test_error(self):
        errors = []
        tracker = ProgressTracker(
            on_error=lambda msg: errors.append(msg)
        )
        
        tracker.error("Network failed")
        
        assert tracker.state == ProgressState.ERROR
        assert "Network failed" in errors
    
    def test_cancel(self):
        tracker = ProgressTracker()
        tracker.cancel()
        
        assert tracker.state == ProgressState.CANCELLED
    
    def test_reset(self):
        tracker = ProgressTracker()
        tracker.set_state(ProgressState.DOWNLOADING)
        tracker.update(progress=0.5)
        
        tracker.reset()
        
        assert tracker.state == ProgressState.IDLE
        assert tracker.current_info.progress == 0.0
    
    def test_yt_dlp_hook_downloading(self):
        tracker = ProgressTracker()
        
        tracker.yt_dlp_hook({
            'status': 'downloading',
            'downloaded_bytes': 5242880,  # 5 MB
            'total_bytes': 10485760,  # 10 MB
            'speed': 1048576,  # 1 MB/s
            'eta': 5,
        })
        
        assert tracker.state == ProgressState.DOWNLOADING
        assert tracker.current_info.progress == 0.5
    
    def test_yt_dlp_hook_finished(self):
        tracker = ProgressTracker()
        tracker.yt_dlp_hook({'status': 'finished'})
        
        assert tracker.state == ProgressState.PROCESSING


class TestProgressTrackerConfig:
    """Tests for ProgressTrackerConfig"""
    
    def test_default_values(self):
        config = ProgressTrackerConfig()
        assert config.update_interval_ms == 100
        assert config.smooth_progress == True


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
