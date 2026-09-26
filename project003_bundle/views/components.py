"""
Reusable UI Components for IDM-YT
Clean, modular Tkinter widgets.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable, List, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class VideoDisplayInfo:
    """Data for displaying video information"""
    title: str = ""
    duration: str = ""
    uploader: str = ""
    views: str = ""
    thumbnail_url: str = ""


class VideoInfoPanel(ttk.LabelFrame):
    """
    Panel for displaying video information with thumbnail.
    
    Usage:
        panel = VideoInfoPanel(parent)
        panel.set_info(VideoDisplayInfo(title="My Video", ...))
        panel.clear()
    """
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, text="Video Information", padding="10", **kwargs)
        self._create_widgets()
        self._thumbnail_image = None  # Keep reference to prevent GC
    
    def _create_widgets(self):
        # Thumbnail
        self.thumbnail_label = ttk.Label(self, text="No thumbnail", width=20)
        self.thumbnail_label.grid(row=0, column=0, rowspan=4, padx=(0, 15), sticky=tk.NW)
        
        # Info labels
        info_frame = ttk.Frame(self)
        info_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N))
        info_frame.columnconfigure(1, weight=1)
        
        # Title
        ttk.Label(info_frame, text="Title:", font=('Arial', 9, 'bold')).grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        self.title_var = tk.StringVar()
        self.title_label = ttk.Label(
            info_frame, textvariable=self.title_var, 
            wraplength=400, font=('Arial', 9)
        )
        self.title_label.grid(row=0, column=1, sticky=tk.W, padx=(5, 0), pady=2)
        
        # Duration
        ttk.Label(info_frame, text="Duration:", font=('Arial', 9, 'bold')).grid(
            row=1, column=0, sticky=tk.W, pady=2
        )
        self.duration_var = tk.StringVar()
        ttk.Label(info_frame, textvariable=self.duration_var).grid(
            row=1, column=1, sticky=tk.W, padx=(5, 0), pady=2
        )
        
        # Uploader
        ttk.Label(info_frame, text="Uploader:", font=('Arial', 9, 'bold')).grid(
            row=2, column=0, sticky=tk.W, pady=2
        )
        self.uploader_var = tk.StringVar()
        ttk.Label(info_frame, textvariable=self.uploader_var).grid(
            row=2, column=1, sticky=tk.W, padx=(5, 0), pady=2
        )
        
        # Views
        ttk.Label(info_frame, text="Views:", font=('Arial', 9, 'bold')).grid(
            row=3, column=0, sticky=tk.W, pady=2
        )
        self.views_var = tk.StringVar()
        ttk.Label(info_frame, textvariable=self.views_var).grid(
            row=3, column=1, sticky=tk.W, padx=(5, 0), pady=2
        )
    
    def set_info(self, info: VideoDisplayInfo):
        """Update panel with video information"""
        self.title_var.set(info.title)
        self.duration_var.set(info.duration)
        self.uploader_var.set(info.uploader)
        self.views_var.set(info.views)
    
    def set_thumbnail(self, image):
        """Set thumbnail image (PhotoImage)"""
        self._thumbnail_image = image
        self.thumbnail_label.configure(image=image, text="")
    
    def clear(self):
        """Clear all information"""
        self.title_var.set("")
        self.duration_var.set("")
        self.uploader_var.set("")
        self.views_var.set("")
        self._thumbnail_image = None
        self.thumbnail_label.configure(image="", text="No thumbnail")


class FormatSelector(ttk.LabelFrame):
    """
    Panel for selecting video/audio format and output container.
    
    Usage:
        selector = FormatSelector(parent)
        selector.set_video_formats([("1080p", "137"), ("720p", "136")])
        format_id = selector.get_selected_format_id()
        container = selector.get_output_format()
    """
    
    OUTPUT_FORMATS = {
        "MP4 (H.264/AAC) - Recommended": "mp4",
        "MKV (Matroska)": "mkv",
        "WebM (VP9/Opus)": "webm",
        "MOV (QuickTime)": "mov",
        "AVI": "avi",
        "FLV (Flash)": "flv",
        "3GP (Mobile)": "3gp",
    }
    
    def __init__(self, parent, title: str = "Video Quality Options", **kwargs):
        super().__init__(parent, text=title, padding="5", **kwargs)
        self.columnconfigure(1, weight=1)
        self._format_options = {}  # display -> format_id
        self._create_widgets()
    
    def _create_widgets(self):
        # Quality selector
        ttk.Label(self, text="Quality:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.format_var = tk.StringVar()
        self.format_combo = ttk.Combobox(
            self, textvariable=self.format_var,
            state="readonly", width=50
        )
        self.format_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        
        # Output format selector
        ttk.Label(self, text="Output Format:").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(5, 0)
        )
        self.output_format_var = tk.StringVar(value="MP4 (H.264/AAC) - Recommended")
        self.output_combo = ttk.Combobox(
            self, textvariable=self.output_format_var,
            values=list(self.OUTPUT_FORMATS.keys()),
            state="readonly", width=30
        )
        self.output_combo.grid(row=1, column=1, sticky=tk.W, padx=(0, 5), pady=(5, 0))
        self.output_combo.current(0)
        
        # Info label
        info_label = ttk.Label(
            self, text="YouTube Studio: MP4, MOV, AVI, WebM, FLV, 3GP",
            font=('Arial', 8), foreground='gray'
        )
        info_label.grid(row=1, column=1, sticky=tk.E, pady=(5, 0))
    
    def set_formats(self, formats: List[Tuple[str, str]]):
        """Set available formats: [(display_str, format_id), ...]"""
        self._format_options = {fmt[0]: fmt[1] for fmt in formats}
        self.format_combo['values'] = [fmt[0] for fmt in formats]
        if formats:
            self.format_combo.current(0)
    
    def get_selected_format(self) -> str:
        """Get selected format display string"""
        return self.format_var.get()
    
    def get_selected_format_id(self) -> Optional[str]:
        """Get selected format ID"""
        return self._format_options.get(self.format_var.get())
    
    def get_output_format(self) -> str:
        """Get selected output container format"""
        return self.OUTPUT_FORMATS.get(
            self.output_format_var.get(), "mp4"
        )


class ProgressPanel(ttk.LabelFrame):
    """
    Panel for displaying download progress.
    
    Usage:
        panel = ProgressPanel(parent)
        panel.set_progress(50.0, "Downloading... 50MB/100MB")
        panel.reset()
    """
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, text="Download Progress", padding="5", **kwargs)
        self.columnconfigure(0, weight=1)
        self._create_widgets()
    
    def _create_widgets(self):
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self, variable=self.progress_var,
            maximum=100, length=400
        )
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        
        # Status label
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(self, textvariable=self.status_var)
        self.status_label.grid(row=1, column=0, sticky=tk.W)
    
    def set_progress(self, percent: float, status: str = ""):
        """Update progress bar and status"""
        self.progress_var.set(percent)
        if status:
            self.status_var.set(status)
    
    def set_status(self, status: str):
        """Update status text only"""
        self.status_var.set(status)
    
    def reset(self):
        """Reset to initial state"""
        self.progress_var.set(0)
        self.status_var.set("Ready")


class LogPanel(ttk.LabelFrame):
    """
    Panel for displaying log messages.
    
    Usage:
        panel = LogPanel(parent)
        panel.log("Starting download...")
        panel.clear()
    """
    
    def __init__(self, parent, height: int = 8, **kwargs):
        super().__init__(parent, text="Log", padding="5", **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._create_widgets(height)
    
    def _create_widgets(self, height: int):
        # Text widget with scrollbar
        self.log_text = tk.Text(
            self, height=height, wrap=tk.WORD,
            font=('Consolas', 9), state='disabled'
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_text['yscrollcommand'] = scrollbar.set
    
    def log(self, message: str):
        """Add a log message with timestamp"""
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, f"{timestamp} {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
    
    def clear(self):
        """Clear all log messages"""
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state='disabled')


class SpeedOptionsPanel(ttk.LabelFrame):
    """
    Panel for parallel download settings.
    
    Usage:
        panel = SpeedOptionsPanel(parent)
        connections = panel.get_concurrent_fragments()
        use_aria = panel.use_aria2c()
    """
    
    def __init__(self, parent, aria2c_available: bool = False, **kwargs):
        super().__init__(parent, text="⚡ Speed Options", padding="5", **kwargs)
        self.aria2c_available = aria2c_available
        self._create_widgets()
    
    def _create_widgets(self):
        # Concurrent fragments
        ttk.Label(self, text="Parallel connections:").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 5)
        )
        self.concurrent_var = tk.IntVar(value=4)
        concurrent_spin = ttk.Spinbox(
            self, from_=1, to=16,
            textvariable=self.concurrent_var, width=5
        )
        concurrent_spin.grid(row=0, column=1, sticky=tk.W, padx=(0, 15))
        
        # aria2c option
        self.aria2c_var = tk.BooleanVar(value=False)
        self.aria2c_check = ttk.Checkbutton(
            self, text="Use aria2c (faster)",
            variable=self.aria2c_var,
            command=self._toggle_aria2c,
        )
        self.aria2c_check.grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        
        ttk.Label(self, text="aria2 connections:").grid(
            row=0, column=3, sticky=tk.W, padx=(0, 5)
        )
        self.aria2c_connections_var = tk.IntVar(value=16)
        self.aria2c_spin = ttk.Spinbox(
            self, from_=1, to=32,
            textvariable=self.aria2c_connections_var, width=5
        )
        self.aria2c_spin.grid(row=0, column=4, sticky=tk.W)
        
        # Show availability status
        if not self.aria2c_available:
            self.aria2c_check.config(state="disabled")
            self.aria2c_spin.config(state="disabled")
            ttk.Label(
                self, text="(aria2c not installed)",
                foreground="gray"
            ).grid(row=0, column=5, sticky=tk.W, padx=(5, 0))
        else:
            self._toggle_aria2c()
    
    def _toggle_aria2c(self):
        """Enable/disable aria2c connection spinbox"""
        if self.aria2c_var.get():
            self.aria2c_spin.config(state="normal")
        else:
            self.aria2c_spin.config(state="disabled")
    
    def get_concurrent_fragments(self) -> int:
        """Get number of parallel connections"""
        return self.concurrent_var.get()
    
    def use_aria2c(self) -> bool:
        """Check if aria2c should be used"""
        return self.aria2c_var.get() and self.aria2c_available
    
    def get_aria2c_connections(self) -> int:
        """Get aria2c connection count"""
        return self.aria2c_connections_var.get()
