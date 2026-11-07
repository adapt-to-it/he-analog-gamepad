"""
Headless smoke test of the virtual_gamepad GUI.

Runs on any OS with tkinter: HID, ViGEm and the Windows DLLs are stubbed.
A fake X98 HE is "connected", so the app must load devices/x98he_5029.json.

    python tests/gui_smoke.py   (any Python with tkinter, e.g. python3.14 on macOS)
"""

import ctypes
import json
import os
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Stubs ──
ctypes.WinDLL = lambda name: types.SimpleNamespace(
    timeBeginPeriod=lambda x: 0, timeEndPeriod=lambda x: 0)


class FakeDevice:
    vendor_id, product_id = 0x3151, 0x5029
    device_path = r"\\?\hid#vid_3151&pid_5029&mi_02"
    hid_caps = types.SimpleNamespace(usage_page=0xFFFF, usage=0x0002)

    def open(self): pass
    def close(self): pass
    def set_raw_data_handler(self, h): pass


hid = types.ModuleType("pywinusb.hid")
hid.find_all_hid_devices = lambda: [FakeDevice()]
pywinusb = types.ModuleType("pywinusb")
pywinusb.hid = hid
sys.modules.update({"pywinusb": pywinusb, "pywinusb.hid": hid})


class _Buttons:
    def __getattr__(self, name): return name


vg = types.ModuleType("vgamepad")
vg.XUSB_BUTTON = _Buttons()
vg.VX360Gamepad = lambda: types.SimpleNamespace(**{n: (lambda *a, **k: None) for n in (
    "left_joystick_float", "right_joystick_float", "left_trigger_float",
    "right_trigger_float", "press_button", "release_button", "update", "reset")})
sys.modules["vgamepad"] = vg

import tkinter as tk  # noqa: E402
import virtual_gamepad as V  # noqa: E402

V.GAMEPAD_CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "gamepad_config.json")

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def pump(seconds=0.0):
    end = time.time() + seconds
    while True:
        root.update()
        if time.time() >= end:
            break
        time.sleep(0.02)


root = tk.Tk()
app = V.GamepadApp(root)
pump(0.1)

# Detected model
check(V.DEVICE_NAME == "X98 HE", f"config of the connected keyboard loaded ({V.DEVICE_NAME})")
check("X98 HE" in root.title(), f"window title shows the model: {root.title()!r}")
check("X98 HE" in app.device_label.cget("text"), "device label shows the model")
check("X68PRO" not in root.title(), "no hardcoded X68PRO in the title")

# Compact window
check(root.winfo_reqwidth() <= 780 and root.winfo_reqheight() <= 520,
      f"window fits 780x520 (req {root.winfo_reqwidth()}x{root.winfo_reqheight()})")

# Tabs
tabs = [app.tabs.tab(t, "text") for t in app.tabs.tabs()]
check(tabs == ["Tuning", "Bindings"], f"tabs are Tuning, Bindings ({tabs})")

ORDER = ["deadzone", "smoothing", "sensitivity_curve", "button_threshold",
         "trigger_threshold", "analog_max_override"]


def visible(widget):
    return bool(widget.winfo_ismapped())


def check_mode(mode):
    app._set_mode(mode)
    app.tabs.select(0)
    pump(0.05)
    full = mode == V.MODE_FULL
    for key in ("button_threshold", "trigger_threshold"):
        check(visible(app.sliders[key]) == full, f"[{mode}] slider {key} visible={full}")
    shown = [k for k in ORDER if visible(app.sliders[k])]
    ys = [app.sliders[k].winfo_rooty() for k in shown]
    check(ys == sorted(ys), f"[{mode}] sliders keep their order {shown}")
    check(all(app.sliders[k].winfo_rooty() + app.sliders[k].winfo_height()
              <= root.winfo_rooty() + root.winfo_height() for k in shown),
          f"[{mode}] no slider cut off at the bottom")
    app.tabs.select(1)
    pump(0.05)
    for action in V.DEFAULT_BINDINGS:
        expected = full or action.startswith("left_stick_")
        widget = app.bind_widgets[action]
        check(visible(widget) == expected, f"[{mode}] binding {action} visible={expected}")
    check(visible(app.right_canvas) == full, f"[{mode}] right stick visible={full}")


check(set(app.bind_vars) == set(V.DEFAULT_BINDINGS), "a binding control for every action")
for m in (V.MODE_HYBRID, V.MODE_FULL, V.MODE_HYBRID, V.MODE_FULL):
    check_mode(m)

# Autosave
app._on_slider("deadzone", "0.2")
app.bind_vars["btn_a"].set("G")
app._on_binding_change("btn_a", app.bind_vars["btn_a"])
pump(1.0)
saved = json.load(open(V.GAMEPAD_CONFIG_PATH)) if os.path.exists(V.GAMEPAD_CONFIG_PATH) else {}
check(abs(saved.get("settings", {}).get("deadzone", 0) - 0.2) < 1e-6, "slider change is saved automatically")
check(saved.get("bindings", {}).get("btn_a") == "G", "binding change is saved automatically")
check(saved.get("settings", {}).get("mode") == V.MODE_FULL, "mode is saved")

# Reset
app.reset_btn.invoke()
pump(1.0)
check(abs(app.settings["deadzone"] - V.DEFAULT_SETTINGS["deadzone"]) < 1e-6, "reset restores settings")
check(app.bindings == V.DEFAULT_BINDINGS and app.bind_vars["btn_a"].get() == "SPACE",
      "reset restores bindings and the controls")
check(abs(float(app.sliders["deadzone"].get()) - V.DEFAULT_SETTINGS["deadzone"]) < 1e-6,
      "reset moves the slider")

# UI loop survives live values in both modes
app.lx_display, app.ly_display, app.lt_display = 0.5, -0.5, 0.7
pump(0.2)

app._on_close()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
