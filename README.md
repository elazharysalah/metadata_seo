# Video Metadata Cleaner

A Python tool that removes AI traces and adds realistic human-like metadata to videos. Makes videos appear as if they were recorded on a phone or edited with common editing software.

## Quick Start

1. Install FFmpeg: `winget install FFmpeg`
2. Double-click **`run_cleaner.bat`** to launch the GUI

## Features

- **Removes all AI encoder traces** - Strips metadata that could identify AI-generated content
- **Realistic timestamps** - Generates believable creation dates
- **Human-like metadata** - Adds device profiles (iPhone, Samsung, Pixel) or editing software (Premiere, DaVinci, Final Cut)
- **Background Music** - Optionally add random music at 50% volume (stops when video ends)
- **Preserves video quality** - Uses stream copy when possible, no re-encoding needed
- **Batch processing** - Process entire folders at once
- **Sequential naming** - Outputs as 1.mp4, 2.mp4, etc.

## Requirements

- Python 3.8 or higher
- FFmpeg (must be installed and in PATH)

## Installation

### 1. Install FFmpeg

**Windows:**
```bash
winget install FFmpeg
```
Or download from https://ffmpeg.org/download.html and add to PATH.

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt install ffmpeg
```

### 2. Clone/Download this project

No Python packages needed - uses only standard library!

## Usage

### Basic Usage

```bash
python metadata_cleaner.py -i ./input_videos -o ./clean_videos
```

### Options

| Option | Description |
|--------|-------------|
| `-i, --input` | Input folder containing videos (required) |
| `-o, --output` | Output folder for cleaned videos (required) |
| `--consistent` | Use same device profile for all videos |
| `--phone` | Prefer phone profiles (default) |
| `--editor` | Prefer editing software profiles |
| `--verify` | Show metadata of first output file |

### Examples

**Process with random phone profiles:**
```bash
python metadata_cleaner.py -i C:\Videos\raw -o C:\Videos\cleaned
```

**Make all videos look like they came from one device:**
```bash
python metadata_cleaner.py -i ./videos -o ./output --consistent
```

**Make videos look like they were edited in software:**
```bash
python metadata_cleaner.py -i ./videos -o ./output --editor
```

**Verify the cleaned metadata:**
```bash
python metadata_cleaner.py -i ./videos -o ./output --verify
```

## Supported Formats

**Video Input:** MP4, MOV, AVI, MKV, WMV, FLV, WebM, M4V, MPEG, MPG, 3GP

**Audio Input:** MP3, WAV, AAC, M4A, FLAC, OGG, WMA, OPUS

**Output:** MP4 (optimized for web with faststart)

## Background Music Feature

When enabled, the tool will:
- Randomly select an audio file from your music folder for each video
- Mix the music at **50% volume** with the original video audio
- **Audio stops when video ends** - music is automatically trimmed to video length
- Each video gets a randomly selected track (great for variety)

## What Gets Cleaned

### Removed
- Original encoder information
- AI-specific metadata tags
- Creation software identifiers
- GPS/location data
- Original timestamps
- Custom metadata fields

### Added (Realistic)
- Device make/model (iPhone, Samsung, Pixel, etc.)
- Editing software (Premiere, DaVinci, Final Cut, CapCut)
- Realistic creation timestamps
- Standard video handler names
- Proper file modification dates

## Device Profiles

The tool randomly selects from realistic device profiles:

**Phones:**
- iPhone 14 Pro, iPhone 13
- Samsung Galaxy S23 Ultra, Galaxy S22
- Google Pixel 8 Pro, Pixel 7

**Editing Software:**
- Adobe Premiere Pro 24.0
- DaVinci Resolve 18.6
- Final Cut Pro 10.7
- CapCut 3.9.0

## Technical Details

- Uses stream copy (`-c:v copy -c:a copy`) to preserve original quality
- Falls back to high-quality re-encoding if stream copy fails
- Re-encode settings: H.264, CRF 18 (visually lossless), AAC 192kbps
- Adds `+faststart` flag for web optimization
- Sets file timestamps to match metadata timestamps

## Troubleshooting

### "FFmpeg not found"
Make sure FFmpeg is installed and in your system PATH. Test by running `ffmpeg -version` in terminal.

### "Stream copy failed"
Some video formats can't be copied directly to MP4. The tool will automatically re-encode in high quality.

### Videos not detected
Check that your videos have supported extensions. The tool is case-insensitive.

## License

MIT License - Free to use and modify.
