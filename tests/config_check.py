"""
Checks that every connected model loads its own config.

    python tests/config_check.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from device_config import resolve_config_path  # noqa: E402

V = 0x3151
CASES = [
    ({(V, 0x5030, "X68PRO HE")}, "key_config.json"),
    ({(V, 0x502D, "X68HE")}, "x68he_502d.json"),
    # Same VID/PID: the USB product name picks the model
    ({(V, 0x5029, "Gaming Keyboard")}, "x98he_5029.json"),
    ({(V, 0x5029, "R68HE")}, "r68he_5029.json"),
    ({(V, 0x5029)}, "r68he_5029.json"),  # no product name: first 0x5029 config
    (set(), "key_config.json"),
]

failures = 0
for connected, expected in CASES:
    got = os.path.basename(resolve_config_path(ROOT, connected))
    ok = got == expected
    failures += not ok
    print(("ok   " if ok else "FAIL ") + f"{sorted(connected)} -> {got} (expected {expected})")
print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
