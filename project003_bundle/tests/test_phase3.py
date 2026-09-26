"""
Unit Tests for Phase 3 Components
Logging system tests
"""

import pytest
import logging
import tempfile
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging_config import IDMLogger, LogConfig, LogLevel, GUILogHandler, get_logger


class TestLogLevel:
    """Tests for LogLevel enum"""
    
    def test_values(self):
        assert LogLevel.DEBUG.value == logging.DEBUG
        assert LogLevel.INFO.value == logging.INFO
        assert LogLevel.WARNING.value == logging.WARNING
        assert LogLevel.ERROR.value == logging.ERROR
        assert LogLevel.CRITICAL.value == logging.CRITICAL


class TestLogConfig:
    """Tests for LogConfig"""
    
    def test_default_values(self):
        config = LogConfig()
        assert config.console_level == LogLevel.INFO
        assert config.file_level == LogLevel.DEBUG
        assert config.log_to_file == True
        assert config.max_file_size_mb == 10
    
    def test_custom_values(self):
        config = LogConfig(
            console_level=LogLevel.DEBUG,
            log_to_file=False,
            max_file_size_mb=20,
        )
        assert config.console_level == LogLevel.DEBUG
        assert config.log_to_file == False
        assert config.max_file_size_mb == 20
    
    def test_gui_callback(self):
        messages = []
        config = LogConfig(gui_callback=lambda msg: messages.append(msg))
        assert config.gui_callback is not None


class TestGUILogHandler:
    """Tests for GUILogHandler"""
    
    def test_emit(self):
        messages = []
        handler = GUILogHandler(callback=lambda msg: messages.append(msg))
        handler.setFormatter(logging.Formatter("%(message)s"))
        
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        handler.emit(record)
        assert "Test message" in messages


class TestIDMLogger:
    """Tests for IDMLogger"""
    
    def test_setup_returns_logger(self):
        # Reset singleton for testing
        IDMLogger._instance = None
        IDMLogger._logger = None
        
        # Skip file logging to avoid Windows file lock issues
        config = LogConfig(log_to_file=False)
        logger = IDMLogger.setup(config)
        
        assert logger is not None
        assert isinstance(logger, logging.Logger)
    
    def test_get_logger(self):
        IDMLogger._instance = None
        IDMLogger._logger = None
        
        config = LogConfig(log_to_file=False)
        IDMLogger.setup(config)
        
        logger = IDMLogger.get()
        assert logger is not None
        
        # Get named logger
        sub_logger = IDMLogger.get("download")
        assert "download" in sub_logger.name
    
    def test_log_levels(self):
        IDMLogger._instance = None
        IDMLogger._logger = None
        
        messages = []
        config = LogConfig(
            log_to_file=False,
            gui_callback=lambda msg: messages.append(msg),
            console_level=LogLevel.DEBUG,
        )
        
        logger = IDMLogger.setup(config)
        
        # Log at different levels
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        # GUI handler should receive messages
        assert len(messages) >= 4
    
    def test_file_logging(self):
        IDMLogger._instance = None
        IDMLogger._logger = None
        
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            log_dir = Path(tmpdir)
            config = LogConfig(
                log_to_file=True,
                log_dir=log_dir,
                log_filename="test.log",
            )
            
            logger = IDMLogger.setup(config)
            logger.info("Test log message to file")
            
            # Force flush and close handlers
            for handler in logger.handlers[:]:
                handler.flush()
                if hasattr(handler, 'close'):
                    handler.close()
                logger.removeHandler(handler)
            
            log_file = log_dir / "test.log"
            assert log_file.exists()
            
            content = log_file.read_text(encoding='utf-8')
            assert "Test log message to file" in content


class TestGetLogger:
    """Tests for get_logger convenience function"""
    
    def test_get_logger_returns_logger(self):
        IDMLogger._instance = None
        IDMLogger._logger = None
        
        config = LogConfig(log_to_file=False)
        IDMLogger.setup(config)
        
        logger = get_logger()
        assert logger is not None
        assert isinstance(logger, logging.Logger)
    
    def test_get_logger_with_name(self):
        IDMLogger._instance = None
        IDMLogger._logger = None
        
        config = LogConfig(log_to_file=False)
        IDMLogger.setup(config)
        
        logger = get_logger("ui")
        assert "ui" in logger.name


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
