"""
Device identification shared by the key mapper and the virtual gamepad.
Reads VID/PID from key_config.json so a config exported by the capture page
(tools/capture/) for another model works without code changes.
"""

import json
import os

DEFAULT_VID = 0x3151
DEFAULT_PID = 0x5030
DEFAULT_NAME = "X68PRO HE"


def load_device_ids(path):
    """Return (vid, pid, name) from the "device" section of key_config.json.

    Falls back to the X68PRO HE values when the file or a field is missing.
    """
    vid, pid, name = DEFAULT_VID, DEFAULT_PID, DEFAULT_NAME
    if not os.path.exists(path):
        return vid, pid, name
    try:
        with open(path) as f:
            device = json.load(f).get("device") or {}
        vid = int(device.get("vid_int", vid))
        pid = int(device.get("pid_int", pid))
        name = device.get("name") or name
    except (OSError, ValueError, TypeError, AttributeError):
        return DEFAULT_VID, DEFAULT_PID, DEFAULT_NAME
    return vid, pid, name
