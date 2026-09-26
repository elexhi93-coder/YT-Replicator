"""
Ultra-Advanced Playlist Manager Window
Professional-grade playlist/channel download management system
Features: Real-time analysis, smart sorting, batch operations, parallel downloads
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import yt_dlp
import threading
import re
from pathlib import Path
from datetime import timedelta, datetime
import datetime as dt  # For datetime.datetime references
import json
import os
from queue import Queue
import time


class AdvancedPlaylistManager:
    """Ultra-advanced window for managing playlist/channel downloads"""
    
    def __init__(self, parent, playlist_info, playlist_entries, log_callback):
        self.parent = parent
        self.playlist_info = playlist_info
        self.playlist_entries = playlist_entries
        self.log_callback = log_callback
        self.is_advanced_mode = False
        self.video_qualities = {}  # Store fetched qualities per video
        self.is_downloading = False
        self.cancel_flag = False
        self.is_paused = False  # Pause/resume state
        self.download_queue = Queue()
        self.failed_downloads = []
        self.completed_downloads = []
        # Store video item widgets (initialized early to avoid UI event race)
        self.video_item_widgets = []
        # Thread safety lock for download state
        self.download_lock = threading.Lock()
        # Pause event for thread synchronization
        self.pause_event = threading.Event()
        self.pause_event.set()  # Initially not paused
        
        # Settings
        self.parallel_downloads = tk.IntVar(value=1)
        self.auto_retry = tk.BooleanVar(value=True)
        self.show_thumbnails = tk.BooleanVar(value=False)
        
        # Initialize critical variables early (before UI) to prevent context menu errors
        self.download_type = tk.StringVar(value="video")
        self.quality_var = tk.StringVar(value="Best Available")
        self.audio_quality_var = tk.StringVar(value="Best Audio (m4a/webm)")
        self.output_format_var = tk.StringVar(value="mp4")
        self.output_formats = {
            "MP4 (H.264/AAC) - Recommended": "mp4",
            "MKV (Matroska)": "mkv",
            "WebM (VP9/Opus)": "webm",
            "MOV (QuickTime)": "mov",
            "AVI": "avi",
            "FLV (Flash)": "flv",
            "3GP (Mobile)": "3gp",
        }
        self.path_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.filename_template_var = tk.StringVar(value="{title}")
        
        # Folder per video settings
        self.folder_per_video = tk.BooleanVar(value=False)   # Create a folder for each video
        self.folder_save_thumbnail = tk.BooleanVar(value=True)
        self.folder_save_metadata = tk.BooleanVar(value=True)
        self.folder_save_subtitles = tk.BooleanVar(value=False)
        self.folder_save_description = tk.BooleanVar(value=False)
        
        # Video split settings
        self.split_enabled = tk.BooleanVar(value=False)
        self.split_threshold_min = tk.IntVar(value=60)  # Only split if video > this many minutes
        self.split_segment_min = tk.IntVar(value=30)    # Split into segments of this many minutes
        self.split_save_thumbnail = tk.BooleanVar(value=True)
        self.split_save_metadata = tk.BooleanVar(value=True)
        
        # Speed optimization settings (IDM-style multi-connection)
        self.concurrent_fragments = tk.IntVar(value=4)   # Parallel fragment downloads (DASH/HLS)
        self.use_aria2c = tk.BooleanVar(value=False)     # Use aria2c external downloader
        self.aria2c_connections = tk.IntVar(value=16)    # Connections per server for aria2c
        self.aria2c_available = self._check_aria2c()     # Check if aria2c is installed
        
        # Detect FFmpeg location (portable or system)
        self.ffmpeg_location = self._detect_ffmpeg()
        
        # Initialize group management
        self.groups = {}  # {group_name: {'color': '#RRGGBB', 'settings': {...}}}
        self.group_settings = {}  # {group_name: {'quality': '1080p', 'format': 'mp4', ...}}
        
        # Create window
        self.window = tk.Toplevel(parent)
        self.window.title(f"🎬 Advanced Playlist Manager - {playlist_info.get('title', 'Playlist')[:50]}")
        self.window.geometry("1400x850")
        self.window.resizable(True, True)
        
        # Analyze playlist
        self.analyze_playlist()
        
        self.setup_ui()
        self.populate_video_list()
    
    def _detect_ffmpeg(self):
        """Detect FFmpeg location - check portable folder first, then system PATH"""
        import shutil
        import subprocess
        try:
            app_dir = Path(__file__).parent
            portable_ffmpeg = app_dir / "ffmpeg" / "bin" / "ffmpeg.exe"
            if portable_ffmpeg.exists():
                # Add to PATH for this session
                ffmpeg_bin_dir = str(portable_ffmpeg.parent)
                if ffmpeg_bin_dir not in os.environ.get('PATH', ''):
                    os.environ['PATH'] = ffmpeg_bin_dir + os.pathsep + os.environ.get('PATH', '')
                self.log_callback(f"✅ FFmpeg found (portable): {portable_ffmpeg}")
                return str(portable_ffmpeg.parent)
            # Check system PATH
            ffmpeg_path = shutil.which('ffmpeg')
            if ffmpeg_path:
                self.log_callback(f"✅ FFmpeg found (system): {ffmpeg_path}")
                return str(Path(ffmpeg_path).parent)
        except Exception as e:
            self.log_callback(f"⚠️ FFmpeg detection error: {e}")
        self.log_callback("⚠️ FFmpeg not found - audio merging/conversion may fail")
        return None

    @staticmethod
    def _check_aria2c():
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
        
        # Speed up non-fragmented downloads with chunked transfer (10MB chunks)
        opts['http_chunk_size'] = 10485760
        
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

    def analyze_playlist(self):
        """Analyze playlist statistics"""
        total_duration = 0
        count = 0
        
        for entry in self.playlist_entries:
            duration = entry.get('duration', 0)
            if duration:
                total_duration += int(duration) if duration else 0
                count += 1
        
        self.total_duration = total_duration
        self.avg_duration = total_duration / count if count > 0 else 0
        self.video_count = len(self.playlist_entries)
    
    def setup_ui(self):
        """Setup the advanced UI"""
        # Main container
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=3)
        main_frame.columnconfigure(1, weight=1, minsize=320)
        main_frame.rowconfigure(1, weight=1)
        
        # === TOP SECTION: Header and Statistics ===
        self.create_header_section(main_frame)
        
        # === MIDDLE SECTION: Video List (Left) and Control Panel (Right) ===
        # Left: Video list
        list_container = ttk.Frame(main_frame)
        list_container.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        list_container.columnconfigure(0, weight=1)
        list_container.rowconfigure(1, weight=1)
        
        self.create_toolbar(list_container)
        self.create_video_list(list_container)
        
        # Right: Control panel with scrollbar
        control_panel_container = ttk.Frame(main_frame)
        control_panel_container.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        control_panel_container.columnconfigure(0, weight=1)
        control_panel_container.rowconfigure(0, weight=1)
        
        # Create canvas and scrollbar for control panel
        self.control_canvas = tk.Canvas(control_panel_container, highlightthickness=0, width=300)
        control_scrollbar = ttk.Scrollbar(control_panel_container, orient="vertical", command=self.control_canvas.yview)
        control_panel = ttk.Frame(self.control_canvas)
        
        control_panel.bind(
            "<Configure>",
            lambda e: self.control_canvas.configure(scrollregion=self.control_canvas.bbox("all"))
        )
        
        self.control_canvas.create_window((0, 0), window=control_panel, anchor="nw")
        self.control_canvas.configure(yscrollcommand=control_scrollbar.set)
        
        self.control_canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        control_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        control_panel.columnconfigure(0, weight=1)
        
        # Bind mousewheel ONLY to the control canvas, not globally
        def _on_control_mousewheel(event):
            self.control_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.control_canvas.bind("<MouseWheel>", _on_control_mousewheel)
        control_panel.bind("<MouseWheel>", _on_control_mousewheel)
        
        self.create_control_panel(control_panel)
        
        # === BOTTOM SECTION: Preview (left) and Progress (right) ===
        self.create_bottom_section(main_frame)
        
    
    def create_header_section(self, parent):
        """Create compact header with title and statistics"""
        header_frame = ttk.LabelFrame(parent, text="📊 Playlist", padding="5")
        header_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5))
        header_frame.columnconfigure(1, weight=1)
        
        # Row 0: Title, stats, and mode all in ONE ROW
        row0_frame = ttk.Frame(header_frame)
        row0_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 3))
        
        # Title (compact)
        uploader = self.playlist_info.get('uploader', '')
        channel_id = self.playlist_info.get('channel_id', '')
        icon = "📺" if (uploader or channel_id) else "📑"
        title_text = self.playlist_info.get('title', 'Unknown')[:40]
        ttk.Label(row0_frame, text=f"{icon} {title_text}", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 15))
        
        # Stats (compact inline)
        ttk.Label(row0_frame, text=f"📹 {self.video_count}", font=('Arial', 8)).pack(side=tk.LEFT, padx=(0, 10))
        total_time_str = str(timedelta(seconds=self.total_duration))
        ttk.Label(row0_frame, text=f"⏱️ {total_time_str}", font=('Arial', 8)).pack(side=tk.LEFT, padx=(0, 10))
        
        # Selected count
        self.selected_count_var = tk.StringVar(value=f"✓ {self.video_count}")
        ttk.Label(row0_frame, textvariable=self.selected_count_var, 
                 font=('Arial', 8, 'bold'), foreground='green').pack(side=tk.LEFT, padx=(0, 15))
        
        # Mode indicator (inline)
        self.mode_indicator = ttk.Label(row0_frame, text="📋 Simple", 
                                       font=('Arial', 8, 'bold'), foreground='blue')
        self.mode_indicator.pack(side=tk.LEFT, padx=(0, 5))
        
        # Mode button (compact)
        self.mode_btn = ttk.Button(row0_frame, text="⚡ Advanced", 
                                   command=self.toggle_mode, width=10)
        self.mode_btn.pack(side=tk.LEFT)
        
        # Row 1: Fetch options (compact single row)
        fetch_frame = ttk.Frame(header_frame)
        fetch_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 0))
        
        # Fetch mode checkbox
        self.fetch_full_metadata = tk.BooleanVar(value=False)
        ttk.Checkbutton(fetch_frame, text="Full metadata (slower, includes dates)", 
                       variable=self.fetch_full_metadata).pack(side=tk.LEFT, padx=(0, 10))
        
        # Limit videos dropdown
        ttk.Label(fetch_frame, text="Limit:").pack(side=tk.LEFT, padx=(0, 5))
        self.limit_videos_var = tk.StringVar(value="All")
        limit_combo = ttk.Combobox(fetch_frame, textvariable=self.limit_videos_var, 
                                   state="readonly", width=12)
        limit_combo['values'] = ['All', 'First 5', 'First 10', 'First 15', 'First 20', 
                                 'First 30', 'First 50', 'First 100']
        limit_combo.pack(side=tk.LEFT, padx=(0, 10))
        
        # Date filter dropdown
        ttk.Label(fetch_frame, text="Date:").pack(side=tk.LEFT, padx=(0, 5))
        self.date_filter_var = tk.StringVar(value="All time")
        date_combo = ttk.Combobox(fetch_frame, textvariable=self.date_filter_var, 
                                 state="readonly", width=15)
        date_combo['values'] = ['All time', 'Last 24 hours', 'Last 3 days', 'Last week', 
                               'Last 2 weeks', 'Last month', 'Last 3 months', 'Last 6 months', 'Last year']
        date_combo.pack(side=tk.LEFT, padx=(0, 10))
        
        # Fetch / Reload button
        self.fetch_btn = ttk.Button(fetch_frame, text="📥 Reload", command=self.start_fetch_entries, width=8)
        self.fetch_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Fetch status (inline)
        self.fetch_status_var = tk.StringVar(value="")
        self.fetch_status_label = ttk.Label(fetch_frame, textvariable=self.fetch_status_var, font=('Arial', 7), foreground='gray')
        self.fetch_status_label.pack(side=tk.LEFT)
        
        # Mode description (empty initially, used by toggle_mode)
        self.mode_description = ttk.Label(header_frame, text="", font=('Arial', 7, 'italic'), foreground='gray')
        self.mode_description.grid(row=2, column=0, sticky=tk.W)
    
    def create_toolbar(self, parent):
        """Create toolbar with search, filter, and sort options"""
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        toolbar.columnconfigure(1, weight=1)
        
        # Search
        ttk.Label(toolbar, text="🔍").grid(row=0, column=0, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self.filter_videos())
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=30)
        search_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        # Sort options
        ttk.Label(toolbar, text="Sort by:").grid(row=0, column=2, padx=(0, 5))
        self.sort_var = tk.StringVar(value="Default")
        sort_combo = ttk.Combobox(toolbar, textvariable=self.sort_var, 
                                 state="readonly", width=15)
        sort_combo['values'] = ['Default', 'Title (A-Z)', 'Title (Z-A)', 
                                'Duration (Short-Long)', 'Duration (Long-Short)',
                                'Date (Newest)', 'Date (Oldest)']
        sort_combo.grid(row=0, column=3, padx=(0, 10))
        sort_combo.bind('<<ComboboxSelected>>', lambda e: self.sort_videos())
        
        # Selection buttons
        ttk.Button(toolbar, text="✓ All", width=6,
                  command=self.select_all).grid(row=0, column=4, padx=2)
        ttk.Button(toolbar, text="✗ None", width=6,
                  command=self.select_none).grid(row=0, column=5, padx=2)
        ttk.Button(toolbar, text="⟲ Invert", width=6,
                  command=self.invert_selection).grid(row=0, column=6, padx=2)
        
        # Advanced filters
        ttk.Button(toolbar, text="🔬 Filters", width=8,
                  command=self.show_advanced_filters).grid(row=0, column=7, padx=(10, 0))
        
        # Column visibility toggle
        ttk.Button(toolbar, text="👁 Columns", width=9,
                  command=self.show_column_selector).grid(row=0, column=8, padx=(10, 0))
    
    def create_video_list(self, parent):
        """Create scrollable video list using Treeview"""
        self.log_callback("🔧 Creating video list tree...")
        
        list_frame = ttk.LabelFrame(parent, text="📝 Video List", padding="5")
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # Create Treeview with columns for professional display
        columns = ('status', 'group', 'title', 'description', 'uploader', 'video_id', 'channel_id', 'url', 'thumbnail', 
                   'duration', 'duration_string', 'upload_date', 'timestamp', 'views', 'likes', 'comments', 
                   'subscribers', 'subtitles', 'resolution', 'fps', 'format', 'category', 'availability', 
                   'location', 'tags', 'tags_list', 'chapters', 'chapters_list', 'live_status', 'age_limit', 
                   'verified', 'aspect_ratio', 'language', 'filesize', 'quality', 'size', 'progress', 'speed',
                   'dl_video', 'dl_audio', 'dl_subs', 'dl_thumb')
        self.video_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings', height=20)
        
        self.log_callback(f"✅ Tree widget created: {self.video_tree}")
        
        # Track current sort column and direction
        self.current_sort_col = None
        self.sort_reverse = False
        
        # Track checkbox header state for toggle all/none
        self.all_checked = True
        
        # Configure columns with clickable headers for sorting
        self.video_tree.heading('#0', text='☑', command=self.toggle_all_checkboxes)
        self.video_tree.heading('status', text='Status', command=lambda: self.sort_by_column('status'))
        self.video_tree.heading('group', text='Group', command=lambda: self.sort_by_column('group'))
        self.video_tree.heading('title', text='Title ▼', command=lambda: self.sort_by_column('title'))
        self.video_tree.heading('description', text='Description', command=lambda: self.sort_by_column('description'))
        self.video_tree.heading('uploader', text='Uploader', command=lambda: self.sort_by_column('uploader'))
        self.video_tree.heading('video_id', text='Video ID', command=lambda: self.sort_by_column('video_id'))
        self.video_tree.heading('channel_id', text='Channel ID', command=lambda: self.sort_by_column('channel_id'))
        self.video_tree.heading('url', text='URL', command=lambda: self.sort_by_column('url'))
        self.video_tree.heading('thumbnail', text='Thumbnail URL', command=lambda: self.sort_by_column('thumbnail'))
        self.video_tree.heading('duration', text='Duration', command=lambda: self.sort_by_column('duration'))
        self.video_tree.heading('duration_string', text='Duration Str', command=lambda: self.sort_by_column('duration_string'))
        self.video_tree.heading('upload_date', text='Upload Date', command=lambda: self.sort_by_column('upload_date'))
        self.video_tree.heading('timestamp', text='Timestamp', command=lambda: self.sort_by_column('timestamp'))
        self.video_tree.heading('views', text='Views', command=lambda: self.sort_by_column('views'))
        self.video_tree.heading('likes', text='Likes', command=lambda: self.sort_by_column('likes'))
        self.video_tree.heading('comments', text='Comments', command=lambda: self.sort_by_column('comments'))
        self.video_tree.heading('subscribers', text='Subscribers', command=lambda: self.sort_by_column('subscribers'))
        self.video_tree.heading('subtitles', text='Subs', command=lambda: self.sort_by_column('subtitles'))
        self.video_tree.heading('resolution', text='Resolution', command=lambda: self.sort_by_column('resolution'))
        self.video_tree.heading('fps', text='FPS', command=lambda: self.sort_by_column('fps'))
        self.video_tree.heading('format', text='Format', command=lambda: self.sort_by_column('format'))
        self.video_tree.heading('category', text='Category', command=lambda: self.sort_by_column('category'))
        self.video_tree.heading('availability', text='Availability', command=lambda: self.sort_by_column('availability'))
        self.video_tree.heading('location', text='Location', command=lambda: self.sort_by_column('location'))
        self.video_tree.heading('tags', text='Tags #', command=lambda: self.sort_by_column('tags'))
        self.video_tree.heading('tags_list', text='Tags List', command=lambda: self.sort_by_column('tags_list'))
        self.video_tree.heading('chapters', text='Chapters #', command=lambda: self.sort_by_column('chapters'))
        self.video_tree.heading('chapters_list', text='Chapters List', command=lambda: self.sort_by_column('chapters_list'))
        self.video_tree.heading('live_status', text='Live Status', command=lambda: self.sort_by_column('live_status'))
        self.video_tree.heading('age_limit', text='Age', command=lambda: self.sort_by_column('age_limit'))
        self.video_tree.heading('verified', text='Verified', command=lambda: self.sort_by_column('verified'))
        self.video_tree.heading('aspect_ratio', text='Aspect', command=lambda: self.sort_by_column('aspect_ratio'))
        self.video_tree.heading('language', text='Lang', command=lambda: self.sort_by_column('language'))
        self.video_tree.heading('filesize', text='Filesize', command=lambda: self.sort_by_column('filesize'))
        self.video_tree.heading('quality', text='Quality', command=lambda: self.sort_by_column('quality'))
        self.video_tree.heading('size', text='Est. Size', command=lambda: self.sort_by_column('size'))
        self.video_tree.heading('progress', text='Progress', command=lambda: self.sort_by_column('progress'))
        self.video_tree.heading('speed', text='Speed/ETA', command=lambda: self.sort_by_column('speed'))
        
        # Download action columns (separate group)
        self.video_tree.heading('dl_video', text='📥 Video')
        self.video_tree.heading('dl_audio', text='🎵 Audio')
        self.video_tree.heading('dl_subs', text='📝 Subs')
        self.video_tree.heading('dl_thumb', text='🖼️ Thumb')
        
        self.video_tree.column('#0', width=50, stretch=False)
        self.video_tree.column('status', width=50, stretch=False)
        self.video_tree.column('group', width=100, stretch=False)
        self.video_tree.column('title', width=200, stretch=True)
        self.video_tree.column('description', width=150, stretch=False)
        self.video_tree.column('uploader', width=95, stretch=False)
        self.video_tree.column('video_id', width=90, stretch=False)
        self.video_tree.column('channel_id', width=90, stretch=False)
        self.video_tree.column('url', width=220, stretch=False)
        self.video_tree.column('thumbnail', width=200, stretch=False)
        self.video_tree.column('duration', width=55, stretch=False)
        self.video_tree.column('duration_string', width=70, stretch=False)
        self.video_tree.column('upload_date', width=80, stretch=False)
        self.video_tree.column('timestamp', width=90, stretch=False)
        self.video_tree.column('views', width=65, stretch=False)
        self.video_tree.column('likes', width=65, stretch=False)
        self.video_tree.column('comments', width=70, stretch=False)
        self.video_tree.column('subscribers', width=75, stretch=False)
        self.video_tree.column('subtitles', width=65, stretch=False)
        self.video_tree.column('resolution', width=80, stretch=False)
        self.video_tree.column('fps', width=45, stretch=False)
        self.video_tree.column('format', width=55, stretch=False)
        self.video_tree.column('category', width=75, stretch=False)
        self.video_tree.column('availability', width=80, stretch=False)
        self.video_tree.column('location', width=100, stretch=False)
        self.video_tree.column('tags', width=50, stretch=False)
        self.video_tree.column('tags_list', width=150, stretch=False)
        self.video_tree.column('chapters', width=60, stretch=False)
        self.video_tree.column('chapters_list', width=200, stretch=False)
        self.video_tree.column('live_status', width=75, stretch=False)
        self.video_tree.column('age_limit', width=40, stretch=False)
        self.video_tree.column('verified', width=60, stretch=False)
        self.video_tree.column('aspect_ratio', width=60, stretch=False)
        self.video_tree.column('language', width=50, stretch=False)
        self.video_tree.column('filesize', width=70, stretch=False)
        self.video_tree.column('quality', width=55, stretch=False)
        self.video_tree.column('size', width=100, stretch=False)
        self.video_tree.column('progress', width=80, stretch=False)
        self.video_tree.column('speed', width=120, stretch=False)
        
        # Download action columns
        self.video_tree.column('dl_video', width=70, stretch=False)
        self.video_tree.column('dl_audio', width=70, stretch=False)
        self.video_tree.column('dl_subs', width=70, stretch=False)
        self.video_tree.column('dl_thumb', width=70, stretch=False)
        
        # Scrollbars
        scrollbar_y = ttk.Scrollbar(list_frame, orient="vertical", command=self.video_tree.yview)
        scrollbar_x = ttk.Scrollbar(list_frame, orient="horizontal", command=self.video_tree.xview)
        self.video_tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        
        # Grid layout
        self.video_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar_y.grid(row=0, column=1, sticky=(tk.N, tk.S))
        scrollbar_x.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        # Bind click to toggle selection
        self.video_tree.bind('<Button-1>', self.on_tree_click)
        # Bind selection change to show thumbnail
        self.video_tree.bind('<<TreeviewSelect>>', self.on_video_select)
        # Bind right-click for context menu
        self.video_tree.bind('<Button-3>', self.show_context_menu)
        # Bind double-click for quality selection
        self.video_tree.bind('<Double-1>', self.on_tree_double_click)
        
        self.log_callback("✅ Video list tree created successfully")
    
    def create_control_panel(self, parent):
        """Create right-side control panel"""
        # Download Settings
        settings_frame = ttk.LabelFrame(parent, text="⚙️ Download Settings", padding="10")
        settings_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        settings_frame.columnconfigure(0, weight=1)
        
        # Download type
        type_frame = ttk.Frame(settings_frame)
        type_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(type_frame, text="Download as:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        # download_type already initialized in __init__
        ttk.Radiobutton(type_frame, text="🎥 Video", variable=self.download_type, 
                       value="video", command=self.toggle_download_type).pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(type_frame, text="🎵 Audio Only", variable=self.download_type, 
                       value="audio", command=self.toggle_download_type).pack(anchor=tk.W)
        
        # Quality settings (Simple mode)
        self.simple_quality_frame = ttk.Frame(settings_frame)
        self.simple_quality_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(self.simple_quality_frame, text="Quality:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        # quality_var already initialized in __init__
        quality_combo = ttk.Combobox(self.simple_quality_frame, textvariable=self.quality_var, 
                                    state="readonly")
        quality_combo['values'] = [
            'Best Available',
            '2160p (4K)',
            '1440p (2K)',
            '1080p (Full HD)',
            '720p (HD)',
            '480p (SD)',
            '360p',
            '240p'
        ]
        quality_combo.pack(fill=tk.X, pady=2)
        
        # Output format
        self.format_frame = ttk.Frame(self.simple_quality_frame)
        self.format_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(self.format_frame, text="Format:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        self.output_format_combo = ttk.Combobox(self.format_frame, state="readonly")
        self.output_format_combo['values'] = list(self.output_formats.keys())
        self.output_format_combo.current(0)  # Default to MP4
        self.output_format_combo.pack(fill=tk.X, pady=2)
        self.output_format_combo.bind('<<ComboboxSelected>>', 
            lambda e: self.output_format_var.set(self.output_formats[self.output_format_combo.get()]))
        
        # Audio quality
        self.audio_quality_frame = ttk.Frame(settings_frame)
        
        ttk.Label(self.audio_quality_frame, text="Audio Quality:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        # audio_quality_var already initialized in __init__
        audio_combo = ttk.Combobox(self.audio_quality_frame, textvariable=self.audio_quality_var, 
                                   state="readonly")
        audio_combo['values'] = [
            'Best Audio (m4a/webm)',
            'MP3 (320kbps)',
            'MP3 (192kbps)',
            'MP3 (128kbps)'
        ]
        audio_combo.pack(fill=tk.X, pady=2)
        
        # Download path
        ttk.Label(settings_frame, text="Save to:", font=('Arial', 9, 'bold')).grid(
            row=3, column=0, sticky=tk.W, pady=(0, 5))
        path_frame = ttk.Frame(settings_frame)
        path_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        path_frame.columnconfigure(0, weight=1)
        
        # path_var already initialized in __init__
        ttk.Entry(path_frame, textvariable=self.path_var).grid(
            row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        ttk.Button(path_frame, text="📁", width=3, command=self.browse_path).grid(row=0, column=1)
        
        # Filename template
        ttk.Label(settings_frame, text="Filename Template:", font=('Arial', 9, 'bold')).grid(
            row=5, column=0, sticky=tk.W, pady=(0, 5))
        
        # filename_template_var already initialized in __init__
        template_frame = ttk.Frame(settings_frame)
        template_frame.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        template_frame.columnconfigure(0, weight=1)
        
        template_entry = ttk.Entry(template_frame, textvariable=self.filename_template_var)
        template_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        ttk.Button(template_frame, text="ℹ️", width=3, command=self.show_template_help).grid(row=0, column=1)
        
        # Template presets
        template_combo = ttk.Combobox(settings_frame, state="readonly", width=30)
        template_combo['values'] = [
            '{title}',
            '{uploader} - {title}',
            '[{upload_date}] {title}',
            '{title} [{resolution}]',
            '{playlist_index}. {title}',
            '[{uploader}] {title} ({id})'
        ]
        template_combo.grid(row=7, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        template_combo.bind('<<ComboboxSelected>>', 
                          lambda e: self.filename_template_var.set(template_combo.get()))
        
        # Advanced options
        adv_options_frame = ttk.LabelFrame(parent, text="🚀 Advanced Options", padding="10")
        adv_options_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        adv_options_frame.columnconfigure(0, weight=1)
        
        # Parallel downloads
        parallel_frame = ttk.Frame(adv_options_frame)
        parallel_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=2)
        parallel_frame.columnconfigure(1, weight=1)
        
        ttk.Label(parallel_frame, text="Parallel Downloads:").grid(row=0, column=0, sticky=tk.W)
        parallel_spin = ttk.Spinbox(parallel_frame, from_=1, to=5, 
                                   textvariable=self.parallel_downloads, width=10)
        parallel_spin.grid(row=0, column=1, sticky=tk.E)
        
        # ============= SPEED OPTIMIZATION SETTINGS =============
        speed_frame = ttk.LabelFrame(adv_options_frame, text="⚡ Speed Optimization (IDM-style)", padding="5")
        speed_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(8, 2))
        speed_frame.columnconfigure(1, weight=1)
        
        # Concurrent fragment downloads
        ttk.Label(speed_frame, text="Parallel Connections:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        frag_spin = ttk.Spinbox(speed_frame, from_=1, to=16, 
                                textvariable=self.concurrent_fragments, width=8)
        frag_spin.grid(row=0, column=1, sticky=tk.E)
        
        # aria2c option
        self.aria2c_check = ttk.Checkbutton(speed_frame, text="Use aria2c (faster, if installed)",
                                            variable=self.use_aria2c)
        self.aria2c_check.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # aria2c connections
        aria2c_conn_frame = ttk.Frame(speed_frame)
        aria2c_conn_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        aria2c_conn_frame.columnconfigure(1, weight=1)
        ttk.Label(aria2c_conn_frame, text="  aria2c Connections:").grid(row=0, column=0, sticky=tk.W)
        self.aria2c_spinbox = ttk.Spinbox(aria2c_conn_frame, from_=1, to=32, 
                                          textvariable=self.aria2c_connections, width=8)
        self.aria2c_spinbox.grid(row=0, column=1, sticky=tk.E)
        
        if not self.aria2c_available:
            self.aria2c_check.configure(state='disabled')
            self.aria2c_spinbox.configure(state='disabled')
        
        # Auto-retry
        ttk.Checkbutton(adv_options_frame, text="Auto-retry failed downloads",
                       variable=self.auto_retry).grid(row=2, column=0, sticky=tk.W, pady=2)
        
        # Show thumbnails
        ttk.Checkbutton(adv_options_frame, text="Show thumbnails (slower)",
                       variable=self.show_thumbnails,
                       command=self.toggle_thumbnails).grid(row=3, column=0, sticky=tk.W, pady=2)
        
        # ============= FOLDER PER VIDEO SETTINGS =============
        folder_frame = ttk.LabelFrame(adv_options_frame, text="📁 Folder Per Video", padding="5")
        folder_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(8, 2))
        folder_frame.columnconfigure(0, weight=1)
        
        ttk.Checkbutton(folder_frame, text="Create a folder for each video",
                       variable=self.folder_per_video).grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Checkbutton(folder_frame, text="Save thumbnail",
                       variable=self.folder_save_thumbnail).grid(row=1, column=0, sticky=tk.W, pady=1, padx=(15, 0))
        ttk.Checkbutton(folder_frame, text="Save metadata JSON",
                       variable=self.folder_save_metadata).grid(row=2, column=0, sticky=tk.W, pady=1, padx=(15, 0))
        ttk.Checkbutton(folder_frame, text="Save subtitles",
                       variable=self.folder_save_subtitles).grid(row=3, column=0, sticky=tk.W, pady=1, padx=(15, 0))
        ttk.Checkbutton(folder_frame, text="Save description (.txt)",
                       variable=self.folder_save_description).grid(row=4, column=0, sticky=tk.W, pady=1, padx=(15, 0))
        
        # ============= VIDEO SPLIT SETTINGS =============
        split_frame = ttk.LabelFrame(adv_options_frame, text="✂️ Auto-Split Long Videos", padding="5")
        split_frame.grid(row=5, column=0, sticky=(tk.W, tk.E), pady=(8, 2))
        split_frame.columnconfigure(0, weight=1)
        
        # Enable split
        ttk.Checkbutton(split_frame, text="Split videos longer than threshold",
                       variable=self.split_enabled).grid(row=0, column=0, sticky=tk.W, pady=2)
        
        # Threshold row
        threshold_frame = ttk.Frame(split_frame)
        threshold_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=2)
        ttk.Label(threshold_frame, text="Only split if longer than:").pack(side=tk.LEFT, padx=(0, 5))
        threshold_combo = ttk.Combobox(threshold_frame, textvariable=self.split_threshold_min,
                                       width=8)
        threshold_combo['values'] = [30, 45, 60, 90, 120]
        threshold_combo.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(threshold_frame, text="min").pack(side=tk.LEFT)
        
        # Segment size row
        segment_frame = ttk.Frame(split_frame)
        segment_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=2)
        ttk.Label(segment_frame, text="Segment length:").pack(side=tk.LEFT, padx=(0, 5))
        segment_combo = ttk.Combobox(segment_frame, textvariable=self.split_segment_min,
                                     width=8)
        segment_combo['values'] = [15, 20, 25, 30, 45, 59, 60]
        segment_combo.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(segment_frame, text="min").pack(side=tk.LEFT)
        
        # Save extras
        ttk.Checkbutton(split_frame, text="Save thumbnail in folder",
                       variable=self.split_save_thumbnail).grid(row=3, column=0, sticky=tk.W, pady=1)
        ttk.Checkbutton(split_frame, text="Save metadata JSON in folder",
                       variable=self.split_save_metadata).grid(row=4, column=0, sticky=tk.W, pady=1)
        
        # Quick actions (Advanced mode only) - starts hidden
        self.quick_actions_frame = ttk.LabelFrame(parent, text="⚡ Quick Actions", padding="10")
        # Don't grid it initially - toggle_mode will show/hide it
        self.quick_actions_frame.columnconfigure(0, weight=1)
        self.quick_actions_frame.columnconfigure(1, weight=1)
        
        # Row 0: Quality presets
        ttk.Label(self.quick_actions_frame, text="📐 Quality Presets:", 
                 font=('Arial', 9, 'bold')).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0,5))
        
        ttk.Button(self.quick_actions_frame, text="🎬 Best Quality",
                  command=lambda: self.set_selected_quality("Best")).grid(
            row=1, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=2)
        ttk.Button(self.quick_actions_frame, text="📺 1080p (FHD)",
                  command=lambda: self.set_selected_quality("1080p")).grid(
            row=1, column=1, sticky=(tk.W, tk.E), pady=2)
        
        ttk.Button(self.quick_actions_frame, text="💻 720p (HD)",
                  command=lambda: self.set_selected_quality("720p")).grid(
            row=2, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=2)
        ttk.Button(self.quick_actions_frame, text="📱 480p (SD)",
                  command=lambda: self.set_selected_quality("480p")).grid(
            row=2, column=1, sticky=(tk.W, tk.E), pady=2)
        
        ttk.Separator(self.quick_actions_frame, orient='horizontal').grid(
            row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        # Row 4: Smart operations
        ttk.Label(self.quick_actions_frame, text="🤖 Smart Operations:", 
                 font=('Arial', 9, 'bold')).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(0,5))
        
        ttk.Button(self.quick_actions_frame, text="🔍 Analyze Quality",
                  command=self.analyze_all_qualities).grid(
            row=5, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=2)
        ttk.Button(self.quick_actions_frame, text="📊 Auto-Adjust Quality",
                  command=self.smart_quality_adjustment).grid(
            row=5, column=1, sticky=(tk.W, tk.E), pady=2)
        
        ttk.Button(self.quick_actions_frame, text="🎵 Audio Only",
                  command=self.set_selected_audio_only).grid(
            row=6, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=2)
        ttk.Button(self.quick_actions_frame, text="📝 With Subtitles",
                  command=self.set_selected_with_subtitles).grid(
            row=6, column=1, sticky=(tk.W, tk.E), pady=2)
        
        ttk.Separator(self.quick_actions_frame, orient='horizontal').grid(
            row=7, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        # Row 8: Priority & Queue
        ttk.Label(self.quick_actions_frame, text="🎯 Download Priority:", 
                 font=('Arial', 9, 'bold')).grid(row=8, column=0, columnspan=2, sticky=tk.W, pady=(0,5))
        
        ttk.Button(self.quick_actions_frame, text="⬆️ Move to Top",
                  command=self.move_selected_to_top).grid(
            row=9, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=2)
        ttk.Button(self.quick_actions_frame, text="⬇️ Move to Bottom",
                  command=self.move_selected_to_bottom).grid(
            row=9, column=1, sticky=(tk.W, tk.E), pady=2)
        
        ttk.Button(self.quick_actions_frame, text="⏸️ Skip Selected",
                  command=self.skip_selected_items).grid(
            row=10, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=2)
        ttk.Button(self.quick_actions_frame, text="📋 Copy Settings",
                  command=self.copy_quality_settings).grid(
            row=10, column=1, sticky=(tk.W, tk.E), pady=2)
        
        ttk.Separator(self.quick_actions_frame, orient='horizontal').grid(
            row=11, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        # Row 12: Group Management
        ttk.Label(self.quick_actions_frame, text="📁 Download Groups:", 
                 font=('Arial', 9, 'bold')).grid(row=12, column=0, columnspan=2, sticky=tk.W, pady=(0,5))
        
        ttk.Button(self.quick_actions_frame, text="➕ Create Group",
                  command=self.create_group).grid(
            row=13, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=2)
        ttk.Button(self.quick_actions_frame, text="📂 Assign to Group",
                  command=self.assign_to_group).grid(
            row=13, column=1, sticky=(tk.W, tk.E), pady=2)
        
        ttk.Button(self.quick_actions_frame, text="❌ Remove from Group",
                  command=self.remove_from_group).grid(
            row=14, column=0, sticky=(tk.W, tk.E), padx=(0, 5), pady=2)
        ttk.Button(self.quick_actions_frame, text="⚙️ Group Settings",
                  command=self.edit_group_settings).grid(
            row=14, column=1, sticky=(tk.W, tk.E), pady=2)
        
        # Plugins section
        self.plugins_frame = ttk.LabelFrame(parent, text="🔌 Extensions (Plugins)", padding="10")
        # Will be shown/hidden with advanced mode
        self.plugins_frame.columnconfigure(0, weight=1)
        
        # Try to import plugin manager
        try:
            from plugin_manager import PluginManager
            self.plugin_manager = PluginManager()
            self.has_plugins = True
            
            # Create plugin checkboxes
            self.plugin_vars = {}
            row = 0
            for plugin in self.plugin_manager.get_plugins():
                var = tk.BooleanVar(value=plugin.enabled_by_default)
                self.plugin_vars[plugin.id] = var
                ttk.Checkbutton(self.plugins_frame, 
                              text=f"{plugin.name}",
                              variable=var).grid(row=row, column=0, sticky=tk.W, pady=2)
                row += 1
            
            # Run plugins button
            ttk.Button(self.plugins_frame, text="▶ Run Enabled Plugins",
                      command=self.run_plugins_on_selected).grid(
                row=row, column=0, sticky=(tk.W, tk.E), pady=(10, 2))
            
            self.log_callback(f"✅ Loaded {len(self.plugin_manager.get_plugins())} plugins")
        except Exception as e:
            self.has_plugins = False
            self.log_callback(f"⚠️ Plugin system unavailable: {e}")
        
        # Statistics
        stats_frame = ttk.LabelFrame(parent, text="📈 Selection Stats", padding="10")
        stats_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.stats_text = tk.Text(stats_frame, height=6, width=30, 
                                 font=('Courier', 8), wrap=tk.WORD)
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        self.stats_text.config(state=tk.DISABLED)
        
        self.update_stats()
    
    def create_bottom_section(self, parent):
        """Create bottom section with Preview (left) and Download Progress (right)"""
        # Container frame for bottom section
        bottom_frame = ttk.Frame(parent)
        bottom_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        bottom_frame.columnconfigure(0, weight=1)
        bottom_frame.columnconfigure(1, weight=1)
        
        # Left: Thumbnail Preview
        self.thumbnail_frame = ttk.LabelFrame(bottom_frame, text="🖼️ Preview", padding="5")
        self.thumbnail_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        
        self.thumbnail_label = tk.Label(self.thumbnail_frame, text="Select a video to preview", 
                                        anchor=tk.CENTER, relief=tk.SUNKEN, background='#f0f0f0',
                                        width=30, height=10)
        self.thumbnail_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Right: Download Progress
        progress_frame = ttk.LabelFrame(bottom_frame, text="📥 Download Progress", padding="10")
        progress_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))
        progress_frame.columnconfigure(0, weight=1)
        
        # Current status
        self.progress_var = tk.StringVar(value="Ready to download")
        ttk.Label(progress_frame, textvariable=self.progress_var, 
                 font=('Arial', 9)).grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Progress bar
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        
        # Current video
        self.current_video_var = tk.StringVar(value="")
        ttk.Label(progress_frame, textvariable=self.current_video_var, 
                 foreground="blue", font=('Arial', 8)).grid(row=2, column=0, sticky=tk.W, pady=(5, 0))
        
        # Speed and ETA
        stats_subframe = ttk.Frame(progress_frame)
        stats_subframe.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        
        self.speed_var = tk.StringVar(value="Speed: ---")
        self.eta_var = tk.StringVar(value="ETA: ---")
        ttk.Label(stats_subframe, textvariable=self.speed_var, 
                 font=('Arial', 8)).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(stats_subframe, textvariable=self.eta_var, 
                 font=('Arial', 8)).pack(side=tk.LEFT)
        
        # Buttons
        button_frame = ttk.Frame(progress_frame)
        button_frame.grid(row=4, column=0, pady=(10, 0))
        
        self.download_btn = ttk.Button(button_frame, 
                                      text=f"▶ Download Selected ({self.video_count} videos)", 
                                      command=self.start_download)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        
        self.pause_btn = ttk.Button(button_frame, text="⏸ Pause", 
                                    command=self.pause_download, state="disabled")
        self.pause_btn.pack(side=tk.LEFT, padx=5)
        
        self.cancel_btn = ttk.Button(button_frame, text="⏹ Cancel", 
                                     command=self.cancel_download, state="disabled")
        self.cancel_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame, text="💾 Export List", 
                  command=self.export_list).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame, text="❌ Close", 
                  command=self.window.destroy).pack(side=tk.LEFT, padx=5)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(progress_frame, textvariable=self.status_var, 
                               relief=tk.SUNKEN, anchor=tk.W, font=('Arial', 8))
        status_label.grid(row=5, column=0, sticky=(tk.W, tk.E), pady=(10, 0))
    
    def populate_video_list(self):
        """Populate the video list with items"""
        try:
            if not isinstance(self.playlist_entries, list):
                self.log_callback("❌ playlist_entries is not a list; cannot populate.")
                return
            count = len(self.playlist_entries)
            self.log_callback(f"🔄 Populating video list with {count} entries...")
            if count == 0:
                self.log_callback("⚠️ No entries found in playlist for display.")
                return
            # Clear any existing tree items (avoid duplicates if re-opened)
            for child in self.video_tree.get_children():
                self.video_tree.delete(child)
            self.video_item_widgets.clear()
            for idx, entry in enumerate(self.playlist_entries):
                title = entry.get('title') or entry.get('id') or 'Unknown Title'
                
                # Get description (truncated)
                description = entry.get('description', '') or ""
                if description:
                    # Truncate to first line or 50 chars
                    desc_lines = description.split('\n')
                    desc_str = desc_lines[0] if desc_lines else description
                    if len(desc_str) > 50:
                        desc_str = desc_str[:47] + "..."
                else:
                    desc_str = "?"
                
                duration = entry.get('duration') or 0
                try:
                    duration_int = int(duration) if duration else 0
                except Exception:
                    duration_int = 0
                dur_str = f"{duration_int//60}:{duration_int%60:02d}" if duration_int else "?"
                
                # Get duration_string (human readable)
                duration_string = entry.get('duration_string', '') or dur_str
                
                # Get uploader/channel name
                uploader = entry.get('uploader') or entry.get('channel') or "?"
                if len(uploader) > 15:
                    uploader = uploader[:12] + "..."
                
                # Get video ID
                video_id = entry.get('id') or entry.get('display_id') or "?"
                if len(video_id) > 11:
                    video_id = video_id[:11]
                
                # Get channel ID
                channel_id = entry.get('channel_id') or entry.get('uploader_id') or "?"
                if len(channel_id) > 11:
                    channel_id = channel_id[:11]
                
                # Get URL
                url = entry.get('webpage_url') or entry.get('url') or ""
                if video_id and video_id != "?" and not url:
                    # Construct URL from video_id if not available
                    url = f"https://www.youtube.com/watch?v={video_id}"
                if len(url) > 45:
                    # Truncate for display
                    url = url[:42] + "..."
                
                # Get thumbnail URL
                thumbnail = entry.get('thumbnail', '') or ""
                if not thumbnail and entry.get('thumbnails'):
                    # Get best quality thumbnail
                    thumbnails = entry['thumbnails']
                    if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
                        thumbnail = thumbnails[-1].get('url', '')
                if len(thumbnail) > 45:
                    thumbnail = thumbnail[:42] + "..."
                if not thumbnail:
                    thumbnail = "?"
                
                # Format upload date
                upload_date = entry.get('upload_date', '')
                if upload_date and len(upload_date) >= 8:
                    # Format YYYYMMDD to YYYY-MM-DD
                    upload_str = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                else:
                    upload_str = "?"
                
                # Get timestamp (Unix timestamp)
                timestamp = entry.get('timestamp', 0)
                if timestamp:
                    import datetime
                    timestamp_str = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                else:
                    timestamp_str = "?"
                
                # Format view count
                view_count = entry.get('view_count', 0)
                if view_count:
                    if view_count >= 1000000:
                        views_str = f"{view_count / 1000000:.1f}M"
                    elif view_count >= 1000:
                        views_str = f"{view_count / 1000:.1f}K"
                    else:
                        views_str = str(view_count)
                else:
                    views_str = "?"
                
                # Format available subtitles
                subtitles = entry.get('subtitles', {})
                auto_captions = entry.get('automatic_captions', {})
                all_subs = list(subtitles.keys()) + list(auto_captions.keys())
                if all_subs:
                    # Show first 2 language codes
                    unique_subs = list(set(all_subs))[:2]
                    subs_str = ','.join([s.upper() for s in unique_subs])
                    if len(all_subs) > 2:
                        subs_str += f"+{len(all_subs)-2}"
                else:
                    subs_str = "None"
                
                # Get resolution - find best available
                resolution_str = "?"
                formats = entry.get('formats', [])
                if formats:
                    max_height = 0
                    max_width = 0
                    for fmt in formats:
                        height = fmt.get('height', 0) or 0
                        width = fmt.get('width', 0) or 0
                        if height > max_height:
                            max_height = height
                            max_width = width
                    if max_height:
                        resolution_str = f"{max_width}x{max_height}"
                elif entry.get('width') and entry.get('height'):
                    resolution_str = f"{entry['width']}x{entry['height']}"
                
                # Get FPS
                fps_str = "?"
                if entry.get('fps'):
                    fps_str = f"{int(entry['fps'])}fps"
                elif formats:
                    for fmt in formats:
                        if fmt.get('fps'):
                            fps_str = f"{int(fmt['fps'])}fps"
                            break
                
                # Get format/codec
                format_str = "?"
                if entry.get('vcodec'):
                    vcodec = entry['vcodec']
                    if vcodec != 'none':
                        # Simplify codec names
                        if 'vp9' in vcodec.lower():
                            format_str = "VP9"
                        elif 'vp8' in vcodec.lower():
                            format_str = "VP8"
                        elif 'av01' in vcodec.lower() or 'av1' in vcodec.lower():
                            format_str = "AV1"
                        elif 'h264' in vcodec.lower() or 'avc' in vcodec.lower():
                            format_str = "H264"
                        elif 'h265' in vcodec.lower() or 'hevc' in vcodec.lower():
                            format_str = "H265"
                        else:
                            format_str = vcodec[:6].upper()
                
                # Get category
                category_str = entry.get('categories', ['?'])[0] if entry.get('categories') else "?"
                if category_str and len(category_str) > 12:
                    category_str = category_str[:9] + "..."
                
                # Format like count
                like_count = entry.get('like_count', 0)
                if like_count:
                    if like_count >= 1000000:
                        likes_str = f"{like_count / 1000000:.1f}M"
                    elif like_count >= 1000:
                        likes_str = f"{like_count / 1000:.1f}K"
                    else:
                        likes_str = str(like_count)
                else:
                    likes_str = "?"
                
                # Format comment count
                comment_count = entry.get('comment_count', 0)
                if comment_count:
                    if comment_count >= 1000000:
                        comments_str = f"{comment_count / 1000000:.1f}M"
                    elif comment_count >= 1000:
                        comments_str = f"{comment_count / 1000:.1f}K"
                    else:
                        comments_str = str(comment_count)
                else:
                    comments_str = "?"
                
                # Format subscriber count
                subscriber_count = entry.get('channel_follower_count', 0)
                if subscriber_count:
                    if subscriber_count >= 1000000:
                        subs_count_str = f"{subscriber_count / 1000000:.1f}M"
                    elif subscriber_count >= 1000:
                        subs_count_str = f"{subscriber_count / 1000:.1f}K"
                    else:
                        subs_count_str = str(subscriber_count)
                else:
                    subs_count_str = "?"
                
                # Get availability
                availability_str = entry.get('availability', '?')
                if availability_str and len(availability_str) > 10:
                    availability_str = availability_str[:7] + "..."
                
                # Get location
                location_str = entry.get('location', '?') or "?"
                if location_str and len(location_str) > 18:
                    location_str = location_str[:15] + "..."
                
                # Get tags count and list
                tags = entry.get('tags', [])
                tags_str = f"{len(tags)}" if tags else "0"
                # Get tags list (first 3 tags)
                if tags and isinstance(tags, list):
                    tags_preview = ', '.join(tags[:3])
                    if len(tags) > 3:
                        tags_preview += f" +{len(tags)-3}"
                    if len(tags_preview) > 50:
                        tags_preview = tags_preview[:47] + "..."
                    tags_list_str = tags_preview
                else:
                    tags_list_str = "None"
                
                # Get chapters count and list
                chapters = entry.get('chapters', [])
                chapters_str = f"{len(chapters)}" if chapters else "0"
                # Get chapters list (first 2 chapter titles)
                if chapters and isinstance(chapters, list):
                    chapter_titles = []
                    for ch in chapters[:2]:
                        if isinstance(ch, dict) and 'title' in ch:
                            chapter_titles.append(ch['title'])
                    chapters_preview = ', '.join(chapter_titles)
                    if len(chapters) > 2:
                        chapters_preview += f" +{len(chapters)-2}"
                    if len(chapters_preview) > 50:
                        chapters_preview = chapters_preview[:47] + "..."
                    chapters_list_str = chapters_preview if chapters_preview else "?"
                else:
                    chapters_list_str = "None"
                
                # Get live status
                live_status = entry.get('live_status', '?') or "?"
                if live_status and len(live_status) > 10:
                    live_status = live_status[:7] + "..."
                
                # Get age limit
                age_limit = entry.get('age_limit', 0)
                age_str = f"{age_limit}+" if age_limit else "All"
                
                # Get verified status
                verified = entry.get('channel_is_verified', False)
                verified_str = "✓" if verified else "-"
                
                # Get aspect ratio
                aspect_ratio = entry.get('aspect_ratio', 0)
                aspect_str = f"{aspect_ratio:.2f}" if aspect_ratio else "?"
                
                # Get language
                language = entry.get('language', '') or ""
                lang_str = language.upper()[:5] if language else "?"
                
                # Get actual filesize
                filesize = entry.get('filesize') or entry.get('filesize_approx', 0)
                if filesize:
                    if filesize >= 1073741824:  # 1GB
                        filesize_str = f"{filesize / 1073741824:.1f}GB"
                    elif filesize >= 1048576:  # 1MB
                        filesize_str = f"{filesize / 1048576:.1f}MB"
                    elif filesize >= 1024:  # 1KB
                        filesize_str = f"{filesize / 1024:.1f}KB"
                    else:
                        filesize_str = f"{filesize}B"
                else:
                    filesize_str = "?"
                
                estimated_size_mb = (duration_int / 60) * 10 if duration_int else 0
                size_str = f"{estimated_size_mb:.0f}MB" if estimated_size_mb > 0 else "?"
                # Default quality based on download type (if available)
                if hasattr(self, 'download_type'):
                    default_quality = 'Best' if self.download_type.get() == 'video' else '320kbps'
                else:
                    default_quality = 'Best'
                item_id = self.video_tree.insert(
                    '', 'end', text=f"☑ {idx+1}",
                    values=('⏳', '', title, desc_str, uploader, video_id, channel_id, url, thumbnail, 
                           dur_str, duration_string, upload_str, timestamp_str, 
                           views_str, likes_str, comments_str, subs_count_str, subs_str, 
                           resolution_str, fps_str, format_str, category_str, availability_str, 
                           location_str, tags_str, tags_list_str, chapters_str, chapters_list_str, 
                           live_status, age_str, verified_str, aspect_str, lang_str, 
                           filesize_str, default_quality, size_str, '-', '-',
                           '📥', '🎵', '📝', '🖼️'),
                    tags=('selected',)
                )
                # Select by default so stats reflect full list
                self.video_tree.selection_add(item_id)
                self.video_item_widgets.append({
                    'item_id': item_id,
                    'entry': entry,
                    'selected': True,
                    'quality': 'Best',
                    'group': '',  # Initialize group as empty
                    'status': '⏳',
                    'analyzed': False,
                    'progress': '-',
                    'speed': '-',
                    'eta': ''
                })
            self.video_tree.tag_configure('selected', background='lightblue')
            inserted = len(self.video_item_widgets)
            if inserted != count:
                self.log_callback(f"⚠️ Mismatch: expected {count} items, inserted {inserted}.")
            else:
                self.log_callback(f"✅ Inserted {inserted} video rows.")
            # Refresh counters
            self.update_selected_count()
            self.update_stats()
        except Exception as e:
            self.log_callback(f"❌ populate_video_list error: {e}")

    def start_fetch_entries(self):
        """Begin incremental (re)fetch of playlist entries and stream them into the list."""
        if getattr(self, 'is_fetching_entries', False):
            return
        # Attempt to get source URL from playlist_info metadata
        source_url = self.playlist_info.get('webpage_url') or self.playlist_info.get('url') or self.playlist_info.get('id')
        if source_url and not str(source_url).startswith('http') and self.playlist_info.get('id'):
            # Construct YouTube playlist/channel URL heuristically if only ID is present
            source_url = f"https://www.youtube.com/playlist?list={self.playlist_info.get('id')}"
        if not source_url:
            self.log_callback("❌ Cannot determine playlist source URL for fetch.")
            messagebox.showerror("Fetch Error", "Cannot determine playlist URL.", parent=self.window)
            return
        self.is_fetching_entries = True
        self.fetch_btn.config(state='disabled')
        self.fetch_status_var.set("Fetching playlist entries...")
        self.log_callback(f"📡 Fetching playlist entries from: {source_url}")

        def worker():
            try:
                # First pass: get playlist structure with flat extraction (fast)
                ydl_opts_flat = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': 'in_playlist',
                    'socket_timeout': 30,
                    'playlistend': None,
                    'ignoreerrors': True,
                }
                
                self.log_callback("📡 Phase 1: Fetching playlist structure...")
                basic_entries = []
                with yt_dlp.YoutubeDL(ydl_opts_flat) as ydl:
                    info = ydl.extract_info(source_url, download=False)
                    if info and info.get('_type') == 'playlist':
                        raw_entries = info.get('entries') or []
                        # Filter out None entries (deleted/unavailable videos)
                        basic_entries = [e for e in raw_entries if e is not None]
                        skipped = len(raw_entries) - len(basic_entries)
                        if skipped > 0:
                            self.log_callback(f"⚠️ Skipped {skipped} unavailable/deleted videos")
                    else:
                        if info:
                            basic_entries = [info]
                
                total = len(basic_entries)
                self.log_callback(f"📊 Channel shows {info.get('playlist_count', 'unknown')} videos, fetched {total} available entries")
                
                # Apply limit filter
                limit_option = self.limit_videos_var.get()
                if limit_option != "All":
                    limit_num = int(limit_option.split()[1])  # Extract number from "First X"
                    if len(basic_entries) > limit_num:
                        basic_entries = basic_entries[:limit_num]
                        self.log_callback(f"📉 Limited to first {limit_num} videos (from {total} total)")
                        total = len(basic_entries)
                
                # Apply date filter (only works with full metadata mode)
                date_filter = self.date_filter_var.get()
                if date_filter != "All time" and self.fetch_full_metadata.get():
                    import datetime
                    now = datetime.datetime.now()
                    
                    # Calculate cutoff date
                    if date_filter == "Last 24 hours":
                        cutoff = now - datetime.timedelta(days=1)
                    elif date_filter == "Last 3 days":
                        cutoff = now - datetime.timedelta(days=3)
                    elif date_filter == "Last week":
                        cutoff = now - datetime.timedelta(weeks=1)
                    elif date_filter == "Last 2 weeks":
                        cutoff = now - datetime.timedelta(weeks=2)
                    elif date_filter == "Last month":
                        cutoff = now - datetime.timedelta(days=30)
                    elif date_filter == "Last 3 months":
                        cutoff = now - datetime.timedelta(days=90)
                    elif date_filter == "Last 6 months":
                        cutoff = now - datetime.timedelta(days=180)
                    elif date_filter == "Last year":
                        cutoff = now - datetime.timedelta(days=365)
                    else:
                        cutoff = None
                    
                    if cutoff:
                        self.log_callback(f"📅 Date filter active: {date_filter} (videos after {cutoff.strftime('%Y-%m-%d')})")
                        # Store cutoff for filtering during full metadata fetch
                        self.date_cutoff = cutoff
                elif date_filter != "All time" and not self.fetch_full_metadata.get():
                    self.log_callback(f"⚠️ Date filter '{date_filter}' requires 'Full metadata' mode to be enabled")
                    self.window.after(0, lambda: messagebox.showwarning(
                        "Date Filter Warning", 
                        "Date filtering requires 'Full metadata' mode.\nPlease enable it and try again.",
                        parent=self.window
                    ))
                
                # Clear existing
                self.window.after(0, lambda: self._reset_video_tree())
                
                # Check if user wants full metadata or fast mode
                fetch_full = self.fetch_full_metadata.get()
                
                if fetch_full:
                    # Full metadata mode: slower but includes upload dates
                    self.log_callback(f"📥 Found {total} entries. Phase 2: Fetching full metadata with dates...")
                    
                    # Second pass: get full metadata including upload_date
                    ydl_opts_full = {
                        'quiet': True,
                        'no_warnings': True,
                        'socket_timeout': 30,
                        'ignoreerrors': True,
                        'skip_download': True,
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts_full) as ydl:
                        successful = 0
                        failed = 0
                        for idx, basic_entry in enumerate(basic_entries, 1):
                            try:
                                video_id = basic_entry.get('id') or basic_entry.get('url')
                                video_title = basic_entry.get('title', 'Unknown')[:30]
                                if not video_id:
                                    # Use basic entry as fallback
                                    self.playlist_entries.append(basic_entry)
                                    self.window.after(0, lambda e=basic_entry, i=idx, t=total: self._insert_single_entry(e, i, t))
                                    successful += 1
                                    continue
                                
                                # Construct URL
                                if not video_id.startswith('http'):
                                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                                else:
                                    video_url = video_id
                                
                                # Extract full info including upload_date
                                full_info = ydl.extract_info(video_url, download=False)
                                if full_info:
                                    # Apply date filter if active
                                    if hasattr(self, 'date_cutoff') and self.date_cutoff:
                                        upload_date = full_info.get('upload_date', '')
                                        if upload_date and len(upload_date) >= 8:
                                            # Parse YYYYMMDD format (using dt alias from top import)
                                            try:
                                                video_date = dt.datetime.strptime(upload_date, '%Y%m%d')
                                                if video_date < self.date_cutoff:
                                                    # Skip this video - too old
                                                    self.log_callback(f"⏭️ Skipped '{video_title}' (uploaded {upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]})")
                                                    continue
                                            except (ValueError, AttributeError):
                                                pass  # If parsing fails, include the video
                                    
                                    self.playlist_entries.append(full_info)
                                    self.window.after(0, lambda e=full_info, i=idx, t=total: self._insert_single_entry(e, i, t))
                                    successful += 1
                                else:
                                    # Fallback to basic
                                    self.log_callback(f"⚠️ No full metadata for video {idx} '{video_title}' - using basic info")
                                    self.playlist_entries.append(basic_entry)
                                    self.window.after(0, lambda e=basic_entry, i=idx, t=total: self._insert_single_entry(e, i, t))
                                    failed += 1
                                
                                # Small delay to avoid rate limiting
                                time.sleep(0.1)
                            
                            except Exception as e:
                                failed += 1
                                video_title = basic_entry.get('title', 'Unknown')[:30] if basic_entry else 'Unknown'
                                self.log_callback(f"⚠️ Error fetching video {idx} '{video_title}': {str(e)[:50]}")
                                # Use basic entry on error
                                if basic_entry:
                                    self.playlist_entries.append(basic_entry)
                                    self.window.after(0, lambda e=basic_entry, i=idx, t=total: self._insert_single_entry(e, i, t))
                        
                        if failed > 0:
                            self.log_callback(f"📊 Full metadata: {successful} successful, {failed} failed/fallback")
                        
                        # Clear date cutoff after filtering
                        if hasattr(self, 'date_cutoff'):
                            delattr(self, 'date_cutoff')
                else:
                    # Fast mode: just use basic entries (no upload dates)
                    self.log_callback(f"📥 Found {total} entries. Loading in fast mode (no upload dates)...")
                    for idx, entry in enumerate(basic_entries, 1):
                        self.playlist_entries.append(entry)
                        self.window.after(0, lambda e=entry, i=idx, t=total: self._insert_single_entry(e, i, t))
                        # Gentle pacing to keep UI responsive
                        time.sleep(0.02)
                
                self.window.after(0, self._finalize_fetch, total)
            except Exception as e:
                self.window.after(0, lambda: self._fetch_failed(str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _reset_video_tree(self):
        """Clear tree and internal tracking before streaming entries."""
        for child in self.video_tree.get_children():
            self.video_tree.delete(child)
        self.video_item_widgets.clear()
        self.playlist_entries = []
        self.update_selected_count()
        self.fetch_status_var.set("Preparing list...")

    def _insert_single_entry(self, entry, idx, total):
        """Insert a single playlist entry row (UI thread)."""
        title = entry.get('title') or entry.get('id') or 'Unknown Title'
        
        # Get description (truncated)
        description = entry.get('description', '') or ""
        if description:
            desc_lines = description.split('\n')
            desc_str = desc_lines[0] if desc_lines else description
            if len(desc_str) > 50:
                desc_str = desc_str[:47] + "..."
        else:
            desc_str = "?"
        
        duration = entry.get('duration') or 0
        try:
            duration_int = int(duration) if duration else 0
        except Exception:
            duration_int = 0
        dur_str = f"{duration_int//60}:{duration_int%60:02d}" if duration_int else "?"
        
        # Get duration_string
        duration_string = entry.get('duration_string', '') or dur_str
        
        # Get uploader/channel name
        uploader = entry.get('uploader') or entry.get('channel') or "?"
        if len(uploader) > 15:
            uploader = uploader[:12] + "..."
        
        # Get video ID
        video_id = entry.get('id') or entry.get('display_id') or "?"
        if len(video_id) > 11:
            video_id = video_id[:11]
        
        # Get channel ID
        channel_id = entry.get('channel_id') or entry.get('uploader_id') or "?"
        if len(channel_id) > 11:
            channel_id = channel_id[:11]
        
        # Get URL
        url = entry.get('webpage_url') or entry.get('url') or ""
        if video_id and video_id != "?" and not url:
            # Construct URL from video_id if not available
            url = f"https://www.youtube.com/watch?v={video_id}"
        if len(url) > 45:
            # Truncate for display
            url = url[:42] + "..."
        
        # Get thumbnail URL
        thumbnail = entry.get('thumbnail', '') or ""
        if not thumbnail and entry.get('thumbnails'):
            thumbnails = entry['thumbnails']
            if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
                thumbnail = thumbnails[-1].get('url', '')
        if len(thumbnail) > 45:
            thumbnail = thumbnail[:42] + "..."
        if not thumbnail:
            thumbnail = "?"
        
        # Format upload date
        upload_date = entry.get('upload_date', '')
        if upload_date and len(upload_date) >= 8:
            # Format YYYYMMDD to YYYY-MM-DD
            upload_str = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        else:
            upload_str = "?"
        
        # Get timestamp
        timestamp = entry.get('timestamp', 0)
        if timestamp:
            import datetime
            timestamp_str = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        else:
            timestamp_str = "?"
        
        # Format view count
        view_count = entry.get('view_count', 0)
        if view_count:
            if view_count >= 1000000:
                views_str = f"{view_count / 1000000:.1f}M"
            elif view_count >= 1000:
                views_str = f"{view_count / 1000:.1f}K"
            else:
                views_str = str(view_count)
        else:
            views_str = "?"
        
        # Format available subtitles
        subtitles = entry.get('subtitles', {})
        auto_captions = entry.get('automatic_captions', {})
        all_subs = list(subtitles.keys()) + list(auto_captions.keys())
        if all_subs:
            # Show first 2 language codes
            unique_subs = list(set(all_subs))[:2]
            subs_str = ','.join([s.upper() for s in unique_subs])
            if len(all_subs) > 2:
                subs_str += f"+{len(all_subs)-2}"
        else:
            subs_str = "None"
        
        # Get resolution - find best available
        resolution_str = "?"
        formats = entry.get('formats', [])
        if formats:
            max_height = 0
            max_width = 0
            for fmt in formats:
                height = fmt.get('height', 0) or 0
                width = fmt.get('width', 0) or 0
                if height > max_height:
                    max_height = height
                    max_width = width
            if max_height:
                resolution_str = f"{max_width}x{max_height}"
        elif entry.get('width') and entry.get('height'):
            resolution_str = f"{entry['width']}x{entry['height']}"
        
        # Get FPS
        fps_str = "?"
        if entry.get('fps'):
            fps_str = f"{int(entry['fps'])}fps"
        elif formats:
            for fmt in formats:
                if fmt.get('fps'):
                    fps_str = f"{int(fmt['fps'])}fps"
                    break
        
        # Get format/codec
        format_str = "?"
        if entry.get('vcodec'):
            vcodec = entry['vcodec']
            if vcodec != 'none':
                # Simplify codec names
                if 'vp9' in vcodec.lower():
                    format_str = "VP9"
                elif 'vp8' in vcodec.lower():
                    format_str = "VP8"
                elif 'av01' in vcodec.lower() or 'av1' in vcodec.lower():
                    format_str = "AV1"
                elif 'h264' in vcodec.lower() or 'avc' in vcodec.lower():
                    format_str = "H264"
                elif 'h265' in vcodec.lower() or 'hevc' in vcodec.lower():
                    format_str = "H265"
                else:
                    format_str = vcodec[:6].upper()
        
        # Get category
        category_str = entry.get('categories', ['?'])[0] if entry.get('categories') else "?"
        if category_str and len(category_str) > 12:
            category_str = category_str[:9] + "..."
        
        # Format like count
        like_count = entry.get('like_count', 0)
        if like_count:
            if like_count >= 1000000:
                likes_str = f"{like_count / 1000000:.1f}M"
            elif like_count >= 1000:
                likes_str = f"{like_count / 1000:.1f}K"
            else:
                likes_str = str(like_count)
        else:
            likes_str = "?"
        
        # Format comment count
        comment_count = entry.get('comment_count', 0)
        if comment_count:
            if comment_count >= 1000000:
                comments_str = f"{comment_count / 1000000:.1f}M"
            elif comment_count >= 1000:
                comments_str = f"{comment_count / 1000:.1f}K"
            else:
                comments_str = str(comment_count)
        else:
            comments_str = "?"
        
        # Format subscriber count
        subscriber_count = entry.get('channel_follower_count', 0)
        if subscriber_count:
            if subscriber_count >= 1000000:
                subs_count_str = f"{subscriber_count / 1000000:.1f}M"
            elif subscriber_count >= 1000:
                subs_count_str = f"{subscriber_count / 1000:.1f}K"
            else:
                subs_count_str = str(subscriber_count)
        else:
            subs_count_str = "?"
        
        # Get availability
        availability_str = entry.get('availability', '?')
        if availability_str and len(availability_str) > 10:
            availability_str = availability_str[:7] + "..."
        
        # Get location
        location_str = entry.get('location', '?') or "?"
        if location_str and len(location_str) > 18:
            location_str = location_str[:15] + "..."
        
        # Get tags count and list
        tags = entry.get('tags', [])
        tags_str = f"{len(tags)}" if tags else "0"
        if tags and isinstance(tags, list):
            tags_preview = ', '.join(tags[:3])
            if len(tags) > 3:
                tags_preview += f" +{len(tags)-3}"
            if len(tags_preview) > 50:
                tags_preview = tags_preview[:47] + "..."
            tags_list_str = tags_preview
        else:
            tags_list_str = "None"
        
        # Get chapters count and list
        chapters = entry.get('chapters', [])
        chapters_str = f"{len(chapters)}" if chapters else "0"
        if chapters and isinstance(chapters, list):
            chapter_titles = []
            for ch in chapters[:2]:
                if isinstance(ch, dict) and 'title' in ch:
                    chapter_titles.append(ch['title'])
            chapters_preview = ', '.join(chapter_titles)
            if len(chapters) > 2:
                chapters_preview += f" +{len(chapters)-2}"
            if len(chapters_preview) > 50:
                chapters_preview = chapters_preview[:47] + "..."
            chapters_list_str = chapters_preview if chapters_preview else "?"
        else:
            chapters_list_str = "None"
        
        # Get live status
        live_status = entry.get('live_status', '?') or "?"
        if live_status and len(live_status) > 10:
            live_status = live_status[:7] + "..."
        
        # Get age limit
        age_limit = entry.get('age_limit', 0)
        age_str = f"{age_limit}+" if age_limit else "All"
        
        # Get verified status
        verified = entry.get('channel_is_verified', False)
        verified_str = "✓" if verified else "-"
        
        # Get aspect ratio
        aspect_ratio = entry.get('aspect_ratio', 0)
        aspect_str = f"{aspect_ratio:.2f}" if aspect_ratio else "?"
        
        # Get language
        language = entry.get('language', '') or ""
        lang_str = language.upper()[:5] if language else "?"
        
        # Get actual filesize
        filesize = entry.get('filesize') or entry.get('filesize_approx', 0)
        if filesize:
            if filesize >= 1073741824:  # 1GB
                filesize_str = f"{filesize / 1073741824:.1f}GB"
            elif filesize >= 1048576:  # 1MB
                filesize_str = f"{filesize / 1048576:.1f}MB"
            elif filesize >= 1024:  # 1KB
                filesize_str = f"{filesize / 1024:.1f}KB"
            else:
                filesize_str = f"{filesize}B"
        else:
            filesize_str = "?"
        
        # Default quality based on download type (if available)
        if hasattr(self, 'download_type'):
            default_quality = 'Best' if self.download_type.get() == 'video' else '320kbps'
        else:
            default_quality = 'Best'
        
        # Estimate file size
        estimated_size_mb = (duration_int / 60) * 10 if duration_int else 0
        size_str = f"{estimated_size_mb:.0f}MB" if estimated_size_mb > 0 else "?"
        
        # Columns: status, group, title, description, uploader, video_id, channel_id, url, thumbnail, duration, duration_string, upload_date, timestamp, views, likes, comments, subscribers, subtitles, resolution, fps, format, category, availability, location, tags, tags_list, chapters, chapters_list, live_status, age_limit, verified, aspect_ratio, language, filesize, quality, size, progress, speed, dl_video, dl_audio, dl_subs, dl_thumb
        item_id = self.video_tree.insert(
            '', 'end', text=f"☑ {idx}", 
            values=('⏳', '', title, desc_str, uploader, video_id, channel_id, url, thumbnail,
                   dur_str, duration_string, upload_str, timestamp_str,
                   views_str, likes_str, comments_str, subs_count_str, subs_str,
                   resolution_str, fps_str, format_str, category_str, availability_str,
                   location_str, tags_str, tags_list_str, chapters_str, chapters_list_str,
                   live_status, age_str, verified_str, aspect_str, lang_str,
                   filesize_str, default_quality, size_str, '-', '-',
                   '📥', '🎵', '📝', '🖼️'), 
            tags=('selected',)
        )
        self.video_tree.selection_add(item_id)
        self.video_item_widgets.append({
            'item_id': item_id,
            'entry': entry,
            'selected': True,
            'quality': 'Best',
            'group': '',  # Initialize group as empty
            'status': '⏳',
            'analyzed': False,
            'progress': '-',
            'speed': '-',
            'eta': ''
        })
        percent = (idx / total) * 100 if total else 0
        self.fetch_status_var.set(f"Loaded {idx}/{total} ({percent:.0f}%)")
        if idx == total:
            self.update_selected_count()
            self.update_stats()

    def _finalize_fetch(self, total):
        """Finalize fetch process."""
        self.is_fetching_entries = False
        self.fetch_btn.config(state='normal', text="🔄 Reload Video List")
        self.fetch_status_var.set(f"Completed loading {total} entries.")
        self.log_callback(f"✅ Finished streaming {total} entries to list.")
        self.update_selected_count()
        self.update_stats()

    def _fetch_failed(self, error):
        self.is_fetching_entries = False
        self.fetch_btn.config(state='normal')
        self.fetch_status_var.set("Fetch failed.")
        self.log_callback(f"❌ Fetch failed: {error}")
        messagebox.showerror("Fetch Failed", f"Could not load playlist entries:\n{error}", parent=self.window)
    
    def on_tree_click(self, event):
        """Handle tree item click to toggle selection or trigger download actions"""
        region = self.video_tree.identify('region', event.x, event.y)
        item = self.video_tree.identify_row(event.y)
        
        if not item:
            return
        
        # Check if clicking on a download action column
        if region == 'cell':
            column = self.video_tree.identify_column(event.x)
            # Map column numbers to column names
            col_num = int(column.replace('#', ''))
            if col_num > 0:
                col_name = list(self.video_tree['columns'])[col_num - 1]
                
                # Handle download action columns
                if col_name == 'dl_video':
                    self.download_item_video_only(item)
                    return "break"
                elif col_name == 'dl_audio':
                    self.download_item_audio_only(item)
                    return "break"
                elif col_name == 'dl_subs':
                    self.download_item_subs_only(item)
                    return "break"
                elif col_name == 'dl_thumb':
                    self.download_item_thumb_only(item)
                    return "break"
            
            # For regular cell clicks, toggle checkbox (same as clicking the tree column)
            # This keeps checkbox state in sync with what the user clicks
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item:
                    widget_data['selected'] = not widget_data['selected']
                    idx = self.video_item_widgets.index(widget_data)
                    
                    if widget_data['selected']:
                        self.video_tree.item(item, tags=('selected',))
                        self.video_tree.item(item, text=f"☑ {idx+1}")
                        self.video_tree.selection_add(item)
                    else:
                        self.video_tree.item(item, tags=())
                        self.video_tree.item(item, text=f"☐ {idx+1}")
                        self.video_tree.selection_remove(item)
                    
                    # Show thumbnail for the clicked item
                    self.show_thumbnail(widget_data['entry'])
                    self.update_selected_count()
                    break
            # Prevent default Treeview selection behavior from overriding checkbox state
            return "break"
        
        # Checkbox toggle logic (tree column = the #0 / checkbox column)
        if region == 'tree':
            if item:
                # Find widget data
                for widget_data in self.video_item_widgets:
                    if widget_data['item_id'] == item:
                        # Toggle selection
                        widget_data['selected'] = not widget_data['selected']
                        idx = self.video_item_widgets.index(widget_data)
                        
                        if widget_data['selected']:
                            self.video_tree.item(item, tags=('selected',))
                            self.video_tree.item(item, text=f"☑ {idx+1}")
                            # Add to Treeview selection so count & download see it
                            self.video_tree.selection_add(item)
                        else:
                            self.video_tree.item(item, tags=())
                            self.video_tree.item(item, text=f"☐ {idx+1}")
                            # Remove from Treeview selection
                            self.video_tree.selection_remove(item)
                        
                        self.update_selected_count()
                        break
                # Prevent default Treeview selection behavior from overriding
                return "break"
    
    def on_video_select(self, event):
        """Handle video selection to show thumbnail"""
        selection = self.video_tree.selection()
        if not selection:
            return
        
        # Get first selected item
        item_id = selection[0]
        
        # Find corresponding entry
        for widget_data in self.video_item_widgets:
            if widget_data['item_id'] == item_id:
                entry = widget_data['entry']
                self.show_thumbnail(entry)
                break
    
    def on_tree_double_click(self, event):
        """Handle double-click on tree item for quick quality selection"""
        region = self.video_tree.identify('region', event.x, event.y)
        if region == 'cell':
            # Identify which column was clicked
            column = self.video_tree.identify_column(event.x)
            item = self.video_tree.identify_row(event.y)
            
            if item and column == '#4':  # Quality column
                self.show_quality_dialog(item)
    
    def show_context_menu(self, event):
        """Show context menu for tree item"""
        item = self.video_tree.identify_row(event.y)
        if not item:
            return
        
        # Select the item
        self.video_tree.selection_set(item)
        
        # Create context menu with organized submenus
        context_menu = tk.Menu(self.window, tearoff=0)
        
        # Quality submenu
        quality_menu = tk.Menu(context_menu, tearoff=0)
        quality_menu.add_command(label="Set Quality Dialog...", 
                                command=lambda: self.show_quality_dialog(item))
        quality_menu.add_command(label="Analyze Available Qualities", 
                                command=lambda: self.analyze_item_quality(item))
        quality_menu.add_separator()
        quality_menu.add_command(label="Best Available", 
                                command=lambda: self.set_item_quality(item, "Best Available"))
        quality_menu.add_command(label="1080p", 
                                command=lambda: self.set_item_quality(item, "1080p"))
        quality_menu.add_command(label="720p", 
                                command=lambda: self.set_item_quality(item, "720p"))
        quality_menu.add_command(label="480p", 
                                command=lambda: self.set_item_quality(item, "480p"))
        quality_menu.add_separator()
        quality_menu.add_command(label="Audio Only (Best)", 
                                command=lambda: self.set_item_audio_only(item, "Best Audio"))
        quality_menu.add_command(label="Audio Only (128k)", 
                                command=lambda: self.set_item_audio_only(item, "128k"))
        context_menu.add_cascade(label="Quality", menu=quality_menu)
        
        # Info submenu
        info_menu = tk.Menu(context_menu, tearoff=0)
        info_menu.add_command(label="Show Video Info", 
                             command=lambda: self.show_item_info(item))
        info_menu.add_command(label="🔍 Analyze Formats", 
                             command=lambda: self.show_format_analysis(item))
        info_menu.add_command(label="Show Thumbnail", 
                             command=lambda: self.show_item_thumbnail(item))
        info_menu.add_command(label="Show Description", 
                             command=lambda: self.show_item_description(item))
        info_menu.add_command(label="Show Stats", 
                             command=lambda: self.show_item_stats(item))
        context_menu.add_cascade(label="Information", menu=info_menu)
        
        # Copy submenu
        copy_menu = tk.Menu(context_menu, tearoff=0)
        copy_menu.add_command(label="Copy URL", 
                             command=lambda: self.copy_item_url(item))
        copy_menu.add_command(label="Copy Title", 
                             command=lambda: self.copy_item_title(item))
        copy_menu.add_command(label="Copy Video ID", 
                             command=lambda: self.copy_item_video_id(item))
        copy_menu.add_command(label="Copy Channel Name", 
                             command=lambda: self.copy_item_channel_name(item))
        copy_menu.add_command(label="Copy Channel URL", 
                             command=lambda: self.copy_item_channel_url(item))
        copy_menu.add_command(label="Copy Thumbnail URL", 
                             command=lambda: self.copy_item_thumbnail_url(item))
        copy_menu.add_separator()
        copy_menu.add_command(label="Copy All Info", 
                             command=lambda: self.copy_item_all_info(item))
        context_menu.add_cascade(label="Copy", menu=copy_menu)
        
        # Open submenu
        open_menu = tk.Menu(context_menu, tearoff=0)
        open_menu.add_command(label="Open Video in Browser", 
                             command=lambda: self.open_item_in_browser(item))
        open_menu.add_command(label="Open Channel", 
                             command=lambda: self.open_item_channel(item))
        open_menu.add_command(label="Open Thumbnail", 
                             command=lambda: self.open_item_thumbnail_browser(item))
        context_menu.add_cascade(label="Open", menu=open_menu)
        
        # Selection submenu
        selection_menu = tk.Menu(context_menu, tearoff=0)
        selection_menu.add_command(label="Select All Above", 
                                  command=lambda: self.select_all_above(item))
        selection_menu.add_command(label="Select All Below", 
                                  command=lambda: self.select_all_below(item))
        selection_menu.add_separator()
        selection_menu.add_command(label="Select Same Uploader", 
                                  command=lambda: self.select_same_uploader(item))
        selection_menu.add_command(label="Select Similar Duration", 
                                  command=lambda: self.select_similar_duration(item))
        context_menu.add_cascade(label="Selection", menu=selection_menu)
        
        context_menu.add_separator()
        context_menu.add_command(label="Download This Item", 
                                command=lambda: self.download_single_item(item))
        context_menu.add_command(label="Skip This Item", 
                                command=lambda: self.skip_item(item))
        context_menu.add_separator()
        context_menu.add_command(label="Remove from List", 
                                command=lambda: self.remove_item_from_list(item))
        
        # Show menu at cursor
        context_menu.tk_popup(event.x_root, event.y_root)
    
    def set_item_quality(self, item_id, quality):
        """Set quality for specific item"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                self.video_tree.set(item_id, 'quality', quality)
                self.log_callback(f"🎬 Set quality to {quality}")
                break
    
    def set_item_audio_only(self, item_id, quality):
        """Set item to audio-only download"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                self.video_tree.set(item_id, 'quality', f"Audio: {quality}")
                self.log_callback(f"🎵 Set to audio only: {quality}")
                break
    
    def show_item_description(self, item_id):
        """Show full description in a window"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                entry = w['entry']
                desc = entry.get('description', 'No description available')
                title = entry.get('title', 'Unknown')
                
                desc_window = tk.Toplevel(self.window)
                desc_window.title(f"Description - {title[:40]}")
                desc_window.geometry("600x400")
                
                text_widget = tk.Text(desc_window, wrap=tk.WORD, padx=10, pady=10)
                text_widget.pack(fill=tk.BOTH, expand=True)
                text_widget.insert('1.0', desc)
                text_widget.config(state=tk.DISABLED)
                
                scrollbar = ttk.Scrollbar(text_widget)
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                text_widget.config(yscrollcommand=scrollbar.set)
                scrollbar.config(command=text_widget.yview)
                break
    
    def show_item_stats(self, item_id):
        """Show detailed stats"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                entry = w['entry']
                stats = f"""Title: {entry.get('title', 'N/A')}
Views: {entry.get('view_count', 'N/A'):,} views
Likes: {entry.get('like_count', 'N/A'):,}
Comments: {entry.get('comment_count', 'N/A'):,}
Upload Date: {entry.get('upload_date', 'N/A')}
Duration: {entry.get('duration_string', 'N/A')}
Channel: {entry.get('uploader', 'N/A')}
Subscribers: {entry.get('channel_follower_count', 'N/A'):,}"""
                
                messagebox.showinfo("Video Statistics", stats, parent=self.window)
                break
    
    def copy_item_channel_name(self, item_id):
        """Copy channel name to clipboard"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                channel = w['entry'].get('uploader', 'Unknown')
                self.window.clipboard_clear()
                self.window.clipboard_append(channel)
                self.log_callback(f"📋 Copied channel: {channel}")
                break
    
    def copy_item_channel_url(self, item_id):
        """Copy channel URL to clipboard"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                channel_url = w['entry'].get('channel_url', '')
                channel_id = w['entry'].get('channel_id', '')
                url = channel_url or f"https://www.youtube.com/channel/{channel_id}" if channel_id else "N/A"
                self.window.clipboard_clear()
                self.window.clipboard_append(url)
                self.log_callback(f"📋 Copied channel URL: {url}")
                break
    
    def copy_item_thumbnail_url(self, item_id):
        """Copy thumbnail URL to clipboard"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                thumb_url = w['entry'].get('thumbnail', 'N/A')
                self.window.clipboard_clear()
                self.window.clipboard_append(thumb_url)
                self.log_callback(f"📋 Copied thumbnail URL")
                break
    
    def copy_item_all_info(self, item_id):
        """Copy all video info as formatted text"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                entry = w['entry']
                info_text = f"""Title: {entry.get('title', 'N/A')}
URL: {self.get_video_url(entry)}
Video ID: {entry.get('id', 'N/A')}
Channel: {entry.get('uploader', 'N/A')}
Channel URL: {entry.get('channel_url', 'N/A')}
Duration: {entry.get('duration_string', 'N/A')}
Upload Date: {entry.get('upload_date', 'N/A')}
Views: {entry.get('view_count', 'N/A'):,}
Likes: {entry.get('like_count', 'N/A'):,}
Comments: {entry.get('comment_count', 'N/A'):,}
Thumbnail: {entry.get('thumbnail', 'N/A')}"""
                
                self.window.clipboard_clear()
                self.window.clipboard_append(info_text)
                self.log_callback("📋 Copied all video info")
                break
    
    def open_item_thumbnail_browser(self, item_id):
        """Open thumbnail in browser"""
        import webbrowser
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                thumb_url = w['entry'].get('thumbnail', '')
                if thumb_url:
                    webbrowser.open(thumb_url)
                    self.log_callback("🌐 Opening thumbnail in browser")
                break
    
    def select_all_above(self, item_id):
        """Select all items above the clicked item"""
        all_items = self.video_tree.get_children()
        item_index = all_items.index(item_id)
        
        for i in range(item_index + 1):
            self.video_tree.selection_add(all_items[i])
        
        self.log_callback(f"✓ Selected {item_index + 1} items above")
        self.update_selected_count()
    
    def select_all_below(self, item_id):
        """Select all items below the clicked item"""
        all_items = self.video_tree.get_children()
        item_index = all_items.index(item_id)
        
        for i in range(item_index, len(all_items)):
            self.video_tree.selection_add(all_items[i])
        
        self.log_callback(f"✓ Selected {len(all_items) - item_index} items below")
        self.update_selected_count()
    
    def select_same_uploader(self, item_id):
        """Select all videos from same uploader"""
        target_uploader = None
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                target_uploader = w['entry'].get('uploader')
                break
        
        if not target_uploader:
            return
        
        count = 0
        for w in self.video_item_widgets:
            if w['entry'].get('uploader') == target_uploader:
                self.video_tree.selection_add(w['item_id'])
                count += 1
        
        self.log_callback(f"✓ Selected {count} videos from {target_uploader}")
        self.update_selected_count()
    
    def select_similar_duration(self, item_id):
        """Select videos with similar duration (±20%)"""
        target_duration = None
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                target_duration = w['entry'].get('duration', 0)
                break
        
        if not target_duration:
            return
        
        min_dur = target_duration * 0.8
        max_dur = target_duration * 1.2
        count = 0
        
        for w in self.video_item_widgets:
            dur = w['entry'].get('duration', 0)
            if min_dur <= dur <= max_dur:
                self.video_tree.selection_add(w['item_id'])
                count += 1
        
        self.log_callback(f"✓ Selected {count} videos with similar duration")
        self.update_selected_count()
    
    def skip_item(self, item_id):
        """Mark item to be skipped during download"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                w['skip'] = True
                self.video_tree.item(item_id, tags=('skipped',))
                self.video_tree.set(item_id, 'status', '⏸️ Skipped')
                title = w['entry'].get('title', 'Unknown')
                self.log_callback(f"⏸️ Marked to skip: {title}")
                break
    
    def safe_tree_update(self, item_id, column, value):
        """Safely update tree item, checking if window still exists"""
        try:
            if self.window.winfo_exists():
                self.video_tree.set(item_id, column, value)
        except (tk.TclError, AttributeError):
            pass  # Window was closed, silently ignore
    
    def download_item_video_only(self, item_id):
        """Download only video (no audio) for this item"""
        if not hasattr(self, 'path_var'):
            messagebox.showwarning("Not Ready", "Please wait for initialization", parent=self.window)
            return
        
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                title = w['entry'].get('title', 'Unknown')[:40]
                url = self.get_video_url(w['entry'])
                self.log_callback(f"📥 Downloading VIDEO only: {title}")
                self.video_tree.set(item_id, 'dl_video', '⏳')
                
                def download():
                    try:
                        ydl_opts = {
                            'format': 'bestvideo',
                            'outtmpl': str(Path(self.path_var.get()) / f"{title}_video.%(ext)s"),
                            'quiet': True
                        }
                        # Set FFmpeg location if available
                        if self.ffmpeg_location:
                            ydl_opts['ffmpeg_location'] = self.ffmpeg_location
                        # Apply speed optimizations
                        ydl_opts.update(self._get_parallel_download_opts())
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url])
                        self.window.after(0, lambda: self.safe_tree_update(item_id, 'dl_video', '✅'))
                        self.log_callback(f"✅ Video downloaded: {title}")
                    except Exception as e:
                        self.window.after(0, lambda: self.safe_tree_update(item_id, 'dl_video', '❌'))
                        self.log_callback(f"❌ Video download failed: {e}")
                
                threading.Thread(target=download, daemon=True).start()
                break
    
    def download_item_audio_only(self, item_id):
        """Download only audio for this item"""
        if not hasattr(self, 'path_var'):
            messagebox.showwarning("Not Ready", "Please wait for initialization", parent=self.window)
            return
        
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                title = w['entry'].get('title', 'Unknown')[:40]
                url = self.get_video_url(w['entry'])
                self.log_callback(f"🎵 Downloading AUDIO only: {title}")
                self.video_tree.set(item_id, 'dl_audio', '⏳')
                
                def download():
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': str(Path(self.path_var.get()) / f"{title}_audio.%(ext)s"),
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '320',
                            }],
                            'quiet': True
                        }
                        # Set FFmpeg location if available
                        if self.ffmpeg_location:
                            ydl_opts['ffmpeg_location'] = self.ffmpeg_location
                        # Apply speed optimizations
                        ydl_opts.update(self._get_parallel_download_opts())
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url])
                        self.window.after(0, lambda: self.safe_tree_update(item_id, 'dl_audio', '✅'))
                        self.log_callback(f"✅ Audio downloaded: {title}")
                    except Exception as e:
                        self.window.after(0, lambda: self.safe_tree_update(item_id, 'dl_audio', '❌'))
                        self.log_callback(f"❌ Audio download failed: {e}")
                
                threading.Thread(target=download, daemon=True).start()
                break
    
    def download_item_subs_only(self, item_id):
        """Download only subtitles for this item"""
        if not hasattr(self, 'path_var'):
            messagebox.showwarning("Not Ready", "Please wait for initialization", parent=self.window)
            return
        
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                title = w['entry'].get('title', 'Unknown')[:40]
                url = self.get_video_url(w['entry'])
                self.log_callback(f"📝 Downloading SUBTITLES: {title}")
                self.video_tree.set(item_id, 'dl_subs', '⏳')
                
                def download():
                    try:
                        ydl_opts = {
                            'skip_download': True,
                            'writesubtitles': True,
                            'writeautomaticsub': True,
                            'subtitleslangs': ['en'],
                            'outtmpl': str(Path(self.path_var.get()) / f"{title}.%(ext)s"),
                            'quiet': True
                        }
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url])
                        self.window.after(0, lambda: self.safe_tree_update(item_id, 'dl_subs', '✅'))
                        self.log_callback(f"✅ Subtitles downloaded: {title}")
                    except Exception as e:
                        self.window.after(0, lambda: self.safe_tree_update(item_id, 'dl_subs', '❌'))
                        self.log_callback(f"❌ Subtitles download failed: {e}")
                
                threading.Thread(target=download, daemon=True).start()
                break
    
    def download_item_thumb_only(self, item_id):
        """Download only thumbnail for this item"""
        if not hasattr(self, 'path_var'):
            messagebox.showwarning("Not Ready", "Please wait for initialization", parent=self.window)
            return
        
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                title = w['entry'].get('title', 'Unknown')[:40]
                thumbnail_url = w['entry'].get('thumbnail', '')
                if not thumbnail_url:
                    messagebox.showinfo("No Thumbnail", "No thumbnail available for this video", parent=self.window)
                    return
                
                self.log_callback(f"🖼️ Downloading THUMBNAIL: {title}")
                self.video_tree.set(item_id, 'dl_thumb', '⏳')
                
                def download():
                    try:
                        import urllib.request
                        # Get file extension from URL
                        ext = thumbnail_url.split('.')[-1].split('?')[0] or 'jpg'
                        save_path = Path(self.path_var.get()) / f"{title}_thumb.{ext}"
                        urllib.request.urlretrieve(thumbnail_url, save_path)
                        self.window.after(0, lambda: self.safe_tree_update(item_id, 'dl_thumb', '✅'))
                        self.log_callback(f"✅ Thumbnail saved: {save_path.name}")
                    except Exception as e:
                        self.window.after(0, lambda: self.safe_tree_update(item_id, 'dl_thumb', '❌'))
                        self.log_callback(f"❌ Thumbnail download failed: {e}")
                
                threading.Thread(target=download, daemon=True).start()
                break
    
    def show_quality_dialog(self, item_id):
        """Show quality selection dialog for specific item"""
        # Safety check - download_type must exist
        if not hasattr(self, 'download_type'):
            messagebox.showerror("Not Ready", 
                               "Download settings not initialized yet. Please wait for the window to fully load.",
                               parent=self.window)
            return
        
        # Find widget data
        widget_data = None
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                widget_data = w
                break
        
        if not widget_data:
            return
        
        title = widget_data['entry'].get('title', 'Unknown')
        
        # Create quality selection dialog
        quality_window = tk.Toplevel(self.window)
        quality_window.title(f"Quality Settings - {title[:40]}")
        quality_window.geometry("400x500")
        quality_window.transient(self.window)
        quality_window.grab_set()
        
        main_frame = ttk.Frame(quality_window, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text=f"Video: {title[:50]}", 
                 font=('Arial', 10, 'bold'), wraplength=370).pack(pady=(0, 15))
        
        # Download type
        type_frame = ttk.LabelFrame(main_frame, text="Download Type", padding="10")
        type_frame.pack(fill=tk.X, pady=(0, 10))
        
        item_type = tk.StringVar(value=self.download_type.get())
        ttk.Radiobutton(type_frame, text="🎥 Video", variable=item_type, 
                       value="video").pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(type_frame, text="🎵 Audio Only", variable=item_type, 
                       value="audio").pack(anchor=tk.W, pady=2)
        
        # Video quality
        video_frame = ttk.LabelFrame(main_frame, text="Video Quality", padding="10")
        video_frame.pack(fill=tk.X, pady=(0, 10))
        
        current_quality = self.video_tree.set(item_id, 'quality')
        quality_var = tk.StringVar(value=current_quality or 'Best')
        
        qualities = ['Best', '2160p (4K)', '1440p (2K)', '1080p', '720p', '480p', '360p', '240p']
        for q in qualities:
            ttk.Radiobutton(video_frame, text=q, variable=quality_var, 
                           value=q.split()[0]).pack(anchor=tk.W, pady=1)
        
        # Audio quality
        audio_frame = ttk.LabelFrame(main_frame, text="Audio Quality", padding="10")
        audio_frame.pack(fill=tk.X, pady=(0, 10))
        
        audio_var = tk.StringVar(value='320kbps')
        audio_qualities = ['Best Audio', '320kbps MP3', '192kbps MP3', '128kbps MP3']
        for aq in audio_qualities:
            ttk.Radiobutton(audio_frame, text=aq, variable=audio_var, 
                           value=aq.split()[0]).pack(anchor=tk.W, pady=1)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(15, 0))
        
        def apply_quality():
            selected_quality = quality_var.get() if item_type.get() == 'video' else audio_var.get()
            self.video_tree.set(item_id, 'quality', selected_quality)
            widget_data['quality'] = selected_quality
            widget_data['download_type'] = item_type.get()
            self.log_callback(f"✅ Set '{title[:40]}' to {selected_quality} ({item_type.get()})")
            quality_window.destroy()
        
        ttk.Button(button_frame, text="✓ Apply", command=apply_quality).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="✗ Cancel", command=quality_window.destroy).pack(side=tk.LEFT, padx=5)
    
    def analyze_item_quality(self, item_id):
        """Analyze available qualities for a specific item"""
        for idx, w in enumerate(self.video_item_widgets):
            if w['item_id'] == item_id:
                self.analyze_video_quality(idx, w['entry'])
                break
    
    def show_item_info(self, item_id):
        """Show detailed info for a specific item"""
        for idx, w in enumerate(self.video_item_widgets):
            if w['item_id'] == item_id:
                self.show_video_info(idx, w['entry'])
                break
    
    def copy_item_url(self, item_id):
        """Copy video URL to clipboard"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                video_id = w['entry'].get('id') or w['entry'].get('url')
                if video_id:
                    if not video_id.startswith('http'):
                        url = f"https://www.youtube.com/watch?v={video_id}"
                    else:
                        url = video_id
                    self.window.clipboard_clear()
                    self.window.clipboard_append(url)
                    self.log_callback(f"📋 Copied URL: {url}")
                break
    
    def download_single_item(self, item_id):
        """Download a single item immediately"""
        # Safety check - path_var must exist
        if not hasattr(self, 'path_var'):
            messagebox.showerror("Not Ready", 
                               "Download settings not initialized yet. Please wait for the window to fully load.",
                               parent=self.window)
            return
        
        for idx, w in enumerate(self.video_item_widgets):
            if w['item_id'] == item_id:
                title = w['entry'].get('title', 'Unknown')
                if messagebox.askyesno("Download Single Video", 
                                      f"Download '{title[:50]}'?", 
                                      parent=self.window):
                    self.log_callback(f"📥 Starting single download: {title}")
                    download_path = Path(self.path_var.get())
                    threading.Thread(target=self.download_single_video, 
                                   args=(self.get_video_url(w['entry']), download_path, w),
                                   daemon=True).start()
                break
    
    def get_video_url(self, entry):
        """Get video URL from entry"""
        video_id = entry.get('id') or entry.get('url')
        if not video_id:
            return None
        if not video_id.startswith('http'):
            return f"https://www.youtube.com/watch?v={video_id}"
        return video_id
    
    def show_item_thumbnail(self, item_id):
        """Show thumbnail for a specific item in a popup window"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                self.show_thumbnail_popup(w['entry'])
                break
    
    def copy_item_title(self, item_id):
        """Copy video title to clipboard"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                title = w['entry'].get('title', 'Unknown')
                self.window.clipboard_clear()
                self.window.clipboard_append(title)
                self.log_callback(f"📋 Copied title: {title[:50]}")
                break
    
    def copy_item_video_id(self, item_id):
        """Copy video ID to clipboard"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                video_id = w['entry'].get('id', 'Unknown')
                self.window.clipboard_clear()
                self.window.clipboard_append(video_id)
                self.log_callback(f"📋 Copied video ID: {video_id}")
                break
    
    def open_item_in_browser(self, item_id):
        """Open video in default browser"""
        import webbrowser
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                url = self.get_video_url(w['entry'])
                if url:
                    webbrowser.open(url)
                    self.log_callback(f"🌐 Opening in browser: {url}")
                break
    
    def open_item_channel(self, item_id):
        """Open video's channel in default browser"""
        import webbrowser
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                channel_id = w['entry'].get('channel_id')
                channel_url = w['entry'].get('channel_url')
                uploader = w['entry'].get('uploader', 'Unknown')
                
                if channel_url:
                    url = channel_url
                elif channel_id:
                    url = f"https://www.youtube.com/channel/{channel_id}"
                else:
                    self.log_callback(f"⚠️ Channel URL not available")
                    return
                
                webbrowser.open(url)
                self.log_callback(f"🌐 Opening channel: {uploader}")
                break
    
    def remove_item_from_list(self, item_id):
        """Remove item from the list"""
        for idx, w in enumerate(self.video_item_widgets):
            if w['item_id'] == item_id:
                title = w['entry'].get('title', 'Unknown')
                if messagebox.askyesno("Remove Video", 
                                      f"Remove '{title[:50]}' from list?", 
                                      parent=self.window):
                    # Remove from tree
                    self.video_tree.delete(item_id)
                    # Remove from widget list
                    self.video_item_widgets.pop(idx)
                    self.log_callback(f"🗑️ Removed: {title}")
                    # Update numbering
                    self.renumber_items()
                    self.update_selected_count()
                break
    
    def renumber_items(self):
        """Renumber all items after deletion"""
        for idx, widget_data in enumerate(self.video_item_widgets):
            item_id = widget_data['item_id']
            checkbox = "☑" if widget_data.get('selected', True) else "☐"
            self.video_tree.item(item_id, text=f"{checkbox} {idx+1}")
    
    def show_thumbnail(self, entry):
        """Display video thumbnail in the preview panel"""
        try:
            thumbnail_url = entry.get('thumbnail')
            title = entry.get('title', 'Unknown')
            duration = entry.get('duration', 0)
            uploader = entry.get('uploader', 'Unknown')
            
            if not thumbnail_url:
                self.thumbnail_label.config(text="No thumbnail available", image='')
                return
            
            # Download and display thumbnail in background thread
            def load_thumb():
                try:
                    import urllib.request
                    from PIL import Image, ImageTk
                    import io
                    
                    # Download thumbnail
                    with urllib.request.urlopen(thumbnail_url, timeout=5) as response:
                        img_data = response.read()
                    
                    # Open and resize
                    img = Image.open(io.BytesIO(img_data))
                    img.thumbnail((280, 160), Image.Resampling.LANCZOS)
                    
                    # Convert to PhotoImage
                    photo = ImageTk.PhotoImage(img)
                    
                    # Update label (must be in main thread)
                    def update_preview():
                        try:
                            self.thumbnail_label.config(image=photo, text='')
                            self.thumbnail_label.image = photo  # Keep reference
                        except (tk.TclError, AttributeError):
                            pass  # Widget destroyed
                    
                    self.window.after(0, update_preview)
                    
                except Exception:
                    # Thumbnail failed to load, show text info instead
                    def show_error():
                        try:
                            self.thumbnail_label.config(
                                text=f"📷 {title[:30]}\n👤 {uploader}\n⏱️ {duration//60}:{duration%60:02d}",
                                image='')
                        except (tk.TclError, AttributeError):
                            pass  # Widget destroyed
                    self.window.after(0, show_error)
            
            threading.Thread(target=load_thumb, daemon=True).start()
            
        except Exception as e:
            self.thumbnail_label.config(text="Preview unavailable", image='')
    
    def show_thumbnail_popup(self, entry):
        """Display video thumbnail in a popup window"""
        try:
            thumbnail_url = entry.get('thumbnail')
            title = entry.get('title', 'Unknown')
            duration = entry.get('duration', 0)
            uploader = entry.get('uploader', 'Unknown')
            
            if not thumbnail_url:
                messagebox.showinfo("No Thumbnail", "No thumbnail available for this video", parent=self.window)
                return
            
            # Create popup window
            thumb_window = tk.Toplevel(self.window)
            thumb_window.title("📷 Thumbnail Preview")
            thumb_window.geometry("600x450")
            
            # Info frame
            info_frame = ttk.Frame(thumb_window, padding="10")
            info_frame.pack(fill=tk.X)
            
            ttk.Label(info_frame, text=f"📹 {title}", font=('Arial', 10, 'bold'), wraplength=580).pack(anchor=tk.W)
            ttk.Label(info_frame, text=f"👤 {uploader}", font=('Arial', 9)).pack(anchor=tk.W, pady=(2, 0))
            
            # Additional info row
            details_frame = ttk.Frame(info_frame)
            details_frame.pack(fill=tk.X, pady=(5, 0))
            
            # Duration
            if duration:
                duration_text = f"⏱️ {duration//60}:{duration%60:02d}"
                ttk.Label(details_frame, text=duration_text, font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 15))
            
            # Resolution
            resolution = entry.get('resolution', '')
            if resolution:
                ttk.Label(details_frame, text=f"📐 {resolution}", font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 15))
            
            # File size
            filesize = entry.get('filesize', 0)
            if filesize and filesize > 0:
                size_mb = filesize / (1024 * 1024)
                if size_mb >= 1024:
                    size_text = f"💾 {size_mb/1024:.2f} GB"
                else:
                    size_text = f"💾 {size_mb:.1f} MB"
                ttk.Label(details_frame, text=size_text, font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 15))
            
            # Format
            format_str = entry.get('format', '') or entry.get('ext', '')
            if format_str:
                # Extract just the extension or format code
                if ' - ' in format_str:
                    format_str = format_str.split(' - ')[0]
                ttk.Label(details_frame, text=f"📦 {format_str}", font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 15))
            
            # FPS (if available)
            fps = entry.get('fps', '')
            if fps:
                ttk.Label(details_frame, text=f"🎬 {fps} fps", font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 15))
            
            # Thumbnail image format
            if thumbnail_url:
                # Try to detect image format from URL
                img_format = 'unknown'
                url_lower = thumbnail_url.lower()
                if '.jpg' in url_lower or '.jpeg' in url_lower:
                    img_format = 'JPEG'
                elif '.png' in url_lower:
                    img_format = 'PNG'
                elif '.webp' in url_lower:
                    img_format = 'WebP'
                elif '.gif' in url_lower:
                    img_format = 'GIF'
                elif '.bmp' in url_lower:
                    img_format = 'BMP'
                elif '.svg' in url_lower:
                    img_format = 'SVG'
                
                if img_format != 'unknown':
                    ttk.Label(details_frame, text=f"🖼️ {img_format}", font=('Arial', 9)).pack(side=tk.LEFT, padx=(0, 15))
            
            ttk.Separator(thumb_window, orient='horizontal').pack(fill=tk.X, pady=5)
            
            # Image frame
            img_frame = ttk.Frame(thumb_window, padding="10")
            img_frame.pack(fill=tk.BOTH, expand=True)
            
            status_label = ttk.Label(img_frame, text="⏳ Loading thumbnail...", font=('Arial', 10))
            status_label.pack(pady=50)
            
            # Download and display thumbnail in background thread
            def load_thumb():
                try:
                    import urllib.request
                    from PIL import Image, ImageTk
                    import io
                    
                    # Download thumbnail
                    with urllib.request.urlopen(thumbnail_url, timeout=10) as response:
                        img_data = response.read()
                    
                    # Open and resize
                    img = Image.open(io.BytesIO(img_data))
                    # Resize to fit window while maintaining aspect ratio
                    img.thumbnail((560, 340), Image.Resampling.LANCZOS)
                    
                    # Convert to PhotoImage
                    photo = ImageTk.PhotoImage(img)
                    
                    # Update display (must be in main thread)
                    def update_img():
                        try:
                            status_label.pack_forget()
                            img_label = ttk.Label(img_frame, image=photo)
                            img_label.image = photo  # Keep reference
                            img_label.pack()
                        except:
                            pass
                    
                    self.window.after(0, update_img)
                    
                except Exception as e:
                    def show_error():
                        try:
                            status_label.config(text=f"❌ Failed to load thumbnail\n{str(e)}")
                        except:
                            pass
                    self.window.after(0, show_error)
            
            threading.Thread(target=load_thumb, daemon=True).start()
            
            # Button frame
            btn_frame = ttk.Frame(thumb_window, padding="10")
            btn_frame.pack(fill=tk.X)
            
            import webbrowser
            ttk.Button(btn_frame, text="Open in Browser", 
                      command=lambda: webbrowser.open(thumbnail_url)).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_frame, text="Close", 
                      command=thumb_window.destroy).pack(side=tk.RIGHT, padx=5)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to show thumbnail: {e}", parent=self.window)
    
    # Old create_video_item function removed - now using Treeview

    
    def toggle_mode(self):
        """Toggle between simple and advanced mode with enhanced visual feedback"""
        self.is_advanced_mode = not self.is_advanced_mode
        
        if self.is_advanced_mode:
            # Switch to Advanced Mode
            self.mode_btn.config(text="📋 Simple")
            self.mode_indicator.config(text="⚡ Advanced", foreground='green')
            self.mode_description.config(text="Individual: set quality per video")
            
            self.log_callback("⚡ Switching to Advanced Mode...")
            
            # Hide simple quality frame
            if hasattr(self, 'simple_quality_frame'):
                self.simple_quality_frame.grid_remove()
                self.log_callback("  ✓ Hidden batch quality settings")
            
            # Show quick actions frame
            if hasattr(self, 'quick_actions_frame'):
                self.quick_actions_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
                self.log_callback("  ✓ Showing quick action buttons")
            
            # Show plugins frame if available
            if hasattr(self, 'plugins_frame') and self.has_plugins:
                self.plugins_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
                self.log_callback("  ✓ Showing plugins panel")
            
            self.log_callback("✅ Advanced Mode Active")
            self.log_callback("   → Right-click videos for per-item quality control")
            self.log_callback("   → Use Quick Actions to set quality for selected videos")
            
            if hasattr(self, 'status_var'):
                self.status_var.set("⚡ Advanced Mode: Individual video control")
        else:
            # Switch to Simple Mode
            self.mode_btn.config(text="⚡ Advanced")
            self.mode_indicator.config(text="📋 Simple Mode", foreground='blue')
            self.mode_description.config(text="Batch: one quality for all")
            
            self.log_callback("📋 Switching to Simple Mode...")
            
            # Hide quick actions
            if hasattr(self, 'quick_actions_frame'):
                self.quick_actions_frame.grid_remove()
                self.log_callback("  ✓ Hidden quick actions")
            
            # Hide plugins
            if hasattr(self, 'plugins_frame'):
                self.plugins_frame.grid_remove()
                self.log_callback("  ✓ Hidden plugins")
            
            # Show simple quality frame
            if hasattr(self, 'simple_quality_frame'):
                self.simple_quality_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
                self.log_callback("  ✓ Showing batch quality settings")
            
            self.log_callback("✅ Simple Mode Active")
            self.log_callback("   → One quality setting applies to all videos")
            self.log_callback("   → Faster batch processing")
            
            if hasattr(self, 'status_var'):
                self.status_var.set("📋 Simple Mode: Batch processing")
    
    def toggle_download_type(self):
        """Toggle between video and audio download"""
        if self.download_type.get() == "video":
            self.audio_quality_frame.grid_remove()
            self.simple_quality_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        else:
            self.simple_quality_frame.grid_remove()
            self.audio_quality_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.update_stats()
    
    def toggle_thumbnails(self):
        """Toggle thumbnail display"""
        if self.show_thumbnails.get():
            self.log_callback("🖼️ Loading thumbnails... (this may take a moment)")
            # TODO: Implement thumbnail loading
        else:
            self.log_callback("Thumbnails disabled")
    
    def filter_videos(self):
        """Filter videos based on search text"""
        search_text = self.search_var.get().lower()
        visible_count = 0
        
        # Detach all items first
        for item in self.video_tree.get_children():
            self.video_tree.detach(item)
        
        # Re-attach items that match the search
        for widget_data in self.video_item_widgets:
            title = widget_data['entry'].get('title', '').lower()
            if search_text in title:
                self.video_tree.reattach(widget_data['item_id'], '', 'end')
                visible_count += 1
        
        self.status_var.set(f"Showing {visible_count} of {self.video_count} videos")
    
    def sort_by_column(self, col):
        """Sort tree by clicking on column header"""
        # Toggle sort direction if clicking same column
        if self.current_sort_col == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_reverse = False
            self.current_sort_col = col
        
        # Update column headers to show sort direction
        all_columns = ('status', 'title', 'description', 'uploader', 'video_id', 'channel_id', 'url', 'thumbnail',
                      'duration', 'duration_string', 'upload_date', 'timestamp', 'views', 'likes', 'comments', 
                      'subscribers', 'subtitles', 'resolution', 'fps', 'format', 'category', 'availability', 
                      'location', 'tags', 'tags_list', 'chapters', 'chapters_list', 'live_status', 'age_limit', 
                      'verified', 'aspect_ratio', 'language', 'filesize', 'quality', 'size', 'progress', 'speed')
        for column in all_columns:
            if column == col:
                arrow = ' ▲' if self.sort_reverse else ' ▼'
                header_text = 'Subs' if column == 'subtitles' else column.replace('_', ' ').title()
                self.video_tree.heading(column, text=header_text + arrow)
            else:
                header_text = 'Subs' if column == 'subtitles' else column.replace('_', ' ').title()
                self.video_tree.heading(column, text=header_text)
        
        # Get all items with their data
        items_data = []
        for item_id in self.video_tree.get_children():
            values = self.video_tree.item(item_id)['values']
            # Find the widget data for this item
            widget_data = None
            for w in self.video_item_widgets:
                if w['item_id'] == item_id:
                    widget_data = w
                    break
            items_data.append((item_id, values, widget_data))
        
        # Define sort key based on column
        def get_sort_key(item):
            item_id, values, widget_data = item
            col_index = list(all_columns).index(col)
            value = values[col_index]
            
            # Special handling for different column types
            if col == 'duration':
                # Parse mm:ss to seconds
                if value and value != '?':
                    parts = value.split(':')
                    if len(parts) == 2:
                        return int(parts[0]) * 60 + int(parts[1])
                return 0
            elif col in ('size', 'filesize'):
                # Parse size like "140MB" to number
                if value and value != '?':
                    val_str = value.replace('MB', '').replace('KB', '').replace('GB', '').replace('B', '')
                    try:
                        num = float(val_str)
                        if 'GB' in value:
                            return num * 1024
                        elif 'KB' in value:
                            return num / 1024
                        else:
                            return num
                    except (ValueError, AttributeError):
                        return 0
                return 0
            elif col in ('views', 'likes', 'comments', 'subscribers'):
                # Parse counts like "1.2M" or "500K" to number
                if value and value != '?':
                    if 'M' in value:
                        return float(value.replace('M', '')) * 1000000
                    elif 'K' in value:
                        return float(value.replace('K', '')) * 1000
                    else:
                        try:
                            return float(value)
                        except (ValueError, TypeError):
                            return 0
                return 0
            elif col == 'fps':
                # Parse fps like "60fps" to number
                if value and value != '?':
                    return int(value.replace('fps', ''))
                return 0
            elif col == 'resolution':
                # Parse resolution like "1920x1080" to height for sorting
                if value and value != '?' and 'x' in value:
                    try:
                        return int(value.split('x')[1])
                    except (ValueError, IndexError):
                        return 0
                return 0
            elif col in ('upload_date', 'timestamp'):
                # Already in YYYY-MM-DD format or timestamp, sorts naturally
                return value if value != '?' else '0000-00-00'
            elif col in ('tags', 'chapters', 'age_limit'):
                # Numeric fields shown as text
                try:
                    # Extract numeric value (e.g., "18+" -> 18, "0" -> 0)
                    num_str = value.replace('+', '').replace('All', '0')
                    return int(num_str) if num_str.isdigit() else 0
                except (ValueError, AttributeError):
                    return 0
            elif col == 'aspect_ratio':
                # Float values like "1.78"
                try:
                    return float(value) if value != '?' else 0
                except (ValueError, TypeError):
                    return 0
            elif col in ('title', 'description', 'uploader', 'category', 'format', 'subtitles', 'video_id', 
                        'channel_id', 'url', 'thumbnail', 'availability', 'location', 'live_status', 
                        'verified', 'language', 'tags_list', 'chapters_list', 'duration_string'):
                return str(value).lower()
            else:
                return str(value)
        
        # Sort items
        items_data.sort(key=get_sort_key, reverse=self.sort_reverse)
        
        # Reorder items in tree
        for new_idx, (item_id, values, widget_data) in enumerate(items_data):
            self.video_tree.move(item_id, '', 'end')
            # Update the checkbox number
            checkbox = "☑" if widget_data and widget_data.get('selected', True) else "☐"
            self.video_tree.item(item_id, text=f"{checkbox} {new_idx+1}")
        
        self.log_callback(f"Sorted by {col} ({'descending' if self.sort_reverse else 'ascending'})")
    
    def sort_videos(self):
        """Sort videos based on selected criteria"""
        sort_by = self.sort_var.get()
        
        if sort_by == "Default":
            sorted_items = list(enumerate(self.video_item_widgets))
        elif sort_by.startswith("Title"):
            reverse = "(Z-A)" in sort_by
            sorted_items = sorted(enumerate(self.video_item_widgets),
                                key=lambda x: x[1]['entry'].get('title', '').lower(),
                                reverse=reverse)
        elif sort_by.startswith("Duration"):
            reverse = "Long-Short" in sort_by
            sorted_items = sorted(enumerate(self.video_item_widgets),
                                key=lambda x: x[1]['entry'].get('duration', 0) or 0,
                                reverse=reverse)
        elif sort_by.startswith("Date"):
            # Date sorting: Newest = reverse (most recent first), Oldest = normal (oldest first)
            reverse = "Newest" in sort_by
            sorted_items = sorted(enumerate(self.video_item_widgets),
                                key=lambda x: x[1]['entry'].get('upload_date', '') or '00000000',
                                reverse=reverse)
        else:
            sorted_items = list(enumerate(self.video_item_widgets))
        
        # Reorder items in tree
        for new_idx, (old_idx, widget_data) in enumerate(sorted_items):
            item_id = widget_data['item_id']
            # Move item to the end
            self.video_tree.move(item_id, '', 'end')
            # Update the item number in the tree
            self.video_tree.item(item_id, text=f"☑ {new_idx+1}")
        
        
        self.log_callback(f"Sorted by: {sort_by}")
    
    def toggle_all_checkboxes(self):
        """Toggle all checkboxes when clicking the header checkbox"""
        if self.all_checked:
            self.select_none()
        else:
            self.select_all()
    
    def select_all(self):
        """Select all visible videos"""
        # Get all visible items (not detached by filters)
        all_items = self.video_tree.get_children()
        
        # Update checkbox state for each item
        for item_id in all_items:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    widget_data['selected'] = True
                    idx = self.video_item_widgets.index(widget_data)
                    self.video_tree.item(item_id, text=f"☑ {idx+1}", tags=('selected',))
                    break
        
        self.video_tree.selection_set(all_items)
        self.all_checked = True
        self.video_tree.heading('#0', text='☑')
        self.update_selected_count()
    
    def select_none(self):
        """Deselect all videos"""
        all_items = self.video_tree.get_children()
        
        # Update checkbox state for each item
        for item_id in all_items:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    widget_data['selected'] = False
                    idx = self.video_item_widgets.index(widget_data)
                    self.video_tree.item(item_id, text=f"☐ {idx+1}", tags=())
                    break
        
        self.video_tree.selection_remove(self.video_tree.selection())
        self.all_checked = False
        self.video_tree.heading('#0', text='☐')
        self.update_selected_count()
    
    def invert_selection(self):
        """Invert current selection"""
        all_items = self.video_tree.get_children()
        
        # Update checkbox state for each item
        for item_id in all_items:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    # Toggle selection state
                    widget_data['selected'] = not widget_data['selected']
                    idx = self.video_item_widgets.index(widget_data)
                    
                    if widget_data['selected']:
                        self.video_tree.item(item_id, text=f"☑ {idx+1}", tags=('selected',))
                    else:
                        self.video_tree.item(item_id, text=f"☐ {idx+1}", tags=())
                    break
        
        # Update tree selection to match
        currently_selected = set(self.video_tree.selection())
        all_items_set = set(all_items)
        new_selection = all_items_set - currently_selected
        
        if currently_selected:
            self.video_tree.selection_remove(list(currently_selected))
        if new_selection:
            self.video_tree.selection_add(list(new_selection))
        
        self.update_selected_count()
    
    def show_column_selector(self):
        """Show dialog to select which columns to display"""
        column_window = tk.Toplevel(self.window)
        column_window.title("👁 Column Visibility")
        column_window.geometry("550x700")
        column_window.resizable(False, False)
        
        main_frame = ttk.Frame(column_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Column definitions with user-friendly names (moved here for preset access)
        column_info = {
            'status': ('Status', '✓'),
            'group': ('Download Group', '✓'),
            'title': ('Title', '✓'),
            'description': ('Description', ''),
            'uploader': ('Channel/Uploader', '✓'),
            'video_id': ('Video ID', ''),
            'channel_id': ('Channel ID', ''),
            'url': ('URL', ''),
            'thumbnail': ('Thumbnail URL', ''),
            'duration': ('Duration (seconds)', '✓'),
            'duration_string': ('Duration (formatted)', ''),
            'upload_date': ('Upload Date', '✓'),
            'timestamp': ('Timestamp', ''),
            'views': ('View Count', '✓'),
            'likes': ('Like Count', '✓'),
            'comments': ('Comment Count', ''),
            'subscribers': ('Subscriber Count', ''),
            'subtitles': ('Subtitles', ''),
            'resolution': ('Resolution', '✓'),
            'fps': ('FPS', ''),
            'format': ('Format', ''),
            'category': ('Category', ''),
            'availability': ('Availability', ''),
            'location': ('Location', ''),
            'tags': ('Tags', ''),
            'tags_list': ('Tags List', ''),
            'chapters': ('Chapters', ''),
            'chapters_list': ('Chapters List', ''),
            'live_status': ('Live Status', ''),
            'age_limit': ('Age Limit', ''),
            'verified': ('Verified Channel', ''),
            'aspect_ratio': ('Aspect Ratio', ''),
            'language': ('Language', ''),
            'filesize': ('File Size', ''),
            'quality': ('Quality', ''),
            'size': ('Size', ''),
            'progress': ('Progress', ''),
            'speed': ('Speed', '')
        }
        
        # Store checkbox variables (initialize early)
        self.column_vars = {}
        
        # Title
        ttk.Label(main_frame, text="Select Columns to Display", font=('Arial', 14, 'bold')).pack(pady=(0, 10))
        ttk.Label(main_frame, text="Download action columns (📥🎵📝🖼️) are always visible", 
                 font=('Arial', 9, 'italic')).pack(pady=(0, 5))
        
        # Quick Presets section
        presets_frame = ttk.LabelFrame(main_frame, text="Quick Presets", padding="10")
        presets_frame.pack(fill=tk.X, pady=(0, 10))
        
        def apply_preset(preset_name):
            if preset_name == "Minimal":
                # Only essential columns
                essential = ['status', 'group', 'title', 'uploader', 'duration', 'resolution']
                for col in column_info.keys():
                    self.column_vars[col].set(col in essential)
            elif preset_name == "Standard":
                # Essential + basic metrics
                standard = ['status', 'group', 'title', 'uploader', 'duration', 'upload_date', 
                           'views', 'likes', 'resolution', 'quality']
                for col in column_info.keys():
                    self.column_vars[col].set(col in standard)
            elif preset_name == "Full":
                # All columns
                for col in column_info.keys():
                    self.column_vars[col].set(True)
            elif preset_name == "Download":
                # Download-focused columns
                download = ['status', 'group', 'title', 'duration', 'quality', 'size', 
                           'progress', 'speed', 'resolution', 'filesize']
                for col in column_info.keys():
                    self.column_vars[col].set(col in download)
        
        btn_frame = ttk.Frame(presets_frame)
        btn_frame.pack()
        
        ttk.Button(btn_frame, text="Minimal", command=lambda: apply_preset("Minimal"), 
                  width=12).grid(row=0, column=0, padx=5, pady=2)
        ttk.Button(btn_frame, text="Standard", command=lambda: apply_preset("Standard"), 
                  width=12).grid(row=0, column=1, padx=5, pady=2)
        ttk.Button(btn_frame, text="Full", command=lambda: apply_preset("Full"), 
                  width=12).grid(row=0, column=2, padx=5, pady=2)
        ttk.Button(btn_frame, text="Download", command=lambda: apply_preset("Download"), 
                  width=12).grid(row=0, column=3, padx=5, pady=2)
        
        # Bottom buttons - pack FIRST so they appear at bottom
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)
        
        # Create scrollable frame with proper container
        scroll_container = ttk.Frame(main_frame)
        scroll_container.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(scroll_container, height=400, width=500)
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Enable mouse wheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # Create checkboxes organized by category
        categories = {
            "Essential Info": ['status', 'group', 'title', 'uploader', 'duration', 'upload_date'],
            "Metrics": ['views', 'likes', 'comments', 'subscribers'],
            "Technical": ['video_id', 'channel_id', 'url', 'resolution', 'fps', 'format', 'filesize', 'quality'],
            "Content": ['description', 'category', 'tags', 'tags_list', 'language'],
            "Media": ['thumbnail', 'subtitles', 'chapters', 'chapters_list', 'aspect_ratio'],
            "Metadata": ['duration_string', 'timestamp', 'availability', 'location', 'live_status', 'age_limit', 'verified'],
            "Download": ['size', 'progress', 'speed']
        }
        
        for category_name, column_list in categories.items():
            # Category header with toggle checkbox
            category_frame = ttk.LabelFrame(scrollable_frame, text="", padding="10")
            category_frame.pack(fill=tk.X, pady=(0, 10))
            
            # Create header with category toggle checkbox
            header_frame = ttk.Frame(category_frame)
            header_frame.pack(fill=tk.X, pady=(0, 5))
            
            category_var = tk.BooleanVar(value=True)
            
            def toggle_category(cat_list=column_list, cat_var=category_var):
                """Toggle all columns in this category"""
                state = cat_var.get()
                for col in cat_list:
                    if col in self.column_vars:
                        self.column_vars[col].set(state)
            
            category_cb = ttk.Checkbutton(header_frame, text=f"✓ {category_name}", 
                                         variable=category_var, 
                                         command=toggle_category)
            category_cb.pack(side=tk.LEFT, anchor=tk.W)
            
            ttk.Separator(category_frame, orient='horizontal').pack(fill=tk.X, pady=(0, 5))
            
            # Individual column checkboxes
            for col in column_list:
                if col in column_info:
                    col_name, default = column_info[col]
                    
                    # Check if column is currently visible
                    try:
                        current_width = self.video_tree.column(col, 'width')
                        is_visible = current_width > 0
                    except (tk.TclError, KeyError):
                        is_visible = bool(default)
                    
                    var = tk.BooleanVar(value=is_visible)
                    self.column_vars[col] = var
                    
                    cb = ttk.Checkbutton(category_frame, text=f"   {col_name}", variable=var)
                    cb.pack(anchor=tk.W, pady=2)
        
        # Pack canvas and scrollbar within scroll_container
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        def apply_visibility():
            """Apply column visibility settings"""
            # Unbind mousewheel when closing
            canvas.unbind_all("<MouseWheel>")
            
            # Default column widths
            default_widths = {
                'status': 80, 'group': 100, 'title': 300, 'description': 200, 'uploader': 150, 'video_id': 120,
                'channel_id': 120, 'url': 150, 'thumbnail': 150, 'duration': 70, 'duration_string': 80,
                'upload_date': 90, 'timestamp': 90, 'views': 80, 'likes': 70, 'comments': 70,
                'subscribers': 90, 'subtitles': 80, 'resolution': 80, 'fps': 50, 'format': 80,
                'category': 100, 'availability': 90, 'location': 100, 'tags': 150, 'tags_list': 150,
                'chapters': 80, 'chapters_list': 150, 'live_status': 80, 'age_limit': 70, 'verified': 70,
                'aspect_ratio': 80, 'language': 70, 'filesize': 90, 'quality': 80, 'size': 80,
                'progress': 80, 'speed': 70
            }
            
            for col, var in self.column_vars.items():
                if var.get():
                    # Show column with default width
                    width = default_widths.get(col, 100)
                    self.video_tree.column(col, width=width, minwidth=50)
                else:
                    # Hide column by setting width to 0
                    self.video_tree.column(col, width=0, minwidth=0)
            
            self.log_callback("✅ Column visibility updated")
            column_window.destroy()
        
        def close_window():
            canvas.unbind_all("<MouseWheel>")
            column_window.destroy()
        
        ttk.Button(button_frame, text="Apply", command=apply_visibility, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Close", command=close_window, width=15).pack(side=tk.RIGHT, padx=5)
        
        # Handle window close button
        column_window.protocol("WM_DELETE_WINDOW", close_window)
    
    def show_advanced_filters(self):
        """Show advanced filtering dialog with multiple filter options"""
        filter_window = tk.Toplevel(self.window)
        filter_window.title("🔬 Advanced Filters")
        filter_window.geometry("500x650")
        filter_window.resizable(False, False)
        
        main_frame = ttk.Frame(filter_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main_frame, text="Advanced Filters", font=('Arial', 14, 'bold')).pack(pady=(0, 10))
        
        # Create notebook for organized filters
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Tab 1: Duration & Metrics
        metrics_frame = ttk.Frame(notebook, padding="10")
        notebook.add(metrics_frame, text="Duration & Metrics")
        
        # Duration filter
        duration_frame = ttk.LabelFrame(metrics_frame, text="Duration", padding="10")
        duration_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(duration_frame, text="Minimum duration (seconds):").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_duration_var = tk.StringVar(value="")
        ttk.Entry(duration_frame, textvariable=min_duration_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(duration_frame, text="Maximum duration (seconds):").grid(row=1, column=0, sticky=tk.W, pady=2)
        max_duration_var = tk.StringVar(value="")
        ttk.Entry(duration_frame, textvariable=max_duration_var, width=15).grid(row=1, column=1, padx=5, pady=2)
        
        # View count filter
        views_frame = ttk.LabelFrame(metrics_frame, text="View Count", padding="10")
        views_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(views_frame, text="Minimum views:").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_views_var = tk.StringVar(value="")
        ttk.Entry(views_frame, textvariable=min_views_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(views_frame, text="Maximum views:").grid(row=1, column=0, sticky=tk.W, pady=2)
        max_views_var = tk.StringVar(value="")
        ttk.Entry(views_frame, textvariable=max_views_var, width=15).grid(row=1, column=1, padx=5, pady=2)
        
        # Like count filter
        likes_frame = ttk.LabelFrame(metrics_frame, text="Like Count", padding="10")
        likes_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(likes_frame, text="Minimum likes:").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_likes_var = tk.StringVar(value="")
        ttk.Entry(likes_frame, textvariable=min_likes_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(likes_frame, text="Maximum likes:").grid(row=1, column=0, sticky=tk.W, pady=2)
        max_likes_var = tk.StringVar(value="")
        ttk.Entry(likes_frame, textvariable=max_likes_var, width=15).grid(row=1, column=1, padx=5, pady=2)
        
        # Tab 2: Text Search
        text_frame = ttk.Frame(notebook, padding="10")
        notebook.add(text_frame, text="Text Search")
        
        # Title search
        title_frame = ttk.LabelFrame(text_frame, text="Title Filter", padding="10")
        title_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(title_frame, text="Contains text:").grid(row=0, column=0, sticky=tk.W, pady=2)
        title_contains_var = tk.StringVar(value="")
        ttk.Entry(title_frame, textvariable=title_contains_var, width=30).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(title_frame, text="Excludes text:").grid(row=1, column=0, sticky=tk.W, pady=2)
        title_excludes_var = tk.StringVar(value="")
        ttk.Entry(title_frame, textvariable=title_excludes_var, width=30).grid(row=1, column=1, padx=5, pady=2)
        
        title_case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(title_frame, text="Case sensitive", variable=title_case_var).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # Description search
        desc_frame = ttk.LabelFrame(text_frame, text="Description Filter", padding="10")
        desc_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(desc_frame, text="Contains text:").grid(row=0, column=0, sticky=tk.W, pady=2)
        desc_contains_var = tk.StringVar(value="")
        ttk.Entry(desc_frame, textvariable=desc_contains_var, width=30).grid(row=0, column=1, padx=5, pady=2)
        
        desc_case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(desc_frame, text="Case sensitive", variable=desc_case_var).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # Channel filter
        channel_frame = ttk.LabelFrame(text_frame, text="Channel Filter", padding="10")
        channel_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(channel_frame, text="Channel name:").grid(row=0, column=0, sticky=tk.W, pady=2)
        channel_var = tk.StringVar(value="")
        ttk.Entry(channel_frame, textvariable=channel_var, width=30).grid(row=0, column=1, padx=5, pady=2)
        
        # Tab 3: Quality & Format
        quality_frame = ttk.Frame(notebook, padding="10")
        notebook.add(quality_frame, text="Quality & Format")
        
        # Resolution filter
        resolution_frame = ttk.LabelFrame(quality_frame, text="Resolution", padding="10")
        resolution_frame.pack(fill=tk.X, pady=(0, 10))
        
        resolutions = ["Any", "4320p (8K)", "2160p (4K)", "1440p (2K)", "1080p (FHD)", "720p (HD)", "480p (SD)", "360p", "240p", "144p"]
        ttk.Label(resolution_frame, text="Minimum resolution:").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_res_var = tk.StringVar(value="Any")
        ttk.Combobox(resolution_frame, textvariable=min_res_var, values=resolutions, state='readonly', width=15).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(resolution_frame, text="Maximum resolution:").grid(row=1, column=0, sticky=tk.W, pady=2)
        max_res_var = tk.StringVar(value="Any")
        ttk.Combobox(resolution_frame, textvariable=max_res_var, values=resolutions, state='readonly', width=15).grid(row=1, column=1, padx=5, pady=2)
        
        # File size filter
        filesize_frame = ttk.LabelFrame(quality_frame, text="File Size (MB)", padding="10")
        filesize_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(filesize_frame, text="Minimum size (MB):").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_size_var = tk.StringVar(value="")
        ttk.Entry(filesize_frame, textvariable=min_size_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(filesize_frame, text="Maximum size (MB):").grid(row=1, column=0, sticky=tk.W, pady=2)
        max_size_var = tk.StringVar(value="")
        ttk.Entry(filesize_frame, textvariable=max_size_var, width=15).grid(row=1, column=1, padx=5, pady=2)
        
        # FPS filter
        fps_frame = ttk.LabelFrame(quality_frame, text="Frame Rate (FPS)", padding="10")
        fps_frame.pack(fill=tk.X, pady=(0, 10))
        
        fps_options = ["Any", "24", "25", "30", "50", "60", "120", "144"]
        ttk.Label(fps_frame, text="Minimum FPS:").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_fps_var = tk.StringVar(value="Any")
        ttk.Combobox(fps_frame, textvariable=min_fps_var, values=fps_options, state='readonly', width=15).grid(row=0, column=1, padx=5, pady=2)
        
        # Tab 4: Additional Filters
        additional_frame = ttk.Frame(notebook, padding="10")
        notebook.add(additional_frame, text="More Filters")
        
        # Comment count filter
        comments_frame = ttk.LabelFrame(additional_frame, text="Comment Count", padding="10")
        comments_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(comments_frame, text="Minimum comments:").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_comments_var = tk.StringVar(value="")
        ttk.Entry(comments_frame, textvariable=min_comments_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(comments_frame, text="Maximum comments:").grid(row=1, column=0, sticky=tk.W, pady=2)
        max_comments_var = tk.StringVar(value="")
        ttk.Entry(comments_frame, textvariable=max_comments_var, width=15).grid(row=1, column=1, padx=5, pady=2)
        
        # Age restriction filter
        age_frame = ttk.LabelFrame(additional_frame, text="Age Restriction", padding="10")
        age_frame.pack(fill=tk.X, pady=(0, 10))
        
        age_restriction_var = tk.StringVar(value="All")
        age_options = ["All", "Only Age-Restricted", "Only Non-Restricted"]
        ttk.Label(age_frame, text="Show:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(age_frame, textvariable=age_restriction_var, values=age_options, state='readonly', width=20).grid(row=0, column=1, padx=5, pady=2)
        
        # Live status filter
        live_frame = ttk.LabelFrame(additional_frame, text="Video Status", padding="10")
        live_frame.pack(fill=tk.X, pady=(0, 10))
        
        live_status_var = tk.StringVar(value="All")
        live_options = ["All", "Only Live/Upcoming", "Only Regular Videos", "Only Premieres"]
        ttk.Label(live_frame, text="Show:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(live_frame, textvariable=live_status_var, values=live_options, state='readonly', width=20).grid(row=0, column=1, padx=5, pady=2)
        
        # Availability filter
        availability_frame = ttk.LabelFrame(additional_frame, text="Availability", padding="10")
        availability_frame.pack(fill=tk.X, pady=(0, 10))
        
        availability_var = tk.StringVar(value="All")
        availability_options = ["All", "Public Only", "Unlisted Only", "Private Only"]
        ttk.Label(availability_frame, text="Show:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(availability_frame, textvariable=availability_var, values=availability_options, state='readonly', width=20).grid(row=0, column=1, padx=5, pady=2)
        
        # Language filter
        language_frame = ttk.LabelFrame(additional_frame, text="Language", padding="10")
        language_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(language_frame, text="Language code (e.g., en, es):").grid(row=0, column=0, sticky=tk.W, pady=2)
        language_var = tk.StringVar(value="")
        ttk.Entry(language_frame, textvariable=language_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        
        # Tab 5: Engagement Metrics
        engagement_frame = ttk.Frame(notebook, padding="10")
        notebook.add(engagement_frame, text="Engagement")
        
        # Like ratio filter
        ratio_frame = ttk.LabelFrame(engagement_frame, text="Like Ratio (%)", padding="10")
        ratio_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(ratio_frame, text="Minimum like ratio (%):").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_ratio_var = tk.StringVar(value="")
        ttk.Entry(ratio_frame, textvariable=min_ratio_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        ttk.Label(ratio_frame, text="(e.g., 90 = 90% likes)").grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=2)
        
        # Views per day filter
        vpd_frame = ttk.LabelFrame(engagement_frame, text="Views Per Day", padding="10")
        vpd_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(vpd_frame, text="Minimum views/day:").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_vpd_var = tk.StringVar(value="")
        ttk.Entry(vpd_frame, textvariable=min_vpd_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(vpd_frame, text="Maximum views/day:").grid(row=1, column=0, sticky=tk.W, pady=2)
        max_vpd_var = tk.StringVar(value="")
        ttk.Entry(vpd_frame, textvariable=max_vpd_var, width=15).grid(row=1, column=1, padx=5, pady=2)
        
        # Playlist index filter
        playlist_frame = ttk.LabelFrame(engagement_frame, text="Playlist Position", padding="10")
        playlist_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(playlist_frame, text="From position:").grid(row=0, column=0, sticky=tk.W, pady=2)
        min_playlist_var = tk.StringVar(value="")
        ttk.Entry(playlist_frame, textvariable=min_playlist_var, width=15).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(playlist_frame, text="To position:").grid(row=1, column=0, sticky=tk.W, pady=2)
        max_playlist_var = tk.StringVar(value="")
        ttk.Entry(playlist_frame, textvariable=max_playlist_var, width=15).grid(row=1, column=1, padx=5, pady=2)
        
        # Has subtitles filter
        subs_frame = ttk.LabelFrame(engagement_frame, text="Content Features", padding="10")
        subs_frame.pack(fill=tk.X, pady=(0, 10))
        
        has_subs_var = tk.StringVar(value="All")
        subs_options = ["All", "With Subtitles Only", "Without Subtitles"]
        ttk.Label(subs_frame, text="Subtitles:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(subs_frame, textvariable=has_subs_var, values=subs_options, state='readonly', width=20).grid(row=0, column=1, padx=5, pady=2)
        
        has_chapters_var = tk.StringVar(value="All")
        chapters_options = ["All", "With Chapters Only", "Without Chapters"]
        ttk.Label(subs_frame, text="Chapters:").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(subs_frame, textvariable=has_chapters_var, values=chapters_options, state='readonly', width=20).grid(row=1, column=1, padx=5, pady=2)
        
        # Bottom button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        def apply_filters():
            """Apply all selected filters to the video list"""
            filtered_count = 0
            total_count = 0
            
            # Column index mapping (matches Treeview column order)
            # 0:status, 1:group, 2:title, 3:description, 4:uploader, 5:video_id, 6:channel_id, 7:url, 8:thumbnail,
            # 9:duration, 10:duration_string, 11:upload_date, 12:timestamp, 13:views, 14:likes, 15:comments,
            # 16:subscribers, 17:subtitles, 18:resolution, 19:fps, 20:format, 21:category, 22:availability,
            # 23:location, 24:tags, 25:tags_list, 26:chapters, 27:chapters_list, 28:live_status, 29:age_limit,
            # 30:verified, 31:aspect_ratio, 32:language, 33:filesize, 34:quality, 35:size, 36:progress, 37:speed
            COL = {
                'status': 0, 'group': 1, 'title': 2, 'description': 3, 'uploader': 4,
                'video_id': 5, 'channel_id': 6, 'url': 7, 'thumbnail': 8,
                'duration': 9, 'duration_string': 10, 'upload_date': 11, 'timestamp': 12,
                'views': 13, 'likes': 14, 'comments': 15, 'subscribers': 16, 'subtitles': 17,
                'resolution': 18, 'fps': 19, 'format': 20, 'category': 21, 'availability': 22,
                'location': 23, 'tags': 24, 'tags_list': 25, 'chapters': 26, 'chapters_list': 27,
                'live_status': 28, 'age_limit': 29, 'verified': 30, 'aspect_ratio': 31,
                'language': 32, 'filesize': 33, 'quality': 34, 'size': 35, 'progress': 36, 'speed': 37
            }
            
            def get_val(values, col_name):
                """Safely get value from tuple by column name"""
                idx = COL.get(col_name, -1)
                return values[idx] if idx >= 0 and len(values) > idx else ""
            
            def parse_number(s):
                """Parse number from string like '1.2M', '500K', or plain numbers"""
                if not s or s == '?':
                    return 0
                s = str(s).strip()
                try:
                    if 'M' in s.upper():
                        return float(s.upper().replace('M', '').strip()) * 1000000
                    elif 'K' in s.upper():
                        return float(s.upper().replace('K', '').strip()) * 1000
                    else:
                        # Remove non-numeric except decimal
                        clean = ''.join(c for c in s if c.isdigit() or c == '.')
                        return float(clean) if clean else 0
                except (ValueError, AttributeError):
                    return 0
            
            def parse_duration(s):
                """Parse duration from mm:ss or seconds format"""
                if not s or s == '?':
                    return 0
                s = str(s).strip()
                try:
                    if ':' in s:
                        parts = s.split(':')
                        if len(parts) == 2:
                            return int(parts[0]) * 60 + int(parts[1])
                        elif len(parts) == 3:
                            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    return int(s)
                except (ValueError, AttributeError):
                    return 0
            
            for item_id in self.video_tree.get_children():
                total_count += 1
                values = self.video_tree.item(item_id, 'values')
                if not values:
                    continue
                
                show_item = True
                
                # Duration filter (using COL mapping and helper functions)
                if min_duration_var.get():
                    try:
                        min_dur = int(min_duration_var.get())
                        duration_val = parse_duration(get_val(values, 'duration'))
                        if duration_val > 0 and duration_val < min_dur:
                            show_item = False
                    except ValueError:
                        pass
                
                if max_duration_var.get() and show_item:
                    try:
                        max_dur = int(max_duration_var.get())
                        duration_val = parse_duration(get_val(values, 'duration'))
                        if duration_val > 0 and duration_val > max_dur:
                            show_item = False
                    except ValueError:
                        pass
                
                # View count filter
                if min_views_var.get() and show_item:
                    try:
                        min_views = int(min_views_var.get())
                        views_val = parse_number(get_val(values, 'views'))
                        if views_val > 0 and views_val < min_views:
                            show_item = False
                    except ValueError:
                        pass
                
                if max_views_var.get() and show_item:
                    try:
                        max_views = int(max_views_var.get())
                        views_val = parse_number(get_val(values, 'views'))
                        if views_val > 0 and views_val > max_views:
                            show_item = False
                    except ValueError:
                        pass
                
                # Like count filter
                if min_likes_var.get() and show_item:
                    try:
                        min_likes = int(min_likes_var.get())
                        likes_val = parse_number(get_val(values, 'likes'))
                        if likes_val > 0 and likes_val < min_likes:
                            show_item = False
                    except ValueError:
                        pass
                
                if max_likes_var.get() and show_item:
                    try:
                        max_likes = int(max_likes_var.get())
                        likes_val = parse_number(get_val(values, 'likes'))
                        if likes_val > 0 and likes_val > max_likes:
                            show_item = False
                    except ValueError:
                        pass
                
                # Title filter
                if title_contains_var.get() and show_item:
                    title = get_val(values, 'title')
                    search_text = title_contains_var.get()
                    if not title_case_var.get():
                        title = str(title).lower()
                        search_text = search_text.lower()
                    if search_text not in title:
                        show_item = False
                
                if title_excludes_var.get() and show_item:
                    title = get_val(values, 'title')
                    search_text = title_excludes_var.get()
                    if not title_case_var.get():
                        title = str(title).lower()
                        search_text = search_text.lower()
                    if search_text in title:
                        show_item = False
                
                # Description filter
                if desc_contains_var.get() and show_item:
                    desc = get_val(values, 'description')
                    search_text = desc_contains_var.get()
                    if not desc_case_var.get():
                        desc = str(desc).lower()
                        search_text = search_text.lower()
                    if search_text not in desc:
                        show_item = False
                
                # Channel filter
                if channel_var.get() and show_item:
                    channel = get_val(values, 'uploader')
                    search_text = channel_var.get()
                    if search_text.lower() not in str(channel).lower():
                        show_item = False
                
                # Resolution filter
                if min_res_var.get() != "Any" and show_item:
                    resolution = get_val(values, 'resolution')
                    min_res = min_res_var.get().split('p')[0].split(' ')[0]
                    if resolution and min_res.isdigit():
                        current_res = ''.join(filter(str.isdigit, str(resolution)))
                        if current_res and int(current_res) < int(min_res):
                            show_item = False
                
                if max_res_var.get() != "Any" and show_item:
                    resolution = get_val(values, 'resolution')
                    max_res = max_res_var.get().split('p')[0].split(' ')[0]
                    if resolution and max_res.isdigit():
                        current_res = ''.join(filter(str.isdigit, str(resolution)))
                        if current_res and int(current_res) > int(max_res):
                            show_item = False
                
                # File size filter (convert MB to bytes)
                if min_size_var.get() and show_item:
                    try:
                        min_size_mb = float(min_size_var.get())
                        min_size_bytes = min_size_mb * 1024 * 1024
                        filesize_val = parse_number(get_val(values, 'filesize'))
                        if filesize_val > 0 and filesize_val < min_size_bytes:
                            show_item = False
                    except ValueError:
                        pass
                
                if max_size_var.get() and show_item:
                    try:
                        max_size_mb = float(max_size_var.get())
                        max_size_bytes = max_size_mb * 1024 * 1024
                        filesize_val = parse_number(get_val(values, 'filesize'))
                        if filesize_val > 0 and filesize_val > max_size_bytes:
                            show_item = False
                    except ValueError:
                        pass
                
                # FPS filter
                if min_fps_var.get() != "Any" and show_item:
                    fps_str = get_val(values, 'fps')
                    min_fps = min_fps_var.get()
                    if fps_str and str(fps_str).replace('.', '').isdigit() and min_fps.isdigit():
                        if float(fps_str) < float(min_fps):
                            show_item = False
                
                # Comment count filter
                if min_comments_var.get() and show_item:
                    try:
                        min_comments = int(min_comments_var.get())
                        comments_val = parse_number(get_val(values, 'comments'))
                        if comments_val > 0 and comments_val < min_comments:
                            show_item = False
                    except ValueError:
                        pass
                
                if max_comments_var.get() and show_item:
                    try:
                        max_comments = int(max_comments_var.get())
                        comments_val = parse_number(get_val(values, 'comments'))
                        if comments_val > 0 and comments_val > max_comments:
                            show_item = False
                    except ValueError:
                        pass
                
                # Age restriction filter
                if age_restriction_var.get() != "All" and show_item:
                    age_limit_str = str(get_val(values, 'age_limit'))
                    if age_restriction_var.get() == "Only Age-Restricted":
                        if not age_limit_str or age_limit_str == "0":
                            show_item = False
                    elif age_restriction_var.get() == "Only Non-Restricted":
                        if age_limit_str and age_limit_str != "0":
                            show_item = False
                
                # Live status filter
                if live_status_var.get() != "All" and show_item:
                    is_live_str = str(get_val(values, 'live_status'))
                    if live_status_var.get() == "Only Live/Upcoming":
                        if is_live_str.lower() not in ["true", "yes", "1", "is_live", "is_upcoming"]:
                            show_item = False
                    elif live_status_var.get() == "Only Regular Videos":
                        if is_live_str.lower() in ["true", "yes", "1", "is_live", "is_upcoming"]:
                            show_item = False
                
                # Availability filter
                if availability_var.get() != "All" and show_item:
                    availability_str = str(get_val(values, 'availability'))
                    if availability_var.get() == "Public Only":
                        if availability_str.lower() != "public":
                            show_item = False
                    elif availability_var.get() == "Unlisted Only":
                        if availability_str.lower() != "unlisted":
                            show_item = False
                    elif availability_var.get() == "Private Only":
                        if availability_str.lower() != "private":
                            show_item = False
                
                # Language filter
                if language_var.get() and show_item:
                    language_str = str(get_val(values, 'language'))
                    if language_var.get().lower() not in language_str.lower():
                        show_item = False
                
                # Like ratio filter (note: dislikes are not available in yt-dlp anymore)
                if min_ratio_var.get() and show_item:
                    try:
                        min_ratio = float(min_ratio_var.get())
                        likes_val = parse_number(get_val(values, 'likes'))
                        views_val = parse_number(get_val(values, 'views'))
                        # Since dislikes are not available, calculate likes-to-views ratio instead
                        if likes_val > 0 and views_val > 0:
                            ratio = (likes_val / views_val) * 100
                            if ratio < min_ratio:
                                show_item = False
                    except ValueError:
                        pass
                
                # Views per day filter
                if (min_vpd_var.get() or max_vpd_var.get()) and show_item:
                    try:
                        views_val = parse_number(get_val(values, 'views'))
                        upload_date_str = str(get_val(values, 'upload_date'))
                        if views_val > 0 and upload_date_str:
                            from datetime import datetime
                            # Parse upload date (format: YYYYMMDD)
                            upload_date = datetime.strptime(upload_date_str[:8], "%Y%m%d")
                            days_since = (datetime.now() - upload_date).days
                            if days_since > 0:
                                vpd = views_val / days_since
                                if min_vpd_var.get():
                                    min_vpd = float(min_vpd_var.get())
                                    if vpd < min_vpd:
                                        show_item = False
                                if max_vpd_var.get() and show_item:
                                    max_vpd = float(max_vpd_var.get())
                                    if vpd > max_vpd:
                                        show_item = False
                    except (ValueError, AttributeError):
                        pass
                
                # Playlist position filter (uses status column as index is not stored in tree)
                # Note: Playlist index is typically stored at extraction time but not displayed
                # This filter may need adjustment based on actual data structure
                if min_playlist_var.get() and show_item:
                    try:
                        min_pos = int(min_playlist_var.get())
                        # Try to get playlist index from widget data instead of tree values
                        widget_data = next((w for w in self.video_item_widgets if w['item_id'] == item_id), None)
                        if widget_data:
                            playlist_index = widget_data.get('entry', {}).get('playlist_index', 0)
                            if playlist_index and int(playlist_index) < min_pos:
                                show_item = False
                    except (ValueError, TypeError):
                        pass
                
                if max_playlist_var.get() and show_item:
                    try:
                        max_pos = int(max_playlist_var.get())
                        widget_data = next((w for w in self.video_item_widgets if w['item_id'] == item_id), None)
                        if widget_data:
                            playlist_index = widget_data.get('entry', {}).get('playlist_index', 0)
                            if playlist_index and int(playlist_index) > max_pos:
                                show_item = False
                    except (ValueError, TypeError):
                        pass
                
                # Subtitles filter
                if has_subs_var.get() != "All" and show_item:
                    subtitles_str = str(get_val(values, 'subtitles'))
                    has_subs = subtitles_str and subtitles_str.lower() not in ["", "none", "false", "0"]
                    if has_subs_var.get() == "With Subtitles Only":
                        if not has_subs:
                            show_item = False
                    elif has_subs_var.get() == "Without Subtitles":
                        if has_subs:
                            show_item = False
                
                # Chapters filter
                if has_chapters_var.get() != "All" and show_item:
                    chapters_str = str(get_val(values, 'chapters'))
                    has_chapters = chapters_str and chapters_str.lower() not in ["", "none", "false", "0", "[]"]
                    if has_chapters_var.get() == "With Chapters Only":
                        if not has_chapters:
                            show_item = False
                    elif has_chapters_var.get() == "Without Chapters":
                        if has_chapters:
                            show_item = False
                
                # Apply filter (detach or reattach item)
                if show_item:
                    filtered_count += 1
                else:
                    self.video_tree.detach(item_id)
                    continue
            
            # Show result message
            self.log_callback(f"✅ Filters applied: Showing {filtered_count} of {total_count} videos")
            filter_window.destroy()
        
        def reset_filters():
            """Reset all filters and show all videos"""
            for item_id in self.video_tree.get_children(''):
                self.video_tree.reattach(item_id, '', tk.END)
            
            # Also get detached items and reattach them
            try:
                all_items = self.video_tree.get_children()
                # Get stored items from widget data
                for widget_data in self.video_item_widgets:
                    item_id = widget_data.get('tree_id')
                    if item_id and item_id not in all_items:
                        try:
                            self.video_tree.reattach(item_id, '', tk.END)
                        except:
                            pass
            except:
                pass
            
            self.log_callback("✅ All filters cleared")
            filter_window.destroy()
        
        # Buttons
        ttk.Button(button_frame, text="Apply Filters", command=apply_filters, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Reset All", command=reset_filters, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Close", command=filter_window.destroy, width=15).pack(side=tk.RIGHT, padx=5)
    
    def update_selected_count(self):
        """Update the count of selected videos"""
        selected_items = self.video_tree.selection()
        selected_count = len(selected_items)
        
        # Calculate total duration of selected videos
        selected_duration = 0
        for item_id in selected_items:
            # Get the widget data for this item
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    selected_duration += widget_data['entry'].get('duration', 0) or 0
                    break
        
        time_str = str(timedelta(seconds=int(selected_duration)))
        self.selected_count_var.set(f"✓ Selected: {selected_count} videos ({time_str})")
        
        # Only update download button if it exists (it's created later in the UI)
        if hasattr(self, 'download_btn'):
            self.download_btn.config(text=f"▶ Download Selected ({selected_count} videos)")
        
        self.update_stats()
    
    def update_stats(self):
        """Update statistics display"""
        # Safety check - stats_text widget must exist
        if not hasattr(self, 'stats_text'):
            return
            
        selected_items = self.video_tree.selection()
        
        if not selected_items:
            stats_text = "No videos selected"
        else:
            count = len(selected_items)
            
            # Calculate durations for selected items
            total_dur = 0
            for item_id in selected_items:
                for widget_data in self.video_item_widgets:
                    if widget_data['item_id'] == item_id:
                        total_dur += widget_data['entry'].get('duration', 0) or 0
                        break
            
            avg_dur = total_dur / count if count > 0 else 0
            
            # Build stats text with safety checks for UI elements
            stats_text = f"""Selected: {count} videos
Total Duration: {str(timedelta(seconds=int(total_dur)))}
Average Length: {str(timedelta(seconds=int(avg_dur)))}"""
            
            # Only add download settings if UI is fully initialized
            if hasattr(self, 'download_type') and hasattr(self, 'quality_var') and hasattr(self, 'audio_quality_var'):
                download_type = self.download_type.get()
                quality = self.quality_var.get() if download_type == 'video' else self.audio_quality_var.get()
                stats_text += f"""

Download Type: {download_type.upper()}
Quality: {quality}

Parallel: {self.parallel_downloads.get()} simultaneous
Connections: {self.concurrent_fragments.get()} parallel fragments{' + aria2c' if self.use_aria2c.get() and self.aria2c_available else ''}"""
        
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete('1.0', tk.END)
        self.stats_text.insert('1.0', stats_text)
        self.stats_text.config(state=tk.DISABLED)
    
    def set_selected_quality(self, quality):
        """Set quality for all selected videos (Advanced mode)"""
        selected_items = self.video_tree.selection()
        
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select videos first", 
                                 parent=self.window)
            return
        
        count = 0
        for item_id in selected_items:
            self.video_tree.set(item_id, 'quality', quality)
            # Update widget data
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    widget_data['quality'] = quality
                    count += 1
                    break
        
        self.log_callback(f"✅ Set {count} videos to '{quality}'")
        messagebox.showinfo("Quality Set", f"Set {count} videos to '{quality}'", 
                          parent=self.window)
    
    def run_plugins_on_selected(self):
        """Run enabled plugins on selected playlist items"""
        if not self.has_plugins:
            return
        
        selected_items = self.video_tree.selection()
        
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select videos first", 
                                 parent=self.window)
            return
        
        # Get enabled plugins
        enabled_plugins = []
        for plugin in self.plugin_manager.get_plugins():
            if self.plugin_vars.get(plugin.id, tk.BooleanVar()).get():
                enabled_plugins.append(plugin)
        
        if not enabled_plugins:
            messagebox.showwarning("No Plugins", "Please enable at least one plugin", 
                                 parent=self.window)
            return
        
        count = len(selected_items)
        plugin_names = ', '.join([p.name for p in enabled_plugins])
        
        if not messagebox.askyesno("Run Plugins", 
                                  f"Run {len(enabled_plugins)} plugin(s) on {count} video(s)?\n\n"
                                  f"Plugins: {plugin_names}", 
                                  parent=self.window):
            return
        
        self.log_callback(f"🔌 Running {len(enabled_plugins)} plugins on {count} videos...")
        
        def run_plugins_worker():
            success_count = 0
            fail_count = 0
            
            for idx, item_id in enumerate(selected_items, 1):
                # Find entry
                entry = None
                for w in self.video_item_widgets:
                    if w['item_id'] == item_id:
                        entry = w['entry']
                        break
                
                if not entry:
                    continue
                
                title = entry.get('title', 'Unknown')
                video_id = entry.get('id') or entry.get('url')
                
                if not video_id:
                    fail_count += 1
                    continue
                
                if not video_id.startswith('http'):
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                else:
                    video_url = video_id
                
                self.window.after(0, self.progress_var.set, 
                                f"🔌 Processing {idx}/{count}: {title[:40]}")
                self.window.after(0, self.progress_bar.config, 
                                {'value': ((idx - 1) / count) * 100})
                
                # Run each enabled plugin
                for plugin in enabled_plugins:
                    try:
                        self.log_callback(f"  ▶ Running {plugin.name} on '{title[:40]}'")
                        
                        # Build context for plugin
                        context = {
                            'url': video_url,
                            'output_dir': self.path_var.get(),
                            'video_info': entry,
                            'playlist_info': self.playlist_info
                        }
                        
                        # Run plugin
                        plugin.run(context, self.log_callback)
                        success_count += 1
                        
                    except Exception as e:
                        self.log_callback(f"  ❌ Plugin {plugin.name} failed: {e}")
                        fail_count += 1
            
            self.window.after(0, self.progress_bar.config, {'value': 100})
            self.window.after(0, self.progress_var.set, 
                            f"✅ Plugins complete! {success_count} success, {fail_count} failed")
            self.window.after(0, lambda: messagebox.showinfo(
                "Plugins Complete", 
                f"Finished running plugins\n\n"
                f"✅ Success: {success_count}\n"
                f"❌ Failed: {fail_count}", 
                parent=self.window))
        
        threading.Thread(target=run_plugins_worker, daemon=True).start()
    
    def analyze_video_quality(self, idx, entry):
        """Analyze available qualities for a specific video"""
        widget_data = self.video_item_widgets[idx]
        
        if widget_data['analyzed']:
            self.log_callback(f"ℹ️ Video {idx+1} already analyzed")
            return
        
        # Update tree item status (safe - called from main thread)
        item_id = widget_data['item_id']
        self.video_tree.set(item_id, 'status', "🔄")
        self.log_callback(f"🔍 Analyzing video {idx+1}...")
        
        def analyze():
            try:
                video_id = entry.get('id') or entry.get('url')
                if not video_id:
                    return
                
                if not video_id.startswith('http'):
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                else:
                    video_url = video_id
                
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'socket_timeout': 30,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    
                    # Parse qualities
                    qualities = set()
                    if 'formats' in info:
                        for fmt in info['formats']:
                            if fmt.get('vcodec') != 'none':
                                height = fmt.get('height')
                                if height:
                                    qualities.add(f"{height}p")
                    
                    self.video_qualities[idx] = sorted(qualities, 
                                                     key=lambda x: int(x.replace('p', '')), 
                                                     reverse=True)
                    
                    # Update dropdown
                    self.window.after(0, self.update_video_qualities, idx)
                    
            except Exception as e:
                self.window.after(0, self.analysis_failed, idx, str(e))
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def update_video_qualities(self, idx):
        """Update quality dropdown with analyzed qualities"""
        widget_data = self.video_item_widgets[idx]
        qualities = self.video_qualities.get(idx, ['Best'])
        
        # Update tree item status and quality column
        self.video_tree.set(widget_data['item_id'], 'status', "✅")
        self.video_tree.set(widget_data['item_id'], 'quality', ', '.join(qualities[:3]))  # Show first 3 qualities
        widget_data['analyzed'] = True
        
        self.log_callback(f"✅ Video {idx+1}: Found {len(qualities)} qualities")
    
    def analysis_failed(self, idx, error):
        """Handle analysis failure"""
        widget_data = self.video_item_widgets[idx]
        self.video_tree.set(widget_data['item_id'], 'status', "❌")
        self.log_callback(f"❌ Video {idx+1}: Analysis failed - {error}")
    
    def analyze_all_qualities(self):
        """Analyze qualities for all selected videos"""
        selected_items = self.video_tree.selection()
        
        # Get indices of selected videos
        selected = []
        for item_id in selected_items:
            for i, widget_data in enumerate(self.video_item_widgets):
                if widget_data['item_id'] == item_id:
                    selected.append(i)
                    break
        
        if not selected:
            messagebox.showwarning("No Selection", "Please select videos to analyze", 
                                 parent=self.window)
            return
        
        if not messagebox.askyesno("Analyze All", 
                                  f"Analyze {len(selected)} videos?\n\nThis may take several minutes.",
                                  parent=self.window):
            return
        
        self.log_callback(f"🔍 Starting quality analysis for {len(selected)} videos...")
        
        for idx in selected:
            self.analyze_video_quality(idx, self.video_item_widgets[idx]['entry'])
            time.sleep(0.5)  # Rate limiting
    
    def browse_path(self):
        """Browse for download directory"""
        path = filedialog.askdirectory(initialdir=self.path_var.get(), parent=self.window)
        if path:
            self.path_var.set(path)
    
    def show_template_help(self):
        """Show filename template help dialog"""
        help_window = tk.Toplevel(self.window)
        help_window.title("📝 Filename Template Help")
        help_window.geometry("500x400")
        help_window.resizable(False, False)
        
        help_frame = ttk.Frame(help_window, padding="15")
        help_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(help_frame, text="Available Template Variables:", 
                 font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(0, 10))
        
        help_text = """
{title}          - Video title
{uploader}       - Channel/uploader name
{upload_date}    - Upload date (YYYYMMDD)
{id}             - Video ID
{resolution}     - Resolution (1080p, 720p, etc.)
{ext}            - File extension (mp4, webm, etc.)
{playlist}       - Playlist title
{playlist_index} - Video number in playlist
{duration}       - Video duration in seconds

Examples:
  {title}
    ➜ "My Video Title.mp4"
    
  {uploader} - {title}
    ➜ "Channel Name - My Video Title.mp4"
    
  [{upload_date}] {title}
    ➜ "[20250114] My Video Title.mp4"
    
  {playlist_index}. {title} [{resolution}]
    ➜ "05. My Video Title [1080p].mp4"
    
  [{uploader}] {title} ({id})
    ➜ "[Channel] My Video Title (dQw4w9WgXcQ).mp4"

Note: Invalid characters (/:*?"<>|) will be removed automatically.
"""
        
        text_widget = scrolledtext.ScrolledText(help_frame, wrap=tk.WORD, 
                                                width=60, height=18, font=('Consolas', 9))
        text_widget.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        text_widget.insert('1.0', help_text)
        text_widget.config(state=tk.DISABLED)
        
        ttk.Button(help_frame, text="Close", command=help_window.destroy).pack()
    
    def show_video_info(self, idx, entry):
        """Show detailed info for a specific video"""
        from video_window import VideoWindow
        
        video_id = entry.get('id') or entry.get('url')
        if not video_id:
            messagebox.showerror("Error", "Could not get video URL", parent=self.window)
            return
        
        if not video_id.startswith('http'):
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            video_url = video_id
        
        video_window = tk.Toplevel(self.window)
        video_window.title(f"Video Info: {entry.get('title', 'Unknown')[:50]}")
        video_window.geometry("700x600")
        
        VideoWindow(video_window, video_url, entry.get('title', 'Unknown'), self.log_callback)
    
    def export_list(self):
        """Export video list to file"""
        filename = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("Text files", "*.txt"), ("All files", "*.*")]
        )
        
        if not filename:
            return
        
        selected = [
            {
                'title': w['entry'].get('title'),
                'id': w['entry'].get('id'),
                'duration': w['entry'].get('duration'),
                'url': f"https://www.youtube.com/watch?v={w['entry'].get('id')}"
            }
            for w in self.video_item_widgets if w.get('selected', False)
        ]
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(selected, f, indent=2, ensure_ascii=False)
        
        self.log_callback(f"💾 Exported {len(selected)} videos to {filename}")
        messagebox.showinfo("Export Complete", f"Exported {len(selected)} videos", 
                          parent=self.window)
    
    def start_download(self):
        """Start downloading selected videos"""
        selected_items = self.video_tree.selection()
        
        # Build list of selected videos with their widget data
        selected_videos = []
        for item_id in selected_items:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    # Get index from video_item_widgets
                    idx = self.video_item_widgets.index(widget_data)
                    selected_videos.append((idx, widget_data))
                    break
        
        if not selected_videos:
            messagebox.showwarning("No Selection", "Please select at least one video", 
                                 parent=self.window)
            return
        
        download_path = Path(self.path_var.get())
        if not download_path.exists():
            messagebox.showerror("Invalid Path", "Download path does not exist!", 
                               parent=self.window)
            return
        
        count = len(selected_videos)
        msg = f"Download {count} videos?\n\n"
        msg += f"Mode: {'Advanced' if self.is_advanced_mode else 'Simple'}\n"
        msg += f"Type: {self.download_type.get().upper()}\n"
        msg += f"Parallel: {self.parallel_downloads.get()}\n"
        msg += f"Connections: {self.concurrent_fragments.get()} parallel fragments"
        if self.use_aria2c.get() and self.aria2c_available:
            msg += f" + aria2c ({self.aria2c_connections.get()} conn)"
        msg += f"\nPath: {download_path}"
        
        if not messagebox.askyesno("Confirm Download", msg, parent=self.window):
            return
        
        self.download_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.cancel_btn.config(state="normal")
        
        with self.download_lock:
            self.is_downloading = True
            self.cancel_flag = False
            self.is_paused = False
            self.failed_downloads = []
            self.completed_downloads = []
        
        # Ensure pause event is set (not paused) at start
        self.pause_event.set()
        self.pause_btn.config(text="⏸ Pause")
        
        threading.Thread(target=self.download_videos, 
                        args=(selected_videos, download_path), 
                        daemon=True).start()
    
    def download_videos(self, selected_videos, download_path):
        """Download videos with parallel support"""
        total = len(selected_videos)
        
        for current, (idx, widget_data) in enumerate(selected_videos, 1):
            # Check for cancel
            with self.download_lock:
                should_cancel = self.cancel_flag
            if should_cancel:
                try:
                    if self.window.winfo_exists():
                        self.window.after(0, self.progress_var.set, "❌ Download cancelled")
                except (tk.TclError, RuntimeError):
                    pass
                break
            
            # Wait if paused (blocks here until resumed)
            self.pause_event.wait()
            
            # Check cancel again after potential pause
            with self.download_lock:
                should_cancel = self.cancel_flag
            if should_cancel:
                try:
                    if self.window.winfo_exists():
                        self.window.after(0, self.progress_var.set, "❌ Download cancelled")
                except (tk.TclError, RuntimeError):
                    pass
                break
            
            entry = widget_data['entry']
            title = entry.get('title', 'Unknown')
            
            # Guard: skip UI updates if window was closed
            try:
                if not self.window.winfo_exists():
                    break
            except (tk.TclError, RuntimeError):
                break
            
            self.window.after(0, self.progress_var.set, 
                            f"📥 Downloading {current}/{total}: {title[:40]}")
            self.window.after(0, self.current_video_var.set, f"📥 {title[:80]}")
            self.window.after(0, self.progress_bar.config, 
                            {'value': 0})  # Reset to 0 for new video
            # Reset speed/ETA for new video
            self.window.after(0, self.speed_var.set, "Speed: ---")
            self.window.after(0, self.eta_var.set, "ETA: ---")
            # Update tree item status
            self.window.after(0, self.video_tree.set, widget_data['item_id'], 'status', '⬇️')
            
            self.log_callback(f"📥 [{current}/{total}] {title[:60]}")
            
            video_id = entry.get('id') or entry.get('url')
            if not video_id:
                self.log_callback(f"⚠️ Skipping: No URL")
                self.failed_downloads.append((idx, "No URL"))
                continue
            
            if not video_id.startswith('http'):
                video_url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                video_url = video_id
            
            try:
                self.download_single_video(video_url, download_path, widget_data)
                self.window.after(0, lambda: self.safe_tree_update(widget_data['item_id'], 'status', '✅'))
                self.completed_downloads.append(idx)
                self.log_callback(f"✅ [{current}/{total}] Completed")
            except Exception as e:
                self.window.after(0, lambda: self.safe_tree_update(widget_data['item_id'], 'status', '❌'))
                self.failed_downloads.append((idx, str(e)))
                self.log_callback(f"❌ [{current}/{total}] Error: {str(e)}")
        
        try:
            if self.window.winfo_exists():
                self.window.after(0, self.download_complete, total)
        except (tk.TclError, RuntimeError):
            pass
    
    def download_single_video(self, video_url, download_path, widget_data):
        """Download a single video with real-time progress"""
        
        # Sanitize filename template - convert {variable} to %(variable)s for yt-dlp
        template = self.filename_template_var.get()
        # Convert Python format {title} to yt-dlp format %(title)s
        template = template.replace('{title}', '%(title)s')
        template = template.replace('{uploader}', '%(uploader)s')
        template = template.replace('{date}', '%(upload_date)s')
        template = template.replace('{resolution}', '%(resolution)s')
        template = template.replace('{id}', '%(id)s')
        template = template.replace('{quality}', '%(height)sp')
        template = template.replace('{ext}', '%(ext)s')
        
        # Log download attempt for debugging
        entry = widget_data['entry']
        title = entry.get('title', 'Unknown')
        self.log_callback(f"🎬 Starting download: {video_url}")
        self.log_callback(f"📁 Download path: {download_path}")
        self.log_callback(f"📝 Filename template: {template}")
        
        # Progress hook for real-time updates (throttled to avoid GIL contention)
        _last_progress_time = [0]  # mutable container for closure
        
        def _do_ui_update(item_id, progress_text, speed_eta_text, size_text, speed_str, eta_str, percent):
            """Batch all UI updates in a single after() callback on the main thread"""
            try:
                if not self.window.winfo_exists():
                    return
                self.video_tree.set(item_id, 'progress', progress_text)
                self.video_tree.set(item_id, 'speed', speed_eta_text)
                self.video_tree.set(item_id, 'size', size_text)
                self.speed_var.set(f"Speed: {speed_str}")
                self.eta_var.set(f"ETA: {eta_str}")
                self.progress_bar.configure(value=percent)
            except (tk.TclError, RuntimeError, AttributeError):
                pass
        
        def progress_hook(d):
            if d['status'] == 'downloading':
                try:
                    # Throttle: update UI at most ~4 times per second
                    now = time.monotonic()
                    if now - _last_progress_time[0] < 0.25:
                        return
                    _last_progress_time[0] = now
                    
                    # Calculate progress percentage
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    
                    if total > 0:
                        percent = (downloaded / total) * 100
                        widget_data['progress'] = percent
                        
                        # Format speed
                        speed = d.get('speed', 0)
                        if speed:
                            speed_mb = speed / (1024 * 1024)
                            speed_str = f"{speed_mb:.2f} MB/s"
                        else:
                            speed_str = "..."
                        
                        # Format ETA
                        eta = d.get('eta', 0)
                        if eta:
                            eta_str = str(timedelta(seconds=int(eta)))
                        else:
                            eta_str = "..."
                        
                        # Format size
                        size_mb = downloaded / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        
                        progress_text = f"{percent:.1f}%"
                        speed_eta_text = f"{speed_str} | {eta_str}"
                        size_text = f"{size_mb:.1f}/{total_mb:.1f}MB"
                        
                        # Single after() call batching all UI updates
                        item_id = widget_data['item_id']
                        self.window.after(0, _do_ui_update, 
                                         item_id, progress_text, speed_eta_text, size_text,
                                         speed_str, eta_str, percent)
                        
                except (tk.TclError, RuntimeError, AttributeError):
                    pass  # Window was closed or widget destroyed, silently ignore
        
        # --- Folder per video: create a subfolder for each video ---
        video_folder = None
        if self.folder_per_video.get():
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:100].strip('. ')
            video_folder = Path(download_path) / safe_title
            video_folder.mkdir(parents=True, exist_ok=True)
            actual_download_path = video_folder
            self.log_callback(f"📁 Video folder: {video_folder}")
        else:
            actual_download_path = download_path
        
        ydl_opts = {
            'outtmpl': str(actual_download_path / f'{template}.%(ext)s'),
            'no_warnings': True,
            'quiet': False,
            'progress_hooks': [progress_hook],
        }
        
        # Apply parallel download options (IDM-style speed boost)
        parallel_opts = self._get_parallel_download_opts()
        ydl_opts.update(parallel_opts)
        
        # Log speed settings
        if parallel_opts.get('concurrent_fragment_downloads', 1) > 1:
            self.log_callback(f"⚡ Using {parallel_opts['concurrent_fragment_downloads']} parallel connections")
        if parallel_opts.get('external_downloader') == 'aria2c':
            self.log_callback(f"⚡ Using aria2c with {self.aria2c_connections.get()} connections per server")
        
        # Set FFmpeg location if available (critical for audio merging & conversion)
        if self.ffmpeg_location:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_location
        
        # Check if video belongs to a group with specific settings
        # Get group from tree instead of widget_data (since we store it in tree)
        item_id = widget_data['item_id']
        video_group = self.video_tree.set(item_id, 'group')
        download_type = self.download_type.get()
        
        if video_group and video_group in self.group_settings:
            # Use group settings
            group_settings = self.group_settings[video_group]
            download_type = group_settings.get('download_type', 'video')
            quality = group_settings.get('quality', 'Best Available')
            audio_quality = group_settings.get('audio_quality', 'Best Audio')
            self.log_callback(f"📁 Using group '{video_group}' settings: {quality}, {download_type}")
        else:
            # Use default or advanced mode settings
            if self.is_advanced_mode:
                quality = widget_data.get('quality', 'Best')
                audio_quality = self.audio_quality_var.get()
            else:
                quality = self.quality_var.get()
                audio_quality = self.audio_quality_var.get()
        
        if download_type == "video":
            if quality in ["Best", "Best Available"]:
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
            else:
                height = quality.split('(')[0].strip().replace('p', '')
                ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'
            # Ensure audio is merged into the output (requires FFmpeg)
            ydl_opts['merge_output_format'] = self.output_format_var.get()
        else:
            # Audio-only download
            if 'MP3' in audio_quality or audio_quality in ['320 kbps', '256 kbps', '192 kbps', '128 kbps', '96 kbps']:
                ydl_opts['format'] = 'bestaudio/best'
                # Extract numeric bitrate from strings like "MP3 (320kbps)" or "320 kbps"
                import re as _re
                bitrate_match = _re.search(r'(\d+)', audio_quality)
                bitrate = bitrate_match.group(1) if bitrate_match else '320'
                self.log_callback(f"🎵 Audio: MP3 at {bitrate}kbps")
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': bitrate,
                }]
            else:
                # Best Audio (m4a/webm) - no conversion needed
                ydl_opts['format'] = 'bestaudio/best'
                self.log_callback(f"🎵 Audio: Best available (no conversion)")
        
        # --- Download the video ---
        downloaded_filepath = None
        try:
            self.log_callback(f"🔧 yt-dlp options: {ydl_opts}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                # Determine downloaded file path from info
                if info:
                    downloaded_filepath = ydl.prepare_filename(info)
                    # If postprocessors changed extension (e.g. mp3), adjust
                    if download_type == "video" and not Path(downloaded_filepath).exists():
                        # Try mp4 extension
                        mp4_path = Path(downloaded_filepath).with_suffix('.mp4')
                        if mp4_path.exists():
                            downloaded_filepath = str(mp4_path)
                self.log_callback(f"✅ Download complete: {downloaded_filepath}")
        except Exception as e:
            self.log_callback(f"❌ Download error: {type(e).__name__}: {str(e)}")
            raise
        
        # --- Post-download: Save extras in per-video folder ---
        if video_folder and video_folder.exists():
            entry = widget_data['entry']
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:100].strip('. ')
            
            # Save thumbnail
            if self.folder_save_thumbnail.get():
                try:
                    thumbnail_url = entry.get('thumbnail', '') or ''
                    if not thumbnail_url:
                        thumbs = entry.get('thumbnails', [])
                        if thumbs:
                            thumbnail_url = thumbs[-1].get('url', '')
                    if thumbnail_url:
                        import urllib.request
                        thumb_ext = 'jpg'
                        if '.webp' in thumbnail_url:
                            thumb_ext = 'webp'
                        elif '.png' in thumbnail_url:
                            thumb_ext = 'png'
                        thumb_path = video_folder / f"{safe_title}_thumbnail.{thumb_ext}"
                        urllib.request.urlretrieve(thumbnail_url, str(thumb_path))
                        self.log_callback(f"  🖼️ Thumbnail saved: {thumb_path.name}")
                except Exception as e:
                    self.log_callback(f"  ⚠️ Thumbnail save failed: {e}")
            
            # Save metadata JSON
            if self.folder_save_metadata.get():
                try:
                    metadata = {
                        'title': title,
                        'video_id': entry.get('id', ''),
                        'url': entry.get('url', '') or entry.get('webpage_url', ''),
                        'uploader': entry.get('uploader', ''),
                        'channel_id': entry.get('channel_id', ''),
                        'upload_date': entry.get('upload_date', ''),
                        'duration_seconds': entry.get('duration', 0),
                        'duration_formatted': str(timedelta(seconds=int(entry.get('duration', 0) or 0))),
                        'description': entry.get('description', ''),
                        'views': entry.get('view_count', 0),
                        'likes': entry.get('like_count', 0),
                        'categories': entry.get('categories', []),
                        'tags': entry.get('tags', []),
                        'resolution': entry.get('resolution', ''),
                        'fps': entry.get('fps', ''),
                        'thumbnail_url': entry.get('thumbnail', ''),
                        'download_date': datetime.now().isoformat(),
                        'download_type': download_type,
                    }
                    json_path = video_folder / f"{safe_title}_metadata.json"
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=2, ensure_ascii=False)
                    self.log_callback(f"  📋 Metadata saved: {json_path.name}")
                except Exception as e:
                    self.log_callback(f"  ⚠️ Metadata save failed: {e}")
            
            # Save subtitles
            if self.folder_save_subtitles.get():
                try:
                    sub_url = entry.get('url', '') or entry.get('webpage_url', '')
                    if not sub_url and entry.get('id'):
                        sub_url = f"https://www.youtube.com/watch?v={entry['id']}"
                    if sub_url:
                        sub_opts = {
                            'skip_download': True,
                            'writesubtitles': True,
                            'writeautomaticsub': True,
                            'subtitleslangs': ['en'],
                            'outtmpl': str(video_folder / f"{safe_title}.%(ext)s"),
                            'quiet': True,
                        }
                        if self.ffmpeg_location:
                            sub_opts['ffmpeg_location'] = self.ffmpeg_location
                        with yt_dlp.YoutubeDL(sub_opts) as ydl:
                            ydl.download([sub_url])
                        self.log_callback(f"  📝 Subtitles saved in folder")
                except Exception as e:
                    self.log_callback(f"  ⚠️ Subtitles save failed: {e}")
            
            # Save description as .txt
            if self.folder_save_description.get():
                try:
                    description = entry.get('description', '')
                    if description:
                        desc_path = video_folder / f"{safe_title}_description.txt"
                        with open(desc_path, 'w', encoding='utf-8') as f:
                            f.write(f"Title: {title}\n")
                            f.write(f"URL: {entry.get('url', '') or entry.get('webpage_url', '')}\n")
                            f.write(f"Uploader: {entry.get('uploader', '')}\n")
                            f.write(f"Upload Date: {entry.get('upload_date', '')}\n")
                            f.write(f"Duration: {str(timedelta(seconds=int(entry.get('duration', 0) or 0)))}\n")
                            f.write(f"\n{'='*60}\n\n")
                            f.write(description)
                        self.log_callback(f"  📄 Description saved: {desc_path.name}")
                    else:
                        self.log_callback(f"  ⚠️ No description available")
                except Exception as e:
                    self.log_callback(f"  ⚠️ Description save failed: {e}")
        
        # --- Post-download: Split long videos if enabled ---
        if (self.split_enabled.get() 
                and download_type == "video" 
                and downloaded_filepath 
                and Path(downloaded_filepath).exists()):
            try:
                entry = widget_data['entry']
                duration = entry.get('duration', 0) or 0
                threshold_sec = self.split_threshold_min.get() * 60
                
                if duration >= threshold_sec:
                    self.log_callback(f"✂️ Video is {duration//60}min — splitting into {self.split_segment_min.get()}min segments...")
                    self.window.after(0, self.progress_var.set, f"✂️ Splitting: {entry.get('title', '')[:40]}")
                    
                    # If folder-per-video is active, split into the video folder
                    split_dest = str(video_folder) if video_folder and video_folder.exists() else download_path
                    self._split_video_into_parts(
                        filepath=downloaded_filepath,
                        entry=entry,
                        download_path=split_dest,
                        duration=duration
                    )
                else:
                    self.log_callback(f"ℹ️ Video is {duration//60}min — below {self.split_threshold_min.get()}min threshold, no split")
            except Exception as e:
                self.log_callback(f"⚠️ Split failed (original file kept): {e}")
    
    def _split_video_into_parts(self, filepath, entry, download_path, duration):
        """Split a downloaded video into parts, save thumbnail & JSON metadata"""
        import subprocess
        import math
        
        title = entry.get('title', 'Unknown')
        # Sanitize folder name
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:100]
        video_folder = Path(download_path) / safe_title
        video_folder.mkdir(parents=True, exist_ok=True)
        
        segment_sec = self.split_segment_min.get() * 60
        num_parts = math.ceil(duration / segment_sec)
        source_path = Path(filepath)
        ext = source_path.suffix  # e.g. .mp4
        
        # Determine ffmpeg executable path
        if self.ffmpeg_location:
            ffmpeg_exe = str(Path(self.ffmpeg_location) / 'ffmpeg.exe')
            if not Path(ffmpeg_exe).exists():
                ffmpeg_exe = str(Path(self.ffmpeg_location) / 'ffmpeg')
        else:
            ffmpeg_exe = 'ffmpeg'
        
        self.log_callback(f"✂️ Splitting into {num_parts} parts of {self.split_segment_min.get()}min each")
        self.log_callback(f"📁 Output folder: {video_folder}")
        
        split_files = []
        for part_num in range(1, num_parts + 1):
            start_sec = (part_num - 1) * segment_sec
            part_filename = f"{safe_title} - Part {part_num}{ext}"
            part_path = video_folder / part_filename
            
            cmd = [
                ffmpeg_exe,
                '-y',                    # Overwrite
                '-i', str(source_path),  # Input
                '-ss', str(start_sec),   # Start time
                '-t', str(segment_sec),  # Duration
                '-c', 'copy',            # No re-encode (fast!)
                '-avoid_negative_ts', 'make_zero',
                str(part_path)
            ]
            
            self.log_callback(f"  ✂️ Part {part_num}/{num_parts}: {start_sec//60}m-{min((start_sec+segment_sec)//60, duration//60)}m")
            
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode == 0 and part_path.exists():
                    size_mb = part_path.stat().st_size / (1024 * 1024)
                    split_files.append({
                        'part': part_num,
                        'filename': part_filename,
                        'start_sec': start_sec,
                        'end_sec': min(start_sec + segment_sec, duration),
                        'size_mb': round(size_mb, 2)
                    })
                    self.log_callback(f"  ✅ Part {part_num} saved ({size_mb:.1f} MB)")
                else:
                    self.log_callback(f"  ❌ Part {part_num} failed: {result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                self.log_callback(f"  ❌ Part {part_num} timed out")
            except Exception as e:
                self.log_callback(f"  ❌ Part {part_num} error: {e}")
            
            # Update progress
            progress = (part_num / num_parts) * 100
            self.window.after(0, lambda p=progress: self.progress_bar.configure(value=p))
        
        # --- Save thumbnail ---
        if self.split_save_thumbnail.get():
            try:
                thumbnail_url = entry.get('thumbnail', '') or entry.get('thumbnails', [{}])[-1].get('url', '')
                if thumbnail_url:
                    import urllib.request
                    thumb_ext = 'jpg'
                    # Try to detect extension from URL
                    if '.webp' in thumbnail_url:
                        thumb_ext = 'webp'
                    elif '.png' in thumbnail_url:
                        thumb_ext = 'png'
                    thumb_path = video_folder / f"{safe_title}_thumbnail.{thumb_ext}"
                    urllib.request.urlretrieve(thumbnail_url, str(thumb_path))
                    self.log_callback(f"  🖼️ Thumbnail saved: {thumb_path.name}")
                else:
                    self.log_callback(f"  ⚠️ No thumbnail URL available")
            except Exception as e:
                self.log_callback(f"  ⚠️ Thumbnail save failed: {e}")
        
        # --- Save metadata JSON ---
        if self.split_save_metadata.get():
            try:
                metadata = {
                    'title': title,
                    'video_id': entry.get('id', ''),
                    'url': entry.get('url', '') or entry.get('webpage_url', ''),
                    'uploader': entry.get('uploader', ''),
                    'channel_id': entry.get('channel_id', ''),
                    'upload_date': entry.get('upload_date', ''),
                    'duration_seconds': duration,
                    'duration_formatted': str(timedelta(seconds=int(duration))),
                    'description': entry.get('description', ''),
                    'views': entry.get('view_count', 0),
                    'likes': entry.get('like_count', 0),
                    'categories': entry.get('categories', []),
                    'tags': entry.get('tags', []),
                    'resolution': entry.get('resolution', ''),
                    'fps': entry.get('fps', ''),
                    'thumbnail_url': entry.get('thumbnail', ''),
                    'split_settings': {
                        'segment_minutes': self.split_segment_min.get(),
                        'threshold_minutes': self.split_threshold_min.get(),
                        'total_parts': num_parts,
                    },
                    'parts': split_files,
                    'original_filename': source_path.name,
                    'split_date': datetime.now().isoformat(),
                }
                json_path = video_folder / f"{safe_title}_metadata.json"
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                self.log_callback(f"  📋 Metadata saved: {json_path.name}")
            except Exception as e:
                self.log_callback(f"  ⚠️ Metadata save failed: {e}")
        
        # --- Move original file into the folder too ---
        try:
            original_dest = video_folder / source_path.name
            if not original_dest.exists():
                import shutil
                shutil.move(str(source_path), str(original_dest))
                self.log_callback(f"  📦 Original moved to folder: {source_path.name}")
        except Exception as e:
            self.log_callback(f"  ⚠️ Could not move original: {e}")
        
        self.log_callback(f"✅ Split complete: {len(split_files)}/{num_parts} parts in '{safe_title}/'")
    
    def pause_download(self):
        """Pause/resume download"""
        with self.download_lock:
            self.is_paused = not self.is_paused
            
            if self.is_paused:
                # Pause: clear the event to block the download thread
                self.pause_event.clear()
                self.pause_btn.config(text="▶ Resume")
                self.progress_var.set("⏸️ Paused - Click Resume to continue")
                self.log_callback("⏸️ Download paused")
            else:
                # Resume: set the event to unblock the download thread
                self.pause_event.set()
                self.pause_btn.config(text="⏸ Pause")
                self.progress_var.set("📥 Resuming download...")
                self.log_callback("▶ Download resumed")
    
    def cancel_download(self):
        """Cancel ongoing download"""
        if messagebox.askyesno("Cancel Download", 
                              "Cancel the download?", 
                              parent=self.window):
            with self.download_lock:
                self.cancel_flag = True
                self.is_downloading = False
                self.is_paused = False
            # Unblock if paused so the thread can exit
            self.pause_event.set()
            self.cancel_btn.config(state="disabled")
            self.pause_btn.config(state="disabled")
            self.log_callback("⏹️ Download cancelled")
    
    def download_complete(self, total):
        """Handle download completion"""
        self.progress_bar['value'] = 100
        self.current_video_var.set("")
        
        completed = len(self.completed_downloads)
        failed = len(self.failed_downloads)
        
        self.progress_var.set(
            f"✅ Complete! {completed}/{total} successful, {failed} failed")
        self.status_var.set(f"Download finished: {completed} OK, {failed} failed")
        
        self.download_btn.config(state="normal")
        self.pause_btn.config(state="disabled")
        self.cancel_btn.config(state="disabled")
        
        with self.download_lock:
            self.is_downloading = False
        
        self.log_callback(f"🎉 Batch complete! {completed} downloaded, {failed} failed")
        
        msg = f"Download Complete!\n\n"
        msg += f"✅ Successful: {completed}\n"
        msg += f"❌ Failed: {failed}"
        
        if failed > 0 and self.auto_retry.get():
            msg += f"\n\nRetry failed downloads?"
            if messagebox.askyesno("Retry Failed", msg, parent=self.window):
                self.retry_failed_downloads()
        else:
            messagebox.showinfo("Complete", msg, parent=self.window)
    
    def retry_failed_downloads(self):
        """Retry failed downloads"""
        self.log_callback(f"🔄 Retrying {len(self.failed_downloads)} failed downloads...")
        # TODO: Implement retry logic
    
    # ============= NEW ADVANCED MODE FEATURES =============
    
    def smart_quality_adjustment(self):
        """Auto-adjust quality based on video resolution and duration"""
        selected_items = self.video_tree.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select videos to adjust quality", parent=self.window)
            return
        
        adjusted_count = 0
        for item_id in selected_items:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    entry = widget_data['entry']
                    
                    # Get resolution and duration
                    resolution = entry.get('resolution', '').lower()
                    duration = entry.get('duration', 0)
                    
                    # Smart logic
                    if '4k' in resolution or '2160' in resolution:
                        quality = 'Best'
                    elif '1080' in resolution:
                        if duration > 1800:  # > 30 min
                            quality = '720p'  # Save space for long videos
                        else:
                            quality = '1080p'
                    elif '720' in resolution:
                        quality = '720p'
                    else:
                        quality = '480p'
                    
                    widget_data['quality'] = quality
                    self.video_tree.set(item_id, 'quality', quality)
                    adjusted_count += 1
                    break
        
        self.log_callback(f"🤖 Auto-adjusted quality for {adjusted_count} videos")
        self.update_selected_count()
    
    def set_selected_audio_only(self):
        """Set selected videos to audio-only download"""
        selected_items = self.video_tree.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select videos to set audio-only", parent=self.window)
            return
        
        for item_id in selected_items:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    widget_data['download_type'] = 'audio'
                    widget_data['quality'] = '320kbps'
                    self.video_tree.set(item_id, 'quality', '🎵 320kbps')
                    break
        
        self.log_callback(f"🎵 Set {len(selected_items)} videos to audio-only (320kbps MP3)")
        self.update_selected_count()
    
    def set_selected_with_subtitles(self):
        """Mark selected videos to download with subtitles"""
        selected_items = self.video_tree.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select videos", parent=self.window)
            return
        
        for item_id in selected_items:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    widget_data['download_subtitles'] = True
                    current_quality = widget_data.get('quality', 'Best')
                    self.video_tree.set(item_id, 'quality', f"{current_quality} +SUB")
                    break
        
        self.log_callback(f"📝 Marked {len(selected_items)} videos to download with subtitles")
        self.update_selected_count()
    
    def move_selected_to_top(self):
        """Move selected videos to top of download queue"""
        selected_items = self.video_tree.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select videos to move", parent=self.window)
            return
        
        # Move items to top
        for item_id in reversed(selected_items):
            self.video_tree.move(item_id, '', 0)
        
        self.log_callback(f"⬆️ Moved {len(selected_items)} videos to top of queue")
    
    def move_selected_to_bottom(self):
        """Move selected videos to bottom of download queue"""
        selected_items = self.video_tree.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select videos to move", parent=self.window)
            return
        
        # Move items to bottom
        for item_id in selected_items:
            self.video_tree.move(item_id, '', 'end')
        
        self.log_callback(f"⬇️ Moved {len(selected_items)} videos to bottom of queue")
    
    def skip_selected_items(self):
        """Mark selected videos to be skipped during download"""
        selected_items = self.video_tree.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select videos to skip", parent=self.window)
            return
        
        for item_id in selected_items:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    widget_data['skip'] = True
                    self.video_tree.set(item_id, 'status', '⏸️ Skip')
                    # Change item appearance
                    self.video_tree.item(item_id, tags=('skipped',))
                    break
        
        # Configure skipped tag appearance
        self.video_tree.tag_configure('skipped', background='#ffdddd', foreground='gray')
        
        self.log_callback(f"⏸️ Marked {len(selected_items)} videos to skip")
        self.update_selected_count()
    
    def copy_quality_settings(self):
        """Copy quality settings from first selected video to others"""
        selected_items = self.video_tree.selection()
        if len(selected_items) < 2:
            messagebox.showinfo("Need Multiple", "Select at least 2 videos (first = source, rest = targets)", 
                              parent=self.window)
            return
        
        # Get quality from first selected
        source_quality = None
        for widget_data in self.video_item_widgets:
            if widget_data['item_id'] == selected_items[0]:
                source_quality = widget_data.get('quality', 'Best')
                break
        
        if not source_quality:
            return
        
        # Apply to rest
        for item_id in selected_items[1:]:
            for widget_data in self.video_item_widgets:
                if widget_data['item_id'] == item_id:
                    widget_data['quality'] = source_quality
                    self.video_tree.set(item_id, 'quality', source_quality)
                    break
        
        self.log_callback(f"📋 Copied quality '{source_quality}' to {len(selected_items)-1} videos")
        self.update_selected_count()
    
    def show_format_analysis(self, item_id):
        """Show detailed format analysis with all available qualities"""
        for w in self.video_item_widgets:
            if w['item_id'] == item_id:
                entry = w['entry']
                title = entry.get('title', 'Unknown')
                video_url = self.get_video_url(entry)
                
                if not video_url:
                    messagebox.showerror("Error", "Could not get video URL", parent=self.window)
                    return
                
                # Create analysis window
                analysis_window = tk.Toplevel(self.window)
                analysis_window.title("🔍 Format Analysis")
                analysis_window.geometry("900x600")
                
                # Title frame
                title_frame = ttk.Frame(analysis_window, padding="10")
                title_frame.pack(fill=tk.X)
                
                ttk.Label(title_frame, text="🔍 Available Formats", 
                         font=('Arial', 14, 'bold')).pack(anchor=tk.W)
                ttk.Label(title_frame, text=title[:80], 
                         font=('Arial', 10), wraplength=880).pack(anchor=tk.W, pady=(5,0))
                
                ttk.Separator(analysis_window, orient='horizontal').pack(fill=tk.X, pady=10)
                
                # Status label
                status_frame = ttk.Frame(analysis_window, padding="10")
                status_frame.pack(fill=tk.X)
                status_label = ttk.Label(status_frame, text="⏳ Analyzing available formats...", 
                                        font=('Arial', 10))
                status_label.pack()
                
                # Create treeview for formats
                tree_frame = ttk.Frame(analysis_window, padding="10")
                tree_frame.pack(fill=tk.BOTH, expand=True)
                
                columns = ('format_id', 'ext', 'resolution', 'fps', 'vcodec', 'acodec', 'filesize', 'bitrate')
                format_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=15)
                
                # Column headings
                format_tree.heading('format_id', text='Format ID')
                format_tree.heading('ext', text='Ext')
                format_tree.heading('resolution', text='Resolution')
                format_tree.heading('fps', text='FPS')
                format_tree.heading('vcodec', text='Video Codec')
                format_tree.heading('acodec', text='Audio Codec')
                format_tree.heading('filesize', text='Size')
                format_tree.heading('bitrate', text='Bitrate')
                
                # Column widths
                format_tree.column('format_id', width=80)
                format_tree.column('ext', width=50)
                format_tree.column('resolution', width=100)
                format_tree.column('fps', width=50)
                format_tree.column('vcodec', width=120)
                format_tree.column('acodec', width=120)
                format_tree.column('filesize', width=100)
                format_tree.column('bitrate', width=100)
                
                scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=format_tree.yview)
                format_tree.configure(yscrollcommand=scrollbar.set)
                
                format_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                
                # Button frame
                btn_frame = ttk.Frame(analysis_window, padding="10")
                btn_frame.pack(fill=tk.X)
                
                ttk.Button(btn_frame, text="Refresh Analysis", 
                          command=lambda: self.refresh_format_analysis(video_url, format_tree, status_label)).pack(side=tk.LEFT, padx=5)
                ttk.Button(btn_frame, text="Close", 
                          command=analysis_window.destroy).pack(side=tk.RIGHT, padx=5)
                
                # Start analysis in background
                def analyze():
                    try:
                        import yt_dlp
                        
                        ydl_opts = {
                            'quiet': True,
                            'no_warnings': True,
                            'skip_download': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(video_url, download=False)
                            formats = info.get('formats', [])
                        
                        # Update UI in main thread
                        def update_tree():
                            try:
                                status_label.config(text=f"✅ Found {len(formats)} formats")
                                
                                # Clear existing items
                                for item in format_tree.get_children():
                                    format_tree.delete(item)
                                
                                # Add formats
                                for fmt in formats:
                                    format_id = fmt.get('format_id', 'N/A')
                                    ext = fmt.get('ext', 'N/A')
                                    resolution = fmt.get('resolution', 'N/A')
                                    fps = fmt.get('fps', 'N/A')
                                    vcodec = fmt.get('vcodec', 'none')
                                    acodec = fmt.get('acodec', 'none')
                                    filesize = fmt.get('filesize', 0)
                                    bitrate = fmt.get('tbr', 0)
                                    
                                    # Format filesize
                                    if filesize:
                                        size_mb = filesize / (1024 * 1024)
                                        if size_mb >= 1024:
                                            size_str = f"{size_mb/1024:.2f} GB"
                                        else:
                                            size_str = f"{size_mb:.1f} MB"
                                    else:
                                        size_str = "Unknown"
                                    
                                    # Format bitrate
                                    bitrate_str = f"{bitrate:.0f} kbps" if bitrate else "N/A"
                                    
                                    # Simplify codec names
                                    if vcodec and len(vcodec) > 20:
                                        vcodec = vcodec[:17] + "..."
                                    if acodec and len(acodec) > 20:
                                        acodec = acodec[:17] + "..."
                                    
                                    format_tree.insert('', 'end', values=(
                                        format_id, ext, resolution, fps, vcodec, acodec, size_str, bitrate_str
                                    ))
                            except:
                                pass
                        
                        self.window.after(0, update_tree)
                        
                    except Exception as e:
                        def show_error():
                            try:
                                status_label.config(text=f"❌ Error: {str(e)}")
                            except:
                                pass
                        self.window.after(0, show_error)
                
                threading.Thread(target=analyze, daemon=True).start()
                break
    
    def refresh_format_analysis(self, video_url, format_tree, status_label):
        """Refresh format analysis"""
        status_label.config(text="⏳ Re-analyzing formats...")
        # Trigger analysis again
        # This would be called from the button
    
    # ==================== Group Management Methods ====================
    
    def create_group(self):
        """Create a new download group with name and color"""
        self.log_callback("📁 Creating new group...")
        
        # Create dialog
        dialog = tk.Toplevel(self.window)
        dialog.title("➕ Create New Group")
        dialog.geometry("400x300")
        dialog.transient(self.window)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (dialog.winfo_screenheight() // 2) - (300 // 2)
        dialog.geometry(f"400x300+{x}+{y}")
        
        # Title
        title_frame = ttk.Frame(dialog, padding="10")
        title_frame.pack(fill=tk.X)
        ttk.Label(title_frame, text="📁 Create Download Group", 
                 font=('Arial', 12, 'bold')).pack()
        
        # Group name
        name_frame = ttk.LabelFrame(dialog, text="Group Name", padding="10")
        name_frame.pack(fill=tk.X, padx=10, pady=10)
        
        name_var = tk.StringVar()
        name_entry = ttk.Entry(name_frame, textvariable=name_var, font=('Arial', 10))
        name_entry.pack(fill=tk.X)
        name_entry.focus()
        
        # Predefined color options
        color_frame = ttk.LabelFrame(dialog, text="Group Color", padding="10")
        color_frame.pack(fill=tk.X, padx=10, pady=10)
        
        colors = [
            ("🔵 Blue", "#3498DB"),
            ("🟢 Green", "#2ECC71"),
            ("🟡 Yellow", "#F1C40F"),
            ("🟠 Orange", "#E67E22"),
            ("🔴 Red", "#E74C3C"),
            ("🟣 Purple", "#9B59B6"),
            ("🟤 Brown", "#795548"),
            ("⚫ Gray", "#95A5A6")
        ]
        
        selected_color = tk.StringVar(value=colors[0][1])
        
        for i, (label, color) in enumerate(colors):
            row = i // 4
            col = i % 4
            rb = ttk.Radiobutton(color_frame, text=label, value=color, 
                                variable=selected_color)
            rb.grid(row=row, column=col, padx=5, pady=2, sticky=tk.W)
        
        # Buttons
        button_frame = ttk.Frame(dialog, padding="10")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        def save_group():
            group_name = name_var.get().strip()
            if not group_name:
                messagebox.showwarning("Invalid Name", "Please enter a group name.")
                return
            
            if group_name in self.groups:
                messagebox.showwarning("Duplicate Name", "A group with this name already exists.")
                return
            
            # Save group
            self.groups[group_name] = {
                'color': selected_color.get(),
                'created': datetime.now().isoformat()
            }
            
            # Initialize group settings with defaults
            self.group_settings[group_name] = {
                'quality': self.quality_var.get(),
                'audio_quality': self.audio_quality_var.get(),
                'download_type': self.download_type.get(),
                'format': 'mp4'
            }
            
            self.log_callback(f"✅ Created group: {group_name}")
            messagebox.showinfo("Success", f"Group '{group_name}' created successfully!")
            dialog.destroy()
        
        ttk.Button(button_frame, text="✅ Create", 
                  command=save_group).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="❌ Cancel", 
                  command=dialog.destroy).pack(side=tk.RIGHT)
    
    def assign_to_group(self):
        """Assign selected videos to a group"""
        selected = self.video_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select videos to assign to a group.")
            return
        
        if not self.groups:
            messagebox.showinfo("No Groups", "Please create a group first.")
            self.create_group()
            return
        
        # Create selection dialog
        dialog = tk.Toplevel(self.window)
        dialog.title("📂 Assign to Group")
        dialog.geometry("350x400")
        dialog.transient(self.window)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (350 // 2)
        y = (dialog.winfo_screenheight() // 2) - (400 // 2)
        dialog.geometry(f"350x400+{x}+{y}")
        
        # Title
        title_frame = ttk.Frame(dialog, padding="10")
        title_frame.pack(fill=tk.X)
        ttk.Label(title_frame, text=f"📂 Assign {len(selected)} video(s) to group", 
                 font=('Arial', 11, 'bold')).pack()
        
        # Group list
        list_frame = ttk.LabelFrame(dialog, text="Select Group", padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Scrollable listbox
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, 
                            font=('Arial', 10), height=12)
        listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)
        
        # Populate groups
        group_items = []
        for group_name, group_info in self.groups.items():
            # Count videos in this group
            count = sum(1 for item in self.video_tree.get_children() 
                       if self.video_tree.set(item, 'group') == group_name)
            group_items.append((group_name, group_info, count))
        
        for group_name, group_info, count in group_items:
            color_emoji = "🔵🟢🟡🟠🔴🟣🟤⚫"[
                ["#3498DB", "#2ECC71", "#F1C40F", "#E67E22", 
                 "#E74C3C", "#9B59B6", "#795548", "#95A5A6"].index(group_info['color'])
                if group_info['color'] in ["#3498DB", "#2ECC71", "#F1C40F", "#E67E22", 
                                          "#E74C3C", "#9B59B6", "#795548", "#95A5A6"]
                else 0
            ]
            listbox.insert(tk.END, f"{color_emoji} {group_name} ({count} videos)")
        
        # Buttons
        button_frame = ttk.Frame(dialog, padding="10")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        def assign():
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a group.")
                return
            
            group_name = list(self.groups.keys())[selection[0]]
            
            # Assign videos to group
            for item in selected:
                self.video_tree.set(item, 'group', group_name)
                # Add color tag
                color = self.groups[group_name]['color']
                tag_name = f"group_{group_name}"
                if tag_name not in self.video_tree.tag_names():
                    self.video_tree.tag_configure(tag_name, background=self.lighten_color(color))
                self.video_tree.item(item, tags=(tag_name,))
            
            self.log_callback(f"✅ Assigned {len(selected)} videos to group: {group_name}")
            messagebox.showinfo("Success", f"Assigned {len(selected)} video(s) to '{group_name}'")
            dialog.destroy()
        
        ttk.Button(button_frame, text="✅ Assign", 
                  command=assign).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="❌ Cancel", 
                  command=dialog.destroy).pack(side=tk.RIGHT)
    
    def remove_from_group(self):
        """Remove selected videos from their groups"""
        selected = self.video_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select videos to remove from groups.")
            return
        
        # Remove group assignment
        removed_count = 0
        for item in selected:
            if self.video_tree.set(item, 'group'):
                self.video_tree.set(item, 'group', '')
                # Remove color tag
                self.video_tree.item(item, tags=())
                removed_count += 1
        
        if removed_count > 0:
            self.log_callback(f"✅ Removed {removed_count} videos from groups")
            messagebox.showinfo("Success", f"Removed {removed_count} video(s) from their groups")
        else:
            messagebox.showinfo("Info", "None of the selected videos are in groups")
    
    def edit_group_settings(self):
        """Edit settings for a specific group"""
        if not self.groups:
            messagebox.showinfo("No Groups", "Please create a group first.")
            return
        
        # Create selection dialog
        dialog = tk.Toplevel(self.window)
        dialog.title("⚙️ Group Settings")
        dialog.geometry("450x500")
        dialog.transient(self.window)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (450 // 2)
        y = (dialog.winfo_screenheight() // 2) - (500 // 2)
        dialog.geometry(f"450x500+{x}+{y}")
        
        # Title
        title_frame = ttk.Frame(dialog, padding="10")
        title_frame.pack(fill=tk.X)
        ttk.Label(title_frame, text="⚙️ Edit Group Settings", 
                 font=('Arial', 12, 'bold')).pack()
        
        # Group selection
        group_frame = ttk.LabelFrame(dialog, text="Select Group", padding="10")
        group_frame.pack(fill=tk.X, padx=10, pady=10)
        
        selected_group = tk.StringVar()
        group_combo = ttk.Combobox(group_frame, textvariable=selected_group, 
                                   state='readonly', font=('Arial', 10))
        group_combo['values'] = list(self.groups.keys())
        if self.groups:
            group_combo.current(0)
        group_combo.pack(fill=tk.X)
        
        # Settings frame
        settings_frame = ttk.LabelFrame(dialog, text="Download Settings", padding="10")
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Quality
        ttk.Label(settings_frame, text="Video Quality:").grid(row=0, column=0, sticky=tk.W, pady=5)
        quality_var = tk.StringVar()
        quality_combo = ttk.Combobox(settings_frame, textvariable=quality_var, 
                                     state='readonly', width=20)
        quality_combo['values'] = ['Best Available', '2160p (4K)', '1440p (2K)', 
                                   '1080p (FHD)', '720p (HD)', '480p (SD)', '360p', '240p']
        quality_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # Audio Quality
        ttk.Label(settings_frame, text="Audio Quality:").grid(row=1, column=0, sticky=tk.W, pady=5)
        audio_var = tk.StringVar()
        audio_combo = ttk.Combobox(settings_frame, textvariable=audio_var, 
                                   state='readonly', width=20)
        audio_combo['values'] = ['Best Audio', '320 kbps', '256 kbps', 
                                 '192 kbps', '128 kbps', '96 kbps']
        audio_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # Download Type
        ttk.Label(settings_frame, text="Download Type:").grid(row=2, column=0, sticky=tk.W, pady=5)
        type_var = tk.StringVar()
        type_combo = ttk.Combobox(settings_frame, textvariable=type_var, 
                                  state='readonly', width=20)
        type_combo['values'] = ['video', 'audio', 'both']
        type_combo.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # Format
        ttk.Label(settings_frame, text="Format:").grid(row=3, column=0, sticky=tk.W, pady=5)
        format_var = tk.StringVar()
        format_combo = ttk.Combobox(settings_frame, textvariable=format_var, 
                                    state='readonly', width=20)
        format_combo['values'] = ['mp4', 'webm', 'mkv', 'mp3', 'm4a', 'opus']
        format_combo.grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5)
        
        settings_frame.columnconfigure(1, weight=1)
        
        # Load settings function
        def load_settings(*args):
            group_name = selected_group.get()
            if group_name and group_name in self.group_settings:
                settings = self.group_settings[group_name]
                quality_var.set(settings.get('quality', 'Best Available'))
                audio_var.set(settings.get('audio_quality', 'Best Audio'))
                type_var.set(settings.get('download_type', 'video'))
                format_var.set(settings.get('format', 'mp4'))
            else:
                quality_var.set('Best Available')
                audio_var.set('Best Audio')
                type_var.set('video')
                format_var.set('mp4')
        
        group_combo.bind('<<ComboboxSelected>>', load_settings)
        load_settings()  # Load initial settings
        
        # Buttons
        button_frame = ttk.Frame(dialog, padding="10")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        def save_settings():
            group_name = selected_group.get()
            if not group_name:
                messagebox.showwarning("No Selection", "Please select a group.")
                return
            
            # Save settings
            self.group_settings[group_name] = {
                'quality': quality_var.get(),
                'audio_quality': audio_var.get(),
                'download_type': type_var.get(),
                'format': format_var.get()
            }
            
            self.log_callback(f"✅ Updated settings for group: {group_name}")
            messagebox.showinfo("Success", f"Settings updated for '{group_name}'")
            dialog.destroy()
        
        def delete_group():
            group_name = selected_group.get()
            if not group_name:
                messagebox.showwarning("No Selection", "Please select a group.")
                return
            
            if messagebox.askyesno("Confirm Delete", 
                                  f"Delete group '{group_name}'?\nVideos will not be deleted, only ungrouped."):
                # Remove group assignment from videos
                for item in self.video_tree.get_children():
                    if self.video_tree.set(item, 'group') == group_name:
                        self.video_tree.set(item, 'group', '')
                        self.video_tree.item(item, tags=())
                
                # Delete group
                del self.groups[group_name]
                if group_name in self.group_settings:
                    del self.group_settings[group_name]
                
                self.log_callback(f"🗑️ Deleted group: {group_name}")
                messagebox.showinfo("Deleted", f"Group '{group_name}' deleted")
                dialog.destroy()
        
        ttk.Button(button_frame, text="🗑️ Delete Group", 
                  command=delete_group).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="✅ Save", 
                  command=save_settings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="❌ Cancel", 
                  command=dialog.destroy).pack(side=tk.RIGHT)
    
    def lighten_color(self, hex_color, factor=0.3):
        """Lighten a hex color for background"""
        # Convert hex to RGB
        hex_color = hex_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        # Lighten
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
        
        return f'#{r:02x}{g:02x}{b:02x}'
