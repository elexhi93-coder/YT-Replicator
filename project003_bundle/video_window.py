"""
Individual Video Window for Playlist Items
Allows downloading single videos from a playlist with custom quality selection
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import yt_dlp
import threading
import re
from pathlib import Path


class VideoWindow:
    """Popup window for individual video download from playlist"""
    
    def __init__(self, window, video_url, video_title, log_callback):
        self.window = window
        self.video_url = video_url
        self.video_title = video_title
        self.log_callback = log_callback
        self.video_info = None
        self.is_downloading = False
        self.video_format_options = {}
        
        self.setup_ui()
        self.fetch_video_info()
    
    def setup_ui(self):
        """Setup the window UI"""
        # Main frame
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Video Information
        info_frame = ttk.LabelFrame(main_frame, text="Video Information", padding="10")
        info_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        info_frame.columnconfigure(1, weight=1)
        
        ttk.Label(info_frame, text="Title:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.title_var = tk.StringVar(value="Loading...")
        ttk.Label(info_frame, textvariable=self.title_var, wraplength=550).grid(
            row=0, column=1, sticky=tk.W)
        
        ttk.Label(info_frame, text="Duration:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        self.duration_var = tk.StringVar(value="Loading...")
        ttk.Label(info_frame, textvariable=self.duration_var).grid(row=1, column=1, sticky=tk.W)
        
        ttk.Label(info_frame, text="Uploader:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5))
        self.uploader_var = tk.StringVar(value="Loading...")
        ttk.Label(info_frame, textvariable=self.uploader_var).grid(row=2, column=1, sticky=tk.W)
        
        ttk.Label(info_frame, text="Views:").grid(row=3, column=0, sticky=tk.W, padx=(0, 5))
        self.views_var = tk.StringVar(value="Loading...")
        ttk.Label(info_frame, textvariable=self.views_var).grid(row=3, column=1, sticky=tk.W)
        
        # Download Type
        type_frame = ttk.LabelFrame(main_frame, text="Download Type", padding="5")
        type_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.download_type = tk.StringVar(value="video")
        ttk.Radiobutton(type_frame, text="🎥 Video", variable=self.download_type, 
                       value="video", command=self.toggle_download_type).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(type_frame, text="🎵 Audio Only", variable=self.download_type, 
                       value="audio", command=self.toggle_download_type).pack(side=tk.LEFT, padx=10)
        
        # Video Quality
        self.video_frame = ttk.LabelFrame(main_frame, text="Video Quality", padding="5")
        self.video_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        self.video_frame.columnconfigure(1, weight=1)
        
        ttk.Label(self.video_frame, text="Quality:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.video_format_var = tk.StringVar()
        self.video_format_combo = ttk.Combobox(self.video_frame, textvariable=self.video_format_var, 
                                        state="readonly", width=60)
        self.video_format_combo.grid(row=0, column=1, sticky=(tk.W, tk.E))
        
        # Audio Quality
        self.audio_frame = ttk.LabelFrame(main_frame, text="Audio Quality", padding="5")
        self.audio_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        self.audio_frame.columnconfigure(1, weight=1)
        self.audio_frame.grid_remove()
        
        ttk.Label(self.audio_frame, text="Quality:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.audio_quality_var = tk.StringVar(value="Best Audio (m4a/webm)")
        self.audio_quality_combo = ttk.Combobox(self.audio_frame, textvariable=self.audio_quality_var,
                                        state="readonly", width=60)
        self.audio_quality_combo['values'] = [
            'Best Audio (m4a/webm)',
            'MP3 (Best Quality)',
            'MP3 (320kbps)',
            'MP3 (192kbps)',
            'MP3 (128kbps)',
            'High Quality (128kbps+)',
            'Medium Quality (64-128kbps)',
            'Worst Quality (Smallest Size)'
        ]
        self.audio_quality_combo.current(0)
        self.audio_quality_combo.grid(row=0, column=1, sticky=(tk.W, tk.E))
        
        # Download Path
        path_frame = ttk.LabelFrame(main_frame, text="Download Location", padding="5")
        path_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        path_frame.columnconfigure(1, weight=1)
        
        ttk.Label(path_frame, text="Save to:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.path_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        ttk.Entry(path_frame, textvariable=self.path_var, width=50).grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        ttk.Button(path_frame, text="Browse", command=self.browse_path).grid(
            row=0, column=2)
        
        # Progress
        progress_frame = ttk.LabelFrame(main_frame, text="Download Progress", padding="5")
        progress_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        
        self.progress_var = tk.StringVar(value="Ready")
        ttk.Label(progress_frame, textvariable=self.progress_var).grid(
            row=0, column=0, sticky=(tk.W, tk.E))
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=600)
        self.progress_bar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=(10, 0))
        
        self.download_btn = ttk.Button(button_frame, text="📥 Download", 
                                       command=self.start_download, state="disabled")
        self.download_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame, text="❌ Close", command=self.window.destroy).pack(side=tk.LEFT, padx=5)
        
        # Status
        self.status_var = tk.StringVar(value="Fetching video information...")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, 
                               relief=tk.SUNKEN, anchor=tk.W)
        status_label.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
    
    def toggle_download_type(self):
        """Toggle between video and audio download"""
        if self.download_type.get() == "video":
            self.video_frame.grid()
            self.audio_frame.grid_remove()
        else:
            self.video_frame.grid_remove()
            self.audio_frame.grid()
    
    def browse_path(self):
        """Browse for download directory"""
        path = filedialog.askdirectory(initialdir=self.path_var.get())
        if path:
            self.path_var.set(path)
    
    def fetch_video_info(self):
        """Fetch video information in background thread"""
        def fetch():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'no_check_certificate': True,
                    'socket_timeout': 30,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.video_url, download=False)
                    self.window.after(0, self.update_info, info)
                    
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                self.window.after(0, self.show_error, error_msg)
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def update_info(self, info):
        """Update UI with video information"""
        try:
            self.video_info = info
            
            # Update labels
            self.title_var.set(info.get('title', 'N/A'))
            
            duration = info.get('duration')
            if duration:
                duration_int = int(duration)
                minutes, seconds = divmod(duration_int, 60)
                hours, minutes = divmod(minutes, 60)
                if hours:
                    duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    duration_str = f"{minutes:02d}:{seconds:02d}"
                self.duration_var.set(duration_str)
            else:
                self.duration_var.set("N/A")
            
            self.uploader_var.set(info.get('uploader', 'N/A'))
            
            view_count = info.get('view_count')
            if view_count:
                self.views_var.set(f"{view_count:,}")
            else:
                self.views_var.set("N/A")
            
            # Parse video formats
            video_formats = []
            if 'formats' in info:
                for fmt in info['formats']:
                    if fmt.get('vcodec') != 'none':
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
            
            # Sort by quality
            def get_height(fmt_tuple):
                try:
                    height_match = re.search(r'(\d+)p', fmt_tuple[0])
                    return int(height_match.group(1)) if height_match else 0
                except:
                    return 0
            
            video_formats.sort(key=get_height, reverse=True)
            
            # Update dropdown
            if video_formats:
                self.video_format_combo['values'] = [fmt[0] for fmt in video_formats]
                self.video_format_options = {fmt[0]: fmt[1] for fmt in video_formats}
                self.video_format_combo.current(0)
                self.download_btn.config(state="normal")
                self.status_var.set(f"Ready - {len(video_formats)} quality options available")
            else:
                self.status_var.set("No video formats found")
            
            self.log_callback(f"✅ Loaded video info: {info.get('title', 'Unknown')[:50]}")
            
        except Exception as e:
            self.show_error(f"Error updating info: {str(e)}")
    
    def show_error(self, error_msg):
        """Show error message"""
        self.status_var.set(error_msg)
        messagebox.showerror("Error", error_msg, parent=self.window)
        self.log_callback(f"❌ {error_msg}")
    
    def start_download(self):
        """Start downloading the video"""
        if self.is_downloading:
            return
        
        try:
            download_path = Path(self.path_var.get())
            if not download_path.exists():
                messagebox.showerror("Error", "Download path does not exist!", parent=self.window)
                return
            
            self.is_downloading = True
            self.download_btn.config(state="disabled")
            self.progress_var.set("Starting download...")
            
            threading.Thread(target=self.download_video, args=(download_path,), daemon=True).start()
            
        except Exception as e:
            self.show_error(f"Error starting download: {str(e)}")
            self.is_downloading = False
    
    def download_video(self, download_path):
        """Download video in background thread"""
        try:
            def progress_hook(d):
                if d['status'] == 'downloading':
                    try:
                        percent = d.get('_percent_str', '0%').strip()
                        speed = d.get('_speed_str', 'N/A')
                        eta = d.get('_eta_str', 'N/A')
                        
                        # Update progress bar
                        try:
                            percent_val = float(percent.replace('%', ''))
                            self.window.after(0, self.progress_bar.config, {'value': percent_val})
                        except:
                            pass
                        
                        status_msg = f"Downloading: {percent} | Speed: {speed} | ETA: {eta}"
                        self.window.after(0, self.progress_var.set, status_msg)
                        
                    except:
                        pass
                        
                elif d['status'] == 'finished':
                    self.window.after(0, self.progress_var.set, "Processing... (merging video+audio)")
            
            ydl_opts = {
                'outtmpl': str(download_path / '%(title)s.%(ext)s'),
                'progress_hooks': [progress_hook],
                'no_warnings': True,
            }
            
            if self.download_type.get() == "video":
                # Video download
                selected_format = self.video_format_var.get()
                format_id = self.video_format_options.get(selected_format)
                
                if format_id:
                    ydl_opts['format'] = f"{format_id}+bestaudio/best"
                else:
                    ydl_opts['format'] = 'best'
            else:
                # Audio download
                audio_quality = self.audio_quality_var.get()
                
                if 'MP3' in audio_quality:
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '320' if '320' in audio_quality else 
                                          '192' if '192' in audio_quality else 
                                          '128' if '128' in audio_quality else '192',
                    }]
                else:
                    if 'Best' in audio_quality:
                        ydl_opts['format'] = 'bestaudio/best'
                    elif 'High' in audio_quality:
                        ydl_opts['format'] = 'bestaudio[abr>=128]/bestaudio/best'
                    elif 'Medium' in audio_quality:
                        ydl_opts['format'] = 'bestaudio[abr>=64][abr<=128]/bestaudio/best'
                    else:
                        ydl_opts['format'] = 'worstaudio/worst'
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.video_url])
            
            self.window.after(0, self.download_complete)
            
        except Exception as e:
            error_msg = f"Download error: {str(e)}"
            self.window.after(0, self.show_error, error_msg)
            self.window.after(0, self.download_btn.config, {'state': 'normal'})
            self.is_downloading = False
    
    def download_complete(self):
        """Handle download completion"""
        self.progress_bar['value'] = 100
        self.progress_var.set("✅ Download complete!")
        self.status_var.set("Download completed successfully!")
        self.is_downloading = False
        self.log_callback(f"✅ Downloaded: {self.video_title[:50]}")
        messagebox.showinfo("Success", "Download completed successfully!", parent=self.window)
        self.download_btn.config(state="normal")
