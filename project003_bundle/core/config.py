"""
Configuration management for IDM-YT Video Downloader
Centralizes all configurable settings
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import json
import os


@dataclass
class AppConfig:
    """Application configuration with defaults"""
    
    # Paths
    default_download_path: Path = field(default_factory=lambda: Path.home() / "Downloads")
    ffmpeg_path: Optional[Path] = None
    
    # Clipboard monitoring
    clipboard_enabled: bool = True
    clipboard_poll_interval_ms: int = 1000
    
    # Download settings
    max_retries: int = 5
    base_backoff_sleep: float = 2.0
    max_backoff_sleep: float = 20.0
    socket_timeout: int = 30
    
    # Subtitle settings
    default_subtitle_langs: List[str] = field(default_factory=lambda: ["en", "en-*"])
    include_auto_subtitles: bool = True
    
    # UI settings
    window_width: int = 800
    window_height: int = 700
    show_ffmpeg_warning: bool = True
    
    # Advanced
    parallel_downloads: int = 1
    auto_retry_failed: bool = True
    
    # Filename templates
    filename_templates: List[str] = field(default_factory=lambda: [
        "{title}",
        "{uploader} - {title}",
        "[{upload_date}] {title}",
        "{title} [{resolution}]",
        "{playlist_index}. {title}",
        "[{uploader}] {title} ({id})",
    ])
    default_template: str = "{title}"
    
    def __post_init__(self):
        """Convert string paths to Path objects if needed"""
        if isinstance(self.default_download_path, str):
            self.default_download_path = Path(self.default_download_path)
        if isinstance(self.ffmpeg_path, str):
            self.ffmpeg_path = Path(self.ffmpeg_path)
    
    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> 'AppConfig':
        """Load configuration from JSON file"""
        if config_path is None:
            config_path = cls._get_default_config_path()
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return cls(**data)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Warning: Could not load config: {e}")
        
        return cls()
    
    def save(self, config_path: Optional[Path] = None) -> bool:
        """Save configuration to JSON file"""
        if config_path is None:
            config_path = self._get_default_config_path()
        
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert to serializable dict
            data = {
                'default_download_path': str(self.default_download_path),
                'ffmpeg_path': str(self.ffmpeg_path) if self.ffmpeg_path else None,
                'clipboard_enabled': self.clipboard_enabled,
                'clipboard_poll_interval_ms': self.clipboard_poll_interval_ms,
                'max_retries': self.max_retries,
                'base_backoff_sleep': self.base_backoff_sleep,
                'max_backoff_sleep': self.max_backoff_sleep,
                'socket_timeout': self.socket_timeout,
                'default_subtitle_langs': self.default_subtitle_langs,
                'include_auto_subtitles': self.include_auto_subtitles,
                'window_width': self.window_width,
                'window_height': self.window_height,
                'show_ffmpeg_warning': self.show_ffmpeg_warning,
                'parallel_downloads': self.parallel_downloads,
                'auto_retry_failed': self.auto_retry_failed,
                'filename_templates': self.filename_templates,
                'default_template': self.default_template,
            }
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
            
        except Exception as e:
            print(f"Warning: Could not save config: {e}")
            return False
    
    @staticmethod
    def _get_default_config_path() -> Path:
        """Get default configuration file path"""
        # Use app directory for portability
        app_dir = Path(__file__).parent.parent
        return app_dir / "config.json"


@dataclass
class DownloadOptions:
    """Options for a single download operation"""
    
    url: str
    download_type: str = "video"  # video, audio, thumbnail, subtitles
    
    # Video options
    video_format_id: Optional[str] = None
    video_quality: Optional[str] = None
    
    # Audio options
    audio_format: str = "bestaudio"
    mp3_bitrate: Optional[str] = None  # None = keep original format
    
    # Subtitle options
    subtitle_langs: List[str] = field(default_factory=lambda: ["en"])
    all_subtitles: bool = False
    auto_subtitles: bool = True
    subtitle_format: str = "best"
    
    # Thumbnail options
    convert_thumbnail_jpg: bool = True
    
    # Output options
    output_path: Optional[Path] = None
    filename_template: str = "%(title)s.%(ext)s"
    
    # Behavior
    skip_download: bool = False  # For thumbnail/subtitle only
    
    def to_ydl_opts(self, progress_hook=None) -> dict:
        """Convert to yt-dlp options dictionary"""
        opts = {
            'quiet': False,
            'no_warnings': False,
            'no_check_certificate': True,
        }
        
        # Set output template
        if self.output_path:
            opts['outtmpl'] = str(self.output_path / self.filename_template)
        
        # Add progress hook if provided
        if progress_hook:
            opts['progress_hooks'] = [progress_hook]
        
        # Configure based on download type
        if self.download_type == "thumbnail":
            opts['skip_download'] = True
            opts['writethumbnail'] = True
            if self.convert_thumbnail_jpg:
                opts['convert_thumbnails'] = 'jpg'
                
        elif self.download_type == "subtitles":
            opts['skip_download'] = True
            opts['writesubtitles'] = True
            if self.all_subtitles:
                opts['allsubtitles'] = True
            else:
                opts['subtitleslangs'] = self.subtitle_langs
            if self.auto_subtitles:
                opts['writeautomaticsub'] = True
            if self.subtitle_format != 'best':
                opts['subtitlesformat'] = self.subtitle_format
                
        elif self.download_type == "audio":
            opts['format'] = self.audio_format
            if self.mp3_bitrate:
                opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': self.mp3_bitrate,
                }]
                
        else:  # video
            if self.video_format_id:
                opts['format'] = self.video_format_id
            else:
                opts['format'] = 'best'
        
        return opts
