"""
Main Application Window - MVC Architecture
This is the refactored main window that uses controllers and views.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import os
from pathlib import Path
import sys
import subprocess
import shutil
from datetime import datetime
from typing import Optional, Dict, Any

# Import controllers
from controllers import DownloadController, VideoController, PlaylistController
from controllers.download_controller import DownloadConfig, DownloadProgress, DownloadState
from controllers.video_controller import VideoInfo, PlaylistInfo

# Import views
from views.components import (
    VideoInfoPanel, FormatSelector, ProgressPanel, 
    LogPanel, SpeedOptionsPanel, VideoDisplayInfo
)
from views.dialogs import PlaylistDialog, SettingsDialog, AboutDialog, PlaylistItemData

# Import core modules
from core import (
    DownloadType, VideoQuality, AudioQuality, URLType, DownloadStatus,
    FormatParser, URLParser,
    ClipboardMonitor, ClipboardMonitorConfig,
    IDMLogger, LogConfig, LogLevel, get_logger,
)

from plugin_manager import PluginManager


VERSION = "2.0.0"
logger = get_logger()


def check_ffmpeg() -> bool:
    """Check if FFmpeg is installed and available"""
    try:
        app_dir = Path(__file__).parent
        portable_ffmpeg = app_dir / "ffmpeg" / "bin" / "ffmpeg.exe"
        
        if portable_ffmpeg.exists():
            ffmpeg_bin_dir = str(portable_ffmpeg.parent)
            if ffmpeg_bin_dir not in os.environ.get('PATH', ''):
                os.environ['PATH'] = ffmpeg_bin_dir + os.pathsep + os.environ.get('PATH', '')
            return True
        
        result = subprocess.run(
            ['ffmpeg', '-version'], 
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return shutil.which('ffmpeg') is not None


def check_aria2c() -> bool:
    """Check if aria2c is available"""
    return shutil.which('aria2c') is not None


class MainWindow:
    """
    Main application window following MVC pattern.
    
    Responsibilities:
    - Coordinate between views and controllers
    - Handle user interactions
    - Manage application state
    """
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"IDM - Video Downloader v{VERSION}")
        self.root.geometry("850x750")
        self.root.resizable(True, True)
        
        # Initialize logging
        self._init_logging()
        logger.info(f"IDM Video Downloader v{VERSION} starting...")
        
        # Check external tools
        self.ffmpeg_available = check_ffmpeg()
        self.aria2c_available = check_aria2c()
        
        # Initialize controllers
        self._init_controllers()
        
        # Initialize plugin system
        self._init_plugins()
        
        # State variables
        self.current_video_info: Optional[VideoInfo] = None
        self.current_playlist_info: Optional[PlaylistInfo] = None
        self.download_path = str(Path.home() / "Downloads")
        self.download_type = tk.StringVar(value="video")
        self.clipboard_monitor_enabled = tk.BooleanVar(value=True)
        
        # Build UI
        self._create_gui()
        
        # Initialize clipboard monitor
        self._init_clipboard_monitor()
        
        # Log status
        if not self.ffmpeg_available:
            logger.info("FFmpeg not detected - MP3 conversion unavailable")
            self.root.after(500, lambda: self.log_panel.log(
                "FFmpeg not detected - Audio will save in original format. Install FFmpeg for MP3."
            ))
        else:
            logger.info("FFmpeg detected - MP3 conversion available")
        
        logger.info("Application initialized successfully")
    
    def _init_logging(self):
        """Initialize logging system"""
        global logger
        config = LogConfig(
            console_level=LogLevel.INFO,
            file_level=LogLevel.DEBUG,
            log_to_file=True,
            log_dir=Path.home() / ".idm-yt" / "logs",
        )
        logger = IDMLogger.setup(config)
    
    def _init_controllers(self):
        """Initialize all controllers"""
        # Download controller with callbacks
        self.download_controller = DownloadController(
            on_progress=self._on_download_progress,
            on_complete=self._on_download_complete,
            on_error=self._on_download_error,
        )
        
        # Video controller with callbacks
        self.video_controller = VideoController(
            on_info_fetched=self._on_video_info_fetched,
            on_error=self._on_video_error,
        )
        
        # Playlist controller
        self.playlist_controller = PlaylistController(
            on_item_progress=self._on_playlist_item_progress,
            on_item_complete=self._on_playlist_item_complete,
            on_all_complete=self._on_playlist_complete,
            on_error=self._on_playlist_error,
        )
    
    def _init_plugins(self):
        """Initialize plugin system"""
        self.plugin_manager = PluginManager()
        self.plugin_vars: Dict[str, tk.BooleanVar] = {}
        
        try:
            self.plugin_manager.discover()
            logger.debug(f"Discovered {len(self.plugin_manager.plugins)} plugins")
        except Exception as e:
            logger.warning(f"Plugin discovery failed: {e}")
    
    def _init_clipboard_monitor(self):
        """Initialize clipboard monitoring"""
        try:
            # ClipboardMonitorConfig expects milliseconds
            config = ClipboardMonitorConfig(
                check_interval_ms=int(1.0 * 1000),
                enabled=True,
            )

            # Build ClipboardMonitor with correct callbacks
            self.clipboard_monitor = ClipboardMonitor(
                on_url_detected=lambda url, auto: self._on_url_detected(url, auto),
                get_current_url=lambda: self.url_var.get(),
                set_url=lambda v: self.url_var.set(v),
                on_status_update=lambda msg: self.log_panel.log(msg) if hasattr(self, 'log_panel') else None,
                config=config,
            )

            if self.clipboard_monitor_enabled.get():
                # Use tkinter's after() scheduler for safe UI updates
                self.clipboard_monitor.start(scheduler=self.root.after)
        except Exception as e:
            logger.warning(f"Clipboard monitor failed: {e}")
            self.clipboard_monitor = None
    
    def _create_gui(self):
        """Create the main GUI layout"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        
        current_row = 0
        
        # === URL Input Section ===
        url_frame = self._create_url_section(main_frame)
        url_frame.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        current_row += 1
        
        # === Video Info Panel (using new component) ===
        self.video_info_panel = VideoInfoPanel(main_frame)
        self.video_info_panel.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        self.video_info_panel.grid_remove()  # Hidden until video fetched
        current_row += 1
        
        # === Download Type Selection ===
        type_frame = self._create_download_type_section(main_frame)
        type_frame.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        current_row += 1
        
        # === Extensions Section ===
        ext_frame = self._create_extensions_section(main_frame)
        ext_frame.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        current_row += 1
        
        # === Format Selector (using new component) ===
        self.format_selector = FormatSelector(main_frame)
        self.format_selector.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        current_row += 1
        
        # === Audio Options (hidden by default) ===
        self.audio_frame = self._create_audio_section(main_frame)
        self.audio_frame.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        self.audio_frame.grid_remove()
        current_row += 1
        
        # === Download Path ===
        path_frame = self._create_path_section(main_frame)
        path_frame.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        current_row += 1
        
        # === Speed Options (using new component) ===
        self.speed_panel = SpeedOptionsPanel(main_frame, aria2c_available=self.aria2c_available)
        self.speed_panel.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        current_row += 1
        
        # === Progress Panel (using new component) ===
        self.progress_panel = ProgressPanel(main_frame)
        self.progress_panel.grid(row=current_row, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        current_row += 1
        
        # === Control Buttons ===
        button_frame = self._create_button_section(main_frame)
        button_frame.grid(row=current_row, column=0, pady=(0, 10))
        current_row += 1
        
        # === Log Panel (using new component) ===
        self.log_panel = LogPanel(main_frame, height=6)
        self.log_panel.grid(row=current_row, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        main_frame.rowconfigure(current_row, weight=1)
        current_row += 1
        
        # === Footer ===
        footer_frame = self._create_footer(main_frame)
        footer_frame.grid(row=current_row, column=0, sticky=(tk.W, tk.E))
    
    def _create_url_section(self, parent) -> ttk.Frame:
        """Create URL input section"""
        frame = ttk.Frame(parent)
        frame.columnconfigure(1, weight=1)
        
        ttk.Label(frame, text="Video URL:", font=('Arial', 10, 'bold')).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 5)
        )
        
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(frame, textvariable=self.url_var, font=('Arial', 10))
        self.url_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        self.url_entry.bind('<Return>', lambda e: self._fetch_info())
        
        self.fetch_btn = ttk.Button(frame, text="Fetch Info", command=self._fetch_info)
        self.fetch_btn.grid(row=0, column=2)
        
        return frame
    
    def _create_download_type_section(self, parent) -> ttk.LabelFrame:
        """Create download type selection"""
        frame = ttk.LabelFrame(parent, text="Download Type", padding="5")
        
        types = [
            ("🎥 Video", "video"),
            ("🎵 Audio Only", "audio"),
            ("🖼️ Thumbnail", "thumbnail"),
            ("💬 Subtitles", "subtitles"),
        ]
        
        for text, value in types:
            ttk.Radiobutton(
                frame, text=text, variable=self.download_type,
                value=value, command=self._on_download_type_changed
            ).pack(side=tk.LEFT, padx=10)
        
        return frame
    
    def _create_extensions_section(self, parent) -> ttk.Frame:
        """Create collapsible extensions section"""
        container = ttk.Frame(parent)
        container.columnconfigure(0, weight=1)
        
        self.extensions_visible = tk.BooleanVar(value=False)
        self.ext_toggle_btn = ttk.Button(
            container, text="▶ Show Extensions (Plugins)",
            command=self._toggle_extensions
        )
        self.ext_toggle_btn.grid(row=0, column=0, sticky=tk.W)
        
        self.ext_frame = ttk.LabelFrame(container, text="Extensions (Plugins)", padding="5")
        self.ext_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.ext_frame.grid_remove()
        
        # Populate plugins
        for i, plugin in enumerate(self.plugin_manager.get_plugins()):
            var = tk.BooleanVar(value=getattr(plugin, 'enabled', True))
            self.plugin_vars[plugin.id] = var
            ttk.Checkbutton(
                self.ext_frame, 
                text=f"{plugin.name} — {plugin.description}",
                variable=var
            ).grid(row=i, column=0, sticky=tk.W, pady=2)
        
        ttk.Button(
            self.ext_frame, text="Run Enabled Extensions",
            command=self._run_extensions
        ).grid(row=len(self.plugin_manager.get_plugins()), column=0, sticky=tk.W, pady=(6, 0))
        
        return container
    
    def _create_audio_section(self, parent) -> ttk.LabelFrame:
        """Create audio quality options"""
        frame = ttk.LabelFrame(parent, text="Audio Quality Options", padding="5")
        frame.columnconfigure(1, weight=1)
        
        ttk.Label(frame, text="Audio Quality:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        
        self.audio_format_var = tk.StringVar()
        self.audio_format_combo = ttk.Combobox(
            frame, textvariable=self.audio_format_var,
            state="readonly", width=40
        )
        self.audio_format_combo.grid(row=0, column=1, sticky=(tk.W, tk.E))
        
        # Populate based on FFmpeg
        if self.ffmpeg_available:
            options = [
                "Best Audio (m4a/webm)",
                "MP3 (Best Quality)",
                "MP3 (320kbps)",
                "MP3 (192kbps)",
                "MP3 (128kbps)",
            ]
        else:
            options = [
                "Best Audio (m4a/webm)",
                "High Quality (128kbps+)",
            ]
        self.audio_format_combo['values'] = options
        self.audio_format_combo.current(0)
        
        return frame
    
    def _create_path_section(self, parent) -> ttk.Frame:
        """Create download path selection"""
        frame = ttk.Frame(parent)
        frame.columnconfigure(1, weight=1)
        
        ttk.Label(frame, text="Download Path:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        
        self.path_var = tk.StringVar(value=self.download_path)
        ttk.Entry(frame, textvariable=self.path_var, state="readonly").grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5)
        )
        
        ttk.Button(frame, text="Browse", command=self._browse_path).grid(row=0, column=2)
        
        return frame
    
    def _create_button_section(self, parent) -> ttk.Frame:
        """Create control buttons"""
        frame = ttk.Frame(parent)
        
        self.download_btn = ttk.Button(
            frame, text="Download", command=self._start_download, state="disabled"
        )
        self.download_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.cancel_btn = ttk.Button(
            frame, text="Cancel", command=self._cancel_download, state="disabled"
        )
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(frame, text="Clear", command=self._clear_all).pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(frame, text="Settings", command=self._show_settings).pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(frame, text="About", command=self._show_about).pack(side=tk.LEFT)
        
        return frame
    
    def _create_footer(self, parent) -> ttk.Frame:
        """Create footer with status"""
        frame = ttk.Frame(parent)
        
        self.clipboard_check = ttk.Checkbutton(
            frame, text="📋 Auto-detect URLs",
            variable=self.clipboard_monitor_enabled,
            command=self._toggle_clipboard_monitor
        )
        self.clipboard_check.pack(side=tk.LEFT, padx=20)
        
        ttk.Label(
            frame, text=f"Version {VERSION}",
            font=('Arial', 8), foreground='gray'
        ).pack(side=tk.RIGHT, padx=5)
        
        return frame
    
    # === Event Handlers ===
    
    def _fetch_info(self):
        """Fetch video information"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter a video URL")
            return
        
        self.fetch_btn.config(state="disabled")
        self.progress_panel.set_status("Fetching video information...")
        self.log_panel.log(f"Fetching info for: {url}")
        
        self.video_controller.fetch_info(url)
    
    def _on_video_info_fetched(self, info: VideoInfo):
        """Handle video info fetched callback"""
        self.current_video_info = info
        
        # Update video info panel
        display_info = VideoDisplayInfo(
            title=info.title,
            duration=self._format_duration(info.duration),
            uploader=info.uploader,
            views=f"{info.view_count:,}" if info.view_count else "N/A",
            thumbnail_url=info.thumbnail_url,
        )
        self.video_info_panel.set_info(display_info)
        self.video_info_panel.grid()
        
        # Update format selector
        formats = [(f"{f['resolution']} - {f['format_note']}", f['format_id']) 
                   for f in info.formats if f.get('resolution')]
        self.format_selector.set_formats(formats)
        
        # Enable download
        self.download_btn.config(state="normal")
        self.fetch_btn.config(state="normal")
        self.progress_panel.set_status("Ready to download")
        self.log_panel.log(f"✓ Video info loaded: {info.title}")
    
    def _on_video_error(self, error: str):
        """Handle video fetch error"""
        self.fetch_btn.config(state="normal")
        self.progress_panel.set_status("Error fetching info")
        self.log_panel.log(f"✗ Error: {error}")
        messagebox.showerror("Error", f"Failed to fetch video info:\n{error}")
    
    def _start_download(self):
        """Start the download"""
        if not self.current_video_info:
            messagebox.showwarning("Warning", "Please fetch video info first")
            return
        
        # Build download config
        config = DownloadConfig(
            url=self.url_var.get().strip(),
            output_path=self.path_var.get(),
            format_id=self.format_selector.get_selected_format_id(),
            download_type=DownloadType[self.download_type.get().upper()],
            output_format=self.format_selector.get_output_format(),
            concurrent_fragments=self.speed_panel.get_concurrent_fragments(),
            use_aria2c=self.speed_panel.use_aria2c(),
            aria2c_connections=self.speed_panel.get_aria2c_connections(),
        )
        
        # Update UI
        self.download_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress_panel.set_progress(0, "Starting download...")
        self.log_panel.log(f"Starting download: {self.current_video_info.title}")
        
        # Start download
        self.download_controller.start_download(config)
    
    def _on_download_progress(self, progress: DownloadProgress):
        """Handle download progress callback"""
        self.root.after(0, lambda: self._update_progress(progress))
    
    def _update_progress(self, progress: DownloadProgress):
        """Update progress UI (must be called from main thread)"""
        self.progress_panel.set_progress(
            progress.percent,
            f"{progress.downloaded_str} / {progress.total_str} • {progress.speed_str} • ETA: {progress.eta_str}"
        )
    
    def _on_download_complete(self, filepath: str):
        """Handle download complete"""
        self.root.after(0, lambda: self._finish_download(filepath))
    
    def _finish_download(self, filepath: str):
        """Finish download UI update"""
        self.progress_panel.set_progress(100, f"Download complete: {filepath}")
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.log_panel.log(f"✓ Download complete: {filepath}")
    
    def _on_download_error(self, error: str):
        """Handle download error"""
        self.root.after(0, lambda: self._handle_download_error(error))
    
    def _handle_download_error(self, error: str):
        """Handle download error UI update"""
        self.progress_panel.set_status(f"Error: {error}")
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.log_panel.log(f"✗ Download error: {error}")
        messagebox.showerror("Download Error", error)
    
    def _cancel_download(self):
        """Cancel current download"""
        self.download_controller.cancel()
        self.progress_panel.set_status("Download cancelled")
        self.cancel_btn.config(state="disabled")
        self.download_btn.config(state="normal")
        self.log_panel.log("Download cancelled by user")
    
    # === Playlist Callbacks ===
    
    def _on_playlist_item_progress(self, index: int, progress: DownloadProgress):
        """Handle playlist item progress"""
        self.root.after(0, lambda: self.progress_panel.set_progress(
            progress.percent,
            f"Item {index}: {progress.downloaded_str} / {progress.total_str}"
        ))
    
    def _on_playlist_item_complete(self, index: int, filepath: str):
        """Handle playlist item complete"""
        self.root.after(0, lambda: self.log_panel.log(f"✓ Item {index} complete"))
    
    def _on_playlist_complete(self, count: int):
        """Handle all playlist items complete"""
        self.root.after(0, lambda: [
            self.progress_panel.set_status(f"Playlist complete: {count} videos"),
            self.log_panel.log(f"✓ Playlist download complete ({count} videos)"),
            self.download_btn.config(state="normal"),
            self.cancel_btn.config(state="disabled"),
        ])
    
    def _on_playlist_error(self, index: int, error: str):
        """Handle playlist item error"""
        self.root.after(0, lambda: self.log_panel.log(f"✗ Item {index} error: {error}"))
    
    # === UI Actions ===
    
    def _on_download_type_changed(self):
        """Handle download type change"""
        dtype = self.download_type.get()
        
        if dtype == "video":
            self.format_selector.grid()
            self.audio_frame.grid_remove()
        elif dtype == "audio":
            self.format_selector.grid_remove()
            self.audio_frame.grid()
        else:
            self.format_selector.grid_remove()
            self.audio_frame.grid_remove()
    
    def _toggle_extensions(self):
        """Toggle extensions visibility"""
        if self.extensions_visible.get():
            self.ext_frame.grid_remove()
            self.ext_toggle_btn.config(text="▶ Show Extensions (Plugins)")
            self.extensions_visible.set(False)
        else:
            self.ext_frame.grid()
            self.ext_toggle_btn.config(text="▼ Hide Extensions (Plugins)")
            self.extensions_visible.set(True)
    
    def _run_extensions(self):
        """Run enabled extensions"""
        if not self.current_video_info:
            messagebox.showwarning("Warning", "Please fetch video info first")
            return
        
        enabled = [pid for pid, var in self.plugin_vars.items() if var.get()]
        self.log_panel.log(f"Running {len(enabled)} extensions...")
        # Plugin execution would go here
    
    def _browse_path(self):
        """Open folder browser"""
        folder = filedialog.askdirectory(initialdir=self.path_var.get())
        if folder:
            self.download_path = folder
            self.path_var.set(folder)
    
    def _clear_all(self):
        """Clear all fields"""
        self.url_var.set("")
        self.current_video_info = None
        self.video_info_panel.clear()
        self.video_info_panel.grid_remove()
        self.progress_panel.reset()
        self.download_btn.config(state="disabled")
    
    def _toggle_clipboard_monitor(self):
        """Toggle clipboard monitoring"""
        if self.clipboard_monitor:
            if self.clipboard_monitor_enabled.get():
                self.clipboard_monitor.start()
                self.log_panel.log("Clipboard monitor enabled")
            else:
                self.clipboard_monitor.stop()
                self.log_panel.log("Clipboard monitor disabled")
    
    def _on_url_detected(self, url: str, auto_pasted: bool = False):
        """Handle URL detected from clipboard (auto_pasted indicates auto-fill)"""
        self.root.after(0, lambda: self._handle_clipboard_url(url))
    
    def _handle_clipboard_url(self, url: str):
        """Handle clipboard URL in main thread"""
        if self.url_var.get() != url:
            self.url_var.set(url)
            self.log_panel.log(f"📋 URL detected: {url}")
    
    def _show_settings(self):
        """Show settings dialog"""
        settings = {
            "download_folder": self.download_path,
            "clipboard_monitor": self.clipboard_monitor_enabled.get(),
            "concurrent_fragments": self.speed_panel.get_concurrent_fragments(),
        }
        
        def on_save(new_settings):
            self.download_path = new_settings.get("download_folder", self.download_path)
            self.path_var.set(self.download_path)
            self.log_panel.log("Settings saved")
        
        dialog = SettingsDialog(self.root, settings, on_save=on_save)
        dialog.show()
    
    def _show_about(self):
        """Show about dialog"""
        dialog = AboutDialog(
            self.root,
            app_name="IDM-YT Video Downloader",
            version=VERSION,
            author="IDM-YT Team",
        )
        dialog.show()
    
    # === Utilities ===
    
    def _format_duration(self, seconds: int) -> str:
        """Format duration in seconds to HH:MM:SS"""
        if not seconds:
            return "N/A"
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"


def main():
    """Application entry point"""
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
