"""
State Machine for Download Operations in IDM-YT
Provides clean state transitions with validation and hooks.
"""

from enum import Enum, auto
from typing import Callable, Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
import threading
import logging

from .events import EventBus, EventType

logger = logging.getLogger(__name__)


class DownloadState(Enum):
    """Possible states for a download operation"""
    IDLE = auto()           # No download active
    FETCHING = auto()       # Fetching video info
    READY = auto()          # Info fetched, ready to download
    QUEUED = auto()         # Added to download queue
    DOWNLOADING = auto()    # Currently downloading
    PAUSED = auto()         # Download paused
    PROCESSING = auto()     # Post-processing (FFmpeg, etc.)
    COMPLETED = auto()      # Download finished successfully
    FAILED = auto()         # Download failed
    CANCELLED = auto()      # Download cancelled by user


@dataclass
class StateTransition:
    """Represents a valid state transition"""
    from_state: DownloadState
    to_state: DownloadState
    trigger: str
    condition: Optional[Callable[[], bool]] = None
    before: Optional[Callable[[], None]] = None
    after: Optional[Callable[[], None]] = None


@dataclass
class StateContext:
    """Context data associated with current state"""
    url: Optional[str] = None
    title: Optional[str] = None
    progress: float = 0.0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class StateMachineError(Exception):
    """Raised when an invalid state transition is attempted"""
    pass


class DownloadStateMachine:
    """
    Finite State Machine for download operations.
    
    Ensures valid state transitions and provides hooks for state changes.
    
    Usage:
        fsm = DownloadStateMachine()
        
        # Add state change listener
        fsm.on_state_change(lambda old, new, ctx: print(f"{old} -> {new}"))
        
        # Trigger transitions
        fsm.fetch()      # IDLE -> FETCHING
        fsm.fetched()    # FETCHING -> READY
        fsm.start()      # READY -> DOWNLOADING
        fsm.pause()      # DOWNLOADING -> PAUSED
        fsm.resume()     # PAUSED -> DOWNLOADING
        fsm.complete()   # DOWNLOADING -> COMPLETED
        
        # Check state
        if fsm.can_start():
            fsm.start()
    """
    
    # Define valid transitions
    TRANSITIONS: List[StateTransition] = [
        # From IDLE
        StateTransition(DownloadState.IDLE, DownloadState.FETCHING, "fetch"),
        
        # From FETCHING
        StateTransition(DownloadState.FETCHING, DownloadState.READY, "fetched"),
        StateTransition(DownloadState.FETCHING, DownloadState.FAILED, "fail"),
        StateTransition(DownloadState.FETCHING, DownloadState.CANCELLED, "cancel"),
        
        # From READY
        StateTransition(DownloadState.READY, DownloadState.QUEUED, "queue"),
        StateTransition(DownloadState.READY, DownloadState.DOWNLOADING, "start"),
        StateTransition(DownloadState.READY, DownloadState.IDLE, "reset"),
        
        # From QUEUED
        StateTransition(DownloadState.QUEUED, DownloadState.DOWNLOADING, "start"),
        StateTransition(DownloadState.QUEUED, DownloadState.CANCELLED, "cancel"),
        StateTransition(DownloadState.QUEUED, DownloadState.IDLE, "reset"),
        
        # From DOWNLOADING
        StateTransition(DownloadState.DOWNLOADING, DownloadState.PAUSED, "pause"),
        StateTransition(DownloadState.DOWNLOADING, DownloadState.PROCESSING, "process"),
        StateTransition(DownloadState.DOWNLOADING, DownloadState.COMPLETED, "complete"),
        StateTransition(DownloadState.DOWNLOADING, DownloadState.FAILED, "fail"),
        StateTransition(DownloadState.DOWNLOADING, DownloadState.CANCELLED, "cancel"),
        
        # From PAUSED
        StateTransition(DownloadState.PAUSED, DownloadState.DOWNLOADING, "resume"),
        StateTransition(DownloadState.PAUSED, DownloadState.CANCELLED, "cancel"),
        StateTransition(DownloadState.PAUSED, DownloadState.IDLE, "reset"),
        
        # From PROCESSING
        StateTransition(DownloadState.PROCESSING, DownloadState.COMPLETED, "complete"),
        StateTransition(DownloadState.PROCESSING, DownloadState.FAILED, "fail"),
        
        # From terminal states (COMPLETED, FAILED, CANCELLED)
        StateTransition(DownloadState.COMPLETED, DownloadState.IDLE, "reset"),
        StateTransition(DownloadState.FAILED, DownloadState.IDLE, "reset"),
        StateTransition(DownloadState.FAILED, DownloadState.FETCHING, "retry"),
        StateTransition(DownloadState.CANCELLED, DownloadState.IDLE, "reset"),
    ]
    
    def __init__(self, initial_state: DownloadState = DownloadState.IDLE):
        self._state = initial_state
        self._context = StateContext()
        self._listeners: List[Callable[[DownloadState, DownloadState, StateContext], None]] = []
        self._lock = threading.RLock()
        self._transition_map = self._build_transition_map()
        
    def _build_transition_map(self) -> Dict[str, Dict[DownloadState, StateTransition]]:
        """Build lookup map for transitions by trigger name"""
        result: Dict[str, Dict[DownloadState, StateTransition]] = {}
        for t in self.TRANSITIONS:
            if t.trigger not in result:
                result[t.trigger] = {}
            result[t.trigger][t.from_state] = t
        return result
    
    @property
    def state(self) -> DownloadState:
        """Current state"""
        with self._lock:
            return self._state
    
    @property
    def context(self) -> StateContext:
        """Current context"""
        with self._lock:
            return self._context
    
    def on_state_change(self, callback: Callable[[DownloadState, DownloadState, StateContext], None]) -> None:
        """Register a state change listener"""
        self._listeners.append(callback)
    
    def _trigger(self, trigger_name: str, **context_updates) -> bool:
        """
        Attempt a state transition.
        
        Returns:
            True if transition succeeded, False otherwise
        """
        with self._lock:
            transitions = self._transition_map.get(trigger_name, {})
            transition = transitions.get(self._state)
            
            if not transition:
                logger.warning(f"Invalid transition: {trigger_name} from {self._state.name}")
                return False
            
            # Check condition if present
            if transition.condition and not transition.condition():
                logger.debug(f"Transition condition failed: {trigger_name}")
                return False
            
            old_state = self._state
            
            # Execute before hook
            if transition.before:
                try:
                    transition.before()
                except Exception as e:
                    logger.error(f"Before hook failed: {e}")
            
            # Update state
            self._state = transition.to_state
            
            # Update context
            for key, value in context_updates.items():
                if hasattr(self._context, key):
                    setattr(self._context, key, value)
                else:
                    self._context.extra[key] = value
            
            # Track timing
            if self._state == DownloadState.DOWNLOADING:
                self._context.started_at = datetime.now()
            elif self._state in (DownloadState.COMPLETED, DownloadState.FAILED, DownloadState.CANCELLED):
                self._context.completed_at = datetime.now()
            
            # Execute after hook
            if transition.after:
                try:
                    transition.after()
                except Exception as e:
                    logger.error(f"After hook failed: {e}")
            
            logger.debug(f"State transition: {old_state.name} -> {self._state.name}")
        
        # Notify listeners outside lock
        for listener in self._listeners:
            try:
                listener(old_state, self._state, self._context)
            except Exception as e:
                logger.error(f"State change listener error: {e}")
        
        # Emit event
        self._emit_state_event(old_state, self._state)
        
        return True
    
    def _emit_state_event(self, old_state: DownloadState, new_state: DownloadState) -> None:
        """Emit appropriate event for state change"""
        event_map = {
            DownloadState.FETCHING: EventType.VIDEO_FETCH_STARTED,
            DownloadState.READY: EventType.VIDEO_FETCH_COMPLETED,
            DownloadState.DOWNLOADING: EventType.DOWNLOAD_STARTED,
            DownloadState.PAUSED: EventType.DOWNLOAD_PAUSED,
            DownloadState.COMPLETED: EventType.DOWNLOAD_COMPLETED,
            DownloadState.FAILED: EventType.DOWNLOAD_FAILED,
            DownloadState.CANCELLED: EventType.DOWNLOAD_CANCELLED,
        }
        
        if new_state in event_map:
            EventBus.emit(
                event_map[new_state],
                data={
                    "url": self._context.url,
                    "title": self._context.title,
                    "old_state": old_state.name,
                    "new_state": new_state.name,
                },
                source="DownloadStateMachine"
            )
    
    # Transition methods
    def fetch(self, url: str = None) -> bool:
        """Start fetching video info: IDLE -> FETCHING"""
        return self._trigger("fetch", url=url)
    
    def fetched(self, title: str = None) -> bool:
        """Video info fetched: FETCHING -> READY"""
        return self._trigger("fetched", title=title)
    
    def queue(self) -> bool:
        """Add to download queue: READY -> QUEUED"""
        return self._trigger("queue")
    
    def start(self) -> bool:
        """Start downloading: READY/QUEUED -> DOWNLOADING"""
        return self._trigger("start")
    
    def pause(self) -> bool:
        """Pause download: DOWNLOADING -> PAUSED"""
        return self._trigger("pause")
    
    def resume(self) -> bool:
        """Resume download: PAUSED -> DOWNLOADING"""
        return self._trigger("resume")
    
    def process(self) -> bool:
        """Start post-processing: DOWNLOADING -> PROCESSING"""
        return self._trigger("process")
    
    def complete(self) -> bool:
        """Download completed: DOWNLOADING/PROCESSING -> COMPLETED"""
        return self._trigger("complete")
    
    def fail(self, error_message: str = None) -> bool:
        """Download failed: * -> FAILED"""
        return self._trigger("fail", error_message=error_message)
    
    def cancel(self) -> bool:
        """Cancel download: * -> CANCELLED"""
        return self._trigger("cancel")
    
    def retry(self) -> bool:
        """Retry failed download: FAILED -> FETCHING"""
        return self._trigger("retry")
    
    def reset(self) -> bool:
        """Reset to idle: * -> IDLE"""
        result = self._trigger("reset")
        if result:
            self._context = StateContext()
        return result
    
    # Query methods
    def can_fetch(self) -> bool:
        return "fetch" in self._transition_map and self._state in self._transition_map["fetch"]
    
    def can_start(self) -> bool:
        return "start" in self._transition_map and self._state in self._transition_map["start"]
    
    def can_pause(self) -> bool:
        return "pause" in self._transition_map and self._state in self._transition_map["pause"]
    
    def can_resume(self) -> bool:
        return "resume" in self._transition_map and self._state in self._transition_map["resume"]
    
    def can_cancel(self) -> bool:
        return "cancel" in self._transition_map and self._state in self._transition_map["cancel"]
    
    def is_active(self) -> bool:
        """Check if a download is in progress"""
        return self._state in (
            DownloadState.FETCHING,
            DownloadState.DOWNLOADING,
            DownloadState.PROCESSING,
        )
    
    def is_terminal(self) -> bool:
        """Check if in a terminal state"""
        return self._state in (
            DownloadState.COMPLETED,
            DownloadState.FAILED,
            DownloadState.CANCELLED,
        )
    
    def update_progress(self, progress: float) -> None:
        """Update download progress (does not change state)"""
        with self._lock:
            self._context.progress = progress
        
        EventBus.emit(
            EventType.DOWNLOAD_PROGRESS,
            data={"progress": progress, "url": self._context.url},
            source="DownloadStateMachine"
        )


class MultiDownloadStateMachine:
    """
    Manages multiple download state machines for batch/parallel downloads.
    """
    
    def __init__(self):
        self._machines: Dict[str, DownloadStateMachine] = {}
        self._lock = threading.RLock()
    
    def get_or_create(self, download_id: str) -> DownloadStateMachine:
        """Get or create a state machine for a download"""
        with self._lock:
            if download_id not in self._machines:
                self._machines[download_id] = DownloadStateMachine()
            return self._machines[download_id]
    
    def get(self, download_id: str) -> Optional[DownloadStateMachine]:
        """Get state machine by ID"""
        with self._lock:
            return self._machines.get(download_id)
    
    def remove(self, download_id: str) -> bool:
        """Remove a state machine"""
        with self._lock:
            if download_id in self._machines:
                del self._machines[download_id]
                return True
            return False
    
    def get_by_state(self, state: DownloadState) -> List[str]:
        """Get all download IDs in a specific state"""
        with self._lock:
            return [
                did for did, fsm in self._machines.items()
                if fsm.state == state
            ]
    
    def active_count(self) -> int:
        """Count active downloads"""
        with self._lock:
            return sum(1 for fsm in self._machines.values() if fsm.is_active())
    
    def cancel_all(self) -> int:
        """Cancel all active downloads, returns count"""
        count = 0
        with self._lock:
            for fsm in self._machines.values():
                if fsm.can_cancel():
                    fsm.cancel()
                    count += 1
        return count
    
    def clear_completed(self) -> int:
        """Remove all terminal state machines, returns count"""
        with self._lock:
            to_remove = [
                did for did, fsm in self._machines.items()
                if fsm.is_terminal()
            ]
            for did in to_remove:
                del self._machines[did]
            return len(to_remove)
