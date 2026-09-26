"""
Enumerations for IDM-YT Video Downloader
Replaces magic strings with type-safe enums
"""

from enum import Enum, auto


class DownloadType(Enum):
    """Types of content that can be downloaded"""
    VIDEO = "video"
    AUDIO = "audio"
    THUMBNAIL = "thumbnail"
    SUBTITLES = "subtitles"
    
    def __str__(self) -> str:
        return self.value
    
    @property
    def display_name(self) -> str:
        """Human-readable display name with emoji"""
        icons = {
            "video": "🎥 Video",
            "audio": "🎵 Audio Only",
            "thumbnail": "🖼️ Thumbnail",
            "subtitles": "💬 Subtitles",
        }
        return icons.get(self.value, self.value)


class VideoQuality(Enum):
    """Video quality presets"""
    BEST = ("best", "Best Available", 0)
    Q4K = ("2160p", "4K (2160p)", 2160)
    Q2K = ("1440p", "2K (1440p)", 1440)
    Q1080P = ("1080p", "Full HD (1080p)", 1080)
    Q720P = ("720p", "HD (720p)", 720)
    Q480P = ("480p", "SD (480p)", 480)
    Q360P = ("360p", "360p", 360)
    Q240P = ("240p", "240p", 240)
    Q144P = ("144p", "144p", 144)
    
    def __init__(self, code: str, display: str, height: int):
        self.code = code
        self.display = display
        self.height = height
    
    def __str__(self) -> str:
        return self.code
    
    @classmethod
    def from_height(cls, height: int) -> 'VideoQuality':
        """Get quality enum from height value"""
        for quality in cls:
            if quality.height == height:
                return quality
        return cls.BEST
    
    @classmethod
    def get_display_list(cls) -> list:
        """Get list of display names for UI dropdown"""
        return [q.display for q in cls]


class AudioQuality(Enum):
    """Audio quality presets"""
    BEST = ("bestaudio", "Best Audio (m4a/webm)", None)
    MP3_BEST = ("bestaudio[ext=m4a]/bestaudio", "MP3 (Best Quality)", "320")
    MP3_320 = ("bestaudio[ext=m4a]/bestaudio", "MP3 (320kbps)", "320")
    MP3_192 = ("bestaudio[ext=m4a]/bestaudio", "MP3 (192kbps)", "192")
    MP3_128 = ("bestaudio[ext=m4a]/bestaudio", "MP3 (128kbps)", "128")
    HIGH = ("bestaudio[abr>=128]", "High Quality (128kbps+)", None)
    MEDIUM = ("bestaudio[abr>=64][abr<128]", "Medium Quality (64-128kbps)", None)
    
    def __init__(self, format_spec: str, display: str, mp3_bitrate: str):
        self.format_spec = format_spec
        self.display = display
        self.mp3_bitrate = mp3_bitrate
    
    def __str__(self) -> str:
        return self.display
    
    @property
    def is_mp3(self) -> bool:
        """Check if this quality requires MP3 conversion"""
        return self.mp3_bitrate is not None
    
    @classmethod
    def get_display_list(cls, ffmpeg_available: bool = True) -> list:
        """Get list of display names for UI dropdown"""
        if ffmpeg_available:
            return [q.display for q in cls]
        else:
            # Without FFmpeg, exclude MP3 options
            return [q.display for q in cls if not q.is_mp3]


class URLType(Enum):
    """Types of URLs that can be processed"""
    SINGLE_VIDEO = auto()
    PLAYLIST = auto()
    CHANNEL = auto()
    CHANNEL_VIDEOS = auto()
    CHANNEL_SHORTS = auto()
    CHANNEL_STREAMS = auto()
    UNKNOWN = auto()
    
    @classmethod
    def detect(cls, url: str) -> 'URLType':
        """Detect URL type from URL string"""
        url_lower = url.lower()
        
        # Channel detection
        if any(p in url_lower for p in ['/@', '/channel/', '/c/', '/user/']):
            if '/shorts' in url_lower:
                return cls.CHANNEL_SHORTS
            elif '/streams' in url_lower:
                return cls.CHANNEL_STREAMS
            elif '/videos' in url_lower:
                return cls.CHANNEL_VIDEOS
            return cls.CHANNEL
        
        # Playlist detection
        if 'list=' in url_lower or '/playlist' in url_lower:
            return cls.PLAYLIST
        
        # Single video (default for valid video URLs)
        if any(p in url_lower for p in ['youtube.com/watch', 'youtu.be/', 'vimeo.com/']):
            return cls.SINGLE_VIDEO
        
        return cls.UNKNOWN
    
    @property
    def is_channel(self) -> bool:
        """Check if this is any type of channel URL"""
        return self in (
            URLType.CHANNEL,
            URLType.CHANNEL_VIDEOS,
            URLType.CHANNEL_SHORTS,
            URLType.CHANNEL_STREAMS,
        )
    
    @property
    def is_collection(self) -> bool:
        """Check if this URL type contains multiple videos"""
        return self.is_channel or self == URLType.PLAYLIST


class DownloadStatus(Enum):
    """Status of a download operation"""
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    
    def __str__(self) -> str:
        return self.value
    
    @property
    def icon(self) -> str:
        """Get status icon for UI display"""
        icons = {
            "pending": "⏳",
            "queued": "📋",
            "downloading": "⬇️",
            "processing": "🔄",
            "completed": "✅",
            "failed": "❌",
            "cancelled": "⏹️",
            "paused": "⏸️",
        }
        return icons.get(self.value, "❓")


class SubtitleFormat(Enum):
    """Subtitle format options"""
    BEST = "best"
    SRT = "srt"
    VTT = "vtt"
    ASS = "ass"
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def get_display_list(cls) -> list:
        return [s.value for s in cls]
