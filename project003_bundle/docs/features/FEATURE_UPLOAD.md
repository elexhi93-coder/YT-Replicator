# Multi-Platform Upload Feature

IDM Video Downloader now supports uploading downloaded videos to multiple platforms simultaneously.

## Supported Platforms

| Platform | API | Features |
|----------|-----|----------|
| **YouTube** | Data API v3 | Resumable upload, thumbnails, scheduling, categories |
| **Dailymotion** | Partner API | Chunked upload, thumbnails, channels |
| **TikTok** | Content Posting API | Direct/chunked upload, captions, privacy |
| **Facebook** | Graph API v18.0 | Pages support, resumable upload, scheduling |

## Getting Started

### 1. Configure Platform Credentials

Each platform requires OAuth 2.0 credentials. Here's how to get them:

#### YouTube
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project
3. Enable "YouTube Data API v3"
4. Go to "Credentials" → "Create Credentials" → "OAuth client ID"
5. Select "Desktop app" as application type
6. Copy the Client ID and Client Secret

#### Dailymotion
1. Go to [Dailymotion Partner HQ](https://www.dailymotion.com/partner)
2. Navigate to "API" section
3. Create a new application
4. Copy the API Key (Client ID) and API Secret

#### TikTok
1. Go to [TikTok for Developers](https://developers.tiktok.com)
2. Create a developer account
3. Create an app and request "Content Posting API" access
4. Copy the Client Key and Client Secret

#### Facebook
1. Go to [Meta for Developers](https://developers.facebook.com)
2. Create a new app (Consumer type)
3. Add "Facebook Login" and "Video Upload" products
4. Copy the App ID and App Secret

### 2. Using the Upload Manager GUI

```python
from uploaders.upload_window import show_upload_window
import tkinter as tk

root = tk.Tk()
show_upload_window(root)
root.mainloop()
```

### 3. Programmatic Usage

```python
from uploaders import UploadManager, Platform, VideoMetadata

# Create manager
manager = UploadManager()

# Configure platforms
manager.configure_platform(
    Platform.YOUTUBE,
    client_id='your_youtube_client_id',
    client_secret='your_youtube_client_secret'
)

manager.configure_platform(
    Platform.FACEBOOK,
    client_id='your_facebook_app_id',
    client_secret='your_facebook_app_secret',
    page_id='optional_page_id'  # For page uploads
)

# Authenticate (opens browser for OAuth)
manager.authenticate_platform(Platform.YOUTUBE, callback=lambda success: print(f"Auth: {success}"))

# Create metadata
metadata = VideoMetadata(
    title='My Downloaded Video',
    description='Video description here',
    tags=['gaming', 'tutorial', 'guide'],
    category='Gaming',
    privacy='private',  # private, unlisted, or public
    thumbnail_path='/path/to/thumbnail.jpg'  # Optional
)

# Platform-specific settings
metadata.youtube_settings = {
    'madeForKids': False,
    'embeddable': True
}

metadata.tiktok_settings = {
    'disable_duet': False,
    'disable_comment': False
}

# Add upload job
job = manager.add_upload(
    video_path='/path/to/video.mp4',
    metadata=metadata,
    platforms=[Platform.YOUTUBE, Platform.FACEBOOK],
    scheduled_time=None  # Optional: Unix timestamp for scheduled upload
)

# Register callbacks
manager.on_job_change(lambda job: print(f"Job {job.id}: {job.status}"))
manager.on_progress(lambda job, progress: print(f"Progress: {progress.percent:.1f}%"))

# Start processing
manager.start()

# Wait for completion or run in background
import time
while job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
    time.sleep(1)

# Check results
for platform, result in job.platform_results.items():
    if result.success:
        print(f"{platform}: {result.video_url}")
    else:
        print(f"{platform}: Failed - {result.error_message}")

# Stop manager when done
manager.stop()
```

## Features

### Upload Queue
- Priority-based queue management
- Multiple concurrent uploads
- Pause/resume functionality
- Automatic retry on failure

### Progress Tracking
- Real-time upload progress
- Speed and ETA calculations
- Per-platform status tracking

### Scheduling
- Schedule uploads for future times
- Platform-specific publish scheduling

### Persistence
- Queue state saved to disk
- Resume uploads after restart

## Architecture

```
uploaders/
├── __init__.py           # Package exports
├── base_uploader.py      # Abstract base class
├── auth_manager.py       # OAuth token management
├── youtube_uploader.py   # YouTube implementation
├── dailymotion_uploader.py  # Dailymotion implementation
├── tiktok_uploader.py    # TikTok implementation
├── facebook_uploader.py  # Facebook implementation
├── upload_manager.py     # Central queue manager
└── upload_window.py      # GUI interface
```

## Platform Limits

| Platform | Max File Size | Max Duration | Formats |
|----------|--------------|--------------|---------|
| YouTube | 256 GB | 12 hours | mp4, avi, mov, mkv, webm, etc. |
| Dailymotion | 60 min | 60 minutes | mp4, avi, mov, mkv, webm, etc. |
| TikTok | 4 GB | 10 minutes | mp4, webm, mov |
| Facebook | 10 GB | 240 minutes | mp4, avi, mov, mkv, etc. |

## Error Handling

The upload system handles various error types:

- **AuthenticationError**: Token expired or invalid
- **RateLimitError**: API rate limit exceeded (with retry-after)
- **QuotaExceededError**: Daily/monthly quota exceeded
- **UploadError**: General upload failures

## Security Notes

- OAuth tokens are stored locally in `~/.idm_tokens.json`
- Platform credentials stored in `~/.idm_platform_configs.json`
- Tokens are refreshed automatically when expired
- Use "private" privacy setting for initial uploads

## Troubleshooting

### "Authentication expired"
- Re-authenticate with the platform
- Check if app credentials are still valid

### "Quota exceeded"
- YouTube: Wait 24 hours or request quota increase
- Check platform developer console for usage stats

### "Rate limited"
- Wait for the specified retry-after period
- Reduce concurrent upload count

### "Upload failed"
- Check file format compatibility
- Verify file isn't corrupted
- Check network connectivity
