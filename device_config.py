"""
Device identification shared by the key mapper and the virtual gamepad.
Reads VID/PID and protocol values from key_config.json so a config exported by
the capture page (tools/capture/) for another model works without code changes.
"""

import glob
import json
import os

DEFAULT_VID = 0x3151
DEFAULT_PID = 0x5030
DEFAULT_NAME = "X68PRO HE"

DEFAULT_PROTOCOL = {
    "enable_cmd": [0x1B, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE3] + [0x00] * 56,
    "disable_cmd": [0x1B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE4] + [0x00] * 56,
    "report_id": 5,
    "prefix": 0x1B,
    "analog_byte_lo": 2,
    "analog_byte_hi": 3,
    "key_id_byte": 4,
    "analog_max": 350,
}

# Vendor config channel: usage page 0xFFFF, usage 0x0002 (feature report).
CONFIG_USAGE_PAGE = 0xFFFF
CONFIG_USAGE = 0x0002


def _read_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_device_ids(path):
    """Return (vid, pid, name) from the "device" section of key_config.json.

    Falls back to the X68PRO HE values when the file or a field is missing.
    """
    device = _read_json(path).get("device")
    if not isinstance(device, dict):
        return DEFAULT_VID, DEFAULT_PID, DEFAULT_NAME
    try:
        vid = int(device.get("vid_int", DEFAULT_VID))
        pid = int(device.get("pid_int", DEFAULT_PID))
    except (ValueError, TypeError):
        return DEFAULT_VID, DEFAULT_PID, DEFAULT_NAME
    return vid, pid, device.get("name") or DEFAULT_NAME


def load_protocol(path):
    """Return the "protocol" section merged over the X68PRO HE defaults."""
    protocol = dict(DEFAULT_PROTOCOL)
    section = _read_json(path).get("protocol")
    if isinstance(section, dict):
        for key, default in DEFAULT_PROTOCOL.items():
            value = section.get(key)
            if isinstance(default, list):
                if isinstance(value, list) and len(value) == 64:
                    protocol[key] = [int(b) & 0xFF for b in value]
            elif isinstance(value, (int, float)) and value > 0:
                protocol[key] = int(value)
    return protocol


def resolve_config_path(base_dir, connected_ids):
    """Pick the config for the keyboard that is plugged in.

    Checks key_config.json first, then devices/*.json. connected_ids is a set
    of (vid, pid) tuples. Returns key_config.json when nothing matches.
    """
    default = os.path.join(base_dir, "key_config.json")
    candidates = [default] + sorted(glob.glob(os.path.join(base_dir, "devices", "*.json")))
    for path in candidates:
        if os.path.exists(path) and load_device_ids(path)[:2] in connected_ids:
            return path
    return default


def find_config_interface(opened_devices):
    """Return the device path of the vendor config channel, or None.

    Matches the HID usage first. Falls back to the mi_02 interface used by
    the X68PRO HE when the capabilities are not available.
    """
    for d in opened_devices:
        caps = getattr(d, "hid_caps", None)
        if caps and caps.usage_page == CONFIG_USAGE_PAGE and caps.usage == CONFIG_USAGE:
            return d.device_path
    for d in opened_devices:
        if "mi_02" in d.device_path.lower():
            return d.device_path
    return None
