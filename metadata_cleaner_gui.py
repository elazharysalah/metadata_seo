"""
Video Metadata Cleaner - GUI Version
Modern interface for cleaning video metadata with merge support.
"""

import os
import sys
import subprocess
import random
import json
import threading
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


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

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg', '.3gp'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg', '.wma', '.opus'}


class ModernStyle:
    """Modern color scheme and styling."""
    BG_DARK = "#1a1a2e"
    BG_CARD = "#16213e"
    BG_INPUT = "#0f3460"
    ACCENT = "#e94560"
    ACCENT_HOVER = "#ff6b6b"
    TEXT = "#ffffff"
    TEXT_DIM = "#a0a0a0"
    SUCCESS = "#4ecca3"
    WARNING = "#ffc107"
    ERROR = "#ff6b6b"


class MetadataCleanerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Video Metadata Cleaner")
        self.root.geometry("750x850")
        self.root.configure(bg=ModernStyle.BG_DARK)
        self.root.resizable(True, True)
        self.root.minsize(700, 750)
        
        # Variables
        self.mode = tk.StringVar(value="folder")  # "folder" or "merge"
        self.input_folder = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.audio_folder = tk.StringVar()
        self.profile_type = tk.StringVar(value="phone")
        self.consistent_profile = tk.BooleanVar(value=False)
        self.music_option = tk.StringVar(value="no")  # "yes", "no", "mix"
        # Audio levels (0.0 – 1.0) for original track and background music
        self.orig_volume = tk.DoubleVar(value=1.0)   # 100%
        self.music_volume = tk.DoubleVar(value=0.5)  # 50%
        self.remove_watermark = tk.BooleanVar(value=False)
        self.watermark_preset = tk.StringVar(value="veo")  # "veo" or "custom"
        self.watermark_x = tk.StringVar(value="1520")
        self.watermark_y = tk.StringVar(value="1000")
        self.watermark_w = tk.StringVar(value="400")
        self.watermark_h = tk.StringVar(value="80")
        # Resolution of the video used when picking the custom region (for scaling)
        self.watermark_ref_w = tk.IntVar(value=1920)
        self.watermark_ref_h = tk.IntVar(value=1080)
        # Slow motion: playback speed as % of normal (100 = unchanged). Re-encodes when < 100%.
        self.slow_motion_enabled = tk.BooleanVar(value=False)
        self.playback_speed_percent = tk.DoubleVar(value=75.0)
        self.is_processing = False
        # Parallel FFmpeg jobs for folder mode (set per run)
        self._encode_workers = 1
        # Cached encoder probe: (name, arg_list) e.g. ('h264_amf', [...])
        self._hw_encoder = None
        self._delogo_supports_band = None
        
        # Merge mode data
        self.current_selection = []  # Current videos being selected for a combination
        self.merge_queue = []  # List of combinations to process: [[video1, video2], [video3, video4], ...]
        
        # Configure styles
        self.setup_styles()
        
        # Build UI
        self.create_ui()
        
        # Check FFmpeg on startup
        self.root.after(100, self.check_ffmpeg_status)

    @staticmethod
    def preferred_parallel_workers(job_count, heavy_encode=False, gpu_encode=False):
        """How many FFmpeg processes to run at once (CPU/GPU-aware)."""
        if job_count <= 1:
            return 1
        cpu = os.cpu_count() or 4
        if gpu_encode:
            # GPU encode: more parallel jobs OK (encoder load is on the GPU)
            return max(1, min(job_count, 3))
        if heavy_encode:
            return max(1, min(job_count, max(2, cpu // 2), 4))
        return max(1, min(job_count, max(2, cpu // 2), 3))

    def _probe_video_encoder(self, codec, extra_args):
        """Quick 1-frame encode to see if this encoder works on this machine."""
        out = Path(tempfile.gettempdir()) / f"mc_enc_probe_{codec}.mp4"
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'color=c=black:s=256x256:d=0.04',
            '-frames:v', '1',
            '-c:v', codec,
            *extra_args,
            str(out),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
            ok = result.returncode == 0 and out.exists() and out.stat().st_size > 0
        except Exception:
            ok = False
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass
        return ok

    def detect_video_encoder(self):
        """Pick fastest working encoder. Prefer GPU (NVENC/AMF/QSV), else fast libx264.
        No admin permission needed — GPU just needs working drivers."""
        if self._hw_encoder is not None:
            return self._hw_encoder

        # (codec, quality args after -c:v codec) — high quality ≈ CRF 18
        candidates = [
            (
                'h264_nvenc',
                ['-preset', 'p5', '-rc', 'vbr', '-cq', '19', '-b:v', '0', '-pix_fmt', 'yuv420p'],
                'NVIDIA NVENC (GPU)',
            ),
            (
                'h264_amf',
                # Keep args simple — qp_b / exotic options often break on real clips
                ['-quality', 'balanced', '-rc', 'cqp', '-qp_i', '18', '-qp_p', '20'],
                'AMD AMF (GPU)',
            ),
            (
                'h264_qsv',
                ['-global_quality', '18'],
                'Intel QSV (GPU)',
            ),
        ]
        for codec, extra, label in candidates:
            if self._probe_video_encoder(codec, extra):
                self._hw_encoder = (codec, ['-c:v', codec, *extra], label, True)
                return self._hw_encoder

        # CPU: veryfast + CRF 18 ≈ same look as medium/slow for most clips, much faster
        self._hw_encoder = (
            'libx264',
            ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p'],
            'libx264 CPU (veryfast)',
            False,
        )
        return self._hw_encoder

    def delogo_supports_band(self):
        """Some FFmpeg builds omit delogo's band= option — detect once."""
        if self._delogo_supports_band is not None:
            return self._delogo_supports_band
        out = Path(tempfile.gettempdir()) / "mc_delogo_band_probe.mp4"
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'color=c=black:s=320x240:d=0.04',
            '-frames:v', '1',
            '-vf', 'delogo=x=10:y=10:w=40:h=20:band=2',
            '-c:v', 'libx264', '-preset', 'ultrafast',
            str(out),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
            err = (result.stderr or "") + (result.stdout or "")
            self._delogo_supports_band = (
                result.returncode == 0 and "Option not found" not in err
            )
        except Exception:
            self._delogo_supports_band = False
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass
        return self._delogo_supports_band

    def cpu_encode_args(self):
        """Reliable CPU fallback encoder args."""
        workers = max(1, int(getattr(self, '_encode_workers', 1) or 1))
        cpu = os.cpu_count() or 4
        threads = max(1, cpu // workers) if workers > 1 else 0
        return [
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-crf', '18',
            '-pix_fmt', 'yuv420p',
            '-threads', str(threads),
        ]

    def video_encode_args(self, force_cpu=False):
        """Encoder args for re-encodes (watermark / slow-mo / merge). Uses GPU when available."""
        if force_cpu:
            return self.cpu_encode_args()
        codec, base_args, _label, is_gpu = self.detect_video_encoder()
        args = list(base_args)
        if codec == 'libx264':
            return self.cpu_encode_args()
        return args

    # Back-compat alias used nowhere after rename, but keep if any missed call sites
    def x264_encode_args(self):
        return self.video_encode_args()
    
    def setup_styles(self):
        """Configure ttk styles for modern look."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure colors
        style.configure("Dark.TFrame", background=ModernStyle.BG_DARK)
        style.configure("Card.TFrame", background=ModernStyle.BG_CARD)
        
        style.configure("Title.TLabel",
                       background=ModernStyle.BG_DARK,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 24, "bold"))
        
        style.configure("Subtitle.TLabel",
                       background=ModernStyle.BG_DARK,
                       foreground=ModernStyle.TEXT_DIM,
                       font=("Segoe UI", 10))
        
        style.configure("Card.TLabel",
                       background=ModernStyle.BG_CARD,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 11))
        
        style.configure("CardTitle.TLabel",
                       background=ModernStyle.BG_CARD,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 12, "bold"))
        
        style.configure("Status.TLabel",
                       background=ModernStyle.BG_DARK,
                       foreground=ModernStyle.TEXT_DIM,
                       font=("Segoe UI", 10))
        
        # Accent button
        style.configure("Accent.TButton",
                       background=ModernStyle.ACCENT,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 12, "bold"),
                       padding=(20, 12))
        style.map("Accent.TButton",
                 background=[("active", ModernStyle.ACCENT_HOVER)])
        
        # Regular button
        style.configure("TButton",
                       background=ModernStyle.BG_INPUT,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 10),
                       padding=(15, 8))
        style.map("TButton",
                 background=[("active", ModernStyle.ACCENT)])
        
        # Small button
        style.configure("Small.TButton",
                       background=ModernStyle.BG_INPUT,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 9),
                       padding=(8, 4))
        
        # Entry
        style.configure("TEntry",
                       fieldbackground=ModernStyle.BG_INPUT,
                       foreground=ModernStyle.TEXT,
                       insertcolor=ModernStyle.TEXT,
                       padding=10)
        
        # Radiobutton
        style.configure("Card.TRadiobutton",
                       background=ModernStyle.BG_CARD,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 10))
        
        style.configure("Dark.TRadiobutton",
                       background=ModernStyle.BG_DARK,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 10))
        
        # Checkbutton
        style.configure("Card.TCheckbutton",
                       background=ModernStyle.BG_CARD,
                       foreground=ModernStyle.TEXT,
                       font=("Segoe UI", 10))
        
        # Progressbar
        style.configure("Accent.Horizontal.TProgressbar",
                       background=ModernStyle.ACCENT,
                       troughcolor=ModernStyle.BG_INPUT,
                       thickness=8)
    
    def create_ui(self):
        """Create the main UI with scrollbar."""
        # Outer container
        outer_frame = ttk.Frame(self.root, style="Dark.TFrame")
        outer_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create canvas with scrollbar on the LEFT
        self.canvas = tk.Canvas(outer_frame, bg=ModernStyle.BG_DARK, 
                               highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(outer_frame, orient=tk.VERTICAL, 
                                 command=self.canvas.yview)
        
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        # Create scrollable frame inside canvas
        self.main_frame = ttk.Frame(self.canvas, style="Dark.TFrame", padding=30)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.main_frame, 
                                                        anchor=tk.NW)
        
        def configure_scroll(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        
        def configure_canvas_width(event):
            self.canvas.itemconfig(self.canvas_window, width=event.width)
        
        self.main_frame.bind("<Configure>", configure_scroll)
        self.canvas.bind("<Configure>", configure_canvas_width)
        
        def on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        self.canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # Title
        title_label = ttk.Label(self.main_frame, text="Video Metadata Cleaner",
                               style="Title.TLabel")
        title_label.pack(pady=(0, 5))
        
        subtitle_label = ttk.Label(self.main_frame,
                                  text="Remove AI traces • Add realistic metadata • Merge videos",
                                  style="Subtitle.TLabel")
        subtitle_label.pack(pady=(0, 20))
        
        # FFmpeg status
        self.ffmpeg_status = ttk.Label(self.main_frame, text="Checking FFmpeg...",
                                       style="Status.TLabel")
        self.ffmpeg_status.pack(pady=(0, 15))
        
        # Mode selector
        self.create_mode_selector(self.main_frame)
        
        # Container for mode-specific content
        self.mode_container = ttk.Frame(self.main_frame, style="Dark.TFrame")
        self.mode_container.pack(fill=tk.BOTH, expand=True)
        
        # Create both mode UIs (will show/hide based on selection)
        self.folder_frame = ttk.Frame(self.mode_container, style="Dark.TFrame")
        self.merge_frame = ttk.Frame(self.mode_container, style="Dark.TFrame")
        
        self.create_folder_mode_ui(self.folder_frame)
        self.create_merge_mode_ui(self.merge_frame)
        
        # Show folder mode by default
        self.folder_frame.pack(fill=tk.BOTH, expand=True)
        
        # Output folder (common to both modes)
        self.create_folder_card(self.main_frame, "Output Folder", "Select destination for processed videos",
                               self.output_folder, self.browse_output)
        
        # Music options card
        self.create_music_card(self.main_frame)
        
        # Watermark removal card (optional, for folder mode)
        self.create_watermark_card(self.main_frame)
        
        # Slow motion (folder + merge)
        self.create_slow_motion_card(self.main_frame)
        
        # Metadata options card
        self.create_options_card(self.main_frame)
        
        # Process button
        self.process_btn = ttk.Button(self.main_frame, text="Process Videos",
                                     style="Accent.TButton",
                                     command=self.start_processing)
        self.process_btn.pack(pady=20, ipadx=20)
        
        # Progress section
        self.progress_frame = ttk.Frame(self.main_frame, style="Dark.TFrame")
        self.progress_frame.pack(fill=tk.X, pady=10)
        
        self.progress_label = ttk.Label(self.progress_frame, text="",
                                        style="Status.TLabel")
        self.progress_label.pack()
        
        self.progress_bar = ttk.Progressbar(self.progress_frame,
                                           style="Accent.Horizontal.TProgressbar",
                                           mode='determinate', length=400)
        self.progress_bar.pack(pady=10)
        self.progress_bar.pack_forget()
        
        # Log area
        self.create_log_area(self.main_frame)
    
    def create_mode_selector(self, parent):
        """Create mode selection card."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.pack(fill=tk.X, pady=8)
        
        ttk.Label(card, text="Processing Mode", style="CardTitle.TLabel").pack(anchor=tk.W)
        
        mode_frame = ttk.Frame(card, style="Card.TFrame")
        mode_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Radiobutton(mode_frame, text="Folder Mode (process all videos in folder)",
                       variable=self.mode, value="folder",
                       style="Card.TRadiobutton",
                       command=self.switch_mode).pack(anchor=tk.W, pady=2)
        
        ttk.Radiobutton(mode_frame, text="Merge Mode (combine videos into one)",
                       variable=self.mode, value="merge",
                       style="Card.TRadiobutton",
                       command=self.switch_mode).pack(anchor=tk.W, pady=2)
    
    def switch_mode(self):
        """Switch between folder and merge mode."""
        if self.mode.get() == "folder":
            self.merge_frame.pack_forget()
            self.folder_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.folder_frame.pack_forget()
            self.merge_frame.pack(fill=tk.BOTH, expand=True)
    
    def create_folder_mode_ui(self, parent):
        """Create folder mode UI elements."""
        self.create_folder_card(parent, "Input Folder", "Select folder with videos",
                               self.input_folder, self.browse_input)
    
    def create_merge_mode_ui(self, parent):
        """Create merge mode UI elements."""
        # Current selection card
        select_card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        select_card.pack(fill=tk.X, pady=8)
        
        ttk.Label(select_card, text="Select Videos to Merge", style="CardTitle.TLabel").pack(anchor=tk.W)
        
        # Buttons row
        btn_frame = ttk.Frame(select_card, style="Card.TFrame")
        btn_frame.pack(fill=tk.X, pady=(10, 5))
        
        ttk.Button(btn_frame, text="+ Add Video(s)", 
                  command=self.add_videos_to_selection).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="Clear Selection", 
                  command=self.clear_selection).pack(side=tk.LEFT)
        
        # Current selection list
        self.selection_listbox = tk.Listbox(select_card, height=4, 
                                           bg=ModernStyle.BG_INPUT,
                                           fg=ModernStyle.TEXT,
                                           font=("Consolas", 9),
                                           selectmode=tk.SINGLE,
                                           relief=tk.FLAT)
        self.selection_listbox.pack(fill=tk.X, pady=(5, 10))
        
        # Add to queue button
        queue_btn_frame = ttk.Frame(select_card, style="Card.TFrame")
        queue_btn_frame.pack(fill=tk.X)
        
        ttk.Button(queue_btn_frame, text="Add Combination to Queue →", 
                  command=self.add_to_queue,
                  style="Accent.TButton").pack(side=tk.LEFT)
        ttk.Button(queue_btn_frame, text="Remove Selected", 
                  command=self.remove_from_selection).pack(side=tk.RIGHT)
        
        # Queue card
        queue_card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        queue_card.pack(fill=tk.X, pady=8)
        
        queue_header = ttk.Frame(queue_card, style="Card.TFrame")
        queue_header.pack(fill=tk.X)
        
        ttk.Label(queue_header, text="Merge Queue", style="CardTitle.TLabel").pack(side=tk.LEFT)
        self.queue_count_label = ttk.Label(queue_header, text="(0 combinations)", 
                                          style="Card.TLabel", foreground=ModernStyle.TEXT_DIM)
        self.queue_count_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # Queue list
        self.queue_listbox = tk.Listbox(queue_card, height=5, 
                                       bg=ModernStyle.BG_INPUT,
                                       fg=ModernStyle.TEXT,
                                       font=("Consolas", 9),
                                       selectmode=tk.SINGLE,
                                       relief=tk.FLAT)
        self.queue_listbox.pack(fill=tk.X, pady=(10, 5))
        
        # Queue controls
        queue_ctrl_frame = ttk.Frame(queue_card, style="Card.TFrame")
        queue_ctrl_frame.pack(fill=tk.X)
        
        ttk.Button(queue_ctrl_frame, text="Remove from Queue", 
                  command=self.remove_from_queue).pack(side=tk.LEFT)
        ttk.Button(queue_ctrl_frame, text="Clear Queue", 
                  command=self.clear_queue).pack(side=tk.RIGHT)
    
    def add_videos_to_selection(self):
        """Add videos to current selection."""
        files = filedialog.askopenfilenames(
            title="Select Videos to Merge",
            filetypes=[("Video files", " ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS))]
        )
        for file in files:
            if file not in self.current_selection:
                self.current_selection.append(file)
                self.selection_listbox.insert(tk.END, Path(file).name)
    
    def remove_from_selection(self):
        """Remove selected video from current selection."""
        selection = self.selection_listbox.curselection()
        if selection:
            idx = selection[0]
            self.selection_listbox.delete(idx)
            del self.current_selection[idx]
    
    def clear_selection(self):
        """Clear current selection."""
        self.current_selection = []
        self.selection_listbox.delete(0, tk.END)
    
    def add_to_queue(self):
        """Add current selection as a combination to the queue."""
        if len(self.current_selection) < 2:
            messagebox.showwarning("Selection Required", 
                                  "Please select at least 2 videos to merge.")
            return
        
        # Add to queue
        self.merge_queue.append(list(self.current_selection))
        
        # Update queue display
        names = " + ".join(Path(f).name for f in self.current_selection)
        self.queue_listbox.insert(tk.END, f"{len(self.merge_queue)}. {names}")
        self.queue_count_label.configure(text=f"({len(self.merge_queue)} combination{'s' if len(self.merge_queue) != 1 else ''})")
        
        # Clear selection for next combination
        self.clear_selection()
    
    def remove_from_queue(self):
        """Remove selected combination from queue."""
        selection = self.queue_listbox.curselection()
        if selection:
            idx = selection[0]
            self.queue_listbox.delete(idx)
            del self.merge_queue[idx]
            # Renumber remaining items
            self.queue_listbox.delete(0, tk.END)
            for i, combo in enumerate(self.merge_queue, 1):
                names = " + ".join(Path(f).name for f in combo)
                self.queue_listbox.insert(tk.END, f"{i}. {names}")
            self.queue_count_label.configure(text=f"({len(self.merge_queue)} combination{'s' if len(self.merge_queue) != 1 else ''})")
    
    def clear_queue(self):
        """Clear the entire queue."""
        self.merge_queue = []
        self.queue_listbox.delete(0, tk.END)
        self.queue_count_label.configure(text="(0 combinations)")
    
    def create_folder_card(self, parent, title, placeholder, variable, browse_command):
        """Create a folder selection card."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.pack(fill=tk.X, pady=8)
        
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor=tk.W)
        
        input_frame = ttk.Frame(card, style="Card.TFrame")
        input_frame.pack(fill=tk.X, pady=(8, 0))
        
        entry = ttk.Entry(input_frame, textvariable=variable, font=("Segoe UI", 10))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        entry.insert(0, placeholder)
        entry.configure(foreground=ModernStyle.TEXT_DIM)
        
        def on_focus_in(e):
            if entry.get() == placeholder:
                entry.delete(0, tk.END)
                entry.configure(foreground=ModernStyle.TEXT)
        
        def on_focus_out(e):
            if not entry.get():
                entry.insert(0, placeholder)
                entry.configure(foreground=ModernStyle.TEXT_DIM)
        
        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)
        
        browse_btn = ttk.Button(input_frame, text="Browse", command=browse_command)
        browse_btn.pack(side=tk.RIGHT, padx=(10, 0))
    
    def create_music_card(self, parent):
        """Create music options card."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.pack(fill=tk.X, pady=8)
        
        ttk.Label(card, text="Background Music", style="CardTitle.TLabel").pack(anchor=tk.W)
        
        options_frame = ttk.Frame(card, style="Card.TFrame")
        options_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Radiobutton(options_frame, text="No - Don't add music",
                       variable=self.music_option, value="no",
                       style="Card.TRadiobutton",
                       command=self.toggle_audio_input).pack(anchor=tk.W, pady=2)
        
        ttk.Radiobutton(options_frame, text="Yes - Add music to all videos (50% volume)",
                       variable=self.music_option, value="yes",
                       style="Card.TRadiobutton",
                       command=self.toggle_audio_input).pack(anchor=tk.W, pady=2)
        
        ttk.Radiobutton(options_frame, text="Mix - Randomly add music to some videos",
                       variable=self.music_option, value="mix",
                       style="Card.TRadiobutton",
                       command=self.toggle_audio_input).pack(anchor=tk.W, pady=2)
        
        # Audio folder input (initially hidden)
        self.audio_input_frame = ttk.Frame(card, style="Card.TFrame")
        self.audio_input_frame.pack(fill=tk.X, pady=(10, 0))
        self.audio_input_frame.pack_forget()
        
        ttk.Label(self.audio_input_frame, text="Music Folder:", 
                 style="Card.TLabel").pack(anchor=tk.W)
        
        audio_row = ttk.Frame(self.audio_input_frame, style="Card.TFrame")
        audio_row.pack(fill=tk.X, pady=(5, 0))
        
        self.audio_entry = ttk.Entry(audio_row, textvariable=self.audio_folder, 
                                    font=("Segoe UI", 10))
        self.audio_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        
        self.audio_browse_btn = ttk.Button(audio_row, text="Browse", 
                                          command=self.browse_audio)
        self.audio_browse_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        self.audio_info = ttk.Label(self.audio_input_frame, text="",
                                   style="Card.TLabel", foreground=ModernStyle.TEXT_DIM)
        self.audio_info.pack(anchor=tk.W, pady=(5, 0))
        
        # Original audio level slider
        orig_frame = ttk.Frame(card, style="Card.TFrame")
        orig_frame.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(orig_frame, text="Original audio level", style="Card.TLabel").pack(anchor=tk.W)
        orig_row = ttk.Frame(orig_frame, style="Card.TFrame")
        orig_row.pack(fill=tk.X, pady=(4, 0))
        self.orig_volume_label = ttk.Label(orig_row, text="100%", style="Card.TLabel")
        self.orig_volume_label.pack(side=tk.RIGHT)
        def on_orig_change(value):
            try:
                pct = int(float(value) * 100)
            except ValueError:
                pct = int(self.orig_volume.get() * 100)
            pct = max(0, min(100, pct))
            self.orig_volume_label.configure(text=f"{pct}%")
        self.orig_volume_scale = ttk.Scale(
            orig_row,
            from_=0.0,
            to=1.0,
            orient=tk.HORIZONTAL,
            variable=self.orig_volume,
            command=on_orig_change,
            length=220,
        )
        self.orig_volume_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # Initialize label text
        on_orig_change(self.orig_volume.get())
        
        # Background music level slider
        music_frame = ttk.Frame(card, style="Card.TFrame")
        music_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(music_frame, text="Background music level", style="Card.TLabel").pack(anchor=tk.W)
        music_row = ttk.Frame(music_frame, style="Card.TFrame")
        music_row.pack(fill=tk.X, pady=(4, 0))
        self.music_volume_label = ttk.Label(music_row, text="50%", style="Card.TLabel")
        self.music_volume_label.pack(side=tk.RIGHT)
        def on_music_change(value):
            try:
                pct = int(float(value) * 100)
            except ValueError:
                pct = int(self.music_volume.get() * 100)
            pct = max(0, min(100, pct))
            self.music_volume_label.configure(text=f"{pct}%")
        self.music_volume_scale = ttk.Scale(
            music_row,
            from_=0.0,
            to=1.0,
            orient=tk.HORIZONTAL,
            variable=self.music_volume,
            command=on_music_change,
            length=220,
        )
        self.music_volume_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        on_music_change(self.music_volume.get())
    
    def toggle_audio_input(self):
        """Show/hide audio folder input based on music option."""
        if self.music_option.get() in ("yes", "mix"):
            self.audio_input_frame.pack(fill=tk.X, pady=(10, 0))
        else:
            self.audio_input_frame.pack_forget()
    
    def browse_audio(self):
        """Open folder browser for audio."""
        folder = filedialog.askdirectory(title="Select Music Folder")
        if folder:
            self.audio_folder.set(folder)
            audio_path = Path(folder)
            count = sum(1 for f in audio_path.iterdir() 
                       if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS)
            self.audio_info.configure(text=f"Found {count} audio file(s)")
    
    def create_watermark_card(self, parent):
        """Create optional watermark removal card."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.pack(fill=tk.X, pady=8)
        
        ttk.Checkbutton(card, text="Remove white watermark (e.g. Veo) from all videos",
                       variable=self.remove_watermark,
                       style="Card.TCheckbutton",
                       command=self.toggle_watermark_options).pack(anchor=tk.W)
        
        self.watermark_options_frame = ttk.Frame(card, style="Card.TFrame")
        self.watermark_options_frame.pack(fill=tk.X, pady=(10, 0))
        self.watermark_options_frame.pack_forget()
        
        ttk.Label(self.watermark_options_frame, 
                  text="Position (e.g. Veo watermark is usually bottom-right):",
                  style="Card.TLabel").pack(anchor=tk.W)
        
        preset_frame = ttk.Frame(self.watermark_options_frame, style="Card.TFrame")
        preset_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Radiobutton(preset_frame, text="Auto (Veo / bottom-right, adapts to resolution)",
                       variable=self.watermark_preset, value="veo",
                       style="Card.TRadiobutton",
                       command=self.toggle_watermark_custom).pack(anchor=tk.W, pady=2)
        
        ttk.Radiobutton(preset_frame, text="Custom (set X, Y, Width, Height in pixels)",
                       variable=self.watermark_preset, value="custom",
                       style="Card.TRadiobutton",
                       command=self.toggle_watermark_custom).pack(anchor=tk.W, pady=2)
        
        self.watermark_custom_frame = ttk.Frame(self.watermark_options_frame, style="Card.TFrame")
        self.watermark_custom_frame.pack(fill=tk.X, pady=(8, 0))
        self.watermark_custom_frame.pack_forget()
        
        custom_row = ttk.Frame(self.watermark_custom_frame, style="Card.TFrame")
        custom_row.pack(fill=tk.X)
        
        ttk.Label(custom_row, text="X:", style="Card.TLabel", width=4).pack(side=tk.LEFT, padx=(0, 2))
        self.entry_wm_x = ttk.Entry(custom_row, textvariable=self.watermark_x, width=6)
        self.entry_wm_x.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(custom_row, text="Y:", style="Card.TLabel", width=4).pack(side=tk.LEFT, padx=(0, 2))
        self.entry_wm_y = ttk.Entry(custom_row, textvariable=self.watermark_y, width=6)
        self.entry_wm_y.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(custom_row, text="W:", style="Card.TLabel", width=4).pack(side=tk.LEFT, padx=(0, 2))
        self.entry_wm_w = ttk.Entry(custom_row, textvariable=self.watermark_w, width=6)
        self.entry_wm_w.pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(custom_row, text="H:", style="Card.TLabel", width=4).pack(side=tk.LEFT, padx=(0, 2))
        self.entry_wm_h = ttk.Entry(custom_row, textvariable=self.watermark_h, width=6)
        self.entry_wm_h.pack(side=tk.LEFT)
        
        preview_row = ttk.Frame(self.watermark_options_frame, style="Card.TFrame")
        preview_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(
            preview_row,
            text="Preview & Select Region (first video)",
            style="Accent.TButton",
            command=self.open_watermark_preview,
        ).pack(side=tk.LEFT)
        ttk.Label(
            preview_row,
            text="  Drag a box on the preview — used for all videos",
            style="Card.TLabel",
            foreground=ModernStyle.TEXT_DIM,
        ).pack(side=tk.LEFT)
        
        ttk.Label(self.watermark_options_frame, 
                  text="Uses GPU encode when available (AMD/NVIDIA/Intel) for much faster processing.",
                  style="Card.TLabel", foreground=ModernStyle.TEXT_DIM).pack(anchor=tk.W, pady=(5, 0))
    
    def toggle_watermark_options(self):
        """Show/hide watermark position options."""
        if self.remove_watermark.get():
            self.watermark_options_frame.pack(fill=tk.X, pady=(10, 0))
            self.toggle_watermark_custom()
        else:
            self.watermark_options_frame.pack_forget()
    
    def toggle_watermark_custom(self):
        """Show/hide custom position inputs."""
        if self.watermark_preset.get() == "custom":
            self.watermark_custom_frame.pack(fill=tk.X, pady=(8, 0))
        else:
            self.watermark_custom_frame.pack_forget()

    def get_first_video_in_folder(self):
        """Return Path of first video in the input folder, or None."""
        folder = self.input_folder.get()
        if not folder or folder == "Select folder with videos":
            return None
        input_path = Path(folder)
        if not input_path.is_dir():
            return None
        videos = [
            f for f in sorted(input_path.iterdir())
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ]
        return videos[0] if videos else None

    def extract_preview_frame(self, video_path, out_png, max_width=720, max_height=480):
        """Extract one scaled frame as PNG for the watermark preview (fits max box)."""
        video_w, video_h = self.get_video_resolution(video_path)
        scale = min(
            1.0,
            max_width / max(1, video_w),
            max_height / max(1, video_h),
        )
        disp_w = max(2, int(video_w * scale))
        disp_h = max(2, int(video_h * scale))
        if disp_w % 2:
            disp_w += 1
        if disp_h % 2:
            disp_h += 1
        cmd = [
            'ffmpeg', '-y', '-ss', '0.1', '-i', str(video_path),
            '-frames:v', '1',
            '-vf', f'scale={disp_w}:{disp_h}',
            '-q:v', '2',
            str(out_png),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        )
        if result.returncode != 0 or not Path(out_png).exists():
            raise RuntimeError(result.stderr[-500:] if result.stderr else "Failed to extract frame")
        return video_w, video_h, disp_w, disp_h

    def open_watermark_preview(self):
        """Open a scrollable, screen-sized preview to drag-select the hide region."""
        video_path = self.get_first_video_in_folder()
        if video_path is None:
            messagebox.showwarning(
                "No Video",
                "Select an input folder that contains at least one video first.",
            )
            return
        if not self.check_ffmpeg_status():
            messagebox.showerror(
                "FFmpeg Required",
                "FFmpeg is required to generate the preview frame.",
            )
            return

        # Fit preview image and window to the screen (leave room for chrome/controls)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(900, max(520, int(screen_w * 0.72)))
        win_h = min(700, max(420, int(screen_h * 0.78)))
        # Image max size inside the scroll viewport
        img_max_w = max(320, win_w - 80)
        img_max_h = max(240, win_h - 220)

        try:
            tmp_dir = tempfile.mkdtemp(prefix="wm_preview_")
            frame_path = Path(tmp_dir) / "preview.png"
            video_w, video_h, disp_w, disp_h = self.extract_preview_frame(
                video_path, frame_path, max_width=img_max_w, max_height=img_max_h
            )
            photo = tk.PhotoImage(file=str(frame_path))
        except Exception as e:
            messagebox.showerror("Preview Failed", f"Could not load preview:\n{e}")
            return

        scale_x = video_w / max(1, disp_w)
        scale_y = video_h / max(1, disp_h)

        win = tk.Toplevel(self.root)
        win.title(f"Watermark region — {video_path.name}")
        win.configure(bg=ModernStyle.BG_DARK)
        win.transient(self.root)
        win.grab_set()
        win.geometry(f"{win_w}x{win_h}")
        win.minsize(480, 360)
        win.resizable(True, True)

        header = ttk.Frame(win, style="Card.TFrame", padding=(12, 10, 12, 4))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text="Drag a box over the watermark. Scroll if needed. Same region applies to all videos.",
            style="Card.TLabel",
        ).pack(anchor=tk.W)

        info = tk.StringVar(
            value=f"Video: {video_w}×{video_h}  |  Preview: {disp_w}×{disp_h}"
        )
        ttk.Label(
            header, textvariable=info, style="Card.TLabel",
            foreground=ModernStyle.TEXT_DIM,
        ).pack(anchor=tk.W, pady=(2, 0))

        # Scrollable preview area
        canvas_wrap = ttk.Frame(win, style="Card.TFrame", padding=8)
        canvas_wrap.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)

        canvas = tk.Canvas(
            canvas_wrap,
            bg="#000000",
            highlightthickness=1,
            highlightbackground=ModernStyle.BG_INPUT,
            cursor="crosshair",
        )
        v_scroll = ttk.Scrollbar(canvas_wrap, orient=tk.VERTICAL, command=canvas.yview)
        h_scroll = ttk.Scrollbar(canvas_wrap, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        canvas.image = photo
        canvas.configure(scrollregion=(0, 0, disp_w, disp_h))

        # Live region values (video pixel space)
        sel_x = tk.StringVar(value=self.watermark_x.get())
        sel_y = tk.StringVar(value=self.watermark_y.get())
        sel_w = tk.StringVar(value=self.watermark_w.get())
        sel_h = tk.StringVar(value=self.watermark_h.get())

        controls = ttk.Frame(win, style="Card.TFrame", padding=(12, 4))
        controls.pack(fill=tk.X)
        for label, var in (("X", sel_x), ("Y", sel_y), ("Width", sel_w), ("Height", sel_h)):
            ttk.Label(controls, text=f"{label}:", style="Card.TLabel").pack(
                side=tk.LEFT, padx=(0, 2)
            )
            ttk.Entry(controls, textvariable=var, width=7).pack(side=tk.LEFT, padx=(0, 12))

        state = {"start": None, "rect": None, "drawing": False}

        def event_to_img(event):
            """Map mouse event to image coordinates (accounts for scroll)."""
            ix = int(canvas.canvasx(event.x))
            iy = int(canvas.canvasy(event.y))
            return max(0, min(disp_w, ix)), max(0, min(disp_h, iy))

        def video_to_canvas(x, y, w, h):
            return (
                int(round(x / scale_x)),
                int(round(y / scale_y)),
                int(round(w / scale_x)),
                int(round(h / scale_y)),
            )

        def canvas_to_video(x1, y1, x2, y2):
            left = max(0, min(x1, x2))
            top = max(0, min(y1, y2))
            right = min(disp_w, max(x1, x2))
            bottom = min(disp_h, max(y1, y2))
            vx = int(round(left * scale_x))
            vy = int(round(top * scale_y))
            vw = max(2, int(round((right - left) * scale_x)))
            vh = max(2, int(round((bottom - top) * scale_y)))
            vx = min(vx, max(0, video_w - 2))
            vy = min(vy, max(0, video_h - 2))
            vw = min(vw, video_w - vx)
            vh = min(vh, video_h - vy)
            return vx, vy, vw, vh

        def draw_rect_from_vars(*_args):
            try:
                x = int(sel_x.get() or 0)
                y = int(sel_y.get() or 0)
                w = int(sel_w.get() or 2)
                h = int(sel_h.get() or 2)
            except ValueError:
                return
            cx, cy, cw, ch = video_to_canvas(x, y, w, h)
            if state["rect"] is not None:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(
                cx, cy, cx + cw, cy + ch,
                outline=ModernStyle.ACCENT, width=2, dash=(4, 2),
            )
            info.set(
                f"Video: {video_w}×{video_h}  |  Preview: {disp_w}×{disp_h}  |  "
                f"Region: x={x} y={y} w={w} h={h}"
            )

        def on_press(event):
            state["drawing"] = True
            state["start"] = event_to_img(event)
            if state["rect"] is not None:
                canvas.delete(state["rect"])
                state["rect"] = None

        def on_drag(event):
            if not state["drawing"] or state["start"] is None:
                return
            x0, y0 = state["start"]
            x1, y1 = event_to_img(event)
            if state["rect"] is not None:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(
                x0, y0, x1, y1,
                outline=ModernStyle.ACCENT, width=2, dash=(4, 2),
            )
            vx, vy, vw, vh = canvas_to_video(x0, y0, x1, y1)
            sel_x.set(str(vx))
            sel_y.set(str(vy))
            sel_w.set(str(vw))
            sel_h.set(str(vh))
            info.set(
                f"Video: {video_w}×{video_h}  |  Preview: {disp_w}×{disp_h}  |  "
                f"Region: x={vx} y={vy} w={vw} h={vh}"
            )

        def on_release(event):
            if not state["drawing"] or state["start"] is None:
                return
            state["drawing"] = False
            x0, y0 = state["start"]
            x1, y1 = event_to_img(event)
            vx, vy, vw, vh = canvas_to_video(x0, y0, x1, y1)
            if vw < 4 or vh < 4:
                messagebox.showinfo(
                    "Too small", "Drag a larger box over the watermark.", parent=win
                )
                return
            sel_x.set(str(vx))
            sel_y.set(str(vy))
            sel_w.set(str(vw))
            sel_h.set(str(vh))
            draw_rect_from_vars()

        def on_mousewheel(event):
            # Windows / Mac / Linux wheel deltas
            if getattr(event, "num", None) == 4 or event.delta > 0:
                canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5 or event.delta < 0:
                canvas.yview_scroll(1, "units")

        def on_shift_mousewheel(event):
            if getattr(event, "num", None) == 4 or event.delta > 0:
                canvas.xview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5 or event.delta < 0:
                canvas.xview_scroll(1, "units")

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        canvas.bind("<MouseWheel>", on_mousewheel)
        canvas.bind("<Shift-MouseWheel>", on_shift_mousewheel)
        canvas.bind("<Button-4>", on_mousewheel)
        canvas.bind("<Button-5>", on_mousewheel)
        # Also scroll when hovering the wrap area
        canvas_wrap.bind("<MouseWheel>", on_mousewheel)
        canvas_wrap.bind("<Shift-MouseWheel>", on_shift_mousewheel)

        draw_rect_from_vars()

        def apply_and_close():
            try:
                x = max(0, int(sel_x.get()))
                y = max(0, int(sel_y.get()))
                w = max(2, int(sel_w.get()))
                h = max(2, int(sel_h.get()))
            except ValueError:
                messagebox.showerror(
                    "Invalid", "X, Y, Width, Height must be integers.", parent=win
                )
                return
            self.watermark_preset.set("custom")
            self.watermark_x.set(str(x))
            self.watermark_y.set(str(y))
            self.watermark_w.set(str(w))
            self.watermark_h.set(str(h))
            self.watermark_ref_w.set(video_w)
            self.watermark_ref_h.set(video_h)
            self.toggle_watermark_custom()
            self.log(
                f"Watermark region set from preview: x={x} y={y} w={w} h={h} "
                f"(ref {video_w}×{video_h}; scaled for other sizes)"
            )
            cleanup()
            win.destroy()

        def cleanup():
            try:
                if frame_path.exists():
                    frame_path.unlink()
                Path(tmp_dir).rmdir()
            except Exception:
                pass

        btn_row = ttk.Frame(win, style="Card.TFrame", padding=12)
        btn_row.pack(fill=tk.X)
        ttk.Button(
            btn_row, text="Apply to all videos", style="Accent.TButton",
            command=apply_and_close,
        ).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(
            btn_row, text="Cancel",
            command=lambda: (cleanup(), win.destroy()),
        ).pack(side=tk.RIGHT)

        win.protocol("WM_DELETE_WINDOW", lambda: (cleanup(), win.destroy()))
    
    def create_slow_motion_card(self, parent):
        """Optional slow motion: user sets playback speed as % of normal (re-encodes video/audio)."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.pack(fill=tk.X, pady=8)
        
        ttk.Checkbutton(
            card,
            text="Slow down video (and audio) — choose playback speed",
            variable=self.slow_motion_enabled,
            style="Card.TCheckbutton",
            command=self.toggle_slow_motion_options,
        ).pack(anchor=tk.W)
        
        self.slow_motion_frame = ttk.Frame(card, style="Card.TFrame")
        self.slow_motion_frame.pack(fill=tk.X, pady=(10, 0))
        self.slow_motion_frame.pack_forget()
        
        ttk.Label(
            self.slow_motion_frame,
            text="Playback speed (% of normal). Lower = slower. 100% = no change.",
            style="Card.TLabel",
            foreground=ModernStyle.TEXT_DIM,
        ).pack(anchor=tk.W)
        
        row = ttk.Frame(self.slow_motion_frame, style="Card.TFrame")
        row.pack(fill=tk.X, pady=(8, 0))
        self.slow_motion_label = ttk.Label(row, text="75%", style="Card.TLabel", width=8)
        self.slow_motion_label.pack(side=tk.LEFT, padx=(0, 10))
        self.slow_motion_scale = ttk.Scale(
            row,
            from_=25,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.playback_speed_percent,
            command=lambda _: self.update_slow_motion_label(),
        )
        self.slow_motion_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(
            self.slow_motion_frame,
            text="Uses re-encoding; slower exports take longer.",
            style="Card.TLabel",
            foreground=ModernStyle.TEXT_DIM,
        ).pack(anchor=tk.W, pady=(6, 0))
    
    def toggle_slow_motion_options(self):
        if self.slow_motion_enabled.get():
            self.slow_motion_frame.pack(fill=tk.X, pady=(10, 0))
            self.update_slow_motion_label()
        else:
            self.slow_motion_frame.pack_forget()
    
    def update_slow_motion_label(self):
        try:
            p = float(self.playback_speed_percent.get())
        except (tk.TclError, TypeError, ValueError):
            p = 75.0
        p = max(25.0, min(100.0, p))
        self.slow_motion_label.configure(text=f"{p:.0f}%")
    
    @staticmethod
    def build_atempo_chain(playback_speed):
        """FFmpeg atempo must stay in [0.5, 2.0] per filter; chain for smaller/larger factors."""
        if playback_speed >= 0.999:
            return ""
        parts = []
        s = float(playback_speed)
        while s < 0.5 - 1e-9:
            parts.append("atempo=0.5")
            s /= 0.5
        while s > 2.0 + 1e-9:
            parts.append("atempo=2.0")
            s /= 2.0
        if abs(s - 1.0) > 1e-6:
            parts.append(f"atempo={s:.6f}".rstrip("0").rstrip("."))
        return ",".join(parts)
    
    def create_options_card(self, parent):
        """Create metadata options card."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.pack(fill=tk.X, pady=8)
        
        ttk.Label(card, text="Metadata Profile", style="CardTitle.TLabel").pack(anchor=tk.W)
        
        options_frame = ttk.Frame(card, style="Card.TFrame")
        options_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Radiobutton(options_frame, text="Phone (iPhone, Samsung, Pixel)",
                       variable=self.profile_type, value="phone",
                       style="Card.TRadiobutton").pack(anchor=tk.W, pady=2)
        
        ttk.Radiobutton(options_frame, text="Editor (Premiere, DaVinci, Final Cut)",
                       variable=self.profile_type, value="editor",
                       style="Card.TRadiobutton").pack(anchor=tk.W, pady=2)
        
        ttk.Radiobutton(options_frame, text="Random (Mix of both)",
                       variable=self.profile_type, value="random",
                       style="Card.TRadiobutton").pack(anchor=tk.W, pady=2)
        
        ttk.Checkbutton(options_frame, text="Use same profile for all videos",
                       variable=self.consistent_profile,
                       style="Card.TCheckbutton").pack(anchor=tk.W, pady=(10, 0))
    
    def create_log_area(self, parent):
        """Create log/output area."""
        log_frame = ttk.Frame(parent, style="Dark.TFrame")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.log_text = tk.Text(log_frame, height=8, bg=ModernStyle.BG_INPUT,
                               fg=ModernStyle.TEXT, font=("Consolas", 9),
                               relief=tk.FLAT, padx=10, pady=10,
                               insertbackground=ModernStyle.TEXT)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.log_text, orient=tk.VERTICAL,
                                 command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log("Ready. Select mode and configure options to begin.")
    
    def log(self, message):
        """Add message to log."""
        self.log_text.configure(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def clear_log(self):
        """Clear the log."""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def browse_input(self):
        """Open folder browser for input."""
        folder = filedialog.askdirectory(title="Select Input Folder")
        if folder:
            self.input_folder.set(folder)
    
    def browse_output(self):
        """Open folder browser for output."""
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder.set(folder)
    
    def check_ffmpeg_status(self):
        """Check if FFmpeg is installed and detect GPU encoder."""
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            if result.returncode == 0:
                _codec, _args, label, is_gpu = self.detect_video_encoder()
                if is_gpu:
                    self.ffmpeg_status.configure(
                        text=f"✓ FFmpeg + {label} — fast watermark encode",
                        foreground=ModernStyle.SUCCESS,
                    )
                else:
                    self.ffmpeg_status.configure(
                        text=f"✓ FFmpeg ({label})",
                        foreground=ModernStyle.SUCCESS,
                    )
                return True
        except FileNotFoundError:
            pass
        
        self.ffmpeg_status.configure(text="✗ FFmpeg not found - Please install FFmpeg",
                                    foreground=ModernStyle.ERROR)
        return False
    
    def get_random_device_profile(self, profile_type):
        """Get a random device profile based on type."""
        phone_profiles = [p for p in DEVICE_PROFILES if p["make"]]
        editor_profiles = [p for p in DEVICE_PROFILES if not p["make"]]
        
        if profile_type == "phone":
            return random.choice(phone_profiles)
        elif profile_type == "editor":
            return random.choice(editor_profiles)
        else:
            if random.random() < 0.7:
                return random.choice(phone_profiles)
            else:
                return random.choice(editor_profiles)
    
    def generate_realistic_timestamp(self, base_time=None, variation_days=30):
        """Generate a realistic timestamp."""
        if base_time is None:
            days_ago = random.randint(7, variation_days)
            base_time = datetime.now() - timedelta(days=days_ago)
        
        return base_time.replace(
            hour=random.randint(8, 20),
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
            microsecond=0
        )
    
    def format_timestamp(self, dt):
        """Format datetime for metadata."""
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    
    def should_add_music(self):
        """Determine if music should be added based on option."""
        option = self.music_option.get()
        if option == "yes":
            return True
        elif option == "no":
            return False
        else:  # mix
            return random.random() < 0.5
    
    def get_audio_files(self):
        """Get list of audio files from audio folder."""
        audio_folder = self.audio_folder.get()
        if not audio_folder:
            return []
        
        audio_path = Path(audio_folder)
        if not audio_path.exists():
            return []
        
        return [f for f in audio_path.iterdir() 
                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS]
    
    def get_video_resolution(self, video_path):
        """Get video resolution using ffprobe."""
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'json',
                str(video_path)
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get('streams'):
                    return data['streams'][0].get('width', 1920), data['streams'][0].get('height', 1080)
        except:
            pass
        return 1920, 1080  # Default to 1080p

    def has_audio_stream(self, video_path):
        """Check if video has an audio stream (many AI/Veo videos are video-only)."""
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'a',
                '-show_entries', 'stream=codec_type',
                '-of', 'json',
                str(video_path)
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                streams = data.get('streams', [])
                return len(streams) > 0
        except:
            pass
        return False

    def get_watermark_region(self, video_path, preset, custom_tuple, ref_size=None):
        """Get (x, y, w, h) for watermark area, always clamped inside the video frame.
        Custom regions are scaled from ref_size (preview / first-video resolution)."""
        width, height = self.get_video_resolution(video_path)
        width = width if width % 2 == 0 else width - 1
        height = height if height % 2 == 0 else height - 1
        band = 10  # delogo band needs margin inside the frame

        if preset == "custom":
            x, y, w, h = custom_tuple
            rw, rh = ref_size if ref_size else (0, 0)
            if rw and rh and (rw != width or rh != height):
                x = int(round(x * width / rw))
                y = int(round(y * height / rh))
                w = int(round(w * width / rw))
                h = int(round(h * height / rh))
        else:
            # Veo style: bottom-right corner
            margin_right = 16
            margin_bottom = 16
            w = min(420, int(width * 0.38))
            h = min(100, int(height * 0.10))
            w = w if w % 2 == 0 else w + 1
            h = h if h % 2 == 0 else h + 1
            x = width - margin_right - w
            y = height - margin_bottom - h

        # Clamp so delogo area (+ band) stays inside the frame (avoids -22 Invalid argument)
        max_w = max(2, width - 2 * band)
        max_h = max(2, height - 2 * band)
        w = max(2, min(int(w), max_w))
        h = max(2, min(int(h), max_h))
        x = max(band, min(int(x), width - band - w))
        y = max(band, min(int(y), height - band - h))
        return x, y, w, h

    def merge_videos(self, video_paths, output_path, profile, timestamp, audio_file=None,
                     remove_original_audio=False, orig_volume=1.0, music_volume=0.5,
                     playback_speed=1.0):
        """Merge multiple videos into one using filter-based concat (no black frames).
        orig_volume and music_volume are 0.0–1.0 volume multipliers for original and music.
        playback_speed: 1.0 = normal; lower slows merged output (re-encodes)."""
        timestamp_str = self.format_timestamp(timestamp)
        orig_vol = max(0.0, min(1.0, orig_volume))
        music_vol = max(0.0, min(1.0, music_volume))
        try:
            playback_speed = float(playback_speed)
        except (TypeError, ValueError):
            playback_speed = 1.0
        playback_speed = max(0.25, min(1.0, playback_speed))
        use_slow = playback_speed < 0.999
        pts_mult = 1.0 / playback_speed if use_slow else 1.0
        atempo = self.build_atempo_chain(playback_speed) if use_slow else ""
        
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
        
        target_width, target_height = self.get_video_resolution(video_paths[0])
        target_width = target_width if target_width % 2 == 0 else target_width + 1
        target_height = target_height if target_height % 2 == 0 else target_height + 1
        
        n = len(video_paths)
        
        audio_flags = [self.has_audio_stream(v) for v in video_paths]
        any_has_audio = any(audio_flags)
        
        filter_parts = []
        for i in range(n):
            filter_parts.append(
                f'[{i}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,'
                f'pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,'
                f'fps=30,format=yuv420p,setsar=1[v{i}]'
            )
            if audio_flags[i]:
                filter_parts.append(
                    f'[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={orig_vol}[a{i}]'
                )
            else:
                filter_parts.append(
                    f'anullsrc=channel_layout=stereo:sample_rate=44100[a{i}]'
                )
        
        video_inputs = ''.join(f'[v{i}]' for i in range(n))
        audio_inputs = ''.join(f'[a{i}]' for i in range(n))
        filter_parts.append(f'{video_inputs}concat=n={n}:v=1:a=0[outv]')
        if not remove_original_audio:
            filter_parts.append(f'{audio_inputs}concat=n={n}:v=0:a=1[outa]')
        
        filter_complex = ';'.join(filter_parts)
        
        try:
            if audio_file:
                if remove_original_audio:
                    cmd = ['ffmpeg', '-y']
                    for video in video_paths:
                        cmd.extend(['-i', str(video)])
                    cmd.extend(['-i', str(audio_file)])
                    
                    music_input_idx = n
                    music_filter = f'[{music_input_idx}:a]volume={music_vol}[aout]'
                    full_filter = filter_complex + ';' + music_filter
                    if use_slow:
                        full_filter += (
                            f';[outv]setpts={pts_mult}*PTS[vslow];[aout]{atempo}[afinal]'
                        )
                    
                    cmd.extend([
                        '-filter_complex', full_filter,
                        '-map', '[vslow]' if use_slow else '[outv]',
                        '-map', '[afinal]' if use_slow else '[aout]',
                        '-shortest',
                        *self.video_encode_args(),
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-map_metadata', '-1',
                    ])
                else:
                    cmd = ['ffmpeg', '-y']
                    for video in video_paths:
                        cmd.extend(['-i', str(video)])
                    cmd.extend(['-i', str(audio_file)])
                    
                    music_input_idx = n
                    if any_has_audio:
                        mix_filter = (
                            f'[{music_input_idx}:a]volume={music_vol}[music];'
                            f'[outa][music]amix=inputs=2:duration=first:dropout_transition=2[aout]'
                        )
                    else:
                        mix_filter = f'[{music_input_idx}:a]volume={music_vol}[aout]'
                    full_filter = filter_complex + ';' + mix_filter
                    if use_slow:
                        full_filter += (
                            f';[outv]setpts={pts_mult}*PTS[vslow];[aout]{atempo}[afinal]'
                        )
                    
                    cmd.extend([
                        '-filter_complex', full_filter,
                        '-map', '[vslow]' if use_slow else '[outv]',
                        '-map', '[afinal]' if use_slow else '[aout]',
                        *self.video_encode_args(),
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-map_metadata', '-1',
                    ])
                
                for entry in metadata_entries:
                    cmd.extend(['-metadata', entry])
                cmd.extend(['-metadata:s:v:0', f'handler_name={profile["handler"]}'])
                cmd.extend(['-metadata:s:a:0', 'handler_name=Sound Media Handler'])
                cmd.extend(['-movflags', '+faststart', str(output_path)])
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                
            else:
                cmd = ['ffmpeg', '-y']
                for video in video_paths:
                    cmd.extend(['-i', str(video)])

                if use_slow and (not remove_original_audio) and any_has_audio:
                    fc = (
                        filter_complex
                        + f';[outv]setpts={pts_mult}*PTS[vslow];[outa]{atempo}[aslow]'
                    )
                    map_v, map_a = '[vslow]', '[aslow]'
                elif use_slow:
                    fc = filter_complex + f';[outv]setpts={pts_mult}*PTS[vslow]'
                    map_v, map_a = '[vslow]', None
                else:
                    fc = filter_complex
                    map_v = '[outv]'
                    map_a = '[outa]' if (not remove_original_audio and any_has_audio) else None

                cmd.extend([
                    '-filter_complex', fc,
                    '-map', map_v,
                    *self.video_encode_args(),
                    '-map_metadata', '-1',
                ])
                if map_a:
                    cmd.extend(['-map', map_a, '-c:a', 'aac', '-b:a', '192k'])
                else:
                    cmd.extend(['-an'])

                for entry in metadata_entries:
                    cmd.extend(['-metadata', entry])
                
                cmd.extend(['-metadata:s:v:0', f'handler_name={profile["handler"]}'])
                if not remove_original_audio and any_has_audio:
                    cmd.extend(['-metadata:s:a:0', 'handler_name=Sound Media Handler'])
                cmd.extend(['-movflags', '+faststart', str(output_path)])
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
            
            if result.returncode == 0:
                try:
                    os.utime(str(output_path), (timestamp.timestamp(), timestamp.timestamp()))
                except:
                    pass
                return True
            
            return False
            
        except Exception:
            return False
    
    def clean_video(self, input_path, output_path, profile, timestamp, audio_file=None,
                    remove_watermark=False, watermark_region=None,
                    orig_volume=1.0, music_volume=0.5, playback_speed=1.0):
        """Clean a single video's metadata, optionally add music, optionally remove watermark.
        orig_volume and music_volume are 0.0–1.0 volume multipliers for original and music.
        playback_speed: 1.0 = normal; lower values slow video/audio (re-encodes)."""
        try:
            playback_speed = float(playback_speed)
        except (TypeError, ValueError):
            playback_speed = 1.0
        playback_speed = max(0.25, min(1.0, playback_speed))
        use_slow = playback_speed < 0.999
        pts_mult = 1.0 / playback_speed if use_slow else 1.0
        v_slow = f",setpts={pts_mult}*PTS" if use_slow else ""
        atempo = self.build_atempo_chain(playback_speed) if use_slow else ""

        timestamp_str = self.format_timestamp(timestamp)
        
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
        
        use_delogo = remove_watermark and watermark_region is not None
        x, y, w, h = watermark_region if use_delogo else (0, 0, 0, 0)
        # Prefer band when supported; many Windows FFmpeg builds lack band=
        if use_delogo and self.delogo_supports_band():
            delogo_filter_with_band = f'delogo=x={x}:y={y}:w={w}:h={h}:band=10'
        else:
            delogo_filter_with_band = f'delogo=x={x}:y={y}:w={w}:h={h}' if use_delogo else None
        delogo_filter = f'delogo=x={x}:y={y}:w={w}:h={h}' if use_delogo else None

        def add_metadata(cmd_list, has_audio_output=True):
            for entry in metadata_entries:
                cmd_list.extend(['-metadata', entry])
            cmd_list.extend(['-metadata:s:v:0', f'handler_name={profile["handler"]}'])
            if has_audio_output:
                cmd_list.extend(['-metadata:s:a:0', 'handler_name=Sound Media Handler'])
            if not use_delogo:
                cmd_list.extend(['-metadata:s:v:0', 'encoder='])
                if has_audio_output:
                    cmd_list.extend(['-metadata:s:a:0', 'encoder='])
            cmd_list.extend(['-movflags', '+faststart', str(output_path)])
        
        try:
            input_has_audio = self.has_audio_stream(input_path)
            music_enabled = audio_file is not None
            orig_vol = max(0.0, min(1.0, orig_volume))
            music_vol = max(0.0, min(1.0, music_volume))

            if use_delogo:
                # Watermark: apply delogo on video, mix audio according to sliders
                current_delogo = delogo_filter_with_band
                # Try GPU first, then CPU if encoder rejects the stream
                encode_modes = [False]
                _c, _a, _l, is_gpu = self.detect_video_encoder()
                if is_gpu:
                    encode_modes.append(True)  # force_cpu fallback

                result = None
                for force_cpu in encode_modes:
                    for attempt in range(2):
                        filter_chains = []
                        # format=yuv420p keeps GPU encoders happy after delogo
                        filter_chains.append(
                            f'[0:v]{current_delogo}{v_slow},format=yuv420p[vout]'
                        )
                        if music_enabled and input_has_audio:
                            if atempo:
                                filter_chains.append(
                                    f'[0:a]volume={orig_vol}[a0];[1:a]volume={music_vol}[a1];'
                                    f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[amx];'
                                    f'[amx]{atempo}[aout]'
                                )
                            else:
                                filter_chains.append(
                                    f'[0:a]volume={orig_vol}[a0];[1:a]volume={music_vol}[a1];'
                                    f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]'
                                )
                            audio_map = '[aout]'
                            has_audio_output = True
                        elif music_enabled and not input_has_audio:
                            filter_chains.append(
                                f'[1:a]volume={music_vol}' + (f',{atempo}' if atempo else '') + '[aout]'
                            )
                            audio_map = '[aout]'
                            has_audio_output = True
                        elif input_has_audio:
                            filter_chains.append(
                                f'[0:a]volume={orig_vol}' + (f',{atempo}' if atempo else '') + '[aout]'
                            )
                            audio_map = '[aout]'
                            has_audio_output = True
                        else:
                            audio_map = None
                            has_audio_output = False

                        filter_complex = ';'.join(filter_chains)
                        cmd = ['ffmpeg', '-y', '-i', str(input_path)]
                        if music_enabled:
                            cmd.extend(['-i', str(audio_file)])
                        cmd.extend([
                            '-filter_complex', filter_complex,
                            '-map', '[vout]',
                        ])
                        if has_audio_output:
                            cmd.extend(['-map', audio_map])
                        cmd.extend(self.video_encode_args(force_cpu=force_cpu))
                        if has_audio_output:
                            cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
                        else:
                            cmd.extend(['-an'])
                        cmd.extend(['-map_metadata', '-1'])
                        add_metadata(cmd, has_audio_output=has_audio_output)

                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                        )

                        if result.returncode == 0:
                            break
                        err = (result.stderr or "") + (result.stdout or "")
                        if attempt == 0 and "Option not found" in err and "delogo" in err:
                            current_delogo = delogo_filter
                            continue
                        break
                    if result is not None and result.returncode == 0:
                        break
            else:
                # No watermark: audio-only filters / copies, or full graph if slow motion
                if music_enabled:
                    if use_slow:
                        vchain = f'[0:v]setpts={pts_mult}*PTS[vout]'
                        if input_has_audio:
                            if atempo:
                                achain = (
                                    f'[0:a]volume={orig_vol}[a0];[1:a]volume={music_vol}[a1];'
                                    f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[amx];'
                                    f'[amx]{atempo}[aout]'
                                )
                            else:
                                achain = (
                                    f'[0:a]volume={orig_vol}[a0];[1:a]volume={music_vol}[a1];'
                                    f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]'
                                )
                            filter_complex = f'{vchain};{achain}'
                        else:
                            filter_complex = f'{vchain};[1:a]volume={music_vol},{atempo}[aout]'
                        cmd = [
                            'ffmpeg', '-y',
                            '-i', str(input_path),
                            '-i', str(audio_file),
                            '-filter_complex', filter_complex,
                            '-map', '[vout]',
                            '-map', '[aout]',
                            *self.video_encode_args(),
                            '-c:a', 'aac', '-b:a', '192k',
                            '-map_metadata', '-1',
                        ]
                        add_metadata(cmd, has_audio_output=True)
                    else:
                        filter_chains = []
                        if input_has_audio:
                            filter_chains.append(
                                f'[0:a]volume={orig_vol}[a0];[1:a]volume={music_vol}[a1];'
                                f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]'
                            )
                        else:
                            filter_chains.append(f'[1:a]volume={music_vol}[aout]')
                        filter_complex = ';'.join(filter_chains)
                        cmd = [
                            'ffmpeg', '-y',
                            '-i', str(input_path),
                            '-i', str(audio_file),
                            '-filter_complex', filter_complex,
                            '-map', '0:v',
                            '-map', '[aout]',
                            '-c:v', 'copy',
                            '-c:a', 'aac', '-b:a', '192k',
                            '-map_metadata', '-1',
                        ]
                        add_metadata(cmd, has_audio_output=True)
                else:
                    cmd = ['ffmpeg', '-y', '-i', str(input_path), '-map_metadata', '-1']
                    if use_slow:
                        if input_has_audio:
                            cmd.extend([
                                '-filter_complex',
                                f'[0:v]setpts={pts_mult}*PTS[vout];'
                                f'[0:a]volume={orig_vol},{atempo}[aout]',
                                '-map', '[vout]',
                                '-map', '[aout]',
                                *self.video_encode_args(),
                                '-c:a', 'aac', '-b:a', '192k',
                            ])
                            add_metadata(cmd, has_audio_output=True)
                        else:
                            cmd.extend([
                                '-filter_complex', f'[0:v]setpts={pts_mult}*PTS[vout]',
                                '-map', '[vout]',
                                *self.video_encode_args(),
                                '-an',
                            ])
                            add_metadata(cmd, has_audio_output=False)
                    elif input_has_audio:
                        cmd.extend([
                            '-filter_complex', f'[0:a]volume={orig_vol}[aout]',
                            '-map', '0:v',
                            '-map', '[aout]',
                            '-c:v', 'copy',
                            '-c:a', 'aac', '-b:a', '192k',
                        ])
                        add_metadata(cmd, has_audio_output=True)
                    else:
                        cmd.extend([
                            '-c:v', 'copy',
                            '-an',
                        ])
                        add_metadata(cmd, has_audio_output=False)

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
            
            if result.returncode == 0:
                # Reject empty/corrupt outputs (FFmpeg can create 0-byte files on early fail)
                try:
                    out_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
                except OSError:
                    out_size = 0
                if out_size < 1024:
                    try:
                        Path(output_path).unlink(missing_ok=True)
                    except TypeError:
                        # Python < 3.8
                        try:
                            if Path(output_path).exists():
                                Path(output_path).unlink()
                        except OSError:
                            pass
                    return False, "Output file was empty/corrupt (0 bytes). Check watermark region fits the video."
                try:
                    os.utime(str(output_path), (timestamp.timestamp(), timestamp.timestamp()))
                except Exception:
                    pass
                return True, None
            
            # Remove broken partial outputs so Windows player doesn't show "Can't play"
            try:
                p = Path(output_path)
                if p.exists() and p.stat().st_size < 1024:
                    p.unlink()
            except OSError:
                pass

            # Return last few lines of stderr for user to see why it failed
            err = (result.stderr or result.stdout or "").strip()
            if err:
                err_lines = err.split("\n")
                err = "\n".join(err_lines[-8:])  # Last 8 lines usually have the error
            return False, err or "FFmpeg failed"
            
        except Exception as e:
            try:
                p = Path(output_path)
                if p.exists() and p.stat().st_size < 1024:
                    p.unlink()
            except OSError:
                pass
            return False, str(e)

    def process_videos(self):
        """Process all videos (runs in thread)."""
        output_path = Path(self.output_folder.get())
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Get audio files if needed
        audio_files = []
        if self.music_option.get() in ("yes", "mix"):
            audio_files = self.get_audio_files()
            if not audio_files and self.music_option.get() == "yes":
                self.root.after(0, lambda: messagebox.showwarning(
                    "No Audio", "Music is enabled but no audio files found."))
                self.root.after(0, self.processing_complete)
                return
        
        profile_type = self.profile_type.get()
        consistent_profile = self.get_random_device_profile(profile_type) if self.consistent_profile.get() else None
        
        if consistent_profile:
            profile_name = f"{consistent_profile['make']} {consistent_profile['model']}" if consistent_profile['make'] else consistent_profile['software']
            self.root.after(0, lambda: self.log(f"Using consistent profile: {profile_name}"))
        
        base_timestamp = self.generate_realistic_timestamp()
        successful = 0
        failed = 0
        
        if self.mode.get() == "folder":
            # Folder mode - process individual videos (parallel when re-encoding)
            input_path = Path(self.input_folder.get())
            video_files = [f for f in sorted(input_path.iterdir()) 
                          if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS]
            
            if not video_files:
                self.root.after(0, lambda: messagebox.showwarning(
                    "No Videos", "No video files found in the input folder."))
                self.root.after(0, self.processing_complete)
                return
            
            remove_wm = getattr(self, '_remove_watermark', False)
            heavy_encode = remove_wm or getattr(self, '_playback_speed', 1.0) < 0.999
            _codec, _args, enc_label, is_gpu = self.detect_video_encoder()
            workers = self.preferred_parallel_workers(
                len(video_files), heavy_encode=heavy_encode, gpu_encode=is_gpu
            )
            self._encode_workers = workers
            
            self.root.after(0, lambda: self.log(f"Found {len(video_files)} video(s)"))
            if remove_wm:
                self.root.after(0, lambda: self.log("Watermark removal: ON (all videos)"))
            self.root.after(0, lambda l=enc_label, g=is_gpu: self.log(
                f"Encoder: {l}" + (" — no extra permission needed" if g else "")
            ))
            if workers > 1:
                self.root.after(0, lambda w=workers: self.log(
                    f"Speed: {w} videos encoding in parallel"
                ))
            elif len(video_files) == 1 and remove_wm:
                self.root.after(0, lambda: self.log(
                    "Note: only 1 video — parallel helps when you have multiple files"
                ))
            self.root.after(0, lambda: self.progress_bar.configure(maximum=len(video_files)))
            
            # Prepare jobs on this thread (keeps numbering / random choices deterministic)
            jobs = []
            for i, video_file in enumerate(video_files, 1):
                output_file = output_path / f"{i}.mp4"
                profile = consistent_profile or self.get_random_device_profile(profile_type)
                timestamp = base_timestamp + timedelta(minutes=random.randint(1, 5) * (i - 1))
                add_music = self.should_add_music()
                audio_file = random.choice(audio_files) if (add_music and audio_files) else None
                wm_region = None
                if remove_wm:
                    wm_region = self.get_watermark_region(
                        video_file,
                        getattr(self, '_watermark_preset', 'veo'),
                        getattr(self, '_watermark_custom', (1520, 1000, 400, 80)),
                        ref_size=getattr(self, '_watermark_ref', None),
                    )
                profile_name = (
                    f"{profile['make']} {profile['model']}" if profile['make'] else profile['software']
                )
                jobs.append({
                    "index": i,
                    "video_file": video_file,
                    "output_file": output_file,
                    "profile": profile,
                    "timestamp": timestamp,
                    "audio_file": audio_file,
                    "wm_region": wm_region,
                    "profile_name": profile_name,
                })
            
            progress_lock = threading.Lock()
            done_count = 0
            successful = 0
            failed = 0
            total = len(jobs)
            
            def run_job(job):
                if not self.is_processing:
                    return False, "Cancelled", job
                vf = job["video_file"]
                log_msg = f"Processing: {vf.name} → {job['profile_name']}"
                if job["audio_file"]:
                    log_msg += " + ♪"
                if job["wm_region"]:
                    log_msg += " (no watermark)"
                self.root.after(0, lambda msg=log_msg: self.log(msg))
                
                ok, err_msg = self.clean_video(
                    job["video_file"],
                    job["output_file"],
                    job["profile"],
                    job["timestamp"],
                    job["audio_file"],
                    remove_watermark=remove_wm,
                    watermark_region=job["wm_region"],
                    orig_volume=getattr(self, '_orig_volume', 1.0),
                    music_volume=getattr(self, '_music_volume', 0.5),
                    playback_speed=getattr(self, '_playback_speed', 1.0),
                )
                return ok, err_msg, job
            
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(run_job, job): job for job in jobs}
                for fut in as_completed(futures):
                    if not self.is_processing:
                        for pending in futures:
                            pending.cancel()
                        break
                    try:
                        ok, err_msg, job = fut.result()
                    except Exception as e:
                        ok, err_msg, job = False, str(e), futures[fut]
                    
                    with progress_lock:
                        done_count += 1
                        n = done_count
                        if ok:
                            successful += 1
                        else:
                            failed += 1
                    
                    out_name = job["output_file"].name
                    vid_name = job["video_file"].name
                    if ok:
                        self.root.after(0, lambda o=out_name: self.log(f"  ✓ Saved as {o}"))
                    else:
                        self.root.after(0, lambda v=vid_name: self.log(f"  ✗ Failed: {v}"))
                        if err_msg:
                            self.root.after(0, lambda e=err_msg: self.log(f"     Error: {e}"))
                    
                    self.root.after(0, lambda v=n: self.progress_bar.configure(value=v))
                    self.root.after(0, lambda v=n, t=total:
                                   self.progress_label.configure(text=f"Processing {v}/{t}..."))
            
            self._encode_workers = 1
        
        else:
            # Merge mode - process queue
            if not self.merge_queue:
                self.root.after(0, lambda: messagebox.showwarning(
                    "Empty Queue", "Please add video combinations to the queue."))
                self.root.after(0, self.processing_complete)
                return
            
            self.root.after(0, lambda: self.log(f"Processing {len(self.merge_queue)} combination(s)"))
            self.root.after(0, lambda: self.progress_bar.configure(maximum=len(self.merge_queue)))
            
            for i, combo in enumerate(self.merge_queue, 1):
                if not self.is_processing:
                    break
                
                output_file = output_path / f"{i}.mp4"
                profile = consistent_profile or self.get_random_device_profile(profile_type)
                timestamp = base_timestamp + timedelta(minutes=random.randint(1, 5) * (i - 1))
                
                # Determine if adding music
                add_music = self.should_add_music()
                audio_file = random.choice(audio_files) if (add_music and audio_files) else None
                
                profile_name = f"{profile['make']} {profile['model']}" if profile['make'] else profile['software']
                video_names = " + ".join(Path(f).name for f in combo)
                log_msg = f"Merging: {video_names}"
                if audio_file:
                    log_msg += f" + ♪"
                
                self.root.after(0, lambda msg=log_msg: self.log(msg))
                self.root.after(0, lambda v=i: self.progress_bar.configure(value=v))
                self.root.after(0, lambda v=i, t=len(self.merge_queue): 
                               self.progress_label.configure(text=f"Merging {v}/{t}..."))
                
                if self.merge_videos(
                    combo,
                    output_file,
                    profile,
                    timestamp,
                    audio_file,
                    remove_original_audio=(self.music_option.get() == "yes"),
                    orig_volume=getattr(self, '_orig_volume', 1.0),
                    music_volume=getattr(self, '_music_volume', 0.5),
                    playback_speed=getattr(self, '_playback_speed', 1.0),
                ):
                    successful += 1
                    self.root.after(0, lambda o=output_file.name: self.log(f"  ✓ Saved as {o}"))
                else:
                    failed += 1
                    self.root.after(0, lambda: self.log(f"  ✗ Failed to merge"))
        
        # Complete
        self.root.after(0, lambda: self.log(f"\n{'='*40}"))
        self.root.after(0, lambda: self.log(f"Complete! Success: {successful}, Failed: {failed}"))
        self.root.after(0, lambda: self.log(f"Output: {output_path}"))
        
        if successful > 0:
            self.root.after(0, lambda: messagebox.showinfo(
                "Complete", f"Successfully processed {successful} video(s)!\n\nOutput folder:\n{output_path}"))
        
        self.root.after(0, self.processing_complete)
    
    def start_processing(self):
        """Start the processing thread."""
        output_folder = self.output_folder.get()
        
        if not output_folder or output_folder == "Select destination for processed videos":
            messagebox.showwarning("Output Required", "Please select an output folder.")
            return
        
        # Validate based on mode
        if self.mode.get() == "folder":
            input_folder = self.input_folder.get()
            if not input_folder or input_folder == "Select folder with videos":
                messagebox.showwarning("Input Required", "Please select an input folder.")
                return
            if not Path(input_folder).exists():
                messagebox.showerror("Error", "Input folder does not exist.")
                return
        else:
            if not self.merge_queue:
                messagebox.showwarning("Queue Empty", "Please add video combinations to the queue.")
                return
        
        # Validate audio folder if music is enabled
        if self.music_option.get() in ("yes", "mix"):
            audio_folder = self.audio_folder.get()
            if not audio_folder:
                messagebox.showwarning("Audio Required", "Please select a music folder or set music to 'No'.")
                return
            if not Path(audio_folder).exists():
                messagebox.showerror("Error", "Audio folder does not exist.")
                return
        
        if not self.check_ffmpeg_status():
            messagebox.showerror("FFmpeg Required", 
                               "FFmpeg is not installed.\n\nInstall with:\nwinget install FFmpeg")
            return
        
        # Store watermark options for use in worker thread (folder mode)
        self._remove_watermark = self.remove_watermark.get()
        self._watermark_preset = self.watermark_preset.get()
        try:
            self._watermark_custom = (
                int(self.watermark_x.get() or 1520),
                int(self.watermark_y.get() or 1000),
                int(self.watermark_w.get() or 400),
                int(self.watermark_h.get() or 80),
            )
        except (ValueError, TypeError):
            self._watermark_custom = (1520, 1000, 400, 80)
        try:
            self._watermark_ref = (
                int(self.watermark_ref_w.get() or 1920),
                int(self.watermark_ref_h.get() or 1080),
            )
        except (ValueError, TypeError, tk.TclError):
            self._watermark_ref = (1920, 1080)
        # If custom region was never previewed, use first input video as reference
        if self._remove_watermark and self.mode.get() == "folder":
            first = self.get_first_video_in_folder()
            if first is not None:
                # Only override defaults when ref still looks like unused 1920x1080 defaults
                # and coords look like old 1080p defaults — always prefer first video if
                # user didn't open preview (ref equals initial defaults).
                if (self.watermark_ref_w.get() == 1920 and self.watermark_ref_h.get() == 1080
                        and self.watermark_preset.get() == "custom"):
                    fw, fh = self.get_video_resolution(first)
                    # Keep typed coords as relative to first video when they fit; else scale from 1920x1080
                    self._watermark_ref = (fw, fh)
                    # If absolute coords don't fit first video, treat values as 1920x1080-based
                    cx, cy, cw, ch = self._watermark_custom
                    if cx + cw > fw or cy + ch > fh:
                        self._watermark_ref = (1920, 1080)

        # Store current audio levels (0.0–1.0) for worker thread
        try:
            self._orig_volume = float(self.orig_volume.get())
        except Exception:
            self._orig_volume = 1.0
        self._orig_volume = max(0.0, min(1.0, self._orig_volume))

        try:
            self._music_volume = float(self.music_volume.get())
        except Exception:
            self._music_volume = 0.5
        self._music_volume = max(0.0, min(1.0, self._music_volume))

        if self.slow_motion_enabled.get():
            try:
                pct = float(self.playback_speed_percent.get())
            except (tk.TclError, TypeError, ValueError):
                pct = 75.0
            pct = max(25.0, min(100.0, pct))
            self._playback_speed = pct / 100.0
        else:
            self._playback_speed = 1.0
        
        # Start processing
        self.is_processing = True
        self.process_btn.configure(state=tk.DISABLED, text="Processing...")
        self.progress_bar.pack(pady=10)
        self.progress_bar.configure(value=0)
        self.clear_log()
        self.log("Starting processing...")
        ps = getattr(self, "_playback_speed", 1.0)
        if ps < 0.999:
            self.log(f"Slow motion: {ps * 100:.0f}% of normal playback speed")
        
        thread = threading.Thread(target=self.process_videos, daemon=True)
        thread.start()
    
    def processing_complete(self):
        """Called when processing is complete."""
        self.is_processing = False
        self.process_btn.configure(state=tk.NORMAL, text="Process Videos")
        self.progress_label.configure(text="")


def main():
    root = tk.Tk()
    try:
        root.iconbitmap(default='')
    except:
        pass
    
    app = MetadataCleanerGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
