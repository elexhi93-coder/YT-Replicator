"""
Advanced Playlist Manager Window
Handles playlist/channel downloads with simple and advanced modes
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import yt_dlp
import threading
import re
from pathlib import Path


class PlaylistManager:
    """Advanced window for managing playlist/channel downloads"""
    
    def __init__(self, parent, playlist_info, playlist_entries, log_callback):
        self.parent = parent
        self.playlist_info = playlist_info
        self.playlist_entries = playlist_entries
        self.log_callback = log_callback
        self.is_advanced_mode = False
        self.video_qualities = {}  # Store individual video qualities
        self.is_downloading = False
        
        # Create window
        self.window = tk.Toplevel(parent)
        self.window.title(f"Playlist Manager - {playlist_info.get('title', 'Playlist')[:50]}")
        self.window.geometry("900x700")
        self.window.resizable(True, True)
        
        self.setup_ui()
        self.populate_video_list()
    
    def setup_ui(self):
        """Setup the main UI"""
        # Main frame
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        header_frame.columnconfigure(1, weight=1)
        
        # Playlist info
        playlist_count = len(self.playlist_entries)
        uploader = self.playlist_info.get('uploader', '')
        
        if uploader or self.playlist_info.get('channel_id'):
            icon = "📺"
            type_text = "Channel"
        else:
            icon = "📑"
            type_text = "Playlist"
        
        title_label = ttk.Label(header_frame, 
                               text=f"{icon} {type_text}: {self.playlist_info.get('title', 'Unknown')}",
                               font=('Arial', 12, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, sticky=tk.W)
        
        count_label = ttk.Label(header_frame, text=f"📊 Total videos: {playlist_count}")
        count_label.grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        
        # Mode toggle button
        self.mode_btn = ttk.Button(header_frame, text="🔧 Switch to Advanced Mode", 
                                   command=self.toggle_mode)
        self.mode_btn.grid(row=1, column=1, sticky=tk.E, pady=(5, 0))
        
        # Search and selection controls
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        control_frame.columnconfigure(1, weight=1)
        
        ttk.Label(control_frame, text="🔍 Search:").grid(row=0, column=0, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self.filter_videos())
        search_entry = ttk.Entry(control_frame, textvariable=self.search_var, width=30)
        search_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        ttk.Button(control_frame, text="✓ Select All", 
                  command=self.select_all).grid(row=0, column=2, padx=2)
        ttk.Button(control_frame, text="✗ Select None", 
                  command=self.select_none).grid(row=0, column=3, padx=2)
        
        self.selected_count_var = tk.StringVar(value=f"Selected: {playlist_count}")
        ttk.Label(control_frame, textvariable=self.selected_count_var).grid(
            row=0, column=4, padx=(10, 0))
        
        # Video list frame
        list_frame = ttk.LabelFrame(main_frame, text="Videos", padding="5")
        list_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # Canvas and scrollbar for video items
        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.video_items_frame = ttk.Frame(canvas)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Create window in canvas
        canvas_window = canvas.create_window((0, 0), window=self.video_items_frame, anchor="nw")
        
        # Configure canvas scrolling
        def configure_scroll_region(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def configure_canvas_width(event):
            canvas.itemconfig(canvas_window, width=event.width)
        
        self.video_items_frame.bind("<Configure>", configure_scroll_region)
        canvas.bind("<Configure>", configure_canvas_width)
        
        # Mouse wheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        self.canvas = canvas
        
        # Settings frame (Simple Mode - shown by default)
        self.simple_settings_frame = ttk.LabelFrame(main_frame, text="Download Settings (Simple Mode)", padding="10")
        self.simple_settings_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        self.simple_settings_frame.columnconfigure(1, weight=1)
        
        # Download type
        ttk.Label(self.simple_settings_frame, text="Download as:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        type_frame = ttk.Frame(self.simple_settings_frame)
        type_frame.grid(row=0, column=1, sticky=tk.W)
        
        self.download_type = tk.StringVar(value="video")
        ttk.Radiobutton(type_frame, text="🎥 Video", variable=self.download_type, 
                       value="video", command=self.toggle_download_type).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(type_frame, text="🎵 Audio Only", variable=self.download_type, 
                       value="audio", command=self.toggle_download_type).pack(side=tk.LEFT, padx=5)
        
        # Quality selection (Simple Mode)
        ttk.Label(self.simple_settings_frame, text="Quality:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        
        self.quality_var = tk.StringVar(value="Best Available")
        self.quality_combo = ttk.Combobox(self.simple_settings_frame, textvariable=self.quality_var, 
                                         state="readonly", width=40)
        self.quality_combo['values'] = [
            'Best Available',
            '2160p (4K)',
            '1440p (2K)',
            '1080p (Full HD)',
            '720p (HD)',
            '480p',
            '360p',
            '240p'
        ]
        self.quality_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=(5, 0))
        
        # Audio quality (hidden by default)
        self.audio_quality_frame = ttk.Frame(self.simple_settings_frame)
        
        ttk.Label(self.audio_quality_frame, text="Audio Quality:").pack(side=tk.LEFT, padx=(0, 10))
        self.audio_quality_var = tk.StringVar(value="Best Audio (m4a/webm)")
        audio_combo = ttk.Combobox(self.audio_quality_frame, textvariable=self.audio_quality_var, 
                                   state="readonly", width=35)
        audio_combo['values'] = [
            'Best Audio (m4a/webm)',
            'MP3 (320kbps)',
            'MP3 (192kbps)',
            'MP3 (128kbps)',
            'High Quality (128kbps+)',
            'Medium Quality (64-128kbps)'
        ]
        audio_combo.current(0)
        audio_combo.pack(side=tk.LEFT)
        
        # Download path
        ttk.Label(self.simple_settings_frame, text="Save to:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        path_frame = ttk.Frame(self.simple_settings_frame)
        path_frame.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=(5, 0))
        path_frame.columnconfigure(0, weight=1)
        
        self.path_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        ttk.Entry(path_frame, textvariable=self.path_var).grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        ttk.Button(path_frame, text="Browse", command=self.browse_path).grid(row=0, column=1)
        
        # Advanced settings frame (hidden by default)
        self.advanced_settings_frame = ttk.LabelFrame(main_frame, text="Advanced Settings", padding="10")
        self.advanced_settings_frame.columnconfigure(0, weight=1)
        
        # Quick actions for advanced mode
        actions_frame = ttk.Frame(self.advanced_settings_frame)
        actions_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        
        ttk.Label(actions_frame, text="Quick Actions:").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="Set All to 1080p", 
                  command=lambda: self.set_all_quality("1080p")).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions_frame, text="Set All to 720p", 
                  command=lambda: self.set_all_quality("720p")).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions_frame, text="Set All to Best", 
                  command=lambda: self.set_all_quality("Best")).pack(side=tk.LEFT, padx=2)
        
        # Progress frame
        progress_frame = ttk.LabelFrame(main_frame, text="Download Progress", padding="10")
        progress_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        
        self.progress_var = tk.StringVar(value="Ready to download")
        ttk.Label(progress_frame, textvariable=self.progress_var).grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=800)
        self.progress_bar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        
        self.current_video_var = tk.StringVar(value="")
        ttk.Label(progress_frame, textvariable=self.current_video_var, 
                 foreground="blue").grid(row=2, column=0, sticky=tk.W, pady=(5, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, pady=(10, 0))
        
        self.download_btn = ttk.Button(button_frame, text=f"▶ Download Selected ({len(self.playlist_entries)} videos)", 
                                      command=self.start_download, style="Accent.TButton")
        self.download_btn.pack(side=tk.LEFT, padx=5)
        
        self.cancel_btn = ttk.Button(button_frame, text="⏹ Cancel", 
                                     command=self.cancel_download, state="disabled")
        self.cancel_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame, text="❌ Close", command=self.window.destroy).pack(side=tk.LEFT, padx=5)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, 
                               relief=tk.SUNKEN, anchor=tk.W)
        status_label.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=(10, 0))
        
        # Store video item widgets
        self.video_item_widgets = []
    
    def populate_video_list(self):
        """Populate the video list"""
        for idx, entry in enumerate(self.playlist_entries):
            self.create_video_item(idx, entry)
        
        self.update_selected_count()
    
    def create_video_item(self, idx, entry):
        """Create a single video item widget"""
        item_frame = ttk.Frame(self.video_items_frame)
        item_frame.grid(row=idx, column=0, sticky=(tk.W, tk.E), pady=2, padx=5)
        item_frame.columnconfigure(1, weight=1)
        
        # Checkbox
        var = tk.BooleanVar(value=True)
        checkbox = ttk.Checkbutton(item_frame, variable=var, command=self.update_selected_count)
        checkbox.grid(row=0, column=0, padx=(0, 5))
        
        # Number and title
        title = entry.get('title', 'Unknown Title')
        duration = entry.get('duration', 0)
        duration_int = int(duration) if duration else 0
        dur_str = f"{duration_int//60}:{duration_int%60:02d}" if duration_int else "?"
        
        title_label = ttk.Label(item_frame, text=f"{idx+1}. {title[:70]}... [{dur_str}]", 
                               width=70, anchor=tk.W)
        title_label.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        
        # Quality dropdown (hidden in simple mode)
        quality_var = tk.StringVar(value="Best")
        quality_combo = ttk.Combobox(item_frame, textvariable=quality_var, 
                                    state="readonly", width=20)
        quality_combo['values'] = ['Best', '1080p', '720p', '480p', '360p']
        
        # Info button
        info_btn = ttk.Button(item_frame, text="ℹ️ Info", width=8,
                             command=lambda: self.show_video_info(idx, entry))
        
        # Store widgets
        self.video_item_widgets.append({
            'frame': item_frame,
            'checkbox': checkbox,
            'var': var,
            'title_label': title_label,
            'quality_combo': quality_combo,
            'quality_var': quality_var,
            'info_btn': info_btn,
            'entry': entry
        })
    
    def toggle_mode(self):
        """Toggle between simple and advanced mode"""
        self.is_advanced_mode = not self.is_advanced_mode
        
        if self.is_advanced_mode:
            # Switch to Advanced Mode
            self.mode_btn.config(text="📋 Switch to Simple Mode")
            self.simple_settings_frame.grid_remove()
            self.advanced_settings_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
            
            # Show quality dropdowns and info buttons for each video
            for idx, widget_data in enumerate(self.video_item_widgets):
                widget_data['quality_combo'].grid(row=0, column=2, padx=5)
                widget_data['info_btn'].grid(row=0, column=3, padx=5)
            
            self.log_callback("🔧 Switched to Advanced Mode - Individual quality control per video")
            self.status_var.set("Advanced Mode: Set quality for each video individually")
        else:
            # Switch to Simple Mode
            self.mode_btn.config(text="🔧 Switch to Advanced Mode")
            self.advanced_settings_frame.grid_remove()
            self.simple_settings_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
            
            # Hide quality dropdowns and info buttons
            for widget_data in self.video_item_widgets:
                widget_data['quality_combo'].grid_remove()
                widget_data['info_btn'].grid_remove()
            
            self.log_callback("📋 Switched to Simple Mode - One quality for all videos")
            self.status_var.set("Simple Mode: One quality setting for all videos")
    
    def toggle_download_type(self):
        """Toggle between video and audio download"""
        if self.download_type.get() == "video":
            self.audio_quality_frame.grid_remove()
            self.quality_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=(5, 0))
        else:
            self.quality_combo.grid_remove()
            self.audio_quality_frame.grid(row=1, column=1, sticky=tk.W, pady=(5, 0))
    
    def filter_videos(self):
        """Filter videos based on search text"""
        search_text = self.search_var.get().lower()
        
        for widget_data in self.video_item_widgets:
            title = widget_data['entry'].get('title', '').lower()
            if search_text in title:
                widget_data['frame'].grid()
            else:
                widget_data['frame'].grid_remove()
    
    def select_all(self):
        """Select all visible videos"""
        for widget_data in self.video_item_widgets:
            if widget_data['frame'].winfo_viewable():
                widget_data['var'].set(True)
        self.update_selected_count()
    
    def select_none(self):
        """Deselect all videos"""
        for widget_data in self.video_item_widgets:
            widget_data['var'].set(False)
        self.update_selected_count()
    
    def update_selected_count(self):
        """Update the count of selected videos"""
        selected = sum(1 for w in self.video_item_widgets if w['var'].get())
        self.selected_count_var.set(f"Selected: {selected}")
        self.download_btn.config(text=f"▶ Download Selected ({selected} videos)")
    
    def set_all_quality(self, quality):
        """Set quality for all selected videos (Advanced mode)"""
        count = 0
        for widget_data in self.video_item_widgets:
            if widget_data['var'].get():
                widget_data['quality_var'].set(quality)
                count += 1
        
        self.log_callback(f"✅ Set quality to '{quality}' for {count} selected videos")
        messagebox.showinfo("Quality Set", f"Set quality to '{quality}' for {count} videos", 
                          parent=self.window)
    
    def browse_path(self):
        """Browse for download directory"""
        path = filedialog.askdirectory(initialdir=self.path_var.get(), parent=self.window)
        if path:
            self.path_var.set(path)
    
    def show_video_info(self, idx, entry):
        """Show detailed info for a specific video"""
        from video_window import VideoWindow
        
        video_id = entry.get('id') or entry.get('url')
        if not video_id:
            messagebox.showerror("Error", "Could not get video URL", parent=self.window)
            return
        
        # Construct URL
        if not video_id.startswith('http'):
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            video_url = video_id
        
        # Open video window
        video_window = tk.Toplevel(self.window)
        video_window.title(f"Video Info: {entry.get('title', 'Unknown')[:50]}")
        video_window.geometry("700x600")
        
        VideoWindow(video_window, video_url, entry.get('title', 'Unknown'), self.log_callback)
    
    def start_download(self):
        """Start downloading selected videos"""
        # Get selected videos
        selected_videos = [(i, w) for i, w in enumerate(self.video_item_widgets) if w['var'].get()]
        
        if not selected_videos:
            messagebox.showwarning("No Selection", "Please select at least one video to download", 
                                 parent=self.window)
            return
        
        # Validate path
        download_path = Path(self.path_var.get())
        if not download_path.exists():
            messagebox.showerror("Invalid Path", "Download path does not exist!", 
                               parent=self.window)
            return
        
        # Confirm download
        count = len(selected_videos)
        mode = "Advanced" if self.is_advanced_mode else "Simple"
        download_as = "Audio" if self.download_type.get() == "audio" else "Video"
        
        msg = f"Download {count} videos?\n\n"
        msg += f"Mode: {mode}\n"
        msg += f"Type: {download_as}\n"
        msg += f"Path: {download_path}"
        
        if not messagebox.askyesno("Confirm Download", msg, parent=self.window):
            return
        
        # Disable controls
        self.download_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.is_downloading = True
        
        # Start download thread
        threading.Thread(target=self.download_videos, 
                        args=(selected_videos, download_path), 
                        daemon=True).start()
    
    def download_videos(self, selected_videos, download_path):
        """Download videos in background thread"""
        total = len(selected_videos)
        
        for current, (idx, widget_data) in enumerate(selected_videos, 1):
            if not self.is_downloading:
                self.window.after(0, self.progress_var.set, "❌ Download cancelled")
                break
            
            entry = widget_data['entry']
            title = entry.get('title', 'Unknown')
            
            # Update progress
            self.window.after(0, self.progress_var.set, 
                            f"Downloading {current}/{total}: {title[:50]}")
            self.window.after(0, self.current_video_var.set, f"📥 {title[:80]}")
            self.window.after(0, self.progress_bar.config, 
                            {'value': ((current - 1) / total) * 100})
            
            self.log_callback(f"📥 [{current}/{total}] Downloading: {title[:60]}")
            
            # Get video URL
            video_id = entry.get('id') or entry.get('url')
            if not video_id:
                self.log_callback(f"⚠️ Skipping {title}: No URL found")
                continue
            
            if not video_id.startswith('http'):
                video_url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                video_url = video_id
            
            # Download
            try:
                self.download_single_video(video_url, download_path, widget_data)
                self.log_callback(f"✅ [{current}/{total}] Completed: {title[:60]}")
            except Exception as e:
                self.log_callback(f"❌ [{current}/{total}] Error: {title[:50]} - {str(e)}")
        
        # Complete
        self.window.after(0, self.download_complete, total)
    
    def download_single_video(self, video_url, download_path, widget_data):
        """Download a single video"""
        ydl_opts = {
            'outtmpl': str(download_path / '%(title)s.%(ext)s'),
            'no_warnings': True,
            'quiet': True,
        }
        
        if self.download_type.get() == "video":
            # Video download
            if self.is_advanced_mode:
                # Use individual quality
                quality = widget_data['quality_var'].get()
                if quality == "Best":
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                else:
                    # Extract height (e.g., "1080p" -> "1080")
                    height = quality.replace('p', '')
                    ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'
            else:
                # Use global quality
                quality = self.quality_var.get()
                if quality == "Best Available":
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                else:
                    height = quality.split('(')[0].strip().replace('p', '')
                    ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'
        else:
            # Audio download
            audio_quality = self.audio_quality_var.get()
            
            if 'MP3' in audio_quality:
                ydl_opts['format'] = 'bestaudio/best'
                bitrate = '320' if '320' in audio_quality else '192' if '192' in audio_quality else '128'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': bitrate,
                }]
            else:
                if 'Best' in audio_quality:
                    ydl_opts['format'] = 'bestaudio/best'
                elif 'High' in audio_quality:
                    ydl_opts['format'] = 'bestaudio[abr>=128]/bestaudio/best'
                elif 'Medium' in audio_quality:
                    ydl_opts['format'] = 'bestaudio[abr>=64][abr<=128]/bestaudio/best'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
    
    def download_complete(self, total):
        """Handle download completion"""
        self.progress_bar['value'] = 100
        self.progress_var.set(f"✅ Download complete! ({total} videos)")
        self.current_video_var.set("")
        self.status_var.set(f"Successfully downloaded {total} videos")
        
        self.download_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.is_downloading = False
        
        self.log_callback(f"🎉 Batch download complete! {total} videos downloaded")
        messagebox.showinfo("Complete", f"Successfully downloaded {total} videos!", 
                          parent=self.window)
    
    def cancel_download(self):
        """Cancel ongoing download"""
        if messagebox.askyesno("Cancel Download", 
                              "Are you sure you want to cancel the download?", 
                              parent=self.window):
            self.is_downloading = False
            self.cancel_btn.config(state="disabled")
            self.log_callback("⏹️ Download cancelled by user")
