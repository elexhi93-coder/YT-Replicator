#!/usr/bin/env python3
"""
Channel Content Downloader

Target a YouTube channel (handle or URL) and operate on a specific content type:
- videos (long-form)
- shorts
- streams

Features:
- List or download items
- Filter by title keywords (include/exclude)
- Filter by duration (min/max seconds)
- Limit max items
- Select video quality or audio (with optional MP3 conversion via FFmpeg)
- Choose output folder

Usage examples:
  python channel_content_downloader.py https://www.youtube.com/@SunsetDrama-z8o --type videos --mode list --limit 30
  python channel_content_downloader.py @SunsetDrama-z8o --type shorts --mode download --download video --quality 720p --limit 20
  python channel_content_downloader.py @SunsetDrama-z8o --type videos --mode download --download audio --audio mp3-192 --include "OST|Trailer" --min-duration 120

Notes:
- MP3 conversion requires FFmpeg. If not found, audio will download in original format (m4a/webm).
- This script uses yt-dlp and follows the same dependency environment as the GUI app.
"""

import argparse
import os
import re
import sys
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

import yt_dlp

APP_DIR = Path(__file__).parent


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available (portable bin inside app or system PATH)."""
    # Portable ffmpeg in app folder
    portable_ffmpeg = APP_DIR / "ffmpeg" / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if portable_ffmpeg.exists():
        ffmpeg_bin_dir = str(portable_ffmpeg.parent)
        if ffmpeg_bin_dir not in os.environ.get('PATH', ''):
            os.environ['PATH'] = ffmpeg_bin_dir + os.pathsep + os.environ.get('PATH', '')
        return True
    # System ffmpeg
    return shutil.which('ffmpeg') is not None


def normalize_channel_url(channel: str, content_type: str) -> str:
    """Normalize user input (handle or URL) to a proper channel subpage URL by content type."""
    # Accept @handle, /channel/ID, full URLs, etc.
    base = "https://www.youtube.com/"
    suffix = {
        'videos': 'videos',
        'shorts': 'shorts',
        'streams': 'streams'
    }[content_type]

    if channel.startswith('@'):
        return f"{base}{channel}/{suffix}"
    if channel.startswith('http://') or channel.startswith('https://'):
        # Ensure it ends with the desired suffix
        url = channel.rstrip('/')
        if url.endswith(('/videos', '/shorts', '/streams')):
            # Replace with target suffix if different
            for tab in ('/videos', '/shorts', '/streams'):
                if url.endswith(tab) and not url.endswith(f'/{suffix}'):
                    url = url[: -len(tab)]
                    break
        return f"{url}/{suffix}" if not url.endswith(f'/{suffix}') else url
    # Fallback: assume it's a channel path like channel/UC... or c/Name or user/Name
    return f"{base}{channel.strip('/')}/{suffix}"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download or list specific content types from a YouTube channel.")
    p.add_argument('channel', help="Channel handle (@name) or URL")
    p.add_argument('--type', dest='content_type', choices=['videos', 'shorts', 'streams'], default='videos',
                   help="Content type tab to target (default: videos)")
    p.add_argument('--mode', choices=['list', 'download'], default='list', help="List items or download them")
    p.add_argument('--limit', type=int, default=0, help="Max number of items to process (0 = no limit)")

    # Filters
    p.add_argument('--include', help="Regex to include by title (case-insensitive)")
    p.add_argument('--exclude', help="Regex to exclude by title (case-insensitive)")
    p.add_argument('--min-duration', type=int, default=0, help="Minimum duration in seconds (0 = no min)")
    p.add_argument('--max-duration', type=int, default=0, help="Maximum duration in seconds (0 = no max)")
    p.add_argument('--since-days', type=int, default=0, help="Only include uploads within the last N days (0 = no filter)")

    # Download settings
    p.add_argument('--download', choices=['video', 'audio'], default='video', help="Download as video or audio")
    p.add_argument('--quality', default='best', help="Video quality: best or e.g. 1080p / 720p / 480p")
    p.add_argument('--audio', default='best', choices=['best', 'mp3-320', 'mp3-192', 'mp3-128'],
                   help="Audio mode: best (original) or MP3 with bitrate")
    p.add_argument('--out', dest='output', default=str(Path.home() / 'Downloads'), help="Output directory")
    p.add_argument('--dry-run', action='store_true', help="Show what would download without downloading")

    return p.parse_args()


def fetch_channel_entries(url: str) -> Dict[str, Any]:
    """Use yt-dlp to extract the channel tab entries (flat for speed)."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'no_check_certificate': True,
        'extract_flat': 'in_playlist',
        'socket_timeout': 30,
        'ignoreerrors': True,
        'playlistend': None,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info or {}


def entry_to_url(entry: Dict[str, Any]) -> Optional[str]:
    vid = entry.get('id') or entry.get('url')
    if not vid:
        return None
    return vid if vid.startswith('http') else f"https://www.youtube.com/watch?v={vid}"


def fetch_full_info(video_url: str) -> Optional[Dict[str, Any]]:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'no_check_certificate': True,
        'socket_timeout': 30,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=False)
    except Exception:
        return None


def passes_filters(info: Dict[str, Any], args: argparse.Namespace) -> bool:
    title = (info.get('title') or '').strip()
    duration = int(info.get('duration') or 0)

    if args.include and not re.search(args.include, title, re.IGNORECASE):
        return False
    if args.exclude and re.search(args.exclude, title, re.IGNORECASE):
        return False
    if args.min_duration and duration and duration < args.min_duration:
        return False
    if args.max_duration and duration and duration > args.max_duration:
        return False

    if args.since_days:
        # upload_date is YYYYMMDD
        up = info.get('upload_date')
        if up and len(str(up)) == 8:
            try:
                dt = datetime.strptime(str(up), '%Y%m%d')
                if dt < datetime.now() - timedelta(days=args.since_days):
                    return False
            except Exception:
                pass
    return True


def build_format_string(args: argparse.Namespace) -> str:
    """Build a yt-dlp format string based on mode, quality, and FFmpeg availability.

    - For audio: bestaudio/best (postprocessors may convert to MP3 if FFmpeg present)
    - For video with FFmpeg: bestvideo+bestaudio (merge) with height constraint when provided
    - For video without FFmpeg: prefer progressive formats (must include both audio and video)
    """
    if args.download == 'audio':
        return 'bestaudio/best'

    # Video path
    q = args.quality.strip().lower()
    no_ffmpeg = not check_ffmpeg()

    # If FFmpeg is unavailable, choose progressive (single-file) formats only
    if no_ffmpeg:
        if q == 'best':
            return 'best[vcodec!=none][acodec!=none]/best'
        # Expecting like '1080p'
        height = re.sub(r'\D', '', q)
        if height.isdigit():
            return (
                f"best[height<={height}][vcodec!=none][acodec!=none]"
                "/best[vcodec!=none][acodec!=none]"
                "/best"
            )
        return 'best[vcodec!=none][acodec!=none]/best'

    # FFmpeg available: allow bestvideo+bestaudio (merged) and constrain by height if provided
    if q == 'best':
        return 'bestvideo+bestaudio/best'
    height = re.sub(r'\D', '', q)
    if height.isdigit():
        return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
    return 'bestvideo+bestaudio/best'


def build_postprocessors(args: argparse.Namespace) -> Optional[List[Dict[str, Any]]]:
    if args.download == 'audio' and args.audio.startswith('mp3'):
        bitrate = args.audio.split('-')[1] if '-' in args.audio else '320'
        if check_ffmpeg():
            return [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate,
            }]
        else:
            print("[i] FFmpeg not found - audio will be saved in original format (m4a/webm)")
            return None
    return None


def download_video(video_url: str, args: argparse.Namespace) -> None:
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    fmt_string = build_format_string(args)
    # If FFmpeg is absent and the format string still contains a '+' (split A/V), fall back to best progressive
    if '+' in fmt_string and not check_ffmpeg():
        fmt_string = 'best[vcodec!=none][acodec!=none]/best'

    ydl_opts: Dict[str, Any] = {
        'outtmpl': str(outdir / '%(title)s.%(ext)s'),
        'quiet': False,
        'no_warnings': True,
        'format': fmt_string,
    }
    pp = build_postprocessors(args)
    if pp:
        ydl_opts['postprocessors'] = pp

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])


def main():
    args = parse_args()
    target_url = normalize_channel_url(args.channel, args.content_type)
    print(f"[+] Target: {target_url}")

    # Extract channel tab entries (flat)
    info = fetch_channel_entries(target_url)
    if not info or info.get('_type') != 'playlist':
        print("[!] Could not extract channel tab entries.")
        sys.exit(1)

    entries = info.get('entries') or []
    total = len(entries)
    print(f"[+] Found {total} items in {args.content_type} tab")

    # Apply limit
    if args.limit and args.limit > 0:
        entries = entries[: args.limit]

    # For accurate filtering (duration/date), fetch per-video info
    processed = []
    for e in entries:
        url = entry_to_url(e)
        if not url:
            continue
        meta = fetch_full_info(url) or {}
        title = meta.get('title') or e.get('title') or 'Unknown'
        if not meta:
            # If full info failed, still allow listing title/URL
            meta = {'title': title, 'duration': 0, 'upload_date': None, 'webpage_url': url}
        else:
            meta['webpage_url'] = url
        if passes_filters(meta, args):
            processed.append(meta)

    if args.mode == 'list' or args.dry_run:
        print("\n=== Matches ===")
        for i, m in enumerate(processed, 1):
            dur = int(m.get('duration') or 0)
            mins, secs = divmod(dur, 60)
            up = m.get('upload_date')
            up_str = f"{up[:4]}-{up[4:6]}-{up[6:8]}" if up else "N/A"
            print(f"{i:3d}. {m.get('title')[:80]}\n     Duration: {mins:02d}:{secs:02d} | Date: {up_str}\n     URL: {m.get('webpage_url')}")
        print(f"\n[+] Total matches: {len(processed)}")
        if args.mode == 'list':
            return

    # Download mode
    print(f"\n[+] Downloading {len(processed)} items to: {args.output}")
    for idx, m in enumerate(processed, 1):
        print(f"\n[{idx}/{len(processed)}] {m.get('title')}")
        try:
            download_video(m['webpage_url'], args)
        except Exception as e:
            print(f"[!] Failed: {e}")


if __name__ == '__main__':
    main()
