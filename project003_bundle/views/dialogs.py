"""
Dialog Windows for IDM-YT
Reusable dialog components.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass


@dataclass
class PlaylistItemData:
    """Data for playlist item display"""
    index: int
    title: str
    duration: str
    selected: bool = True
    status: str = "Pending"


class PlaylistDialog(tk.Toplevel):
    """
    Dialog for selecting playlist items to download.
    
    Usage:
        dialog = PlaylistDialog(parent, playlist_items, on_download=callback)
        dialog.show()
    """
    
    def __init__(
        self,
        parent,
        items: List[PlaylistItemData],
        playlist_title: str = "Playlist",
        on_download: Optional[Callable[[List[int]], None]] = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.items = items
        self.playlist_title = playlist_title
        self.on_download = on_download
        self._checkboxes: List[tk.BooleanVar] = []
        
        self.title(f"Playlist: {playlist_title}")
        self.geometry("700x500")
        self.minsize(500, 300)
        
        self._create_widgets()
        self.transient(parent)
        self.grab_set()
    
    def _create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(
            header_frame,
            text=f"{self.playlist_title} ({len(self.items)} videos)",
            font=('Arial', 12, 'bold')
        ).pack(side=tk.LEFT)
        
        # Select/Deselect buttons
        btn_frame = ttk.Frame(header_frame)
        btn_frame.pack(side=tk.RIGHT)
        
        ttk.Button(
            btn_frame, text="Select All",
            command=self._select_all
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(
            btn_frame, text="Deselect All",
            command=self._deselect_all
        ).pack(side=tk.LEFT)
        
        # Treeview for items
        tree_frame = ttk.Frame(main_frame)
        tree_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        columns = ("select", "index", "title", "duration", "status")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns,
            show="headings", selectmode="extended"
        )
        
        # Column headers
        self.tree.heading("select", text="✓")
        self.tree.heading("index", text="#")
        self.tree.heading("title", text="Title")
        self.tree.heading("duration", text="Duration")
        self.tree.heading("status", text="Status")
        
        # Column widths
        self.tree.column("select", width=30, anchor=tk.CENTER)
        self.tree.column("index", width=40, anchor=tk.CENTER)
        self.tree.column("title", width=400)
        self.tree.column("duration", width=80, anchor=tk.CENTER)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL,
            command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Populate items
        self._populate_items()
        
        # Toggle on click
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double_click)
        
        # Bottom buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, sticky=(tk.E), pady=(10, 0))
        
        ttk.Button(
            button_frame, text="Cancel",
            command=self.destroy
        ).pack(side=tk.RIGHT, padx=(5, 0))
        
        ttk.Button(
            button_frame, text="Download Selected",
            command=self._on_download_click
        ).pack(side=tk.RIGHT)
    
    def _populate_items(self):
        """Add items to treeview"""
        for item in self.items:
            check = "☑" if item.selected else "☐"
            self.tree.insert("", tk.END, values=(
                check, item.index, item.title,
                item.duration, item.status
            ))
    
    def _on_click(self, event):
        """Handle click to toggle checkbox"""
        region = self.tree.identify_region(event.x, event.y)
        if region == "cell":
            col = self.tree.identify_column(event.x)
            if col == "#1":  # Checkbox column
                item = self.tree.identify_row(event.y)
                self._toggle_item(item)
    
    def _on_double_click(self, event):
        """Toggle on double click anywhere"""
        item = self.tree.identify_row(event.y)
        if item:
            self._toggle_item(item)
    
    def _toggle_item(self, item: str):
        """Toggle item selection"""
        values = list(self.tree.item(item, "values"))
        values[0] = "☑" if values[0] == "☐" else "☐"
        self.tree.item(item, values=values)
    
    def _select_all(self):
        """Select all items"""
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[0] = "☑"
            self.tree.item(item, values=values)
    
    def _deselect_all(self):
        """Deselect all items"""
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[0] = "☐"
            self.tree.item(item, values=values)
    
    def get_selected_indices(self) -> List[int]:
        """Get indices of selected items"""
        selected = []
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            if values[0] == "☑":
                selected.append(int(values[1]))
        return selected
    
    def _on_download_click(self):
        """Handle download button click"""
        selected = self.get_selected_indices()
        if not selected:
            messagebox.showwarning("No Selection", "Please select at least one video.")
            return
        
        if self.on_download:
            self.on_download(selected)
        self.destroy()
    
    def update_item_status(self, index: int, status: str):
        """Update status of specific item"""
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            if int(values[1]) == index:
                values[4] = status
                self.tree.item(item, values=values)
                break
    
    def show(self):
        """Show dialog and wait"""
        self.wait_window()


class SettingsDialog(tk.Toplevel):
    """
    Dialog for application settings.
    
    Usage:
        dialog = SettingsDialog(parent, current_settings, on_save=callback)
        dialog.show()
    """
    
    def __init__(
        self,
        parent,
        settings: Dict[str, Any],
        on_save: Optional[Callable[[Dict[str, Any]], None]] = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.settings = settings.copy()
        self.on_save = on_save
        
        self.title("Settings")
        self.geometry("500x400")
        self.resizable(False, False)
        
        self._create_widgets()
        self.transient(parent)
        self.grab_set()
    
    def _create_widgets(self):
        # Notebook for tabs
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # General tab
        general_frame = ttk.Frame(notebook, padding="10")
        notebook.add(general_frame, text="General")
        self._create_general_tab(general_frame)
        
        # Downloads tab
        downloads_frame = ttk.Frame(notebook, padding="10")
        notebook.add(downloads_frame, text="Downloads")
        self._create_downloads_tab(downloads_frame)
        
        # Network tab
        network_frame = ttk.Frame(notebook, padding="10")
        notebook.add(network_frame, text="Network")
        self._create_network_tab(network_frame)
        
        # Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(
            button_frame, text="Cancel",
            command=self.destroy
        ).pack(side=tk.RIGHT, padx=(5, 0))
        
        ttk.Button(
            button_frame, text="Save",
            command=self._on_save_click
        ).pack(side=tk.RIGHT)
    
    def _create_general_tab(self, parent):
        """Create general settings tab"""
        # Default download folder
        ttk.Label(parent, text="Default download folder:").grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        
        folder_frame = ttk.Frame(parent)
        folder_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        folder_frame.columnconfigure(0, weight=1)
        
        self.download_folder_var = tk.StringVar(
            value=self.settings.get("download_folder", "")
        )
        ttk.Entry(
            folder_frame, textvariable=self.download_folder_var
        ).grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        
        ttk.Button(
            folder_frame, text="Browse...",
            command=self._browse_folder
        ).grid(row=0, column=1)
        
        # Clipboard monitor
        self.clipboard_var = tk.BooleanVar(
            value=self.settings.get("clipboard_monitor", True)
        )
        ttk.Checkbutton(
            parent, text="Monitor clipboard for URLs",
            variable=self.clipboard_var
        ).grid(row=2, column=0, sticky=tk.W, pady=5)
        
        # Auto-fetch info
        self.auto_fetch_var = tk.BooleanVar(
            value=self.settings.get("auto_fetch", True)
        )
        ttk.Checkbutton(
            parent, text="Auto-fetch video info when URL is pasted",
            variable=self.auto_fetch_var
        ).grid(row=3, column=0, sticky=tk.W, pady=5)
    
    def _create_downloads_tab(self, parent):
        """Create downloads settings tab"""
        # Default format
        ttk.Label(parent, text="Default format:").grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.default_format_var = tk.StringVar(
            value=self.settings.get("default_format", "best")
        )
        format_combo = ttk.Combobox(
            parent, textvariable=self.default_format_var,
            values=["best", "best[height<=1080]", "best[height<=720]", 
                    "best[height<=480]", "bestaudio"],
            width=30
        )
        format_combo.grid(row=1, column=0, sticky=tk.W, pady=(0, 10))
        
        # Concurrent fragments
        ttk.Label(parent, text="Default parallel connections:").grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        self.concurrent_var = tk.IntVar(
            value=self.settings.get("concurrent_fragments", 4)
        )
        ttk.Spinbox(
            parent, from_=1, to=16,
            textvariable=self.concurrent_var, width=5
        ).grid(row=3, column=0, sticky=tk.W, pady=(0, 10))
        
        # Embed metadata
        self.metadata_var = tk.BooleanVar(
            value=self.settings.get("embed_metadata", True)
        )
        ttk.Checkbutton(
            parent, text="Embed metadata in files",
            variable=self.metadata_var
        ).grid(row=4, column=0, sticky=tk.W, pady=5)
        
        # Embed thumbnail
        self.thumbnail_var = tk.BooleanVar(
            value=self.settings.get("embed_thumbnail", False)
        )
        ttk.Checkbutton(
            parent, text="Embed thumbnail in audio files",
            variable=self.thumbnail_var
        ).grid(row=5, column=0, sticky=tk.W, pady=5)
    
    def _create_network_tab(self, parent):
        """Create network settings tab"""
        # Rate limit
        ttk.Label(parent, text="Rate limit (e.g., 500K, 2M):").grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.rate_limit_var = tk.StringVar(
            value=self.settings.get("rate_limit", "")
        )
        ttk.Entry(
            parent, textvariable=self.rate_limit_var, width=15
        ).grid(row=1, column=0, sticky=tk.W, pady=(0, 10))
        
        # Proxy
        ttk.Label(parent, text="Proxy (e.g., socks5://127.0.0.1:1080):").grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        self.proxy_var = tk.StringVar(
            value=self.settings.get("proxy", "")
        )
        ttk.Entry(
            parent, textvariable=self.proxy_var, width=40
        ).grid(row=3, column=0, sticky=tk.W, pady=(0, 10))
        
        # Use aria2c
        self.use_aria2c_var = tk.BooleanVar(
            value=self.settings.get("use_aria2c", False)
        )
        ttk.Checkbutton(
            parent, text="Use aria2c for downloads",
            variable=self.use_aria2c_var
        ).grid(row=4, column=0, sticky=tk.W, pady=5)
    
    def _browse_folder(self):
        """Open folder browser"""
        folder = filedialog.askdirectory(
            initialdir=self.download_folder_var.get()
        )
        if folder:
            self.download_folder_var.set(folder)
    
    def _on_save_click(self):
        """Handle save button"""
        self.settings = {
            "download_folder": self.download_folder_var.get(),
            "clipboard_monitor": self.clipboard_var.get(),
            "auto_fetch": self.auto_fetch_var.get(),
            "default_format": self.default_format_var.get(),
            "concurrent_fragments": self.concurrent_var.get(),
            "embed_metadata": self.metadata_var.get(),
            "embed_thumbnail": self.thumbnail_var.get(),
            "rate_limit": self.rate_limit_var.get(),
            "proxy": self.proxy_var.get(),
            "use_aria2c": self.use_aria2c_var.get(),
        }
        
        if self.on_save:
            self.on_save(self.settings)
        self.destroy()
    
    def show(self):
        """Show dialog and wait"""
        self.wait_window()


class AboutDialog(tk.Toplevel):
    """
    About dialog with application information.
    
    Usage:
        dialog = AboutDialog(parent, version="1.0.0")
        dialog.show()
    """
    
    def __init__(
        self,
        parent,
        app_name: str = "IDM-YT Video Downloader",
        version: str = "1.0.0",
        description: str = "",
        author: str = "",
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.app_name = app_name
        self.version = version
        self.description = description
        self.author = author
        
        self.title(f"About {app_name}")
        self.geometry("400x300")
        self.resizable(False, False)
        
        self._create_widgets()
        self.transient(parent)
        self.grab_set()
    
    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # App name
        ttk.Label(
            main_frame, text=self.app_name,
            font=('Arial', 16, 'bold')
        ).pack(pady=(0, 5))
        
        # Version
        ttk.Label(
            main_frame, text=f"Version {self.version}",
            font=('Arial', 10)
        ).pack(pady=(0, 15))
        
        # Description
        if self.description:
            desc_label = ttk.Label(
                main_frame, text=self.description,
                wraplength=350, justify=tk.CENTER
            )
            desc_label.pack(pady=(0, 15))
        
        # Default description
        default_desc = (
            "A powerful video downloader with parallel downloads, "
            "multiple format support, and plugin system.\n\n"
            "Built with Python, Tkinter, and yt-dlp."
        )
        ttk.Label(
            main_frame, text=default_desc,
            wraplength=350, justify=tk.CENTER
        ).pack(pady=(0, 15))
        
        # Author
        if self.author:
            ttk.Label(
                main_frame, text=f"Author: {self.author}",
                font=('Arial', 9)
            ).pack(pady=(0, 10))
        
        # Features list
        features = [
            "✓ Parallel fragment downloads",
            "✓ YouTube Studio-compatible formats",
            "✓ Plugin system",
            "✓ Clipboard monitoring",
        ]
        for feature in features:
            ttk.Label(main_frame, text=feature).pack(anchor=tk.W)
        
        # Close button
        ttk.Button(
            main_frame, text="Close",
            command=self.destroy
        ).pack(pady=(20, 0))
    
    def show(self):
        """Show dialog and wait"""
        self.wait_window()
