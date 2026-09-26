"""
Unit Tests for IDM-YT Core Module
Run with: python -m pytest tests/ -v
"""

import pytest
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.enums import (
    DownloadType, 
    VideoQuality, 
    AudioQuality, 
    URLType, 
    DownloadStatus,
    SubtitleFormat,
)
from core.config import AppConfig, DownloadOptions
from core.format_parser import FormatParser, VideoFormat, AudioFormat
from core.url_parser import URLParser, ParsedURL


class TestDownloadTypeEnum:
    """Tests for DownloadType enum"""
    
    def test_values(self):
        assert DownloadType.VIDEO.value == "video"
        assert DownloadType.AUDIO.value == "audio"
        assert DownloadType.THUMBNAIL.value == "thumbnail"
        assert DownloadType.SUBTITLES.value == "subtitles"
    
    def test_string_conversion(self):
        assert str(DownloadType.VIDEO) == "video"
        assert str(DownloadType.AUDIO) == "audio"
    
    def test_display_name(self):
        assert "🎥" in DownloadType.VIDEO.display_name
        assert "🎵" in DownloadType.AUDIO.display_name


class TestVideoQualityEnum:
    """Tests for VideoQuality enum"""
    
    def test_quality_heights(self):
        assert VideoQuality.Q4K.height == 2160
        assert VideoQuality.Q1080P.height == 1080
        assert VideoQuality.Q720P.height == 720
    
    def test_from_height(self):
        assert VideoQuality.from_height(1080) == VideoQuality.Q1080P
        assert VideoQuality.from_height(720) == VideoQuality.Q720P
        assert VideoQuality.from_height(9999) == VideoQuality.BEST  # Unknown returns BEST
    
    def test_display_list(self):
        displays = VideoQuality.get_display_list()
        assert len(displays) == 9  # BEST + 8 quality levels
        assert "Best Available" in displays
        assert "Full HD (1080p)" in displays


class TestAudioQualityEnum:
    """Tests for AudioQuality enum"""
    
    def test_is_mp3(self):
        assert AudioQuality.MP3_320.is_mp3 == True
        assert AudioQuality.MP3_192.is_mp3 == True
        assert AudioQuality.BEST.is_mp3 == False
    
    def test_mp3_bitrate(self):
        assert AudioQuality.MP3_320.mp3_bitrate == "320"
        assert AudioQuality.MP3_192.mp3_bitrate == "192"
        assert AudioQuality.MP3_128.mp3_bitrate == "128"
    
    def test_display_list_without_ffmpeg(self):
        displays = AudioQuality.get_display_list(ffmpeg_available=False)
        # MP3 options should be excluded
        assert not any("MP3" in d for d in displays)


class TestURLTypeEnum:
    """Tests for URLType enum"""
    
    def test_detect_youtube_video(self):
        assert URLType.detect("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == URLType.SINGLE_VIDEO
        assert URLType.detect("https://youtu.be/dQw4w9WgXcQ") == URLType.SINGLE_VIDEO
    
    def test_detect_youtube_playlist(self):
        assert URLType.detect("https://www.youtube.com/playlist?list=PLtest123") == URLType.PLAYLIST
        assert URLType.detect("https://www.youtube.com/watch?v=abc&list=PLtest") == URLType.PLAYLIST
    
    def test_detect_youtube_channel(self):
        assert URLType.detect("https://www.youtube.com/@channelname") == URLType.CHANNEL
        assert URLType.detect("https://www.youtube.com/@channelname/videos") == URLType.CHANNEL_VIDEOS
        assert URLType.detect("https://www.youtube.com/@channelname/shorts") == URLType.CHANNEL_SHORTS
    
    def test_is_channel_property(self):
        assert URLType.CHANNEL.is_channel == True
        assert URLType.CHANNEL_VIDEOS.is_channel == True
        assert URLType.SINGLE_VIDEO.is_channel == False
    
    def test_is_collection_property(self):
        assert URLType.PLAYLIST.is_collection == True
        assert URLType.CHANNEL.is_collection == True
        assert URLType.SINGLE_VIDEO.is_collection == False


class TestDownloadStatusEnum:
    """Tests for DownloadStatus enum"""
    
    def test_icons(self):
        assert DownloadStatus.DOWNLOADING.icon == "⬇️"
        assert DownloadStatus.COMPLETED.icon == "✅"
        assert DownloadStatus.FAILED.icon == "❌"


class TestAppConfig:
    """Tests for AppConfig class"""
    
    def test_default_values(self):
        config = AppConfig()
        assert config.default_download_path == Path.home() / "Downloads"
        assert config.clipboard_enabled == True
        assert config.max_retries == 5
    
    def test_custom_values(self):
        config = AppConfig(
            max_retries=10,
            base_backoff_sleep=5.0,
        )
        assert config.max_retries == 10
        assert config.base_backoff_sleep == 5.0
    
    def test_string_to_path_conversion(self):
        config = AppConfig(default_download_path="/tmp/downloads")
        assert isinstance(config.default_download_path, Path)


class TestDownloadOptions:
    """Tests for DownloadOptions class"""
    
    def test_default_options(self):
        opts = DownloadOptions(url="https://youtube.com/watch?v=test")
        assert opts.download_type == "video"
        assert opts.audio_format == "bestaudio"
    
    def test_to_ydl_opts_video(self):
        opts = DownloadOptions(
            url="https://youtube.com/watch?v=test",
            download_type="video",
            video_format_id="137+140",
            output_path=Path("/tmp"),
        )
        ydl_opts = opts.to_ydl_opts()
        assert ydl_opts['format'] == "137+140"
        assert 'outtmpl' in ydl_opts
    
    def test_to_ydl_opts_audio_mp3(self):
        opts = DownloadOptions(
            url="https://youtube.com/watch?v=test",
            download_type="audio",
            mp3_bitrate="320",
        )
        ydl_opts = opts.to_ydl_opts()
        assert 'postprocessors' in ydl_opts
        assert ydl_opts['postprocessors'][0]['preferredcodec'] == 'mp3'
    
    def test_to_ydl_opts_thumbnail(self):
        opts = DownloadOptions(
            url="https://youtube.com/watch?v=test",
            download_type="thumbnail",
        )
        ydl_opts = opts.to_ydl_opts()
        assert ydl_opts['skip_download'] == True
        assert ydl_opts['writethumbnail'] == True
    
    def test_to_ydl_opts_subtitles(self):
        opts = DownloadOptions(
            url="https://youtube.com/watch?v=test",
            download_type="subtitles",
            subtitle_langs=["en", "es"],
        )
        ydl_opts = opts.to_ydl_opts()
        assert ydl_opts['writesubtitles'] == True
        assert ydl_opts['subtitleslangs'] == ["en", "es"]


class TestVideoFormat:
    """Tests for VideoFormat dataclass"""
    
    def test_from_dict(self):
        fmt_dict = {
            'format_id': '137',
            'ext': 'mp4',
            'height': 1080,
            'width': 1920,
            'fps': 30,
            'filesize': 52428800,
            'vcodec': 'avc1.640028',
            'acodec': 'none',
        }
        vf = VideoFormat.from_dict(fmt_dict)
        assert vf.format_id == '137'
        assert vf.height == 1080
        assert vf.has_video == True
        assert vf.has_audio == False
    
    def test_quality_label(self):
        vf = VideoFormat(
            format_id='137',
            extension='mp4',
            height=1080,
            width=1920,
            fps=60,
            filesize=104857600,  # 100MB
            filesize_approx=None,
            vcodec='avc1',
            acodec=None,
            tbr=5000,
            format_note='premium',
        )
        label = vf.quality_label
        assert "1080p" in label
        assert "60fps" in label
        assert "MB" in label
        assert "[mp4]" in label


class TestFormatParser:
    """Tests for FormatParser class"""
    
    def test_parse_video_formats_empty(self):
        result = FormatParser.parse_video_formats({})
        assert result == []
    
    def test_parse_video_formats(self):
        info = {
            'formats': [
                {'format_id': '137', 'vcodec': 'avc1', 'acodec': 'none', 'height': 1080, 'ext': 'mp4'},
                {'format_id': '136', 'vcodec': 'avc1', 'acodec': 'none', 'height': 720, 'ext': 'mp4'},
                {'format_id': '140', 'vcodec': 'none', 'acodec': 'mp4a', 'ext': 'm4a'},  # Audio only
            ]
        }
        result = FormatParser.parse_video_formats(info)
        assert len(result) == 2  # Only video formats
        assert result[0][1] == '137'  # Highest quality first
    
    def test_parse_audio_formats(self):
        info = {
            'formats': [
                {'format_id': '137', 'vcodec': 'avc1', 'acodec': 'none', 'height': 1080},
                {'format_id': '140', 'vcodec': 'none', 'acodec': 'mp4a', 'abr': 128, 'ext': 'm4a'},
                {'format_id': '251', 'vcodec': 'none', 'acodec': 'opus', 'abr': 160, 'ext': 'webm'},
            ]
        }
        result = FormatParser.parse_audio_formats(info)
        assert len(result) == 2  # Only audio formats
        assert result[0][1] == '251'  # Highest bitrate first
    
    def test_format_duration(self):
        assert FormatParser.format_duration(None) == "N/A"
        assert FormatParser.format_duration(65) == "1:05"
        assert FormatParser.format_duration(3665) == "1:01:05"
    
    def test_format_view_count(self):
        assert FormatParser.format_view_count(None) == "N/A"
        assert "K" in FormatParser.format_view_count(5000)
        assert "M" in FormatParser.format_view_count(1500000)
    
    def test_format_filesize(self):
        assert FormatParser.format_filesize(None) == "Unknown"
        assert "KB" in FormatParser.format_filesize(2048)
        assert "MB" in FormatParser.format_filesize(5242880)
        assert "GB" in FormatParser.format_filesize(1610612736)


class TestURLParser:
    """Tests for URLParser class"""
    
    def test_parse_youtube_video(self):
        result = URLParser.parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert result.platform == "youtube"
        assert result.url_type == URLType.SINGLE_VIDEO
        assert result.video_id == "dQw4w9WgXcQ"
    
    def test_parse_youtube_short_url(self):
        result = URLParser.parse("https://youtu.be/dQw4w9WgXcQ")
        assert result.video_id == "dQw4w9WgXcQ"
        assert result.url_type == URLType.SINGLE_VIDEO
    
    def test_parse_youtube_playlist(self):
        result = URLParser.parse("https://www.youtube.com/playlist?list=PLtest123abc")
        assert result.url_type == URLType.PLAYLIST
        assert result.playlist_id == "PLtest123abc"
    
    def test_parse_youtube_channel_handle(self):
        result = URLParser.parse("https://www.youtube.com/@TestChannel")
        assert result.url_type == URLType.CHANNEL
        assert result.channel_handle == "TestChannel"
    
    def test_parse_youtube_channel_videos(self):
        result = URLParser.parse("https://www.youtube.com/@TestChannel/videos")
        assert result.url_type == URLType.CHANNEL_VIDEOS
    
    def test_parse_vimeo(self):
        result = URLParser.parse("https://vimeo.com/123456789")
        assert result.platform == "vimeo"
        assert result.video_id == "123456789"
    
    def test_is_valid_video_url(self):
        assert URLParser.is_valid_video_url("https://www.youtube.com/watch?v=test") == True
        assert URLParser.is_valid_video_url("https://vimeo.com/123") == True
        assert URLParser.is_valid_video_url("https://google.com") == False
        assert URLParser.is_valid_video_url("not a url") == False
        assert URLParser.is_valid_video_url(None) == False
    
    def test_extract_from_text(self):
        text = """
        Check out this video: https://www.youtube.com/watch?v=abc123
        Also this one: https://youtu.be/def456
        And my channel: https://www.youtube.com/@MyChannel
        """
        urls = URLParser.extract_from_text(text)
        assert len(urls) == 3
    
    def test_cleaned_url_single_video(self):
        # URL with extra parameters should be cleaned
        result = URLParser.parse("https://www.youtube.com/watch?v=test&list=PLplaylist&index=5")
        # When detected as playlist, the cleaned URL keeps playlist
        # When we want single video, we'd extract video_id only
        assert result.video_id == "test"
    
    def test_cleaned_url_channel(self):
        result = URLParser.parse("https://www.youtube.com/@TestChannel")
        # Should add /videos tab
        assert "/videos" in result.cleaned_url or result.url_type == URLType.CHANNEL


class TestIntegration:
    """Integration tests for combined functionality"""
    
    def test_url_to_download_options(self):
        """Test creating download options from parsed URL"""
        parsed = URLParser.parse("https://www.youtube.com/watch?v=test123")
        
        opts = DownloadOptions(
            url=parsed.cleaned_url,
            download_type="video",
            video_quality="1080p",
        )
        
        assert opts.url == parsed.cleaned_url
        ydl_opts = opts.to_ydl_opts()
        assert 'format' in ydl_opts


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
