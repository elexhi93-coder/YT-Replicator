# Video Uploader - Multi-Platform Video Upload Application

A standalone GUI application for uploading videos to multiple platforms simultaneously.

**Version: 2.1.0**

## 🌐 Supported Platforms

| Platform | Max File Size | Features |
|----------|--------------|----------|
| **YouTube** | 256 GB | Resumable upload, thumbnails, categories, AI disclosure, sponsorship, localizations |
| **Dailymotion** | 2 GB | Channel support, geoblocking, hashtags, password protection, AI disclosure |
| **TikTok** | 4 GB | Direct & chunked upload, Duet/Stitch/Comments control, brand content |
| **Facebook** | 10 GB | Page support, resumable upload, secret videos, drafts |

## 🚀 Quick Start

### Running from Source
```bash
# Install dependencies (if needed)
pip install -r requirements.txt

# Run the application
python video_uploader.py

# Or use the batch file on Windows
run_uploader.bat
```

### Building Portable Executable
```bash
# Windows
build_uploader_portable.bat

# Output: dist/Video Uploader.exe
```

## 📖 Setup Guide

### 1. YouTube Setup
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable **YouTube Data API v3**
4. Go to Credentials → Create OAuth 2.0 Client ID
5. Select "Desktop app" as application type
6. Copy the Client ID and Client Secret

### 2. Dailymotion Setup
1. Go to [Dailymotion Partner HQ](https://www.dailymotion.com/partner)
2. Navigate to API section
3. Create a new application
4. Copy the API Key and API Secret

### 3. TikTok Setup
1. Go to [TikTok for Developers](https://developers.tiktok.com/)
2. Create a new app
3. Request **Content Posting API** access
4. Once approved, copy Client Key and Client Secret

### 4. Facebook Setup
1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create a new app (type: Consumer)
3. Add products: Facebook Login, Video API
4. Copy App ID and App Secret
5. (Optional) Get your Page ID for page uploads

## 🎯 Features

### Upload Queue
- Queue multiple uploads
- Priority-based processing
- Pause/Resume individual uploads
- Retry failed uploads
- Persistent queue (survives app restart)

### Multi-Platform Upload
- Upload to multiple platforms simultaneously
- Independent progress tracking per platform
- Platform-specific error handling

### Scheduling
- Schedule uploads for later
- Automatic upload at scheduled time

### OAuth Authentication
- Secure OAuth 2.0 with PKCE
- Token refresh handling
- Persistent token storage

### 🆕 Compliance & Disclosure Settings (v2.1.0)
Cross-platform compliance features:
- **Made for Kids (COPPA)** - Required disclosure for child-directed content
- **AI/Synthetic Content** - Disclose AI-generated content (YouTube, Dailymotion, TikTok)
- **Paid Promotion** - Sponsorship disclosure (YouTube)
- **Embedding Control** - Allow/disallow embedding on other websites

### 🆕 Platform-Specific Advanced Settings (v2.1.0)

| Platform | New Settings |
|----------|-------------|
| **YouTube** | License type (Standard/Creative Commons), Public stats visibility, Multi-language localizations, Recording date & location |
| **Dailymotion** | Country code, Geoblocking, Hashtags (separate from tags), Password protection, Expiry date, AI alteration flag |
| **TikTok** | Disable Duet, Disable Stitch, Disable Comments, Brand content toggles |
| **Facebook** | Secret video (unlisted), Save as draft, Content category, Sponsor ID |

### Metadata Templates
- Save reusable metadata templates
- Platform-specific descriptions
- Auto-apply title prefixes/suffixes

### Thumbnail Generator
- Extract frames from video
- Select custom thumbnail
- Automatic upload with video

## 🖥️ User Interface

```
┌─────────────────────────────────────────────────────────────────────┐
│  📤 Video Uploader                                            v1.0.0│
├────────────────────────────────┬────────────────────────────────────┤
│  Platforms                     │  [➕ New Upload] [🔄 Refresh]      │
│  ▶️ YouTube        ● ⚙️ 🔑     │  Filter: [All ▼]                   │
│  📺 Dailymotion    ○ ⚙️ 🔑     │  ┌───────────────────────────────┐ │
│  🎵 TikTok         ○ ⚙️ 🔑     │  │ Title     │ Platforms │ Status │ │
│  📘 Facebook       ○ ⚙️ 🔑     │  │ My Video  │ YT, FB    │ 45%   │ │
├────────────────────────────────│  │ Tutorial  │ YT        │ Queue │ │
│  Statistics                    │  │ Demo      │ All       │ Done  │ │
│  Total Jobs:           5       │  └───────────────────────────────┘ │
│  Queued:               2       │  [📋 Details] [⏸ Pause] [▶ Resume] │
│  Completed:            2       │  [🔄 Retry] [❌ Cancel]            │
│  Failed:               1       ├────────────────────────────────────┤
│  Success Rate:      80.0%      │                                    │
├────────────────────────────────│                                    │
│  Activity Log                  │                                    │
│  [12:00:00] ✅ Completed: ...  │                                    │
│  [11:58:30] 🔄 Uploading: ...  │                                    │
│  [11:58:00] ➕ Added: ...      │                                    │
└────────────────────────────────┴────────────────────────────────────┘
```

### Platform Status Icons
- ● Green: Logged in and ready
- ○ Orange: Configured but not logged in
- ○ Gray: Not configured

### Buttons
- ⚙️ Configure platform credentials
- 🔑 Log in / Authenticate

## 📁 File Structure

```
video_uploader.py           # Main application
run_uploader.bat            # Launch script (Windows)
video_uploader_portable.spec # PyInstaller build spec
build_uploader_portable.bat # Build script
uploaders/                  # Upload modules
    __init__.py
    base_uploader.py        # Base classes and types
    auth_manager.py         # OAuth management
    upload_manager.py       # Queue and job management
    youtube_uploader.py     # YouTube API
    dailymotion_uploader.py # Dailymotion API
    tiktok_uploader.py      # TikTok API
    facebook_uploader.py    # Facebook API
    upload_window.py        # GUI components
```

## ⚙️ Configuration Files

Configuration is stored in your home directory:
- `~/.video_uploader_configs.json` - Platform API credentials
- `~/.video_uploader_queue.json` - Upload queue state
- `~/.idm_tokens.json` - OAuth tokens

## 🔒 Security Notes

1. **API credentials** are stored locally on your machine
2. **OAuth tokens** are encrypted and stored in your home directory
3. **Never share** your configuration files with others
4. The app uses **PKCE** for enhanced OAuth security

## 🐛 Troubleshooting

### "No Platforms Ready" Error
- Configure at least one platform using the ⚙️ button
- Log in using the 🔑 button

### OAuth Login Issues
- Ensure port 8585 is available (used for OAuth callback)
- Try logging out and back in
- Check if your API credentials are correct

### Upload Fails Immediately
- Verify the video file exists and is accessible
- Check if the platform supports the video format
- Ensure you have upload permissions on the platform

### Quota Exceeded
- YouTube: Wait 24 hours or request quota increase
- Other platforms: Check platform-specific limits

## 📝 License

This is a standalone component from IDM Video Downloader.
For license information, see the main project README.

## 🤝 Contributing

Contributions are welcome! Please submit pull requests or issues on GitHub.
