# YouTube Metadata Comparison

## ✅ Currently Implemented in Advanced Playlist Manager

### Video Metadata
- ✅ **Title** - Column: `title`
- ✅ **Publish date** - Column: `upload_date` (YYYY-MM-DD format)
- ✅ **Duration** - Column: `duration` (mm:ss format)
- ✅ **View count** - Column: `views` (with M/K notation)
- ✅ **Like count** - Column: `likes` (with M/K notation)
- ❌ **Dislike count** - NOT available (YouTube API removed dislikes in 2021)
- ✅ **Channel name** - Column: `uploader`
- ✅ **Channel ID** - Column: `channel_id`
- ✅ **Video ID** - Column: `video_id`
- ✅ **URL** - Column: `url`
- ✅ **Tags** - Column: `tags` (count only)
- ✅ **Categories** - Column: `category`
- ❌ **Thumbnails** - NOT displayed (but available in metadata)
- ❌ **Description** - NOT displayed (but available in metadata)

### Comment Data
- ✅ **Comment count** - Column: `comments` (with M/K notation)
- ❌ **Top-level comments** - NOT fetched
- ❌ **Replies to comments** - NOT fetched
- ❌ **Comment details** - NOT fetched

### Channel Data
- ✅ **Number of subscribers** - Column: `subscribers` (channel_follower_count)
- ✅ **Channel ID** - Column: `channel_id`
- ✅ **Verified status** - Column: `verified` (✓ or -)
- ❌ **Channel description** - NOT fetched
- ❌ **Channel creation date** - NOT fetched
- ❌ **Total videos** - NOT fetched
- ❌ **Channel banner/icon** - NOT fetched

### Playlist Data
- ✅ **Playlist title** - Available in playlist_info
- ✅ **List of video IDs** - All videos fetched
- ✅ **Number of videos** - Displayed in UI
- ❌ **Playlist description** - NOT displayed
- ❌ **Playlist ID** - NOT displayed

### Captions/Subtitles
- ✅ **Available languages** - Column: `subtitles` (language codes)
- ❌ **Downloadable transcript** - NOT implemented

### Technical/Format Data
- ✅ **Resolution** - Column: `resolution` (widthxheight)
- ✅ **FPS** - Column: `fps`
- ✅ **Format/Codec** - Column: `format` (VP9, H264, etc.)
- ✅ **Aspect ratio** - Column: `aspect_ratio`
- ✅ **File size estimate** - Column: `size`

### Additional Metadata
- ✅ **Availability** - Column: `availability` (public, unlisted, etc.)
- ✅ **Location** - Column: `location` (filming location)
- ✅ **Chapters count** - Column: `chapters`
- ✅ **Live status** - Column: `live_status` (not_live, is_live, was_live)
- ✅ **Age limit** - Column: `age_limit`
- ✅ **Language** - Column: `language`

---

## ❌ NOT Implemented / Missing

### Video Metadata
- ❌ **Description** (full text) - Available but not displayed
- ❌ **Dislike count** - Not available from YouTube API anymore
- ❌ **Thumbnail URLs** - Available but not displayed/downloaded
- ❌ **Full tags list** - Only showing count, not actual tags

### Comments
- ❌ **Individual comments** - Only total count shown
- ❌ **Comment authors**
- ❌ **Comment timestamps**
- ❌ **Comment likes**
- ❌ **Comment replies**

### Channel Data
- ❌ **Channel description**
- ❌ **Channel creation date**
- ❌ **Total channel videos**
- ❌ **Channel banner image**
- ❌ **Channel icon/avatar**
- ❌ **Upload playlist ID**

### Related Content
- ❌ **Related videos** (IDs, titles)
- ❌ **Recommendations**
- ❌ **Where video is embedded** (external sites)

### Engagement Over Time
- ❌ **Trending view-counts** (historical data)
- ❌ **Growth of likes/comments** (time-series)

### Live Streams
- ❌ **Live chat capture/archived chat**
- ❌ **Concurrent viewers** (during live)
- ❌ **Stream start/end times** (detailed)

### Embedded Data
- ❌ **Embed URL**
- ❌ **Embed player parameters**

---

## 🔍 Available in yt-dlp but NOT Displayed

These fields are available in the metadata but not currently shown in columns:

1. **description** - Full video description text
2. **thumbnail** - Main thumbnail URL
3. **thumbnails** - Array of all thumbnail sizes
4. **tags** - Full list of tags (we only show count)
5. **heatmap** - Viewer engagement heatmap (100 points)
6. **chapters** - Chapter list with timestamps (we only show count)
7. **duration_string** - Human-readable duration
8. **release_timestamp** - Exact release time
9. **timestamp** - Unix timestamp
10. **filesize** / **filesize_approx** - Actual file size
11. **webpage_url_basename** - URL components
12. **extractor** / **extractor_key** - Source info

---

## 💡 Recommendations for Enhancement

### High Priority (Easy to Add)
1. **Description column** - Truncated preview (first 50 chars)
2. **Full tags list** - Show actual tags, not just count
3. **Thumbnail preview** - Already have thumbnail_label, could populate on selection
4. **Full chapter list** - Show chapter titles with timestamps

### Medium Priority
5. **Download actual thumbnails** - Save thumbnail images to disk
6. **Related videos** - If available in yt-dlp metadata
7. **Heatmap visualization** - Show engagement graph
8. **Actual filesize** - Instead of estimated size

### Low Priority (Complex)
9. **Comment fetching** - Requires separate API calls
10. **Historical tracking** - Would need database/storage
11. **Live chat** - Real-time capture during streams

### Not Feasible
- **Dislike count** - Removed by YouTube API
- **Embed tracking** - Would require web scraping
- **External embed locations** - Not available via API

---

## Summary

**Currently Implemented:** ~26 out of ~50 possible fields (52%)

**Strengths:**
- Comprehensive video metadata ✅
- Good engagement metrics (views, likes, comments, subscribers) ✅
- Technical details (resolution, fps, codec, aspect ratio) ✅
- Availability and content info (age limit, location, verified) ✅

**Main Gaps:**
- Individual comments and replies ❌
- Detailed channel information ❌
- Related/recommended videos ❌
- Historical/trending data ❌
- Embedded content tracking ❌
