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
import threading
import time
import json
import os
import math

from device_config import load_device_ids

# ── Config ──────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "key_config.json")
GAMEPAD_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "gamepad_config.json")

VID, PID, DEVICE_NAME = load_device_ids(CONFIG_PATH)
ENABLE_CMD = [0x1B, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE3] + [0x00] * 56
DISABLE_CMD = [0x1B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE4] + [0x00] * 56

hid_dll = ctypes.WinDLL('hid.dll')
kernel32 = ctypes.WinDLL('kernel32.dll')

ANALOG_MAX = 350.0  # max raw value from keyboard

# Modes
MODE_HYBRID = "hybrid"           # Only left stick, KB+mouse pass through
MODE_FULL = "full_controller"    # Everything mapped to Xbox controller

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
    "analog_max_override": 350,    # override max analog value
}


class KeyboardState:
    """Tracks analog values for all keys."""
    def __init__(self, key_mapping):
        self.key_mapping = key_mapping  # key_label -> key_id
        self.id_to_key = {v: k for k, v in key_mapping.items()}
        self.values = {}  # key_label -> raw analog (0-350)
        self.lock = threading.Lock()

    def update(self, key_id, analog_value):
        key_label = self.id_to_key.get(key_id)
        if key_label:
            with self.lock:
                self.values[key_label] = analog_value

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

    def update(self, target, smoothing):
        if smoothing <= 0:
            self.value = target
        else:
            self.value += (target - self.value) * (1.0 - smoothing)
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

    def update(self, kb_state, bindings, settings):
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

        lx_val = self.lx.update(raw_lx, smoothing)
        ly_val = self.ly.update(raw_ly, smoothing)

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

            rx_val = self.rx.update(raw_rx, smoothing)
            ry_val = self.ry.update(raw_ry, smoothing)
            self.pad.right_joystick_float(x_value_float=rx_val, y_value_float=ry_val)

            # ── Triggers (analog) ──
            lt_raw = kb_state.get_normalized(bindings.get("left_trigger", ""), settings)
            rt_raw = kb_state.get_normalized(bindings.get("right_trigger", ""), settings)
            lt_val = self.lt.update(lt_raw, smoothing)
            rt_val = self.rt.update(rt_raw, smoothing)
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

            if dpad_up and dpad_right:
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP)
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT)
            elif dpad_up and dpad_left:
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP)
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT)
            elif dpad_down and dpad_right:
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN)
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT)
            elif dpad_down and dpad_left:
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN)
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT)
            elif dpad_up:
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP)
            elif dpad_down:
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN)
            elif dpad_left:
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT)
            elif dpad_right:
                self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT)
            else:
                for dp in [vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
                           vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT, vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT]:
                    self.pad.release_button(button=dp)

        self.pad.update()
        return lx_val, ly_val, rx_val, ry_val, lt_val, rt_val


class GamepadApp:
    def __init__(self, root):
        self.root = root
        self.root.title("X68PRO HE → Xbox 360 Gamepad")
        self.root.geometry("820x680")
        self.root.configure(bg="#1a1a2e")
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

        self._build_ui()
        self._init_hid()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._gamepad_loop()
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
        else:
            bindings = dict(DEFAULT_BINDINGS)
            settings = dict(DEFAULT_SETTINGS)
        return bindings, settings

    def _save_gamepad_config(self):
        # Sync mode from UI
        self.settings["mode"] = self.mode_var.get()
        cfg = {"bindings": self.bindings, "settings": self.settings}
        with open(GAMEPAD_CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)

    def _build_ui(self):
        # Prevent keyboard from triggering GUI
        self.root.bind_all('<space>', lambda e: 'break')
        self.root.bind_all('<Return>', lambda e: 'break')

        # ── Top bar ──
        top = tk.Frame(self.root, bg="#16213e")
        top.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.status_label = tk.Label(
            top, text="DISCONNECTED", font=("Consolas", 13, "bold"),
            fg="#ff4444", bg="#16213e"
        )
        self.status_label.pack(side=tk.LEFT, padx=10, pady=8)

        self.toggle_btn = tk.Button(
            top, text="ACTIVATE GAMEPAD", font=("Consolas", 11, "bold"),
            bg="#00aa55", fg="white", command=self._toggle_active, width=20
        )
        self.toggle_btn.pack(side=tk.RIGHT, padx=10, pady=8)

        # Mode selector
        mode_frame = tk.Frame(top, bg="#16213e")
        mode_frame.pack(side=tk.RIGHT, padx=10, pady=8)

        tk.Label(mode_frame, text="Mode:", font=("Consolas", 10, "bold"),
                 fg="#ccc", bg="#16213e").pack(side=tk.LEFT, padx=(0, 5))

        self.mode_var = tk.StringVar(value=self.settings.get("mode", MODE_HYBRID))
        self.mode_combo = ttk.Combobox(
            mode_frame, textvariable=self.mode_var,
            values=[MODE_HYBRID, MODE_FULL],
            width=16, font=("Consolas", 10), state="readonly"
        )
        self.mode_combo.pack(side=tk.LEFT)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

        # Mode description
        self.mode_desc = tk.Label(
            self.root, text="", font=("Consolas", 9),
            fg="#888", bg="#1a1a2e", anchor=tk.W
        )
        self.mode_desc.pack(fill=tk.X, padx=16, pady=(0, 2))

        # ── Main area ──
        main = tk.Frame(self.root, bg="#1a1a2e")
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Left: stick visualization
        self.viz_frame = tk.LabelFrame(
            main, text=" CONTROLLER ", font=("Consolas", 10, "bold"),
            fg="#00ccff", bg="#16213e"
        )
        self.viz_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        # Stick canvases side by side
        self.sticks_frame = tk.Frame(self.viz_frame, bg="#16213e")
        self.sticks_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left stick
        ls_frame = tk.Frame(self.sticks_frame, bg="#16213e")
        ls_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(ls_frame, text="LEFT STICK (WASD)", font=("Consolas", 9, "bold"),
                 fg="#888", bg="#16213e").pack()
        self.left_canvas = tk.Canvas(ls_frame, bg="#0a0a1a", width=180, height=180,
                                     highlightthickness=0)
        self.left_canvas.pack(padx=5, pady=5)
        self.ls_label = tk.Label(ls_frame, text="X: 0.00  Y: 0.00",
                                 font=("Consolas", 9), fg="#00ff88", bg="#16213e")
        self.ls_label.pack()

        # Right stick (container for show/hide)
        self.rs_frame = tk.Frame(self.sticks_frame, bg="#16213e")
        self.rs_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(self.rs_frame, text="RIGHT STICK", font=("Consolas", 9, "bold"),
                 fg="#888", bg="#16213e").pack()
        self.right_canvas = tk.Canvas(self.rs_frame, bg="#0a0a1a", width=180, height=180,
                                      highlightthickness=0)
        self.right_canvas.pack(padx=5, pady=5)
        self.rs_label = tk.Label(self.rs_frame, text="X: 0.00  Y: 0.00",
                                 font=("Consolas", 9), fg="#00ff88", bg="#16213e")
        self.rs_label.pack()

        # Triggers (container for show/hide)
        self.trig_frame = tk.Frame(self.viz_frame, bg="#16213e")
        self.trig_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(self.trig_frame, text="LT", font=("Consolas", 9, "bold"),
                 fg="#888", bg="#16213e").pack(side=tk.LEFT)
        self.lt_bar = tk.Canvas(self.trig_frame, bg="#0a0a1a", height=20, highlightthickness=0)
        self.lt_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.rt_bar = tk.Canvas(self.trig_frame, bg="#0a0a1a", height=20, highlightthickness=0)
        self.rt_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Label(self.trig_frame, text="RT", font=("Consolas", 9, "bold"),
                 fg="#888", bg="#16213e").pack(side=tk.LEFT)

        # Buttons status (container for show/hide)
        self.btn_label = tk.Label(
            self.viz_frame, text="Buttons: ---", font=("Consolas", 10),
            fg="#ffcc00", bg="#16213e", anchor=tk.W
        )
        self.btn_label.pack(fill=tk.X, padx=10, pady=5)

        # Raw WASD values
        self.raw_label = tk.Label(
            self.viz_frame, text="Raw WASD: ---", font=("Consolas", 9),
            fg="#666", bg="#16213e", anchor=tk.W
        )
        self.raw_label.pack(fill=tk.X, padx=10, pady=(0, 5))

        # ── Right: settings ──
        self.settings_frame = tk.LabelFrame(
            main, text=" SETTINGS ", font=("Consolas", 10, "bold"),
            fg="#00ccff", bg="#16213e", width=280
        )
        self.settings_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0))
        self.settings_frame.pack_propagate(False)

        self.sliders = {}
        self.slider_frames = {}
        slider_defs = [
            ("deadzone", "Deadzone", 0, 0.5, self.settings["deadzone"], True),
            ("smoothing", "Smoothing", 0, 0.95, self.settings["smoothing"], True),
            ("sensitivity_curve", "Sensitivity", 0.2, 3.0, self.settings["sensitivity_curve"], True),
            ("button_threshold", "Btn Threshold", 0.01, 0.5, self.settings["button_threshold"], False),
            ("trigger_threshold", "Trig Threshold", 0.01, 0.5, self.settings["trigger_threshold"], False),
            ("analog_max_override", "Analog Max", 100, 500, self.settings["analog_max_override"], True),
        ]

        for key, label, min_v, max_v, default, show_hybrid in slider_defs:
            f = tk.Frame(self.settings_frame, bg="#16213e")
            f.pack(fill=tk.X, padx=8, pady=4)

            val_label = tk.Label(f, text=f"{label}: {default:.2f}",
                                 font=("Consolas", 9), fg="#ccc", bg="#16213e", width=22, anchor=tk.W)
            val_label.pack()

            slider = ttk.Scale(f, from_=min_v, to=max_v, value=default, orient=tk.HORIZONTAL,
                              command=lambda v, k=key, l=val_label, lb=label: self._on_slider(k, v, l, lb))
            slider.pack(fill=tk.X)
            self.sliders[key] = slider
            self.slider_frames[key] = (f, show_hybrid)

        # Bindings section
        self.bindings_label = tk.Label(self.settings_frame, text="KEY BINDINGS",
                                        font=("Consolas", 9, "bold"),
                                        fg="#ffcc00", bg="#16213e")
        self.bindings_label.pack(pady=(10, 2))

        self.bind_container = tk.Frame(self.settings_frame, bg="#16213e")
        self.bind_container.pack(fill=tk.BOTH, expand=True)

        bind_canvas = tk.Canvas(self.bind_container, bg="#16213e", highlightthickness=0)
        bind_scroll = ttk.Scrollbar(self.bind_container, orient=tk.VERTICAL, command=bind_canvas.yview)
        bind_inner = tk.Frame(bind_canvas, bg="#16213e")

        bind_inner.bind("<Configure>", lambda e: bind_canvas.configure(scrollregion=bind_canvas.bbox("all")))
        bind_canvas.create_window((0, 0), window=bind_inner, anchor=tk.NW)
        bind_canvas.configure(yscrollcommand=bind_scroll.set)

        bind_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        bind_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.bind_vars = {}
        self.bind_rows = {}
        all_keys = sorted(self.key_mapping.keys())

        HYBRID_BINDINGS = {"left_stick_up", "left_stick_down", "left_stick_left", "left_stick_right"}

        for action in sorted(self.bindings.keys()):
            f = tk.Frame(bind_inner, bg="#16213e")
            f.pack(fill=tk.X, pady=1)

            short = action.replace("left_stick_", "LS_").replace("right_stick_", "RS_")
            short = short.replace("btn_", "").replace("thumb_", "Th")

            tk.Label(f, text=f"{short}:", font=("Consolas", 8),
                     fg="#aaa", bg="#16213e", width=12, anchor=tk.E).pack(side=tk.LEFT)

            var = tk.StringVar(value=self.bindings[action])
            combo = ttk.Combobox(f, textvariable=var, values=all_keys,
                                width=8, font=("Consolas", 8), state="readonly")
            combo.pack(side=tk.LEFT, padx=2)
            combo.bind("<<ComboboxSelected>>",
                       lambda e, a=action, v=var: self._on_binding_change(a, v))
            self.bind_vars[action] = var
            self.bind_rows[action] = (f, action in HYBRID_BINDINGS)

        # Save button
        tk.Button(self.settings_frame, text="SAVE CONFIG", font=("Consolas", 10, "bold"),
                  bg="#2266cc", fg="white", command=self._save_gamepad_config
                  ).pack(fill=tk.X, padx=8, pady=8)

        # Apply initial mode UI
        self._update_mode_ui()

    def _on_mode_change(self, event=None):
        mode = self.mode_var.get()
        self.settings["mode"] = mode
        self._update_mode_ui()

    def _update_mode_ui(self):
        mode = self.settings.get("mode", MODE_HYBRID)
        is_hybrid = (mode == MODE_HYBRID)

        # Mode description
        if is_hybrid:
            self.mode_desc.config(
                text="HYBRID: Left stick only. Keyboard + mouse pass through to game.",
                fg="#00ff88"
            )
        else:
            self.mode_desc.config(
                text="FULL: All inputs mapped to Xbox controller.",
                fg="#ffcc00"
            )

        # Show/hide right stick, triggers, buttons
        if is_hybrid:
            self.rs_frame.pack_forget()
            self.trig_frame.pack_forget()
            self.btn_label.pack_forget()
        else:
            self.rs_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                               in_=self.sticks_frame)
            self.trig_frame.pack(fill=tk.X, padx=10, pady=5,
                                 in_=self.viz_frame, before=self.btn_label)
            self.btn_label.pack(fill=tk.X, padx=10, pady=5, in_=self.viz_frame,
                                before=self.raw_label)

        # Show/hide slider frames (button/trigger thresholds only in full mode)
        for key, (frame, show_in_hybrid) in self.slider_frames.items():
            if is_hybrid and not show_in_hybrid:
                frame.pack_forget()
            else:
                frame.pack(fill=tk.X, padx=8, pady=4, in_=self.settings_frame)

        # Show/hide binding rows
        for action, (frame, show_in_hybrid) in self.bind_rows.items():
            if is_hybrid and not show_in_hybrid:
                frame.pack_forget()
            else:
                frame.pack(fill=tk.X, pady=1)

    def _on_slider(self, key, value, label_widget, label_text):
        v = float(value)
        self.settings[key] = v
        label_widget.config(text=f"{label_text}: {v:.2f}")

    def _on_binding_change(self, action, var):
        self.bindings[action] = var.get()

    def _init_hid(self):
        devices = hid.find_all_hid_devices()
        kbd_devs = [d for d in devices if d.vendor_id == VID and d.product_id == PID]

        for d in kbd_devs:
            if 'mi_02' in d.device_path:
                self.config_path = d.device_path

        for d in kbd_devs:
            try:
                d.open()
                d.set_raw_data_handler(self._hid_handler)
                self.opened_devices.append(d)
            except:
                pass

        if self.opened_devices:
            self.status_label.config(text=f"HID OK ({len(self.opened_devices)} ifaces)", fg="#ffcc00")
        else:
            self.status_label.config(text="HID ERROR", fg="#ff4444")

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
        if len(data) < 5 or data[0] != 5 or data[1] != 0x1B:
            return
        analog = data[2] + data[3] * 256
        key_id = data[4]
        self.kb_state.update(key_id, analog)

    def _toggle_active(self):
        if self.active:
            self._deactivate()
        else:
            self._activate()

    def _activate(self):
        # Enable analog mode
        if not self._send_feature(ENABLE_CMD):
            self.status_label.config(text="ENABLE FAILED", fg="#ff4444")
            return

        # Create gamepad
        try:
            self.gamepad = VirtualGamepad()
        except Exception as e:
            self.status_label.config(text=f"ViGEm ERROR: {e}", fg="#ff4444")
            return

        self.active = True
        self.status_label.config(text="GAMEPAD ACTIVE", fg="#00ff88")
        self.toggle_btn.config(text="DEACTIVATE", bg="#cc2222")

    def _deactivate(self):
        self.active = False
        self._send_feature(DISABLE_CMD)

        if self.gamepad:
            # Reset controller state
            self.gamepad.pad.reset()
            self.gamepad.pad.update()
            del self.gamepad.pad
            self.gamepad = None

        self.status_label.config(text="GAMEPAD OFF", fg="#ffcc00")
        self.toggle_btn.config(text="ACTIVATE GAMEPAD", bg="#00aa55")

    def _gamepad_loop(self):
        """Update gamepad at ~120Hz."""
        if self.active and self.gamepad:
            vals = self.gamepad.update(self.kb_state, self.bindings, self.settings)
            self.lx_display, self.ly_display = vals[0], vals[1]
            self.rx_display, self.ry_display = vals[2], vals[3]
            self.lt_display, self.rt_display = vals[4], vals[5]

        self.root.after(8, self._gamepad_loop)  # ~120Hz

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
        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10:
            return

        cx, cy = w / 2, h / 2
        r = min(cx, cy) - 10

        # Outer circle
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                          outline="#333355", width=2)

        # Cross
        canvas.create_line(cx - r, cy, cx + r, cy, fill="#222244")
        canvas.create_line(cx, cy - r, cx, cy + r, fill="#222244")

        # Deadzone circle
        dz = self.settings.get("deadzone", 0.05)
        dz_r = r * dz
        canvas.create_oval(cx - dz_r, cy - dz_r, cx + dz_r, cy + dz_r,
                          outline="#442222", width=1, dash=(2, 2))

        # Dot position
        dx = cx + x * r
        dy = cy - y * r  # Y inverted
        dot_r = 8

        # Trail (magnitude indicator)
        mag = math.sqrt(x ** 2 + y ** 2)
        if mag > 0.01:
            intensity = min(255, int(mag * 255))
            color = f'#{intensity:02X}{max(0, 255 - intensity):02X}00'
        else:
            color = '#00ff88'

        canvas.create_oval(dx - dot_r, dy - dot_r, dx + dot_r, dy + dot_r,
                          fill=color, outline="white", width=2)

    def _draw_trigger(self, canvas, value):
        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 10:
            return

        bar_w = int(value * w)
        intensity = min(255, int(value * 255))
        color = f'#{intensity:02X}{max(0, 200 - intensity):02X}00'
        canvas.create_rectangle(0, 0, bar_w, h, fill=color)

    def _on_close(self):
        self.running = False
        if self.active:
            self._deactivate()
        for d in self.opened_devices:
            try:
                d.close()
            except:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = GamepadApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
