"""
Tests for Phase 4: Exceptions and Download Queue
"""

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

from core.exceptions import (
    IDMError, ErrorCategory, ErrorContext,
    NetworkError, ConnectionError, TimeoutError, RateLimitError,
    VideoNotFoundError, PlaylistNotFoundError, PrivateVideoError,
    AgeRestrictedError, GeoBlockedError,
    FormatError, FormatNotAvailableError, FFmpegError, FFmpegNotFoundError,
    StorageError, DiskFullError,
    ExtractionError, UnsupportedURLError, PluginError,
    DownloadError, DownloadCancelledError,
    classify_yt_dlp_error,
)
from core.download_queue import (
    DownloadQueue, QueueItem, QueuePriority, QueueStats
)
from core.settings import (
    AppSettings, WindowSettings, DownloadSettings, ClipboardSettings,
    UISettings, PluginSettings, SettingsManager,
)
from core.enums import DownloadStatus


# ===== Exception Tests =====

class TestErrorCategory:
    """Tests for ErrorCategory enum"""
    
    def test_all_categories_exist(self):
        """All error categories should be defined"""
        categories = [
            ErrorCategory.NETWORK,
            ErrorCategory.AUTH,
            ErrorCategory.FORMAT,
            ErrorCategory.STORAGE,
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.NOT_FOUND,
            ErrorCategory.EXTRACTION,
            ErrorCategory.CONFIG,
            ErrorCategory.PLUGIN,
            ErrorCategory.UNKNOWN,
        ]
        assert len(categories) == 10


class TestErrorContext:
    """Tests for ErrorContext dataclass"""
    
    def test_create_empty_context(self):
        """Should create context with defaults"""
        ctx = ErrorContext()
        assert ctx.url is None
        assert ctx.video_id is None
        assert ctx.attempt == 0
    
    def test_create_with_values(self):
        """Should store provided values"""
        ctx = ErrorContext(
            url="https://youtube.com/watch?v=test",
            video_id="test",
            attempt=3,
            max_attempts=5,
        )
        assert ctx.url == "https://youtube.com/watch?v=test"
        assert ctx.video_id == "test"
        assert ctx.attempt == 3
        assert ctx.max_attempts == 5


class TestIDMError:
    """Tests for base IDMError"""
    
    def test_basic_error(self):
        """Should create basic error"""
        error = IDMError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.category == ErrorCategory.UNKNOWN
        assert error.recoverable is False
    
    def test_error_with_category(self):
        """Should set category"""
        error = IDMError("Network issue", category=ErrorCategory.NETWORK)
        assert error.category == ErrorCategory.NETWORK
    
    def test_error_with_context(self):
        """Should store context"""
        ctx = ErrorContext(url="https://example.com")
        error = IDMError("Error", context=ctx)
        assert error.context.url == "https://example.com"
    
    def test_recoverable_error(self):
        """Should mark as recoverable"""
        error = IDMError("Retry later", recoverable=True)
        assert error.recoverable is True


class TestNetworkErrors:
    """Tests for network-related errors"""
    
    def test_network_error(self):
        """NetworkError should be NETWORK category"""
        error = NetworkError("Connection failed")
        assert error.category == ErrorCategory.NETWORK
    
    def test_connection_error(self):
        """ConnectionError should be NetworkError subclass"""
        error = ConnectionError("No internet")
        assert isinstance(error, NetworkError)
        assert error.recoverable is True
    
    def test_timeout_error(self):
        """TimeoutError should be NetworkError subclass"""
        error = TimeoutError("Request timed out")
        assert isinstance(error, NetworkError)
        assert error.recoverable is True
    
    def test_rate_limit_error(self):
        """RateLimitError should have retry info"""
        error = RateLimitError("https://example.com", retry_after=60)
        assert error.category == ErrorCategory.RATE_LIMIT
        assert error.retry_after == 60
        assert error.recoverable is True


class TestVideoErrors:
    """Tests for video-related errors"""
    
    def test_video_not_found(self):
        """VideoNotFoundError should be NOT_FOUND"""
        error = VideoNotFoundError("dQw4w9WgXcQ")
        assert error.category == ErrorCategory.NOT_FOUND
        assert "dQw4w9WgXcQ" in str(error)
    
    def test_private_video(self):
        """PrivateVideoError should be AUTH"""
        error = PrivateVideoError("private123")
        assert error.category == ErrorCategory.AUTH
        assert error.recoverable is False
    
    def test_age_restricted(self):
        """AgeRestrictedError should be AUTH"""
        error = AgeRestrictedError("adult123")
        assert error.category == ErrorCategory.AUTH
    
    def test_geo_blocked(self):
        """GeoBlockedError should be AUTH"""
        error = GeoBlockedError("https://example.com", video_id="blocked123", country="US")
        assert error.category == ErrorCategory.AUTH
        assert error.context.extra["country"] == "US"


class TestFormatErrors:
    """Tests for format-related errors"""
    
    def test_format_error(self):
        """FormatError should be FORMAT category"""
        error = FormatError("Invalid format")
        assert error.category == ErrorCategory.FORMAT
    
    def test_format_not_available(self):
        """FormatNotAvailableError should track format id"""
        error = FormatNotAvailableError("1080p", url="https://example.com")
        assert "1080p" in str(error)
    
    def test_ffmpeg_error(self):
        """FFmpegError should store operation"""
        error = FFmpegError("Conversion failed", operation="encoding")
        assert "encoding" in str(error)
    
    def test_ffmpeg_not_found(self):
        """FFmpegNotFoundError should be subclass"""
        error = FFmpegNotFoundError()
        assert isinstance(error, FFmpegError)


class TestStorageErrors:
    """Tests for storage-related errors"""
    
    def test_storage_error(self):
        """StorageError should be STORAGE category"""
        error = StorageError("Write failed")
        assert error.category == ErrorCategory.STORAGE
    
    def test_disk_full(self):
        """DiskFullError should track path"""
        error = DiskFullError("/path/to/disk", required_bytes=1024*1024)
        assert error.category == ErrorCategory.STORAGE
        assert "/path/to/disk" in str(error)


class TestOtherErrors:
    """Tests for other error types"""
    
    def test_extraction_error(self):
        """ExtractionError should be EXTRACTION"""
        error = ExtractionError("Failed to parse", url="https://example.com")
        assert error.category == ErrorCategory.EXTRACTION
    
    def test_unsupported_url(self):
        """UnsupportedURLError should store URL"""
        error = UnsupportedURLError("https://unknown.com/video")
        assert "https://unknown.com/video" in str(error)
    
    def test_plugin_error(self):
        """PluginError should store plugin name"""
        error = PluginError("metadata", "Plugin crashed")
        assert "metadata" in str(error)
        assert error.category == ErrorCategory.PLUGIN
    
    def test_download_cancelled(self):
        """DownloadCancelledError should exist"""
        error = DownloadCancelledError("https://example.com")
        assert isinstance(error, DownloadError)


class TestClassifyYtDlpError:
    """Tests for yt-dlp error classification"""
    
    def test_classify_network_error(self):
        """Should classify network errors"""
        # Mock yt-dlp network error
        class MockNetworkError(Exception):
            pass
        
        with patch.dict('sys.modules', {'yt_dlp.utils': Mock()}):
            # Just test that function exists and returns IDMError
            error = classify_yt_dlp_error(Exception("network error"), "https://youtube.com")
            assert isinstance(error, IDMError)
    
    def test_classify_generic_error(self):
        """Should wrap unknown errors"""
        error = classify_yt_dlp_error(ValueError("unknown"), "https://youtube.com")
        assert isinstance(error, IDMError)


# ===== Download Queue Tests =====

class TestQueuePriority:
    """Tests for QueuePriority enum"""
    
    def test_priority_ordering(self):
        """Priorities should be ordered"""
        assert QueuePriority.LOW.value < QueuePriority.NORMAL.value
        assert QueuePriority.NORMAL.value < QueuePriority.HIGH.value
        assert QueuePriority.HIGH.value < QueuePriority.URGENT.value
    
    def test_priority_comparison(self):
        """Should support comparison"""
        assert QueuePriority.LOW < QueuePriority.HIGH


class TestQueueItem:
    """Tests for QueueItem dataclass"""
    
    def test_create_item(self):
        """Should create with defaults"""
        item = QueueItem(url="https://youtube.com/watch?v=test")
        assert item.url == "https://youtube.com/watch?v=test"
        assert item.status == DownloadStatus.PENDING
        assert item.priority == QueuePriority.NORMAL
        assert item.id is not None
    
    def test_item_has_timestamps(self):
        """Should have timestamp fields"""
        item = QueueItem(url="test")
        assert item.added_at is not None
        assert item.started_at is None
        assert item.completed_at is None
    
    def test_to_dict(self):
        """Should serialize to dict"""
        item = QueueItem(url="test", title="Test Video")
        data = item.to_dict()
        assert data['url'] == "test"
        assert data['title'] == "Test Video"
        assert 'status' in data
    
    def test_from_dict(self):
        """Should deserialize from dict"""
        data = {
            'id': 'test123',
            'url': 'https://example.com',
            'title': 'Test',
            'status': 'pending',
            'priority': 1,
        }
        item = QueueItem.from_dict(data)
        assert item.id == 'test123'
        assert item.url == 'https://example.com'
        assert item.status == DownloadStatus.PENDING


class TestDownloadQueue:
    """Tests for DownloadQueue class"""
    
    @pytest.fixture
    def temp_queue_path(self, tmp_path):
        """Create temp path for queue persistence"""
        return tmp_path / "queue.json"
    
    @pytest.fixture
    def queue(self, temp_queue_path):
        """Create test queue"""
        q = DownloadQueue(
            persistence_path=temp_queue_path,
            auto_save=False,
        )
        yield q
        q.stop()
    
    def test_add_item(self, queue):
        """Should add items to queue"""
        item = queue.add("https://youtube.com/watch?v=test", title="Test")
        assert item.url == "https://youtube.com/watch?v=test"
        assert item.title == "Test"
        assert queue.get(item.id) is not None
    
    def test_remove_item(self, queue):
        """Should remove items"""
        item = queue.add("test")
        assert queue.remove(item.id) is True
        assert queue.get(item.id) is None
    
    def test_get_all(self, queue):
        """Should return all items"""
        queue.add("url1")
        queue.add("url2")
        items = queue.get_all()
        assert len(items) == 2
    
    def test_get_by_status(self, queue):
        """Should filter by status"""
        item1 = queue.add("url1")
        item2 = queue.add("url2")
        item2.status = DownloadStatus.COMPLETED
        
        pending = queue.get_by_status(DownloadStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].id == item1.id
    
    def test_get_stats(self, queue):
        """Should calculate statistics"""
        queue.add("url1")
        queue.add("url2")
        item3 = queue.add("url3")
        item3.status = DownloadStatus.COMPLETED
        
        stats = queue.get_stats()
        assert stats.total == 3
        assert stats.pending == 2
        assert stats.completed == 1
    
    def test_clear_completed(self, queue):
        """Should clear completed items"""
        queue.add("url1")
        item2 = queue.add("url2")
        item2.status = DownloadStatus.COMPLETED
        
        cleared = queue.clear_completed()
        assert cleared == 1
        assert len(queue.get_all()) == 1
    
    def test_priority_ordering(self, queue):
        """Items should be ordered by priority"""
        queue.add("low", priority=QueuePriority.LOW)
        queue.add("high", priority=QueuePriority.HIGH)
        queue.add("normal", priority=QueuePriority.NORMAL)
        
        # Higher priority items should come first
        items = sorted(queue.get_all())
        assert items[0].priority == QueuePriority.HIGH
    
    def test_update_progress(self, queue):
        """Should update item progress"""
        item = queue.add("test")
        queue.update_progress(
            item.id,
            progress=0.5,
            downloaded_bytes=1024,
            speed="1 MB/s",
        )
        
        updated = queue.get(item.id)
        assert updated.progress == 0.5
        assert updated.downloaded_bytes == 1024
        assert updated.speed == "1 MB/s"
    
    def test_pause_resume(self, queue):
        """Should pause and resume"""
        assert queue.is_paused is False
        queue.pause()
        assert queue.is_paused is True
        queue.resume()
        assert queue.is_paused is False


class TestQueuePersistence:
    """Tests for queue persistence"""
    
    def test_save_and_load(self, tmp_path):
        """Should persist queue to disk"""
        queue_path = tmp_path / "test_queue.json"
        
        # Create and populate queue
        queue1 = DownloadQueue(persistence_path=queue_path, auto_save=True)
        queue1.add("url1", title="Video 1")
        queue1.add("url2", title="Video 2")
        queue1.stop()
        
        # Load in new queue instance
        queue2 = DownloadQueue(persistence_path=queue_path)
        items = queue2.get_all()
        
        assert len(items) == 2
        titles = {item.title for item in items}
        assert "Video 1" in titles
        assert "Video 2" in titles
        
        queue2.stop()


class TestQueueStats:
    """Tests for QueueStats dataclass"""
    
    def test_default_stats(self):
        """Should have zero defaults"""
        stats = QueueStats()
        assert stats.total == 0
        assert stats.pending == 0
        assert stats.downloading == 0
        assert stats.completed == 0
        assert stats.failed == 0


# ===== Settings Tests =====

class TestWindowSettings:
    """Tests for WindowSettings dataclass"""
    
    def test_defaults(self):
        """Should have sensible defaults"""
        settings = WindowSettings()
        assert settings.width == 800
        assert settings.height == 600
        assert settings.maximized is False
    
    def test_custom_values(self):
        """Should accept custom values"""
        settings = WindowSettings(width=1200, height=800, maximized=True)
        assert settings.width == 1200
        assert settings.height == 800
        assert settings.maximized is True


class TestDownloadSettings:
    """Tests for DownloadSettings dataclass"""
    
    def test_defaults(self):
        """Should have sensible defaults"""
        settings = DownloadSettings()
        assert settings.default_quality == "best"
        assert settings.embed_thumbnail is True
        assert settings.max_concurrent == 2
    
    def test_default_path_created(self):
        """Should create default path in Downloads folder"""
        settings = DownloadSettings()
        assert "IDM-YT" in settings.default_path


class TestAppSettings:
    """Tests for AppSettings"""
    
    def test_create_defaults(self):
        """Should create with all default subsettings"""
        settings = AppSettings()
        assert isinstance(settings.window, WindowSettings)
        assert isinstance(settings.download, DownloadSettings)
        assert isinstance(settings.clipboard, ClipboardSettings)
        assert isinstance(settings.ui, UISettings)
        assert isinstance(settings.plugins, PluginSettings)
    
    def test_add_recent_url(self):
        """Should track recent URLs"""
        settings = AppSettings()
        settings.add_recent_url("https://youtube.com/watch?v=1")
        settings.add_recent_url("https://youtube.com/watch?v=2")
        
        assert len(settings.recent_urls) == 2
        assert settings.recent_urls[0] == "https://youtube.com/watch?v=2"  # Most recent first
    
    def test_add_recent_url_deduplicates(self):
        """Should move existing URL to front"""
        settings = AppSettings()
        settings.add_recent_url("url1")
        settings.add_recent_url("url2")
        settings.add_recent_url("url1")
        
        assert len(settings.recent_urls) == 2
        assert settings.recent_urls[0] == "url1"
    
    def test_add_recent_url_max_items(self):
        """Should limit recent URLs"""
        settings = AppSettings()
        for i in range(30):
            settings.add_recent_url(f"url{i}")
        
        assert len(settings.recent_urls) == 20  # Default max
    
    def test_clear_recent(self):
        """Should clear all recent items"""
        settings = AppSettings()
        settings.add_recent_url("url1")
        settings.add_recent_path("/path1")
        settings.clear_recent()
        
        assert settings.recent_urls == []
        assert settings.recent_paths == []
    
    def test_reset(self):
        """Should reset to defaults"""
        settings = AppSettings()
        settings.download.default_quality = "720p"
        settings.add_recent_url("url1")
        
        settings.reset()
        
        assert settings.download.default_quality == "best"
        assert settings.recent_urls == []


class TestSettingsPersistence:
    """Tests for settings persistence"""
    
    def test_save_and_load(self, tmp_path):
        """Should persist settings to disk"""
        settings_file = tmp_path / "settings.json"
        
        # Create and modify settings
        settings1 = AppSettings()
        settings1._settings_file = str(settings_file)
        settings1.download.default_quality = "1080p"
        settings1.add_recent_url("https://example.com")
        settings1.save()
        
        # Load in new instance
        settings2 = AppSettings.load(str(settings_file))
        
        assert settings2.download.default_quality == "1080p"
        assert "https://example.com" in settings2.recent_urls
    
    def test_load_missing_file(self, tmp_path):
        """Should return defaults for missing file"""
        settings = AppSettings.load(str(tmp_path / "nonexistent.json"))
        assert settings.download.default_quality == "best"


class TestSettingsManager:
    """Tests for SettingsManager singleton"""
    
    def test_get_returns_same_instance(self, tmp_path):
        """Should return same instance"""
        settings_file = str(tmp_path / "settings.json")
        SettingsManager._instance = None  # Reset singleton
        SettingsManager.initialize(settings_file)
        
        s1 = SettingsManager.get()
        s2 = SettingsManager.get()
        
        assert s1 is s2
    
    def test_save(self, tmp_path):
        """Should save via manager"""
        settings_file = tmp_path / "settings.json"
        SettingsManager._instance = None  # Reset singleton
        SettingsManager.initialize(str(settings_file))
        
        settings = SettingsManager.get()
        settings.download.default_quality = "720p"
        SettingsManager.save()
        
        assert settings_file.exists()
