"""
Channel Monitor - Watch YouTube channels for new uploads
Periodically checks subscribed channels and notifies of new content
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import time
import re

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from n8n_webhook import get_config as get_webhook_config
    _WEBHOOK_AVAILABLE = True
except ImportError:
    _WEBHOOK_AVAILABLE = False


class ChannelMonitor:
    """Monitor YouTube channels for new uploads"""
    
    # Config file path
    CONFIG_FILE = Path(__file__).parent / "channel_monitor_config.json"
    
    def __init__(self, parent, log_callback=None, on_new_video_callback=None,
                 auto_download_callback=None, monitor_status_callback=None):
        self.parent = parent
        self.log_callback = log_callback or print
        self.on_new_video_callback = on_new_video_callback  # Called when new video found
        self.auto_download_callback = auto_download_callback  # Called to auto-download a video
        self.monitor_status_callback = monitor_status_callback  # Called with (is_monitoring, channel_count)

        # Channel data: {channel_id: {name, url, last_check, last_video_id, videos: []}}
        self.channels = {}
        self.load_config()
        
        # Monitoring state
        self.is_monitoring = False
        self.monitor_thread = None
        self.check_interval = tk.IntVar(value=30)  # Minutes
        
        # New videos found
        self.new_videos = []
        
        # Create window
        self.window = tk.Toplevel(parent)
        self.window.title("📡 Channel Monitor")
        self.window.geometry("800x550")
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.setup_ui()
        self.refresh_channel_list()
    
    def setup_ui(self):
        """Setup the monitor UI"""
        # Main container
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === TOP: Add channel section ===
        add_frame = ttk.LabelFrame(main_frame, text="➕ Add Channel to Monitor", padding="10")
        add_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(add_frame, text="Channel URL:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(add_frame, textvariable=self.url_var, width=50)
        url_entry.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        url_entry.bind('<Return>', lambda e: self.add_channel())
        
        ttk.Button(add_frame, text="➕ Add Channel", command=self.add_channel).pack(side=tk.LEFT)
        
        # === MIDDLE: Channels list and new videos ===
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(0, weight=1)
        
        # Left: Subscribed channels
        self.create_channel_list(content_frame)
        
        # Right: New videos found
        self.create_new_videos_panel(content_frame)
        
        # === BOTTOM: Monitor controls ===
        self.create_controls(main_frame)
    
    def create_channel_list(self, parent):
        """Create the subscribed channels list"""
        list_frame = ttk.LabelFrame(parent, text="📺 Monitored Channels", padding="5")
        list_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        
        # Treeview
        columns = ('name', 'last_check', 'status', 'auto_dl', 'webhook')
        self.channel_tree = ttk.Treeview(list_frame, columns=columns, show='headings',
                                          selectmode='browse')

        self.channel_tree.heading('name', text='📺 Channel')
        self.channel_tree.heading('last_check', text='🕐 Last Check')
        self.channel_tree.heading('status', text='📊 Status')
        self.channel_tree.heading('auto_dl', text='🤖 Auto-DL')
        self.channel_tree.heading('webhook', text='🔗 n8n Webhook')

        self.channel_tree.column('name', width=130, minwidth=90)
        self.channel_tree.column('last_check', width=100, minwidth=70)
        self.channel_tree.column('status', width=60, minwidth=50)
        self.channel_tree.column('auto_dl', width=65, minwidth=50)
        self.channel_tree.column('webhook', width=90, minwidth=60)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.channel_tree.yview)
        self.channel_tree.configure(yscrollcommand=scrollbar.set)
        
        self.channel_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind right-click
        self.channel_tree.bind('<Button-3>', self.show_channel_menu)
        self.channel_tree.bind('<Double-1>', self.check_channel_now)
        
        # Buttons under list
        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(btn_frame, text="🔄 Check Now",
                  command=self.check_selected_channel).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🌐 Open Channel",
                  command=self.open_channel).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️ Remove",
                  command=self.remove_channel).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🤖 Toggle Auto-DL",
                  command=self.toggle_auto_download).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🔗 Set Webhook",
                  command=self.set_channel_webhook).pack(side=tk.LEFT, padx=2)
    
    def create_new_videos_panel(self, parent):
        """Create the new videos panel"""
        videos_frame = ttk.LabelFrame(parent, text="🆕 New Videos Found", padding="5")
        videos_frame.grid(row=0, column=1, sticky='nsew')
        
        # Treeview for new videos
        columns = ('title', 'channel', 'date')
        self.new_videos_tree = ttk.Treeview(videos_frame, columns=columns, show='headings',
                                             selectmode='extended')
        
        self.new_videos_tree.heading('title', text='🎬 Title')
        self.new_videos_tree.heading('channel', text='📺 Channel')
        self.new_videos_tree.heading('date', text='📅 Date')
        
        self.new_videos_tree.column('title', width=200, minwidth=150)
        self.new_videos_tree.column('channel', width=100, minwidth=80)
        self.new_videos_tree.column('date', width=80, minwidth=60)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(videos_frame, orient='vertical', 
                                 command=self.new_videos_tree.yview)
        self.new_videos_tree.configure(yscrollcommand=scrollbar.set)
        
        self.new_videos_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind double-click to download
        self.new_videos_tree.bind('<Double-1>', self.download_selected_video)
        
        # Buttons
        btn_frame = ttk.Frame(videos_frame)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(btn_frame, text="⬇️ Download Selected", 
                  command=self.download_selected_videos).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⬇️ Download All", 
                  command=self.download_all_new).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="✓ Mark as Seen", 
                  command=self.clear_new_videos).pack(side=tk.LEFT, padx=2)
    
    def create_controls(self, parent):
        """Create monitoring controls and n8n webhook settings."""
        control_frame = ttk.LabelFrame(parent, text="⚙️ Monitor Settings", padding="10")
        control_frame.pack(fill=tk.X, pady=(10, 0))

        # Row 1: interval + status + buttons
        settings_frame = ttk.Frame(control_frame)
        settings_frame.pack(fill=tk.X)

        ttk.Label(settings_frame, text="Check every:").pack(side=tk.LEFT)
        interval_spin = ttk.Spinbox(settings_frame, from_=5, to=1440, width=5,
                                    textvariable=self.check_interval)
        interval_spin.pack(side=tk.LEFT, padx=5)
        ttk.Label(settings_frame, text="minutes").pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="⏸️ Monitoring stopped")
        ttk.Label(settings_frame, textvariable=self.status_var,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=30)

        self.countdown_var = tk.StringVar(value="")
        ttk.Label(settings_frame, textvariable=self.countdown_var,
                 foreground='blue').pack(side=tk.LEFT)

        btn_frame = ttk.Frame(settings_frame)
        btn_frame.pack(side=tk.RIGHT)

        self.start_btn = ttk.Button(btn_frame, text="▶️ Start Monitoring",
                                    command=self.start_monitoring)
        self.start_btn.pack(side=tk.LEFT, padx=2)

        self.stop_btn = ttk.Button(btn_frame, text="⏹️ Stop",
                                   command=self.stop_monitoring, state='disabled')
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(btn_frame, text="🔄 Check All Now",
                  command=self.check_all_channels).pack(side=tk.LEFT, padx=2)

        ttk.Button(btn_frame, text="❌ Close",
                  command=self.on_close).pack(side=tk.LEFT, padx=10)

        # Row 2: n8n global webhook URL
        webhook_frame = ttk.LabelFrame(control_frame, text="🔗 n8n Webhook (Global Fallback)",
                                       padding="5")
        webhook_frame.pack(fill=tk.X, pady=(8, 0))

        wh_row = ttk.Frame(webhook_frame)
        wh_row.pack(fill=tk.X)

        ttk.Label(wh_row, text="Webhook URL:").pack(side=tk.LEFT)
        self.global_webhook_var = tk.StringVar()
        if _WEBHOOK_AVAILABLE:
            self.global_webhook_var.set(get_webhook_config().global_url)
        wh_entry = ttk.Entry(wh_row, textvariable=self.global_webhook_var, width=55)
        wh_entry.pack(side=tk.LEFT, padx=(5, 5), fill=tk.X, expand=True)

        ttk.Button(wh_row, text="💾 Save",
                  command=self._save_global_webhook).pack(side=tk.LEFT, padx=2)

        self.webhook_enabled_var = tk.BooleanVar(
            value=get_webhook_config().enabled if _WEBHOOK_AVAILABLE else False
        )
        ttk.Checkbutton(wh_row, text="Enabled",
                       variable=self.webhook_enabled_var,
                       command=self._toggle_webhook_enabled).pack(side=tk.LEFT, padx=5)
    
    def add_channel(self):
        """Add a channel to monitor"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please enter a channel URL", parent=self.window)
            return
        
        # Extract channel info
        self.log_callback(f"🔍 Fetching channel info: {url}")
        self.status_var.set("⏳ Fetching channel info...")
        
        def fetch():
            try:
                ydl_opts = {
                    'quiet': True,
                    'extract_flat': True,
                    'playlistend': 1,  # Just get the first video to verify channel
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                
                # Get channel info
                if info.get('_type') == 'playlist':
                    channel_name = info.get('channel', info.get('uploader', info.get('title', 'Unknown')))
                    channel_id = info.get('channel_id', info.get('id', url))
                    channel_url = info.get('channel_url', info.get('webpage_url', url))
                    
                    # Get latest video ID
                    entries = info.get('entries', [])
                    latest_video_id = entries[0].get('id') if entries else None
                else:
                    # Single video - get channel from it
                    channel_name = info.get('channel', info.get('uploader', 'Unknown'))
                    channel_id = info.get('channel_id', channel_name)
                    channel_url = info.get('channel_url', url)
                    latest_video_id = info.get('id')
                
                # Add to channels
                self.channels[channel_id] = {
                    'name': channel_name,
                    'url': channel_url,
                    'last_check': datetime.now().isoformat(),
                    'last_video_id': latest_video_id,
                    'videos_seen': [latest_video_id] if latest_video_id else [],
                    'auto_download': False,
                }
                
                self.save_config()
                self.window.after(0, self.refresh_channel_list)
                self.window.after(0, lambda: self.url_var.set(""))
                self.window.after(0, lambda: self.status_var.set(f"✅ Added: {channel_name}"))
                self.log_callback(f"✅ Added channel: {channel_name}")
                
            except Exception as e:
                self.window.after(0, lambda: self.status_var.set(f"❌ Error: {str(e)[:50]}"))
                self.log_callback(f"❌ Error adding channel: {e}")
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def refresh_channel_list(self):
        """Refresh the channel treeview"""
        for item in self.channel_tree.get_children():
            self.channel_tree.delete(item)
        
        for channel_id, data in self.channels.items():
            last_check = data.get('last_check', 'Never')
            if last_check != 'Never':
                try:
                    dt = datetime.fromisoformat(last_check)
                    last_check = dt.strftime('%m/%d %H:%M')
                except:
                    pass
            
            auto_dl = '✅ ON' if data.get('auto_download', False) else '⬜ OFF'
            # Webhook: show per-channel URL if set, else show global indicator
            ch_webhook = ''
            if _WEBHOOK_AVAILABLE:
                cfg = get_webhook_config()
                if cfg.channel_urls.get(channel_id):
                    ch_webhook = '🔗 Custom'
                elif cfg.global_url:
                    ch_webhook = '🌐 Global'
                else:
                    ch_webhook = '—'
            self.channel_tree.insert('', 'end', iid=channel_id, values=(
                data.get('name', 'Unknown'),
                last_check,
                '✅ Active',
                auto_dl,
                ch_webhook,
            ))
    
    def remove_channel(self):
        """Remove selected channel"""
        selection = self.channel_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Select a channel to remove", parent=self.window)
            return
        
        channel_id = selection[0]
        channel_name = self.channels.get(channel_id, {}).get('name', 'Unknown')
        
        if messagebox.askyesno("Confirm", f"Remove '{channel_name}' from monitoring?", 
                               parent=self.window):
            del self.channels[channel_id]
            self.save_config()
            self.refresh_channel_list()
            self.log_callback(f"🗑️ Removed channel: {channel_name}")
    
    def check_selected_channel(self):
        """Check selected channel for new videos"""
        selection = self.channel_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Select a channel to check", parent=self.window)
            return
        
        self.check_channel(selection[0])
    
    def check_channel_now(self, event=None):
        """Double-click handler to check channel"""
        selection = self.channel_tree.selection()
        if selection:
            self.check_channel(selection[0])
    
    def check_channel(self, channel_id):
        """Check a single channel for new videos"""
        if channel_id not in self.channels:
            return
        
        channel_data = self.channels[channel_id]
        channel_name = channel_data.get('name', 'Unknown')
        channel_url = channel_data.get('url', '')
        
        self.log_callback(f"🔍 Checking channel: {channel_name}")
        self.status_var.set(f"⏳ Checking: {channel_name}")
        
        # Update tree status
        self.channel_tree.set(channel_id, 'status', '⏳ Checking...')
        
        def check():
            try:
                ydl_opts = {
                    'quiet': True,
                    'extract_flat': True,
                    'playlistend': 10,  # Check last 10 videos
                }
                
                # Construct videos URL
                if '/videos' not in channel_url:
                    videos_url = channel_url.rstrip('/') + '/videos'
                else:
                    videos_url = channel_url
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(videos_url, download=False)
                
                entries = info.get('entries', [])
                seen_ids = set(channel_data.get('videos_seen', []))
                new_videos = []
                
                for entry in entries:
                    video_id = entry.get('id')
                    if video_id and video_id not in seen_ids:
                        new_videos.append({
                            'id': video_id,
                            'title': entry.get('title', 'Unknown'),
                            'url': f"https://www.youtube.com/watch?v={video_id}",
                            'channel': channel_name,
                            'channel_id': channel_id,
                            'date': entry.get('upload_date', '')
                        })
                        seen_ids.add(video_id)
                
                # Update channel data
                channel_data['last_check'] = datetime.now().isoformat()
                channel_data['videos_seen'] = list(seen_ids)
                if entries:
                    channel_data['last_video_id'] = entries[0].get('id')
                
                self.save_config()
                
                # Add to new videos list
                self.new_videos.extend(new_videos)
                
                # Update UI
                self.window.after(0, self.refresh_channel_list)
                self.window.after(0, self.refresh_new_videos)
                
                if new_videos:
                    self.window.after(0, lambda: self.status_var.set(
                        f"🆕 Found {len(new_videos)} new video(s) from {channel_name}"))
                    self.log_callback(f"🆕 Found {len(new_videos)} new video(s) from {channel_name}")
                    
                    # Notify callback if set
                    if self.on_new_video_callback:
                        for video in new_videos:
                            self.on_new_video_callback(video)

                    # Auto-download if enabled for this channel
                    if channel_data.get('auto_download', False) and self.auto_download_callback:
                        for video in new_videos:
                            self.auto_download_callback(video)
                else:
                    self.window.after(0, lambda: self.status_var.set(
                        f"✅ No new videos from {channel_name}"))
                    self.log_callback(f"✅ No new videos from {channel_name}")
                
                self.window.after(0, lambda: self.channel_tree.set(channel_id, 'status', '✅'))
                
            except Exception as e:
                self.window.after(0, lambda: self.channel_tree.set(channel_id, 'status', '❌ Error'))
                self.window.after(0, lambda: self.status_var.set(f"❌ Error: {str(e)[:50]}"))
                self.log_callback(f"❌ Error checking {channel_name}: {e}")
        
        threading.Thread(target=check, daemon=True).start()
    
    def check_all_channels(self):
        """Check all channels for new videos"""
        if not self.channels:
            messagebox.showinfo("Info", "No channels to check", parent=self.window)
            return
        
        self.log_callback("🔄 Checking all channels...")
        
        def check_all():
            for channel_id in list(self.channels.keys()):
                self.check_channel(channel_id)
                time.sleep(2)  # Rate limiting
        
        threading.Thread(target=check_all, daemon=True).start()
    
    def refresh_new_videos(self):
        """Refresh the new videos treeview"""
        for item in self.new_videos_tree.get_children():
            self.new_videos_tree.delete(item)
        
        for i, video in enumerate(self.new_videos):
            date = video.get('date', '')
            if date and len(date) == 8:
                date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            
            self.new_videos_tree.insert('', 'end', iid=str(i), values=(
                video.get('title', 'Unknown')[:50],
                video.get('channel', 'Unknown'),
                date
            ), tags=(video.get('url', ''),))
    
    def download_selected_video(self, event=None):
        """Download double-clicked video"""
        selection = self.new_videos_tree.selection()
        if selection:
            self.download_videos([selection[0]])
    
    def download_selected_videos(self):
        """Download selected new videos"""
        selection = self.new_videos_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Select videos to download", parent=self.window)
            return
        self.download_videos(list(selection))
    
    def download_all_new(self):
        """Download all new videos"""
        if not self.new_videos:
            messagebox.showinfo("Info", "No new videos to download", parent=self.window)
            return
        
        all_ids = [str(i) for i in range(len(self.new_videos))]
        self.download_videos(all_ids)
    
    def download_videos(self, video_ids):
        """Download videos by their tree IDs"""
        urls = []
        for vid_id in video_ids:
            try:
                idx = int(vid_id)
                if 0 <= idx < len(self.new_videos):
                    urls.append(self.new_videos[idx]['url'])
            except:
                pass
        
        if urls and self.on_new_video_callback:
            for url in urls:
                self.on_new_video_callback({'url': url, 'action': 'download'})
            messagebox.showinfo("Download", f"Sent {len(urls)} video(s) to download queue", 
                               parent=self.window)
        elif urls:
            # Copy URLs to clipboard
            self.window.clipboard_clear()
            self.window.clipboard_append('\n'.join(urls))
            messagebox.showinfo("Copied", f"Copied {len(urls)} URL(s) to clipboard", 
                               parent=self.window)
    
    def clear_new_videos(self):
        """Clear/mark as seen all new videos"""
        self.new_videos.clear()
        self.refresh_new_videos()
        self.log_callback("✓ Marked all new videos as seen")
    
    def open_channel(self):
        """Open selected channel in browser"""
        selection = self.channel_tree.selection()
        if not selection:
            return
        
        channel_id = selection[0]
        url = self.channels.get(channel_id, {}).get('url', '')
        if url:
            import webbrowser
            webbrowser.open(url)
    
    def show_channel_menu(self, event):
        """Right-click context menu for channels"""
        item = self.channel_tree.identify_row(event.y)
        if item:
            self.channel_tree.selection_set(item)
        
        menu = tk.Menu(self.window, tearoff=0)
        menu.add_command(label="🔄 Check Now", command=self.check_selected_channel)
        menu.add_command(label="🌐 Open in Browser", command=self.open_channel)
        menu.add_separator()
        menu.add_command(label="🗑️ Remove", command=self.remove_channel)
        
        menu.tk_popup(event.x_root, event.y_root)
    
    def start_monitoring(self):
        """Start background monitoring"""
        if self.is_monitoring:
            return
        
        self.is_monitoring = True
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.status_var.set("▶️ Monitoring active")
        self.log_callback("▶️ Started channel monitoring")
        if self.monitor_status_callback:
            self.monitor_status_callback(True, len(self.channels))
        
        def monitor_loop():
            while self.is_monitoring:
                # Check all channels
                self.check_all_channels()
                
                # Wait for interval
                interval_seconds = self.check_interval.get() * 60
                for remaining in range(interval_seconds, 0, -1):
                    if not self.is_monitoring:
                        break
                    
                    mins, secs = divmod(remaining, 60)
                    self.window.after(0, lambda m=mins, s=secs: 
                                     self.countdown_var.set(f"Next check in: {m:02d}:{s:02d}"))
                    time.sleep(1)
                
                self.window.after(0, lambda: self.countdown_var.set(""))
        
        self.monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop background monitoring"""
        self.is_monitoring = False
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.status_var.set("⏸️ Monitoring stopped")
        self.countdown_var.set("")
        self.log_callback("⏸️ Stopped channel monitoring")
        if self.monitor_status_callback:
            self.monitor_status_callback(False, len(self.channels))
    
    def load_config(self):
        """Load saved channel configuration"""
        try:
            if self.CONFIG_FILE.exists():
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.channels = data.get('channels', {})
                    self.log_callback(f"📂 Loaded {len(self.channels)} monitored channel(s)")
        except Exception as e:
            self.log_callback(f"⚠️ Could not load config: {e}")
            self.channels = {}
    
    def save_config(self):
        """Save channel configuration"""
        try:
            data = {
                'channels': self.channels,
                'last_saved': datetime.now().isoformat()
            }
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_callback(f"⚠️ Could not save config: {e}")
    
    def on_close(self):
        """Handle window close — hides window if monitoring is active, preserving background monitoring."""
        if self.is_monitoring:
            # Keep monitoring running silently in background — just hide the window
            self.window.withdraw()
        else:
            self.save_config()
            self.window.destroy()

    def show(self):
        """Re-show the channel monitor window."""
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self.refresh_channel_list()
        self.refresh_new_videos()

    def toggle_auto_download(self):
        """Toggle auto-download for the selected channel."""
        selection = self.channel_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Select a channel to toggle auto-download",
                                parent=self.window)
            return
        channel_id = selection[0]
        if channel_id not in self.channels:
            return
        current = self.channels[channel_id].get('auto_download', False)
        self.channels[channel_id]['auto_download'] = not current
        self.save_config()
        self.refresh_channel_list()
        state = "enabled" if not current else "disabled"
        channel_name = self.channels[channel_id].get('name', 'Unknown')
        self.log_callback(f"🤖 Auto-download {state} for: {channel_name}")

    def set_channel_webhook(self):
        """Set a custom n8n webhook URL for the selected channel."""
        if not _WEBHOOK_AVAILABLE:
            messagebox.showwarning("Not Available",
                                   "n8n webhook module not found.",
                                   parent=self.window)
            return
        selection = self.channel_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Select a channel first.", parent=self.window)
            return
        channel_id = selection[0]
        channel_name = self.channels.get(channel_id, {}).get('name', 'Unknown')
        cfg = get_webhook_config()
        current_url = cfg.channel_urls.get(channel_id, '')

        # Show input dialog
        dialog = _WebhookURLDialog(
            self.window,
            title=f"n8n Webhook — {channel_name}",
            current_url=current_url,
            placeholder="https://your-n8n-host/webhook/xxxx",
        )
        self.window.wait_window(dialog)

        if dialog.result is None:
            return  # Cancelled

        new_url = dialog.result.strip()
        if new_url:
            cfg.set_channel_url(channel_id, new_url)
            self.log_callback(f"🔗 Webhook set for {channel_name}: {new_url}")
        else:
            cfg.remove_channel_url(channel_id)
            self.log_callback(f"🔗 Webhook removed for {channel_name} (using global)")
        self.refresh_channel_list()

    def _save_global_webhook(self):
        """Save the global fallback webhook URL."""
        if not _WEBHOOK_AVAILABLE:
            return
        url = self.global_webhook_var.get().strip()
        cfg = get_webhook_config()
        cfg.global_url = url
        cfg.save()
        self.refresh_channel_list()
        self.log_callback(f"🔗 Global webhook URL saved: {url or '(cleared)'}")

    def _toggle_webhook_enabled(self):
        """Enable/disable all webhook firing."""
        if not _WEBHOOK_AVAILABLE:
            return
        cfg = get_webhook_config()
        cfg.enabled = self.webhook_enabled_var.get()
        cfg.save()
        state = "enabled" if cfg.enabled else "disabled"
        self.log_callback(f"🔗 n8n webhooks {state}")


class _WebhookURLDialog(tk.Toplevel):
    """Simple dialog to enter/edit a webhook URL."""

    def __init__(self, parent, title: str, current_url: str, placeholder: str):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.geometry("520x130")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame,
                  text="Enter the n8n webhook URL for this channel.\n"
                       "Leave blank to use the global URL (or disable).",
                  justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 8))

        self._url_var = tk.StringVar(value=current_url)
        entry = ttk.Entry(frame, textvariable=self._url_var, width=60)
        entry.pack(fill=tk.X, pady=(0, 10))
        entry.focus_set()
        if not current_url:
            entry.insert(0, placeholder)
            entry.config(foreground='gray')
            entry.bind('<FocusIn>', lambda e: (entry.delete(0, tk.END),
                                               entry.config(foreground='black')))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(anchor=tk.E)
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT)

        self.bind('<Return>', lambda e: self._save())
        self.bind('<Escape>', lambda e: self.destroy())

    def _save(self):
        val = self._url_var.get().strip()
        # Ignore placeholder text
        if val.startswith('https://your-n8n-host'):
            val = ''
        self.result = val
        self.destroy()


# Test standalone
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    app = ChannelMonitor(root)
    root.mainloop()
