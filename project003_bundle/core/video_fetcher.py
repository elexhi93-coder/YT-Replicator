"""
Video Info Fetcher Component
Fetches video/playlist information from URLs using yt-dlp.
"""

import threading
from typing import Callable, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import yt_dlp

from .url_parser import URLParser, ParsedURL
from .enums import URLType


class FetchStatus(Enum):
    """Status of a fetch operation"""
    PENDING = "pending"
    FETCHING = "fetching"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class VideoInfo:
    """Parsed video information"""
    video_id: str
    title: str
    duration: Optional[int] = None  # seconds
    uploader: Optional[str] = None
    view_count: Optional[int] = None
    thumbnail_url: Optional[str] = None
    formats: list = field(default_factory=list)
    description: Optional[str] = None
    upload_date: Optional[str] = None
    
    # For playlists
    is_playlist: bool = False
    playlist_title: Optional[str] = None
    playlist_count: Optional[int] = None
    entries: list = field(default_factory=list)
    
    # Raw data for advanced usage
    raw_info: dict = field(default_factory=dict)
    
    @classmethod
    def from_yt_dlp(cls, info: dict) -> 'VideoInfo':
        """Create VideoInfo from yt-dlp extract_info result"""
        is_playlist = info.get('_type') == 'playlist' or 'entries' in info
        
        if is_playlist:
            entries = list(info.get('entries', []) or [])
            return cls(
                video_id=info.get('id', ''),
                title=info.get('title', 'Unknown Playlist'),
                is_playlist=True,
                playlist_title=info.get('title'),
                playlist_count=len(entries),
                entries=entries,
                uploader=info.get('uploader') or info.get('channel'),
                thumbnail_url=info.get('thumbnail'),
                raw_info=info,
            )
        else:
            return cls(
                video_id=info.get('id', ''),
                title=info.get('title', 'Unknown'),
                duration=info.get('duration'),
                uploader=info.get('uploader') or info.get('channel'),
                view_count=info.get('view_count'),
                thumbnail_url=info.get('thumbnail'),
                formats=info.get('formats', []),
                description=info.get('description'),
                upload_date=info.get('upload_date'),
                raw_info=info,
            )


@dataclass
class FetchResult:
    """Result of a fetch operation"""
    status: FetchStatus
    video_info: Optional[VideoInfo] = None
    error_message: Optional[str] = None
    url: str = ""
    url_type: URLType = URLType.UNKNOWN
    
    @property
    def is_success(self) -> bool:
        return self.status == FetchStatus.SUCCESS
    
    @property
    def is_playlist(self) -> bool:
        return self.video_info.is_playlist if self.video_info else False


@dataclass
class FetcherConfig:
    """Configuration for video fetcher"""
    quiet: bool = True
    no_warnings: bool = True
    no_check_certificate: bool = True
    extract_flat: bool = False  # True for fast playlist extraction
    socket_timeout: int = 30
    retries: int = 3
    
    def to_ydl_opts(self, extract_flat: Optional[bool] = None) -> dict:
        """Convert to yt-dlp options dict"""
        return {
            'quiet': self.quiet,
            'no_warnings': self.no_warnings,
            'no_check_certificate': self.no_check_certificate,
            'extract_flat': extract_flat if extract_flat is not None else self.extract_flat,
            'socket_timeout': self.socket_timeout,
            'retries': self.retries,
        }


class VideoInfoFetcher:
    """
    Fetches video information from URLs.
    
    Usage:
        fetcher = VideoInfoFetcher()
        
        # Synchronous
        result = fetcher.fetch("https://youtube.com/watch?v=...")
        if result.is_success:
            print(result.video_info.title)
        
        # Asynchronous with callback
        fetcher.fetch_async(
            url="https://youtube.com/watch?v=...",
            on_complete=lambda result: print(result.video_info.title),
            on_progress=lambda msg: print(msg)
        )
    """
    
    def __init__(self, config: Optional[FetcherConfig] = None):
        """
        Initialize fetcher.
        
        Args:
            config: Optional configuration
        """
        self.config = config or FetcherConfig()
        self._current_thread: Optional[threading.Thread] = None
        self._cancelled = False
    
    def fetch(
        self,
        url: str,
        as_playlist: bool = False,
        extract_flat: bool = False,
    ) -> FetchResult:
        """
        Fetch video information synchronously.
        
        Args:
            url: Video or playlist URL
            as_playlist: Force treating URL as playlist
            extract_flat: Use fast extraction (less info, faster)
            
        Returns:
            FetchResult with video info or error
        """
        self._cancelled = False
        
        # Parse URL to determine type
        parsed_url = URLParser.parse(url)
        
        try:
            ydl_opts = self.config.to_ydl_opts(extract_flat=extract_flat)
            
            # Add playlist extraction option if needed
            if as_playlist or parsed_url.url_type.is_collection:
                ydl_opts['extract_flat'] = 'in_playlist' if extract_flat else False
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if self._cancelled:
                    return FetchResult(
                        status=FetchStatus.CANCELLED,
                        url=url,
                        url_type=parsed_url.url_type
                    )
                
                info = ydl.extract_info(url, download=False)
                
                if info is None:
                    return FetchResult(
                        status=FetchStatus.ERROR,
                        error_message="Failed to extract video information",
                        url=url,
                        url_type=parsed_url.url_type
                    )
                
                video_info = VideoInfo.from_yt_dlp(info)
                
                return FetchResult(
                    status=FetchStatus.SUCCESS,
                    video_info=video_info,
                    url=url,
                    url_type=parsed_url.url_type
                )
                
        except yt_dlp.utils.DownloadError as e:
            return FetchResult(
                status=FetchStatus.ERROR,
                error_message=str(e),
                url=url,
                url_type=parsed_url.url_type
            )
        except Exception as e:
            return FetchResult(
                status=FetchStatus.ERROR,
                error_message=f"Unexpected error: {str(e)}",
                url=url,
                url_type=parsed_url.url_type
            )
    
    def fetch_async(
        self,
        url: str,
        on_complete: Callable[[FetchResult], None],
        on_progress: Optional[Callable[[str], None]] = None,
        as_playlist: bool = False,
        extract_flat: bool = False,
    ) -> threading.Thread:
        """
        Fetch video information asynchronously.
        
        Args:
            url: Video or playlist URL
            on_complete: Callback when fetch completes
            on_progress: Optional progress callback
            as_playlist: Force treating URL as playlist
            extract_flat: Use fast extraction
            
        Returns:
            The thread running the fetch operation
        """
        def fetch_worker():
            if on_progress:
                on_progress("Fetching video information...")
            
            result = self.fetch(url, as_playlist=as_playlist, extract_flat=extract_flat)
            
            if on_progress:
                if result.is_success:
                    on_progress(f"Fetched: {result.video_info.title}")
                else:
                    on_progress(f"Error: {result.error_message}")
            
            on_complete(result)
        
        self._current_thread = threading.Thread(target=fetch_worker, daemon=True)
        self._current_thread.start()
        return self._current_thread
    
    def cancel(self):
        """Cancel current fetch operation"""
        self._cancelled = True
    
    def is_fetching(self) -> bool:
        """Check if a fetch operation is in progress"""
        return (self._current_thread is not None and 
                self._current_thread.is_alive())
    
    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for current fetch to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if fetch completed, False if timeout
        """
        if self._current_thread:
            self._current_thread.join(timeout=timeout)
            return not self._current_thread.is_alive()
        return True


class BatchVideoFetcher:
    """
    Fetches information for multiple videos in parallel.
    Useful for playlist processing.
    """
    
    def __init__(
        self,
        max_workers: int = 4,
        config: Optional[FetcherConfig] = None
    ):
        """
        Initialize batch fetcher.
        
        Args:
            max_workers: Maximum concurrent fetches
            config: Optional configuration
        """
        self.max_workers = max_workers
        self.config = config or FetcherConfig()
    
    def fetch_all(
        self,
        urls: list[str],
        on_each_complete: Optional[Callable[[FetchResult, int], None]] = None,
        on_all_complete: Optional[Callable[[list[FetchResult]], None]] = None,
    ) -> list[FetchResult]:
        """
        Fetch information for multiple URLs.
        
        Args:
            urls: List of URLs to fetch
            on_each_complete: Callback after each fetch (result, index)
            on_all_complete: Callback after all fetches complete
            
        Returns:
            List of FetchResult objects
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        results = [None] * len(urls)
        fetcher = VideoInfoFetcher(config=self.config)
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_index = {
                executor.submit(fetcher.fetch, url): i
                for i, url in enumerate(urls)
            }
            
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = FetchResult(
                        status=FetchStatus.ERROR,
                        error_message=str(e),
                        url=urls[index]
                    )
                
                results[index] = result
                
                if on_each_complete:
                    on_each_complete(result, index)
        
        if on_all_complete:
            on_all_complete(results)
        
        return results
