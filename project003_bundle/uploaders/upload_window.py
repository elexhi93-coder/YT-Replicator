"""
Upload Window - GUI for managing multi-platform video uploads.

Provides interface for:
- Configuring platform credentials
- Managing OAuth authentication
- Creating and managing upload jobs
- Monitoring upload progress
"""

import os
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, Dict, Any, List, Callable
import threading
import logging
from pathlib import Path

from uploaders import (
    UploadManager,
    UploadJob,
    JobStatus,
    Platform,
    VideoMetadata,
    UploadProgress,
    UploadStatus,
    AuthManager,
    OAuthProvider
)

logger = logging.getLogger(__name__)


class PlatformConfigDialog(tk.Toplevel):
    """Dialog for configuring platform OAuth credentials."""
    
    def __init__(self, parent, platform: Platform, current_config: Dict[str, str] = None):
        super().__init__(parent)
        
        self.platform = platform
        self.result = None
        
        self.title(f"Configure {platform.value.title()}")
        self.geometry("500x350")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 350) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets(current_config or {})
    
    def _create_widgets(self, current_config: Dict[str, str]):
        """Create dialog widgets."""
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Instructions
        instructions = self._get_instructions()
        instr_label = ttk.Label(
            main_frame,
            text=instructions,
            wraplength=450,
            justify=tk.LEFT
        )
        instr_label.pack(fill=tk.X, pady=(0, 15))
        
        # Client ID
        ttk.Label(main_frame, text="Client ID:").pack(anchor=tk.W)
        self.client_id_var = tk.StringVar(value=current_config.get('client_id', ''))
        client_id_entry = ttk.Entry(main_frame, textvariable=self.client_id_var, width=60)
        client_id_entry.pack(fill=tk.X, pady=(0, 10))
        
        # Client Secret
        ttk.Label(main_frame, text="Client Secret:").pack(anchor=tk.W)
        self.client_secret_var = tk.StringVar(value=current_config.get('client_secret', ''))
        client_secret_entry = ttk.Entry(main_frame, textvariable=self.client_secret_var, width=60, show='•')
        client_secret_entry.pack(fill=tk.X, pady=(0, 10))
        
        # Show/hide secret button
        self.show_secret = tk.BooleanVar(value=False)
        show_btn = ttk.Checkbutton(
            main_frame,
            text="Show secret",
            variable=self.show_secret,
            command=lambda: client_secret_entry.configure(show='' if self.show_secret.get() else '•')
        )
        show_btn.pack(anchor=tk.W, pady=(0, 10))
        
        # Platform-specific fields
        self._add_platform_fields(main_frame, current_config)
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.RIGHT)
    
    def _get_instructions(self) -> str:
        """Get platform-specific setup instructions."""
        instructions = {
            Platform.YOUTUBE: (
                "To get YouTube API credentials:\n"
                "1. Go to Google Cloud Console (console.cloud.google.com)\n"
                "2. Create a project and enable YouTube Data API v3\n"
                "3. Create OAuth 2.0 credentials (Desktop app type)\n"
                "4. Copy the Client ID and Client Secret below"
            ),
            Platform.DAILYMOTION: (
                "To get Dailymotion API credentials:\n"
                "1. Go to Dailymotion Partner HQ (www.dailymotion.com/partner)\n"
                "2. Create an application in the API section\n"
                "3. Copy the API Key (Client ID) and API Secret below"
            ),
            Platform.TIKTOK: (
                "To get TikTok API credentials:\n"
                "1. Go to TikTok for Developers (developers.tiktok.com)\n"
                "2. Create an app and request Content Posting API access\n"
                "3. Copy the Client Key and Client Secret below"
            ),
            Platform.FACEBOOK: (
                "To get Facebook API credentials:\n"
                "1. Go to Meta for Developers (developers.facebook.com)\n"
                "2. Create an app with Facebook Login and Video API\n"
                "3. Copy the App ID and App Secret below"
            )
        }
        return instructions.get(self.platform, "Enter your API credentials below.")
    
    def _add_platform_fields(self, parent, current_config: Dict[str, str]):
        """Add platform-specific configuration fields."""
        if self.platform == Platform.FACEBOOK:
            ttk.Label(parent, text="Page ID (optional, for page uploads):").pack(anchor=tk.W)
            self.page_id_var = tk.StringVar(value=current_config.get('page_id', ''))
            ttk.Entry(parent, textvariable=self.page_id_var, width=60).pack(fill=tk.X, pady=(0, 10))
    
    def _save(self):
        """Save configuration and close."""
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()
        
        if not client_id or not client_secret:
            messagebox.showerror("Error", "Client ID and Client Secret are required.")
            return
        
        self.result = {
            'client_id': client_id,
            'client_secret': client_secret
        }
        
        # Add platform-specific fields
        if self.platform == Platform.FACEBOOK:
            page_id = self.page_id_var.get().strip()
            if page_id:
                self.result['page_id'] = page_id
        
        self.destroy()


class UploadJobDialog(tk.Toplevel):
    """Dialog for creating a new upload job."""
    
    def __init__(
        self,
        parent,
        upload_manager: UploadManager,
        video_path: str = None
    ):
        super().__init__(parent)
        
        self.upload_manager = upload_manager
        self.result: Optional[UploadJob] = None
        
        self.title("New Upload")
        self.geometry("600x700")
        self.resizable(True, True)
        self.minsize(500, 600)
        self.transient(parent)
        self.grab_set()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 600) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 700) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets(video_path)
    
    def _create_widgets(self, video_path: str = None):
        """Create dialog widgets."""
        # Main scrollable frame
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        main_frame = ttk.Frame(canvas, padding=20)
        
        main_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=main_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Video file selection
        file_frame = ttk.LabelFrame(main_frame, text="Video File", padding=10)
        file_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.video_path_var = tk.StringVar(value=video_path or "")
        path_entry = ttk.Entry(file_frame, textvariable=self.video_path_var, width=50)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(
            file_frame,
            text="Browse...",
            command=self._browse_video
        ).pack(side=tk.RIGHT)
        
        # Metadata section
        meta_frame = ttk.LabelFrame(main_frame, text="Video Metadata", padding=10)
        meta_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Title
        ttk.Label(meta_frame, text="Title:").pack(anchor=tk.W)
        self.title_var = tk.StringVar()
        ttk.Entry(meta_frame, textvariable=self.title_var, width=60).pack(fill=tk.X, pady=(0, 10))
        
        # Description
        ttk.Label(meta_frame, text="Description:").pack(anchor=tk.W)
        self.description_text = tk.Text(meta_frame, height=5, width=60)
        self.description_text.pack(fill=tk.X, pady=(0, 10))
        
        # Tags
        ttk.Label(meta_frame, text="Tags (comma-separated):").pack(anchor=tk.W)
        self.tags_var = tk.StringVar()
        ttk.Entry(meta_frame, textvariable=self.tags_var, width=60).pack(fill=tk.X, pady=(0, 10))
        
        # Category
        ttk.Label(meta_frame, text="Category:").pack(anchor=tk.W)
        self.category_var = tk.StringVar()
        categories = [
            "Entertainment", "Music", "Gaming", "Education", "Science & Technology",
            "News & Politics", "Sports", "Comedy", "People & Blogs", "Film & Animation"
        ]
        category_combo = ttk.Combobox(
            meta_frame,
            textvariable=self.category_var,
            values=categories,
            width=40
        )
        category_combo.pack(anchor=tk.W, pady=(0, 10))
        
        # Privacy
        ttk.Label(meta_frame, text="Privacy:").pack(anchor=tk.W)
        self.privacy_var = tk.StringVar(value="private")
        privacy_frame = ttk.Frame(meta_frame)
        privacy_frame.pack(anchor=tk.W, pady=(0, 10))
        
        for value, text in [("private", "Private"), ("unlisted", "Unlisted"), ("public", "Public")]:
            ttk.Radiobutton(
                privacy_frame,
                text=text,
                variable=self.privacy_var,
                value=value
            ).pack(side=tk.LEFT, padx=(0, 15))
        
        # Thumbnail
        thumb_frame = ttk.Frame(meta_frame)
        thumb_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(thumb_frame, text="Thumbnail (optional):").pack(anchor=tk.W)
        self.thumbnail_var = tk.StringVar()
        ttk.Entry(thumb_frame, textvariable=self.thumbnail_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(thumb_frame, text="Browse...", command=self._browse_thumbnail).pack(side=tk.RIGHT)
        
        # Platforms section
        platform_frame = ttk.LabelFrame(main_frame, text="Upload Platforms", padding=10)
        platform_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.platform_vars: Dict[Platform, tk.BooleanVar] = {}
        
        for platform in Platform:
            frame = ttk.Frame(platform_frame)
            frame.pack(fill=tk.X, pady=2)
            
            var = tk.BooleanVar(value=False)
            self.platform_vars[platform] = var
            
            is_configured = self.upload_manager.is_platform_configured(platform)
            is_authenticated = self.upload_manager.is_platform_authenticated(platform)
            
            cb = ttk.Checkbutton(
                frame,
                text=platform.value.title(),
                variable=var,
                state=tk.NORMAL if is_configured else tk.DISABLED
            )
            cb.pack(side=tk.LEFT)
            
            if is_configured:
                status = "✓ Authenticated" if is_authenticated else "⚠ Not authenticated"
                color = "green" if is_authenticated else "orange"
            else:
                status = "Not configured"
                color = "gray"
            
            status_label = ttk.Label(frame, text=status, foreground=color)
            status_label.pack(side=tk.RIGHT)
        
        # Schedule section
        schedule_frame = ttk.LabelFrame(main_frame, text="Scheduling", padding=10)
        schedule_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.schedule_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            schedule_frame,
            text="Schedule upload for later",
            variable=self.schedule_var,
            command=self._toggle_schedule
        ).pack(anchor=tk.W)
        
        self.schedule_datetime_frame = ttk.Frame(schedule_frame)
        self.schedule_datetime_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(self.schedule_datetime_frame, text="Date (YYYY-MM-DD):").pack(side=tk.LEFT)
        self.schedule_date_var = tk.StringVar()
        ttk.Entry(
            self.schedule_datetime_frame,
            textvariable=self.schedule_date_var,
            width=12
        ).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(self.schedule_datetime_frame, text="Time (HH:MM):").pack(side=tk.LEFT, padx=(10, 0))
        self.schedule_time_var = tk.StringVar()
        ttk.Entry(
            self.schedule_datetime_frame,
            textvariable=self.schedule_time_var,
            width=8
        ).pack(side=tk.LEFT, padx=5)
        
        self.schedule_datetime_frame.pack_forget()  # Hidden by default
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Add to Queue", command=self._add_upload).pack(side=tk.RIGHT)
    
    def _browse_video(self):
        """Browse for video file."""
        filetypes = [
            ("Video files", "*.mp4 *.avi *.mov *.mkv *.webm *.flv *.wmv"),
            ("All files", "*.*")
        ]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.video_path_var.set(path)
            
            # Auto-fill title from filename
            if not self.title_var.get():
                self.title_var.set(Path(path).stem)
    
    def _browse_thumbnail(self):
        """Browse for thumbnail image."""
        filetypes = [
            ("Image files", "*.jpg *.jpeg *.png *.gif"),
            ("All files", "*.*")
        ]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.thumbnail_var.set(path)
    
    def _toggle_schedule(self):
        """Toggle schedule datetime visibility."""
        if self.schedule_var.get():
            self.schedule_datetime_frame.pack(fill=tk.X, pady=(10, 0))
        else:
            self.schedule_datetime_frame.pack_forget()
    
    def _add_upload(self):
        """Validate and add upload to queue."""
        # Validate video path
        video_path = self.video_path_var.get().strip()
        if not video_path or not os.path.exists(video_path):
            messagebox.showerror("Error", "Please select a valid video file.")
            return
        
        # Validate title
        title = self.title_var.get().strip()
        if not title:
            messagebox.showerror("Error", "Title is required.")
            return
        
        # Get selected platforms
        platforms = [p for p, var in self.platform_vars.items() if var.get()]
        if not platforms:
            messagebox.showerror("Error", "Please select at least one platform.")
            return
        
        # Create metadata
        tags = [t.strip() for t in self.tags_var.get().split(',') if t.strip()]
        
        metadata = VideoMetadata(
            title=title,
            description=self.description_text.get("1.0", tk.END).strip(),
            tags=tags,
            category=self.category_var.get(),
            privacy=self.privacy_var.get(),
            thumbnail_path=self.thumbnail_var.get() or None
        )
        
        # Parse schedule time
        scheduled_time = None
        if self.schedule_var.get():
            try:
                date_str = self.schedule_date_var.get().strip()
                time_str = self.schedule_time_var.get().strip()
                
                if date_str and time_str:
                    from datetime import datetime
                    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                    scheduled_time = dt.timestamp()
                    
                    if scheduled_time <= time.time():
                        messagebox.showerror("Error", "Scheduled time must be in the future.")
                        return
            except ValueError:
                messagebox.showerror("Error", "Invalid date/time format. Use YYYY-MM-DD and HH:MM.")
                return
        
        # Add to queue
        try:
            self.result = self.upload_manager.add_upload(
                video_path=video_path,
                metadata=metadata,
                platforms=platforms,
                scheduled_time=scheduled_time
            )
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add upload: {e}")


class UploadWindow(tk.Toplevel):
    """Main upload management window."""
    
    def __init__(self, parent, upload_manager: UploadManager = None):
        super().__init__(parent)
        
        self.upload_manager = upload_manager or UploadManager()
        self._job_widgets: Dict[str, Dict[str, Any]] = {}
        
        self.title("Upload Manager")
        self.geometry("900x600")
        self.minsize(700, 500)
        
        # Load platform configs
        self._platform_configs: Dict[Platform, Dict[str, str]] = {}
        self._load_platform_configs()
        
        self._create_widgets()
        self._setup_callbacks()
        
        # Start upload manager
        self.upload_manager.start()
        
        # Refresh job list
        self._refresh_jobs()
        
        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _create_widgets(self):
        """Create window widgets."""
        # Main container
        main_container = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel - Platforms
        left_panel = ttk.Frame(main_container, width=250)
        main_container.add(left_panel, weight=1)
        
        # Platform configuration
        platform_frame = ttk.LabelFrame(left_panel, text="Platforms", padding=10)
        platform_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.platform_widgets: Dict[Platform, Dict[str, Any]] = {}
        
        for platform in Platform:
            frame = ttk.Frame(platform_frame)
            frame.pack(fill=tk.X, pady=5)
            
            # Platform name
            ttk.Label(frame, text=platform.value.title(), width=12).pack(side=tk.LEFT)
            
            # Status indicator
            status_label = ttk.Label(frame, text="○", foreground="gray")
            status_label.pack(side=tk.LEFT, padx=5)
            
            # Config button
            config_btn = ttk.Button(
                frame,
                text="Configure",
                width=10,
                command=lambda p=platform: self._configure_platform(p)
            )
            config_btn.pack(side=tk.RIGHT)
            
            # Auth button
            auth_btn = ttk.Button(
                frame,
                text="Login",
                width=8,
                command=lambda p=platform: self._authenticate_platform(p),
                state=tk.DISABLED
            )
            auth_btn.pack(side=tk.RIGHT, padx=5)
            
            self.platform_widgets[platform] = {
                'status': status_label,
                'config_btn': config_btn,
                'auth_btn': auth_btn
            }
        
        self._update_platform_status()
        
        # Statistics
        stats_frame = ttk.LabelFrame(left_panel, text="Statistics", padding=10)
        stats_frame.pack(fill=tk.X)
        
        self.stats_labels: Dict[str, ttk.Label] = {}
        for stat in ['Total Jobs', 'Queued', 'Completed', 'Success Rate']:
            row = ttk.Frame(stats_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"{stat}:").pack(side=tk.LEFT)
            label = ttk.Label(row, text="0")
            label.pack(side=tk.RIGHT)
            self.stats_labels[stat] = label
        
        # Right panel - Upload queue
        right_panel = ttk.Frame(main_container)
        main_container.add(right_panel, weight=3)
        
        # Toolbar
        toolbar = ttk.Frame(right_panel)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(
            toolbar,
            text="➕ New Upload",
            command=self._new_upload
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(
            toolbar,
            text="🔄 Refresh",
            command=self._refresh_jobs
        ).pack(side=tk.LEFT)
        
        # Filter
        ttk.Label(toolbar, text="Filter:").pack(side=tk.LEFT, padx=(20, 5))
        self.filter_var = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(
            toolbar,
            textvariable=self.filter_var,
            values=["All", "Queued", "In Progress", "Completed", "Failed"],
            width=12,
            state="readonly"
        )
        filter_combo.pack(side=tk.LEFT)
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_jobs())
        
        # Job list
        list_frame = ttk.LabelFrame(right_panel, text="Upload Queue", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # Treeview
        columns = ('title', 'platforms', 'status', 'progress')
        self.job_tree = ttk.Treeview(list_frame, columns=columns, show='headings')
        
        self.job_tree.heading('title', text='Title')
        self.job_tree.heading('platforms', text='Platforms')
        self.job_tree.heading('status', text='Status')
        self.job_tree.heading('progress', text='Progress')
        
        self.job_tree.column('title', width=200)
        self.job_tree.column('platforms', width=150)
        self.job_tree.column('status', width=100)
        self.job_tree.column('progress', width=150)
        
        # Scrollbars
        y_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.job_tree.yview)
        self.job_tree.configure(yscrollcommand=y_scroll.set)
        
        self.job_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Context menu
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="View Details", command=self._view_job_details)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Pause", command=self._pause_selected)
        self.context_menu.add_command(label="Resume", command=self._resume_selected)
        self.context_menu.add_command(label="Cancel", command=self._cancel_selected)
        self.context_menu.add_command(label="Retry", command=self._retry_selected)
        
        self.job_tree.bind("<Button-3>", self._show_context_menu)
        self.job_tree.bind("<Double-1>", lambda e: self._view_job_details())
    
    def _load_platform_configs(self):
        """Load saved platform configurations."""
        config_path = Path.home() / ".idm_platform_configs.json"
        if config_path.exists():
            try:
                import json
                with open(config_path, 'r') as f:
                    data = json.load(f)
                
                for platform_name, config in data.items():
                    try:
                        platform = Platform(platform_name)
                        self._platform_configs[platform] = config
                        
                        # Configure the platform
                        self.upload_manager.configure_platform(
                            platform,
                            config['client_id'],
                            config['client_secret'],
                            **{k: v for k, v in config.items() if k not in ('client_id', 'client_secret')}
                        )
                    except (ValueError, KeyError):
                        continue
            except Exception as e:
                logger.error(f"Failed to load platform configs: {e}")
    
    def _save_platform_configs(self):
        """Save platform configurations."""
        config_path = Path.home() / ".idm_platform_configs.json"
        try:
            import json
            data = {
                platform.value: config
                for platform, config in self._platform_configs.items()
            }
            with open(config_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save platform configs: {e}")
    
    def _configure_platform(self, platform: Platform):
        """Open platform configuration dialog."""
        current_config = self._platform_configs.get(platform, {})
        
        dialog = PlatformConfigDialog(self, platform, current_config)
        self.wait_window(dialog)
        
        if dialog.result:
            self._platform_configs[platform] = dialog.result
            self._save_platform_configs()
            
            # Configure the upload manager
            self.upload_manager.configure_platform(
                platform,
                dialog.result['client_id'],
                dialog.result['client_secret'],
                **{k: v for k, v in dialog.result.items() if k not in ('client_id', 'client_secret')}
            )
            
            self._update_platform_status()
            messagebox.showinfo("Success", f"{platform.value.title()} configured successfully!")
    
    def _authenticate_platform(self, platform: Platform):
        """Start OAuth flow for a platform."""
        def auth_callback(success: bool):
            self.after(0, lambda: self._on_auth_complete(platform, success))
        
        self.upload_manager.authenticate_platform(platform, auth_callback)
        
        # Update UI to show authenticating
        widgets = self.platform_widgets[platform]
        widgets['auth_btn'].configure(text="...", state=tk.DISABLED)
    
    def _on_auth_complete(self, platform: Platform, success: bool):
        """Handle authentication completion."""
        self._update_platform_status()
        
        if success:
            messagebox.showinfo("Success", f"Successfully logged in to {platform.value.title()}!")
        else:
            messagebox.showerror("Error", f"Failed to authenticate with {platform.value.title()}.")
    
    def _update_platform_status(self):
        """Update platform status indicators."""
        for platform, widgets in self.platform_widgets.items():
            is_configured = self.upload_manager.is_platform_configured(platform)
            is_authenticated = self.upload_manager.is_platform_authenticated(platform)
            
            if is_authenticated:
                widgets['status'].configure(text="●", foreground="green")
                widgets['auth_btn'].configure(text="Logout", state=tk.NORMAL)
            elif is_configured:
                widgets['status'].configure(text="○", foreground="orange")
                widgets['auth_btn'].configure(text="Login", state=tk.NORMAL)
            else:
                widgets['status'].configure(text="○", foreground="gray")
                widgets['auth_btn'].configure(state=tk.DISABLED)
    
    def _setup_callbacks(self):
        """Set up upload manager callbacks."""
        self.upload_manager.on_job_change(self._on_job_change)
        self.upload_manager.on_progress(self._on_progress)
    
    def _on_job_change(self, job: UploadJob):
        """Handle job status change."""
        self.after(0, lambda: self._update_job_in_tree(job))
    
    def _on_progress(self, job: UploadJob, progress: UploadProgress):
        """Handle progress update."""
        self.after(0, lambda: self._update_job_progress(job, progress))
    
    def _new_upload(self):
        """Open new upload dialog."""
        dialog = UploadJobDialog(self, self.upload_manager)
        self.wait_window(dialog)
        
        if dialog.result:
            self._refresh_jobs()
            messagebox.showinfo("Success", "Upload added to queue!")
    
    def _refresh_jobs(self):
        """Refresh job list."""
        # Clear tree
        for item in self.job_tree.get_children():
            self.job_tree.delete(item)
        
        # Get jobs based on filter
        filter_value = self.filter_var.get()
        jobs = self.upload_manager.get_all_jobs()
        
        status_map = {
            "Queued": [JobStatus.QUEUED, JobStatus.WAITING_SCHEDULE],
            "In Progress": [JobStatus.IN_PROGRESS, JobStatus.PAUSED],
            "Completed": [JobStatus.COMPLETED],
            "Failed": [JobStatus.FAILED, JobStatus.CANCELLED]
        }
        
        if filter_value != "All":
            allowed_statuses = status_map.get(filter_value, [])
            jobs = [j for j in jobs if j.status in allowed_statuses]
        
        # Sort by status and created time
        jobs.sort(key=lambda j: (
            0 if j.status == JobStatus.IN_PROGRESS else
            1 if j.status == JobStatus.QUEUED else
            2 if j.status == JobStatus.PAUSED else
            3,
            -j.created_at
        ))
        
        # Add to tree
        for job in jobs:
            self._add_job_to_tree(job)
        
        # Update statistics
        self._update_statistics()
    
    def _add_job_to_tree(self, job: UploadJob):
        """Add job to tree view."""
        platforms = ", ".join(p.value.title() for p in job.platforms)
        status = self._format_status(job)
        progress = self._format_progress(job)
        
        self.job_tree.insert(
            '',
            tk.END,
            iid=job.id,
            values=(job.metadata.title, platforms, status, progress)
        )
    
    def _update_job_in_tree(self, job: UploadJob):
        """Update job in tree view."""
        if not self.job_tree.exists(job.id):
            self._refresh_jobs()
            return
        
        platforms = ", ".join(p.value.title() for p in job.platforms)
        status = self._format_status(job)
        progress = self._format_progress(job)
        
        self.job_tree.item(
            job.id,
            values=(job.metadata.title, platforms, status, progress)
        )
        
        self._update_statistics()
    
    def _update_job_progress(self, job: UploadJob, progress: UploadProgress):
        """Update job progress in tree."""
        if not self.job_tree.exists(job.id):
            return
        
        progress_text = f"{progress.percent:.1f}% | {progress.speed_formatted}"
        
        values = list(self.job_tree.item(job.id)['values'])
        values[3] = progress_text
        self.job_tree.item(job.id, values=values)
    
    def _format_status(self, job: UploadJob) -> str:
        """Format job status for display."""
        status_icons = {
            JobStatus.QUEUED: "⏳ Queued",
            JobStatus.WAITING_SCHEDULE: "📅 Scheduled",
            JobStatus.IN_PROGRESS: "🔄 Uploading",
            JobStatus.COMPLETED: "✅ Completed",
            JobStatus.FAILED: "❌ Failed",
            JobStatus.CANCELLED: "🚫 Cancelled",
            JobStatus.PAUSED: "⏸ Paused"
        }
        return status_icons.get(job.status, job.status.name)
    
    def _format_progress(self, job: UploadJob) -> str:
        """Format job progress for display."""
        if job.status == JobStatus.COMPLETED:
            success_count = sum(1 for r in job.platform_results.values() if r.success)
            return f"{success_count}/{len(job.platforms)} succeeded"
        elif job.status == JobStatus.FAILED:
            return job.error_message or "Unknown error"
        elif job.progress:
            return f"{job.progress.percent:.1f}%"
        else:
            return "-"
    
    def _update_statistics(self):
        """Update statistics display."""
        stats = self.upload_manager.get_statistics()
        
        self.stats_labels['Total Jobs'].configure(text=str(stats['total_jobs']))
        self.stats_labels['Queued'].configure(text=str(stats['queued_jobs']))
        self.stats_labels['Completed'].configure(text=str(stats['completed_jobs']))
        self.stats_labels['Success Rate'].configure(text=f"{stats['success_rate']*100:.1f}%")
    
    def _show_context_menu(self, event):
        """Show context menu for selected job."""
        item = self.job_tree.identify_row(event.y)
        if item:
            self.job_tree.selection_set(item)
            self.context_menu.tk_popup(event.x_root, event.y_root)
    
    def _get_selected_job(self) -> Optional[UploadJob]:
        """Get currently selected job."""
        selection = self.job_tree.selection()
        if selection:
            return self.upload_manager.get_job(selection[0])
        return None
    
    def _view_job_details(self):
        """View details of selected job."""
        job = self._get_selected_job()
        if not job:
            return
        
        # Create details dialog
        dialog = tk.Toplevel(self)
        dialog.title(f"Job Details: {job.metadata.title}")
        dialog.geometry("500x400")
        dialog.transient(self)
        
        text = tk.Text(dialog, wrap=tk.WORD, padx=10, pady=10)
        text.pack(fill=tk.BOTH, expand=True)
        
        # Format details
        details = f"""Title: {job.metadata.title}
Status: {job.status.name}
Created: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(job.created_at))}
Platforms: {', '.join(p.value for p in job.platforms)}

Description:
{job.metadata.description}

Tags: {', '.join(job.metadata.tags)}
Privacy: {job.metadata.privacy}
Category: {job.metadata.category}

Results:
"""
        for platform, result in job.platform_results.items():
            if result.success:
                details += f"\n{platform}: ✅ Success\n  URL: {result.video_url}\n"
            else:
                details += f"\n{platform}: ❌ Failed\n  Error: {result.error_message}\n"
        
        if job.error_message:
            details += f"\nError: {job.error_message}"
        
        text.insert(tk.END, details)
        text.configure(state=tk.DISABLED)
    
    def _pause_selected(self):
        """Pause selected job."""
        job = self._get_selected_job()
        if job:
            self.upload_manager.pause_upload(job.id)
    
    def _resume_selected(self):
        """Resume selected job."""
        job = self._get_selected_job()
        if job:
            self.upload_manager.resume_upload(job.id)
    
    def _cancel_selected(self):
        """Cancel selected job."""
        job = self._get_selected_job()
        if job:
            if messagebox.askyesno("Confirm", "Are you sure you want to cancel this upload?"):
                self.upload_manager.cancel_upload(job.id)
    
    def _retry_selected(self):
        """Retry selected job."""
        job = self._get_selected_job()
        if job:
            self.upload_manager.retry_upload(job.id)
            self._refresh_jobs()
    
    def _on_close(self):
        """Handle window close."""
        self.upload_manager.stop()
        self.destroy()


def show_upload_window(parent, upload_manager: UploadManager = None):
    """
    Show the upload management window.
    
    Args:
        parent: Parent window
        upload_manager: Optional existing upload manager
        
    Returns:
        UploadWindow instance
    """
    return UploadWindow(parent, upload_manager)


if __name__ == "__main__":
    # Test the upload window
    root = tk.Tk()
    root.title("IDM Video Downloader")
    root.geometry("400x300")
    
    def open_upload():
        show_upload_window(root)
    
    ttk.Button(root, text="Open Upload Manager", command=open_upload).pack(pady=20)
    
    root.mainloop()
