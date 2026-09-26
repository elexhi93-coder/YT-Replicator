#!/usr/bin/env python3
"""
Simple CLI version of the IDM Video Downloader for testing
"""

import yt_dlp
import os
from pathlib import Path
import sys

def list_formats(url):
    """List available formats for a video"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            print(f"\nTitle: {info.get('title', 'N/A')}")
            print(f"Uploader: {info.get('uploader', 'N/A')}")
            print(f"Duration: {info.get('duration', 'N/A')} seconds")
            print(f"View Count: {info.get('view_count', 'N/A')}")
            
            print("\nAvailable formats:")
            print("-" * 80)
            print(f"{'Format ID':<12} {'Extension':<10} {'Resolution':<12} {'File Size':<12} {'Note'}")
            print("-" * 80)
            
            formats = []
            if 'formats' in info:
                for fmt in info['formats']:
                    if fmt.get('vcodec') != 'none':  # Video formats
                        format_id = fmt.get('format_id', 'N/A')
                        ext = fmt.get('ext', 'N/A')
                        height = fmt.get('height')
                        width = fmt.get('width')
                        filesize = fmt.get('filesize')
                        format_note = fmt.get('format_note', '')
                        
                        resolution = f"{width}x{height}" if width and height else "N/A"
                        
                        if filesize:
                            size_mb = f"{filesize / (1024 * 1024):.1f}MB"
                        else:
                            size_mb = "N/A"
                            
                        print(f"{format_id:<12} {ext:<10} {resolution:<12} {size_mb:<12} {format_note}")
                        formats.append(format_id)
            
            print(f"{'best':<12} {'auto':<10} {'best':<12} {'auto':<12} Best quality")
            print(f"{'worst':<12} {'auto':<10} {'worst':<12} {'auto':<12} Worst quality")
            print(f"{'bestaudio':<12} {'audio':<10} {'audio-only':<12} {'auto':<12} Audio only")
            
            return formats
            
    except Exception as e:
        print(f"Error: {e}")
        return []

def download_video(url, format_id='best', output_path=None):
    """Download video with specified format"""
    if output_path is None:
        output_path = str(Path.home() / "Downloads")
    
    ydl_opts = {
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'format': format_id,
    }
    
    # If audio only, convert to MP3
    if format_id == 'bestaudio':
        ydl_opts.update({
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"\nDownloading with format: {format_id}")
            print(f"Output directory: {output_path}")
            print("-" * 50)
            ydl.download([url])
            print("\nDownload completed successfully!")
            
    except Exception as e:
        print(f"Download error: {e}")

def main():
    """Main CLI function"""
    print("IDM Video Downloader - CLI Version")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python cli_downloader.py <URL> [format_id] [output_path]")
        print("\nExamples:")
        print("  python cli_downloader.py 'https://youtube.com/watch?v=...'")
        print("  python cli_downloader.py 'https://youtube.com/watch?v=...' best")
        print("  python cli_downloader.py 'https://youtube.com/watch?v=...' bestaudio")
        print("  python cli_downloader.py 'https://youtube.com/watch?v=...' 720p ~/Downloads")
        return
    
    url = sys.argv[1]
    format_id = sys.argv[2] if len(sys.argv) > 2 else 'best'
    output_path = sys.argv[3] if len(sys.argv) > 3 else None
    
    # If format_id is 'list', show available formats
    if format_id.lower() == 'list':
        list_formats(url)
        return
    
    # Show available formats first
    print("Fetching video information...")
    formats = list_formats(url)
    
    if not formats:
        print("Could not fetch video information.")
        return
    
    # Ask user for confirmation
    print(f"\nProceed with download using format '{format_id}'? (y/n): ", end="")
    response = input().lower().strip()
    
    if response in ['y', 'yes']:
        download_video(url, format_id, output_path)
    else:
        print("Download cancelled.")

if __name__ == "__main__":
    main()