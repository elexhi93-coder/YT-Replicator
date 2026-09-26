"""
Logging Configuration for IDM-YT
Provides structured logging with file and console handlers.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import threading


class LogLevel(Enum):
    """Log level enumeration"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


@dataclass
class LogConfig:
    """Configuration for logging"""
    # Log levels
    console_level: LogLevel = LogLevel.INFO
    file_level: LogLevel = LogLevel.DEBUG
    
    # File settings
    log_to_file: bool = True
    log_dir: Path = field(default_factory=lambda: Path.home() / ".idm-yt" / "logs")
    log_filename: str = "idm-yt.log"
    max_file_size_mb: int = 10
    backup_count: int = 5
    
    # Format settings
    console_format: str = "[%(levelname)s] %(message)s"
    file_format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    
    # GUI integration
    gui_callback: Optional[Callable[[str], None]] = None


class GUILogHandler(logging.Handler):
    """Custom handler that sends logs to a GUI callback"""
    
    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self.callback = callback
        self._lock = threading.Lock()
    
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            with self._lock:
                self.callback(msg)
        except Exception:
            self.handleError(record)


class IDMLogger:
    """
    Central logging manager for IDM-YT application.
    
    Usage:
        # Basic setup
        logger = IDMLogger.setup()
        logger.info("Application started")
        
        # With GUI integration
        def update_log_widget(message: str):
            log_text.insert(tk.END, message + "\\n")
        
        config = LogConfig(gui_callback=update_log_widget)
        logger = IDMLogger.setup(config)
    """
    
    _instance: Optional['IDMLogger'] = None
    _logger: Optional[logging.Logger] = None
    
    def __init__(self, config: Optional[LogConfig] = None):
        self.config = config or LogConfig()
        self._setup_logging()
    
    @classmethod
    def setup(cls, config: Optional[LogConfig] = None) -> logging.Logger:
        """
        Set up and return the application logger.
        
        Args:
            config: Optional logging configuration
            
        Returns:
            Configured logger instance
        """
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance.get_logger()
    
    @classmethod
    def get(cls, name: Optional[str] = None) -> logging.Logger:
        """
        Get a logger instance.
        
        Args:
            name: Logger name (uses 'idm-yt' if None)
            
        Returns:
            Logger instance
        """
        if cls._logger is None:
            cls.setup()
        
        if name:
            return logging.getLogger(f"idm-yt.{name}")
        return cls._logger
    
    def get_logger(self) -> logging.Logger:
        """Get the main logger instance"""
        return self._logger
    
    def _setup_logging(self):
        """Configure logging handlers and formatters"""
        # Create main logger
        self._logger = logging.getLogger("idm-yt")
        self._logger.setLevel(logging.DEBUG)  # Capture all, filter at handler level
        
        # Clear existing handlers
        self._logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.config.console_level.value)
        console_formatter = logging.Formatter(
            self.config.console_format,
            datefmt=self.config.date_format
        )
        console_handler.setFormatter(console_formatter)
        self._logger.addHandler(console_handler)
        
        # File handler
        if self.config.log_to_file:
            self._setup_file_handler()
        
        # GUI handler
        if self.config.gui_callback:
            self._setup_gui_handler()
        
        # Store in class
        IDMLogger._logger = self._logger
    
    def _setup_file_handler(self):
        """Set up rotating file handler"""
        from logging.handlers import RotatingFileHandler
        
        # Ensure log directory exists
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = self.config.log_dir / self.config.log_filename
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=self.config.max_file_size_mb * 1024 * 1024,
            backupCount=self.config.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(self.config.file_level.value)
        
        file_formatter = logging.Formatter(
            self.config.file_format,
            datefmt=self.config.date_format
        )
        file_handler.setFormatter(file_formatter)
        
        self._logger.addHandler(file_handler)
    
    def _setup_gui_handler(self):
        """Set up GUI callback handler"""
        gui_handler = GUILogHandler(self.config.gui_callback)
        gui_handler.setLevel(self.config.console_level.value)
        
        # Simple format for GUI
        gui_formatter = logging.Formatter(
            "[%(asctime)s] %(message)s",
            datefmt="%H:%M:%S"
        )
        gui_handler.setFormatter(gui_formatter)
        
        self._logger.addHandler(gui_handler)
    
    def add_gui_handler(self, callback: Callable[[str], None]):
        """
        Add a GUI handler after initial setup.
        
        Args:
            callback: Function to receive log messages
        """
        self.config.gui_callback = callback
        self._setup_gui_handler()


# Convenience functions for quick logging
def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance"""
    return IDMLogger.get(name)


def debug(msg: str, *args, **kwargs):
    """Log debug message"""
    IDMLogger.get().debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs):
    """Log info message"""
    IDMLogger.get().info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    """Log warning message"""
    IDMLogger.get().warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    """Log error message"""
    IDMLogger.get().error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs):
    """Log critical message"""
    IDMLogger.get().critical(msg, *args, **kwargs)


# Type aliases for annotations
Logger = logging.Logger
