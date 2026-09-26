#!/usr/bin/env python3
"""
Internet Download Manager (IDM) - Video Downloader
A GUI application for downloading videos from YouTube and other platforms
with multiple resolution options.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import os
import json
import re
from datetime import datetime
import yt_dlp
from pathlib import Path
import sys
import subprocess
from video_window import VideoWindow
from plugin_manager import PluginManager
import shutil
from PIL import Image, ImageTk
from download_library import DownloadLibrary
from channel_monitor import ChannelMonitor

try:
    from n8n_webhook import fire_webhook as _fire_webhook
    _N8N_AVAILABLE = True
except ImportError:
    _N8N_AVAILABLE = False
import urllib.request
import io
import pyperclip  # For clipboard monitoring
import time
import random

# Import refactored core modules
from core import (
    DownloadType, VideoQuality, AudioQuality, URLType, DownloadStatus,
    FormatParser, URLParser,
    ClipboardMonitor, ClipboardMonitorConfig,
    ProgressTracker, ProgressState,
    IDMLogger, LogConfig, LogLevel, get_logger,
)


VERSION = "1.2.0"

# Initialize logger (will be configured with GUI handler in VideoDownloader)
logger = get_logger()


def _find_ffmpeg_on_windows() -> Path | None:
    """Search common Windows install locations for ffmpeg.exe."""
    candidates = [
        Path(os.environ.get('USERPROFILE', '')) / 'AppData' / 'Local' / 'Microsoft' / 'WindowsApps' / 'ffmpeg.exe',
        Path('C:/Program Files/ffmpeg/bin/ffmpeg.exe'),
        Path('C:/Program Files (x86)/ffmpeg/bin/ffmpeg.exe'),
        Path('C:/ffmpeg/bin/ffmpeg.exe'),
        Path('C:/Program Files/Gyan/ffmpeg/bin/ffmpeg.exe'),
        Path('C:/Program Files/ffmpeg/bin/ffmpeg.exe'),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def check_ffmpeg():
    """Check if FFmpeg is installed and available"""
    try:
        # First check if ffmpeg is in the app's folder (portable)
        app_dir = Path(__file__).parent
        portable_ffmpeg = app_dir / "ffmpeg" / "bin" / "ffmpeg.exe"
        
        if portable_ffmpeg.exists():
            ffmpeg_bin_dir = str(portable_ffmpeg.parent)
            if ffmpeg_bin_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = ffmpeg_bin_dir + os.pathsep + os.environ.get('PATH', '')
            return True

        # Check if ffmpeg is in system PATH
        result = subprocess.run(['ffmpeg', '-version'], 
                                capture_output=True, 
                                text=True, 
                                timeout=5)
        if result.returncode == 0:
            return True

        # Try explicit candidate locations on Windows
        if os.name == 'nt':
            candidate = _find_ffmpeg_on_windows()
            if candidate and candidate.exists():
                ffmpeg_bin_dir = str(candidate.parent)
                if ffmpeg_bin_dir not in os.environ.get('PATH', ''):
                    os.environ['PATH'] = ffmpeg_bin_dir + os.pathsep + os.environ.get('PATH', '')
                return True

        return False
    except Exception:
        # Also check using shutil
        if shutil.which('ffmpeg'):
            return True
        if os.name == 'nt':
            candidate = _find_ffmpeg_on_windows()
            return bool(candidate and candidate.exists())
        return False


class VideoDownloader:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"IDM - Video Downloader v{VERSION}")
        self.root.geometry("800x700")
        self.root.resizable(True, True)
        
        # Initialize logging with file support
        self._init_logging()
        logger.info(f"IDM Video Downloader v{VERSION} starting...")
        
        # Initialize variables
        self.download_path: str = str(Path.home() / "Downloads")
        self.video_info: dict | None = None
        self.download_thread: threading.Thread | None = None
        self.ffmpeg_available: bool = check_ffmpeg()
        self.ffmpeg_warning_shown: bool = False  # Track if warning was shown
        
        # Subtitles backoff (Advanced) defaults
        self.subs_backoff_max_attempts = tk.IntVar(value=5)
        self.subs_backoff_base_sleep = tk.DoubleVar(value=2.0)
        self.subs_backoff_max_sleep = tk.DoubleVar(value=20.0)
        self.subs_show_advanced = tk.BooleanVar(value=False)
        
        # Parallel download settings (IDM-style speed boost)
        self.concurrent_fragments = tk.IntVar(value=4)  # Parallel fragment downloads
        self.use_aria2c = tk.BooleanVar(value=False)    # Use aria2c external downloader
        self.aria2c_connections = tk.IntVar(value=16)   # Connections per server for aria2c
        self.aria2c_available = self._check_aria2c()    # Check if aria2c is installed
        
        # Output container format (YouTube Studio compatible)
        self.output_format_var = tk.StringVar(value="mp4")
        # Supported formats: https://support.google.com/youtube/troubleshooter/2888402
        self.output_formats = {
            "MP4 (H.264/AAC) - Recommended": "mp4",
            "MKV (Matroska)": "mkv",
            "WebM (VP9/Opus)": "webm",
            "MOV (QuickTime)": "mov",
            "AVI": "avi",
            "FLV (Flash)": "flv",
            "3GP (Mobile)": "3gp",
        }
        
        # Playlist support
        self.is_playlist: bool = False
        self.playlist_entries: list = []
        self.selected_playlist_items: list = []
        
        # Clipboard monitoring - using new ClipboardMonitor component
        self.clipboard_monitor_enabled = tk.BooleanVar(value=True)
        self.clipboard_monitor: ClipboardMonitor | None = None  # Initialized after GUI

        # Channel monitor — single persistent instance shared across window opens
        self.channel_monitor_instance: ChannelMonitor | None = None
        
        # Initialize plugin system before building the GUI
        self.plugin_manager = PluginManager()
        try:
            self.plugin_manager.discover()
            logger.debug(f"Discovered {len(self.plugin_manager.plugins)} plugins")
        except Exception as e:
            logger.warning(f"Plugin discovery failed: {e}")
        self.plugin_vars: dict = {}

        # Create GUI
        self.create_gui()
        
        # Initialize and start clipboard monitor using new component
        self._init_clipboard_monitor()
        
        # Log FFmpeg status
        if not self.ffmpeg_available:
            logger.info("FFmpeg not detected - MP3 conversion unavailable")
            self.root.after(500, lambda: self.log_message("FFmpeg not detected - Audio will save in original format (webm/m4a). Install FFmpeg for MP3 conversion."))
        else:
            logger.info("FFmpeg detected - MP3 conversion available")
        
        # Configure yt-dlp options
        self.ydl_opts_base: dict = {
            'quiet': False,
            'no_warnings': False,
            'extractaudio': False,
            'outtmpl': os.path.join(self.download_path, '%(title)s.%(ext)s'),
        }
        
        logger.info("Application initialized successfully")

        # Auto-start background channel monitoring if any channels have auto-download enabled
        self.root.after(1500, self._init_channel_background_monitoring)
    
    def _init_logging(self) -> None:
        """Initialize the logging system"""
        global logger
        
        # Configure logging with file output
        config = LogConfig(
            console_level=LogLevel.INFO,
            file_level=LogLevel.DEBUG,
            log_to_file=True,
            log_dir=Path.home() / ".idm-yt" / "logs",
        )
        
        # Setup logger and update global reference
        logger = IDMLogger.setup(config)

    def ydl_download_with_backoff(self, ydl_opts, url, is_subtitles=False, context='single'):
        """Call yt-dlp with exponential backoff when encountering HTTP 429.

        - ydl_opts: options dict for YoutubeDL
        - url: single URL string to download
        - is_subtitles: True if we're downloading subtitles-only (more prone to 429)
        - context: 'single' or 'playlist' for logging context
        """
        if is_subtitles:
            try:
                max_attempts = int(self.subs_backoff_max_attempts.get())
            except Exception:
                max_attempts = 5
            try:
                base_sleep = float(self.subs_backoff_base_sleep.get())
            except Exception:
                base_sleep = (ydl_opts.get('sleep_requests', 1.0) or 1.0)
            try:
                max_cap = float(self.subs_backoff_max_sleep.get())
            except Exception:
                max_cap = 20.0
        else:
            max_attempts = 2
            base_sleep = ydl_opts.get('sleep_requests', 1.0) or 1.0
            max_cap = 20.0
        for attempt in range(max_attempts):
            try:
                # Evaluate any deferred/callable values in options
                ydl_opts_local = dict(ydl_opts)
                for _k in ('retries', 'extractor_retries', 'sleep_requests'):
                    if _k in ydl_opts_local and callable(ydl_opts_local[_k]):
                        try:
                            ydl_opts_local[_k] = ydl_opts_local[_k]()
                        except Exception:
                            pass
                with yt_dlp.YoutubeDL(ydl_opts_local) as ydl:
                    ydl.download([url])
                return
            except Exception as e:
                msg = str(e)
                is_429 = ('HTTP Error 429' in msg) or ('Too Many Requests' in msg)
                if is_subtitles and is_429 and attempt < max_attempts - 1:
                    delay = min(max_cap, base_sleep * (2 ** attempt) * random.uniform(1.0, 1.6))
                    try:
                        self.root.after(0, self.log_message, f"⏳ Rate limited (429). Retrying in {delay:.1f}s... [{context}]")
                    except Exception:
                        pass
                    time.sleep(delay)
                    # Increase per-request sleep for next attempt
                    ydl_opts['sleep_requests'] = min(max_cap / 2.0, max(ydl_opts.get('sleep_requests', 0) or 0, delay / 2.0))
                    continue
                raise
    
    def _check_aria2c(self) -> bool:
        """Check if aria2c is available in PATH"""
        import shutil
        return shutil.which('aria2c') is not None
    
    def _get_parallel_download_opts(self) -> dict:
        """
        Get yt-dlp options for parallel/chunked downloading.
        Similar to IDM's multi-connection download approach.
        """
        opts = {}
        
        # Use concurrent fragment downloads (works for DASH/HLS streams)
        concurrent = self.concurrent_fragments.get()
        if concurrent > 1:
            opts['concurrent_fragment_downloads'] = concurrent
        
        # Use aria2c for even faster downloads if available and enabled
        if self.use_aria2c.get() and self.aria2c_available:
            connections = self.aria2c_connections.get()
            opts['external_downloader'] = 'aria2c'
            opts['external_downloader_args'] = {
                'aria2c': [
                    f'-x{connections}',     # Max connections per server
                    f'-s{connections}',     # Split file into N parts  
                    '-k1M',                 # Min split size 1MB
                    '--file-allocation=none',
                    '--optimize-concurrent-downloads=true',
                ]
            }
        
        return opts
        
    def create_gui(self):
        """Create the main GUI interface"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # URL Input Section - Compact (label, entry, button all in one line)
        url_frame = ttk.Frame(main_frame)
        url_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        url_frame.columnconfigure(1, weight=1)
        
        ttk.Label(url_frame, text="Video URL:", font=('Arial', 10, 'bold')).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 5)
        )
        
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=('Arial', 10))
        self.url_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        
        self.fetch_btn = ttk.Button(url_frame, text="Fetch Info", command=self.fetch_video_info)
        self.fetch_btn.grid(row=0, column=2)
        
        # Video Information Section (collapsible - hidden by default)
        self.info_frame = ttk.LabelFrame(main_frame, text="Video Information", padding="5")
        self.info_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        self.info_frame.columnconfigure(1, weight=1)
        self.info_frame.grid_remove()  # Hide by default until video is fetched
        
        # Create a frame to hold thumbnail and text info side by side
        info_content_frame = ttk.Frame(self.info_frame)
        info_content_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N))
        info_content_frame.columnconfigure(1, weight=1)
        
        # Thumbnail display (left side)
        self.thumbnail_label = ttk.Label(info_content_frame, text="No thumbnail", 
                                        relief="sunken", width=20)
        self.thumbnail_label.grid(row=0, column=0, rowspan=4, sticky=(tk.W, tk.N), 
                                 padx=(0, 10), pady=(0, 5))
        
        # Text info (right side)
        text_info_frame = ttk.Frame(info_content_frame)
        text_info_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N))
        text_info_frame.columnconfigure(1, weight=1)
        
        ttk.Label(text_info_frame, text="Title:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.title_var = tk.StringVar()
        ttk.Label(text_info_frame, textvariable=self.title_var, wraplength=450).grid(
            row=0, column=1, sticky=(tk.W, tk.E)
        )
        
        ttk.Label(text_info_frame, text="Duration:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        self.duration_var = tk.StringVar()
        ttk.Label(text_info_frame, textvariable=self.duration_var).grid(row=1, column=1, sticky=tk.W)
        
        ttk.Label(text_info_frame, text="Uploader:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5))
        self.uploader_var = tk.StringVar()
        ttk.Label(text_info_frame, textvariable=self.uploader_var).grid(row=2, column=1, sticky=tk.W)
        
        ttk.Label(text_info_frame, text="Views:").grid(row=3, column=0, sticky=tk.W, padx=(0, 5))
        self.views_var = tk.StringVar()
        ttk.Label(text_info_frame, textvariable=self.views_var).grid(row=3, column=1, sticky=tk.W)
        
        # Playlist Section (hidden by default)
        self.playlist_frame = ttk.LabelFrame(main_frame, text="📑 Playlist Items", padding="5")
        self.playlist_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        self.playlist_frame.columnconfigure(0, weight=1)
        self.playlist_frame.grid_remove()  # Hide by default
        
        # Playlist info bar
        playlist_info_frame = ttk.Frame(self.playlist_frame)
        playlist_info_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        playlist_info_frame.columnconfigure(1, weight=1)
        
        self.playlist_info_var = tk.StringVar()
        ttk.Label(playlist_info_frame, textvariable=self.playlist_info_var, 
                 font=('Arial', 9, 'bold')).grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        # Select All / None buttons
        playlist_btn_frame = ttk.Frame(playlist_info_frame)
        playlist_btn_frame.grid(row=0, column=1, sticky=tk.E)
        ttk.Button(playlist_btn_frame, text="Select All", 
                  command=self.select_all_playlist).pack(side=tk.LEFT, padx=2)
        ttk.Button(playlist_btn_frame, text="Select None", 
                  command=self.select_none_playlist).pack(side=tk.LEFT, padx=2)
        
        # Playlist items listbox with scrollbar
        playlist_list_frame = ttk.Frame(self.playlist_frame)
        playlist_list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 5))
        playlist_list_frame.columnconfigure(0, weight=1)
        playlist_list_frame.rowconfigure(0, weight=1)
        
        playlist_scrollbar = ttk.Scrollbar(playlist_list_frame)
        playlist_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        self.playlist_listbox = tk.Listbox(playlist_list_frame, 
                                          height=8,
                                          selectmode=tk.MULTIPLE,
                                          yscrollcommand=playlist_scrollbar.set,
                                          font=('Arial', 9))
        self.playlist_listbox.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        playlist_scrollbar.config(command=self.playlist_listbox.yview)
        
        # Bind double-click to open individual video window
        self.playlist_listbox.bind('<Double-Button-1>', self.open_video_window)
        
        # Download Type Selection
        type_frame = ttk.LabelFrame(main_frame, text="Download Type", padding="5")
        type_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.download_type = tk.StringVar(value="video")
        ttk.Radiobutton(type_frame, text="🎥 Video", variable=self.download_type, 
                   value="video", command=self.toggle_download_type).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(type_frame, text="🎵 Audio Only", variable=self.download_type, 
                   value="audio", command=self.toggle_download_type).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(type_frame, text="🖼️ Thumbnail", variable=self.download_type, 
                   value="thumbnail", command=self.toggle_download_type).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(type_frame, text="💬 Subtitles", variable=self.download_type, 
                   value="subtitles", command=self.toggle_download_type).pack(side=tk.LEFT, padx=10)

        # Extensions (Plugins) Section - Collapsible
        ext_container = ttk.Frame(main_frame)
        ext_container.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        ext_container.columnconfigure(0, weight=1)
        
        # Toggle button for extensions
        self.extensions_visible = tk.BooleanVar(value=False)
        self.ext_toggle_btn = ttk.Button(ext_container, text="▶ Show Extensions (Plugins)", 
                                         command=self.toggle_extensions)
        self.ext_toggle_btn.grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        # Extensions frame (hidden by default)
        self.ext_frame = ttk.LabelFrame(ext_container, text="Extensions (Plugins)", padding="5")
        self.ext_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.ext_frame.columnconfigure(0, weight=1)
        self.ext_frame.grid_remove()  # Hide by default
        
        plugin_row = 0
        for plugin in self.plugin_manager.get_plugins():
            var = tk.BooleanVar(value=getattr(plugin, 'enabled', True))
            self.plugin_vars[plugin.id] = var
            cb = ttk.Checkbutton(self.ext_frame, text=f"{plugin.name} — {plugin.description}", variable=var)
            cb.grid(row=plugin_row, column=0, sticky=tk.W, pady=2)
            plugin_row += 1
        ttk.Button(self.ext_frame, text="Run Enabled Extensions", command=self.run_extensions).grid(row=plugin_row, column=0, sticky=tk.W, pady=(6,0))
        
        # Video Format Selection Section
        self.video_frame = ttk.LabelFrame(main_frame, text="Video Quality Options", padding="5")
        self.video_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        self.video_frame.columnconfigure(1, weight=1)

        ttk.Label(self.video_frame, text="Video Quality:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.video_format_var = tk.StringVar()
        self.video_format_combo = ttk.Combobox(self.video_frame, textvariable=self.video_format_var,
                                               state="readonly", width=50)
        self.video_format_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        
        # Output container format selection
        ttk.Label(self.video_frame, text="Output Format:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(5, 0))
        self.output_format_combo = ttk.Combobox(
            self.video_frame, 
            textvariable=self.output_format_var,
            values=list(self.output_formats.keys()),
            state="readonly", 
            width=30
        )
        self.output_format_combo.grid(row=1, column=1, sticky=tk.W, padx=(0, 5), pady=(5, 0))
        self.output_format_combo.current(0)  # Default to MP4
        
        # Format info label
        format_info = ttk.Label(self.video_frame, text="YouTube Studio: MP4, MOV, AVI, WebM, FLV, 3GP", 
                               font=('Arial', 8), foreground='gray')
        format_info.grid(row=1, column=1, sticky=tk.E, padx=(0, 5), pady=(5, 0))

        # Audio Format Selection Section
        self.audio_frame = ttk.LabelFrame(main_frame, text="Audio Quality Options", padding="5")
        self.audio_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        self.audio_frame.columnconfigure(1, weight=1)
        self.audio_frame.grid_remove()  # Hide by default

        ttk.Label(self.audio_frame, text="Audio Quality:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.audio_format_var = tk.StringVar()
        self.audio_format_combo = ttk.Combobox(self.audio_frame, textvariable=self.audio_format_var,
                                               state="readonly", width=50)
        self.audio_format_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))

        # Populate audio quality options based on FFmpeg availability
        if self.ffmpeg_available:
            audio_options = [
                ("Best Audio (m4a/webm)", "bestaudio"),
                ("MP3 (Best Quality)", "bestaudio[ext=m4a]/bestaudio"),
                ("MP3 (320kbps)", "bestaudio[ext=m4a]/bestaudio"),
                ("MP3 (192kbps)", "bestaudio[ext=m4a]/bestaudio"),
                ("MP3 (128kbps)", "bestaudio[ext=m4a]/bestaudio"),
                ("High Quality (128kbps+)", "bestaudio[abr>=128]"),
                ("Medium Quality (64-128kbps)", "bestaudio[abr>=64][abr<128]"),
            ]
        else:
            audio_options = [
                ("Best Audio (m4a/webm)", "bestaudio"),
                ("High Quality (128kbps+)", "bestaudio[abr>=128]"),
                ("Medium Quality (64-128kbps)", "bestaudio[abr>=64][abr<128]"),
            ]
        self.audio_format_combo['values'] = [opt[0] for opt in audio_options]
        self.audio_format_options = {opt[0]: opt[1] for opt in audio_options}
        self.audio_format_combo.current(0)

        # Thumbnail Options Section (hidden by default)
        self.thumb_frame = ttk.LabelFrame(main_frame, text="Thumbnail Options", padding="5")
        self.thumb_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        self.thumb_frame.columnconfigure(1, weight=1)
        self.thumb_frame.grid_remove()

        ttk.Label(self.thumb_frame, text="Format:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        # Allow choosing thumbnail output format
        self.thumb_format_var = tk.StringVar(value="jpg")
        self.thumb_format_combo = ttk.Combobox(
            self.thumb_frame,
            textvariable=self.thumb_format_var,
            values=["original", "jpg", "png", "webp", "bmp"],
            state="readonly",
            width=12,
        )
        self.thumb_format_combo.grid(row=0, column=1, sticky=tk.W)

        # Output name for thumbnail (allow patterns like %(title)s)
        ttk.Label(self.thumb_frame, text="Output name:").grid(row=1, column=0, sticky=tk.W, padx=(0,5), pady=(6,0))
        self.thumb_name_var = tk.StringVar(value='%(title)s_thumbnail')
        ttk.Entry(self.thumb_frame, textvariable=self.thumb_name_var, width=30).grid(row=1, column=1, sticky=tk.W, pady=(6,0))

        # Subtitles Options Section (hidden by default)
        self.subs_frame = ttk.LabelFrame(main_frame, text="Subtitles Options", padding="5")
        self.subs_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        self.subs_frame.columnconfigure(1, weight=1)
        self.subs_frame.grid_remove()

        # Languages entry
        ttk.Label(self.subs_frame, text="Languages (comma-separated codes):").grid(row=0, column=0, sticky=tk.W)
        self.subs_langs_var = tk.StringVar(value="en, en-*")
        ttk.Entry(self.subs_frame, textvariable=self.subs_langs_var).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5,0))

        # All languages and auto-generated
        self.subs_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.subs_frame, text="Download all available languages",
            variable=self.subs_all_var).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(5,0))

        self.subs_auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.subs_frame, text="Include auto-generated subtitles (fallback)",
            variable=self.subs_auto_var).grid(row=2, column=0, columnspan=2, sticky=tk.W)

        # Subtitles format
        ttk.Label(self.subs_frame, text="Subtitles format:").grid(row=3, column=0, sticky=tk.W, pady=(5,0))
        self.subs_format_var = tk.StringVar(value="best")
        subs_format_combo = ttk.Combobox(self.subs_frame, textvariable=self.subs_format_var,
                                         state="readonly", width=20)
        subs_format_combo['values'] = ["best", "srt", "vtt"]
        subs_format_combo.current(0)
        subs_format_combo.grid(row=3, column=1, sticky=tk.W, pady=(5,0))

        # Gentle warning about rate limiting when requesting many subtitles
        ttk.Label(
            self.subs_frame,
            text=("Tip: requesting 'all languages' together with 'auto-generated' can hit site rate limits.\n"
                  "If both are selected, the app limits to your language list to reduce errors."),
            foreground='gray'
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        # Prevent conflicting selection in UI: if user checks one, uncheck the other
        def on_subs_all_toggle():
            if self.subs_all_var.get() and self.subs_auto_var.get():
                # Prefer keeping auto-generated; uncheck all to reduce requests
                self.subs_all_var.set(False)
                messagebox.showinfo(
                    "Subtitles Options",
                    "To avoid rate limits, you can't select 'All languages' together with 'Auto-generated'.\n"
                    "We'll use your language list with auto-generated instead."
                )

        def on_subs_auto_toggle():
            if self.subs_auto_var.get() and self.subs_all_var.get():
                self.subs_all_var.set(False)
                messagebox.showinfo(
                    "Subtitles Options",
                    "To avoid rate limits, 'All languages' has been turned off while Auto-generated is enabled."
                )

        # Rebind the existing checkbuttons with command hooks
        for child in self.subs_frame.winfo_children():
            if isinstance(child, ttk.Checkbutton):
                txt = child.cget('text')
                if 'Download all available languages' in txt:
                    child.configure(command=on_subs_all_toggle)
                elif 'Include auto-generated subtitles' in txt:
                    child.configure(command=on_subs_auto_toggle)

        # Advanced toggles for backoff
        def toggle_subs_advanced():
            if self.subs_show_advanced.get():
                subs_adv_frame.grid()
            else:
                subs_adv_frame.grid_remove()

        adv_toggle = ttk.Checkbutton(
            self.subs_frame,
            text="Show advanced options",
            variable=self.subs_show_advanced,
            command=toggle_subs_advanced
        )
        adv_toggle.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        subs_adv_frame = ttk.Frame(self.subs_frame)
        subs_adv_frame.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E))
        subs_adv_frame.columnconfigure(1, weight=1)
        subs_adv_frame.grid_remove()

        ttk.Label(subs_adv_frame, text="Max retries:").grid(row=0, column=0, sticky=tk.W)
        try:
            spn_attempts = ttk.Spinbox(subs_adv_frame, from_=2, to=10, textvariable=self.subs_backoff_max_attempts, width=5)
        except Exception:
            spn_attempts = tk.Spinbox(subs_adv_frame, from_=2, to=10, textvariable=self.subs_backoff_max_attempts, width=5)
        spn_attempts.grid(row=0, column=1, sticky=tk.W, padx=(6,0))

        ttk.Label(subs_adv_frame, text="Base sleep (s):").grid(row=1, column=0, sticky=tk.W, pady=(4,0))
        try:
            spn_base = ttk.Spinbox(subs_adv_frame, from_=0.5, to=5.0, increment=0.5, textvariable=self.subs_backoff_base_sleep, width=5)
        except Exception:
            spn_base = tk.Spinbox(subs_adv_frame, from_=0.5, to=5.0, increment=0.5, textvariable=self.subs_backoff_base_sleep, width=5)
        spn_base.grid(row=1, column=1, sticky=tk.W, padx=(6,0), pady=(4,0))

        ttk.Label(subs_adv_frame, text="Max sleep (s):").grid(row=2, column=0, sticky=tk.W, pady=(4,0))
        try:
            spn_cap = ttk.Spinbox(subs_adv_frame, from_=5.0, to=60.0, increment=1.0, textvariable=self.subs_backoff_max_sleep, width=5)
        except Exception:
            spn_cap = tk.Spinbox(subs_adv_frame, from_=5.0, to=60.0, increment=1.0, textvariable=self.subs_backoff_max_sleep, width=5)
        spn_cap.grid(row=2, column=1, sticky=tk.W, padx=(6,0), pady=(4,0))

        # Download Path Section
        path_frame = ttk.Frame(main_frame)
        path_frame.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        path_frame.columnconfigure(1, weight=1)

        ttk.Label(path_frame, text="Download Path:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.path_var = tk.StringVar(value=self.download_path)
        ttk.Entry(path_frame, textvariable=self.path_var, state="readonly").grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5)
        )
        ttk.Button(path_frame, text="Browse", command=self.browse_path).grid(row=0, column=2)

        # Speed Options Section (IDM-style parallel downloads)
        speed_frame = ttk.LabelFrame(main_frame, text="⚡ Speed Options", padding="5")
        speed_frame.grid(row=7, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Concurrent fragments (built-in parallel download for DASH/HLS)
        ttk.Label(speed_frame, text="Parallel connections:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        try:
            frag_spinbox = ttk.Spinbox(speed_frame, from_=1, to=16, textvariable=self.concurrent_fragments, width=5)
        except Exception:
            frag_spinbox = tk.Spinbox(speed_frame, from_=1, to=16, textvariable=self.concurrent_fragments, width=5)
        frag_spinbox.grid(row=0, column=1, sticky=tk.W, padx=(0, 15))
        
        # Aria2c option (advanced multi-connection downloader)
        self.aria2c_check = ttk.Checkbutton(
            speed_frame, 
            text="Use aria2c (faster)", 
            variable=self.use_aria2c,
            command=self._toggle_aria2c_options
        )
        self.aria2c_check.grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        
        ttk.Label(speed_frame, text="aria2 connections:").grid(row=0, column=3, sticky=tk.W, padx=(0, 5))
        try:
            self.aria2c_spinbox = ttk.Spinbox(speed_frame, from_=1, to=32, textvariable=self.aria2c_connections, width=5)
        except Exception:
            self.aria2c_spinbox = tk.Spinbox(speed_frame, from_=1, to=32, textvariable=self.aria2c_connections, width=5)
        self.aria2c_spinbox.grid(row=0, column=4, sticky=tk.W)
        
        # Show aria2c status
        if not self.aria2c_available:
            self.aria2c_check.config(state="disabled")
            self.aria2c_spinbox.config(state="disabled")
            ttk.Label(speed_frame, text="(aria2c not installed)", foreground="gray").grid(row=0, column=5, sticky=tk.W, padx=(5, 0))
        else:
            self._toggle_aria2c_options()  # Set initial state

        # Progress Section
        progress_frame = ttk.LabelFrame(main_frame, text="Download Progress", padding="5")
        progress_frame.grid(row=8, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var,
                                            maximum=100, length=400)
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(progress_frame, textvariable=self.status_var).grid(row=1, column=0, sticky=tk.W)

        # Control Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=9, column=0, columnspan=2, pady=(0, 10))

        self.download_btn = ttk.Button(button_frame, text="Download",
                                       command=self.start_download, state="disabled")
        self.download_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.cancel_btn = ttk.Button(button_frame, text="Cancel",
                                     command=self.cancel_download, state="disabled")
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(button_frame, text="Clear", command=self.clear_all).pack(side=tk.LEFT, padx=(0, 5))
        
        # FFmpeg Download Button (only show if FFmpeg not found)
        if not check_ffmpeg():
            self.ffmpeg_btn = ttk.Button(button_frame, text="📥 Get FFmpeg (for MP3)", 
                                        command=self.download_ffmpeg_gui, 
                                        style="Accent.TButton")
            self.ffmpeg_btn.pack(side=tk.LEFT)
        
        # Log Section
        log_frame = ttk.LabelFrame(main_frame, text="Log", padding="5")
        log_frame.grid(row=10, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(10, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, width=70)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Controls Frame
        controls_frame = ttk.Frame(main_frame)
        controls_frame.grid(row=10, column=0, columnspan=2, sticky=(tk.W, tk.E))
        
        # Clipboard monitor toggle
        self.clipboard_check = ttk.Checkbutton(controls_frame, 
                                              text="📋 Auto-detect URLs", 
                                              variable=self.clipboard_monitor_enabled,
                                              command=self.toggle_clipboard_monitor)
        self.clipboard_check.pack(side=tk.LEFT, padx=20)
        
        # Tools buttons - quick access to new features
        tools_frame = ttk.Frame(controls_frame)
        tools_frame.pack(side=tk.LEFT, padx=20)
        
        ttk.Button(tools_frame, text="📚 Library", width=10,
                  command=self.open_download_library).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_frame, text="📡 Channels", width=10,
                  command=self.open_channel_monitor).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools_frame, text="📤 Upload", width=10,
                  command=self.open_upload_manager).pack(side=tk.LEFT, padx=2)

        # Background monitoring status indicator
        self.monitor_status_var = tk.StringVar(value="")
        ttk.Label(tools_frame, textvariable=self.monitor_status_var,
                  foreground='green', font=('Arial', 8)).pack(side=tk.LEFT, padx=(8, 2))

        version_label = ttk.Label(controls_frame, text=f"Version {VERSION}", 
                                 font=('Arial', 8), foreground='gray')
        version_label.pack(side=tk.RIGHT, padx=5, pady=2)
        
        # Bind Enter key to URL entry
        self.url_entry.bind('<Return>', lambda e: self.fetch_video_info())
    
    def _toggle_aria2c_options(self):
        """Enable/disable aria2c connection spinbox based on checkbox"""
        if self.use_aria2c.get():
            self.aria2c_spinbox.config(state="normal")
        else:
            self.aria2c_spinbox.config(state="disabled")
    
    def run_extensions(self):
        """Run all enabled plugins against current context."""
        # Sync enabled flags with UI vars
        for p in self.plugin_manager.get_plugins():
            var = self.plugin_vars.get(p.id)
            if var is not None:
                p.enabled = bool(var.get())

        enabled = self.plugin_manager.get_enabled()
        if not enabled:
            messagebox.showinfo("Extensions", "No extensions enabled.")
            return
        if not self.video_info and not (self.is_playlist and self.playlist_entries):
            messagebox.showwarning("Extensions", "Fetch a video or playlist first.")
            return
        self.log_message(f"🔌 Running {len(enabled)} extension(s)...")
        for p in enabled:
            try:
                # Determine context eligibility
                if self.is_playlist and not p.supports_playlist:
                    self.log_message(f"[EXT:{p.id}] Skipped (playlist not supported)")
                    continue
                if (not self.is_playlist) and p.requires_video and not self.video_info:
                    self.log_message(f"[EXT:{p.id}] Skipped (video info required)")
                    continue
                p.run(self, self.video_info, self.playlist_entries if self.is_playlist else None)
                self.log_message(f"[EXT:{p.id}] Completed")
            except Exception as e:
                self.log_message(f"[EXT:{p.id}] Error: {e}")
        
    def show_ffmpeg_warning(self):
        """Show warning about missing FFmpeg"""
        response = messagebox.showinfo(
            "FFmpeg Information",
            "ℹ️ FFmpeg Status: Not Found\n\n"
            "• Video downloads: ✅ Will work normally\n"
            "• Audio downloads: ⚠️ Will download in original format (webm/m4a)\n"
            "• For MP3 conversion: Install FFmpeg\n\n"
            "To install FFmpeg:\n"
            "• Run: install_ffmpeg.bat (in the app folder)\n"
            "• Or: choco install ffmpeg\n"
            "• Or: winget install ffmpeg\n\n"
            "You can use the app now and install FFmpeg later if needed."
        )
        self.log_message("ℹ️ FFmpeg not found - Audio will be saved in original format")
    
    def open_download_library(self):
        """Open the Download Library window to browse downloaded content by type"""
        try:
            DownloadLibrary(self.root, default_path=self.download_path, 
                           log_callback=self.log_message)
            self.log_message("📚 Opened Download Library")
        except Exception as e:
            self.log_message(f"❌ Error opening Download Library: {e}")
            messagebox.showerror("Error", f"Could not open Download Library:\n{e}")
    
    def open_channel_monitor(self):
        """Open the Channel Monitor window to watch for new uploads"""
        try:
            # Reuse existing instance — avoid creating duplicate monitors
            if self.channel_monitor_instance is not None:
                self.channel_monitor_instance.show()
                self.log_message("📡 Channel Monitor opened")
                return

            def on_new_video(video_data):
                title = video_data.get('title', 'Unknown')
                channel = video_data.get('channel', 'Unknown')
                self.log_message(f"🆕 New video from {channel}: {title}")

            self.channel_monitor_instance = ChannelMonitor(
                self.root,
                log_callback=self.log_message,
                on_new_video_callback=on_new_video,
                auto_download_callback=self._auto_download_video,
                monitor_status_callback=self._update_monitor_status,
            )
            self.log_message("📡 Opened Channel Monitor")
        except Exception as e:
            self.log_message(f"❌ Error opening Channel Monitor: {e}")
            messagebox.showerror("Error", f"Could not open Channel Monitor:\n{e}")
    
    def open_upload_manager(self):
        """Open the Upload Manager window for multi-platform uploads"""
        try:
            from uploaders.upload_window import show_upload_window
            show_upload_window(self.root)
            self.log_message("📤 Opened Upload Manager")
        except ImportError as e:
            self.log_message(f"❌ Upload module not available: {e}")
            messagebox.showerror("Error", 
                f"Upload Manager is not available.\n"
                f"Make sure the uploaders package is installed:\n{e}")
        except Exception as e:
            self.log_message(f"❌ Error opening Upload Manager: {e}")
            messagebox.showerror("Error", f"Could not open Upload Manager:\n{e}")

    def _update_monitor_status(self, is_monitoring: bool, channel_count: int):
        """Update the monitoring status indicator in the main window toolbar."""
        if is_monitoring and channel_count > 0:
            self.monitor_status_var.set(f"📡 Monitoring {channel_count} channel(s)")
        else:
            self.monitor_status_var.set("")

    def _auto_download_video(self, video_data: dict):
        """Auto-download a new video detected by the channel monitor."""
        url = video_data.get('url', '')
        title = video_data.get('title', 'Unknown')
        channel = video_data.get('channel', 'Unknown')

        if not url:
            return

        self.root.after(0, self.log_message,
                        f"🤖 Auto-downloading: {title} (from {channel})")

        def download():
            saved_path = None
            try:
                out_template = os.path.join(
                    self.download_path, '%(title)s.%(ext)s'
                )
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'merge_output_format': 'mp4',
                    'outtmpl': out_template,
                    'quiet': True,
                    'no_warnings': True,
                }

                # Capture the actual saved filename
                downloaded_files = []

                def _progress_hook(d):
                    if d.get('status') == 'finished':
                        downloaded_files.append(d.get('filename', ''))

                ydl_opts['progress_hooks'] = [_progress_hook]

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    # Resolve actual output path from info
                    if info:
                        video_data['duration'] = info.get('duration', 0)
                        video_data['channel_url'] = info.get('channel_url', '')

                # Determine saved file path
                if downloaded_files:
                    saved_path = downloaded_files[-1]
                    # mp4 merge renames .webm → .mp4
                    if saved_path and not os.path.exists(saved_path):
                        mp4_path = os.path.splitext(saved_path)[0] + '.mp4'
                        if os.path.exists(mp4_path):
                            saved_path = mp4_path

                self.root.after(0, self.log_message,
                                f"✅ Auto-download complete: {title}")

                # Fire n8n webhook if configured
                if _N8N_AVAILABLE:
                    _fire_webhook(
                        video_data=video_data,
                        file_path=saved_path,
                        log_callback=lambda msg: self.root.after(
                            0, self.log_message, msg
                        ),
                    )

            except Exception as e:
                self.root.after(0, self.log_message,
                                f"❌ Auto-download failed: {title} — {e}")

        threading.Thread(target=download, daemon=True).start()

    def _init_channel_background_monitoring(self):
        """Auto-start channel monitoring in background if any channels have auto-download enabled."""
        config_file = Path(__file__).parent / "channel_monitor_config.json"
        if not config_file.exists():
            return
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            channels = data.get('channels', {})
            if not channels:
                return
            auto_dl_channels = [
                ch for ch in channels.values() if ch.get('auto_download', False)
            ]
            if not auto_dl_channels:
                return  # No channels with auto-download — nothing to start

            # Create monitor instance silently (window hidden)
            def on_new_video(video_data):
                title = video_data.get('title', 'Unknown')
                channel = video_data.get('channel', 'Unknown')
                self.log_message(f"🆕 New video from {channel}: {title}")

            self.channel_monitor_instance = ChannelMonitor(
                self.root,
                log_callback=self.log_message,
                on_new_video_callback=on_new_video,
                auto_download_callback=self._auto_download_video,
                monitor_status_callback=self._update_monitor_status,
            )
            self.channel_monitor_instance.window.withdraw()  # Stay hidden
            self.channel_monitor_instance.start_monitoring()  # Start background loop
            self.log_message(
                f"🤖 Background channel monitoring started "
                f"({len(auto_dl_channels)} auto-download channel(s))"
            )
        except Exception as e:
            logger.warning(f"Could not auto-start channel monitor: {e}")

    def load_thumbnail(self, thumbnail_url):
        """Download and display video thumbnail"""
        try:
            if not thumbnail_url:
                return
                
            self.log_message(f"Loading thumbnail...")
            
            # Download thumbnail
            with urllib.request.urlopen(thumbnail_url, timeout=10) as response:
                image_data = response.read()
            
            # Open image with PIL
            image = Image.open(io.BytesIO(image_data))
            
            # Resize to fit in the display area (max 160x90 for 16:9 aspect ratio)
            max_width = 160
            max_height = 90
            
            # Calculate aspect ratio
            aspect_ratio = image.width / image.height
            
            if aspect_ratio > (max_width / max_height):
                # Width is the limiting factor
                new_width = max_width
                new_height = int(max_width / aspect_ratio)
            else:
                # Height is the limiting factor
                new_height = max_height
                new_width = int(max_height * aspect_ratio)
            
            # Resize image
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image)
            
            # Update label
            self.thumbnail_label.configure(image=photo, text="")
            self.thumbnail_label.image = photo  # Keep a reference
            
            self.log_message("✓ Thumbnail loaded")
            
        except Exception as e:
            self.log_message(f"⚠️ Could not load thumbnail: {str(e)}")
            self.thumbnail_label.configure(text="No thumbnail\navailable")
    
    def toggle_download_type(self):
        """Toggle between video and audio download options"""
        dtype = self.download_type.get()
        # Hide all optional frames first
        self.video_frame.grid_remove()
        self.audio_frame.grid_remove()
        self.thumb_frame.grid_remove()
        self.subs_frame.grid_remove()

        if dtype == "video":
            self.video_frame.grid()
        elif dtype == "audio":
            if not self.ffmpeg_available and not self.ffmpeg_warning_shown:
                self.log_message("ℹ️ Note: Without FFmpeg, audio saves as webm/m4a (not MP3)")
                self.ffmpeg_warning_shown = True
            self.audio_frame.grid()
        elif dtype == "thumbnail":
            self.thumb_frame.grid()
        elif dtype == "subtitles":
            self.subs_frame.grid()
    
    def toggle_extensions(self):
        """Toggle the visibility of the extensions panel"""
        if self.extensions_visible.get():
            # Hide extensions
            self.ext_frame.grid_remove()
            self.ext_toggle_btn.config(text="▶ Show Extensions (Plugins)")
            self.extensions_visible.set(False)
        else:
            # Show extensions
            self.ext_frame.grid()
            self.ext_toggle_btn.config(text="Hide Extensions (Plugins)")
            self.extensions_visible.set(True)
    
    def log_message(self, message: str, level: str = "info") -> None:
        """
        Add a message to the log with timestamp.
        Also logs to the application logger.
        
        Args:
            message: The message to log
            level: Log level (debug, info, warning, error)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
        
        # Also log to application logger
        log_func = getattr(logger, level, logger.info)
        log_func(message)
        
    def fetch_video_info(self):
        """Fetch video information from the provided URL"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a video URL")
            return
        
        # Use URLParser for intelligent URL classification
        parsed_url = URLParser.parse(url)
        url_type = parsed_url.url_type
        
        # Check if URL is a channel/profile URL
        is_channel_url = url_type.is_channel
        
        # If it's a channel URL, ensure we get the /videos tab
        if is_channel_url:
            # Use the cleaned URL which adds /videos tab if needed
            if url_type == URLType.CHANNEL:
                url = parsed_url.cleaned_url
                self.log_message(f"Channel URL detected, fetching videos tab: {url}")
        
        # Check if URL contains playlist parameter
        has_playlist_param = url_type == URLType.PLAYLIST
        
        # Determine the URL type
        fetch_as_playlist = False
        
        if is_channel_url:
            # It's a channel URL - ask user what they want
            response = messagebox.askyesno(
                "Channel Detected",
                "🎬 YouTube channel/profile detected!\n\n"
                "Do you want to download ALL videos from this channel?\n\n"
                "• YES - Show all channel videos (may take time to load)\n"
                "• NO - Just view channel info",
                icon='question'
            )
            if response:
                fetch_as_playlist = True
                self.log_message("📺 User chose to fetch all channel videos")
            else:
                self.log_message("ℹ️ Fetching channel info only")
        elif has_playlist_param:
            # It's a playlist URL - ask user what they want
            if 'v=' in url:
                # URL has both video and playlist
                response = messagebox.askyesnocancel(
                    "Playlist or Video?",
                    "🎯 This URL contains both a video and a playlist!\n\n"
                    "What would you like to download?\n\n"
                    "• YES - Download entire playlist\n"
                    "• NO - Download only this video\n"
                    "• CANCEL - Go back",
                    icon='question'
                )
                if response is None:  # Cancel
                    self.fetch_btn.config(state="normal")
                    return
                elif response:  # Yes - playlist
                    fetch_as_playlist = True
                    self.log_message("📑 User chose to download playlist")
                else:  # No - single video
                    fetch_as_playlist = False
                    self.log_message("🎥 User chose to download single video only")
                    # Clean URL - remove playlist parameter
                    import urllib.parse
                    parsed = urllib.parse.urlparse(url)
                    params = urllib.parse.parse_qs(parsed.query)
                    if 'v' in params:
                        clean_params = {'v': params['v']}
                        new_query = urllib.parse.urlencode(clean_params, doseq=True)
                        url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, 
                                                      parsed.params, new_query, parsed.fragment))
                        self.log_message(f"Cleaned URL: {url}")
            else:
                # Pure playlist URL
                response = messagebox.askyesno(
                    "Playlist Detected",
                    "📑 YouTube playlist detected!\n\n"
                    "Do you want to download the entire playlist?\n\n"
                    "• YES - Show all playlist videos\n"
                    "• NO - Cancel",
                    icon='question'
                )
                if response:
                    fetch_as_playlist = True
                    self.log_message("📑 User chose to download playlist")
                else:
                    self.fetch_btn.config(state="normal")
                    return
        else:
            # Regular single video URL - use URLParser's cleaned URL
            if parsed_url.platform == 'youtube' and parsed_url.video_id:
                url = f"https://www.youtube.com/watch?v={parsed_url.video_id}"
                self.log_message(f"Cleaned URL (removed extra params): {url}")
        
        self.fetch_btn.config(state="disabled")
        self.status_var.set("Fetching video information...")
        self.log_message("Fetching video information...")
        
        def fetch_info():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'no_check_certificate': True,
                    'extract_flat': 'in_playlist' if fetch_as_playlist else False,
                    'socket_timeout': 30,
                }
                
                # For channel URLs, we need to extract all videos
                if is_channel_url and fetch_as_playlist:
                    ydl_opts['playlistend'] = None  # Get all videos
                    ydl_opts['ignoreerrors'] = True  # Skip unavailable videos
                
                self.root.after(0, self.log_message, f"Connecting to: {url}")
                
                if fetch_as_playlist:
                    if is_channel_url:
                        self.root.after(0, self.log_message, "� Loading channel videos... (this may take a minute)")
                    else:
                        self.root.after(0, self.log_message, "📑 Loading playlist items...")
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    self.root.after(0, self.log_message, "Extracting video information...")
                    info = ydl.extract_info(url, download=False)
                    
                    if not info:
                        raise Exception("No video information received")
                    
                    # Check if it's a playlist
                    if info.get('_type') == 'playlist':
                        self.root.after(0, self.handle_playlist, info)
                    else:
                        self.video_info = info
                        self.root.after(0, self.log_message, f"Successfully fetched info for: {info.get('title', 'Unknown')}")
                        # Update GUI in main thread
                        self.root.after(0, self.update_video_info, info)
                    
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                error_msg = f"Error fetching video info: {str(e)}\n{error_details}"
                self.root.after(0, self.handle_fetch_error, error_msg)
        
        # Run in separate thread
        threading.Thread(target=fetch_info, daemon=True).start()
    
    def handle_playlist(self, playlist_info):
        """Handle playlist information - Open Advanced Playlist Manager Window"""
        try:
            from advanced_playlist_manager import AdvancedPlaylistManager
            
            self.is_playlist = True
            playlist_entries = playlist_info.get('entries', [])
            # Save entries for plugins and other features
            self.playlist_entries = playlist_entries or []
            playlist_title = playlist_info.get('title', 'Playlist')
            playlist_count = len(playlist_entries)
            
            # Determine if it's a channel or playlist
            uploader = playlist_info.get('uploader', '')
            channel_id = playlist_info.get('channel_id', '')
            
            if uploader or channel_id:
                source_type = "📺 Channel"
                self.log_message(f"📺 Channel detected: {playlist_title}")
            else:
                source_type = "📑 Playlist"
                self.log_message(f"📑 Playlist detected: {playlist_title}")
            
            self.log_message(f"📊 Found {playlist_count} videos")
            self.log_message(f"🎯 Opening Advanced Playlist Manager...")
            
            # Open Advanced Playlist Manager Window
            AdvancedPlaylistManager(self.root, playlist_info, playlist_entries, self.log_message)
            
            # Reset main window
            self.fetch_btn.config(state="normal")
            self.status_var.set(f"{source_type} loaded - {playlist_count} videos")
            
        except Exception as e:
            import traceback
            self.log_message(f"❌ Error opening playlist manager: {str(e)}")
            self.log_message(traceback.format_exc())
            self.fetch_btn.config(state="normal")
    def fetch_playlist_formats(self):
        """Fetch video formats from first video in playlist to populate quality options"""
        try:
            if not self.playlist_entries:
                self.root.after(0, self.log_message, "⚠️ No videos in playlist")
                return
            
            # Get first video URL
            first_video = self.playlist_entries[0]
            video_url = first_video.get('url') or first_video.get('webpage_url') or first_video.get('id')
            
            if not video_url:
                self.root.after(0, self.log_message, "⚠️ Could not get video URL for format detection")
                return
            
            # If we only have ID, construct YouTube URL
            if not video_url.startswith('http'):
                video_url = f"https://www.youtube.com/watch?v={video_url}"
            
            self.root.after(0, self.log_message, f"🔍 Detecting formats from: {first_video.get('title', 'first video')[:50]}...")
            
            # Fetch full info for first video to get formats
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'no_check_certificate': True,
                'socket_timeout': 30,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                if not info or 'formats' not in info:
                    self.root.after(0, self.log_message, "⚠️ No formats found")
                    return
                
                # Parse video formats (same logic as single video)
                video_formats = []
                for fmt in info['formats']:
                    if fmt.get('vcodec') != 'none':  # Video formats only
                        height = fmt.get('height')
                        fps = fmt.get('fps')
                        ext = fmt.get('ext', 'mp4')
                        format_note = fmt.get('format_note', '')
                        filesize = fmt.get('filesize')
                        
                        if height:
                            quality_str = f"{height}p"
                            if fps:
                                quality_str += f" {fps}fps"
                            if format_note:
                                quality_str += f" ({format_note})"
                            if filesize:
                                size_mb = filesize / (1024 * 1024)
                                quality_str += f" - {size_mb:.1f}MB"
                            quality_str += f" [{ext}]"
                            
                            video_formats.append((quality_str, fmt['format_id']))
                
                # Sort by quality (height)
                def get_height(fmt_tuple):
                    try:
                        height_match = re.search(r'(\d+)p', fmt_tuple[0])
                        return int(height_match.group(1)) if height_match else 0
                    except:
                        return 0
                
                video_formats.sort(key=get_height, reverse=True)
                
                # Update GUI in main thread
                self.root.after(0, self.update_playlist_formats, video_formats)
                
        except Exception as e:
            error_msg = f"⚠️ Could not fetch formats: {str(e)}"
            self.root.after(0, self.log_message, error_msg)
    
    def update_playlist_formats(self, video_formats):
        """Update video format dropdown with fetched formats"""
        try:
            if video_formats:
                self.video_format_combo['values'] = [fmt[0] for fmt in video_formats]
                self.video_format_options = {fmt[0]: fmt[1] for fmt in video_formats}
                self.video_format_combo.current(0)
                self.log_message(f"✅ Loaded {len(video_formats)} video quality options")
                self.log_message(f"📹 Default: {video_formats[0][0]}")
            else:
                self.log_message("⚠️ No video formats available")
        except Exception as e:
            self.log_message(f"❌ Error updating formats: {str(e)}")
    
    def open_video_window(self, event=None):
        """Open a new window for individual video from playlist"""
        try:
            # Get selected item index
            selection = self.playlist_listbox.curselection()
            if not selection:
                return
            
            idx = selection[0]
            if idx >= len(self.playlist_entries):
                return
            
            video_entry = self.playlist_entries[idx]
            video_title = video_entry.get('title', 'Unknown')
            video_id = video_entry.get('id') or video_entry.get('url')
            
            if not video_id:
                messagebox.showerror("Error", "Could not get video URL")
                return
            
            # Construct video URL
            if not video_id.startswith('http'):
                video_url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                video_url = video_id
            
            self.log_message(f"🔍 Opening video window: {video_title[:50]}...")
            
            # Create new window
            video_window = tk.Toplevel(self.root)
            video_window.title(f"Download: {video_title[:60]}")
            video_window.geometry("700x600")
            video_window.resizable(True, True)
            
            # Create VideoWindow instance
            VideoWindow(video_window, video_url, video_title, self.log_message)
            
        except Exception as e:
            self.log_message(f"❌ Error opening video window: {str(e)}")
            messagebox.showerror("Error", f"Could not open video window: {str(e)}")
        
    def update_video_info(self, info):
        """Update the GUI with video information"""
        try:
            self.log_message("Updating video information in GUI...")
            
            # Mark as single video (not playlist)
            self.is_playlist = False
            self.playlist_frame.grid_remove()  # Hide playlist frame
            
            # Update video info labels
            self.title_var.set(info.get('title', 'N/A'))
            self.log_message(f"Title: {info.get('title', 'N/A')}")
            
            # Use FormatParser for duration formatting
            duration = info.get('duration')
            self.duration_var.set(FormatParser.format_duration(duration))
                
            self.uploader_var.set(info.get('uploader', 'N/A'))
            
            # Use FormatParser for view count formatting
            view_count = info.get('view_count')
            self.views_var.set(FormatParser.format_view_count(view_count))
            
            # Load thumbnail
            thumbnail_url = info.get('thumbnail') or ""
            if not thumbnail_url and info.get('thumbnails'):
                thumbnails = info['thumbnails']
                if isinstance(thumbnails, list) and len(thumbnails) > 0:
                    thumbnail_url = thumbnails[-1].get('url', '') or thumbnail_url

            if thumbnail_url:
                # Load thumbnail in a separate thread to avoid blocking
                threading.Thread(target=self.load_thumbnail, args=(thumbnail_url,), daemon=True).start()
            else:
                self.thumbnail_label.configure(text="No thumbnail\navailable")
            
            # Populate VIDEO format options only
            self.log_message("Parsing available video formats...")
            video_formats = []
            if 'formats' in info:
                self.log_message(f"Found {len(info['formats'])} total formats")
                for fmt in info['formats']:
                    if fmt.get('vcodec') != 'none':  # Video formats only
                        height = fmt.get('height')
                        fps = fmt.get('fps')
                        ext = fmt.get('ext', 'mp4')
                        format_note = fmt.get('format_note', '')
                        filesize = fmt.get('filesize')
                        
                        if height:
                            quality_str = f"{height}p"
                            if fps:
                                quality_str += f" {fps}fps"
                            if format_note:
                                quality_str += f" ({format_note})"
                            if filesize:
                                size_mb = filesize / (1024 * 1024)
                                quality_str += f" - {size_mb:.1f}MB"
                            quality_str += f" [{ext}]"
                            
                            video_formats.append((quality_str, fmt['format_id']))
            
            # Sort video formats by quality (height)
            def get_height(fmt_tuple):
                try:
                    height_match = re.search(r'(\d+)p', fmt_tuple[0])
                    return int(height_match.group(1)) if height_match else 0
                except:
                    return 0
                    
            video_formats.sort(key=get_height, reverse=True)
            
            self.log_message(f"Found {len(video_formats)} video formats")
            
            # Update VIDEO combobox
            self.video_format_combo['values'] = [fmt[0] for fmt in video_formats]
            self.video_format_options = {fmt[0]: fmt[1] for fmt in video_formats}
            
            if video_formats:
                self.video_format_combo.current(0)
                self.download_btn.config(state="normal")
                self.log_message(f"Default quality: {video_formats[0][0]}")
            else:
                self.log_message("WARNING: No video formats found!")
            
            self.status_var.set("Video information loaded successfully")
            self.log_message("Video information loaded successfully")
            
            # Show the Video Information section now that we have data
            self.info_frame.grid()
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self.handle_fetch_error(f"Error processing video info: {str(e)}\n{error_details}")
        finally:
            self.fetch_btn.config(state="normal")
            
    def handle_fetch_error(self, error_msg):
        """Handle errors during video info fetching"""
        # Log the full error to the log text
        self.log_message("="*50)
        self.log_message("ERROR DETAILS:")
        self.log_message(error_msg)
        self.log_message("="*50)
        
        self.status_var.set("Error fetching video information")
        
        # Hide the Video Information section on error
        self.info_frame.grid_remove()
        
        # Show simplified error to user
        if "traceback" in error_msg.lower():
            # Extract just the main error message
            lines = error_msg.split('\n')
            main_error = lines[0] if lines else error_msg
        else:
            main_error = error_msg
            
        messagebox.showerror("Fetch Error", f"{main_error}\n\nCheck the log for more details.")
        self.fetch_btn.config(state="normal")
        
    def download_ffmpeg_gui(self):
        """Download portable FFmpeg with GUI feedback"""
        import subprocess
        import zipfile
        import urllib.request
        
        result = messagebox.askyesno(
            "Download FFmpeg",
            "FFmpeg is required for MP3 conversion.\n\n"
            "Download portable FFmpeg (~100MB)?\n"
            "It will be installed to the app folder only.\n\n"
            "This may take a few minutes..."
        )
        
        if not result:
            return
        
        self.log_message("=" * 50)
        self.log_message("Starting FFmpeg download...")
        
        # Disable buttons during download
        if hasattr(self, 'ffmpeg_btn'):
            self.ffmpeg_btn.config(state="disabled", text="Downloading...")
        self.download_btn.config(state="disabled")
        
        def download_thread():
            try:
                # Get app directory
                if getattr(sys, 'frozen', False):
                    app_dir = os.path.dirname(sys.executable)
                else:
                    app_dir = os.path.dirname(os.path.abspath(__file__))
                
                ffmpeg_dir = os.path.join(app_dir, "ffmpeg", "bin")
                os.makedirs(ffmpeg_dir, exist_ok=True)
                
                # Download URL
                url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
                zip_path = os.path.join(app_dir, "ffmpeg_temp.zip")
                
                self.root.after(0, self.log_message, "Downloading FFmpeg from gyan.dev...")
                self.root.after(0, self.status_var.set, "Downloading FFmpeg...")
                
                # Download with progress
                def reporthook(count, block_size, total_size):
                    if total_size > 0:
                        percent = int(count * block_size * 100 / total_size)
                        if percent <= 100:
                            self.root.after(0, self.progress_var.set, percent)
                            self.root.after(0, self.status_var.set, 
                                          f"Downloading FFmpeg... {percent}%")
                
                urllib.request.urlretrieve(url, zip_path, reporthook)
                
                self.root.after(0, self.log_message, "Download complete! Extracting...")
                self.root.after(0, self.status_var.set, "Extracting FFmpeg...")
                self.root.after(0, self.progress_var.set, 0)
                
                # Extract
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    # Find ffmpeg.exe and ffprobe.exe in the zip
                    for file in zip_ref.namelist():
                        if file.endswith(('ffmpeg.exe', 'ffprobe.exe', 'ffplay.exe')):
                            # Extract just these files
                            file_data = zip_ref.read(file)
                            file_name = os.path.basename(file)
                            target_path = os.path.join(ffmpeg_dir, file_name)
                            with open(target_path, 'wb') as f:
                                f.write(file_data)
                            self.root.after(0, self.log_message, f"Extracted: {file_name}")
                
                # Clean up
                os.remove(zip_path)
                
                self.root.after(0, self.log_message, "✅ FFmpeg installed successfully!")
                self.root.after(0, self.log_message, f"Location: {ffmpeg_dir}")
                self.root.after(0, self.log_message, "You can now download MP3 audio! 🎵")
                self.root.after(0, self.status_var.set, "FFmpeg ready!")
                self.root.after(0, self.progress_var.set, 100)
                
                # Update FFmpeg status and reload audio options
                self.root.after(0, self._update_after_ffmpeg_install)
                
                self.root.after(0, messagebox.showinfo, "Success", 
                              "FFmpeg installed successfully!\nYou can now download MP3 audio.")
                
            except Exception as e:
                error_msg = f"Failed to download FFmpeg: {str(e)}"
                self.root.after(0, self.log_message, f"❌ {error_msg}")
                self.root.after(0, self.status_var.set, "FFmpeg download failed")
                self.root.after(0, self.progress_var.set, 0)
                
                # Re-enable button
                if hasattr(self, 'ffmpeg_btn'):
                    self.root.after(0, self.ffmpeg_btn.config, 
                                  {"state": "normal", "text": "📥 Get FFmpeg (for MP3)"})
                
                self.root.after(0, messagebox.showerror, "Download Failed", error_msg)
        
        # Start download in background thread
        thread = threading.Thread(target=download_thread, daemon=True)
        thread.start()
    
    def _update_after_ffmpeg_install(self):
        """Update UI after FFmpeg is installed"""
        # Hide the FFmpeg button
        if hasattr(self, 'ffmpeg_btn'):
            self.ffmpeg_btn.pack_forget()
        
        # Re-check FFmpeg availability
        self.ffmpeg_available = check_ffmpeg()
        
        # Update audio format options to include MP3
        if self.ffmpeg_available:
            audio_options = [
                ("Best Audio (m4a/webm)", "bestaudio"),
                ("MP3 (Best Quality)", "bestaudio[ext=m4a]/bestaudio"),
                ("MP3 (320kbps)", "bestaudio[ext=m4a]/bestaudio"),
                ("MP3 (192kbps)", "bestaudio[ext=m4a]/bestaudio"),
                ("MP3 (128kbps)", "bestaudio[ext=m4a]/bestaudio"),
                ("High Quality (128kbps+)", "bestaudio[abr>=128]"),
                ("Medium Quality (64-128kbps)", "bestaudio[abr>=64][abr<128]"),
            ]
            self.log_message("✅ MP3 formats are now available!")
        else:
            audio_options = [
                ("Best Audio (m4a/webm)", "bestaudio"),
                ("High Quality (128kbps+)", "bestaudio[abr>=128]"),
                ("Medium Quality (64-128kbps)", "bestaudio[abr>=64][abr<128]"),
            ]
        
        # Update combobox
        self.audio_format_combo['values'] = [opt[0] for opt in audio_options]
        self.audio_format_options = {opt[0]: opt[1] for opt in audio_options}
        self.audio_format_combo.current(0)
        
        # Re-enable download button if video info is loaded
        if self.video_info:
            self.download_btn.config(state="normal")
        
        self.log_message("Audio format options updated!")
    
    def browse_path(self):
        """Browse for download directory"""
        path = filedialog.askdirectory(initialdir=self.download_path)
        if path:
            self.download_path = path
            self.path_var.set(path)
            
    def start_download(self):
        """Start the download process"""
        # Check if it's a playlist download
        if self.is_playlist:
            return self.start_playlist_download()
        
        if not self.video_info:
            messagebox.showerror("Error", "Please fetch video information first")
            return
        
        dtype = self.download_type.get()
        # Get the selected format based on download type
        if dtype == "video":
            selected_format = self.video_format_var.get()
            format_id = self.video_format_options.get(selected_format)
            if not selected_format:
                messagebox.showerror("Error", "Please select a video quality first")
                return
        elif dtype == "audio":
            selected_format = self.audio_format_var.get()
            format_id = self.audio_format_options.get(selected_format)
            if not selected_format:
                messagebox.showerror("Error", "Please select an audio quality first")
                return
        elif dtype == "thumbnail":
            selected_format = "thumbnail"
            format_id = None
        elif dtype == "subtitles":
            selected_format = "subtitles"
            format_id = None
            
        self.download_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress_var.set(0)
        
        self.log_message(f"Starting download: {selected_format}")
        self.status_var.set("Downloading...")
        
        def download():
            try:
                # Re-check FFmpeg availability right before download
                self.ffmpeg_available = check_ffmpeg()
                
                ydl_opts = {
                    'outtmpl': os.path.join(self.download_path, '%(title)s.%(ext)s'),
                    'progress_hooks': [self.progress_hook],
                }
                
                # Apply parallel download options (IDM-style speed boost)
                parallel_opts = self._get_parallel_download_opts()
                ydl_opts.update(parallel_opts)
                
                # Log speed settings
                if parallel_opts.get('concurrent_fragment_downloads', 1) > 1:
                    self.root.after(0, self.log_message, f"⚡ Using {parallel_opts['concurrent_fragment_downloads']} parallel connections")
                if parallel_opts.get('external_downloader') == 'aria2c':
                    self.root.after(0, self.log_message, f"⚡ Using aria2c with {self.aria2c_connections.get()} connections per server")
                
                if dtype == "thumbnail":
                    # Only download thumbnail in best available quality
                    ydl_opts.update({
                        'skip_download': True,
                        'writethumbnail': True,
                    })
                    # Convert thumbnails to selected format (unless 'original' chosen)
                    try:
                        thumb_fmt = self.thumb_format_var.get()
                    except Exception:
                        thumb_fmt = 'jpg'
                    if thumb_fmt and thumb_fmt != 'original':
                        ydl_opts['convert_thumbnails'] = thumb_fmt

                    # Allow custom output name for thumbnail
                    try:
                        thumb_name = self.thumb_name_var.get().strip()
                    except Exception:
                        thumb_name = '%(title)s_thumbnail'
                    if not thumb_name:
                        thumb_name = '%(title)s_thumbnail'
                    # Ensure outtmpl uses %(ext)s so converted extension is applied
                    ydl_opts['outtmpl'] = os.path.join(self.download_path, thumb_name + '.%(ext)s')
                    self.root.after(0, self.log_message, "🖼️ Saving thumbnail only")
                elif dtype == "subtitles":
                    # Only download subtitles
                    ydl_opts.update({
                        'skip_download': True,
                        'writesubtitles': True,
                        # Base throttling
                        'retries': lambda: int(self.subs_backoff_max_attempts.get()) if hasattr(self, 'subs_backoff_max_attempts') else 8,
                        'extractor_retries': 4,
                        'sleep_requests': lambda: float(self.subs_backoff_base_sleep.get()) if hasattr(self, 'subs_backoff_base_sleep') else 2.0,
                        'http_headers': {'Accept-Language': 'en-US,en;q=0.9'}
                    })
                    # Decide language strategy:
                    all_langs = self.subs_all_var.get()
                    auto_gen = self.subs_auto_var.get()
                    langs_raw = [s.strip() for s in self.subs_langs_var.get().split(',') if s.strip()]
                    # If both all languages and auto subtitles selected, log warning and prefer explicit list + auto
                    if all_langs and auto_gen:
                        self.root.after(0, self.log_message, "⚠️ Both 'all languages' and 'auto-generated' selected. Limiting to provided list + auto to avoid HTTP 429.")
                        all_langs = False  # override to reduce requests
                        if not langs_raw:
                            langs_raw = ['en']
                    if all_langs:
                        ydl_opts['allsubtitles'] = True
                    else:
                        # Filter obvious malformed codes (allow patterns like en-*)
                        valid_langs = []
                        for code in langs_raw:
                            if re.match(r'^[a-zA-Z]{2}(?:-[a-zA-Z0-9*]+)?$', code):
                                valid_langs.append(code)
                            else:
                                self.root.after(0, self.log_message, f"🚫 Ignoring invalid subtitle language code: {code}")
                        if valid_langs:
                            ydl_opts['subtitleslangs'] = valid_langs
                    if auto_gen:
                        ydl_opts['writeautomaticsub'] = True
                    subfmt = self.subs_format_var.get()
                    if subfmt and subfmt != 'best':
                        ydl_opts['subtitlesformat'] = subfmt
                    self.root.after(0, self.log_message, "💬 Saving subtitles only")
                elif dtype == "audio":
                    # Check if user selected MP3 format
                    is_mp3_requested = "MP3" in selected_format
                    if is_mp3_requested:
                        if self.ffmpeg_available:
                            if "320" in selected_format or "Best Quality" in selected_format:
                                quality = '320'
                            elif "192" in selected_format:
                                quality = '192'
                            elif "128" in selected_format:
                                quality = '128'
                            else:
                                quality = '320'
                            ydl_opts.update({
                                'format': 'bestaudio/best',
                                'postprocessors': [{
                                    'key': 'FFmpegExtractAudio',
                                    'preferredcodec': 'mp3',
                                    'preferredquality': quality,
                                }],
                            })
                            self.root.after(0, self.log_message, f"✅ Using FFmpeg to convert to MP3 ({quality} kbps)")
                        else:
                            ydl_opts['format'] = 'bestaudio/best'
                            self.root.after(0, self.log_message, 
                                            "⚠️ FFmpeg not available - Downloading audio in original format (webm/m4a)")
                            self.root.after(0, self.log_message, 
                                            "Click 'Get FFmpeg' button for MP3 conversion")
                    else:
                        ydl_opts['format'] = format_id
                else:
                    # Video - merge with best audio (DASH streams are video-only)
                    # format_id+bestaudio means: download format_id video + best audio, then merge
                    ydl_opts['format'] = f"{format_id}+bestaudio/best"
                    
                    # Get selected output container format
                    selected_format_name = self.output_format_var.get()
                    output_container = self.output_formats.get(selected_format_name, "mp4")
                    ydl_opts['merge_output_format'] = output_container
                    
                    if self.ffmpeg_available:
                        self.root.after(0, self.log_message, f"🔊 Merging video with audio → {output_container.upper()}")
                    else:
                        self.root.after(0, self.log_message, "⚠️ FFmpeg not found - audio may be missing!")
                
                # Use adaptive backoff for subtitles to reduce HTTP 429
                self.ydl_download_with_backoff(
                    ydl_opts,
                    self.video_info['webpage_url'],
                    is_subtitles=(dtype == "subtitles"),
                    context='single'
                )

                # Post-process thumbnail conversion if yt-dlp didn't convert
                if dtype == "thumbnail":
                    try:
                        import glob
                        desired_fmt = thumb_fmt if (thumb_fmt and thumb_fmt != 'original') else None
                        if desired_fmt:
                            pattern = os.path.join(self.download_path, thumb_name + '.*')
                            matches = glob.glob(pattern)
                            if matches:
                                src = matches[0]
                                src_ext = os.path.splitext(src)[1].lstrip('.').lower()
                                if src_ext != desired_fmt.lower():
                                    try:
                                        img = Image.open(src)
                                        # Handle alpha when converting to JPEG
                                        tgt_path = os.path.join(self.download_path, thumb_name + '.' + desired_fmt)
                                        if desired_fmt.lower() in ('jpg', 'jpeg'):
                                            if img.mode in ('RGBA', 'LA'):
                                                bg = Image.new('RGB', img.size, (255, 255, 255))
                                                alpha = img.split()[-1]
                                                bg.paste(img.convert('RGBA'), mask=alpha)
                                                img = bg
                                            else:
                                                img = img.convert('RGB')
                                        else:
                                            # Ensure PIL can save the format
                                            if img.mode == 'P':
                                                img = img.convert('RGBA')
                                        img.save(tgt_path)
                                        self.root.after(0, self.log_message, f"🖼️ Converted thumbnail to {desired_fmt.upper()}")
                                        # Remove original if different
                                        try:
                                            if os.path.abspath(src) != os.path.abspath(tgt_path):
                                                os.remove(src)
                                        except Exception:
                                            pass
                                    except Exception as e:
                                        self.root.after(0, self.log_message, f"⚠️ Thumbnail conversion failed: {e}")
                    except Exception:
                        pass

                self.root.after(0, self.download_complete)
                
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                
                # Check if it's an FFmpeg error
                if 'ffmpeg' in str(e).lower() or 'postprocessing' in str(e).lower():
                    error_msg = ("FFmpeg Error: Audio conversion failed!\n\n"
                               "FFmpeg is not installed or not accessible.\n\n"
                               "To fix this:\n"
                               "1. Download FFmpeg: https://ffmpeg.org/download.html\n"
                               "2. Extract and add to system PATH\n"
                               "3. Restart the application\n\n"
                               f"Technical details: {str(e)}")
                else:
                    error_msg = f"Download error: {str(e)}\n\n{error_details}"
                    
                self.root.after(0, self.download_error, error_msg)
        
        self.download_thread = threading.Thread(target=download, daemon=True)
        self.download_thread.start()
    
    def start_playlist_download(self):
        """Download selected playlist items"""
        # Get selected indices
        selected_indices = self.playlist_listbox.curselection()
        
        if not selected_indices:
            messagebox.showwarning("No Selection", "Please select at least one video to download")
            return
        
        # Get selected entries
        selected_entries = [self.playlist_entries[i] for i in selected_indices]
        total_count = len(selected_entries)
        
        self.log_message(f"📑 Starting playlist download: {total_count} videos")
        
        # Get format settings
        dtype = self.download_type.get()
        if dtype == "video":
            selected_format = self.video_format_var.get()
            format_id = self.video_format_options.get(selected_format)
        elif dtype == "audio":
            selected_format = self.audio_format_var.get()
            format_id = self.audio_format_options.get(selected_format)
        else:
            selected_format = dtype
            format_id = None
        
        self.download_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        
        def download_playlist():
            try:
                for idx, entry in enumerate(selected_entries, 1):
                    video_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                    video_title = entry.get('title', 'Unknown')
                    
                    self.root.after(0, self.log_message, f"[{idx}/{total_count}] Downloading: {video_title}")
                    self.root.after(0, self.status_var.set, f"Downloading {idx}/{total_count}: {video_title[:50]}...")
                    
                    # Re-check FFmpeg availability
                    self.ffmpeg_available = check_ffmpeg()

                    ydl_opts = {
                        'outtmpl': os.path.join(self.download_path, '%(title)s.%(ext)s'),
                        'progress_hooks': [lambda d: self.root.after(0, self.playlist_progress_hook, d, idx, total_count)],
                    }
                    
                    # Apply parallel download options (IDM-style speed boost)
                    parallel_opts = self._get_parallel_download_opts()
                    ydl_opts.update(parallel_opts)

                    if dtype == "thumbnail":
                        ydl_opts.update({'skip_download': True, 'writethumbnail': True})
                        if self.thumb_convert_jpg.get():
                            ydl_opts['convert_thumbnails'] = 'jpg'
                    elif dtype == "subtitles":
                        ydl_opts.update({
                            'skip_download': True,
                            'writesubtitles': True,
                            'retries': lambda: int(self.subs_backoff_max_attempts.get()) if hasattr(self, 'subs_backoff_max_attempts') else 8,
                            'extractor_retries': 4,
                            'sleep_requests': lambda: float(self.subs_backoff_base_sleep.get()) if hasattr(self, 'subs_backoff_base_sleep') else 2.0,
                            'http_headers': {'Accept-Language': 'en-US,en;q=0.9'}
                        })
                        all_langs = self.subs_all_var.get()
                        auto_gen = self.subs_auto_var.get()
                        langs_raw = [s.strip() for s in self.subs_langs_var.get().split(',') if s.strip()]
                        if all_langs and auto_gen:
                            self.root.after(0, self.log_message, "⚠️ Both 'all languages' and 'auto-generated' selected. Limiting to provided list + auto to avoid HTTP 429.")
                            all_langs = False
                            if not langs_raw:
                                langs_raw = ['en']
                        if all_langs:
                            ydl_opts['allsubtitles'] = True
                        else:
                            valid_langs = []
                            for code in langs_raw:
                                if re.match(r'^[a-zA-Z]{2}(?:-[a-zA-Z0-9*]+)?$', code):
                                    valid_langs.append(code)
                                else:
                                    self.root.after(0, self.log_message, f"🚫 Ignoring invalid subtitle language code: {code}")
                            if valid_langs:
                                ydl_opts['subtitleslangs'] = valid_langs
                        if auto_gen:
                            ydl_opts['writeautomaticsub'] = True
                        subfmt = self.subs_format_var.get()
                        if subfmt and subfmt != 'best':
                            ydl_opts['subtitlesformat'] = subfmt
                    elif dtype == "audio":
                        is_mp3_requested = "MP3" in selected_format
                        if is_mp3_requested:
                            if self.ffmpeg_available:
                                quality = '320'
                                if "192" in selected_format:
                                    quality = '192'
                                elif "128" in selected_format:
                                    quality = '128'
                                ydl_opts.update({
                                    'format': 'bestaudio/best',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': quality,
                                    }],
                                })
                            else:
                                ydl_opts['format'] = 'bestaudio/best'
                        else:
                            ydl_opts['format'] = format_id
                    else:
                        # Video - merge with best audio (DASH streams are video-only)
                        ydl_opts['format'] = f"{format_id}+bestaudio/best"
                        # Get selected output container format
                        selected_format_name = self.output_format_var.get()
                        output_container = self.output_formats.get(selected_format_name, "mp4")
                        ydl_opts['merge_output_format'] = output_container
                    
                    # Adaptive backoff for subtitles entries
                    self.ydl_download_with_backoff(
                        ydl_opts,
                        video_url,
                        is_subtitles=(dtype == "subtitles"),
                        context=f'playlist item {idx}/{total_count}'
                    )
                    
                    self.root.after(0, self.log_message, f"✅ [{idx}/{total_count}] Completed: {video_title}")
                
                self.root.after(0, self.playlist_download_complete, total_count)
                
            except Exception as e:
                error_msg = f"Playlist download error: {str(e)}"
                self.root.after(0, self.download_error, error_msg)
        
        threading.Thread(target=download_playlist, daemon=True).start()
    
    def playlist_progress_hook(self, d, current, total):
        """Handle playlist download progress"""
        if d['status'] == 'downloading':
            try:
                if 'total_bytes' in d:
                    progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                elif 'total_bytes_estimate' in d:
                    progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                else:
                    return
                
                self.progress_var.set(progress)
                speed = d.get('speed', 0)
                if speed:
                    speed_mb = speed / (1024 * 1024)
                    self.status_var.set(f"[{current}/{total}] Downloading... {progress:.1f}% @ {speed_mb:.2f} MB/s")
            except:
                pass
        elif d['status'] == 'finished':
            self.progress_var.set(100)
    
    def playlist_download_complete(self, count):
        """Handle playlist download completion"""
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.progress_var.set(100)
        self.status_var.set(f"✅ Playlist complete! {count} videos downloaded")
        self.log_message(f"🎉 Playlist download complete! Downloaded {count} videos")
        messagebox.showinfo("Success", f"Playlist download complete!\n\n{count} videos downloaded successfully.")
    
    def progress_hook(self, d):
        """Handle download progress updates"""
        if d['status'] == 'downloading':
            try:
                if 'total_bytes' in d:
                    progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                elif 'total_bytes_estimate' in d:
                    progress = (d['downloaded_bytes'] / d['total_bytes_estimate']) * 100
                else:
                    return
                    
                self.root.after(0, self.update_progress, progress, d)
            except:
                pass
        elif d['status'] == 'finished':
            self.root.after(0, self.update_progress, 100, d)
            
    def update_progress(self, progress, d):
        """Update progress bar and status"""
        self.progress_var.set(progress)
        
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        speed = d.get('speed', 0)
        
        if speed:
            speed_str = f"{speed / 1024 / 1024:.1f} MB/s"
        else:
            speed_str = "0 MB/s"
            
        if total:
            downloaded_mb = downloaded / 1024 / 1024
            total_mb = total / 1024 / 1024
            status = f"Downloading... {downloaded_mb:.1f}/{total_mb:.1f} MB ({progress:.1f}%) - {speed_str}"
        else:
            status = f"Downloading... {progress:.1f}% - {speed_str}"
            
        self.status_var.set(status)
        
    def download_complete(self):
        """Handle download completion"""
        self.progress_var.set(100)
        self.status_var.set("Download completed successfully!")
        self.log_message("Download completed successfully!")
        
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        
        messagebox.showinfo("Success", "Download completed successfully!")
        
    def download_error(self, error_msg):
        """Handle download errors"""
        self.log_message(error_msg)
        self.status_var.set("Download failed")
        
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        
        messagebox.showerror("Download Error", error_msg)
        
    def cancel_download(self):
        """Cancel the current download"""
        self.log_message("Download cancelled by user")
        self.status_var.set("Download cancelled")
        
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
    
    def _init_clipboard_monitor(self):
        """Initialize the clipboard monitor using the new component"""
        def on_url_detected(url: str, auto_pasted: bool):
            """Callback when clipboard URL is detected"""
            self.status_var.set("URL detected in clipboard!")
            self.log_message("Clipboard: Video URL detected!")
            
            if auto_pasted:
                self.log_message("URL auto-pasted from clipboard")
                self.fetch_btn.focus_set()
            else:
                self.log_message("New URL detected, but URL field is not empty")
        
        # Create clipboard monitor config
        config = ClipboardMonitorConfig(
            check_interval_ms=1000,
            enabled=True,
            auto_paste_when_empty=True,
        )
        
        # Create clipboard monitor with callbacks
        self.clipboard_monitor = ClipboardMonitor(
            on_url_detected=on_url_detected,
            get_current_url=lambda: self.url_var.get(),
            set_url=lambda url: self.url_var.set(url),
            config=config,
        )
        
        # Start monitoring using tkinter's scheduler
        self.clipboard_monitor.start(scheduler=self.root.after)
    
    def toggle_clipboard_monitor(self):
        """Toggle clipboard monitoring on/off"""
        if self.clipboard_monitor_enabled.get():
            self.clipboard_monitor.enabled = True
            self.log_message("Clipboard monitor enabled - Auto-detecting URLs")
            self.status_var.set("Clipboard monitor: ON")
        else:
            self.clipboard_monitor.enabled = False
            self.log_message("Clipboard monitor paused")
            self.status_var.set("Clipboard monitor: OFF")
    
    def select_all_playlist(self):
        """Select all playlist items"""
        self.playlist_listbox.selection_set(0, tk.END)
        self.log_message(f"Selected all {len(self.playlist_entries)} playlist items")
    
    def select_none_playlist(self):
        """Deselect all playlist items"""
        self.playlist_listbox.selection_clear(0, tk.END)
        self.log_message("⏹️ Cleared playlist selection")
    
    def clear_all(self):
        """Clear all fields and reset the interface"""
        self.url_var.set("")
        self.title_var.set("")
        self.duration_var.set("")
        self.uploader_var.set("")
        self.views_var.set("")
        self.video_format_var.set("")
        self.video_format_combo['values'] = []
        self.audio_format_combo.current(0)  # Reset to default audio quality
        self.progress_var.set(0)
        self.status_var.set("Ready")
        self.log_text.delete(1.0, tk.END)
        
        # Reset thumbnail
        self.thumbnail_label.configure(image='', text="No thumbnail")
        self.thumbnail_label.image = None
        
        # Reset playlist
        self.is_playlist = False
        self.playlist_entries = []
        self.playlist_frame.grid_remove()
        self.playlist_listbox.delete(0, tk.END)
        self.playlist_info_var.set("")
        
        # Hide Video Information section
        self.info_frame.grid_remove()
        
        self.video_info = None
        self.download_btn.config(state="disabled")
        self.cancel_btn.config(state="disabled")


def main():
    """Main function to run the application"""
    root = tk.Tk()
    app = VideoDownloader(root)
    
    # Center the window
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - (root.winfo_width() // 2)
    y = (root.winfo_screenheight() // 2) - (root.winfo_height() // 2)
    root.geometry(f"+{x}+{y}")
    
    root.mainloop()


if __name__ == "__main__":
    main()