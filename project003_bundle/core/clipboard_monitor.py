"""
Clipboard Monitor Component
Watches clipboard for video URLs and notifies via callbacks.
"""

import threading
import time
from typing import Callable, Optional
from dataclasses import dataclass, field

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

from .url_parser import URLParser


@dataclass
class ClipboardMonitorConfig:
    """Configuration for clipboard monitoring"""
    check_interval_ms: int = 1000  # Check every 1 second
    enabled: bool = True
    auto_paste_when_empty: bool = True


class ClipboardMonitor:
    """
    Monitors system clipboard for video URLs.
    
    Usage:
        def on_url_detected(url: str, auto_pasted: bool):
            print(f"Found URL: {url}")
        
        monitor = ClipboardMonitor(
            on_url_detected=on_url_detected,
            get_current_url=lambda: url_entry.get()
        )
        monitor.start()
    """
    
    def __init__(
        self,
        on_url_detected: Callable[[str, bool], None],
        get_current_url: Callable[[], str],
        set_url: Optional[Callable[[str], None]] = None,
        on_status_update: Optional[Callable[[str], None]] = None,
        config: Optional[ClipboardMonitorConfig] = None,
    ):
        """
        Initialize clipboard monitor.
        
        Args:
            on_url_detected: Callback when valid video URL detected. 
                             Args: (url, was_auto_pasted)
            get_current_url: Function to get current URL from input field
            set_url: Optional function to set URL in input field (for auto-paste)
            on_status_update: Optional callback for status messages
            config: Optional configuration
        """
        self.on_url_detected = on_url_detected
        self.get_current_url = get_current_url
        self.set_url = set_url
        self.on_status_update = on_status_update
        self.config = config or ClipboardMonitorConfig()
        
        self._last_clipboard_url: str = ""
        self._enabled = self.config.enabled
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._scheduler: Optional[Callable] = None  # For tkinter's after()
    
    @property
    def enabled(self) -> bool:
        """Check if monitoring is enabled"""
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        """Enable or disable monitoring"""
        self._enabled = value
    
    def start(self, scheduler: Optional[Callable] = None):
        """
        Start monitoring clipboard.
        
        Args:
            scheduler: Optional scheduler function (e.g., root.after for tkinter)
                      If not provided, uses a background thread.
        """
        if not PYPERCLIP_AVAILABLE:
            if self.on_status_update:
                self.on_status_update("Clipboard monitoring unavailable (pyperclip not installed)")
            return
        
        self._running = True
        self._scheduler = scheduler
        
        if scheduler:
            # Use tkinter's after() for thread-safe GUI updates
            self._schedule_check()
        else:
            # Use background thread
            self._thread = threading.Thread(target=self._monitoring_loop, daemon=True)
            self._thread.start()
    
    def stop(self):
        """Stop monitoring clipboard"""
        self._running = False
    
    def _schedule_check(self):
        """Schedule next clipboard check using tkinter's after()"""
        if not self._running:
            return
        
        self._check_clipboard()
        
        if self._scheduler and self._running:
            self._scheduler(self.config.check_interval_ms, self._schedule_check)
    
    def _monitoring_loop(self):
        """Background thread monitoring loop"""
        while self._running:
            self._check_clipboard()
            time.sleep(self.config.check_interval_ms / 1000.0)
    
    def _check_clipboard(self):
        """Check clipboard for new video URLs"""
        if not self._enabled:
            return
        
        try:
            current_clipboard = pyperclip.paste()
            
            # Check if clipboard changed and contains content
            if current_clipboard and current_clipboard != self._last_clipboard_url:
                # Validate as video URL using URLParser
                if URLParser.is_valid_video_url(current_clipboard):
                    self._last_clipboard_url = current_clipboard
                    
                    # Check if we should auto-paste
                    auto_pasted = False
                    current_url = self.get_current_url()
                    
                    if (self.config.auto_paste_when_empty and 
                        self.set_url and 
                        not current_url.strip()):
                        self.set_url(current_clipboard.strip())
                        auto_pasted = True
                    
                    # Notify callback
                    self.on_url_detected(current_clipboard.strip(), auto_pasted)
                    
        except Exception:
            # Silently ignore clipboard errors (common on some systems)
            pass
    
    def get_last_detected_url(self) -> str:
        """Get the last detected video URL"""
        return self._last_clipboard_url
    
    def clear_history(self):
        """Clear the last detected URL (allows re-detection of same URL)"""
        self._last_clipboard_url = ""


class ClipboardURLExtractor:
    """
    Utility class for extracting video URLs from text.
    Useful for parsing multiple URLs from clipboard content.
    """
    
    @staticmethod
    def extract_all(text: str) -> list[str]:
        """
        Extract all video URLs from text content.
        
        Args:
            text: Text that may contain video URLs
            
        Returns:
            List of valid video URLs found
        """
        return URLParser.extract_from_text(text)
    
    @staticmethod
    def extract_first(text: str) -> Optional[str]:
        """
        Extract first video URL from text content.
        
        Args:
            text: Text that may contain video URLs
            
        Returns:
            First valid video URL or None
        """
        urls = URLParser.extract_from_text(text)
        return urls[0] if urls else None
