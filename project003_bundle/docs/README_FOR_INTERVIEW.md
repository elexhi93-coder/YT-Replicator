# IDM Video Downloader - Project Presentation

## Overview
IDM Video Downloader is a professional-grade, cross-platform desktop application for downloading videos, audio, thumbnails, and subtitles from YouTube and 1000+ other sites. It features a modern, user-friendly interface, advanced playlist management, and is fully portable for Windows 7/8/10/11 (32-bit and 64-bit).

---

## Key Features
- **Multi-format Download:** Video (4K, 1080p, etc.), Audio (MP3), Thumbnails, Subtitles
- **Advanced Playlist Manager:** Batch operations, smart sorting, per-item quality, group downloads
- **Modern UI:** Tkinter-based, collapsible sections, context menus, clipboard monitoring
- **Portable Executable:** No installation required, single .exe for Windows 7+ (32/64-bit)
- **FFmpeg Integration:** Automatic MP3 conversion
- **Extensible:** Plugin system for future features
- **Robust Error Handling:** Thread-safe, user-friendly messages, logging

---

## Technologies Used
- **Python 3.8+** (PyInstaller for packaging)
- **yt-dlp** (video/audio extraction)
- **Tkinter** (GUI)
- **Pillow** (image processing)
- **Pyperclip** (clipboard)
- **FFmpeg** (audio conversion)

---

## Architecture Highlights
- **Modular Design:** Separation of UI, download logic, plugin management
- **Threading:** Responsive UI during downloads
- **Configurable:** User can select quality, format, output path, and more
- **Batch & Parallel Downloads:** Efficient for large playlists/channels
- **Cross-version Compatibility:** Runs on legacy and modern Windows

---

## User Experience
- **Simple Mode:** Paste URL, select type, download
- **Advanced Mode:** Manage playlists, set per-video/group settings, filter/sort
- **Progress Feedback:** Real-time speed, ETA, status
- **Error Recovery:** Retry failed downloads, clear/reset UI

---

## Build & Distribution
- **Portable Build Scripts:**
  - `build_portable_win7_32bit.bat` (32-bit)
  - `build_portable_win7.bat` (64-bit)
- **Output:** Single .exe in `dist/` folder
- **Documentation:** Comprehensive user and technical README

---

## Why This Project?
- **Demonstrates:**
  - Full-stack Python desktop development
  - GUI/UX design for real users
  - Packaging and distribution for legacy systems
  - Integration with open-source tools (yt-dlp, FFmpeg)
  - Robust error handling and code quality
- **Ready for Production:**
  - Used by real users for video management
  - Easy to maintain and extend

---

## Screenshots
![Main UI](screenshots/main_ui.png)
![Advanced Playlist Manager](screenshots/advanced_manager.png)

---

## Contact
**Author:** [Your Name]
**Email:** [your.email@example.com]
**LinkedIn:** [linkedin.com/in/yourprofile]

---

*Thank you for considering my application! I am ready to discuss technical details, design choices, and demonstrate the application live.*
