"""
Download Library - Browse and manage downloaded content by type
Organizes downloads into Videos, Audio, Thumbnails, and Subtitles
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
from pathlib import Path
from datetime import datetime
import json
import subprocess
import platform


class DownloadLibrary:
    """Window to browse and manage downloaded content organized by type"""
    
    # File extensions for each category
    CATEGORIES = {
        'Videos': ['.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.3gp', '.m4v'],
        'Audio': ['.mp3', '.m4a', '.opus', '.ogg', '.wav', '.flac', '.aac', '.wma'],
        'Thumbnails': ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'],
        'Subtitles': ['.srt', '.vtt', '.ass', '.ssa', '.sub', '.sbv']
    }
    
    # Icons for categories
    ICONS = {
        'Videos': '🎬',
        'Audio': '🎵',
        'Thumbnails': '🖼️',
        'Subtitles': '📝'
    }
    
    def __init__(self, parent, default_path=None, log_callback=None):
        self.parent = parent
        self.log_callback = log_callback or print
        self.default_path = default_path or str(Path.home() / "Downloads")
        
        # Track scanned files
        self.files_by_category = {cat: [] for cat in self.CATEGORIES}
        self.current_category = 'Videos'
        
        # Create window
        self.window = tk.Toplevel(parent)
        self.window.title("📚 Download Library")
        self.window.geometry("900x600")
        self.window.resizable(True, True)
        
        self.setup_ui()
        self.scan_directory(self.default_path)
    
    def setup_ui(self):
        """Setup the library UI"""
        # Main container
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === TOP: Path selector ===
        path_frame = ttk.Frame(main_frame)
        path_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(path_frame, text="📁 Scan Folder:", font=('Arial', 10)).pack(side=tk.LEFT)
        
        self.path_var = tk.StringVar(value=self.default_path)
        path_entry = ttk.Entry(path_frame, textvariable=self.path_var, width=60)
        path_entry.pack(side=tk.LEFT, padx=(10, 5), fill=tk.X, expand=True)
        
        ttk.Button(path_frame, text="📂 Browse", command=self.browse_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(path_frame, text="🔄 Refresh", command=self.refresh).pack(side=tk.LEFT, padx=2)
        
        # Include subfolders option
        self.include_subfolders = tk.BooleanVar(value=True)
        ttk.Checkbutton(path_frame, text="Include subfolders", 
                       variable=self.include_subfolders).pack(side=tk.LEFT, padx=10)
        
        # === MIDDLE: Category tabs (left) and File list (right) ===
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left: Category buttons
        self.create_category_panel(content_frame)
        
        # Right: File list
        self.create_file_list(content_frame)
        
        # === BOTTOM: Actions ===
        self.create_action_bar(main_frame)
    
    def create_category_panel(self, parent):
        """Create the left panel with category buttons"""
        cat_frame = ttk.LabelFrame(parent, text="📂 Categories", padding="10")
        cat_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        self.category_buttons = {}
        self.category_counts = {}
        
        for category in self.CATEGORIES:
            icon = self.ICONS[category]
            
            # Frame for each category
            btn_frame = ttk.Frame(cat_frame)
            btn_frame.pack(fill=tk.X, pady=5)
            
            # Count label
            count_var = tk.StringVar(value="0")
            self.category_counts[category] = count_var
            
            # Button
            btn = tk.Button(btn_frame, 
                           text=f"{icon} {category}",
                           font=('Arial', 11),
                           width=15,
                           anchor='w',
                           relief=tk.FLAT,
                           bg='#e0e0e0',
                           command=lambda c=category: self.show_category(c))
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.category_buttons[category] = btn
            
            # Count badge
            count_label = ttk.Label(btn_frame, textvariable=count_var, 
                                   font=('Arial', 9, 'bold'), foreground='blue')
            count_label.pack(side=tk.RIGHT, padx=5)
        
        # Separator
        ttk.Separator(cat_frame, orient='horizontal').pack(fill=tk.X, pady=15)
        
        # Stats
        stats_frame = ttk.LabelFrame(cat_frame, text="📊 Statistics", padding="5")
        stats_frame.pack(fill=tk.X)
        
        self.total_files_var = tk.StringVar(value="Total: 0 files")
        self.total_size_var = tk.StringVar(value="Size: 0 MB")
        
        ttk.Label(stats_frame, textvariable=self.total_files_var, 
                 font=('Arial', 9)).pack(anchor='w')
        ttk.Label(stats_frame, textvariable=self.total_size_var, 
                 font=('Arial', 9)).pack(anchor='w')
        
        # Highlight initial category
        self.highlight_category('Videos')
    
    def create_file_list(self, parent):
        """Create the file list treeview"""
        list_frame = ttk.LabelFrame(parent, text="📄 Files", padding="5")
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Search bar
        search_frame = ttk.Frame(list_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(search_frame, text="🔍").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self.filter_files())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40)
        search_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        ttk.Button(search_frame, text="✖", width=3, 
                  command=lambda: self.search_var.set("")).pack(side=tk.LEFT)
        
        # Treeview
        columns = ('name', 'size', 'date', 'path')
        self.file_tree = ttk.Treeview(list_frame, columns=columns, show='headings', 
                                      selectmode='extended')
        
        # Column headers
        self.file_tree.heading('name', text='📄 Name', command=lambda: self.sort_column('name'))
        self.file_tree.heading('size', text='📊 Size', command=lambda: self.sort_column('size'))
        self.file_tree.heading('date', text='📅 Date', command=lambda: self.sort_column('date'))
        self.file_tree.heading('path', text='📁 Location', command=lambda: self.sort_column('path'))
        
        # Column widths
        self.file_tree.column('name', width=250, minwidth=150)
        self.file_tree.column('size', width=80, minwidth=60)
        self.file_tree.column('date', width=100, minwidth=80)
        self.file_tree.column('path', width=200, minwidth=100)
        
        # Scrollbars
        v_scroll = ttk.Scrollbar(list_frame, orient='vertical', command=self.file_tree.yview)
        h_scroll = ttk.Scrollbar(list_frame, orient='horizontal', command=self.file_tree.xview)
        self.file_tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        
        # Pack
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Bind events
        self.file_tree.bind('<Double-1>', self.open_file)
        self.file_tree.bind('<Return>', self.open_file)
        self.file_tree.bind('<Button-3>', self.show_context_menu)
        
        # Store sort state
        self.sort_column_name = 'name'
        self.sort_reverse = False
    
    def create_action_bar(self, parent):
        """Create bottom action bar"""
        action_frame = ttk.Frame(parent)
        action_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Left: Selection info
        self.selection_var = tk.StringVar(value="Select files to see options")
        ttk.Label(action_frame, textvariable=self.selection_var, 
                 font=('Arial', 9)).pack(side=tk.LEFT)
        
        # Right: Buttons
        btn_frame = ttk.Frame(action_frame)
        btn_frame.pack(side=tk.RIGHT)
        
        ttk.Button(btn_frame, text="▶️ Open", 
                  command=self.open_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="📁 Show in Folder", 
                  command=self.show_in_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🗑️ Delete", 
                  command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="❌ Close", 
                  command=self.window.destroy).pack(side=tk.LEFT, padx=10)
    
    def browse_folder(self):
        """Browse for a folder to scan"""
        folder = filedialog.askdirectory(parent=self.window, 
                                         initialdir=self.path_var.get())
        if folder:
            self.path_var.set(folder)
            self.scan_directory(folder)
    
    def refresh(self):
        """Refresh the current folder"""
        self.scan_directory(self.path_var.get())
    
    def scan_directory(self, path):
        """Scan directory for media files"""
        # Reset
        self.files_by_category = {cat: [] for cat in self.CATEGORIES}
        total_size = 0
        
        path = Path(path)
        if not path.exists():
            messagebox.showerror("Error", f"Path does not exist:\n{path}", parent=self.window)
            return
        
        # Scan files
        if self.include_subfolders.get():
            files = path.rglob('*')
        else:
            files = path.glob('*')
        
        for file_path in files:
            if file_path.is_file():
                ext = file_path.suffix.lower()
                for category, extensions in self.CATEGORIES.items():
                    if ext in extensions:
                        try:
                            stat = file_path.stat()
                            file_info = {
                                'name': file_path.name,
                                'path': str(file_path),
                                'size': stat.st_size,
                                'date': datetime.fromtimestamp(stat.st_mtime)
                            }
                            self.files_by_category[category].append(file_info)
                            total_size += stat.st_size
                        except Exception:
                            pass
                        break
        
        # Update counts
        total_files = 0
        for category, files_list in self.files_by_category.items():
            count = len(files_list)
            self.category_counts[category].set(str(count))
            total_files += count
        
        # Update stats
        self.total_files_var.set(f"Total: {total_files} files")
        self.total_size_var.set(f"Size: {self.format_size(total_size)}")
        
        # Refresh current view
        self.show_category(self.current_category)
        
        self.log_callback(f"📚 Scanned {path}: Found {total_files} files")
    
    def show_category(self, category):
        """Show files for a category"""
        self.current_category = category
        self.highlight_category(category)
        
        # Clear tree
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        
        # Add files
        files = self.files_by_category.get(category, [])
        for file_info in files:
            self.file_tree.insert('', 'end', values=(
                file_info['name'],
                self.format_size(file_info['size']),
                file_info['date'].strftime('%Y-%m-%d'),
                str(Path(file_info['path']).parent)
            ), tags=(file_info['path'],))
    
    def highlight_category(self, category):
        """Highlight the selected category button"""
        for cat, btn in self.category_buttons.items():
            if cat == category:
                btn.configure(bg='#4CAF50', fg='white')
            else:
                btn.configure(bg='#e0e0e0', fg='black')
    
    def filter_files(self):
        """Filter files by search term"""
        search_term = self.search_var.get().lower()
        
        # Clear and repopulate
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        
        files = self.files_by_category.get(self.current_category, [])
        for file_info in files:
            if search_term in file_info['name'].lower():
                self.file_tree.insert('', 'end', values=(
                    file_info['name'],
                    self.format_size(file_info['size']),
                    file_info['date'].strftime('%Y-%m-%d'),
                    str(Path(file_info['path']).parent)
                ), tags=(file_info['path'],))
    
    def sort_column(self, col):
        """Sort by column"""
        if self.sort_column_name == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column_name = col
            self.sort_reverse = False
        
        files = self.files_by_category.get(self.current_category, [])
        
        if col == 'name':
            files.sort(key=lambda x: x['name'].lower(), reverse=self.sort_reverse)
        elif col == 'size':
            files.sort(key=lambda x: x['size'], reverse=self.sort_reverse)
        elif col == 'date':
            files.sort(key=lambda x: x['date'], reverse=self.sort_reverse)
        elif col == 'path':
            files.sort(key=lambda x: x['path'].lower(), reverse=self.sort_reverse)
        
        self.show_category(self.current_category)
    
    def get_selected_paths(self):
        """Get file paths of selected items"""
        paths = []
        for item in self.file_tree.selection():
            tags = self.file_tree.item(item, 'tags')
            if tags:
                paths.append(tags[0])
        return paths
    
    def open_file(self, event=None):
        """Open the double-clicked file"""
        paths = self.get_selected_paths()
        if paths:
            self.open_with_default(paths[0])
    
    def open_selected(self):
        """Open selected files"""
        paths = self.get_selected_paths()
        for path in paths[:5]:  # Limit to 5 files
            self.open_with_default(path)
    
    def open_with_default(self, path):
        """Open file with default application"""
        try:
            if platform.system() == 'Windows':
                os.startfile(path)
            elif platform.system() == 'Darwin':
                subprocess.run(['open', path])
            else:
                subprocess.run(['xdg-open', path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open file:\n{e}", parent=self.window)
    
    def show_in_folder(self):
        """Show selected file in file explorer"""
        paths = self.get_selected_paths()
        if not paths:
            messagebox.showinfo("Info", "Select a file first", parent=self.window)
            return
        
        path = paths[0]
        try:
            if platform.system() == 'Windows':
                subprocess.run(['explorer', '/select,', path])
            elif platform.system() == 'Darwin':
                subprocess.run(['open', '-R', path])
            else:
                subprocess.run(['xdg-open', str(Path(path).parent)])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{e}", parent=self.window)
    
    def delete_selected(self):
        """Delete selected files"""
        paths = self.get_selected_paths()
        if not paths:
            messagebox.showinfo("Info", "Select files to delete", parent=self.window)
            return
        
        if not messagebox.askyesno("Confirm Delete", 
                                   f"Delete {len(paths)} file(s)?\nThis cannot be undone!",
                                   parent=self.window):
            return
        
        deleted = 0
        for path in paths:
            try:
                os.remove(path)
                deleted += 1
            except Exception as e:
                self.log_callback(f"❌ Could not delete {path}: {e}")
        
        messagebox.showinfo("Deleted", f"Deleted {deleted} file(s)", parent=self.window)
        self.refresh()
    
    def show_context_menu(self, event):
        """Show right-click context menu"""
        # Select the item under cursor
        item = self.file_tree.identify_row(event.y)
        if item:
            self.file_tree.selection_set(item)
        
        menu = tk.Menu(self.window, tearoff=0)
        menu.add_command(label="▶️ Open", command=self.open_selected)
        menu.add_command(label="📁 Show in Folder", command=self.show_in_folder)
        menu.add_separator()
        menu.add_command(label="📋 Copy Path", command=self.copy_path)
        menu.add_command(label="📋 Copy Name", command=self.copy_name)
        menu.add_separator()
        menu.add_command(label="🗑️ Delete", command=self.delete_selected)
        
        menu.tk_popup(event.x_root, event.y_root)
    
    def copy_path(self):
        """Copy file path to clipboard"""
        paths = self.get_selected_paths()
        if paths:
            self.window.clipboard_clear()
            self.window.clipboard_append(paths[0])
    
    def copy_name(self):
        """Copy file name to clipboard"""
        selection = self.file_tree.selection()
        if selection:
            name = self.file_tree.item(selection[0], 'values')[0]
            self.window.clipboard_clear()
            self.window.clipboard_append(name)
    
    @staticmethod
    def format_size(size_bytes):
        """Format bytes to human readable size"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# Test standalone
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    app = DownloadLibrary(root)
    root.mainloop()
