"""
Application Bootstrap for IDM-YT
Initializes the application with proper dependency injection.
"""

import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Optional
import sys
import logging

from core import (
    AppConfig,
    IDMLogger, LogConfig, LogLevel, get_logger,
    create_app_container, AppContainer, get_container,
    EventBus, EventType,
)
from controllers.main_controller import MainController

logger = get_logger("app")


class IDMApplication:
    """
    Main application class with proper initialization.
    
    This class handles:
    - Dependency injection setup
    - Logger configuration
    - Event bus initialization
    - GUI creation
    - Application lifecycle
    
    Usage:
        app = IDMApplication()
        app.run()
    
    Or for more control:
        app = IDMApplication(configure_logging=False)
        app.configure_logging(level=LogLevel.DEBUG)
        app.initialize()
        app.run()
    """
    
    VERSION = "1.3.0"
    
    def __init__(
        self,
        config_path: Optional[Path] = None,
        configure_logging: bool = True,
    ):
        """
        Initialize the application.
        
        Args:
            config_path: Path to configuration directory
            configure_logging: Whether to auto-configure logging
        """
        self.config_path = config_path or Path.home() / ".idm-yt"
        self.root: Optional[tk.Tk] = None
        self.container: Optional[AppContainer] = None
        self.controller: Optional[MainController] = None
        self._initialized = False
        
        if configure_logging:
            self._configure_logging()
    
    def _configure_logging(self, level: LogLevel = LogLevel.INFO) -> None:
        """Configure application logging"""
        config = LogConfig(
            console_level=level,
            file_level=LogLevel.DEBUG,
            log_to_file=True,
            log_dir=self.config_path / "logs",
        )
        IDMLogger.setup(config)
        logger.info(f"IDM Video Downloader v{self.VERSION} starting...")
    
    def configure_logging(self, level: LogLevel = LogLevel.INFO) -> 'IDMApplication':
        """Configure logging (chainable)"""
        self._configure_logging(level)
        return self
    
    def initialize(self) -> 'IDMApplication':
        """
        Initialize all application components.
        
        Returns:
            Self for chaining
        """
        if self._initialized:
            return self
        
        logger.info("Initializing application components...")
        
        # Create DI container
        self.container = create_app_container(self.config_path)
        
        # Create Tkinter root
        self.root = tk.Tk()
        self.root.title(f"IDM - Video Downloader v{self.VERSION}")
        self.root.geometry("800x700")
        self.root.resizable(True, True)
        
        # Configure container with GUI
        self.container.configure_gui(self.root)
        
        # Create main controller
        self.controller = MainController(self.container)
        
        # Set up global event handlers
        self._setup_event_handlers()
        
        # Emit app starting event
        EventBus.emit(EventType.APP_STARTING, source="IDMApplication")
        
        self._initialized = True
        logger.info("Application initialized")
        
        return self
    
    def _setup_event_handlers(self) -> None:
        """Set up global event handlers"""
        # Log all events in debug mode
        def log_event(event):
            logger.debug(f"Event: {event}")
        
        # Subscribe to key events for logging
        for event_type in [
            EventType.DOWNLOAD_STARTED,
            EventType.DOWNLOAD_COMPLETED,
            EventType.DOWNLOAD_FAILED,
            EventType.VIDEO_FETCH_COMPLETED,
        ]:
            EventBus.subscribe(event_type, log_event)
    
    def create_gui(self) -> 'IDMApplication':
        """
        Create the main GUI.
        
        This can be overridden to use a different GUI implementation.
        
        Returns:
            Self for chaining
        """
        if not self._initialized:
            self.initialize()
        
        # Import here to avoid circular imports
        from video_downloader import VideoDownloader
        
        # Create the main window
        self.main_window = VideoDownloader(self.root)
        
        # Emit app ready event
        EventBus.emit(EventType.APP_READY, source="IDMApplication")
        
        return self
    
    def run(self) -> None:
        """Run the application main loop"""
        if not self._initialized:
            self.initialize()
        
        if not hasattr(self, 'main_window'):
            self.create_gui()
        
        # Center window
        self._center_window()
        
        logger.info("Starting main loop")
        
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            logger.info("Application interrupted by user")
        finally:
            self._cleanup()
    
    def _center_window(self) -> None:
        """Center the main window on screen"""
        if self.root:
            self.root.update_idletasks()
            x = (self.root.winfo_screenwidth() // 2) - (self.root.winfo_width() // 2)
            y = (self.root.winfo_screenheight() // 2) - (self.root.winfo_height() // 2)
            self.root.geometry(f"+{x}+{y}")
    
    def _cleanup(self) -> None:
        """Clean up resources on exit"""
        logger.info("Cleaning up...")
        
        # Emit closing event
        EventBus.emit(EventType.APP_CLOSING, source="IDMApplication")
        
        # Clear event subscriptions
        EventBus.clear()
        
        logger.info("Application closed")


def create_app(**kwargs) -> IDMApplication:
    """
    Factory function to create and configure the application.
    
    Args:
        **kwargs: Arguments passed to IDMApplication
        
    Returns:
        Configured IDMApplication instance
    """
    return IDMApplication(**kwargs).initialize()


def main():
    """Main entry point"""
    app = IDMApplication()
    app.run()


if __name__ == "__main__":
    main()
