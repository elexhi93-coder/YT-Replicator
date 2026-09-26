#!/usr/bin/env python3
"""
Video Uploader - Multi-Platform Video Upload Application

A standalone GUI application for uploading videos to multiple platforms:
- YouTube
- Dailymotion
- TikTok
- Facebook

Features:
- Drag & Drop support
- System Tray with notifications
- Metadata Templates
- Platform-specific descriptions
- Thumbnail Generator from video frames
- Advanced Settings for compliance (COPPA, AI disclosure, sponsorship)
- Cross-platform language settings
- Platform-specific advanced options:
  * YouTube: License type, public stats, localizations
  * Dailymotion: Geoblocking, hashtags, password protection, expiry
  * TikTok: Duet/Stitch/Comments control, brand content
  * Facebook: Secret videos, drafts, content categories

This is a dedicated application separate from IDM Video Downloader.

Changelog v2.1.0:
- Added Made for Kids (COPPA compliance) across all platforms
- Added AI/Synthetic content disclosure (YouTube, Dailymotion, TikTok)
- Added paid promotion/sponsorship disclosure (YouTube)
- Added multi-language support with audio language setting
- Added embedding control across platforms
- YouTube: Added localizations, recording date, location support
- Dailymotion: Added geoblocking, hashtags, password, expiry date
- TikTok: Added brand content toggles, AI content flag
- Facebook: Added secret videos, drafts, content categories
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import sys
import os
import logging
import json
import time
import threading
import subprocess
import tempfile
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field, asdict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from uploaders import (
    UploadManager,
    Platform,
    VideoMetadata,
    UploadJob,
    JobStatus,
    UploadProgress,
    UploadStatus,
    AuthManager,
    OAuthProvider
)

VERSION = "2.1.0"
APP_NAME = "Video Uploader"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Metadata Templates
# ============================================================================

@dataclass
class MetadataTemplate:
    """Template for reusable video metadata."""
    name: str
    title_prefix: str = ""
    title_suffix: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    category: str = ""
    privacy: str = "private"
    # Platform-specific descriptions
    youtube_description: str = ""
    dailymotion_description: str = ""
    tiktok_description: str = ""
    facebook_description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MetadataTemplate':
        return cls(**data)


class TemplateManager:
    """Manages metadata templates."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path or Path.home() / ".video_uploader_templates.json")
        self.templates: Dict[str, MetadataTemplate] = {}
        self._load_templates()
    
    def _load_templates(self):
        """Load templates from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for name, template_data in data.items():
                    self.templates[name] = MetadataTemplate.from_dict(template_data)
            except Exception as e:
                logger.error(f"Failed to load templates: {e}")
    
    def _save_templates(self):
        """Save templates to file."""
        try:
            data = {name: t.to_dict() for name, t in self.templates.items()}
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save templates: {e}")
    
    def add_template(self, template: MetadataTemplate):
        """Add or update a template."""
        self.templates[template.name] = template
        self._save_templates()
    
    def remove_template(self, name: str):
        """Remove a template."""
        if name in self.templates:
            del self.templates[name]
            self._save_templates()
    
    def get_template(self, name: str) -> Optional[MetadataTemplate]:
        """Get a template by name."""
        return self.templates.get(name)
    
    def list_templates(self) -> List[str]:
        """List all template names."""
        return list(self.templates.keys())


# ============================================================================
# Thumbnail Generator
# ============================================================================

class ThumbnailGenerator:
    """Generate thumbnails from video files using FFmpeg."""
    
    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()
    
    def _find_ffmpeg(self) -> Optional[str]:
        """Find FFmpeg executable."""
        # Check in local ffmpeg folder
        local_ffmpeg = Path(__file__).parent / "ffmpeg" / "bin" / "ffmpeg.exe"
        if local_ffmpeg.exists():
            return str(local_ffmpeg)
        
        # Check in PATH
        import shutil
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        
        return None
    
    def is_available(self) -> bool:
        """Check if FFmpeg is available."""
        return self.ffmpeg_path is not None
    
    def get_video_duration(self, video_path: str) -> float:
        """Get video duration in seconds."""
        if not self.ffmpeg_path:
            return 0.0
        
        try:
            ffprobe = self.ffmpeg_path.replace("ffmpeg", "ffprobe")
            if not os.path.exists(ffprobe):
                ffprobe = self.ffmpeg_path.replace("ffmpeg.exe", "ffprobe.exe")
            
            cmd = [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"Failed to get video duration: {e}")
            return 0.0
    
    def extract_frame(self, video_path: str, time_seconds: float, output_path: str) -> bool:
        """Extract a frame from video at specified time."""
        if not self.ffmpeg_path:
            return False
        
        try:
            cmd = [
                self.ffmpeg_path,
                "-y",  # Overwrite
                "-ss", str(time_seconds),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",  # High quality
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            return result.returncode == 0 and os.path.exists(output_path)
        except Exception as e:
            logger.error(f"Failed to extract frame: {e}")
            return False
    
    def generate_thumbnails(self, video_path: str, count: int = 5) -> List[str]:
        """Generate multiple thumbnail options from video."""
        if not self.ffmpeg_path:
            return []
        
        duration = self.get_video_duration(video_path)
        if duration <= 0:
            return []
        
        thumbnails = []
        temp_dir = tempfile.mkdtemp(prefix="video_uploader_thumbs_")
        
        # Generate frames at evenly spaced intervals
        for i in range(count):
            time_pos = (duration / (count + 1)) * (i + 1)
            output_path = os.path.join(temp_dir, f"thumb_{i:02d}.jpg")
            
            if self.extract_frame(video_path, time_pos, output_path):
                thumbnails.append(output_path)
        
        return thumbnails


# ============================================================================
# System Tray Support
# ============================================================================

class SystemTray:
    """System tray icon and notifications (Windows)."""
    
    def __init__(self, app: 'VideoUploaderApp'):
        self.app = app
        self.tray_icon = None
        self._running = False
        self._thread = None
        
        # Try to import pystray
        try:
            import pystray
            from PIL import Image
            self.pystray = pystray
            self.PIL_Image = Image
            self._available = True
        except ImportError:
            self._available = False
            logger.warning("System tray not available. Install: pip install pystray pillow")
    
    def is_available(self) -> bool:
        return self._available
    
    def start(self):
        """Start system tray icon."""
        if not self._available or self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_tray, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop system tray icon."""
        self._running = False
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except:
                pass
    
    def _create_icon_image(self):
        """Create tray icon image."""
        # Create a simple upload icon
        size = 64
        image = self.PIL_Image.new('RGBA', (size, size), (0, 0, 0, 0))
        
        try:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
            
            # Draw upload arrow
            center = size // 2
            draw.polygon([
                (center, 10),
                (center + 20, 30),
                (center + 10, 30),
                (center + 10, 50),
                (center - 10, 50),
                (center - 10, 30),
                (center - 20, 30),
            ], fill=(66, 133, 244))
            
        except ImportError:
            pass
        
        return image
    
    def _run_tray(self):
        """Run tray icon in background thread."""
        try:
            image = self._create_icon_image()
            
            menu = self.pystray.Menu(
                self.pystray.MenuItem("Show Window", self._show_window),
                self.pystray.MenuItem("New Upload", self._new_upload),
                self.pystray.Menu.SEPARATOR,
                self.pystray.MenuItem("Pause All", self._pause_all),
                self.pystray.MenuItem("Resume All", self._resume_all),
                self.pystray.Menu.SEPARATOR,
                self.pystray.MenuItem("Exit", self._exit_app),
            )
            
            self.tray_icon = self.pystray.Icon(
                APP_NAME,
                image,
                f"{APP_NAME} v{VERSION}",
                menu
            )
            
            self.tray_icon.run()
        except Exception as e:
            logger.error(f"System tray error: {e}")
    
    def _show_window(self):
        """Show main window."""
        self.app.root.after(0, self._do_show_window)
    
    def _do_show_window(self):
        self.app.root.deiconify()
        self.app.root.lift()
        self.app.root.focus_force()
    
    def _new_upload(self):
        """Open new upload dialog."""
        self.app.root.after(0, self.app._new_upload)
    
    def _pause_all(self):
        self.app.root.after(0, self.app._pause_all)
    
    def _resume_all(self):
        self.app.root.after(0, self.app._resume_all)
    
    def _exit_app(self):
        self.app.root.after(0, self.app._force_close)
    
    def notify(self, title: str, message: str):
        """Show system notification."""
        if self.tray_icon and self._running:
            try:
                self.tray_icon.notify(message, title)
            except Exception as e:
                logger.error(f"Notification error: {e}")


# ============================================================================
# Drag and Drop Support
# ============================================================================

class DragDropHandler:
    """Handle drag and drop for video files."""
    
    def __init__(self, widget: tk.Widget, callback: Callable[[List[str]], None]):
        self.widget = widget
        self.callback = callback
        self._setup_dnd()
    
    def _setup_dnd(self):
        """Set up drag and drop handling."""
        try:
            # Try tkinterdnd2 first
            from tkinterdnd2 import DND_FILES
            self.widget.drop_target_register(DND_FILES)
            self.widget.dnd_bind('<<Drop>>', self._on_drop_tkdnd)
            logger.info("Drag & Drop enabled (tkinterdnd2)")
        except ImportError:
            logger.warning("Drag & Drop not available. Install: pip install tkinterdnd2")
    
    def _on_drop_tkdnd(self, event):
        """Handle drop event from tkinterdnd2."""
        files = self._parse_drop_data(event.data)
        video_files = self._filter_video_files(files)
        if video_files:
            self.callback(video_files)
    
    def _parse_drop_data(self, data: str) -> List[str]:
        """Parse dropped file data."""
        files = []
        # Handle different formats
        if data.startswith('{'):
            # Windows format with braces for paths with spaces
            import re
            files = re.findall(r'\{([^}]+)\}', data)
            # Also get unbraced paths
            remaining = re.sub(r'\{[^}]+\}', '', data)
            files.extend(remaining.split())
        else:
            files = data.split()
        
        return [f.strip() for f in files if f.strip()]
    
    def _filter_video_files(self, files: List[str]) -> List[str]:
        """Filter to only video files."""
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v', '.3gp'}
        return [f for f in files if Path(f).suffix.lower() in video_extensions]


# ============================================================================
# Enhanced Dialogs
# ============================================================================

class TemplateDialog(tk.Toplevel):
    """Dialog for managing metadata templates."""
    
    def __init__(self, parent, template_manager: TemplateManager, template: Optional[MetadataTemplate] = None):
        super().__init__(parent)
        
        self.template_manager = template_manager
        self.editing_template = template
        self.result: Optional[MetadataTemplate] = None
        
        self.title("Edit Template" if template else "New Template")
        self.geometry("600x700")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        
        if template:
            self._load_template(template)
    
    def _create_widgets(self):
        """Create dialog widgets."""
        # Scrollable frame
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        main_frame = ttk.Frame(canvas, padding=15)
        
        main_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=main_frame, anchor="nw", width=560)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Template name
        ttk.Label(main_frame, text="Template Name *", font=('Arial', 10, 'bold')).pack(anchor=tk.W)
        self.name_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.name_var, width=50).pack(fill=tk.X, pady=(0, 15))
        
        # Title modifications
        title_frame = ttk.LabelFrame(main_frame, text="Title Modifications", padding=10)
        title_frame.pack(fill=tk.X, pady=(0, 10))
        
        row = ttk.Frame(title_frame)
        row.pack(fill=tk.X)
        
        ttk.Label(row, text="Prefix:").pack(side=tk.LEFT)
        self.title_prefix_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.title_prefix_var, width=20).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row, text="Suffix:").pack(side=tk.LEFT, padx=(20, 0))
        self.title_suffix_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.title_suffix_var, width=20).pack(side=tk.LEFT, padx=5)
        
        # Common metadata
        meta_frame = ttk.LabelFrame(main_frame, text="Common Metadata", padding=10)
        meta_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(meta_frame, text="Default Description:").pack(anchor=tk.W)
        self.description_text = tk.Text(meta_frame, height=4, wrap=tk.WORD)
        self.description_text.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(meta_frame, text="Tags (comma-separated):").pack(anchor=tk.W)
        self.tags_var = tk.StringVar()
        ttk.Entry(meta_frame, textvariable=self.tags_var).pack(fill=tk.X, pady=(0, 10))
        
        row2 = ttk.Frame(meta_frame)
        row2.pack(fill=tk.X)
        
        ttk.Label(row2, text="Category:").pack(side=tk.LEFT)
        self.category_var = tk.StringVar()
        categories = ["", "Entertainment", "Music", "Gaming", "Education", "Science & Technology",
                     "News & Politics", "Sports", "Comedy", "People & Blogs"]
        ttk.Combobox(row2, textvariable=self.category_var, values=categories, width=20).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row2, text="Privacy:").pack(side=tk.LEFT, padx=(20, 0))
        self.privacy_var = tk.StringVar(value="private")
        ttk.Combobox(row2, textvariable=self.privacy_var, values=["private", "unlisted", "public"], 
                    width=12, state="readonly").pack(side=tk.LEFT, padx=5)
        
        # Platform-specific descriptions
        platform_frame = ttk.LabelFrame(main_frame, text="Platform-Specific Descriptions (Optional)", padding=10)
        platform_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(platform_frame, text="Leave empty to use common description", 
                 foreground="gray").pack(anchor=tk.W, pady=(0, 10))
        
        self.platform_desc_texts = {}
        for platform in ["YouTube", "Dailymotion", "TikTok", "Facebook"]:
            ttk.Label(platform_frame, text=f"{platform}:").pack(anchor=tk.W)
            text = tk.Text(platform_frame, height=2, wrap=tk.WORD)
            text.pack(fill=tk.X, pady=(0, 5))
            self.platform_desc_texts[platform.lower()] = text
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="💾 Save Template", command=self._save).pack(side=tk.RIGHT)
    
    def _load_template(self, template: MetadataTemplate):
        """Load template data into form."""
        self.name_var.set(template.name)
        self.title_prefix_var.set(template.title_prefix)
        self.title_suffix_var.set(template.title_suffix)
        self.description_text.insert("1.0", template.description)
        self.tags_var.set(", ".join(template.tags))
        self.category_var.set(template.category)
        self.privacy_var.set(template.privacy)
        
        # Platform-specific
        if template.youtube_description:
            self.platform_desc_texts['youtube'].insert("1.0", template.youtube_description)
        if template.dailymotion_description:
            self.platform_desc_texts['dailymotion'].insert("1.0", template.dailymotion_description)
        if template.tiktok_description:
            self.platform_desc_texts['tiktok'].insert("1.0", template.tiktok_description)
        if template.facebook_description:
            self.platform_desc_texts['facebook'].insert("1.0", template.facebook_description)
    
    def _save(self):
        """Save template."""
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Error", "Template name is required.")
            return
        
        tags = [t.strip() for t in self.tags_var.get().split(',') if t.strip()]
        
        template = MetadataTemplate(
            name=name,
            title_prefix=self.title_prefix_var.get().strip(),
            title_suffix=self.title_suffix_var.get().strip(),
            description=self.description_text.get("1.0", tk.END).strip(),
            tags=tags,
            category=self.category_var.get(),
            privacy=self.privacy_var.get(),
            youtube_description=self.platform_desc_texts['youtube'].get("1.0", tk.END).strip(),
            dailymotion_description=self.platform_desc_texts['dailymotion'].get("1.0", tk.END).strip(),
            tiktok_description=self.platform_desc_texts['tiktok'].get("1.0", tk.END).strip(),
            facebook_description=self.platform_desc_texts['facebook'].get("1.0", tk.END).strip(),
        )
        
        self.template_manager.add_template(template)
        self.result = template
        self.destroy()


class ThumbnailSelectorDialog(tk.Toplevel):
    """Dialog for selecting thumbnail from video frames."""
    
    def __init__(self, parent, video_path: str, generator: ThumbnailGenerator):
        super().__init__(parent)
        
        self.video_path = video_path
        self.generator = generator
        self.result: Optional[str] = None
        self.thumbnails: List[str] = []
        self.thumbnail_labels: List[tk.Label] = []
        
        self.title("Select Thumbnail")
        self.geometry("700x400")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self._generate_thumbnails()
    
    def _create_widgets(self):
        """Create dialog widgets."""
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Click on a thumbnail to select it:", 
                 font=('Arial', 10)).pack(anchor=tk.W, pady=(0, 10))
        
        # Thumbnails container
        self.thumb_frame = ttk.Frame(main_frame)
        self.thumb_frame.pack(fill=tk.BOTH, expand=True)
        
        # Progress/status
        self.status_var = tk.StringVar(value="Generating thumbnails...")
        self.status_label = ttk.Label(main_frame, textvariable=self.status_var)
        self.status_label.pack(pady=10)
        
        # Custom time frame
        custom_frame = ttk.Frame(main_frame)
        custom_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(custom_frame, text="Or extract at specific time (seconds):").pack(side=tk.LEFT)
        self.time_var = tk.StringVar()
        ttk.Entry(custom_frame, textvariable=self.time_var, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(custom_frame, text="Extract", command=self._extract_custom).pack(side=tk.LEFT)
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Browse...", command=self._browse).pack(side=tk.RIGHT, padx=5)
    
    def _generate_thumbnails(self):
        """Generate thumbnails in background thread."""
        def generate():
            self.thumbnails = self.generator.generate_thumbnails(self.video_path, count=5)
            self.after(0, self._display_thumbnails)
        
        threading.Thread(target=generate, daemon=True).start()
    
    def _display_thumbnails(self):
        """Display generated thumbnails."""
        if not self.thumbnails:
            self.status_var.set("Failed to generate thumbnails. Try browsing for an image.")
            return
        
        self.status_var.set("Click to select:")
        
        try:
            from PIL import Image, ImageTk
            
            for i, thumb_path in enumerate(self.thumbnails):
                # Load and resize image
                img = Image.open(thumb_path)
                img.thumbnail((120, 80))
                photo = ImageTk.PhotoImage(img)
                
                # Create clickable label
                label = tk.Label(self.thumb_frame, image=photo, cursor="hand2",
                               relief=tk.RAISED, borderwidth=2)
                label.image = photo  # Keep reference
                label.grid(row=0, column=i, padx=5, pady=5)
                label.bind("<Button-1>", lambda e, p=thumb_path: self._select_thumbnail(p))
                
                self.thumbnail_labels.append(label)
                
        except ImportError:
            self.status_var.set("Install Pillow for thumbnail preview: pip install pillow")
    
    def _select_thumbnail(self, path: str):
        """Select a thumbnail."""
        self.result = path
        self.destroy()
    
    def _extract_custom(self):
        """Extract frame at custom time."""
        try:
            time_sec = float(self.time_var.get())
            temp_path = tempfile.mktemp(suffix=".jpg", prefix="thumb_custom_")
            
            if self.generator.extract_frame(self.video_path, time_sec, temp_path):
                self.result = temp_path
                self.destroy()
            else:
                messagebox.showerror("Error", "Failed to extract frame at specified time.")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number of seconds.")
    
    def _browse(self):
        """Browse for custom thumbnail."""
        filetypes = [
            ("Image files", "*.jpg *.jpeg *.png *.gif *.webp"),
            ("All files", "*.*")
        ]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self.result = path
            self.destroy()


class PlatformConfigDialog(tk.Toplevel):
    """Dialog for configuring platform OAuth credentials."""
    
    def __init__(self, parent, platform: Platform, current_config: Dict[str, str] = None):
        super().__init__(parent)
        
        self.platform = platform
        self.result = None
        
        self.title(f"Configure {platform.value.title()}")
        self.geometry("550x400")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 550) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 400) // 2
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
            wraplength=500,
            justify=tk.LEFT
        )
        instr_label.pack(fill=tk.X, pady=(0, 15))
        
        # Help link
        help_btn = ttk.Button(
            main_frame,
            text="📖 Open Setup Guide",
            command=self._open_help
        )
        help_btn.pack(anchor=tk.W, pady=(0, 15))
        
        # Client ID
        ttk.Label(main_frame, text="Client ID:").pack(anchor=tk.W)
        self.client_id_var = tk.StringVar(value=current_config.get('client_id', ''))
        client_id_entry = ttk.Entry(main_frame, textvariable=self.client_id_var, width=65)
        client_id_entry.pack(fill=tk.X, pady=(0, 10))
        
        # Client Secret
        ttk.Label(main_frame, text="Client Secret:").pack(anchor=tk.W)
        self.client_secret_var = tk.StringVar(value=current_config.get('client_secret', ''))
        self.client_secret_entry = ttk.Entry(main_frame, textvariable=self.client_secret_var, width=65, show='•')
        self.client_secret_entry.pack(fill=tk.X, pady=(0, 10))
        
        # Show/hide secret button
        self.show_secret = tk.BooleanVar(value=False)
        show_btn = ttk.Checkbutton(
            main_frame,
            text="Show secret",
            variable=self.show_secret,
            command=self._toggle_secret
        )
        show_btn.pack(anchor=tk.W, pady=(0, 10))
        
        # Platform-specific fields
        self._add_platform_fields(main_frame, current_config)
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.RIGHT)
    
    def _toggle_secret(self):
        """Toggle secret visibility."""
        self.client_secret_entry.configure(show='' if self.show_secret.get() else '•')
    
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
    
    def _open_help(self):
        """Open help documentation."""
        import webbrowser
        urls = {
            Platform.YOUTUBE: "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
            Platform.DAILYMOTION: "https://www.dailymotion.com/partner",
            Platform.TIKTOK: "https://developers.tiktok.com",
            Platform.FACEBOOK: "https://developers.facebook.com"
        }
        webbrowser.open(urls.get(self.platform, "https://google.com"))
    
    def _add_platform_fields(self, parent, current_config: Dict[str, str]):
        """Add platform-specific configuration fields."""
        if self.platform == Platform.FACEBOOK:
            ttk.Label(parent, text="Page ID (optional, for page uploads):").pack(anchor=tk.W)
            self.page_id_var = tk.StringVar(value=current_config.get('page_id', ''))
            ttk.Entry(parent, textvariable=self.page_id_var, width=65).pack(fill=tk.X, pady=(0, 10))
    
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


class NewUploadDialog(tk.Toplevel):
    """Enhanced dialog for creating a new upload job."""
    
    def __init__(self, parent, upload_manager: UploadManager, template_manager: TemplateManager,
                 thumbnail_generator: ThumbnailGenerator, initial_video: str = None):
        super().__init__(parent)
        
        self.upload_manager = upload_manager
        self.template_manager = template_manager
        self.thumbnail_generator = thumbnail_generator
        self.result: Optional[UploadJob] = None
        
        self.title("New Upload")
        self.geometry("700x850")
        self.resizable(True, True)
        self.minsize(600, 700)
        self.transient(parent)
        self.grab_set()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 700) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 850) // 2
        self.geometry(f"+{x}+{y}")
        
        self._create_widgets()
        
        # Load initial video if provided
        if initial_video:
            self.video_path_var.set(initial_video)
            self.title_var.set(Path(initial_video).stem)
    
    def _create_widgets(self):
        """Create dialog widgets."""
        # Main scrollable frame
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        main_frame = ttk.Frame(canvas, padding=20)
        
        main_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=main_frame, anchor="nw", width=660)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Template selection
        template_frame = ttk.Frame(main_frame)
        template_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(template_frame, text="📋 Template:").pack(side=tk.LEFT)
        self.template_var = tk.StringVar()
        templates = ["(None)"] + self.template_manager.list_templates()
        self.template_combo = ttk.Combobox(
            template_frame,
            textvariable=self.template_var,
            values=templates,
            width=25,
            state="readonly"
        )
        self.template_combo.pack(side=tk.LEFT, padx=5)
        self.template_combo.current(0)
        self.template_combo.bind("<<ComboboxSelected>>", self._on_template_selected)
        
        ttk.Button(template_frame, text="➕ New", command=self._new_template).pack(side=tk.LEFT, padx=2)
        ttk.Button(template_frame, text="✏️ Edit", command=self._edit_template).pack(side=tk.LEFT, padx=2)
        
        # Video file selection
        file_frame = ttk.LabelFrame(main_frame, text="📁 Video File", padding=10)
        file_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.video_path_var = tk.StringVar()
        path_entry = ttk.Entry(file_frame, textvariable=self.video_path_var, width=55)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(
            file_frame,
            text="Browse...",
            command=self._browse_video
        ).pack(side=tk.RIGHT)
        
        # Metadata section
        meta_frame = ttk.LabelFrame(main_frame, text="📝 Video Metadata", padding=10)
        meta_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Title
        ttk.Label(meta_frame, text="Title *").pack(anchor=tk.W)
        self.title_var = tk.StringVar()
        ttk.Entry(meta_frame, textvariable=self.title_var, width=65).pack(fill=tk.X, pady=(0, 10))
        
        # Description
        ttk.Label(meta_frame, text="Description (common)").pack(anchor=tk.W)
        desc_frame = ttk.Frame(meta_frame)
        desc_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.description_text = tk.Text(desc_frame, height=4, width=65, wrap=tk.WORD)
        desc_scroll = ttk.Scrollbar(desc_frame, orient="vertical", command=self.description_text.yview)
        self.description_text.configure(yscrollcommand=desc_scroll.set)
        self.description_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        desc_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Platform-specific descriptions toggle
        self.use_platform_desc_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            meta_frame,
            text="Use platform-specific descriptions",
            variable=self.use_platform_desc_var,
            command=self._toggle_platform_descriptions
        ).pack(anchor=tk.W, pady=(0, 5))
        
        self.platform_desc_frame = ttk.Frame(meta_frame)
        self.platform_desc_texts: Dict[str, tk.Text] = {}
        
        for platform in ["YouTube", "Dailymotion", "TikTok", "Facebook"]:
            row = ttk.Frame(self.platform_desc_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"{platform}:", width=12).pack(side=tk.LEFT)
            text = tk.Text(row, height=2, width=50, wrap=tk.WORD)
            text.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.platform_desc_texts[platform.lower()] = text
        
        # Tags
        ttk.Label(meta_frame, text="Tags (comma-separated)").pack(anchor=tk.W)
        self.tags_var = tk.StringVar()
        ttk.Entry(meta_frame, textvariable=self.tags_var, width=65).pack(fill=tk.X, pady=(0, 10))
        
        # Category and Privacy row
        row_frame = ttk.Frame(meta_frame)
        row_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Category
        cat_frame = ttk.Frame(row_frame)
        cat_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(cat_frame, text="Category").pack(anchor=tk.W)
        self.category_var = tk.StringVar()
        categories = [
            "Entertainment", "Music", "Gaming", "Education", "Science & Technology",
            "News & Politics", "Sports", "Comedy", "People & Blogs", "Film & Animation",
            "Howto & Style", "Travel & Events", "Pets & Animals", "Autos & Vehicles"
        ]
        ttk.Combobox(
            cat_frame,
            textvariable=self.category_var,
            values=categories,
            width=25
        ).pack(anchor=tk.W)
        
        # Privacy
        priv_frame = ttk.Frame(row_frame)
        priv_frame.pack(side=tk.RIGHT, padx=(20, 0))
        ttk.Label(priv_frame, text="Privacy").pack(anchor=tk.W)
        self.privacy_var = tk.StringVar(value="private")
        privacy_combo = ttk.Combobox(
            priv_frame,
            textvariable=self.privacy_var,
            values=["private", "unlisted", "public"],
            width=12,
            state="readonly"
        )
        privacy_combo.pack(anchor=tk.W)
        
        # Thumbnail
        thumb_frame = ttk.LabelFrame(main_frame, text="🖼️ Thumbnail", padding=10)
        thumb_frame.pack(fill=tk.X, pady=(0, 15))
        
        thumb_row = ttk.Frame(thumb_frame)
        thumb_row.pack(fill=tk.X)
        self.thumbnail_var = tk.StringVar()
        ttk.Entry(thumb_row, textvariable=self.thumbnail_var, width=45).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(thumb_row, text="Browse...", command=self._browse_thumbnail).pack(side=tk.LEFT, padx=2)
        ttk.Button(thumb_row, text="🎬 From Video", command=self._generate_thumbnail).pack(side=tk.LEFT, padx=2)
        
        # Platforms section
        platform_frame = ttk.LabelFrame(main_frame, text="🌐 Upload Platforms", padding=10)
        platform_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.platform_vars: Dict[Platform, tk.BooleanVar] = {}
        
        for platform in Platform:
            frame = ttk.Frame(platform_frame)
            frame.pack(fill=tk.X, pady=3)
            
            var = tk.BooleanVar(value=False)
            self.platform_vars[platform] = var
            
            is_configured = self.upload_manager.is_platform_configured(platform)
            is_authenticated = self.upload_manager.is_platform_authenticated(platform)
            
            cb = ttk.Checkbutton(
                frame,
                text=f"  {platform.value.title()}",
                variable=var,
                state=tk.NORMAL if is_authenticated else tk.DISABLED
            )
            cb.pack(side=tk.LEFT)
            
            if is_authenticated:
                status = "✅ Ready"
                color = "green"
            elif is_configured:
                status = "⚠️ Not logged in"
                color = "orange"
            else:
                status = "❌ Not configured"
                color = "gray"
            
            status_label = ttk.Label(frame, text=status, foreground=color)
            status_label.pack(side=tk.RIGHT)
        
        # Schedule section
        schedule_frame = ttk.LabelFrame(main_frame, text="📅 Scheduling (Optional)", padding=10)
        schedule_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.schedule_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            schedule_frame,
            text="Schedule upload for later",
            variable=self.schedule_var,
            command=self._toggle_schedule
        ).pack(anchor=tk.W)
        
        self.schedule_datetime_frame = ttk.Frame(schedule_frame)
        
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
        
        # === Advanced Settings Section ===
        advanced_frame = ttk.LabelFrame(main_frame, text="⚙️ Advanced Settings", padding=10)
        advanced_frame.pack(fill=tk.X, pady=(0, 15))
        
        # --- Compliance Settings (Cross-platform) ---
        compliance_frame = ttk.Frame(advanced_frame)
        compliance_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(compliance_frame, text="Compliance:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        
        # Made for Kids
        self.made_for_kids_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            compliance_frame,
            text="Made for Kids (COPPA compliance - applies to all platforms)",
            variable=self.made_for_kids_var
        ).pack(anchor=tk.W, padx=(10, 0))
        
        # AI Content Disclosure
        self.contains_ai_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            compliance_frame,
            text="Contains AI-generated/synthetic content",
            variable=self.contains_ai_var
        ).pack(anchor=tk.W, padx=(10, 0))
        
        # Paid Promotion
        self.paid_promotion_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            compliance_frame,
            text="Contains paid promotion/sponsorship",
            variable=self.paid_promotion_var
        ).pack(anchor=tk.W, padx=(10, 0))
        
        # Embedding
        self.allow_embedding_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            compliance_frame,
            text="Allow embedding on other websites",
            variable=self.allow_embedding_var
        ).pack(anchor=tk.W, padx=(10, 0))
        
        # --- Language Settings ---
        lang_frame = ttk.Frame(advanced_frame)
        lang_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(lang_frame, text="Language:", font=('Arial', 9, 'bold')).pack(anchor=tk.W)
        
        lang_row = ttk.Frame(lang_frame)
        lang_row.pack(fill=tk.X, padx=(10, 0))
        
        ttk.Label(lang_row, text="Video Language:").pack(side=tk.LEFT)
        self.language_var = tk.StringVar(value="en")
        languages = ["en", "es", "fr", "de", "it", "pt", "ru", "ja", "ko", "zh", "ar", "hi"]
        ttk.Combobox(lang_row, textvariable=self.language_var, values=languages, width=8).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(lang_row, text="Audio Language:").pack(side=tk.LEFT, padx=(15, 0))
        self.audio_language_var = tk.StringVar(value="en")
        ttk.Combobox(lang_row, textvariable=self.audio_language_var, values=languages, width=8).pack(side=tk.LEFT, padx=5)
        
        # --- Platform-Specific Settings Toggle ---
        self.show_platform_settings_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            advanced_frame,
            text="Show platform-specific advanced settings",
            variable=self.show_platform_settings_var,
            command=self._toggle_platform_settings
        ).pack(anchor=tk.W, pady=(5, 0))
        
        # Platform settings container (hidden by default)
        self.platform_settings_frame = ttk.Frame(advanced_frame)
        
        # YouTube Settings
        yt_frame = ttk.LabelFrame(self.platform_settings_frame, text="YouTube", padding=5)
        yt_frame.pack(fill=tk.X, pady=5)
        
        self.yt_license_var = tk.StringVar(value="youtube")
        yt_row1 = ttk.Frame(yt_frame)
        yt_row1.pack(fill=tk.X)
        ttk.Label(yt_row1, text="License:").pack(side=tk.LEFT)
        ttk.Combobox(yt_row1, textvariable=self.yt_license_var, 
                    values=["youtube", "creativeCommon"], width=15, state="readonly").pack(side=tk.LEFT, padx=5)
        
        self.yt_public_stats_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(yt_row1, text="Show public stats", variable=self.yt_public_stats_var).pack(side=tk.LEFT, padx=15)
        
        # Dailymotion Settings
        dm_frame = ttk.LabelFrame(self.platform_settings_frame, text="Dailymotion", padding=5)
        dm_frame.pack(fill=tk.X, pady=5)
        
        dm_row1 = ttk.Frame(dm_frame)
        dm_row1.pack(fill=tk.X)
        
        ttk.Label(dm_row1, text="Country:").pack(side=tk.LEFT)
        self.dm_country_var = tk.StringVar()
        ttk.Entry(dm_row1, textvariable=self.dm_country_var, width=5).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(dm_row1, text="Hashtags:").pack(side=tk.LEFT, padx=(15, 0))
        self.dm_hashtags_var = tk.StringVar()
        ttk.Entry(dm_row1, textvariable=self.dm_hashtags_var, width=25).pack(side=tk.LEFT, padx=5)
        
        dm_row2 = ttk.Frame(dm_frame)
        dm_row2.pack(fill=tk.X, pady=(5, 0))
        
        self.dm_explicit_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dm_row2, text="Explicit content", variable=self.dm_explicit_var).pack(side=tk.LEFT)
        
        ttk.Label(dm_row2, text="Password:").pack(side=tk.LEFT, padx=(15, 0))
        self.dm_password_var = tk.StringVar()
        ttk.Entry(dm_row2, textvariable=self.dm_password_var, width=15, show='•').pack(side=tk.LEFT, padx=5)
        
        # TikTok Settings
        tt_frame = ttk.LabelFrame(self.platform_settings_frame, text="TikTok", padding=5)
        tt_frame.pack(fill=tk.X, pady=5)
        
        tt_row = ttk.Frame(tt_frame)
        tt_row.pack(fill=tk.X)
        
        self.tt_disable_duet_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tt_row, text="Disable Duet", variable=self.tt_disable_duet_var).pack(side=tk.LEFT)
        
        self.tt_disable_stitch_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tt_row, text="Disable Stitch", variable=self.tt_disable_stitch_var).pack(side=tk.LEFT, padx=10)
        
        self.tt_disable_comments_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tt_row, text="Disable Comments", variable=self.tt_disable_comments_var).pack(side=tk.LEFT, padx=10)
        
        # Facebook Settings
        fb_frame = ttk.LabelFrame(self.platform_settings_frame, text="Facebook", padding=5)
        fb_frame.pack(fill=tk.X, pady=5)
        
        fb_row = ttk.Frame(fb_frame)
        fb_row.pack(fill=tk.X)
        
        self.fb_secret_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(fb_row, text="Secret video (unlisted)", variable=self.fb_secret_var).pack(side=tk.LEFT)
        
        self.fb_unpublished_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(fb_row, text="Save as draft", variable=self.fb_unpublished_var).pack(side=tk.LEFT, padx=15)
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))
        
        ttk.Button(btn_frame, text="Cancel", command=self._cancel).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="📤 Add to Queue", command=self._add_upload).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="💾 Save as Template", command=self._save_as_template).pack(side=tk.LEFT)
    
    def _on_template_selected(self, event=None):
        """Apply selected template."""
        template_name = self.template_var.get()
        if template_name == "(None)":
            return
        
        template = self.template_manager.get_template(template_name)
        if not template:
            return
        
        # Apply template
        current_title = self.title_var.get()
        if current_title:
            new_title = f"{template.title_prefix}{current_title}{template.title_suffix}"
            self.title_var.set(new_title.strip())
        
        if template.description:
            self.description_text.delete("1.0", tk.END)
            self.description_text.insert("1.0", template.description)
        
        if template.tags:
            self.tags_var.set(", ".join(template.tags))
        
        if template.category:
            self.category_var.set(template.category)
        
        self.privacy_var.set(template.privacy)
        
        # Platform-specific descriptions
        has_platform_desc = any([
            template.youtube_description,
            template.dailymotion_description,
            template.tiktok_description,
            template.facebook_description
        ])
        
        if has_platform_desc:
            self.use_platform_desc_var.set(True)
            self._toggle_platform_descriptions()
            
            if template.youtube_description:
                self.platform_desc_texts['youtube'].delete("1.0", tk.END)
                self.platform_desc_texts['youtube'].insert("1.0", template.youtube_description)
            if template.dailymotion_description:
                self.platform_desc_texts['dailymotion'].delete("1.0", tk.END)
                self.platform_desc_texts['dailymotion'].insert("1.0", template.dailymotion_description)
            if template.tiktok_description:
                self.platform_desc_texts['tiktok'].delete("1.0", tk.END)
                self.platform_desc_texts['tiktok'].insert("1.0", template.tiktok_description)
            if template.facebook_description:
                self.platform_desc_texts['facebook'].delete("1.0", tk.END)
                self.platform_desc_texts['facebook'].insert("1.0", template.facebook_description)
    
    def _new_template(self):
        """Create new template."""
        dialog = TemplateDialog(self, self.template_manager)
        self.wait_window(dialog)
        
        if dialog.result:
            # Refresh template list
            templates = ["(None)"] + self.template_manager.list_templates()
            self.template_combo['values'] = templates
    
    def _edit_template(self):
        """Edit selected template."""
        template_name = self.template_var.get()
        if template_name == "(None)":
            messagebox.showinfo("Info", "Please select a template to edit.")
            return
        
        template = self.template_manager.get_template(template_name)
        if template:
            dialog = TemplateDialog(self, self.template_manager, template)
            self.wait_window(dialog)
    
    def _toggle_platform_descriptions(self):
        """Toggle platform-specific description fields."""
        if self.use_platform_desc_var.get():
            self.platform_desc_frame.pack(fill=tk.X, pady=(5, 0))
        else:
            self.platform_desc_frame.pack_forget()
    
    def _toggle_platform_settings(self):
        """Toggle platform-specific advanced settings visibility."""
        if self.show_platform_settings_var.get():
            self.platform_settings_frame.pack(fill=tk.X, pady=(10, 0))
        else:
            self.platform_settings_frame.pack_forget()
    
    def _generate_thumbnail(self):
        """Open thumbnail selector dialog."""
        video_path = self.video_path_var.get().strip()
        if not video_path or not os.path.exists(video_path):
            messagebox.showerror("Error", "Please select a video file first.")
            return
        
        if not self.thumbnail_generator.is_available():
            messagebox.showerror("Error", "FFmpeg is required for thumbnail generation.\nPlease install FFmpeg or place it in the ffmpeg/bin folder.")
            return
        
        dialog = ThumbnailSelectorDialog(self, video_path, self.thumbnail_generator)
        self.wait_window(dialog)
        
        if dialog.result:
            self.thumbnail_var.set(dialog.result)
    
    def _save_as_template(self):
        """Save current settings as template."""
        tags = [t.strip() for t in self.tags_var.get().split(',') if t.strip()]
        
        template = MetadataTemplate(
            name="",  # Will be set in dialog
            description=self.description_text.get("1.0", tk.END).strip(),
            tags=tags,
            category=self.category_var.get(),
            privacy=self.privacy_var.get(),
        )
        
        if self.use_platform_desc_var.get():
            template.youtube_description = self.platform_desc_texts['youtube'].get("1.0", tk.END).strip()
            template.dailymotion_description = self.platform_desc_texts['dailymotion'].get("1.0", tk.END).strip()
            template.tiktok_description = self.platform_desc_texts['tiktok'].get("1.0", tk.END).strip()
            template.facebook_description = self.platform_desc_texts['facebook'].get("1.0", tk.END).strip()
        
        dialog = TemplateDialog(self, self.template_manager, template)
        self.wait_window(dialog)
        
        if dialog.result:
            templates = ["(None)"] + self.template_manager.list_templates()
            self.template_combo['values'] = templates
            messagebox.showinfo("Success", f"Template '{dialog.result.name}' saved!")
    
    def _cancel(self):
        """Cancel and close."""
        self.unbind_all("<MouseWheel>")
        self.destroy()
    
    def _browse_video(self):
        """Browse for video file."""
        filetypes = [
            ("Video files", "*.mp4 *.avi *.mov *.mkv *.webm *.flv *.wmv *.m4v *.3gp"),
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
            ("Image files", "*.jpg *.jpeg *.png *.gif *.webp"),
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
        
        # Get description (common or platform-specific)
        description = self.description_text.get("1.0", tk.END).strip()
        
        # Build platform-specific descriptions dict
        platform_descriptions = {}
        if self.use_platform_desc_var.get():
            for platform_name, text_widget in self.platform_desc_texts.items():
                desc = text_widget.get("1.0", tk.END).strip()
                if desc:
                    platform_descriptions[platform_name] = desc
        
        metadata = VideoMetadata(
            title=title,
            description=description,
            tags=tags,
            category=self.category_var.get(),
            privacy=self.privacy_var.get(),
            thumbnail_path=self.thumbnail_var.get() or None,
            # Cross-platform compliance fields
            language=self.language_var.get() if hasattr(self, 'language_var') else 'en',
            audio_language=self.audio_language_var.get() if hasattr(self, 'audio_language_var') else 'en',
            made_for_kids=self.made_for_kids_var.get() if hasattr(self, 'made_for_kids_var') else False,
            contains_ai_content=self.contains_ai_var.get() if hasattr(self, 'contains_ai_var') else False,
            has_paid_promotion=self.paid_promotion_var.get() if hasattr(self, 'paid_promotion_var') else False,
            allow_embedding=self.allow_embedding_var.get() if hasattr(self, 'allow_embedding_var') else True
        )
        
        # Build platform-specific settings
        # YouTube settings
        if hasattr(self, 'yt_license_var'):
            metadata.youtube_settings = {
                'license': self.yt_license_var.get(),
                'publicStatsViewable': self.yt_public_stats_var.get()
            }
        
        # Dailymotion settings
        if hasattr(self, 'dm_country_var'):
            dm_settings = {}
            if self.dm_country_var.get():
                dm_settings['country'] = self.dm_country_var.get()
            if self.dm_hashtags_var.get():
                dm_settings['hashtags'] = [h.strip() for h in self.dm_hashtags_var.get().split(',') if h.strip()]
            if self.dm_explicit_var.get():
                dm_settings['explicit'] = True
            if self.dm_password_var.get():
                dm_settings['password'] = self.dm_password_var.get()
            if dm_settings:
                metadata.dailymotion_settings = dm_settings
        
        # TikTok settings
        if hasattr(self, 'tt_disable_duet_var'):
            metadata.tiktok_settings = {
                'disable_duet': self.tt_disable_duet_var.get(),
                'disable_stitch': self.tt_disable_stitch_var.get(),
                'disable_comment': self.tt_disable_comments_var.get()
            }
        
        # Facebook settings
        if hasattr(self, 'fb_secret_var'):
            fb_settings = {}
            if self.fb_secret_var.get():
                fb_settings['secret'] = True
            if self.fb_unpublished_var.get():
                fb_settings['unpublished'] = True
            if fb_settings:
                metadata.facebook_settings = fb_settings
        
        # Store platform-specific descriptions in extra_data
        if platform_descriptions:
            metadata.extra_data = {'platform_descriptions': platform_descriptions}
        
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
            self.unbind_all("<MouseWheel>")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add upload: {e}")


# ============================================================================
# Main Application
# ============================================================================

class VideoUploaderApp:
    """Main Video Uploader Application with enhanced features."""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.geometry("1100x750")
        self.root.minsize(900, 650)
        
        # Set app icon (if available)
        try:
            icon_path = Path(__file__).parent / "assets" / "upload_icon.ico"
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except:
            pass
        
        # Initialize managers
        persistence_path = Path.home() / ".video_uploader_queue.json"
        self.upload_manager = UploadManager(persistence_path=str(persistence_path))
        self.template_manager = TemplateManager()
        self.thumbnail_generator = ThumbnailGenerator()
        
        # Platform configurations
        self._platform_configs: Dict[Platform, Dict[str, str]] = {}
        self._load_platform_configs()
        
        # Create UI
        self._create_widgets()
        self._setup_callbacks()
        self._setup_drag_drop()
        
        # Start upload manager
        self.upload_manager.start()
        
        # System tray
        self.system_tray = SystemTray(self)
        if self.system_tray.is_available():
            self.system_tray.start()
        
        # Initial refresh
        self._refresh_jobs()
        self._update_statistics()
        
        # Handle window close and minimize
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Unmap>", self._on_minimize)
        
        logger.info(f"{APP_NAME} v{VERSION} started")
        self._log(f"🚀 {APP_NAME} v{VERSION} started")
        
        # Show feature status
        features = []
        if self.thumbnail_generator.is_available():
            features.append("Thumbnail Generator")
        if self.system_tray.is_available():
            features.append("System Tray")
        if features:
            self._log(f"✅ Features: {', '.join(features)}")
    
    def _setup_drag_drop(self):
        """Set up drag and drop handling."""
        try:
            self.dnd_handler = DragDropHandler(self.root, self._on_files_dropped)
            self._log("📥 Drag & Drop enabled")
        except Exception as e:
            logger.warning(f"Drag & Drop setup failed: {e}")
    
    def _on_files_dropped(self, files: List[str]):
        """Handle dropped video files."""
        if not files:
            return
        
        self._log(f"📥 Dropped {len(files)} file(s)")
        
        # Open upload dialog for first file
        self._new_upload(initial_video=files[0])
    
    def _on_minimize(self, event=None):
        """Handle window minimize - go to system tray."""
        if self.system_tray.is_available() and self.root.state() == 'iconic':
            self.root.withdraw()
            self.system_tray.notify(APP_NAME, "Running in background. Click tray icon to restore.")
    
    def _create_widgets(self):
        """Create main window widgets."""
        # Style
        style = ttk.Style()
        style.configure("Header.TLabel", font=('Arial', 12, 'bold'))
        style.configure("Status.TLabel", font=('Arial', 9))
        style.configure("DropZone.TFrame", background='#e8f4f8')
        
        # Main container
        main_container = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel - Platforms & Stats
        left_panel = ttk.Frame(main_container, width=300)
        main_container.add(left_panel, weight=1)
        
        # App header
        header_frame = ttk.Frame(left_panel)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(
            header_frame,
            text=f"📤 {APP_NAME}",
            style="Header.TLabel"
        ).pack(side=tk.LEFT)
        
        ttk.Label(
            header_frame,
            text=f"v{VERSION}",
            foreground="gray"
        ).pack(side=tk.RIGHT)
        
        # Drop zone hint
        drop_frame = ttk.Frame(left_panel)
        drop_frame.pack(fill=tk.X, pady=(0, 10))
        
        drop_label = ttk.Label(
            drop_frame,
            text="📥 Drag & Drop video files here",
            foreground="gray",
            font=('Arial', 9, 'italic')
        )
        drop_label.pack()
        
        # Platform configuration
        platform_frame = ttk.LabelFrame(left_panel, text="Platforms", padding=10)
        platform_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.platform_widgets: Dict[Platform, Dict[str, Any]] = {}
        
        for platform in Platform:
            frame = ttk.Frame(platform_frame)
            frame.pack(fill=tk.X, pady=4)
            
            # Platform icon and name
            name_frame = ttk.Frame(frame)
            name_frame.pack(side=tk.LEFT)
            
            icon = self._get_platform_icon(platform)
            ttk.Label(name_frame, text=f"{icon} {platform.value.title()}", width=14).pack(side=tk.LEFT)
            
            # Status indicator
            status_label = ttk.Label(frame, text="○", foreground="gray", width=3)
            status_label.pack(side=tk.LEFT)
            
            # Buttons frame
            btn_frame = ttk.Frame(frame)
            btn_frame.pack(side=tk.RIGHT)
            
            # Config button
            config_btn = ttk.Button(
                btn_frame,
                text="⚙️",
                width=3,
                command=lambda p=platform: self._configure_platform(p)
            )
            config_btn.pack(side=tk.LEFT, padx=1)
            
            # Auth button
            auth_btn = ttk.Button(
                btn_frame,
                text="🔑",
                width=3,
                command=lambda p=platform: self._authenticate_platform(p),
                state=tk.DISABLED
            )
            auth_btn.pack(side=tk.LEFT, padx=1)
            
            self.platform_widgets[platform] = {
                'status': status_label,
                'config_btn': config_btn,
                'auth_btn': auth_btn
            }
        
        self._update_platform_status()
        
        # Templates section
        template_frame = ttk.LabelFrame(left_panel, text="📋 Templates", padding=10)
        template_frame.pack(fill=tk.X, pady=(0, 10))
        
        template_btn_frame = ttk.Frame(template_frame)
        template_btn_frame.pack(fill=tk.X)
        
        ttk.Button(template_btn_frame, text="➕ New Template", 
                  command=self._new_template).pack(side=tk.LEFT, padx=2)
        ttk.Button(template_btn_frame, text="📂 Manage", 
                  command=self._manage_templates).pack(side=tk.LEFT, padx=2)
        
        template_count = len(self.template_manager.list_templates())
        self.template_count_label = ttk.Label(template_frame, text=f"{template_count} templates saved", 
                                              foreground="gray")
        self.template_count_label.pack(pady=(5, 0))
        
        # Statistics
        stats_frame = ttk.LabelFrame(left_panel, text="Statistics", padding=10)
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.stats_labels: Dict[str, ttk.Label] = {}
        stats = [
            ('total', 'Total Jobs'),
            ('queued', 'Queued'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('success_rate', 'Success Rate')
        ]
        
        for key, label in stats:
            row = ttk.Frame(stats_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"{label}:").pack(side=tk.LEFT)
            value_label = ttk.Label(row, text="0", foreground="blue")
            value_label.pack(side=tk.RIGHT)
            self.stats_labels[key] = value_label
        
        # Log section
        log_frame = ttk.LabelFrame(left_panel, text="Activity Log", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, height=10, width=30, wrap=tk.WORD, state=tk.DISABLED)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
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
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        # Batch actions
        ttk.Button(
            toolbar,
            text="⏸ Pause All",
            command=self._pause_all
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            toolbar,
            text="▶ Resume All",
            command=self._resume_all
        ).pack(side=tk.LEFT, padx=2)
        
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
        list_frame = ttk.LabelFrame(right_panel, text="Upload Queue (drag & drop videos here)", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # Treeview with columns
        columns = ('title', 'platforms', 'status', 'progress', 'created')
        self.job_tree = ttk.Treeview(list_frame, columns=columns, show='headings', selectmode='extended')
        
        self.job_tree.heading('title', text='Title', anchor=tk.W)
        self.job_tree.heading('platforms', text='Platforms')
        self.job_tree.heading('status', text='Status')
        self.job_tree.heading('progress', text='Progress')
        self.job_tree.heading('created', text='Created')
        
        self.job_tree.column('title', width=250, anchor=tk.W)
        self.job_tree.column('platforms', width=120)
        self.job_tree.column('status', width=100)
        self.job_tree.column('progress', width=120)
        self.job_tree.column('created', width=130)
        
        # Scrollbars
        y_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.job_tree.yview)
        x_scroll = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.job_tree.xview)
        self.job_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        
        self.job_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Job actions toolbar
        actions_frame = ttk.Frame(right_panel)
        actions_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(actions_frame, text="📋 Details", command=self._view_job_details).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions_frame, text="⏸ Pause", command=self._pause_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions_frame, text="▶ Resume", command=self._resume_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions_frame, text="🔄 Retry", command=self._retry_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(actions_frame, text="❌ Cancel", command=self._cancel_selected).pack(side=tk.LEFT, padx=2)
        
        # Context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="📋 View Details", command=self._view_job_details)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="⏸ Pause", command=self._pause_selected)
        self.context_menu.add_command(label="▶ Resume", command=self._resume_selected)
        self.context_menu.add_command(label="🔄 Retry", command=self._retry_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ Cancel", command=self._cancel_selected)
        
        self.job_tree.bind("<Button-3>", self._show_context_menu)
        self.job_tree.bind("<Double-1>", lambda e: self._view_job_details())
    
    def _get_platform_icon(self, platform: Platform) -> str:
        """Get emoji icon for platform."""
        icons = {
            Platform.YOUTUBE: "▶️",
            Platform.DAILYMOTION: "📺",
            Platform.TIKTOK: "🎵",
            Platform.FACEBOOK: "📘"
        }
        return icons.get(platform, "🌐")
    
    def _load_platform_configs(self):
        """Load saved platform configurations."""
        config_path = Path.home() / ".video_uploader_configs.json"
        if config_path.exists():
            try:
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
                        
                self._log(f"Loaded {len(self._platform_configs)} platform configurations")
            except Exception as e:
                logger.error(f"Failed to load platform configs: {e}")
    
    def _save_platform_configs(self):
        """Save platform configurations."""
        config_path = Path.home() / ".video_uploader_configs.json"
        try:
            data = {
                platform.value: config
                for platform, config in self._platform_configs.items()
            }
            with open(config_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save platform configs: {e}")
    
    def _log(self, message: str):
        """Add message to activity log."""
        timestamp = time.strftime("%H:%M:%S")
        
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def _new_template(self):
        """Create new template."""
        dialog = TemplateDialog(self.root, self.template_manager)
        self.root.wait_window(dialog)
        
        if dialog.result:
            count = len(self.template_manager.list_templates())
            self.template_count_label.configure(text=f"{count} templates saved")
            self._log(f"📋 Template '{dialog.result.name}' created")
    
    def _manage_templates(self):
        """Open template management dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Manage Templates")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        
        # Template list
        list_frame = ttk.Frame(dialog, padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        listbox = tk.Listbox(list_frame, selectmode=tk.SINGLE)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        for name in self.template_manager.list_templates():
            listbox.insert(tk.END, name)
        
        # Buttons
        btn_frame = ttk.Frame(dialog, padding=10)
        btn_frame.pack(fill=tk.X)
        
        def edit_selected():
            selection = listbox.curselection()
            if selection:
                name = listbox.get(selection[0])
                template = self.template_manager.get_template(name)
                if template:
                    edit_dialog = TemplateDialog(dialog, self.template_manager, template)
                    dialog.wait_window(edit_dialog)
        
        def delete_selected():
            selection = listbox.curselection()
            if selection:
                name = listbox.get(selection[0])
                if messagebox.askyesno("Confirm", f"Delete template '{name}'?"):
                    self.template_manager.remove_template(name)
                    listbox.delete(selection[0])
                    count = len(self.template_manager.list_templates())
                    self.template_count_label.configure(text=f"{count} templates saved")
        
        ttk.Button(btn_frame, text="Edit", command=edit_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Delete", command=delete_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
    
    def _configure_platform(self, platform: Platform):
        """Open platform configuration dialog."""
        current_config = self._platform_configs.get(platform, {})
        
        dialog = PlatformConfigDialog(self.root, platform, current_config)
        self.root.wait_window(dialog)
        
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
            self._log(f"✅ {platform.value.title()} configured")
            messagebox.showinfo("Success", f"{platform.value.title()} configured successfully!\n\nClick the 🔑 button to log in.")
    
    def _authenticate_platform(self, platform: Platform):
        """Start OAuth flow for a platform."""
        def auth_callback(success: bool):
            self.root.after(0, lambda: self._on_auth_complete(platform, success))
        
        self._log(f"🔐 Authenticating with {platform.value.title()}...")
        self.upload_manager.authenticate_platform(platform, auth_callback)
        
        # Update UI to show authenticating
        widgets = self.platform_widgets[platform]
        widgets['auth_btn'].configure(state=tk.DISABLED)
        widgets['status'].configure(text="⋯", foreground="blue")
    
    def _on_auth_complete(self, platform: Platform, success: bool):
        """Handle authentication completion."""
        self._update_platform_status()
        
        if success:
            self._log(f"✅ Logged in to {platform.value.title()}")
            messagebox.showinfo("Success", f"Successfully logged in to {platform.value.title()}!")
            
            # System tray notification
            if self.system_tray.is_available():
                self.system_tray.notify("Login Successful", f"Logged in to {platform.value.title()}")
        else:
            self._log(f"❌ Login failed for {platform.value.title()}")
            messagebox.showerror("Error", f"Failed to authenticate with {platform.value.title()}.")
    
    def _update_platform_status(self):
        """Update platform status indicators."""
        for platform, widgets in self.platform_widgets.items():
            is_configured = self.upload_manager.is_platform_configured(platform)
            is_authenticated = self.upload_manager.is_platform_authenticated(platform)
            
            if is_authenticated:
                widgets['status'].configure(text="●", foreground="green")
                widgets['auth_btn'].configure(state=tk.NORMAL)
            elif is_configured:
                widgets['status'].configure(text="○", foreground="orange")
                widgets['auth_btn'].configure(state=tk.NORMAL)
            else:
                widgets['status'].configure(text="○", foreground="gray")
                widgets['auth_btn'].configure(state=tk.DISABLED)
    
    def _setup_callbacks(self):
        """Set up upload manager callbacks."""
        self.upload_manager.on_job_change(self._on_job_change)
        self.upload_manager.on_progress(self._on_progress)
    
    def _on_job_change(self, job: UploadJob):
        """Handle job status change."""
        self.root.after(0, lambda: self._update_job_in_tree(job))
        self.root.after(0, self._update_statistics)
        
        # Log status changes
        status_msg = {
            JobStatus.QUEUED: f"📋 Queued: {job.metadata.title}",
            JobStatus.IN_PROGRESS: f"🔄 Uploading: {job.metadata.title}",
            JobStatus.COMPLETED: f"✅ Completed: {job.metadata.title}",
            JobStatus.FAILED: f"❌ Failed: {job.metadata.title}",
            JobStatus.CANCELLED: f"🚫 Cancelled: {job.metadata.title}",
            JobStatus.PAUSED: f"⏸ Paused: {job.metadata.title}"
        }
        msg = status_msg.get(job.status)
        if msg:
            self.root.after(0, lambda m=msg: self._log(m))
        
        # System tray notification for completed/failed
        if self.system_tray.is_available():
            if job.status == JobStatus.COMPLETED:
                self.system_tray.notify("Upload Complete", f"'{job.metadata.title}' uploaded successfully!")
            elif job.status == JobStatus.FAILED:
                self.system_tray.notify("Upload Failed", f"'{job.metadata.title}' failed to upload.")
    
    def _on_progress(self, job: UploadJob, progress: UploadProgress):
        """Handle progress update."""
        self.root.after(0, lambda: self._update_job_progress(job, progress))
    
    def _new_upload(self, initial_video: str = None):
        """Open new upload dialog."""
        # Check if any platform is authenticated
        has_auth = any(
            self.upload_manager.is_platform_authenticated(p)
            for p in Platform
        )
        
        if not has_auth:
            messagebox.showwarning(
                "No Platforms Ready",
                "Please configure and log in to at least one platform first.\n\n"
                "1. Click ⚙️ to configure a platform\n"
                "2. Click 🔑 to log in"
            )
            return
        
        dialog = NewUploadDialog(
            self.root, 
            self.upload_manager, 
            self.template_manager,
            self.thumbnail_generator,
            initial_video=initial_video
        )
        self.root.wait_window(dialog)
        
        if dialog.result:
            self._refresh_jobs()
            self._log(f"➕ Added: {dialog.result.metadata.title}")
    
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
        
        self._update_statistics()
    
    def _add_job_to_tree(self, job: UploadJob):
        """Add job to tree view."""
        platforms = ", ".join(p.value.title()[:3] for p in job.platforms)
        status = self._format_status(job)
        progress = self._format_progress(job)
        created = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.created_at))
        
        self.job_tree.insert(
            '',
            tk.END,
            iid=job.id,
            values=(job.metadata.title, platforms, status, progress, created)
        )
    
    def _update_job_in_tree(self, job: UploadJob):
        """Update job in tree view."""
        if not self.job_tree.exists(job.id):
            self._refresh_jobs()
            return
        
        platforms = ", ".join(p.value.title()[:3] for p in job.platforms)
        status = self._format_status(job)
        progress = self._format_progress(job)
        created = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.created_at))
        
        self.job_tree.item(
            job.id,
            values=(job.metadata.title, platforms, status, progress, created)
        )
    
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
        status_text = {
            JobStatus.QUEUED: "⏳ Queued",
            JobStatus.WAITING_SCHEDULE: "📅 Scheduled",
            JobStatus.IN_PROGRESS: "🔄 Uploading",
            JobStatus.COMPLETED: "✅ Done",
            JobStatus.FAILED: "❌ Failed",
            JobStatus.CANCELLED: "🚫 Cancelled",
            JobStatus.PAUSED: "⏸ Paused"
        }
        return status_text.get(job.status, job.status.name)
    
    def _format_progress(self, job: UploadJob) -> str:
        """Format job progress for display."""
        if job.status == JobStatus.COMPLETED:
            success_count = sum(1 for r in job.platform_results.values() if r.success)
            return f"{success_count}/{len(job.platforms)} OK"
        elif job.status == JobStatus.FAILED:
            return "Failed"
        elif job.progress:
            return f"{job.progress.percent:.1f}%"
        else:
            return "-"
    
    def _update_statistics(self):
        """Update statistics display."""
        stats = self.upload_manager.get_statistics()
        
        self.stats_labels['total'].configure(text=str(stats['total_jobs']))
        self.stats_labels['queued'].configure(text=str(stats['queued_jobs']))
        self.stats_labels['completed'].configure(text=str(stats['completed_jobs']))
        self.stats_labels['failed'].configure(text=str(stats['failed_uploads']))
        self.stats_labels['success_rate'].configure(text=f"{stats['success_rate']*100:.1f}%")
    
    def _show_context_menu(self, event):
        """Show context menu for selected job."""
        item = self.job_tree.identify_row(event.y)
        if item:
            self.job_tree.selection_set(item)
            self.context_menu.tk_popup(event.x_root, event.y_root)
    
    def _get_selected_jobs(self) -> List[UploadJob]:
        """Get currently selected jobs."""
        selection = self.job_tree.selection()
        jobs = []
        for job_id in selection:
            job = self.upload_manager.get_job(job_id)
            if job:
                jobs.append(job)
        return jobs
    
    def _view_job_details(self):
        """View details of selected job."""
        jobs = self._get_selected_jobs()
        if not jobs:
            return
        
        job = jobs[0]
        
        # Create details dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Job Details: {job.metadata.title}")
        dialog.geometry("550x500")
        dialog.transient(self.root)
        
        text = tk.Text(dialog, wrap=tk.WORD, padx=10, pady=10)
        scroll = ttk.Scrollbar(dialog, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Format details
        details = f"""📄 Title: {job.metadata.title}

📊 Status: {job.status.name}
📅 Created: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(job.created_at))}
🌐 Platforms: {', '.join(p.value for p in job.platforms)}

📝 Description:
{job.metadata.description or '(none)'}

🏷️ Tags: {', '.join(job.metadata.tags) or '(none)'}
🔒 Privacy: {job.metadata.privacy}
📁 Category: {job.metadata.category or '(none)'}
🖼️ Thumbnail: {job.metadata.thumbnail_path or '(none)'}

📤 Upload Results:
"""
        for platform, result in job.platform_results.items():
            if result.success:
                details += f"\n  ✅ {platform}:\n     URL: {result.video_url}\n     Upload time: {result.upload_time:.1f}s\n"
            else:
                details += f"\n  ❌ {platform}:\n     Error: {result.error_message}\n"
        
        if not job.platform_results:
            details += "\n  (no results yet)\n"
        
        if job.error_message:
            details += f"\n⚠️ Error: {job.error_message}"
        
        text.insert(tk.END, details)
        text.configure(state=tk.DISABLED)
    
    def _pause_selected(self):
        """Pause selected jobs."""
        for job in self._get_selected_jobs():
            self.upload_manager.pause_upload(job.id)
    
    def _resume_selected(self):
        """Resume selected jobs."""
        for job in self._get_selected_jobs():
            self.upload_manager.resume_upload(job.id)
    
    def _cancel_selected(self):
        """Cancel selected jobs."""
        jobs = self._get_selected_jobs()
        if not jobs:
            return
        
        if messagebox.askyesno("Confirm", f"Cancel {len(jobs)} upload(s)?"):
            for job in jobs:
                self.upload_manager.cancel_upload(job.id)
    
    def _retry_selected(self):
        """Retry selected jobs."""
        for job in self._get_selected_jobs():
            self.upload_manager.retry_upload(job.id)
        self._refresh_jobs()
    
    def _pause_all(self):
        """Pause all in-progress uploads."""
        for job in self.upload_manager.get_all_jobs():
            if job.status == JobStatus.IN_PROGRESS:
                self.upload_manager.pause_upload(job.id)
        self._log("⏸ Paused all uploads")
    
    def _resume_all(self):
        """Resume all paused uploads."""
        for job in self.upload_manager.get_all_jobs():
            if job.status == JobStatus.PAUSED:
                self.upload_manager.resume_upload(job.id)
        self._log("▶ Resumed all uploads")
    
    def _on_close(self):
        """Handle window close."""
        # If system tray is available, minimize instead of closing
        if self.system_tray.is_available():
            if messagebox.askyesno("Confirm", "Minimize to system tray?\n\nClick 'No' to exit completely."):
                self.root.withdraw()
                self.system_tray.notify(APP_NAME, "Running in background")
                return
        
        self._force_close()
    
    def _force_close(self):
        """Force close the application."""
        self._log("Shutting down...")
        self.system_tray.stop()
        self.upload_manager.stop()
        self.root.destroy()


def main():
    """Main entry point."""
    # Try to use tkinterdnd2 for drag and drop
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
        logger.info("Using TkinterDnD for drag & drop support")
    except ImportError:
        root = tk.Tk()
        logger.info("TkinterDnD not available, basic mode")
    
    # Set theme
    try:
        root.tk.call("source", "azure.tcl")
        root.tk.call("set_theme", "light")
    except:
        pass
    
    app = VideoUploaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
