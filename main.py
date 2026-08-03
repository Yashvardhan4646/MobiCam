import os
import sys
import time
import json
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import cv2
from PIL import Image, ImageTk

# AI Engine import
from ai_engine import AIEngine

# Base directories
BASE_DIR = Path(__file__).parent.resolve()
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
RECORDINGS_DIR = BASE_DIR / "recordings"
EVENTS_DIR = BASE_DIR / "events"
CONFIG_FILE = BASE_DIR / "config.json"

# Ensure directories exist
SNAPSHOTS_DIR.mkdir(exist_ok=True)
RECORDINGS_DIR.mkdir(exist_ok=True)
EVENTS_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "ip_address": "192.168.1.100",
    "port": "4747",
    "preset": "DroidCam (WiFi)",
    "custom_url": "",
    "auto_reconnect": True,
    "rotation": 0,
    "flip_h": False,
    "flip_v": False,
    "ai_mode": "Object Detection (MobileNet)",
    "ai_conf": 50,
    "sound_alarm": True,
    "target_filter": "All",
    "auto_person_capture": True
}

PRESETS = {
    "DroidCam (WiFi)": "http://{ip}:{port}/video",
    "DroidCam (mjpegfeed)": "http://{ip}:{port}/mjpegfeed",
    "IP Webcam (Android)": "http://{ip}:{port}/video",
    "IP Camera (iOS / Generic)": "http://{ip}:{port}/live",
    "RTSP Stream": "rtsp://{ip}:{port}/h264_pcm.sdp",
    "Custom URL": "{custom_url}"
}


# Enable low latency / zero buffering in FFmpeg backend
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "fflags;nobuffer|flags;low_delay|framedrop|max_delay;0"
cv2.setNumThreads(0)


class FastStreamReader:
    """
    Ultra low-latency frame grabber.
    Continuously drains the OpenCV video capture buffer queue in a dedicated background thread,
    ensuring the application always reads the newest frame direct from the camera with zero lag.
    """
    def __init__(self):
        self.cap = None
        self.latest_frame = None
        self.grabbed = False
        self.stopped = False
        self.lock = threading.Lock()
        self.thread = None

    def start(self, cap):
        self.cap = cap
        self.stopped = False
        self.grabbed = False
        self.latest_frame = None
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while not self.stopped:
            if not self.cap or not self.cap.isOpened():
                time.sleep(0.005)
                continue

            try:
                # cap.grab() rapidly flushes queued frames from internal socket buffer
                grabbed = self.cap.grab()
                if grabbed:
                    ret, frame = self.cap.retrieve()
                    if ret and frame is not None:
                        with self.lock:
                            self.latest_frame = frame
                            self.grabbed = True
                else:
                    time.sleep(0.002)
            except Exception:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            if not self.grabbed or self.latest_frame is None:
                return False, None
            return True, self.latest_frame

    def stop(self):
        self.stopped = True
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.latest_frame = None
        self.grabbed = False


class MobileCameraApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("AI Mobile Camera & Security Viewer")
        self.geometry("1180x760")
        self.minsize(980, 650)
        self.configure(bg="#121212")

        # Load Configuration
        self.config_data = self.load_config()

        # State Variables
        self.stream_reader = None
        self.is_streaming = False
        self.is_recording = False
        self.out_writer = None
        self.recording_start_time = None
        self.current_frame = None
        self.fps = 0
        self.frame_count = 0
        self.fps_timer = time.time()
        self.stream_thread = None
        self.last_event_save_time = 0

        # AI Engine Instance
        self.ai_engine = AIEngine()

        # Transform variables
        self.rotation_angle = tk.IntVar(value=self.config_data.get("rotation", 0))
        self.flip_h_var = tk.BooleanVar(value=self.config_data.get("flip_h", False))
        self.flip_v_var = tk.BooleanVar(value=self.config_data.get("flip_v", False))

        # AI Control variables
        self.ai_mode_var = tk.StringVar(value=self.config_data.get("ai_mode", "Object Detection (MobileNet)"))
        self.target_filter_var = tk.StringVar(value=self.config_data.get("target_filter", "All"))
        self.conf_slider_var = tk.IntVar(value=self.config_data.get("ai_conf", 50))
        self.sound_alarm_var = tk.BooleanVar(value=self.config_data.get("sound_alarm", True))
        self.auto_person_capture_var = tk.BooleanVar(value=self.config_data.get("auto_person_capture", True))

        # Auto Person Capture state
        self.last_person_snap_time = 0
        self.auto_clip_writer = None
        self.auto_clip_start_time = 0

        # Setup GUI Layout
        self.setup_styles()
        self.build_ui()

        # Update initial URL string display
        self.update_url_preview()

        # Handle window close cleanly
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    return {**DEFAULT_CONFIG, **data}
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        self.config_data["ip_address"] = self.entry_ip.get().strip()
        self.config_data["port"] = self.entry_port.get().strip()
        self.config_data["preset"] = self.combo_preset.get()
        self.config_data["custom_url"] = self.entry_custom.get().strip()
        self.config_data["rotation"] = self.rotation_angle.get()
        self.config_data["flip_h"] = self.flip_h_var.get()
        self.config_data["flip_v"] = self.flip_v_var.get()
        self.config_data["ai_mode"] = self.ai_mode_var.get()
        self.config_data["ai_conf"] = self.conf_slider_var.get()
        self.config_data["sound_alarm"] = self.sound_alarm_var.get()
        self.config_data["target_filter"] = self.target_filter_var.get()
        self.config_data["auto_person_capture"] = self.auto_person_capture_var.get()
        
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Dark colors
        BG_DARK = "#121212"
        PANEL_BG = "#1e1e1e"
        ACCENT_BLUE = "#00adb5"
        TEXT_LIGHT = "#eeeeee"

        self.style.configure("TFrame", background=PANEL_BG)
        self.style.configure("Sidebar.TFrame", background=PANEL_BG)
        self.style.configure("TLabel", background=PANEL_BG, foreground=TEXT_LIGHT, font=("Segoe UI", 9))
        self.style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"), foreground=ACCENT_BLUE)
        self.style.configure("Status.TLabel", font=("Segoe UI", 9, "italic"), foreground="#aaaaaa")

        self.style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=5, background="#333333", foreground=TEXT_LIGHT)
        self.style.map("TButton", background=[("active", "#444444")])

        self.style.configure("Accent.TButton", background=ACCENT_BLUE, foreground="#000000")
        self.style.map("Accent.TButton", background=[("active", "#00c4cc")])

        self.style.configure("Danger.TButton", background="#ff4d4d", foreground="#ffffff")
        self.style.map("Danger.TButton", background=[("active", "#ff6666")])

        self.style.configure("TEntry", fieldbackground="#2a2a2a", foreground=TEXT_LIGHT, insertcolor=TEXT_LIGHT)
        self.style.configure("TCombobox", fieldbackground="#2a2a2a", foreground=TEXT_LIGHT, background="#333333")

    def build_ui(self):
        # Main Layout Split
        self.main_container = ttk.Frame(self, style="TFrame")
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # ------------------ LEFT SIDEBAR ------------------
        sidebar = ttk.Frame(self.main_container, style="Sidebar.TFrame", width=360, padding=12)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=0, pady=0)
        sidebar.pack_propagate(False)

        # Title
        lbl_title = ttk.Label(sidebar, text="📱 AI Mobile Camera", style="Header.TLabel")
        lbl_title.pack(anchor="w", pady=(0, 10))

        # Connection Settings Card
        settings_frame = ttk.LabelFrame(sidebar, text=" Connection Settings ", padding=8)
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        # Preset Selector
        ttk.Label(settings_frame, text="Camera App Type:").pack(anchor="w", pady=(1, 1))
        self.combo_preset = ttk.Combobox(
            settings_frame, 
            values=list(PRESETS.keys()),
            state="readonly"
        )
        self.combo_preset.set(self.config_data.get("preset", "DroidCam (WiFi)"))
        self.combo_preset.pack(fill=tk.X, pady=(0, 6))
        self.combo_preset.bind("<<ComboboxSelected>>", self.on_preset_changed)

        # IP & Port Entries side by side
        ip_port_box = ttk.Frame(settings_frame)
        ip_port_box.pack(fill=tk.X, pady=(0, 6))

        ip_left = ttk.Frame(ip_port_box)
        ip_left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Label(ip_left, text="Mobile IP:").pack(anchor="w")
        self.entry_ip = ttk.Entry(ip_left)
        self.entry_ip.insert(0, self.config_data.get("ip_address", "192.168.1.100"))
        self.entry_ip.pack(fill=tk.X)
        self.entry_ip.bind("<KeyRelease>", lambda e: self.update_url_preview())

        port_right = ttk.Frame(ip_port_box)
        port_right.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Label(port_right, text="Port:").pack(anchor="w")
        self.entry_port = ttk.Entry(port_right, width=8)
        self.entry_port.insert(0, self.config_data.get("port", "4747"))
        self.entry_port.pack(fill=tk.X)
        self.entry_port.bind("<KeyRelease>", lambda e: self.update_url_preview())

        # Custom URL Entry (hidden by default)
        self.lbl_custom = ttk.Label(settings_frame, text="Custom URL / RTSP:")
        self.entry_custom = ttk.Entry(settings_frame)
        self.entry_custom.insert(0, self.config_data.get("custom_url", ""))
        self.entry_custom.bind("<KeyRelease>", lambda e: self.update_url_preview())

        # Stream Target URL Preview
        self.lbl_url_preview = ttk.Label(settings_frame, text="", font=("Consolas", 8), foreground="#00adb5", wraplength=320)
        self.lbl_url_preview.pack(anchor="w", pady=(2, 6))

        # Connect Button
        self.btn_connect = ttk.Button(settings_frame, text="▶ Start Stream", style="Accent.TButton", command=self.toggle_stream)
        self.btn_connect.pack(fill=tk.X)

        # 🤖 AI VISION & SECURITY CARD
        ai_frame = ttk.LabelFrame(sidebar, text=" 🤖 AI Vision & Security ", padding=8)
        ai_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(ai_frame, text="AI Mode:").pack(anchor="w", pady=(1, 1))
        combo_ai_mode = ttk.Combobox(
            ai_frame,
            values=["Off", "Object Detection (MobileNet)", "Security Motion Alert"],
            textvariable=self.ai_mode_var,
            state="readonly"
        )
        combo_ai_mode.pack(fill=tk.X, pady=(0, 6))

        filter_box = ttk.Frame(ai_frame)
        filter_box.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(filter_box, text="Filter:").pack(side=tk.LEFT)
        combo_filter = ttk.Combobox(
            filter_box,
            values=["All", "Person Only", "Pets", "Vehicles"],
            textvariable=self.target_filter_var,
            state="readonly",
            width=15
        )
        combo_filter.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))

        # Confidence Slider
        conf_box = ttk.Frame(ai_frame)
        conf_box.pack(fill=tk.X, pady=(0, 4))
        self.lbl_conf = ttk.Label(conf_box, text=f"Confidence: {self.conf_slider_var.get()}%")
        self.lbl_conf.pack(anchor="w")
        slider_conf = ttk.Scale(
            ai_frame, from_=20, to=90, 
            variable=self.conf_slider_var, 
            command=lambda v: self.lbl_conf.config(text=f"Confidence: {int(float(v))}%")
        )
        slider_conf.pack(fill=tk.X, pady=(0, 6))

        # Sound Alarm Option
        chk_sound = ttk.Checkbutton(ai_frame, text="🔊 Sound Alarm on Person/Motion", variable=self.sound_alarm_var)
        chk_sound.pack(anchor="w")

        # Auto Person Snapshot & 5s Video Option
        chk_person = ttk.Checkbutton(ai_frame, text="📸 Auto 5s Video & Snap on Person", variable=self.auto_person_capture_var)
        chk_person.pack(anchor="w", pady=(2, 0))

        # Capture Actions Card
        actions_frame = ttk.LabelFrame(sidebar, text=" Controls & Capture ", padding=8)
        actions_frame.pack(fill=tk.X, pady=(0, 10))

        act_btns = ttk.Frame(actions_frame)
        act_btns.pack(fill=tk.X)

        self.btn_snapshot = ttk.Button(act_btns, text="📸 Snapshot", command=self.take_snapshot, state=tk.DISABLED)
        self.btn_snapshot.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        self.btn_record = ttk.Button(act_btns, text="🔴 Record", command=self.toggle_recording, state=tk.DISABLED)
        self.btn_record.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(3, 0))

        # Live Detection Event Log
        log_frame = ttk.LabelFrame(sidebar, text=" 📋 AI Event Log ", padding=6)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.log_listbox = tk.Listbox(log_frame, bg="#121212", fg="#00e676", font=("Consolas", 8), selectbackground="#333333", highlightthickness=0, bd=0)
        self.log_listbox.pack(fill=tk.BOTH, expand=True)

        # Folder Quick Links
        folders_box = ttk.Frame(sidebar)
        folders_box.pack(fill=tk.X, side=tk.BOTTOM, pady=0)

        btn_snaps = ttk.Button(folders_box, text="📁 Snaps", command=lambda: self.open_folder(SNAPSHOTS_DIR))
        btn_snaps.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        btn_recs = ttk.Button(folders_box, text="🎥 Recs", command=lambda: self.open_folder(RECORDINGS_DIR))
        btn_recs.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        btn_events = ttk.Button(folders_box, text="🚨 Events", command=lambda: self.open_folder(EVENTS_DIR))
        btn_events.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(2, 0))

        # ------------------ RIGHT VIEWPORT ------------------
        viewport_container = ttk.Frame(self.main_container, style="TFrame")
        viewport_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Top Bar
        top_bar = ttk.Frame(viewport_container)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        self.lbl_status = ttk.Label(top_bar, text="Status: Disconnected 🔴", font=("Segoe UI", 11, "bold"), foreground="#ff4d4d")
        self.lbl_status.pack(side=tk.LEFT)

        self.lbl_fps = ttk.Label(top_bar, text="0.0 FPS", font=("Segoe UI", 10), foreground="#aaaaaa")
        self.lbl_fps.pack(side=tk.RIGHT)

        self.lbl_rec_timer = ttk.Label(top_bar, text="", font=("Segoe UI", 10, "bold"), foreground="#ff4d4d")
        self.lbl_rec_timer.pack(side=tk.RIGHT, padx=15)

        # Video Canvas Screen
        self.canvas = tk.Canvas(viewport_container, bg="#000000", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas_text = self.canvas.create_text(
            400, 300, 
            text="AI Camera Stream Inactive\n\n1. Open DroidCam or IP Webcam on phone\n2. Click 'Start Stream'",
            fill="#777777", font=("Segoe UI", 14), justify=tk.CENTER
        )
        self.canvas.bind("<Configure>", self.on_canvas_resize)

    def on_preset_changed(self, event=None):
        preset = self.combo_preset.get()
        if preset == "Custom URL":
            self.lbl_custom.pack(anchor="w", pady=(2, 2))
            self.entry_custom.pack(fill=tk.X, pady=(0, 6))
        else:
            self.lbl_custom.pack_forget()
            self.entry_custom.pack_forget()
        self.update_url_preview()

    def get_stream_url(self):
        preset = self.combo_preset.get()
        template = PRESETS.get(preset, "")
        ip = self.entry_ip.get().strip()
        port = self.entry_port.get().strip()
        custom_url = self.entry_custom.get().strip()

        if custom_url.isdigit() and preset == "Custom URL":
            return int(custom_url)

        return template.format(ip=ip, port=port, custom_url=custom_url)

    def update_url_preview(self):
        try:
            url = self.get_stream_url()
            self.lbl_url_preview.config(text=str(url))
        except Exception:
            self.lbl_url_preview.config(text="Invalid URL format")

    def toggle_stream(self):
        if not self.is_streaming:
            self.start_stream()
        else:
            self.stop_stream()

    def start_stream(self):
        url = self.get_stream_url()
        self.save_config()

        self.lbl_status.config(text="Status: Connecting... 🟡", foreground="#ffb300")
        self.btn_connect.config(text="Connecting...", state=tk.DISABLED)
        self.update_idletasks()

        self.is_streaming = True
        self.stream_thread = threading.Thread(target=self.run_stream, args=(url,), daemon=True)
        self.stream_thread.start()

    def run_stream(self, url):
        candidate_urls = [url]
        if "4747" in str(url) or "droidcam" in self.combo_preset.get().lower():
            ip = self.entry_ip.get().strip()
            port = self.entry_port.get().strip()
            candidate_urls.extend([
                f"http://{ip}:{port}/mjpegfeed?640x480",
                f"http://{ip}:{port}/video?640x480",
                f"http://{ip}:{port}/video",
                f"http://{ip}:{port}/mjpegfeed"
            ])

        urls_to_try = []
        for u in candidate_urls:
            if u not in urls_to_try:
                urls_to_try.append(u)

        temp_cap = None
        for test_url in urls_to_try:
            print(f"Attempting low-latency stream connection to: {test_url}")
            c = cv2.VideoCapture(test_url)
            c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if c.isOpened():
                ret, test_frame = c.read()
                if ret and test_frame is not None:
                    temp_cap = c
                    print(f"Successfully connected to stream: {test_url}")
                    break
                else:
                    c.release()

        if temp_cap is None:
            self.after(0, self.on_stream_failed, "Could not open video stream. Please check:\n1. DroidCam/IP Webcam is open on phone\n2. Phone IP and Port are correct\n3. Laptop and Phone are on same Wi-Fi")
            return

        self.stream_reader = FastStreamReader()
        self.stream_reader.start(temp_cap)
        self.after(0, self.on_stream_connected)

        while self.is_streaming:
            ret, raw_frame = self.stream_reader.read()
            if not ret or raw_frame is None:
                time.sleep(0.002)
                continue

            # Apply manual transforms (rotation/flip)
            frame = self.apply_transforms(raw_frame)

            # Process AI vision detection
            ai_mode = self.ai_mode_var.get()
            conf_thresh = self.conf_slider_var.get() / 100.0
            play_sound = self.sound_alarm_var.get()
            target_filter = self.target_filter_var.get()

            annotated_frame, detections, alert_triggered, alert_msg = self.ai_engine.process_frame(
                frame, mode=ai_mode, conf_threshold=conf_thresh, play_alarm=play_sound, target_filter=target_filter
            )

            self.current_frame = annotated_frame.copy()

            # Record active video frame
            if self.is_recording and self.out_writer is not None:
                self.out_writer.write(annotated_frame)

            # Security Event Auto-Save (with 5-second cooldown)
            if alert_triggered and ai_mode == "Security Motion Alert":
                now = time.time()
                if now - self.last_event_save_time > 5.0:
                    self.last_event_save_time = now
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    event_file = EVENTS_DIR / f"event_{ts}.jpg"
                    cv2.imwrite(str(event_file), annotated_frame)
                    self.after(0, self.log_ai_event, f"🚨 {ts[-6:]} Security Alert Saved!")

            # Person Detection Trigger (Auto Snapshot + 5-Second Video Clip)
            person_detected = any(d.get("class") == "person" for d in detections)
            if person_detected and self.auto_person_capture_var.get():
                now_time = time.time()
                ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")

                # Auto Snapshot (with 6s cooldown)
                if now_time - self.last_person_snap_time >= 6.0:
                    self.last_person_snap_time = now_time
                    snap_file = SNAPSHOTS_DIR / f"person_snap_{ts_str}.jpg"
                    cv2.imwrite(str(snap_file), annotated_frame)
                    self.after(0, self.log_ai_event, f"📸 Person Snapshot Saved!")

                # Auto 5-Second Video Clip Trigger (with 6s cooldown)
                if self.auto_clip_writer is None and (now_time - self.auto_clip_start_time >= 6.0):
                    clip_file = RECORDINGS_DIR / f"person_clip_5s_{ts_str}.mp4"
                    fh, fw = annotated_frame.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    fps_target = max(15.0, self.fps if self.fps > 0 else 25.0)
                    self.auto_clip_writer = cv2.VideoWriter(str(clip_file), fourcc, fps_target, (fw, fh))
                    self.auto_clip_start_time = now_time
                    self.after(0, self.log_ai_event, f"🔴 5s Person Clip Started...")

            # Write active frames to auto 5-second video clip writer
            if self.auto_clip_writer is not None:
                self.auto_clip_writer.write(annotated_frame)
                if time.time() - self.auto_clip_start_time >= 5.0:
                    self.auto_clip_writer.release()
                    self.auto_clip_writer = None
                    self.after(0, self.log_ai_event, f"💾 5s Person Clip Saved!")

            # Log Detection Events
            if detections:
                det_names = ", ".join(set([d["class"].title() for d in detections]))
                t_str = datetime.now().strftime("%H:%M:%S")
                self.after(0, self.log_ai_event, f"{t_str} - {det_names}")

            # Calculate FPS
            self.frame_count += 1
            now = time.time()
            if now - self.fps_timer >= 1.0:
                self.fps = self.frame_count / (now - self.fps_timer)
                self.frame_count = 0
                self.fps_timer = now
                self.after(0, self.update_fps_ui)

            # Display frame in canvas
            self.after(0, self.render_frame, annotated_frame)

        if self.stream_reader:
            self.stream_reader.stop()
            self.stream_reader = None

        if self.auto_clip_writer:
            self.auto_clip_writer.release()
            self.auto_clip_writer = None

        if self.is_recording:
            self.stop_recording_internal()

        self.after(0, self.on_stream_stopped)

    def log_ai_event(self, msg):
        # Insert event log message into Listbox
        self.log_listbox.insert(0, msg)
        if self.log_listbox.size() > 50:
            self.log_listbox.delete(50, tk.END)

    def apply_transforms(self, frame):
        rot = self.rotation_angle.get()
        if rot == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rot == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rot == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        fh = self.flip_h_var.get()
        fv = self.flip_v_var.get()
        if fh and fv:
            frame = cv2.flip(frame, -1)
        elif fh:
            frame = cv2.flip(frame, 1)
        elif fv:
            frame = cv2.flip(frame, 0)

        return frame

    def render_frame(self, frame):
        if not self.is_streaming:
            return

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()

        if cw <= 10 or ch <= 10:
            return

        fh, fw = frame.shape[:2]
        scale = min(cw / fw, ch / fh)
        nw, nh = int(fw * scale), int(fh * scale)

        if nw > 0 and nh > 0:
            # Ultra-fast OpenCV C++ resize before color space conversion
            resized_bgr = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
            rgb_frame = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb_frame)
            self.tk_photo = ImageTk.PhotoImage(image=pil_img)

            self.canvas.delete("all")
            self.canvas.create_image(cw // 2, ch // 2, image=self.tk_photo, anchor=tk.CENTER)

    def update_fps_ui(self):
        self.lbl_fps.config(text=f"{self.fps:.1f} FPS")
        if self.is_recording and self.recording_start_time:
            elapsed = int(time.time() - self.recording_start_time)
            mins, secs = divmod(elapsed, 60)
            self.lbl_rec_timer.config(text=f"REC 🔴 {mins:02d}:{secs:02d}")

    def on_stream_connected(self):
        self.lbl_status.config(text="Status: Live AI Stream 🟢", foreground="#00e676")
        self.btn_connect.config(text="⏹ Stop Stream", style="Danger.TButton", state=tk.NORMAL)
        self.btn_snapshot.config(state=tk.NORMAL)
        self.btn_record.config(state=tk.NORMAL)

    def on_stream_failed(self, error_msg):
        self.is_streaming = False
        self.lbl_status.config(text="Status: Connection Failed 🔴", foreground="#ff4d4d")
        self.btn_connect.config(text="▶ Start Stream", style="Accent.TButton", state=tk.NORMAL)
        messagebox.showerror("Connection Error", error_msg)

    def on_stream_stopped(self):
        self.lbl_status.config(text="Status: Disconnected 🔴", foreground="#ff4d4d")
        self.btn_connect.config(text="▶ Start Stream", style="Accent.TButton", state=tk.NORMAL)
        self.btn_snapshot.config(state=tk.DISABLED)
        self.btn_record.config(state=tk.DISABLED)
        self.lbl_fps.config(text="0.0 FPS")
        self.lbl_rec_timer.config(text="")
        self.canvas.delete("all")
        self.canvas_text = self.canvas.create_text(
            self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2, 
            text="Camera Stream Stopped\n\nClick 'Start Stream' to reconnect.",
            fill="#777777", font=("Segoe UI", 14), justify=tk.CENTER
        )

    def stop_stream(self):
        self.is_streaming = False
        self.btn_connect.config(text="Stopping...", state=tk.DISABLED)

    def take_snapshot(self):
        if self.current_frame is None:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = SNAPSHOTS_DIR / f"snapshot_{timestamp}.jpg"
        
        cv2.imwrite(str(filename), self.current_frame)
        self.log_ai_event(f"📸 Snapshot saved: {timestamp[-6:]}")

        self.canvas.create_rectangle(0, 0, self.canvas.winfo_width(), self.canvas.winfo_height(), fill="#ffffff", tags="flash")
        self.after(80, lambda: self.canvas.delete("flash"))

    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        if self.current_frame is None:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = RECORDINGS_DIR / f"recording_{timestamp}.mp4"

        fh, fw = self.current_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        fps_target = max(15.0, self.fps if self.fps > 0 else 25.0)

        self.out_writer = cv2.VideoWriter(str(filename), fourcc, fps_target, (fw, fh))
        self.is_recording = True
        self.recording_start_time = time.time()

        self.btn_record.config(text="⏹ Stop Recording", style="Danger.TButton")
        self.log_ai_event(f"🔴 Recording started")

    def stop_recording(self):
        self.is_recording = False
        self.stop_recording_internal()
        self.btn_record.config(text="🔴 Record", style="TButton")
        self.lbl_rec_timer.config(text="")
        self.log_ai_event(f"💾 Recording saved")
        messagebox.showinfo("Recording Stopped", f"Video recording saved in:\n{RECORDINGS_DIR}")

    def stop_recording_internal(self):
        if self.out_writer:
            self.out_writer.release()
            self.out_writer = None
        self.recording_start_time = None

    def open_folder(self, folder_path):
        folder_path.mkdir(exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder_path)
        elif sys.platform == "darwin":
            os.system(f'open "{folder_path}"')
        else:
            os.system(f'xdg-open "{folder_path}"')

    def on_canvas_resize(self, event):
        if not self.is_streaming and hasattr(self, "canvas_text"):
            self.canvas.coords(self.canvas_text, event.width // 2, event.height // 2)

    def on_closing(self):
        self.save_config()
        self.is_streaming = False
        self.destroy()


if __name__ == "__main__":
    app = MobileCameraApp()
    app.mainloop()
