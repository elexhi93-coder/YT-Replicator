# IDM Video Downloader - Portable Edition for Windows 7/8/10/11

## 📦 Available Builds

### 32-bit Version (Maximum Compatibility)
**File:** `IDM_Video_Downloader_Win7_x86.exe`
**Size:** ~40 MB
**Compatible with:**
- ✅ Windows 7 (32-bit)
- ✅ Windows 7 (64-bit)
- ✅ Windows 8/8.1 (32-bit and 64-bit)
- ✅ Windows 10 (32-bit and 64-bit)
- ✅ Windows 11 (64-bit with 32-bit emulation)
- ✅ Older 32-bit systems

**Best for:** Maximum compatibility, older systems, 32-bit Windows

### 64-bit Version (Recommended)
**File:** `IDM_Video_Downloader_Win7.exe`
**Size:** ~40 MB
**Compatible with:**
- ✅ Windows 7 (64-bit)
- ✅ Windows 8/8.1 (64-bit)
- ✅ Windows 10 (64-bit)
- ✅ Windows 11 (64-bit)

**Best for:** Modern 64-bit systems, better performance

---

## 🚀 Quick Start

1. **Download** the appropriate version for your system
2. **Double-click** the .exe file to run
3. **No installation required** - runs directly!

---

## ✨ Features

### Core Features
- 🎥 **Video Download** - Download videos in multiple qualities (4K, 1080p, 720p, etc.)
- 🎵 **Audio Only** - Extract audio as MP3 (requires FFmpeg)
- 🖼️ **Thumbnails** - Download video thumbnails in high quality
- 💬 **Subtitles** - Download subtitles in multiple languages
- 📋 **Playlist Support** - Download entire playlists or channels
- 📁 **Advanced Playlist Manager** - Professional-grade playlist management

### Advanced Features
- ⚡ **Advanced Mode** - Individual video control with per-video quality settings
- 📊 **Smart Sorting** - Sort by views, date, duration, size, etc.
- 🎯 **Advanced Filters** - Filter by duration, views, date range, resolution
- 📂 **Download Groups** - Organize downloads with color-coded groups
- 👁️ **Column Visibility** - Customize what metadata you see
- 🔍 **Format Analysis** - Inspect available formats before downloading
- 📝 **Metadata Display** - 38+ metadata fields (title, uploader, views, likes, etc.)
- 🔄 **Batch Operations** - Download multiple videos simultaneously
- 📅 **Date Filtering** - Download only recent videos

### User Interface
- 🎨 **Clean & Modern** - Professional Tkinter GUI
- 📱 **Compact Layout** - Space-efficient design
- 🔍 **Collapsible Sections** - Show/hide sections as needed
- 📋 **Clipboard Monitor** - Auto-detect URLs in clipboard
- 📊 **Real-time Progress** - Live speed and ETA display
- 🎯 **Context Menu** - Right-click for quick actions

---

## 📋 System Requirements

### Minimum Requirements
- **OS:** Windows 7 or newer
- **RAM:** 512 MB (1 GB recommended)
- **Disk Space:** 100 MB free space
- **Internet:** Active internet connection

### Optional
- **FFmpeg:** For MP3 conversion (can be downloaded through the app)

---

## 🎓 How to Use

### Basic Usage (Simple Mode)

1. **Paste URL** into the "Video URL" field
2. **Click "Fetch Info"** to load video information
3. **Select Download Type:**
   - 🎥 Video (select quality)
   - 🎵 Audio Only (MP3 with FFmpeg)
   - 🖼️ Thumbnail
   - 💬 Subtitles
4. **Choose Download Path** (default: Downloads folder)
5. **Click "Download"**

### Advanced Usage (Advanced Mode)

1. **Paste Playlist/Channel URL**
2. **Click "Fetch Info"**
3. **Click "Advanced"** button in the Advanced Playlist Manager
4. **Features available:**
   - ✅ Select/deselect individual videos
   - 🎯 Set different quality for each video
   - 📊 Sort and filter videos
   - 📂 Create download groups
   - 👁️ Customize visible columns
   - 🔍 Analyze video formats
   - ⚙️ Apply batch operations

### Download Groups

1. Click **"Create Group"** in Quick Actions
2. **Name** the group and choose a **color**
3. **Select videos** in the list
4. Click **"Assign to Group"**
5. Click **"Group Settings"** to set quality/format for the group
6. Download - all group videos use group settings!

---

## 🔧 Building from Source

### Prerequisites
```bash
pip install pyinstaller pillow pyperclip yt-dlp
```

### Build 32-bit (Maximum Compatibility)
```bash
build_portable_win7_32bit.bat
```
Output: `dist/IDM_Video_Downloader_Win7_x86.exe`

### Build 64-bit (Recommended)
```bash
build_portable_win7.bat
```
Output: `dist/IDM_Video_Downloader_Win7.exe`

---

## ❓ FAQ

### Q: Which version should I download?
**A:** 
- **32-bit** if you have Windows 7 32-bit or older systems
- **64-bit** if you have modern 64-bit Windows (most users)

### Q: Do I need to install anything?
**A:** No! Just run the .exe file directly. No installation needed.

### Q: Can I convert to MP3?
**A:** Yes, but you need FFmpeg. The app can download it for you automatically.

### Q: Does it work offline?
**A:** No, you need an active internet connection to download videos.

### Q: Is it safe?
**A:** Yes! It's built with PyInstaller from open-source Python code. No viruses or malware.

### Q: Why is the file so large (40 MB)?
**A:** It includes Python runtime and all dependencies (yt-dlp, PIL, etc.) for true portability.

### Q: Can I use it on Windows XP?
**A:** No, minimum requirement is Windows 7. Python 3.12 doesn't support XP.

### Q: Does it support other sites besides YouTube?
**A:** Yes! It uses yt-dlp which supports 1000+ sites.

---

## 📝 License

Valid until: **December 31, 2025**

---

## 🐛 Troubleshooting

### "Windows protected your PC" warning
This is normal for unsigned executables. Click "More info" → "Run anyway"

### MP3 conversion not working
Download FFmpeg through the app: Click "📥 Get FFmpeg" button

### Download fails
1. Check internet connection
2. Update yt-dlp (app auto-updates)
3. Try different quality setting
4. Check if URL is valid

### Slow performance
Close other programs to free up RAM

---

## 🎉 Credits

- **yt-dlp** - Video downloading engine
- **PyInstaller** - Executable packaging
- **Pillow** - Image processing
- **pyperclip** - Clipboard monitoring

---

## 📞 Support

For issues, bugs, or feature requests, please check the documentation or contact support.

---

**Version:** 1.2.0  
**Build Date:** November 11, 2025  
**Architecture:** x86 (32-bit) and x64 (64-bit)
