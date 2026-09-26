"""
Upload Manager - Central manager for upload queue and scheduling.

Handles multi-platform uploads, queue management, and scheduling.
"""

import json
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, List, Set
from enum import Enum, auto
from pathlib import Path
import queue
from datetime import datetime, timedelta

from .base_uploader import (
    BaseUploader,
    VideoMetadata,
    UploadProgress,
    UploadResult,
    UploadStatus,
    PlatformCredentials
)
from .auth_manager import AuthManager, OAuthProvider
from .youtube_uploader import YouTubeUploader
from .dailymotion_uploader import DailymotionUploader
from .tiktok_uploader import TikTokUploader
from .facebook_uploader import FacebookUploader

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Status of an upload job."""
    QUEUED = auto()
    WAITING_SCHEDULE = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    PAUSED = auto()


class Platform(Enum):
    """Supported upload platforms."""
    YOUTUBE = "youtube"
    DAILYMOTION = "dailymotion"
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"


@dataclass
class UploadJob:
    """Represents a single upload job."""
    id: str
    video_path: str
    metadata: VideoMetadata
    platforms: List[Platform]
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    scheduled_time: Optional[float] = None
    priority: int = 0  # Higher = more priority
    
    # Progress tracking
    current_platform: Optional[Platform] = None
    platform_results: Dict[str, UploadResult] = field(default_factory=dict)
    progress: Optional[UploadProgress] = None
    
    # Error tracking
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            'id': self.id,
            'video_path': self.video_path,
            'metadata': self.metadata.to_dict(),
            'platforms': [p.value for p in self.platforms],
            'status': self.status.name,
            'created_at': self.created_at,
            'scheduled_time': self.scheduled_time,
            'priority': self.priority,
            'platform_results': {
                k: {
                    'success': v.success,
                    'video_id': v.video_id,
                    'video_url': v.video_url,
                    'error_message': v.error_message
                }
                for k, v in self.platform_results.items()
            },
            'error_message': self.error_message,
            'retry_count': self.retry_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UploadJob':
        """Create from dictionary."""
        job = cls(
            id=data['id'],
            video_path=data['video_path'],
            metadata=VideoMetadata.from_dict(data['metadata']),
            platforms=[Platform(p) for p in data['platforms']],
            status=JobStatus[data.get('status', 'QUEUED')],
            created_at=data.get('created_at', time.time()),
            scheduled_time=data.get('scheduled_time'),
            priority=data.get('priority', 0),
            error_message=data.get('error_message'),
            retry_count=data.get('retry_count', 0)
        )
        return job
    
    @property
    def is_complete(self) -> bool:
        """Check if all platforms have been processed."""
        return len(self.platform_results) >= len(self.platforms)
    
    @property
    def all_successful(self) -> bool:
        """Check if all platform uploads were successful."""
        if not self.is_complete:
            return False
        return all(r.success for r in self.platform_results.values())
    
    @property
    def any_successful(self) -> bool:
        """Check if any platform upload was successful."""
        return any(r.success for r in self.platform_results.values())


class UploadQueue:
    """Thread-safe upload queue with priority support."""
    
    def __init__(self):
        """Initialize upload queue."""
        self._queue: List[UploadJob] = []
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
    
    def add(self, job: UploadJob):
        """Add a job to the queue."""
        with self._condition:
            self._queue.append(job)
            self._queue.sort(key=lambda j: (-j.priority, j.created_at))
            self._condition.notify()
    
    def get(self, timeout: float = None) -> Optional[UploadJob]:
        """Get next job from queue, blocking if empty."""
        with self._condition:
            while True:
                # Find first job that's ready (not scheduled for future)
                now = time.time()
                for i, job in enumerate(self._queue):
                    if job.status == JobStatus.QUEUED:
                        if job.scheduled_time is None or job.scheduled_time <= now:
                            job.status = JobStatus.IN_PROGRESS
                            return job
                
                # No ready jobs, wait
                if not self._condition.wait(timeout):
                    return None
    
    def peek(self) -> Optional[UploadJob]:
        """Peek at next job without removing."""
        with self._lock:
            for job in self._queue:
                if job.status == JobStatus.QUEUED:
                    return job
            return None
    
    def remove(self, job_id: str) -> bool:
        """Remove a job from the queue."""
        with self._lock:
            for i, job in enumerate(self._queue):
                if job.id == job_id:
                    del self._queue[i]
                    return True
            return False
    
    def get_job(self, job_id: str) -> Optional[UploadJob]:
        """Get a job by ID."""
        with self._lock:
            for job in self._queue:
                if job.id == job_id:
                    return job
            return None
    
    def get_all(self) -> List[UploadJob]:
        """Get all jobs in queue."""
        with self._lock:
            return list(self._queue)
    
    def clear(self):
        """Clear all jobs from queue."""
        with self._lock:
            self._queue.clear()
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)


class UploadManager:
    """Central manager for multi-platform video uploads."""
    
    def __init__(
        self,
        auth_manager: Optional[AuthManager] = None,
        persistence_path: Optional[str] = None,
        max_concurrent: int = 2
    ):
        """
        Initialize upload manager.
        
        Args:
            auth_manager: Authentication manager instance
            persistence_path: Path to persist queue state
            max_concurrent: Maximum concurrent uploads
        """
        self.auth_manager = auth_manager or AuthManager()
        self.persistence_path = Path(persistence_path) if persistence_path else None
        self.max_concurrent = max_concurrent
        
        # Upload queue
        self.queue = UploadQueue()
        self._completed_jobs: List[UploadJob] = []
        
        # Platform uploaders
        self._uploaders: Dict[Platform, BaseUploader] = {}
        
        # Worker threads
        self._workers: List[threading.Thread] = []
        self._running = False
        self._shutdown_event = threading.Event()
        
        # Callbacks
        self._job_callbacks: List[Callable[[UploadJob], None]] = []
        self._progress_callbacks: List[Callable[[UploadJob, UploadProgress], None]] = []
        
        # Load persisted state
        if self.persistence_path:
            self._load_state()
    
    def configure_platform(
        self,
        platform: Platform,
        client_id: str,
        client_secret: str,
        **kwargs
    ):
        """
        Configure a platform for uploads.
        
        Args:
            platform: The platform to configure
            client_id: OAuth client ID
            client_secret: OAuth client secret
            **kwargs: Platform-specific settings
        """
        # Configure auth
        oauth_provider = OAuthProvider[platform.name]
        self.auth_manager.configure_platform(
            oauth_provider,
            client_id,
            client_secret
        )
        
        # Create uploader
        credentials = PlatformCredentials(
            client_id=client_id,
            client_secret=client_secret
        )
        
        if platform == Platform.YOUTUBE:
            self._uploaders[platform] = YouTubeUploader(credentials)
        elif platform == Platform.DAILYMOTION:
            self._uploaders[platform] = DailymotionUploader(credentials)
        elif platform == Platform.TIKTOK:
            self._uploaders[platform] = TikTokUploader(credentials)
        elif platform == Platform.FACEBOOK:
            page_id = kwargs.get('page_id')
            self._uploaders[platform] = FacebookUploader(credentials, page_id)
        
        logger.info(f"Configured {platform.value} for uploads")
    
    def is_platform_configured(self, platform: Platform) -> bool:
        """Check if a platform is configured."""
        return platform in self._uploaders
    
    def is_platform_authenticated(self, platform: Platform) -> bool:
        """Check if a platform is authenticated."""
        oauth_provider = OAuthProvider[platform.name]
        return self.auth_manager.is_authenticated(oauth_provider)
    
    def authenticate_platform(
        self,
        platform: Platform,
        callback: Optional[Callable[[bool], None]] = None
    ) -> bool:
        """
        Start authentication for a platform.
        
        Args:
            platform: The platform to authenticate
            callback: Optional callback when auth completes
            
        Returns:
            True if auth flow started
        """
        oauth_provider = OAuthProvider[platform.name]
        
        def auth_callback(success: bool):
            if success:
                # Update uploader credentials
                token = self.auth_manager.get_access_token(oauth_provider)
                if platform in self._uploaders and token:
                    self._uploaders[platform].credentials.access_token = token
            
            if callback:
                callback(success)
        
        return self.auth_manager.authenticate(oauth_provider, auth_callback)
    
    def add_upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        platforms: List[Platform],
        scheduled_time: Optional[float] = None,
        priority: int = 0
    ) -> UploadJob:
        """
        Add a video to the upload queue.
        
        Args:
            video_path: Path to the video file
            metadata: Video metadata
            platforms: Platforms to upload to
            scheduled_time: Optional scheduled upload time
            priority: Job priority (higher = more priority)
            
        Returns:
            The created upload job
        """
        # Generate job ID
        job_id = f"upload_{int(time.time() * 1000)}_{len(self.queue)}"
        
        job = UploadJob(
            id=job_id,
            video_path=video_path,
            metadata=metadata,
            platforms=platforms,
            scheduled_time=scheduled_time,
            priority=priority
        )
        
        if scheduled_time:
            job.status = JobStatus.WAITING_SCHEDULE
        
        self.queue.add(job)
        self._save_state()
        
        logger.info(f"Added upload job {job_id} for {len(platforms)} platforms")
        
        return job
    
    def cancel_upload(self, job_id: str) -> bool:
        """Cancel an upload job."""
        job = self.queue.get_job(job_id)
        if job:
            if job.status == JobStatus.IN_PROGRESS:
                # Cancel active upload
                if job.current_platform and job.current_platform in self._uploaders:
                    self._uploaders[job.current_platform].cancel()
            
            job.status = JobStatus.CANCELLED
            self._notify_job_change(job)
            self._save_state()
            return True
        return False
    
    def pause_upload(self, job_id: str) -> bool:
        """Pause an upload job."""
        job = self.queue.get_job(job_id)
        if job and job.status == JobStatus.IN_PROGRESS:
            if job.current_platform and job.current_platform in self._uploaders:
                self._uploaders[job.current_platform].pause()
            job.status = JobStatus.PAUSED
            self._notify_job_change(job)
            return True
        return False
    
    def resume_upload(self, job_id: str) -> bool:
        """Resume a paused upload job."""
        job = self.queue.get_job(job_id)
        if job and job.status == JobStatus.PAUSED:
            if job.current_platform and job.current_platform in self._uploaders:
                self._uploaders[job.current_platform].resume()
            job.status = JobStatus.IN_PROGRESS
            self._notify_job_change(job)
            return True
        return False
    
    def retry_upload(self, job_id: str) -> bool:
        """Retry a failed upload job."""
        job = self.queue.get_job(job_id)
        if job and job.status == JobStatus.FAILED:
            job.status = JobStatus.QUEUED
            job.retry_count += 1
            job.error_message = None
            self._notify_job_change(job)
            self._save_state()
            return True
        return False
    
    def get_job(self, job_id: str) -> Optional[UploadJob]:
        """Get a job by ID."""
        job = self.queue.get_job(job_id)
        if not job:
            # Check completed jobs
            for j in self._completed_jobs:
                if j.id == job_id:
                    return j
        return job
    
    def get_all_jobs(self) -> List[UploadJob]:
        """Get all jobs (queued and completed)."""
        return self.queue.get_all() + self._completed_jobs
    
    def get_queued_jobs(self) -> List[UploadJob]:
        """Get all queued jobs."""
        return [j for j in self.queue.get_all() if j.status == JobStatus.QUEUED]
    
    def get_completed_jobs(self) -> List[UploadJob]:
        """Get completed jobs."""
        return self._completed_jobs.copy()
    
    def start(self):
        """Start the upload manager worker threads."""
        if self._running:
            return
        
        self._running = True
        self._shutdown_event.clear()
        
        # Start worker threads
        for i in range(self.max_concurrent):
            worker = threading.Thread(
                target=self._worker_thread,
                name=f"UploadWorker-{i}",
                daemon=True
            )
            worker.start()
            self._workers.append(worker)
        
        logger.info(f"Started {self.max_concurrent} upload workers")
    
    def stop(self, timeout: float = 30.0):
        """Stop the upload manager."""
        if not self._running:
            return
        
        self._running = False
        self._shutdown_event.set()
        
        # Wait for workers to finish
        for worker in self._workers:
            worker.join(timeout / len(self._workers))
        
        self._workers.clear()
        self._save_state()
        
        logger.info("Upload manager stopped")
    
    def on_job_change(self, callback: Callable[[UploadJob], None]):
        """Register callback for job status changes."""
        self._job_callbacks.append(callback)
    
    def on_progress(self, callback: Callable[[UploadJob, UploadProgress], None]):
        """Register callback for upload progress."""
        self._progress_callbacks.append(callback)
    
    def _worker_thread(self):
        """Worker thread for processing uploads."""
        while self._running:
            if self._shutdown_event.is_set():
                break
            
            # Get next job
            job = self.queue.get(timeout=1.0)
            if not job:
                continue
            
            try:
                self._process_job(job)
            except Exception as e:
                logger.exception(f"Error processing job {job.id}")
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                self._notify_job_change(job)
    
    def _process_job(self, job: UploadJob):
        """Process a single upload job."""
        logger.info(f"Processing job {job.id}")
        
        for platform in job.platforms:
            if job.status == JobStatus.CANCELLED:
                break
            
            # Skip if already uploaded to this platform
            if platform.value in job.platform_results:
                continue
            
            job.current_platform = platform
            self._notify_job_change(job)
            
            # Get uploader
            uploader = self._uploaders.get(platform)
            if not uploader:
                result = UploadResult(
                    success=False,
                    platform=platform.value,
                    error_message=f"{platform.value} not configured"
                )
                job.platform_results[platform.value] = result
                continue
            
            # Update credentials from auth manager
            oauth_provider = OAuthProvider[platform.name]
            token = self.auth_manager.get_access_token(oauth_provider)
            if token:
                uploader.credentials.access_token = token
            
            # Progress callback
            def progress_callback(progress: UploadProgress):
                job.progress = progress
                self._notify_progress(job, progress)
            
            # Upload
            try:
                result = uploader.upload(
                    job.video_path,
                    job.metadata,
                    progress_callback
                )
                job.platform_results[platform.value] = result
                
                if not result.success:
                    logger.warning(f"Upload to {platform.value} failed: {result.error_message}")
                else:
                    logger.info(f"Upload to {platform.value} successful: {result.video_url}")
                    
            except Exception as e:
                logger.exception(f"Upload to {platform.value} failed")
                job.platform_results[platform.value] = UploadResult(
                    success=False,
                    platform=platform.value,
                    error_message=str(e)
                )
        
        # Update job status
        if job.status != JobStatus.CANCELLED:
            if job.all_successful:
                job.status = JobStatus.COMPLETED
            elif job.any_successful:
                job.status = JobStatus.COMPLETED  # Partial success
            else:
                if job.retry_count < job.max_retries:
                    job.status = JobStatus.QUEUED
                    job.retry_count += 1
                    job.platform_results.clear()
                    self.queue.add(job)
                else:
                    job.status = JobStatus.FAILED
        
        job.current_platform = None
        job.progress = None
        
        # Move to completed
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            self.queue.remove(job.id)
            self._completed_jobs.append(job)
        
        self._notify_job_change(job)
        self._save_state()
    
    def _notify_job_change(self, job: UploadJob):
        """Notify callbacks of job change."""
        for callback in self._job_callbacks:
            try:
                callback(job)
            except Exception as e:
                logger.error(f"Job callback error: {e}")
    
    def _notify_progress(self, job: UploadJob, progress: UploadProgress):
        """Notify callbacks of progress update."""
        for callback in self._progress_callbacks:
            try:
                callback(job, progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    def _save_state(self):
        """Save queue state to disk."""
        if not self.persistence_path:
            return
        
        try:
            state = {
                'queued': [j.to_dict() for j in self.queue.get_all()],
                'completed': [j.to_dict() for j in self._completed_jobs[-100:]]  # Keep last 100
            }
            
            with open(self.persistence_path, 'w') as f:
                json.dump(state, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def _load_state(self):
        """Load queue state from disk."""
        if not self.persistence_path or not self.persistence_path.exists():
            return
        
        try:
            with open(self.persistence_path, 'r') as f:
                state = json.load(f)
            
            for job_data in state.get('queued', []):
                job = UploadJob.from_dict(job_data)
                if job.status == JobStatus.IN_PROGRESS:
                    job.status = JobStatus.QUEUED  # Reset interrupted jobs
                self.queue.add(job)
            
            for job_data in state.get('completed', []):
                job = UploadJob.from_dict(job_data)
                self._completed_jobs.append(job)
            
            logger.info(f"Loaded {len(self.queue)} queued and {len(self._completed_jobs)} completed jobs")
            
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get upload statistics."""
        all_jobs = self.get_all_jobs()
        
        total_uploads = 0
        successful_uploads = 0
        failed_uploads = 0
        total_upload_time = 0.0
        
        by_platform: Dict[str, Dict[str, int]] = {
            p.value: {'success': 0, 'failed': 0}
            for p in Platform
        }
        
        for job in all_jobs:
            for platform, result in job.platform_results.items():
                total_uploads += 1
                if result.success:
                    successful_uploads += 1
                    by_platform[platform]['success'] += 1
                    total_upload_time += result.upload_time
                else:
                    failed_uploads += 1
                    by_platform[platform]['failed'] += 1
        
        return {
            'total_jobs': len(all_jobs),
            'queued_jobs': len(self.get_queued_jobs()),
            'completed_jobs': len(self._completed_jobs),
            'total_uploads': total_uploads,
            'successful_uploads': successful_uploads,
            'failed_uploads': failed_uploads,
            'success_rate': successful_uploads / total_uploads if total_uploads > 0 else 0,
            'average_upload_time': total_upload_time / successful_uploads if successful_uploads > 0 else 0,
            'by_platform': by_platform
        }
