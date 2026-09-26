# IDM Video Downloader - Presentation & User Manual

---

## Project Presentation
IDM Video Downloader is a professional desktop application for downloading videos, audio, thumbnails, and subtitles from YouTube and 1000+ other sites. It features a modern, user-friendly interface, advanced playlist management, and is fully portable for Windows 7/8/10/11 (32-bit and 64-bit).

---

## Technologies Used
- **Python 3.8+**: Core language and logic
- **yt-dlp**: Video/audio extraction engine
- **Tkinter**: GUI framework
- **Pillow**: Image/thumbnail processing
- **Pyperclip**: Clipboard monitoring
- **FFmpeg**: Audio conversion (MP3)
- **PyInstaller**: Packaging into portable executables

---

## User Manual

### 1. Getting Started
- Download or build the portable executable using the provided batch scripts (`build_portable_win7_32bit.bat` or `build_portable_win7.bat`).
- Place `ffmpeg` binaries in the `ffmpeg/bin/` folder if MP3 conversion is required.
- Double-click the `.exe` file in the `dist/` folder to launch the application.

### 2. Main Features
- **Simple Mode**: Paste a video/playlist URL, select download type (video/audio/subtitles), and click Download.
- **Advanced Playlist Manager**: Add multiple URLs, batch download, set per-item quality, sort/filter items, and group downloads.
- **Clipboard Monitoring**: Automatically detects copied URLs for quick access.
- **Collapsible UI Sections**: Hide/show advanced options for a cleaner interface.
- **Error Handling**: User-friendly messages and retry options for failed downloads.

### 3. How to Use
#### Download a Single Video
1. Paste the video URL into the input field.
2. Select the desired format (Video/Audio/MP3/Subtitles).
3. Click the Download button.
4. Monitor progress and status in the UI.

#### Download a Playlist or Channel
1. Switch to Advanced Mode.
2. Paste the playlist/channel URL.
3. Configure per-item or group settings (quality, format, output path).
4. Click Download All.
5. Use sorting/filtering to manage large lists.

#### Convert to MP3
- Ensure FFmpeg is available in `ffmpeg/bin/`.
- Select MP3 as the output format.
- The app will automatically convert downloaded audio to MP3.

#### Error Recovery
- If a download fails, review the error message.
- Click Retry or Clear All to reset the UI and try again.

### 4. Tips & Troubleshooting
- For best results, keep yt-dlp and FFmpeg up to date.
- If you encounter issues, check the log messages for details.
- The app is portable—no installation required. Just run the `.exe`.

---

## Contact & Support
**Author:** [Your Name]
**Email:** [your.email@example.com]
**LinkedIn:** [linkedin.com/in/yourprofile]

---

*Thank you for using IDM Video Downloader! For more help, see the full documentation or contact the author.*
