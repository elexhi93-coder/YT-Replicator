"""
Event Bus System for IDM-YT
Provides decoupled communication between components using publish/subscribe pattern.
"""

from enum import Enum, auto
from typing import Callable, Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import threading
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """All application events"""
    
    # Application lifecycle
    APP_STARTING = auto()
    APP_READY = auto()
    APP_CLOSING = auto()
    
    # URL/Video events
    URL_DETECTED = auto()
    URL_PASTED = auto()
    VIDEO_FETCH_STARTED = auto()
    VIDEO_FETCH_COMPLETED = auto()
    VIDEO_FETCH_FAILED = auto()
    
    # Playlist events
    PLAYLIST_DETECTED = auto()
    PLAYLIST_LOADED = auto()
    PLAYLIST_ITEM_SELECTED = auto()
    PLAYLIST_SELECTION_CHANGED = auto()
    
    # Download events
    DOWNLOAD_QUEUED = auto()
    DOWNLOAD_STARTED = auto()
    DOWNLOAD_PROGRESS = auto()
    DOWNLOAD_PAUSED = auto()
    DOWNLOAD_RESUMED = auto()
    DOWNLOAD_COMPLETED = auto()
    DOWNLOAD_FAILED = auto()
    DOWNLOAD_CANCELLED = auto()
    
    # Batch download events
    BATCH_STARTED = auto()
    BATCH_PROGRESS = auto()
    BATCH_COMPLETED = auto()
    
    # Settings events
    SETTINGS_CHANGED = auto()
    SETTINGS_SAVED = auto()
    SETTINGS_LOADED = auto()
    
    # Plugin events
    PLUGIN_LOADED = auto()
    PLUGIN_EXECUTED = auto()
    PLUGIN_ERROR = auto()
    
    # UI events
    UI_THEME_CHANGED = auto()
    UI_LOG_MESSAGE = auto()
    UI_STATUS_UPDATE = auto()
    UI_ERROR_DISPLAY = auto()
    
    # Clipboard events
    CLIPBOARD_MONITOR_STARTED = auto()
    CLIPBOARD_MONITOR_STOPPED = auto()
    CLIPBOARD_URL_FOUND = auto()


@dataclass
class Event:
    """Event data container"""
    type: EventType
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: Optional[str] = None
    
    def __repr__(self) -> str:
        return f"Event({self.type.name}, source={self.source}, data={type(self.data).__name__})"


# Type alias for event handlers
EventHandler = Callable[[Event], None]


class EventBus:
    """
    Central event bus for application-wide communication.
    
    Thread-safe publish/subscribe implementation.
    
    Usage:
        # Subscribe to events
        EventBus.subscribe(EventType.DOWNLOAD_STARTED, lambda e: print(f"Started: {e.data}"))
        
        # Publish events
        EventBus.emit(EventType.DOWNLOAD_STARTED, {"url": "...", "title": "..."})
        
        # Unsubscribe
        EventBus.unsubscribe(EventType.DOWNLOAD_STARTED, handler)
    """
    
    _listeners: Dict[EventType, List[EventHandler]] = {}
    _lock = threading.RLock()
    _history: List[Event] = []
    _history_max_size: int = 100
    _enabled: bool = True
    
    @classmethod
    def subscribe(cls, event_type: EventType, handler: EventHandler) -> None:
        """
        Subscribe to an event type.
        
        Args:
            event_type: The event type to listen for
            handler: Callback function that receives Event objects
        """
        with cls._lock:
            if event_type not in cls._listeners:
                cls._listeners[event_type] = []
            if handler not in cls._listeners[event_type]:
                cls._listeners[event_type].append(handler)
                logger.debug(f"Subscribed handler to {event_type.name}")
    
    @classmethod
    def unsubscribe(cls, event_type: EventType, handler: EventHandler) -> bool:
        """
        Unsubscribe from an event type.
        
        Returns:
            True if handler was removed, False if not found
        """
        with cls._lock:
            if event_type in cls._listeners and handler in cls._listeners[event_type]:
                cls._listeners[event_type].remove(handler)
                logger.debug(f"Unsubscribed handler from {event_type.name}")
                return True
            return False
    
    @classmethod
    def emit(cls, event_type: EventType, data: Any = None, source: Optional[str] = None) -> Event:
        """
        Emit an event to all subscribers.
        
        Args:
            event_type: The type of event to emit
            data: Optional data payload
            source: Optional source identifier
            
        Returns:
            The emitted Event object
        """
        event = Event(type=event_type, data=data, source=source)
        
        if not cls._enabled:
            return event
        
        with cls._lock:
            # Add to history
            cls._history.append(event)
            if len(cls._history) > cls._history_max_size:
                cls._history.pop(0)
            
            handlers = cls._listeners.get(event_type, []).copy()
        
        # Call handlers outside lock to prevent deadlocks
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in event handler for {event_type.name}: {e}")
        
        logger.debug(f"Emitted {event_type.name} to {len(handlers)} handlers")
        return event
    
    @classmethod
    def emit_async(cls, event_type: EventType, data: Any = None, source: Optional[str] = None) -> Event:
        """
        Emit an event asynchronously (handlers run in separate thread).
        
        Use for events where handlers might be slow.
        """
        event = Event(type=event_type, data=data, source=source)
        
        if not cls._enabled:
            return event
        
        def dispatch():
            with cls._lock:
                handlers = cls._listeners.get(event_type, []).copy()
            
            for handler in handlers:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"Async handler error for {event_type.name}: {e}")
        
        thread = threading.Thread(target=dispatch, daemon=True)
        thread.start()
        return event
    
    @classmethod
    def clear(cls, event_type: Optional[EventType] = None) -> None:
        """
        Clear subscribers for a specific event type or all events.
        """
        with cls._lock:
            if event_type:
                cls._listeners.pop(event_type, None)
            else:
                cls._listeners.clear()
    
    @classmethod
    def get_history(cls, event_type: Optional[EventType] = None, limit: int = 10) -> List[Event]:
        """
        Get recent event history.
        
        Args:
            event_type: Filter by event type (None for all)
            limit: Maximum number of events to return
        """
        with cls._lock:
            if event_type:
                events = [e for e in cls._history if e.type == event_type]
            else:
                events = cls._history.copy()
            return events[-limit:]
    
    @classmethod
    def set_enabled(cls, enabled: bool) -> None:
        """Enable or disable the event bus."""
        cls._enabled = enabled
    
    @classmethod
    def subscriber_count(cls, event_type: EventType) -> int:
        """Get number of subscribers for an event type."""
        with cls._lock:
            return len(cls._listeners.get(event_type, []))


# Convenience decorators
def on_event(event_type: EventType):
    """
    Decorator to subscribe a function to an event.
    
    Usage:
        @on_event(EventType.DOWNLOAD_COMPLETED)
        def handle_download_complete(event: Event):
            print(f"Download done: {event.data}")
    """
    def decorator(func: EventHandler) -> EventHandler:
        EventBus.subscribe(event_type, func)
        return func
    return decorator


def emit(event_type: EventType, data: Any = None, source: str = None) -> Event:
    """Shorthand for EventBus.emit()"""
    return EventBus.emit(event_type, data, source)


# Event data classes for type safety
@dataclass
class DownloadProgressData:
    """Data for DOWNLOAD_PROGRESS events"""
    url: str
    title: str
    percent: float
    downloaded_bytes: int
    total_bytes: Optional[int]
    speed: Optional[float]
    eta: Optional[int]
    filename: Optional[str] = None


@dataclass
class DownloadCompletedData:
    """Data for DOWNLOAD_COMPLETED events"""
    url: str
    title: str
    output_path: str
    duration_seconds: float
    file_size: int


@dataclass
class DownloadFailedData:
    """Data for DOWNLOAD_FAILED events"""
    url: str
    title: Optional[str]
    error_message: str
    error_category: str
    recoverable: bool


@dataclass
class VideoFetchedData:
    """Data for VIDEO_FETCH_COMPLETED events"""
    url: str
    title: str
    duration: int
    uploader: str
    view_count: int
    thumbnail_url: Optional[str]
    formats: List[dict]
    is_playlist: bool
    playlist_count: Optional[int] = None


@dataclass
class LogMessageData:
    """Data for UI_LOG_MESSAGE events"""
    message: str
    level: str = "info"  # info, warning, error, success
    timestamp: datetime = field(default_factory=datetime.now)
