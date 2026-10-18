"""
X68PRO HE - Interactive Key Mapper GUI
Maps every physical key to its analog key_id.
Saves a complete config JSON for the virtual gamepad.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import ctypes
from ctypes import wintypes
import pywinusb.hid as hid
import threading
import time
import json
import os

from device_config import load_device_ids

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "key_config.json")
VID, PID, DEVICE_NAME = load_device_ids(CONFIG_PATH)

ENABLE_CMD = [0x1B, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE3] + [0x00] * 56
DISABLE_CMD = [0x1B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE4] + [0x00] * 56

hid_dll = ctypes.WinDLL('hid.dll')
kernel32 = ctypes.WinDLL('kernel32.dll')

# X68 Pro HE layout (68 keys) - row by row, left to right
# Each entry: (key_label, width_units) where 1 unit = standard key
KEYBOARD_LAYOUT = [
    # Row 0: ESC + numbers + backspace
    [("ESC", 1), ("1", 1), ("2", 1), ("3", 1), ("4", 1), ("5", 1), ("6", 1),
     ("7", 1), ("8", 1), ("9", 1), ("0", 1), ("-", 1), ("=", 1), ("BKSP", 2), ("DEL", 1)],
    # Row 1: Tab + QWERTY + backslash
    [("TAB", 1.5), ("Q", 1), ("W", 1), ("E", 1), ("R", 1), ("T", 1), ("Y", 1),
     ("U", 1), ("I", 1), ("O", 1), ("P", 1), ("[", 1), ("]", 1), ("\\", 1.5), ("PGUP", 1)],
    # Row 2: Caps + ASDF + Enter
    [("CAPS", 1.75), ("A", 1), ("S", 1), ("D", 1), ("F", 1), ("G", 1), ("H", 1),
     ("J", 1), ("K", 1), ("L", 1), (";", 1), ("'", 1), ("ENTER", 2.25), ("PGDN", 1)],
    # Row 3: Shift + ZXCV + Shift + Up
    [("LSHIFT", 2.25), ("Z", 1), ("X", 1), ("C", 1), ("V", 1), ("B", 1), ("N", 1),
     ("M", 1), (",", 1), (".", 1), ("/", 1), ("RSHIFT", 1.75), ("UP", 1)],
    # Row 4: Ctrl + Win + Alt + Space + Alt + Fn + Ctrl + arrows
    [("LCTRL", 1.25), ("WIN", 1.25), ("LALT", 1.25), ("SPACE", 6.25),
     ("RALT", 1), ("FN", 1), ("LEFT", 1), ("DOWN", 1), ("RIGHT", 1)],
]

# Flat list of all key names in order
ALL_KEYS = []
for row in KEYBOARD_LAYOUT:
    for key_label, _ in row:
        ALL_KEYS.append(key_label)


class KeyMapperGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("X68PRO HE - Key Mapper")
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(True, True)

        self.mapping = {}  # key_label -> key_id
        self.current_key_index = -1
        self.is_mapping = False
        self.analog_enabled = False

        # HID state
        self.config_path = None
        self.opened_devices = []
        self.latest_key_id = None
        self.latest_analog = 0
        self.peak_analog = 0
        self.data_lock = threading.Lock()
        self.last_event_time = 0

        # Key button widgets
        self.key_buttons = {}

        self._build_ui()
        self._init_hid()

        # Load existing mapping if available
        self._load_existing()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_loop()

    def _build_ui(self):
        # Prevent SPACE/ENTER from activating focused GUI buttons
        self.root.bind_all('<space>', lambda e: 'break')
        self.root.bind_all('<Return>', lambda e: 'break')

        # Top bar
        top = tk.Frame(self.root, bg="#16213e")
        top.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.status_label = tk.Label(
            top, text="Initializing...", font=("Consolas", 13, "bold"),
            fg="#00ff88", bg="#16213e"
        )
        self.status_label.pack(side=tk.LEFT, padx=10, pady=8)

        self.analog_label = tk.Label(
            top, text="Analog: ---", font=("Consolas", 12),
            fg="#ffcc00", bg="#16213e"
        )
        self.analog_label.pack(side=tk.RIGHT, padx=10, pady=8)

        self.progress_label = tk.Label(
            top, text="0/68 mapped", font=("Consolas", 11),
            fg="#888", bg="#16213e"
        )
        self.progress_label.pack(side=tk.RIGHT, padx=10, pady=8)

        # Keyboard visual
        kbd_frame = tk.Frame(self.root, bg="#1a1a2e")
        kbd_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        KEY_W = 52  # pixels per unit width
        KEY_H = 48
        PAD = 3

        for row_idx, row in enumerate(KEYBOARD_LAYOUT):
            row_frame = tk.Frame(kbd_frame, bg="#1a1a2e")
            row_frame.pack(anchor=tk.W, pady=PAD)

            for key_label, width_units in row:
                w = int(KEY_W * width_units) - PAD * 2
                btn = tk.Button(
                    row_frame, text=key_label, width=0,
                    font=("Consolas", 9, "bold"),
                    bg="#2a2a4e", fg="#888", activebackground="#3a3a6e",
                    relief=tk.FLAT, bd=1, padx=2, pady=2,
                    command=lambda k=key_label: self._manual_select(k)
                )
                btn.config(height=2)
                btn.pack(side=tk.LEFT, padx=PAD, ipadx=max(0, (w - 40) // 2))
                self.key_buttons[key_label] = btn

        # Instruction + current key display
        instr_frame = tk.Frame(self.root, bg="#16213e")
        instr_frame.pack(fill=tk.X, padx=8, pady=4)

        self.instr_label = tk.Label(
            instr_frame, text="Press START to begin mapping all keys",
            font=("Consolas", 14), fg="white", bg="#16213e", height=2
        )
        self.instr_label.pack(pady=8)

        # Buttons
        btn_frame = tk.Frame(self.root, bg="#1a1a2e")
        btn_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        self.start_btn = tk.Button(
            btn_frame, text="START MAPPING", font=("Consolas", 11, "bold"),
            bg="#00aa55", fg="white", command=self._start_mapping, width=18, height=2
        )
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.skip_btn = tk.Button(
            btn_frame, text="SKIP KEY", font=("Consolas", 11, "bold"),
            bg="#aa5500", fg="white", command=self._skip_key, width=12, height=2,
            state=tk.DISABLED
        )
        self.skip_btn.pack(side=tk.LEFT, padx=5)

        self.undo_btn = tk.Button(
            btn_frame, text="UNDO", font=("Consolas", 11, "bold"),
            bg="#555577", fg="white", command=self._undo_key, width=10, height=2,
            state=tk.DISABLED
        )
        self.undo_btn.pack(side=tk.LEFT, padx=5)

        self.save_btn = tk.Button(
            btn_frame, text="SAVE CONFIG", font=("Consolas", 11, "bold"),
            bg="#2266cc", fg="white", command=self._save_config, width=14, height=2
        )
        self.save_btn.pack(side=tk.RIGHT, padx=5)

        self.freemode_btn = tk.Button(
            btn_frame, text="FREE MODE", font=("Consolas", 11, "bold"),
            bg="#663399", fg="white", command=self._toggle_freemode, width=14, height=2
        )
        self.freemode_btn.pack(side=tk.RIGHT, padx=5)

        self.free_mode = False

    def _init_hid(self):
        """Find and open HID devices."""
        devices = hid.find_all_hid_devices()
        kbd_devs = [d for d in devices if d.vendor_id == VID and d.product_id == PID]

        if not kbd_devs:
            self.status_label.config(text=f"ERRORE: {DEVICE_NAME} non trovata!", fg="#ff4444")
            return

        for d in kbd_devs:
            if 'mi_02' in d.device_path:
                self.config_path = d.device_path

        # Open all for listening
        for d in kbd_devs:
            try:
                d.open()
                d.set_raw_data_handler(self._hid_handler)
                self.opened_devices.append(d)
            except:
                pass

        n = len(self.opened_devices)
        self.status_label.config(
            text=f"Connesso ({n} interfacce)" if n > 0 else "Errore connessione",
            fg="#00ff88" if n > 0 else "#ff4444"
        )

    def _send_feature(self, cmd):
        """Send feature report to config interface."""
        if not self.config_path:
            return False
        handle = kernel32.CreateFileW(
            self.config_path, 0xC0000000, 0x03, None, 3, 0, None
        )
        if handle == ctypes.c_void_p(-1).value:
            return False
        buf = (ctypes.c_byte * 65)()
        buf[0] = 0
        for i in range(64):
            buf[i + 1] = cmd[i]
        result = hid_dll.HidD_SetFeature(handle, ctypes.byref(buf), 65)
        kernel32.CloseHandle(handle)
        return bool(result)

    def _enable_analog(self):
        if self._send_feature(ENABLE_CMD):
            self.analog_enabled = True
            return True
        return False

    def _disable_analog(self):
        if self._send_feature(DISABLE_CMD):
            self.analog_enabled = False
            return True
        return False

    def _hid_handler(self, data):
        """Handle incoming HID data."""
        if len(data) < 5:
            return
        report_id = data[0]
        if report_id != 5:
            return

        prefix = data[1]
        if prefix != 0x1B:
            return

        analog_lo = data[2]
        analog_hi = data[3]
        key_id = data[4]
        analog_value = analog_lo + analog_hi * 256

        with self.data_lock:
            self.latest_analog = analog_value
            if analog_value > 0:
                self.latest_key_id = key_id
                self.last_event_time = time.time()
                if analog_value > self.peak_analog:
                    self.peak_analog = analog_value

    def _update_loop(self):
        """Periodic UI update at ~30fps."""
        with self.data_lock:
            key_id = self.latest_key_id
            analog = self.latest_analog
            peak = self.peak_analog

        # Update analog display
        if analog > 0:
            bar_len = int(analog / 10)
            bar = '|' * min(bar_len, 40)
            self.analog_label.config(
                text=f"Key ID: {key_id}  Analog: {analog:4d} (peak:{peak})  {bar}"
            )
        else:
            self.analog_label.config(text=f"Analog: idle")

        # Auto-assign in mapping mode
        if self.is_mapping and self.current_key_index >= 0:
            now = time.time()
            # If a key was pressed (peak > threshold) and then released (analog dropped)
            if peak > 30 and analog == 0 and (now - self.last_event_time) > 0.15:
                self._assign_current_key(key_id)

        # Free mode: show detected key_id live
        if self.free_mode and key_id is not None and analog > 30:
            # Find if this key_id is already mapped
            found = [k for k, v in self.mapping.items() if v == key_id]
            if found:
                self.instr_label.config(
                    text=f"Key ID {key_id} = {found[0]}  (analog: {analog})"
                )
            else:
                self.instr_label.config(
                    text=f"Key ID {key_id} = UNMAPPED  (analog: {analog})"
                )

        # Update progress
        mapped = len(self.mapping)
        total = len(ALL_KEYS)
        self.progress_label.config(text=f"{mapped}/{total} mapped")

        self.root.after(33, self._update_loop)

    def _start_mapping(self):
        """Start sequential mapping of all keys."""
        if not self.analog_enabled:
            ok = self._enable_analog()
            if not ok:
                messagebox.showerror("Error", "Cannot enable analog mode!")
                return

        self.is_mapping = True
        self.free_mode = False
        self.current_key_index = 0
        self.start_btn.config(state=tk.DISABLED)
        self.skip_btn.config(state=tk.NORMAL)
        self.undo_btn.config(state=tk.NORMAL)

        # Skip already mapped keys
        self._advance_to_next_unmapped()
        self._highlight_current()

    def _advance_to_next_unmapped(self):
        """Skip to next key that hasn't been mapped yet."""
        while (self.current_key_index < len(ALL_KEYS) and
               ALL_KEYS[self.current_key_index] in self.mapping):
            self.current_key_index += 1

    def _highlight_current(self):
        """Highlight the current key to map."""
        # Reset all button colors
        for label, btn in self.key_buttons.items():
            if label in self.mapping:
                btn.config(bg="#1a5a2a", fg="#00ff88")  # green = mapped
            else:
                btn.config(bg="#2a2a4e", fg="#888")  # default

        if self.current_key_index >= len(ALL_KEYS):
            self._finish_mapping()
            return

        key = ALL_KEYS[self.current_key_index]
        self.key_buttons[key].config(bg="#cc4400", fg="white")  # orange = active
        self.instr_label.config(
            text=f"Premi il tasto:  {key}  (poi rilascia)"
        )
        # Reset peak for next detection
        with self.data_lock:
            self.peak_analog = 0
            self.latest_key_id = None

    def _assign_current_key(self, key_id):
        """Assign detected key_id to current key."""
        if self.current_key_index >= len(ALL_KEYS):
            return

        key_label = ALL_KEYS[self.current_key_index]

        # Check for duplicate key_id
        existing = [k for k, v in self.mapping.items() if v == key_id]
        if existing:
            self.instr_label.config(
                text=f"Key ID {key_id} gia' usato per {existing[0]}! Riprova.",
                fg="#ff4444"
            )
            with self.data_lock:
                self.peak_analog = 0
                self.latest_key_id = None
            self.root.after(1500, lambda: self.instr_label.config(fg="white"))
            return

        self.mapping[key_label] = key_id
        self.key_buttons[key_label].config(bg="#1a5a2a", fg="#00ff88")

        print(f"  Mapped: {key_label} -> key_id={key_id}", flush=True)

        # Move to next
        self.current_key_index += 1
        self._advance_to_next_unmapped()
        self._highlight_current()

    def _skip_key(self):
        """Skip current key."""
        if self.current_key_index < len(ALL_KEYS):
            key = ALL_KEYS[self.current_key_index]
            print(f"  Skipped: {key}", flush=True)
            self.current_key_index += 1
            self._advance_to_next_unmapped()
            with self.data_lock:
                self.peak_analog = 0
                self.latest_key_id = None
            self._highlight_current()

    def _undo_key(self):
        """Undo the last mapped key."""
        if not self.mapping:
            return
        # Find the last mapped key by going backwards
        for i in range(self.current_key_index - 1, -1, -1):
            key = ALL_KEYS[i]
            if key in self.mapping:
                del self.mapping[key]
                self.current_key_index = i
                print(f"  Undo: {key}", flush=True)
                with self.data_lock:
                    self.peak_analog = 0
                    self.latest_key_id = None
                self._highlight_current()
                return

    def _manual_select(self, key_label):
        """Click on a key button to manually map/remap it."""
        if not self.analog_enabled:
            return
        # Switch to mapping this specific key
        self.is_mapping = True
        self.free_mode = False
        idx = ALL_KEYS.index(key_label)
        self.current_key_index = idx
        # Remove old mapping if exists
        if key_label in self.mapping:
            del self.mapping[key_label]
        self.skip_btn.config(state=tk.NORMAL)
        self.undo_btn.config(state=tk.NORMAL)
        self._highlight_current()

    def _toggle_freemode(self):
        """Toggle free detection mode (just shows key_id as you press)."""
        if not self.analog_enabled:
            ok = self._enable_analog()
            if not ok:
                messagebox.showerror("Error", "Cannot enable analog mode!")
                return

        self.free_mode = not self.free_mode
        self.is_mapping = not self.free_mode

        if self.free_mode:
            self.freemode_btn.config(bg="#9944cc", text="EXIT FREE MODE")
            self.instr_label.config(text="FREE MODE: premi qualsiasi tasto per vedere il suo ID")
            self.start_btn.config(state=tk.NORMAL)
        else:
            self.freemode_btn.config(bg="#663399", text="FREE MODE")
            self.instr_label.config(text="Press START to continue mapping")
            self.start_btn.config(state=tk.NORMAL)

    def _finish_mapping(self):
        """All keys mapped."""
        self.is_mapping = False
        self.skip_btn.config(state=tk.DISABLED)
        self.start_btn.config(state=tk.NORMAL, text="RESTART")
        self.instr_label.config(
            text=f"COMPLETATO! {len(self.mapping)}/{len(ALL_KEYS)} tasti mappati. Premi SAVE."
        )

    def _save_config(self):
        """Save the mapping to JSON config file."""
        config = {
            "device": {
                "name": DEVICE_NAME,
                "vid": f"0x{VID:04X}",
                "pid": f"0x{PID:04X}",
                "vid_int": VID,
                "pid_int": PID,
            },
            "protocol": {
                "enable_cmd": ENABLE_CMD,
                "disable_cmd": DISABLE_CMD,
                "report_id": 5,
                "prefix": 0x1B,
                "analog_byte_lo": 2,
                "analog_byte_hi": 3,
                "key_id_byte": 4,
                "analog_max": 350,
                "note": "pywinusb byte indices (byte[0]=report_id)"
            },
            "key_mapping": self.mapping,
            "reverse_mapping": {v: k for k, v in self.mapping.items()},
            "unmapped_keys": [k for k in ALL_KEYS if k not in self.mapping],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        path = os.path.join(os.path.dirname(__file__), "key_config.json")
        with open(path, 'w') as f:
            json.dump(config, f, indent=2)

        mapped = len(self.mapping)
        self.instr_label.config(
            text=f"Salvato in key_config.json ({mapped} tasti)"
        )
        messagebox.showinfo("Saved", f"Config saved to:\n{path}\n\n{mapped} keys mapped.")
        print(f"\nConfig saved: {path}", flush=True)
        print(f"Mapped {mapped}/{len(ALL_KEYS)} keys:", flush=True)
        for k, v in sorted(self.mapping.items(), key=lambda x: x[1]):
            print(f"  {k:10s} -> key_id {v}", flush=True)

    def _load_existing(self):
        """Load existing mapping if available."""
        path = os.path.join(os.path.dirname(__file__), "key_config.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    config = json.load(f)
                self.mapping = config.get("key_mapping", {})
                # Convert key_ids to int (JSON may have stored as string)
                self.mapping = {k: int(v) for k, v in self.mapping.items()}
                # Update button colors
                for label in self.mapping:
                    if label in self.key_buttons:
                        self.key_buttons[label].config(bg="#1a5a2a", fg="#00ff88")
                self.instr_label.config(
                    text=f"Caricata mappatura esistente ({len(self.mapping)} tasti). "
                         f"START per continuare o clicca un tasto per rimapparlo."
                )
                print(f"Loaded existing mapping: {len(self.mapping)} keys", flush=True)
            except Exception as e:
                print(f"Could not load existing config: {e}", flush=True)

    def _on_close(self):
        """Cleanup on window close."""
        if self.analog_enabled:
            self._disable_analog()
        for d in self.opened_devices:
            try:
                d.close()
            except:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    # Center window
    root.update_idletasks()
    app = KeyMapperGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
