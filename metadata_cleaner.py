"""
Video Metadata Cleaner
Removes AI traces and adds realistic human-like metadata to videos.
"""

import os
import sys
import subprocess
import random
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import argparse


# Common phone/camera models for realistic metadata
DEVICE_PROFILES = [
    {
        "make": "Apple",
        "model": "iPhone 14 Pro",
        "software": "17.4.1",
        "handler": "Apple Video Media Handler"
    },
    {
        "make": "Apple", 
        "model": "iPhone 13",
        "software": "16.6",
        "handler": "Apple Video Media Handler"
    },
    {
        "make": "Samsung",
        "model": "Galaxy S23 Ultra",
        "software": "One UI 6.0",
        "handler": "VideoHandle"
    },
    {
        "make": "Samsung",
        "model": "Galaxy S22",
        "software": "One UI 5.1",
        "handler": "VideoHandle"
    },
    {
        "make": "Google",
        "model": "Pixel 8 Pro",
        "software": "Android 14",
        "handler": "VideoHandle"
    },
    {
        "make": "Google",
        "model": "Pixel 7",
        "software": "Android 13",
        "handler": "VideoHandle"
    },
    # Editing software profiles (looks like human edited)
    {
        "make": "",
        "model": "",
        "software": "Adobe Premiere Pro 24.0",
        "handler": "Adobe Video Media Handler"
    },
    {
        "make": "",
        "model": "",
        "software": "DaVinci Resolve 18.6",
        "handler": "Blackmagic Video Handler"
    },
    {
        "make": "",
        "model": "",
        "software": "Final Cut Pro 10.7",
        "handler": "Apple Video Media Handler"
    },
    {
        "make": "",
        "model": "",
        "software": "CapCut 3.9.0",
        "handler": "VideoHandle"
    },
]

# Video extensions to process
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg', '.3gp'}


def check_ffmpeg():
    """Check if FFmpeg is installed and accessible."""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_video_info(input_path):
    """Get video information using ffprobe."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            str(input_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        print(f"  Warning: Could not read video info: {e}")
    
    return None


def generate_realistic_timestamp(base_time=None, variation_days=30):
    """Generate a realistic timestamp within a range."""
    if base_time is None:
        # Generate a timestamp within the last few months
        days_ago = random.randint(7, variation_days)
        base_time = datetime.now() - timedelta(days=days_ago)
    
    # Add some random hours/minutes for realism
    hours_offset = random.randint(8, 20)  # Daytime hours
    minutes_offset = random.randint(0, 59)
    seconds_offset = random.randint(0, 59)
    
    timestamp = base_time.replace(
        hour=hours_offset,
        minute=minutes_offset,
        second=seconds_offset,
        microsecond=0
    )
    
    return timestamp


def format_timestamp_for_metadata(dt):
    """Format datetime for video metadata."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def get_random_device_profile(prefer_phone=True):
    """Get a random device profile."""
    if prefer_phone:
        # 70% chance for phone, 30% for editing software
        phone_profiles = [p for p in DEVICE_PROFILES if p["make"]]
        editor_profiles = [p for p in DEVICE_PROFILES if not p["make"]]
        
        if random.random() < 0.7:
            return random.choice(phone_profiles)
        else:
            return random.choice(editor_profiles)
    else:
        return random.choice(DEVICE_PROFILES)


def clean_video_metadata(input_path, output_path, profile=None, timestamp=None, preserve_quality=True):
    """
    Clean video metadata and add realistic human-like metadata.
    
    Args:
        input_path: Path to input video
        output_path: Path to output video
        profile: Device profile to use (random if None)
        timestamp: Timestamp to use (random realistic if None)
        preserve_quality: If True, copy streams without re-encoding when possible
    """
    if profile is None:
        profile = get_random_device_profile()
    
    if timestamp is None:
        timestamp = generate_realistic_timestamp()
    
    timestamp_str = format_timestamp_for_metadata(timestamp)
    
    # Build FFmpeg command
    cmd = ['ffmpeg', '-y', '-i', str(input_path)]
    
    # Strip all existing metadata
    cmd.extend(['-map_metadata', '-1'])
    
    # Video/Audio codec settings
    if preserve_quality:
        # Try to copy streams without re-encoding (fastest, no quality loss)
        cmd.extend(['-c:v', 'copy', '-c:a', 'copy'])
    else:
        # Re-encode with high quality (removes any encoder-specific traces)
        cmd.extend([
            '-c:v', 'libx264',
            '-preset', 'slow',
            '-crf', '18',  # High quality
            '-c:a', 'aac',
            '-b:a', '192k'
        ])
    
    # Add clean metadata
    metadata_entries = [
        f'creation_time={timestamp_str}',
        f'date={timestamp_str}',
    ]
    
    if profile["make"]:
        metadata_entries.extend([
            f'make={profile["make"]}',
            f'model={profile["model"]}',
        ])
    
    if profile["software"]:
        metadata_entries.append(f'encoder={profile["software"]}')
        metadata_entries.append(f'software={profile["software"]}')
    
    # Add metadata to command
    for entry in metadata_entries:
        cmd.extend(['-metadata', entry])
    
    # Set handler name for streams (removes AI encoder traces)
    cmd.extend(['-metadata:s:v:0', f'handler_name={profile["handler"]}'])
    cmd.extend(['-metadata:s:a:0', 'handler_name=Sound Media Handler'])
    
    # Remove any potentially identifying stream metadata
    cmd.extend(['-metadata:s:v:0', 'encoder='])
    cmd.extend(['-metadata:s:a:0', 'encoder='])
    
    # Output settings
    cmd.extend([
        '-movflags', '+faststart',  # Web-optimized MP4
        str(output_path)
    ])
    
    # Run FFmpeg
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        if result.returncode != 0:
            # If copy mode failed, try re-encoding
            if preserve_quality and 'could not find tag' in result.stderr.lower():
                print("  Stream copy failed, re-encoding...")
                return clean_video_metadata(input_path, output_path, profile, timestamp, preserve_quality=False)
            
            print(f"  FFmpeg error: {result.stderr}")
            return False
        
        # Update file timestamps to match metadata
        try:
            os.utime(str(output_path), (timestamp.timestamp(), timestamp.timestamp()))
        except Exception:
            pass
        
        return True
        
    except Exception as e:
        print(f"  Error processing video: {e}")
        return False


def process_folder(input_folder, output_folder, use_consistent_profile=False, prefer_phone=True):
    """
    Process all videos in a folder.
    
    Args:
        input_folder: Path to folder containing input videos
        output_folder: Path to output folder
        use_consistent_profile: If True, use same device profile for all videos
        prefer_phone: If True, prefer phone profiles over editing software
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)
    
    if not input_path.exists():
        print(f"Error: Input folder '{input_folder}' does not exist.")
        return False
    
    # Create output folder
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Find all video files
    video_files = []
    for file in sorted(input_path.iterdir()):
        if file.is_file() and file.suffix.lower() in VIDEO_EXTENSIONS:
            video_files.append(file)
    
    if not video_files:
        print(f"No video files found in '{input_folder}'")
        print(f"Supported formats: {', '.join(VIDEO_EXTENSIONS)}")
        return False
    
    print(f"\nFound {len(video_files)} video(s) to process")
    print(f"Output folder: {output_path.absolute()}\n")
    
    # Get consistent profile if requested
    consistent_profile = get_random_device_profile(prefer_phone) if use_consistent_profile else None
    
    # Generate timestamps that are slightly sequential (like a photo session)
    base_timestamp = generate_realistic_timestamp()
    
    successful = 0
    failed = 0
    
    for i, video_file in enumerate(video_files, 1):
        output_file = output_path / f"{i}.mp4"
        
        print(f"[{i}/{len(video_files)}] Processing: {video_file.name}")
        
        # Use consistent profile or generate new one
        profile = consistent_profile or get_random_device_profile(prefer_phone)
        
        # Generate sequential timestamp (adds 1-5 minutes between videos)
        timestamp = base_timestamp + timedelta(minutes=random.randint(1, 5) * (i - 1))
        
        print(f"  Profile: {profile['make']} {profile['model']}" if profile['make'] else f"  Profile: {profile['software']}")
        print(f"  Timestamp: {format_timestamp_for_metadata(timestamp)}")
        
        if clean_video_metadata(video_file, output_file, profile, timestamp):
            print(f"  Output: {output_file.name}")
            successful += 1
        else:
            print(f"  FAILED to process {video_file.name}")
            failed += 1
        
        print()
    
    print(f"\n{'='*50}")
    print(f"Processing complete!")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print(f"  Output folder: {output_path.absolute()}")
    
    return failed == 0


def verify_clean_metadata(video_path):
    """Verify that metadata has been cleaned (for testing)."""
    info = get_video_info(video_path)
    if info:
        print("\nMetadata verification:")
        print(json.dumps(info.get('format', {}).get('tags', {}), indent=2))
    return info


def main():
    parser = argparse.ArgumentParser(
        description='Clean video metadata and add realistic human-like metadata.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python metadata_cleaner.py -i ./input_videos -o ./clean_videos
  python metadata_cleaner.py -i C:/Videos/raw -o C:/Videos/cleaned --phone
  python metadata_cleaner.py -i ./videos -o ./output --consistent
        """
    )
    
    parser.add_argument('-i', '--input', required=True,
                        help='Input folder containing videos')
    parser.add_argument('-o', '--output', required=True,
                        help='Output folder for cleaned videos')
    parser.add_argument('--consistent', action='store_true',
                        help='Use same device profile for all videos (like batch from one device)')
    parser.add_argument('--phone', action='store_true', default=True,
                        help='Prefer phone profiles (default)')
    parser.add_argument('--editor', action='store_true',
                        help='Prefer editing software profiles')
    parser.add_argument('--verify', action='store_true',
                        help='Verify metadata after processing')
    
    args = parser.parse_args()
    
    # Check FFmpeg
    print("Checking FFmpeg installation...")
    if not check_ffmpeg():
        print("\nError: FFmpeg is not installed or not in PATH.")
        print("\nInstallation instructions:")
        print("  Windows: Download from https://ffmpeg.org/download.html")
        print("           or use: winget install FFmpeg")
        print("  macOS:   brew install ffmpeg")
        print("  Linux:   sudo apt install ffmpeg")
        sys.exit(1)
    
    print("FFmpeg found!\n")
    
    # Process
    prefer_phone = not args.editor
    success = process_folder(
        args.input,
        args.output,
        use_consistent_profile=args.consistent,
        prefer_phone=prefer_phone
    )
    
    # Verify if requested
    if args.verify and success:
        output_path = Path(args.output)
        first_video = next(output_path.glob("*.mp4"), None)
        if first_video:
            verify_clean_metadata(first_video)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
