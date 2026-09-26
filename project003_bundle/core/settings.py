"""
Settings Persistence for IDM-YT
Manages application settings with JSON file persistence.
"""

import json
import os
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum

from .logging_config import get_logger

logger = get_logger("settings")


@dataclass
class WindowSettings:
    """Window geometry and state"""
    width: int = 800
    height: int = 600
    x: Optional[int] = None
    y: Optional[int] = None
    maximized: bool = False


@dataclass
class DownloadSettings:
    """Download-related settings"""
    default_path: str = ""
    default_quality: str = "best"
    default_audio_quality: str = "320k"
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    prefer_mp4: bool = True
    max_concurrent: int = 2
    retry_count: int = 3
    
    def __post_init__(self):
        if not self.default_path:
            # Set default to user's Downloads folder
            self.default_path = str(Path.home() / "Downloads" / "IDM-YT")


@dataclass
class ClipboardSettings:
    """Clipboard monitor settings"""
    enabled: bool = True
    auto_fetch: bool = True
    check_interval: float = 1.0


@dataclass
class UISettings:
    """User interface settings"""
    theme: str = "system"  # "light", "dark", "system"
    show_thumbnails: bool = True
    show_status_bar: bool = True
    confirm_close: bool = True
    minimize_to_tray: bool = False
    auto_clear_completed: bool = False


@dataclass
class PluginSettings:
    """Plugin settings"""
    enabled_plugins: list = field(default_factory=lambda: [
        "metadata",
        "chapters_text",
        "thumbnails_variants",
    ])
    plugin_configs: dict = field(default_factory=dict)


@dataclass 
class AppSettings:
    """
    Complete application settings with persistence.
    
    Usage:
        settings = AppSettings.load()
        settings.download.default_quality = "1080p"
        settings.save()
    """
    window: WindowSettings = field(default_factory=WindowSettings)
    download: DownloadSettings = field(default_factory=DownloadSettings)
    clipboard: ClipboardSettings = field(default_factory=ClipboardSettings)
    ui: UISettings = field(default_factory=UISettings)
    plugins: PluginSettings = field(default_factory=PluginSettings)
    
    # Recent items
    recent_urls: list = field(default_factory=list)
    recent_paths: list = field(default_factory=list)
    
    # Internal metadata
    _version: str = "1.0"
    _last_saved: Optional[str] = None
    _settings_file: str = field(default="", repr=False)
    
    def __post_init__(self):
        if not self._settings_file:
            self._settings_file = str(
                Path.home() / ".idm-yt" / "settings.json"
            )
    
    # ===== Persistence =====
    
    @classmethod
    def load(cls, settings_file: Optional[str] = None) -> 'AppSettings':
        """
        Load settings from file, or create defaults.
        
        Args:
            settings_file: Custom settings file path
            
        Returns:
            AppSettings instance
        """
        path = Path(settings_file) if settings_file else Path.home() / ".idm-yt" / "settings.json"
        
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                settings = cls._from_dict(data)
                settings._settings_file = str(path)
                logger.info(f"Loaded settings from {path}")
                return settings
                
            except Exception as e:
                logger.error(f"Failed to load settings: {e}")
                # Return defaults if load fails
        
        # Create new settings
        settings = cls()
        settings._settings_file = str(path)
        return settings
    
    def save(self) -> bool:
        """
        Save settings to file.
        
        Returns:
            True if successful
        """
        try:
            path = Path(self._settings_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            self._last_saved = datetime.now().isoformat()
            data = self._to_dict()
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved settings to {path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            return False
    
    def reset(self):
        """Reset all settings to defaults"""
        default = AppSettings()
        default._settings_file = self._settings_file
        
        self.window = default.window
        self.download = default.download
        self.clipboard = default.clipboard
        self.ui = default.ui
        self.plugins = default.plugins
        self.recent_urls = []
        self.recent_paths = []
        
        logger.info("Settings reset to defaults")
    
    # ===== Recent Items =====
    
    def add_recent_url(self, url: str, max_items: int = 20):
        """Add URL to recent list"""
        if url in self.recent_urls:
            self.recent_urls.remove(url)
        self.recent_urls.insert(0, url)
        self.recent_urls = self.recent_urls[:max_items]
    
    def add_recent_path(self, path: str, max_items: int = 10):
        """Add path to recent list"""
        if path in self.recent_paths:
            self.recent_paths.remove(path)
        self.recent_paths.insert(0, path)
        self.recent_paths = self.recent_paths[:max_items]
    
    def clear_recent(self):
        """Clear recent items"""
        self.recent_urls = []
        self.recent_paths = []
    
    # ===== Serialization =====
    
    def _to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "version": self._version,
            "last_saved": self._last_saved,
            "window": asdict(self.window),
            "download": asdict(self.download),
            "clipboard": asdict(self.clipboard),
            "ui": asdict(self.ui),
            "plugins": asdict(self.plugins),
            "recent_urls": self.recent_urls,
            "recent_paths": self.recent_paths,
        }
    
    @classmethod
    def _from_dict(cls, data: dict) -> 'AppSettings':
        """Create from dictionary"""
        settings = cls()
        
        # Load window settings
        if 'window' in data:
            settings.window = WindowSettings(**data['window'])
        
        # Load download settings
        if 'download' in data:
            settings.download = DownloadSettings(**data['download'])
        
        # Load clipboard settings
        if 'clipboard' in data:
            settings.clipboard = ClipboardSettings(**data['clipboard'])
        
        # Load UI settings
        if 'ui' in data:
            settings.ui = UISettings(**data['ui'])
        
        # Load plugin settings
        if 'plugins' in data:
            settings.plugins = PluginSettings(**data['plugins'])
        
        # Load recent items
        settings.recent_urls = data.get('recent_urls', [])
        settings.recent_paths = data.get('recent_paths', [])
        
        # Metadata
        settings._version = data.get('version', '1.0')
        settings._last_saved = data.get('last_saved')
        
        return settings


class SettingsManager:
    """
    Singleton manager for application settings.
    
    Usage:
        # Get settings anywhere in the app
        settings = SettingsManager.get()
        
        # Modify and save
        settings.download.default_quality = "1080p"
        SettingsManager.save()
    """
    
    _instance: Optional[AppSettings] = None
    _file_path: Optional[str] = None
    
    @classmethod
    def initialize(cls, settings_file: Optional[str] = None):
        """Initialize settings manager"""
        cls._file_path = settings_file
        cls._instance = AppSettings.load(settings_file)
    
    @classmethod
    def get(cls) -> AppSettings:
        """Get current settings"""
        if cls._instance is None:
            cls._instance = AppSettings.load(cls._file_path)
        return cls._instance
    
    @classmethod
    def save(cls) -> bool:
        """Save current settings"""
        if cls._instance:
            return cls._instance.save()
        return False
    
    @classmethod
    def reset(cls):
        """Reset settings to defaults"""
        if cls._instance:
            cls._instance.reset()
            cls._instance.save()
    
    @classmethod
    def reload(cls):
        """Reload settings from file"""
        cls._instance = AppSettings.load(cls._file_path)
