"""
Format Parser for IDM-YT Video Downloader
Extracts and parses video/audio format information from yt-dlp
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple


@dataclass
class VideoFormat:
    """Represents a single video format option"""
    format_id: str
    extension: str
    height: Optional[int]
    width: Optional[int]
    fps: Optional[int]
    filesize: Optional[int]
    filesize_approx: Optional[int]
    vcodec: Optional[str]
    acodec: Optional[str]
    tbr: Optional[float]  # Total bitrate
    format_note: Optional[str]
    
    @property
    def has_video(self) -> bool:
        """Check if format has video stream"""
        return self.vcodec is not None and self.vcodec != 'none'
    
    @property
    def has_audio(self) -> bool:
        """Check if format has audio stream"""
        return self.acodec is not None and self.acodec != 'none'
    
    @property
    def is_combined(self) -> bool:
        """Check if format has both video and audio"""
        return self.has_video and self.has_audio
    
    @property
    def quality_label(self) -> str:
        """Generate quality label string"""
        parts = []
        
        if self.height:
            parts.append(f"{self.height}p")
        
        if self.fps and self.fps > 30:
            parts.append(f"{self.fps}fps")
        
        if self.format_note:
            parts.append(f"({self.format_note})")
        
        size = self.filesize or self.filesize_approx
        if size:
            size_mb = size / (1024 * 1024)
            if size_mb >= 1024:
                parts.append(f"- {size_mb/1024:.1f}GB")
            else:
                parts.append(f"- {size_mb:.1f}MB")
        
        parts.append(f"[{self.extension}]")
        
        return " ".join(parts)
    
    @classmethod
    def from_dict(cls, fmt: Dict[str, Any]) -> 'VideoFormat':
        """Create VideoFormat from yt-dlp format dict"""
        return cls(
            format_id=fmt.get('format_id', ''),
            extension=fmt.get('ext', 'mp4'),
            height=fmt.get('height'),
            width=fmt.get('width'),
            fps=fmt.get('fps'),
            filesize=fmt.get('filesize'),
            filesize_approx=fmt.get('filesize_approx'),
            vcodec=fmt.get('vcodec'),
            acodec=fmt.get('acodec'),
            tbr=fmt.get('tbr'),
            format_note=fmt.get('format_note'),
        )


@dataclass
class AudioFormat:
    """Represents a single audio format option"""
    format_id: str
    extension: str
    acodec: Optional[str]
    abr: Optional[float]  # Audio bitrate
    asr: Optional[int]  # Audio sample rate
    filesize: Optional[int]
    format_note: Optional[str]
    
    @property
    def quality_label(self) -> str:
        """Generate quality label string"""
        parts = []
        
        if self.abr:
            parts.append(f"{int(self.abr)}kbps")
        
        if self.asr:
            parts.append(f"{self.asr}Hz")
        
        if self.format_note:
            parts.append(f"({self.format_note})")
        
        if self.filesize:
            size_mb = self.filesize / (1024 * 1024)
            parts.append(f"- {size_mb:.1f}MB")
        
        parts.append(f"[{self.extension}]")
        
        return " ".join(parts)
    
    @classmethod
    def from_dict(cls, fmt: Dict[str, Any]) -> 'AudioFormat':
        """Create AudioFormat from yt-dlp format dict"""
        return cls(
            format_id=fmt.get('format_id', ''),
            extension=fmt.get('ext', 'm4a'),
            acodec=fmt.get('acodec'),
            abr=fmt.get('abr'),
            asr=fmt.get('asr'),
            filesize=fmt.get('filesize'),
            format_note=fmt.get('format_note'),
        )


class FormatParser:
    """Parses yt-dlp format information into structured data"""
    
    @staticmethod
    def parse_video_formats(info: Dict[str, Any]) -> List[Tuple[str, str]]:
        """
        Parse video formats from yt-dlp info dict.
        
        Args:
            info: yt-dlp extracted info dictionary
            
        Returns:
            List of tuples: (display_string, format_id)
            Sorted by quality (highest first)
        """
        formats = info.get('formats', [])
        video_formats = []
        
        for fmt in formats:
            # Skip audio-only formats
            if fmt.get('vcodec') == 'none' or fmt.get('vcodec') is None:
                continue
            
            vf = VideoFormat.from_dict(fmt)
            
            # Only include formats with known height
            if vf.height:
                video_formats.append((vf.quality_label, vf.format_id, vf.height))
        
        # Sort by height (descending)
        video_formats.sort(key=lambda x: x[2], reverse=True)
        
        # Remove duplicates based on height (keep best per resolution)
        seen_heights = set()
        unique_formats = []
        for label, fmt_id, height in video_formats:
            if height not in seen_heights:
                seen_heights.add(height)
                unique_formats.append((label, fmt_id))
        
        return unique_formats
    
    @staticmethod
    def parse_audio_formats(info: Dict[str, Any]) -> List[Tuple[str, str]]:
        """
        Parse audio formats from yt-dlp info dict.
        
        Args:
            info: yt-dlp extracted info dictionary
            
        Returns:
            List of tuples: (display_string, format_id)
            Sorted by quality (highest first)
        """
        formats = info.get('formats', [])
        audio_formats = []
        
        for fmt in formats:
            # Only audio-only formats
            if fmt.get('vcodec') != 'none':
                continue
            if fmt.get('acodec') == 'none' or fmt.get('acodec') is None:
                continue
            
            af = AudioFormat.from_dict(fmt)
            abr = af.abr or 0
            audio_formats.append((af.quality_label, af.format_id, abr))
        
        # Sort by bitrate (descending)
        audio_formats.sort(key=lambda x: x[2], reverse=True)
        
        return [(label, fmt_id) for label, fmt_id, _ in audio_formats]
    
    @staticmethod
    def get_best_video_format(info: Dict[str, Any], max_height: Optional[int] = None) -> Optional[str]:
        """
        Get the best video format ID.
        
        Args:
            info: yt-dlp extracted info dictionary
            max_height: Maximum resolution height (e.g., 1080 for 1080p)
            
        Returns:
            Format ID string or None
        """
        formats = FormatParser.parse_video_formats(info)
        
        if not formats:
            return None
        
        if max_height is None:
            return formats[0][1]  # Return best quality
        
        # Find best format within height limit
        for label, fmt_id in formats:
            # Extract height from label
            height_match = re.search(r'(\d+)p', label)
            if height_match:
                height = int(height_match.group(1))
                if height <= max_height:
                    return fmt_id
        
        return formats[-1][1]  # Return lowest if all exceed limit
    
    @staticmethod
    def get_best_audio_format(info: Dict[str, Any]) -> Optional[str]:
        """
        Get the best audio format ID.
        
        Args:
            info: yt-dlp extracted info dictionary
            
        Returns:
            Format ID string or None
        """
        formats = FormatParser.parse_audio_formats(info)
        return formats[0][1] if formats else None
    
    @staticmethod
    def estimate_download_size(info: Dict[str, Any], format_id: str) -> Optional[int]:
        """
        Estimate download size for a given format.
        
        Args:
            info: yt-dlp extracted info dictionary
            format_id: Format ID to check
            
        Returns:
            Estimated size in bytes or None
        """
        for fmt in info.get('formats', []):
            if fmt.get('format_id') == format_id:
                return fmt.get('filesize') or fmt.get('filesize_approx')
        return None
    
    @staticmethod
    def format_duration(seconds: Optional[int]) -> str:
        """
        Format duration in seconds to human-readable string.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Formatted string (e.g., "1:23:45" or "12:34")
        """
        if not seconds:
            return "N/A"
        
        seconds = int(seconds)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"
    
    @staticmethod
    def format_view_count(count: Optional[int]) -> str:
        """
        Format view count to human-readable string.
        
        Args:
            count: View count
            
        Returns:
            Formatted string (e.g., "1.5M views")
        """
        if not count:
            return "N/A"
        
        if count >= 1_000_000_000:
            return f"{count / 1_000_000_000:.1f}B views"
        elif count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M views"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K views"
        return f"{count} views"
    
    @staticmethod
    def format_filesize(size_bytes: Optional[int]) -> str:
        """
        Format file size to human-readable string.
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Formatted string (e.g., "150.5 MB")
        """
        if not size_bytes:
            return "Unknown"
        
        if size_bytes >= 1_073_741_824:  # 1 GB
            return f"{size_bytes / 1_073_741_824:.1f} GB"
        elif size_bytes >= 1_048_576:  # 1 MB
            return f"{size_bytes / 1_048_576:.1f} MB"
        elif size_bytes >= 1_024:  # 1 KB
            return f"{size_bytes / 1_024:.1f} KB"
        return f"{size_bytes} B"
