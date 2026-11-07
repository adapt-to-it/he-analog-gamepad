"""
X68PRO HE → Virtual Xbox 360 Gamepad
Reads analog key data and maps it to a virtual controller via ViGEmBus.

Modes:
- HYBRID: Only WASD → left stick. Keyboard + mouse work normally for games
  that support simultaneous gamepad + KB/M input.
- FULL CONTROLLER: All keys mapped to Xbox buttons/sticks/triggers.
  For games that don't support mixed input.

Features:
- Analog WASD → Left stick with true analog walking/running
- Configurable deadzone, smoothing, sensitivity curves
- Live GUI with stick visualization and config
"""

import tkinter as tk
from tkinter import ttk
import vgamepad as vg
import pywinusb.hid as hid
import ctypes
import sys
import threading
import time
import json
import os
import math

from device_config import (
    find_config_interface, load_device_ids, load_protocol, resolve_config_path,
)

# ── Config ──────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Pick the config that matches the plugged-in keyboard (key_config.json or devices/*.json).
_CONNECTED = {(d.vendor_id, d.product_id) for d in hid.find_all_hid_devices()}
CONFIG_PATH = resolve_config_path(BASE_DIR, _CONNECTED)
GAMEPAD_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "gamepad_config.json")

VID, PID, DEVICE_NAME = load_device_ids(CONFIG_PATH)
DEVICE_KEY = f"{VID:04X}:{PID:04X}"
PROTOCOL = load_protocol(CONFIG_PATH)
ENABLE_CMD = PROTOCOL["enable_cmd"]
DISABLE_CMD = PROTOCOL["disable_cmd"]
REPORT_ID = PROTOCOL["report_id"]
PREFIX = PROTOCOL["prefix"]
BYTE_LO = PROTOCOL["analog_byte_lo"]
BYTE_HI = PROTOCOL["analog_byte_hi"]
KEY_ID_BYTE = PROTOCOL["key_id_byte"]

hid_dll = ctypes.WinDLL('hid.dll')
kernel32 = ctypes.WinDLL('kernel32.dll')

winmm = ctypes.WinDLL('winmm.dll')

# Gamepad timing: the worker thread wakes on every HID report, and at least
# every IDLE_TICK so smoothing can settle after the last report.
SMOOTHING_REF_DT = 1.0 / 120.0   # smoothing values are tuned for 120 Hz steps
IDLE_TICK = 0.004                # max wait between updates without reports
MIN_UPDATE_INTERVAL = 0.001      # cap at ~1000 updates/s towards ViGEm

ANALOG_MAX = float(PROTOCOL["analog_max"])  # max raw value from keyboard (350 on X68PRO HE, 730 on X68HE)

# Modes
MODE_HYBRID = "hybrid"           # Only left stick, KB+mouse pass through
MODE_FULL = "full_controller"    # Everything mapped to Xbox controller

# GUI colors: one accent, the rest neutral
PALETTE = {
    "bg": "#1e1f22",
    "panel": "#2b2d31",
    "field": "#383a40",
    "border": "#3f4147",
    "text": "#dbdee1",
    "muted": "#949ba4",
    "accent": "#5b8def",
    "ok": "#3ba55d",
    "warn": "#d29922",
    "error": "#e5534b",
    "canvas": "#18191c",
    "grid": "#3f4147",
}
UI_FONT = ("Segoe UI", 9)
TITLE_FONT = ("Segoe UI", 10, "bold")
VALUE_FONT = ("Consolas", 9)  # numeric values only

# Default gamepad bindings: keyboard_key -> gamepad_action
DEFAULT_BINDINGS = {
    # Left stick (analog)
    "left_stick_up": "W",
    "left_stick_down": "S",
    "left_stick_left": "A",
    "left_stick_right": "D",
    # Right stick (analog)
    "right_stick_up": "I",
    "right_stick_down": "K",
    "right_stick_left": "J",
    "right_stick_right": "L",
    # Face buttons
    "btn_a": "SPACE",
    "btn_b": "LSHIFT",
    "btn_x": "E",
    "btn_y": "Q",
    # Bumpers & triggers
    "left_bumper": "TAB",
    "right_bumper": "R",
    "left_trigger": "LCTRL",
    "right_trigger": "F",
    # D-pad
    "dpad_up": "UP",
    "dpad_down": "DOWN",
    "dpad_left": "LEFT",
    "dpad_right": "RIGHT",
    # System
    "btn_start": "ENTER",
    "btn_back": "ESC",
    "btn_thumb_left": "C",
    "btn_thumb_right": "V",
}

DEFAULT_SETTINGS = {
    "mode": MODE_HYBRID,           # hybrid or full_controller
    "deadzone": 0.05,              # 0-1, below this = 0
    "smoothing": 0.3,              # 0-1, EMA factor (0=no smoothing, 1=max)
    "sensitivity_curve": 1.0,      # 1=linear, <1=more sensitive at start, >1=less sensitive
    "trigger_threshold": 0.15,     # analog threshold to consider trigger "pressed"
    "button_threshold": 0.15,      # analog threshold for digital button press
    "analog_max_override": ANALOG_MAX,  # override max analog value
}


class KeyboardState:
    """Tracks analog values for all keys."""
    def __init__(self, key_mapping):
        self.key_mapping = key_mapping  # key_label -> key_id
        self.id_to_key = {v: k for k, v in key_mapping.items()}
        self.values = {}  # key_label -> raw analog (0-ANALOG_MAX)
        self.lock = threading.Lock()
        self.changed = threading.Event()  # set on every new analog value

    def update(self, key_id, analog_value):
        key_label = self.id_to_key.get(key_id)
        if key_label:
            with self.lock:
                self.values[key_label] = analog_value
            self.changed.set()

    def get(self, key_label):
        with self.lock:
            return self.values.get(key_label, 0)

    def get_normalized(self, key_label, settings):
        """Get value normalized to 0.0-1.0 with deadzone and curve."""
        raw = self.get(key_label)
        max_val = settings.get("analog_max_override", ANALOG_MAX)
        normalized = min(1.0, raw / max_val) if max_val > 0 else 0.0

        # Deadzone
        dz = settings.get("deadzone", 0.05)
        if normalized < dz:
            return 0.0
        normalized = (normalized - dz) / (1.0 - dz)

        # Sensitivity curve
        curve = settings.get("sensitivity_curve", 1.0)
        if curve != 1.0:
            normalized = math.pow(normalized, curve)

        return min(1.0, max(0.0, normalized))


class SmoothedAxis:
    """Exponential moving average for stick axes."""
    def __init__(self):
        self.value = 0.0

    def update(self, target, smoothing, dt):
        """Move towards target. The result depends on elapsed time, not on
        how often update() runs: smoothing is the share kept per 1/120 s."""
        if smoothing <= 0:
            self.value = target
        else:
            keep = math.pow(smoothing, dt / SMOOTHING_REF_DT)
            self.value += (target - self.value) * (1.0 - keep)
        return self.value


class VirtualGamepad:
    """Manages the ViGEm Xbox 360 controller."""
    def __init__(self):
        self.pad = vg.VX360Gamepad()
        self.lx = SmoothedAxis()
        self.ly = SmoothedAxis()
        self.rx = SmoothedAxis()
        self.ry = SmoothedAxis()
        self.lt = SmoothedAxis()
        self.rt = SmoothedAxis()

    def update(self, kb_state, bindings, settings, dt):
        smoothing = settings.get("smoothing", 0.3)
        mode = settings.get("mode", MODE_HYBRID)

        # ── Left stick (always active) ──
        up = kb_state.get_normalized(bindings.get("left_stick_up", ""), settings)
        down = kb_state.get_normalized(bindings.get("left_stick_down", ""), settings)
        left = kb_state.get_normalized(bindings.get("left_stick_left", ""), settings)
        right = kb_state.get_normalized(bindings.get("left_stick_right", ""), settings)

        raw_lx = right - left
        raw_ly = up - down

        # Clamp diagonal magnitude to 1.0
        mag = math.sqrt(raw_lx ** 2 + raw_ly ** 2)
        if mag > 1.0:
            raw_lx /= mag
            raw_ly /= mag

        lx_val = self.lx.update(raw_lx, smoothing, dt)
        ly_val = self.ly.update(raw_ly, smoothing, dt)

        self.pad.left_joystick_float(x_value_float=lx_val, y_value_float=ly_val)

        rx_val = ry_val = lt_val = rt_val = 0.0

        if mode == MODE_FULL:
            btn_thresh = settings.get("button_threshold", 0.15)

            # ── Right stick ──
            r_up = kb_state.get_normalized(bindings.get("right_stick_up", ""), settings)
            r_down = kb_state.get_normalized(bindings.get("right_stick_down", ""), settings)
            r_left = kb_state.get_normalized(bindings.get("right_stick_left", ""), settings)
            r_right = kb_state.get_normalized(bindings.get("right_stick_right", ""), settings)

            raw_rx = r_right - r_left
            raw_ry = r_up - r_down
            mag = math.sqrt(raw_rx ** 2 + raw_ry ** 2)
            if mag > 1.0:
                raw_rx /= mag
                raw_ry /= mag

            rx_val = self.rx.update(raw_rx, smoothing, dt)
            ry_val = self.ry.update(raw_ry, smoothing, dt)
            self.pad.right_joystick_float(x_value_float=rx_val, y_value_float=ry_val)

            # ── Triggers (analog) ──
            lt_raw = kb_state.get_normalized(bindings.get("left_trigger", ""), settings)
            rt_raw = kb_state.get_normalized(bindings.get("right_trigger", ""), settings)
            lt_val = self.lt.update(lt_raw, smoothing, dt)
            rt_val = self.rt.update(rt_raw, smoothing, dt)
            self.pad.left_trigger_float(value_float=lt_val)
            self.pad.right_trigger_float(value_float=rt_val)

            # ── Buttons (digital from analog threshold) ──
            button_map = {
                "btn_a": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
                "btn_b": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                "btn_x": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
                "btn_y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                "left_bumper": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                "right_bumper": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                "btn_start": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
                "btn_back": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
                "btn_thumb_left": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
                "btn_thumb_right": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
            }

            for action, xbutton in button_map.items():
                key_label = bindings.get(action, "")
                val = kb_state.get_normalized(key_label, settings)
                if val > btn_thresh:
                    self.pad.press_button(button=xbutton)
                else:
                    self.pad.release_button(button=xbutton)

            # ── D-Pad ──
            dpad_up = kb_state.get_normalized(bindings.get("dpad_up", ""), settings) > btn_thresh
            dpad_down = kb_state.get_normalized(bindings.get("dpad_down", ""), settings) > btn_thresh
            dpad_left = kb_state.get_normalized(bindings.get("dpad_left", ""), settings) > btn_thresh
            dpad_right = kb_state.get_normalized(bindings.get("dpad_right", ""), settings) > btn_thresh

            # Each direction is set on its own, so a released one never stays pressed.
            for pressed, xbutton in (
                (dpad_up, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP),
                (dpad_down, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN),
                (dpad_left, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT),
                (dpad_right, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT),
            ):
                if pressed:
                    self.pad.press_button(button=xbutton)
                else:
                    self.pad.release_button(button=xbutton)

        self.pad.update()
        return lx_val, ly_val, rx_val, ry_val, lt_val, rt_val


# Binding groups shown in the Bindings tab: (header, [(action, friendly name)])
BINDING_GROUPS = [
    ("Left stick", [
        ("left_stick_up", "Up"), ("left_stick_down", "Down"),
        ("left_stick_left", "Left"), ("left_stick_right", "Right"),
    ]),
    ("Right stick", [
        ("right_stick_up", "Up"), ("right_stick_down", "Down"),
        ("right_stick_left", "Left"), ("right_stick_right", "Right"),
    ]),
    ("Triggers", [
        ("left_trigger", "Left trigger"), ("right_trigger", "Right trigger"),
    ]),
    ("Buttons", [
        ("btn_a", "A"), ("btn_b", "B"), ("btn_x", "X"), ("btn_y", "Y"),
        ("left_bumper", "Left bumper"), ("right_bumper", "Right bumper"),
        ("btn_thumb_left", "Left thumb"), ("btn_thumb_right", "Right thumb"),
    ]),
    ("D-pad", [
        ("dpad_up", "Up"), ("dpad_down", "Down"),
        ("dpad_left", "Left"), ("dpad_right", "Right"),
    ]),
    ("System", [
        ("btn_start", "Start"), ("btn_back", "Back"),
    ]),
]


class GamepadApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{DEVICE_NAME} → Xbox 360 Gamepad")
        self.root.geometry("760x440")
        self.root.minsize(700, 420)
        self.root.configure(bg=PALETTE["bg"])
        self.root.resizable(True, True)

        self.running = True
        self.active = False

        # Load configs
        self.key_mapping = self._load_key_config()
        self.bindings, self.settings = self._load_gamepad_config()

        # State
        self.kb_state = KeyboardState(self.key_mapping)
        self.gamepad = None
        self.opened_devices = []
        self.config_path = None

        # GUI state
        self.lx_display = 0.0
        self.ly_display = 0.0
        self.rx_display = 0.0
        self.ry_display = 0.0
        self.lt_display = 0.0
        self.rt_display = 0.0
        self._save_job = None

        self._apply_style()
        self._build_ui()
        self._init_hid()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.pad_lock = threading.Lock()  # guards self.gamepad between threads
        winmm.timeBeginPeriod(1)  # 1 ms timer resolution instead of 15.6 ms
        self.worker = threading.Thread(target=self._gamepad_worker, daemon=True)
        self.worker.start()
        self._ui_update_loop()

    def _load_key_config(self):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        mapping = cfg["key_mapping"]
        return {k: int(v) for k, v in mapping.items()}

    def _load_gamepad_config(self):
        if os.path.exists(GAMEPAD_CONFIG_PATH):
            with open(GAMEPAD_CONFIG_PATH) as f:
                cfg = json.load(f)
            bindings = cfg.get("bindings", DEFAULT_BINDINGS)
            settings = {**DEFAULT_SETTINGS, **cfg.get("settings", {})}
            # A saved Analog Max belongs to the keyboard it was tuned on.
            if settings.get("analog_max_device") != DEVICE_KEY:
                settings["analog_max_override"] = ANALOG_MAX
        else:
            bindings = dict(DEFAULT_BINDINGS)
            settings = dict(DEFAULT_SETTINGS)
        return bindings, settings

    def _save_gamepad_config(self):
        # Sync mode from UI
        self.settings["mode"] = self.mode_var.get()
        self.settings["analog_max_device"] = DEVICE_KEY
        cfg = {"bindings": self.bindings, "settings": self.settings}
        with open(GAMEPAD_CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)

    def _schedule_save(self):
        # Debounce: write the config once the user has paused for 500 ms
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(500, self._do_save)

    def _do_save(self):
        self._save_job = None
        self._save_gamepad_config()
        self.saved_label.config(text="Saved")
        self.root.after(1500, lambda: self.saved_label.config(text=""))

    def _apply_style(self):
        p = PALETTE
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=p["panel"], foreground=p["text"], font=UI_FONT)
        style.configure("TNotebook", background=p["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=p["panel"], foreground=p["muted"],
                        padding=(10, 4), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", p["field"])],
                  foreground=[("selected", p["text"])])
        # clam draws the slider thumb with "background": accent thumb on a field trough
        style.configure("TScale", background=p["accent"], troughcolor=p["canvas"],
                        bordercolor=p["panel"], lightcolor=p["accent"], darkcolor=p["accent"],
                        sliderlength=14)
        style.map("TScale", background=[("active", p["text"])])
        # ttk buttons: tk.Button ignores colors on macOS (native white button)
        for name, bg, fg, hover in (("Accent.TButton", p["accent"], p["bg"], p["text"]),
                                    ("Danger.TButton", p["field"], p["error"], p["border"]),
                                    ("Flat.TButton", p["field"], p["text"], p["border"])):
            style.configure(name, background=bg, foreground=fg, bordercolor=bg,
                            lightcolor=bg, darkcolor=bg, focuscolor=bg,
                            padding=(10, 4), relief="flat")
            style.map(name, background=[("pressed", hover), ("active", hover)],
                      lightcolor=[("active", hover)], darkcolor=[("active", hover)])
        style.configure("Accent.TButton", font=TITLE_FONT)
        style.configure("Danger.TButton", font=TITLE_FONT)
        style.configure("TRadiobutton", background=p["panel"], foreground=p["text"], font=UI_FONT)
        style.map("TRadiobutton",
                  background=[("active", p["panel"])],
                  indicatorcolor=[("selected", p["accent"]), ("!selected", p["field"])])
        style.configure("TCombobox", fieldbackground=p["field"], background=p["panel"],
                        foreground=p["text"], arrowcolor=p["muted"], bordercolor=p["border"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", p["field"])],
                  foreground=[("readonly", p["text"])],
                  selectbackground=[("readonly", p["field"])],
                  selectforeground=[("readonly", p["text"])])
        style.configure("TScrollbar", background=p["field"], troughcolor=p["canvas"],
                        arrowcolor=p["muted"], bordercolor=p["canvas"])

    def _build_ui(self):
        p = PALETTE
        # Prevent keyboard from triggering GUI
        self.root.bind_all('<space>', lambda e: 'break')
        self.root.bind_all('<Return>', lambda e: 'break')

        # ── Top bar ──
        top = tk.Frame(self.root, bg=p["panel"])
        top.pack(fill=tk.X, padx=8, pady=(8, 4))

        connected = (VID, PID) in _CONNECTED
        self.device_label = tk.Label(
            top, text=f"{DEVICE_NAME} {'connected' if connected else 'not found'}",
            font=TITLE_FONT, fg=p["ok"] if connected else p["error"], bg=p["panel"]
        )
        self.device_label.pack(side=tk.LEFT, padx=10, pady=8)

        self.status_label = tk.Label(
            top, text="DISCONNECTED", font=TITLE_FONT, fg=p["error"], bg=p["panel"]
        )
        self.status_label.pack(side=tk.LEFT, padx=4, pady=8)

        # Accent when off; panel with error text when on
        self.toggle_btn = ttk.Button(
            top, text="Activate", style="Accent.TButton",
            command=self._toggle_active, width=14
        )
        self.toggle_btn.pack(side=tk.RIGHT, padx=10, pady=8)

        # Mode selector
        mode_frame = tk.Frame(top, bg=p["panel"])
        mode_frame.pack(side=tk.RIGHT, padx=10, pady=8)

        self.mode_var = tk.StringVar(value=self.settings.get("mode", MODE_HYBRID))
        ttk.Radiobutton(
            mode_frame, text="Hybrid", value=MODE_HYBRID, variable=self.mode_var,
            command=lambda: self._set_mode(self.mode_var.get())
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(
            mode_frame, text="Full controller", value=MODE_FULL, variable=self.mode_var,
            command=lambda: self._set_mode(self.mode_var.get())
        ).pack(side=tk.LEFT)

        # Mode hint
        self.mode_desc = tk.Label(
            self.root, text="", font=UI_FONT, fg=p["muted"], bg=p["bg"], anchor=tk.W
        )
        self.mode_desc.pack(fill=tk.X, padx=16, pady=(0, 2))

        # ── Main area ──
        main = tk.Frame(self.root, bg=p["bg"])
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Left: controller view
        self.viz_frame = tk.LabelFrame(
            main, text=" Controller ", font=TITLE_FONT, fg=p["text"], bg=p["panel"],
            bd=0, highlightthickness=0
        )
        self.viz_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        # Stick canvases side by side
        self.sticks_frame = tk.Frame(self.viz_frame, bg=p["panel"])
        self.sticks_frame.pack(fill=tk.X, padx=5, pady=5)

        # Left stick
        ls_frame = tk.Frame(self.sticks_frame, bg=p["panel"])
        ls_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.ls_title = tk.Label(ls_frame, text=self._stick_title("LEFT", "left_stick"),
                                 font=UI_FONT, fg=p["muted"], bg=p["panel"])
        self.ls_title.pack()
        self.left_canvas = tk.Canvas(ls_frame, bg=p["canvas"], width=150, height=150,
                                     highlightthickness=0)
        self.left_canvas.pack(padx=5, pady=5)
        self.ls_label = tk.Label(ls_frame, text="X: 0.00  Y: 0.00",
                                 font=VALUE_FONT, fg=p["text"], bg=p["panel"])
        self.ls_label.pack()

        # Right stick (container for show/hide)
        self.rs_frame = tk.Frame(self.sticks_frame, bg=p["panel"])
        self.rs_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.rs_title = tk.Label(self.rs_frame, text=self._stick_title("RIGHT", "right_stick"),
                                 font=UI_FONT, fg=p["muted"], bg=p["panel"])
        self.rs_title.pack()
        self.right_canvas = tk.Canvas(self.rs_frame, bg=p["canvas"], width=150, height=150,
                                      highlightthickness=0)
        self.right_canvas.pack(padx=5, pady=5)
        self.rs_label = tk.Label(self.rs_frame, text="X: 0.00  Y: 0.00",
                                 font=VALUE_FONT, fg=p["text"], bg=p["panel"])
        self.rs_label.pack()

        # Triggers (container for show/hide)
        self.trig_frame = tk.Frame(self.viz_frame, bg=p["panel"])
        self.trig_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(self.trig_frame, text="LT", font=UI_FONT,
                 fg=p["muted"], bg=p["panel"]).pack(side=tk.LEFT)
        self.lt_bar = tk.Canvas(self.trig_frame, bg=p["canvas"], width=1, height=16, highlightthickness=0)
        self.lt_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.rt_bar = tk.Canvas(self.trig_frame, bg=p["canvas"], width=1, height=16, highlightthickness=0)
        self.rt_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Label(self.trig_frame, text="RT", font=UI_FONT,
                 fg=p["muted"], bg=p["panel"]).pack(side=tk.LEFT)

        # Buttons status (container for show/hide)
        self.btn_label = tk.Label(
            self.viz_frame, text="Buttons: ---", font=UI_FONT,
            fg=p["text"], bg=p["panel"], anchor=tk.W
        )
        self.btn_label.pack(fill=tk.X, padx=10, pady=5)

        # Raw WASD values
        self.raw_label = tk.Label(
            self.viz_frame, text="Raw WASD: ---", font=VALUE_FONT,
            fg=p["muted"], bg=p["panel"], anchor=tk.W
        )
        self.raw_label.pack(fill=tk.X, padx=10, pady=(0, 5))

        # ── Right: tabs ──
        right = tk.Frame(main, bg=p["bg"])
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0), before=self.viz_frame)  # packed first: keeps its width in full mode

        # Reset row at the bottom, packed first so the notebook cannot push it out
        reset_row = tk.Frame(right, bg=p["bg"])
        reset_row.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        self.reset_btn = ttk.Button(
            reset_row, text="Reset to defaults", style="Flat.TButton",
            command=self._reset_defaults
        )
        self.reset_btn.pack(side=tk.LEFT)
        self.saved_label = tk.Label(reset_row, text="", font=UI_FONT,
                                    fg=p["ok"], bg=p["bg"])
        self.saved_label.pack(side=tk.LEFT, padx=8)

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        tune = tk.Frame(self.tabs, bg=p["panel"])
        bind = tk.Frame(self.tabs, bg=p["panel"])
        self.tabs.add(tune, text="Tuning")
        self.tabs.add(bind, text="Bindings")

        # Tuning: one grid row per slider
        self.sliders = {}
        self.slider_labels = {}
        self.slider_rows = {}  # key -> ((name, slider, value), shown in hybrid)
        slider_defs = [
            ("deadzone", "Deadzone", 0, 0.5, True),
            ("smoothing", "Smoothing", 0, 0.95, True),
            ("sensitivity_curve", "Sensitivity", 0.2, 3.0, True),
            ("button_threshold", "Btn Threshold", 0.01, 0.5, False),
            ("trigger_threshold", "Trig Threshold", 0.01, 0.5, False),
            ("analog_max_override", "Analog Max", 100, max(500, round(ANALOG_MAX * 1.5)), True),
        ]

        for row, (key, label, min_v, max_v, show_hybrid) in enumerate(slider_defs):
            name = tk.Label(tune, text=label, font=UI_FONT, fg=p["text"],
                            bg=p["panel"], width=12, anchor=tk.W)
            name.grid(row=row, column=0, sticky="w", padx=(8, 4), pady=4)

            slider = ttk.Scale(tune, from_=min_v, to=max_v, value=self.settings[key],
                               orient=tk.HORIZONTAL, length=130,
                               command=lambda v, k=key: self._on_slider(k, v))
            slider.grid(row=row, column=1, sticky="ew", padx=4, pady=4)

            value = tk.Label(tune, text="", font=VALUE_FONT, fg=p["text"],
                             bg=p["panel"], width=6, anchor=tk.E)
            value.grid(row=row, column=2, sticky="e", padx=(4, 8), pady=4)

            self.sliders[key] = slider
            self.slider_labels[key] = value
            self.slider_rows[key] = ((name, slider, value), show_hybrid)
            self._show_value(key)

        # Bindings: scrollable list of groups
        bind_canvas = tk.Canvas(bind, bg=p["panel"], highlightthickness=0,
                                width=300, height=230)
        bind_scroll = ttk.Scrollbar(bind, orient=tk.VERTICAL, command=bind_canvas.yview)
        bind_inner = tk.Frame(bind_canvas, bg=p["panel"])

        bind_inner.bind("<Configure>", lambda e: bind_canvas.configure(scrollregion=bind_canvas.bbox("all")))
        bind_canvas.create_window((0, 0), window=bind_inner, anchor=tk.NW)
        bind_canvas.configure(yscrollcommand=bind_scroll.set)

        bind_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=8)
        bind_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=4, pady=8)

        self.bind_vars = {}
        self.bind_widgets = {}
        self.bind_groups = []  # (group frame, shown in hybrid)
        all_keys = sorted(self.key_mapping.keys())

        for row, (title, actions) in enumerate(BINDING_GROUPS):
            group = tk.Frame(bind_inner, bg=p["panel"])
            group.grid(row=row, column=0, sticky="ew", pady=(4, 0))
            tk.Label(group, text=title, font=TITLE_FONT,
                     fg=p["muted"], bg=p["panel"], anchor=tk.W).pack(fill=tk.X)

            for action, friendly in actions:
                f = tk.Frame(group, bg=p["panel"])
                f.pack(fill=tk.X, pady=1)

                tk.Label(f, text=f"{friendly}:", font=UI_FONT,
                         fg=p["text"], bg=p["panel"], width=12, anchor=tk.E).pack(side=tk.LEFT)

                self.bindings.setdefault(action, DEFAULT_BINDINGS[action])
                var = tk.StringVar(value=self.bindings[action])
                combo = ttk.Combobox(f, textvariable=var, values=all_keys,
                                     width=8, font=VALUE_FONT, state="readonly")
                combo.pack(side=tk.LEFT, padx=2)
                combo.bind("<<ComboboxSelected>>",
                           lambda e, a=action, v=var: self._on_binding_change(a, v))
                self.bind_vars[action] = var
                self.bind_widgets[action] = combo

            self.bind_groups.append((group, title == "Left stick"))

        # Apply initial mode UI
        self._update_mode_ui()

    def _stick_title(self, side, prefix):
        keys = [self.bindings.get(f"{prefix}_{d}", "") for d in ("up", "left", "down", "right")]
        return f"{side} STICK ({' '.join(keys)})"

    def _refresh_stick_titles(self):
        self.ls_title.config(text=self._stick_title("LEFT", "left_stick"))
        self.rs_title.config(text=self._stick_title("RIGHT", "right_stick"))

    def _show_value(self, key):
        v = self.settings[key]
        text = f"{round(v)}" if key == "analog_max_override" else f"{v:.2f}"
        self.slider_labels[key].config(text=text)

    def _set_mode(self, mode):
        self.mode_var.set(mode)
        self.settings["mode"] = mode
        self._update_mode_ui()
        self._schedule_save()

    def _update_mode_ui(self):
        p = PALETTE
        mode = self.settings.get("mode", MODE_HYBRID)
        is_hybrid = (mode == MODE_HYBRID)

        # Mode hint
        if is_hybrid:
            self.mode_desc.config(
                text="HYBRID: left stick only. Keyboard and mouse pass through to the game."
            )
        else:
            self.mode_desc.config(
                text="FULL: every input is mapped to the Xbox controller."
            )

        # Right stick, triggers and buttons line: full mode only
        if is_hybrid:
            self.rs_frame.pack_forget()
            self.trig_frame.pack_forget()
            self.btn_label.pack_forget()
        else:
            self.rs_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.trig_frame.pack(fill=tk.X, padx=10, pady=5, before=self.raw_label)
            self.btn_label.pack(fill=tk.X, padx=10, pady=5, before=self.raw_label)

        # Thresholds: full mode only (grid_remove keeps the row order)
        for key, (widgets, show_in_hybrid) in self.slider_rows.items():
            for w in widgets:
                if is_hybrid and not show_in_hybrid:
                    w.grid_remove()
                else:
                    w.grid()

        # Binding groups: hybrid shows only the left stick
        for group, show_in_hybrid in self.bind_groups:
            if is_hybrid and not show_in_hybrid:
                group.grid_remove()
            else:
                group.grid()

    def _on_slider(self, key, value):
        self.settings[key] = float(value)
        self._show_value(key)
        self._schedule_save()

    def _on_binding_change(self, action, var):
        self.bindings[action] = var.get()
        self._refresh_stick_titles()
        self._schedule_save()

    def _reset_defaults(self):
        self.settings = dict(DEFAULT_SETTINGS)
        self.bindings = dict(DEFAULT_BINDINGS)

        self.mode_var.set(self.settings["mode"])
        for key, slider in self.sliders.items():
            slider.set(self.settings[key])
            self._show_value(key)
        for action, var in self.bind_vars.items():
            var.set(self.bindings[action])
        self._refresh_stick_titles()
        self._update_mode_ui()
        self._schedule_save()

    def _init_hid(self):
        p = PALETTE
        devices = hid.find_all_hid_devices()
        kbd_devs = [d for d in devices if d.vendor_id == VID and d.product_id == PID]

        for d in kbd_devs:
            try:
                d.open()
                d.set_raw_data_handler(self._hid_handler)
                self.opened_devices.append(d)
            except:
                pass
        self.config_path = find_config_interface(self.opened_devices)

        if self.opened_devices:
            self.status_label.config(text=f"HID OK ({len(self.opened_devices)} ifaces)", fg=p["ok"])
        else:
            self.status_label.config(text="HID ERROR", fg=p["error"])

    def _send_feature(self, cmd):
        if not self.config_path:
            return False
        h = kernel32.CreateFileW(self.config_path, 0xC0000000, 0x03, None, 3, 0, None)
        if h == ctypes.c_void_p(-1).value:
            return False
        buf = (ctypes.c_byte * 65)()
        buf[0] = 0
        for i in range(64):
            buf[i + 1] = cmd[i]
        r = hid_dll.HidD_SetFeature(h, ctypes.byref(buf), 65)
        kernel32.CloseHandle(h)
        return bool(r)

    def _hid_handler(self, data):
        if len(data) <= max(BYTE_LO, BYTE_HI, KEY_ID_BYTE):
            return
        if data[0] != REPORT_ID or data[1] != PREFIX:
            return
        analog = data[BYTE_LO] + data[BYTE_HI] * 256
        key_id = data[KEY_ID_BYTE]
        self.kb_state.update(key_id, analog)

    def _toggle_active(self):
        if self.active:
            self._deactivate()
        else:
            self._activate()

    def _activate(self):
        p = PALETTE
        # Enable analog mode
        if not self._send_feature(ENABLE_CMD):
            self.status_label.config(text="ENABLE FAILED", fg=p["error"])
            return

        # Create gamepad
        try:
            gamepad = VirtualGamepad()
        except Exception as e:
            self.status_label.config(text=f"ViGEm ERROR: {e}", fg=p["error"])
            return

        with self.pad_lock:
            self.gamepad = gamepad
            self.active = True
        self.status_label.config(text="GAMEPAD ACTIVE", fg=p["ok"])
        self.toggle_btn.config(text="Deactivate", style="Danger.TButton")

    def _deactivate(self):
        p = PALETTE
        with self.pad_lock:
            self.active = False
            gamepad, self.gamepad = self.gamepad, None
        self._send_feature(DISABLE_CMD)

        if gamepad:
            # Reset controller state
            gamepad.pad.reset()
            gamepad.pad.update()
            del gamepad.pad

        self.status_label.config(text="GAMEPAD OFF", fg=p["warn"])
        self.toggle_btn.config(text="Activate", style="Accent.TButton")

    def _gamepad_worker(self):
        """Send the gamepad state as soon as a HID report arrives.

        Runs outside the Tk loop, so the GUI does not add delay or jitter.
        Never touches Tk widgets: it only writes the *_display values.
        """
        changed = self.kb_state.changed
        last = time.perf_counter()
        while self.running:
            changed.wait(IDLE_TICK)
            changed.clear()
            now = time.perf_counter()
            dt = now - last
            last = now
            with self.pad_lock:
                if self.active and self.gamepad:
                    vals = self.gamepad.update(self.kb_state, self.bindings, self.settings, dt)
                    self.lx_display, self.ly_display = vals[0], vals[1]
                    self.rx_display, self.ry_display = vals[2], vals[3]
                    self.lt_display, self.rt_display = vals[4], vals[5]
            # Reports can arrive faster than 1 kHz: merge them instead of
            # sending one ViGEm update each.
            spare = MIN_UPDATE_INTERVAL - (time.perf_counter() - now)
            if spare > 0:
                time.sleep(spare)

    def _ui_update_loop(self):
        """Update UI at ~30fps."""
        if not self.running:
            return

        mode = self.settings.get("mode", MODE_HYBRID)

        self._draw_stick(self.left_canvas, self.lx_display, self.ly_display)
        self.ls_label.config(text=f"X:{self.lx_display:+.2f}  Y:{self.ly_display:+.2f}")

        if mode == MODE_FULL:
            self._draw_stick(self.right_canvas, self.rx_display, self.ry_display)
            self._draw_trigger(self.lt_bar, self.lt_display)
            self._draw_trigger(self.rt_bar, self.rt_display)
            self.rs_label.config(text=f"X:{self.rx_display:+.2f}  Y:{self.ry_display:+.2f}")

            # Button status
            thresh = self.settings.get("button_threshold", 0.15)
            active_btns = []
            for action in ["btn_a", "btn_b", "btn_x", "btn_y", "left_bumper", "right_bumper",
                           "btn_start", "btn_back", "btn_thumb_left", "btn_thumb_right"]:
                key = self.bindings.get(action, "")
                if self.kb_state.get_normalized(key, self.settings) > thresh:
                    short = action.replace("btn_", "").replace("left_", "L").replace("right_", "R").upper()
                    active_btns.append(short)
            self.btn_label.config(text=f"Buttons: {' '.join(active_btns) if active_btns else '---'}")

        # Raw WASD
        w = self.kb_state.get(self.bindings.get("left_stick_up", ""))
        a = self.kb_state.get(self.bindings.get("left_stick_left", ""))
        s = self.kb_state.get(self.bindings.get("left_stick_down", ""))
        d = self.kb_state.get(self.bindings.get("left_stick_right", ""))
        self.raw_label.config(text=f"Raw: W={w:3d} A={a:3d} S={s:3d} D={d:3d}")

        self.root.after(33, self._ui_update_loop)

    def _draw_stick(self, canvas, x, y):
        p = PALETTE
        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10:
            return

        cx, cy = w / 2, h / 2
        r = min(cx, cy) - 10

        # Outer circle
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline=p["grid"], width=1)

        # Cross
        canvas.create_line(cx - r, cy, cx + r, cy, fill=p["grid"])
        canvas.create_line(cx, cy - r, cx, cy + r, fill=p["grid"])

        # Deadzone circle
        dz = self.settings.get("deadzone", 0.05)
        dz_r = r * dz
        canvas.create_oval(cx - dz_r, cy - dz_r, cx + dz_r, cy + dz_r,
                           outline=p["grid"], width=1, dash=(2, 2))

        # Dot position: solid accent, radius 6
        dx = cx + x * r
        dy = cy - y * r  # Y inverted
        dot_r = 6
        canvas.create_oval(dx - dot_r, dy - dot_r, dx + dot_r, dy + dot_r,
                           fill=p["accent"], outline="")

    def _draw_trigger(self, canvas, value):
        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10:
            return

        bar_w = int(value * w)
        canvas.create_rectangle(0, 0, bar_w, h, fill=PALETTE["accent"], outline="")

    def _on_close(self):
        self.running = False
        self.worker.join(timeout=0.5)
        if self.active:
            self._deactivate()
        # Write a pending debounced save before the window goes away
        if self._save_job:
            self.root.after_cancel(self._save_job)
            self._save_job = None
            self._save_gamepad_config()
        winmm.timeEndPeriod(1)
        for d in self.opened_devices:
            try:
                d.close()
            except:
                pass
        self.root.destroy()


def main():
    # The HID, gamepad and Tk threads share the GIL. A 1 ms switch interval
    # (default 5 ms) keeps a busy Tk redraw from delaying a gamepad update.
    sys.setswitchinterval(0.001)
    root = tk.Tk()
    app = GamepadApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
