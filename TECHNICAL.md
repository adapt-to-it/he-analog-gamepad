# Attack Shark X68PRO HE -- USB HID Analog Protocol Technical Reference

This document describes the reverse-engineered USB HID protocol used by the
Attack Shark X68PRO HE Hall Effect keyboard to stream per-key analog switch
travel data to the host PC. All information was obtained through independent
analysis of the device's HID descriptors, the official web-based driver, and
runtime traffic captures.

---

## 1. Device Identification

| Field           | Value                                      |
|-----------------|--------------------------------------------|
| Vendor ID (VID) | `0x3151` (Sonix Technology Co., Ltd.)      |
| Product ID (PID)| `0x5030`                                   |
| Product String  | `X68PRO HE`                                |
| Layout          | 65% (67 physical keys)                     |
| Switch Type     | Hall Effect (magnetic analog)              |
| Switch Travel   | 0.1 mm -- 3.4 mm                           |

---

## 2. HID Interface Topology

The keyboard exposes **4 HID collections** spread across **2 USB interfaces**.
A fifth collection (the standard Keyboard HID on Usage Page 0x07) exists on a
separate interface but is claimed by the Windows HID keyboard driver and is not
directly enumerable by user-mode applications.

| # | USB Interface | Collection | Usage Page | Usage    | Input Report         | Purpose                                              |
|---|---------------|------------|------------|----------|----------------------|------------------------------------------------------|
| 0 | `mi_01`, col01 | Consumer Control | `0x000C` | `0x0001` | 3 bytes, RID = 3  | Media keys (volume, play/pause, etc.) -- 1-bit button fields |
| 1 | `mi_01`, col02 | Generic Desktop  | `0x0001` | `0x0080` | 3 bytes, RID = 2  | System controls (power, sleep, wake) -- 1-bit button fields  |
| 2 | `mi_01`, col05 | Vendor Specific  | `0xFFFF` | `0x0001` | 32 bytes, RID = 5 | **Analog key data** -- 31 x 8-bit values, range 0--255       |
| 3 | `mi_02`        | Vendor Specific  | `0xFFFF` | `0x0002` | None               | **Config channel** -- 65-byte Feature Report, RID = 0        |

**Note:** The standard Keyboard HID interface (Usage Page `0x07`) is handled by
the Windows input stack directly. It cannot be opened by `CreateFileW` with
read access while Windows holds the exclusive lock.

---

## 3. Analog Mode Activation Protocol

The keyboard does **not** send analog data by default. It operates as a normal
HID keyboard until the host explicitly enables analog streaming by writing a
HID Feature Report to the config channel on interface `mi_02`.

### 3.1 Enable Analog Mode

```
Feature Report ID : 0
Direction         : Host -> Device  (HidD_SetFeature / sendFeatureReport)
Total Length      : 64 bytes (+1 byte Report ID prefix on Windows API)

Byte layout:
  [0]    = 0x1B    command prefix (constant)
  [1]    = 0x01    enable flag
  [2-6]  = 0x00
  [7]    = 0xE3    checksum
  [8-63] = 0x00
```

### 3.2 Disable Analog Mode

```
Feature Report ID : 0
Direction         : Host -> Device
Total Length      : 64 bytes (+1 byte Report ID prefix on Windows API)

Byte layout:
  [0]    = 0x1B    command prefix (constant)
  [1]    = 0x00    disable flag
  [2-6]  = 0x00
  [7]    = 0xE4    checksum
  [8-63] = 0x00
```

### 3.3 Checksum Formula

```
byte[7] = 0xE4 - byte[1]
```

When enabling (byte[1] = 0x01): checksum = 0xE4 - 0x01 = **0xE3**.
When disabling (byte[1] = 0x00): checksum = 0xE4 - 0x00 = **0xE4**.

---

## 4. Analog Data Format (Input Reports)

Once analog mode is active, the keyboard sends an Input Report on collection
`col05` (Report ID 5) every time a key's analog value changes. Reports are
**event-driven**: no data is sent for keys that are not moving. Each report
carries data for exactly **one key**.

### 4.1 WebHID Format (31 data bytes, Report ID delivered separately)

```
Byte[0]    = 0x1B         prefix (constant)
Byte[1]    = analog_lo    low byte of the 16-bit analog value (0-255)
Byte[2]    = analog_hi    high byte of the 16-bit analog value (0 or 1)
Byte[3]    = key_id       unique physical key identifier
Byte[4-30] = 0x00         unused / padding
```

### 4.2 pywinusb Format (32 bytes, byte[0] = Report ID)

```
Byte[0]    = 0x05         Report ID
Byte[1]    = 0x1B         prefix (constant)
Byte[2]    = analog_lo
Byte[3]    = analog_hi
Byte[4]    = key_id
Byte[5-31] = 0x00         unused / padding
```

### 4.3 Analog Value Interpretation

- **Encoding:** 16-bit unsigned integer, little-endian.
  ```
  value = analog_lo + (analog_hi * 256)
  ```
- **Range:** 0 (fully released) to approximately **350** (fully depressed at 3.4 mm).
- **Resolution:** ~350 discrete steps across 3.4 mm of travel.
- **Delivery:** One report per key per value change. Multiple keys pressed
  simultaneously generate separate reports in rapid succession; the report rate
  is high enough for real-time multi-key tracking.

---

## 5. Key ID Mapping

Each physical key is assigned a unique `key_id` value (the byte at offset 3 in
WebHID format, or offset 4 in pywinusb format). The IDs follow the keyboard's
internal switch matrix layout rather than standard HID Usage codes.

### 5.1 Complete Key Map (67 Keys)

#### Row 0 -- Top Row (Function / Number)

| Key   | ESC | 1  | 2  | 3  | 4  | 5  | 6  | 7  | 8  | 9  | 0  | -  | =  | BKSP | DEL |
|-------|-----|----|----|----|----|----|----|----|----|----|----|----|----|----- |-----|
| ID    |  1  |  7 | 13 | 19 | 25 | 31 | 37 | 43 | 49 | 55 | 61 | 67 | 73 |  79  |  85 |

#### Row 1

| Key   | TAB | Q  | W  | E  | R  | T  | Y  | U  | I  | O  | P  | [  | ]  |  \  | PGUP |
|-------|-----|----|----|----|----|----|----|----|----|----|----|----|----|----- |------|
| ID    |  2  |  8 | 14 | 20 | 26 | 32 | 38 | 44 | 50 | 56 | 62 | 68 | 74 |  80  |  86  |

#### Row 2

| Key   | CAPS | A  | S  | D  | F  | G  | H  | J  | K  | L  | ;  | '  | ENTER | PGDN |
|-------|------|----|----|----|----|----|----|----|----|----|----|----|-------|------|
| ID    |   3  |  9 | 15 | 21 | 27 | 33 | 39 | 45 | 51 | 57 | 63 | 69 |  81   |  87  |

#### Row 3

| Key   | LSHIFT | Z  | X  | C  | V  | B  | N  | M  | ,  | .  | /  | RSHIFT | UP |
|-------|--------|----|----|----|----|----|----|----|----|----|----|----- --|-----|
| ID    |   4    | 16 | 22 | 28 | 34 | 40 | 46 | 52 | 58 | 64 | 70 |   76   | 82 |

#### Row 4 -- Bottom Row

| Key   | LCTRL | WIN | LALT | SPACE | RALT | FN | LEFT | DOWN | RIGHT |
|-------|-------|-----|------|-------|------|----|------|------|-------|
| ID    |   5   | 17  |  23  |  41   |  65  | 59 |  77  |  83  |  89   |

### 5.2 Key ID Pattern

IDs are assigned **column-first**, incrementing by 6 per row within the same
physical column of the switch matrix:

- **Column 0:** ESC = 1, TAB = 2, CAPS = 3, LSHIFT = 4, LCTRL = 5
- **Column 1:** 1 = 7, Q = 8, A = 9 (IDs 7, 8, 9 -- starting at 7, stride 1 down the column)
- **General pattern:** `key_id = (column * 6) + row + 1` (approximate; some
  columns have fewer than 5 keys, causing gaps in the ID space)

The matrix has physical gaps where keys span multiple columns (e.g., Space,
Backspace, Shift). Those positions are simply unoccupied in the ID sequence.

---

## 6. Reverse Engineering Methodology

The protocol was decoded through the following steps:

### Step 1 -- HID Enumeration

Used **pywinusb** to enumerate all HID devices matching VID `0x3151` / PID
`0x5030`. This revealed the four collections on interfaces `mi_01` and `mi_02`,
their Usage Pages, and their report sizes.

### Step 2 -- HID Descriptor Analysis

Called Windows HID API functions (`HidP_GetCaps`, `HidP_GetValueCaps`) via
**ctypes** to parse the HID Report Descriptors. The vendor-specific collection
on `mi_01/col05` was identified as having 31 x 8-bit input value capabilities,
suggesting a multi-value data channel. The config collection on `mi_02` exposed
a 65-byte Feature Report (Report ID 0).

### Step 3 -- Web Driver Interception

The official Attack Shark web-based configuration tool (which uses the
**WebHID API**) was loaded in the browser. A JavaScript interceptor was injected
into the page by monkey-patching the `HIDDevice.prototype.sendFeatureReport` and
`HIDDevice.prototype.receiveFeatureReport` methods in the browser console. This
captured all Feature Report traffic between the driver and the keyboard.

### Step 4 -- Activation Command Discovery

The web driver's **"Simulation Detection"** toggle (used for the "Stroke
Setting" visualization feature) was identified as the trigger that enables and
disables analog data streaming. Toggling it produced the 64-byte Feature
Reports documented in Section 3, including the `0x1B` command prefix and the
`0xE4 - byte[1]` checksum pattern.

### Step 5 -- Activation Replication in Python

The captured activation command was replicated in Python using **ctypes** calls
to `hid.dll` (`HidD_SetFeature`) and `kernel32.dll` (`CreateFileW`) to open
the `mi_02` device path and send the Feature Report programmatically.

### Step 6 -- Input Report Decoding

With analog mode active, **pywinusb** asynchronous report callbacks captured
the raw Input Reports on `col05`. The per-key report structure (prefix, analog
low byte, analog high byte, key ID) was decoded by analyzing data patterns
across multiple key presses at varying depths.

### Step 7 -- Interactive Key Mapping

A custom GUI tool was built to interactively map all 67 physical keys. Each key
was pressed individually while the tool recorded the `key_id` byte from the
incoming report, building the complete lookup table documented in Section 5.

---

## 7. Web Driver Analysis

The official Attack Shark web driver is a browser-based application that uses
the **WebHID API** (`navigator.hid`) to communicate with the keyboard. It
connects by calling:

```js
navigator.hid.requestDevice({
    filters: [{ vendorId: 0x3151, productId: 0x5030 }]
});
```

The driver supports two categories of communication:

1. **Configuration** -- Writing actuation point thresholds, Rapid Trigger
   sensitivity, and DKS (Dynamic Keystroke) profiles to the keyboard's
   onboard memory via Feature Reports on `mi_02`.

2. **Simulation / Analog Streaming** -- Toggling analog data mode for the
   real-time "Stroke Setting" visualization. This is the mechanism documented
   in Section 3.

The interception was performed entirely in the browser developer console by
overriding the `sendFeatureReport` and `receiveFeatureReport` methods on the
`HIDDevice` prototype before the driver established its connection.

---

## 8. Operating Modes

The application supports two modes to handle the fact that most PC games do
not accept simultaneous gamepad and keyboard/mouse input.

### 8.1 Hybrid Mode (default)

Only the **left analog stick** (WASD) is sent to the virtual Xbox 360
controller. All other keyboard keys and the mouse pass through to the game
natively. This is the ideal mode for games that accept both a gamepad and
keyboard/mouse at the same time (simultaneous input).

**Advantages:** True analog movement + native mouse precision for aiming.
**Limitation:** Only works with games that support simultaneous input. A
community-maintained list is available at
[PCGamingWiki](https://www.pcgamingwiki.com/wiki/List_of_games_that_support_simultaneous_input).

### 8.2 Full Controller Mode

All configured keyboard keys are mapped to virtual Xbox 360 controller
inputs: left stick, right stick, analog triggers, face buttons, bumpers,
D-pad, and system buttons. The game sees a single Xbox controller with no
keyboard/mouse interference.

**Advantages:** Compatible with any game that supports Xbox controllers.
**Limitation:** Mouse aiming is not available (right stick is keyboard-driven).

### 8.3 The Simultaneous Input Problem

When a game detects XInput controller data, it typically switches to
"controller mode" and suppresses keyboard/mouse. When it detects mouse
movement, it switches back. This causes UI prompt flickering and input
conflicts. This is a **per-game developer decision**, not a Windows or API
limitation. The mode selector allows the user to choose the best strategy
for each game.

---

## 9. Limitations

- **Mutually exclusive with normal keyboard operation.** While analog mode is
  active, the keyboard stops sending standard HID keyboard reports. The
  official driver displays a warning about this. Normal keyboard functionality
  resumes when analog mode is disabled.

- **Single key per report.** Each Input Report carries the analog value for
  exactly one key. There is no multi-key batch format. However, reports arrive
  fast enough for real-time tracking of multiple simultaneous key presses.

- **Model-specific protocol.** The protocol documented here is specific to the
  X68PRO HE (PID `0x5030`). Other Attack Shark Hall Effect models (X68 HE,
  X68 MAX HE) use the same Sonix chipset but may have different PIDs and
  potentially different command bytes or report structures.

- **No passive analog readout.** There is no known way to read analog switch
  data while simultaneously preserving normal keyboard functionality. This
  appears to be a firmware-level limitation of the Sonix controller.

---

## 10. Implementation Notes

### Platform

Windows only. The implementation relies on:

- **ctypes** bindings to `hid.dll` for `HidD_SetFeature` and `HidD_GetFeature`.
- **ctypes** bindings to `kernel32.dll` for `CreateFileW` to open HID device
  handles by path.
- **pywinusb** for HID device enumeration and asynchronous Input Report
  callbacks.

### Virtual Controller Output

- **ViGEmBus** driver + **vgamepad** Python library to create a virtual Xbox
  360 controller.
- Analog key values are mapped to gamepad axes (thumbsticks, triggers).

### Performance

- **Gamepad update rate:** event-driven. A worker thread updates the virtual controller on every analog report, capped at about 1000 updates/s, and at least every 4 ms so smoothing can settle. Smoothing depends on elapsed time, not on the update rate.
- **Smoothing:** Exponential Moving Average (EMA) with a configurable
  smoothing factor to reduce jitter in the analog readings.
- **Diagonal stick clamping:** The resultant magnitude of combined X/Y axis
  inputs is capped at 1.0 to enforce a circular deadzone and prevent corner
  over-extension on the virtual thumbstick.
