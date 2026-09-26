"""
Download Queue Manager for IDM-YT
Manages download queue with priority, pause/resume, and persistence.
"""

import threading
import queue
import json
import time
from pathlib import Path
from typing import Optional, Callable, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto
import uuid

from .enums import DownloadStatus, DownloadType
from .config import DownloadOptions
from .exceptions import IDMError, DownloadCancelledError
from .logging_config import get_logger

logger = get_logger("queue")


class QueuePriority(Enum):
    """Priority levels for download queue"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3
    
    def __lt__(self, other: 'QueuePriority') -> bool:
        return self.value < other.value


@dataclass
class QueueItem:
    """Represents an item in the download queue"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    url: str = ""
    title: str = ""
    
    # Status
    status: DownloadStatus = DownloadStatus.PENDING
    priority: QueuePriority = QueuePriority.NORMAL
    
    # Progress
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed: Optional[str] = None
    eta: Optional[str] = None
    
    # Download options
    download_type: str = "video"
    format_id: Optional[str] = None
    output_path: Optional[str] = None
    
    # Metadata
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    # Error info
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def __lt__(self, other: 'QueueItem') -> bool:
        """For priority queue ordering (higher priority first)"""
        return self.priority.value > other.priority.value
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['status'] = self.status.value
        data['priority'] = self.priority.value
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'QueueItem':
        """Create from dictionary"""
        data['status'] = DownloadStatus(data.get('status', 'pending'))
        data['priority'] = QueuePriority(data.get('priority', 1))
        return cls(**data)


@dataclass
class QueueStats:
    """Statistics about the download queue"""
    total: int = 0
    pending: int = 0
    downloading: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    total_bytes_downloaded: int = 0


class DownloadQueue:
    """
    Manages a queue of downloads with priority, pause/resume, and persistence.
    
    Usage:
        queue = DownloadQueue()
        
        # Add items
        item = queue.add("https://youtube.com/watch?v=...", title="My Video")
        
        # Start processing
        queue.start(download_callback=my_download_function)
        
        # Pause/Resume
        queue.pause()
        queue.resume()
        
        # Check status
        stats = queue.get_stats()
    """
    
    def __init__(
        self,
        max_concurrent: int = 1,
        persistence_path: Optional[Path] = None,
        auto_save: bool = True,
    ):
        """
        Initialize download queue.
        
        Args:
            max_concurrent: Maximum concurrent downloads
            persistence_path: Path for queue persistence file
            auto_save: Auto-save queue on changes
        """
        self.max_concurrent = max_concurrent
        self.persistence_path = persistence_path or Path.home() / ".idm-yt" / "queue.json"
        self.auto_save = auto_save
        
        # Queue storage
        self._items: dict[str, QueueItem] = {}  # id -> item
        self._pending_queue: queue.PriorityQueue = queue.PriorityQueue()
        
        # State
        self._running = False
        self._paused = False
        self._active_downloads: set[str] = set()
        
        # Threading
        self._lock = threading.RLock()
        self._workers: list[threading.Thread] = []
        self._stop_event = threading.Event()
        
        # Callbacks
        self._download_callback: Optional[Callable] = None
        self._on_item_update: Optional[Callable[[QueueItem], None]] = None
        self._on_item_complete: Optional[Callable[[QueueItem], None]] = None
        self._on_item_error: Optional[Callable[[QueueItem, str], None]] = None
        
        # Load persisted queue
        self._load()
    
    # ===== Public API =====
    
    def add(
        self,
        url: str,
        title: str = "",
        priority: QueuePriority = QueuePriority.NORMAL,
        download_type: str = "video",
        format_id: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> QueueItem:
        """
        Add a new item to the queue.
        
        Returns:
            The created QueueItem
        """
        item = QueueItem(
            url=url,
            title=title or url,
            priority=priority,
            download_type=download_type,
            format_id=format_id,
            output_path=output_path,
        )
        
        with self._lock:
            self._items[item.id] = item
            self._pending_queue.put(item)
        
        logger.info(f"Added to queue: {title or url} [{item.id}]")
        
        if self.auto_save:
            self._save()
        
        return item
    
    def remove(self, item_id: str) -> bool:
        """Remove an item from the queue"""
        with self._lock:
            if item_id in self._items:
                item = self._items[item_id]
                if item.status == DownloadStatus.DOWNLOADING:
                    logger.warning(f"Cannot remove active download: {item_id}")
                    return False
                
                del self._items[item_id]
                logger.info(f"Removed from queue: {item_id}")
                
                if self.auto_save:
                    self._save()
                return True
        return False
    
    def clear_completed(self) -> int:
        """Remove all completed items from queue"""
        with self._lock:
            to_remove = [
                id for id, item in self._items.items()
                if item.status in (DownloadStatus.COMPLETED, DownloadStatus.CANCELLED)
            ]
            
            for item_id in to_remove:
                del self._items[item_id]
            
            if self.auto_save and to_remove:
                self._save()
            
            return len(to_remove)
    
    def get(self, item_id: str) -> Optional[QueueItem]:
        """Get a queue item by ID"""
        return self._items.get(item_id)
    
    def get_all(self) -> list[QueueItem]:
        """Get all queue items"""
        with self._lock:
            return list(self._items.values())
    
    def get_by_status(self, status: DownloadStatus) -> list[QueueItem]:
        """Get items by status"""
        with self._lock:
            return [item for item in self._items.values() if item.status == status]
    
    def get_stats(self) -> QueueStats:
        """Get queue statistics"""
        with self._lock:
            stats = QueueStats(total=len(self._items))
            
            for item in self._items.values():
                if item.status == DownloadStatus.PENDING:
                    stats.pending += 1
                elif item.status == DownloadStatus.DOWNLOADING:
                    stats.downloading += 1
                elif item.status == DownloadStatus.COMPLETED:
                    stats.completed += 1
                    stats.total_bytes_downloaded += item.downloaded_bytes
                elif item.status == DownloadStatus.FAILED:
                    stats.failed += 1
                elif item.status == DownloadStatus.CANCELLED:
                    stats.cancelled += 1
            
            return stats
    
    def start(
        self,
        download_callback: Callable[[QueueItem], bool],
        on_item_update: Optional[Callable[[QueueItem], None]] = None,
        on_item_complete: Optional[Callable[[QueueItem], None]] = None,
        on_item_error: Optional[Callable[[QueueItem, str], None]] = None,
    ):
        """
        Start processing the queue.
        
        Args:
            download_callback: Function that performs the download.
                              Receives QueueItem, returns True on success.
            on_item_update: Called when item progress updates
            on_item_complete: Called when item completes
            on_item_error: Called when item fails
        """
        if self._running:
            logger.warning("Queue already running")
            return
        
        self._download_callback = download_callback
        self._on_item_update = on_item_update
        self._on_item_complete = on_item_complete
        self._on_item_error = on_item_error
        
        self._running = True
        self._paused = False
        self._stop_event.clear()
        
        # Re-queue pending items
        with self._lock:
            for item in self._items.values():
                if item.status == DownloadStatus.PENDING:
                    self._pending_queue.put(item)
        
        # Start worker threads
        for i in range(self.max_concurrent):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"DownloadWorker-{i}",
                daemon=True,
            )
            self._workers.append(worker)
            worker.start()
        
        logger.info(f"Queue started with {self.max_concurrent} workers")
    
    def stop(self):
        """Stop the queue gracefully"""
        if not self._running:
            return
        
        logger.info("Stopping queue...")
        self._running = False
        self._stop_event.set()
        
        # Wait for workers
        for worker in self._workers:
            worker.join(timeout=5.0)
        
        self._workers.clear()
        self._save()
        logger.info("Queue stopped")
    
    def pause(self):
        """Pause queue processing"""
        self._paused = True
        logger.info("Queue paused")
    
    def resume(self):
        """Resume queue processing"""
        self._paused = False
        logger.info("Queue resumed")
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def is_paused(self) -> bool:
        return self._paused
    
    # ===== Item Updates =====
    
    def update_progress(
        self,
        item_id: str,
        progress: Optional[float] = None,
        downloaded_bytes: Optional[int] = None,
        total_bytes: Optional[int] = None,
        speed: Optional[str] = None,
        eta: Optional[str] = None,
    ):
        """Update item progress"""
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return
            
            if progress is not None:
                item.progress = progress
            if downloaded_bytes is not None:
                item.downloaded_bytes = downloaded_bytes
            if total_bytes is not None:
                item.total_bytes = total_bytes
            if speed is not None:
                item.speed = speed
            if eta is not None:
                item.eta = eta
        
        if self._on_item_update:
            self._on_item_update(item)
    
    def set_status(self, item_id: str, status: DownloadStatus, error: Optional[str] = None):
        """Set item status"""
        with self._lock:
            item = self._items.get(item_id)
            if not item:
                return
            
            item.status = status
            
            if status == DownloadStatus.DOWNLOADING:
                item.started_at = datetime.now().isoformat()
            elif status == DownloadStatus.COMPLETED:
                item.completed_at = datetime.now().isoformat()
                item.progress = 1.0
            elif status == DownloadStatus.FAILED:
                item.error_message = error
        
        if self.auto_save:
            self._save()
    
    def retry(self, item_id: str) -> bool:
        """Retry a failed item"""
        with self._lock:
            item = self._items.get(item_id)
            if not item or item.status not in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
                return False
            
            if item.retry_count >= item.max_retries:
                logger.warning(f"Max retries reached for {item_id}")
                return False
            
            item.status = DownloadStatus.PENDING
            item.retry_count += 1
            item.error_message = None
            item.progress = 0.0
            
            self._pending_queue.put(item)
            logger.info(f"Retrying {item_id} (attempt {item.retry_count})")
            
            return True
    
    # ===== Worker =====
    
    def _worker_loop(self):
        """Worker thread main loop"""
        while self._running and not self._stop_event.is_set():
            # Check if paused
            if self._paused:
                time.sleep(0.5)
                continue
            
            try:
                # Get next item (with timeout so we can check stop flag)
                item = self._pending_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            # Skip if already processed
            if item.status != DownloadStatus.PENDING:
                continue
            
            # Mark as downloading
            with self._lock:
                self._active_downloads.add(item.id)
                item.status = DownloadStatus.DOWNLOADING
                item.started_at = datetime.now().isoformat()
            
            logger.info(f"Starting download: {item.title} [{item.id}]")
            
            try:
                # Call download callback
                if self._download_callback:
                    success = self._download_callback(item)
                    
                    if success:
                        item.status = DownloadStatus.COMPLETED
                        item.completed_at = datetime.now().isoformat()
                        item.progress = 1.0
                        logger.info(f"Completed: {item.title} [{item.id}]")
                        
                        if self._on_item_complete:
                            self._on_item_complete(item)
                    else:
                        item.status = DownloadStatus.FAILED
                        logger.error(f"Failed: {item.title} [{item.id}]")
                        
                        if self._on_item_error:
                            self._on_item_error(item, item.error_message or "Download failed")
            
            except DownloadCancelledError:
                item.status = DownloadStatus.CANCELLED
                logger.info(f"Cancelled: {item.title} [{item.id}]")
            
            except Exception as e:
                item.status = DownloadStatus.FAILED
                item.error_message = str(e)
                logger.error(f"Error downloading {item.id}: {e}")
                
                if self._on_item_error:
                    self._on_item_error(item, str(e))
            
            finally:
                with self._lock:
                    self._active_downloads.discard(item.id)
                
                if self.auto_save:
                    self._save()
    
    # ===== Persistence =====
    
    def _save(self):
        """Save queue to disk"""
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            
            with self._lock:
                data = {
                    'items': [item.to_dict() for item in self._items.values()],
                    'saved_at': datetime.now().isoformat(),
                }
            
            with open(self.persistence_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            
        except Exception as e:
            logger.error(f"Failed to save queue: {e}")
    
    def _load(self):
        """Load queue from disk"""
        if not self.persistence_path.exists():
            return
        
        try:
            with open(self.persistence_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            items_data = data.get('items', [])
            
            with self._lock:
                for item_data in items_data:
                    try:
                        item = QueueItem.from_dict(item_data)
                        # Reset downloading items to pending
                        if item.status == DownloadStatus.DOWNLOADING:
                            item.status = DownloadStatus.PENDING
                        self._items[item.id] = item
                    except Exception as e:
                        logger.warning(f"Failed to load queue item: {e}")
            
            logger.info(f"Loaded {len(self._items)} items from queue")
            
        except Exception as e:
            logger.error(f"Failed to load queue: {e}")
