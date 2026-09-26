#!/usr/bin/env python3
"""
IDM-YT Video Downloader - Main Entry Point
Version 2.0 with MVC Architecture
"""

import sys
import tkinter as tk
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def main():
    """Launch the application"""
    # Import here to avoid circular imports
    from main_window import MainWindow
    
    root = tk.Tk()
    
    # Set window icon if available
    icon_path = project_root / "icon.ico"
    if icon_path.exists():
        try:
            root.iconbitmap(str(icon_path))
        except Exception:
            pass
    
    # Create and run application
    app = MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
