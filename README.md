# X68PRO HE Virtual Gamepad

**Turn your analog Hall Effect keyboard into a true analog Xbox 360 controller.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

This project reverse engineers the vendor-specific HID protocol of the **Attack Shark X68PRO HE** Hall Effect keyboard to extract real-time 16-bit analog key travel data, then feeds it into a virtual Xbox 360 controller via ViGEmBus. The result is **true analog stick input from WASD keys** -- not binary on/off, but smooth, pressure-sensitive movement proportional to how far you press each key.

## Features

- **True analog input** -- WASD keys drive the left stick with full 0-100% travel, not digital emulation
- **Two operating modes:**
  - **Hybrid** -- Only WASD maps to the left stick; keyboard and mouse pass through to the game normally. Ideal for games that support simultaneous gamepad + keyboard/mouse input.
  - **Full Controller** -- All keys mapped to Xbox buttons, sticks, and triggers. For games that require a single input device.
- **Dual analog sticks** (Full Controller mode) -- Left stick (WASD) and right stick (IJKL) with independent analog axes
- **Analog triggers** (Full Controller mode) -- Left and right triggers respond to key travel depth
- **All 67 keys mapped** -- Complete key-to-ID mapping for every key on the 65% layout
- **Live controller visualization** -- Real-time GUI showing stick position, trigger bars, and active buttons
- **Configurable curves** -- Deadzone, smoothing (EMA), and sensitivity curve (linear/exponential) sliders
- **Customizable bindings** -- Remap any keyboard key to any gamepad action via the settings panel
- **Persistent configuration** -- Bindings, settings, and selected mode saved to JSON, loaded automatically on startup
- **Interactive key mapper** -- Visual tool to map (or remap) every physical key to its analog ID
- **WebHID interceptor** -- JavaScript snippet for capturing the keyboard's protocol traffic in the browser
- **120 Hz update rate** -- Gamepad state refreshed at ~120 Hz for low-latency response
- **One-click launcher** -- `run.vbs` to start the app with a double-click, no terminal needed

## How It Works

The X68PRO HE uses a **Sonix Technology** microcontroller (VID `0x3151`, PID `0x5030`) with multiple HID interfaces. Interface 2 (`mi_02`) exposes a vendor-specific endpoint that can be switched into analog mode by sending a specific **HID Feature Report**:

```
Enable:  [0x1B, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE3, ...zero-padded to 64 bytes]
Disable: [0x1B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE4, ...zero-padded to 64 bytes]
```

Once enabled, the keyboard streams **Input Reports** (Report ID `0x05`) for every key event:

| Byte | Content |
|------|---------|
| 0 | Report ID (`0x05`) |
| 1 | Prefix (`0x1B`) |
| 2 | Analog value (low byte) |
| 3 | Analog value (high byte) |
| 4 | Key ID (unique per physical key) |

The analog value is a 16-bit unsigned integer ranging from **0** (key released) to approximately **350** (key fully depressed). This project reads these reports, normalizes the values, applies deadzone and sensitivity curves, and maps them to a virtual Xbox 360 controller created through ViGEmBus.

> The protocol was discovered through reverse engineering using HID descriptor analysis, raw USB sniffing, and a custom WebHID interceptor. Full technical documentation is available in [TECHNICAL.md](TECHNICAL.md).

## Requirements

- **OS:** Windows 10 or later (uses native Windows HID API via ctypes)
- **Python:** 3.10 or later
- **Hardware:** Attack Shark X68PRO HE keyboard (Hall Effect variant)
- **ViGEmBus driver:** Required for virtual Xbox 360 controller emulation
  - Download from [ViGEmBus releases](https://github.com/nefarius/ViGEmBus/releases)

## Installation

1. **Install ViGEmBus**

   Download and install the latest ViGEmBus driver from the [official releases page](https://github.com/nefarius/ViGEmBus/releases). A system restart may be required.

2. **Clone the repository**

   ```bash
   git clone https://github.com/YOUR_USERNAME/x68pro-he-gamepad.git
   cd x68pro-he-gamepad
   ```

3. **Create a virtual environment (recommended)**

   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

4. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

5. **Connect your X68PRO HE keyboard** via USB

## Usage

### Step 1: Map Your Keys (first time only)

Run the key mapper to associate each physical key with its internal analog key ID:

```bash
python key_mapper_gui.py
```

- Click **START MAPPING** to begin the guided mapping process.
- Press each highlighted key on the keyboard when prompted, then release it.
- Use **SKIP** to skip a key or **UNDO** to redo the previous one.
- Use **FREE MODE** to test individual keys and see their IDs in real time.
- Click **SAVE CONFIG** when finished. The mapping is saved to `key_config.json`.

A pre-configured `key_config.json` with all 67 keys already mapped is included in this repository.

### Step 2: Launch the Virtual Gamepad

Double-click **`run.vbs`** in the project folder, or run from the terminal:

```bash
python virtual_gamepad.py
```

- The GUI will connect to the keyboard's HID interfaces automatically.
- **Select a mode** from the dropdown in the top bar:
  - **hybrid** (default) -- Only WASD sends left stick data. Your keyboard and mouse continue to work normally. Use this for games that support simultaneous gamepad + keyboard/mouse input (e.g., Halo Infinite, GTA V, Battlefield).
  - **full_controller** -- All keys are mapped to Xbox buttons, sticks, and triggers. Use this for games that don't support mixed input.
- Click **ACTIVATE GAMEPAD** to enable analog mode and create the virtual Xbox 360 controller.
- The controller will appear in Windows as a standard Xbox 360 gamepad.
- Use the live visualization to verify stick and trigger response.
- Adjust settings (deadzone, smoothing, sensitivity) using the sliders on the right panel.
- Click **DEACTIVATE** to disable analog mode and remove the virtual controller.

### WebHID Interceptor (optional)

To capture the keyboard's protocol traffic in a Chromium-based browser:

1. Open the keyboard's web configuration tool in Chrome or Edge.
2. Open DevTools (F12) and go to the Console tab.
3. Paste the contents of `intercept_webhid.js` and press Enter.
4. Interact with the web driver -- all HID traffic will be logged.
5. Run `__webhid_export()` in the console to copy captured data to the clipboard.

## Configuration

### key_config.json

Generated by the key mapper. Contains the complete mapping of key labels to internal key IDs, device identification, and protocol details. You should not need to edit this manually.

### gamepad_config.json

Created automatically when you save settings from the virtual gamepad GUI. Contains:

- **bindings** -- Which keyboard key is assigned to each gamepad action
- **settings** -- Tuning parameters for the analog processing pipeline

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| `mode` | `hybrid` / `full_controller` | `hybrid` | Operating mode (see Usage section above) |
| `deadzone` | 0.00 -- 0.50 | 0.05 | Values below this threshold are treated as zero |
| `smoothing` | 0.00 -- 0.95 | 0.30 | Exponential moving average factor (higher = smoother but more latent) |
| `sensitivity_curve` | 0.20 -- 3.00 | 1.00 | Response curve exponent (1.0 = linear, <1 = more sensitive at low travel, >1 = less sensitive at low travel) |
| `button_threshold` | 0.01 -- 0.50 | 0.15 | Normalized analog value required to register a digital button press (Full Controller only) |
| `trigger_threshold` | 0.01 -- 0.50 | 0.15 | Normalized analog value required to register a trigger press (Full Controller only) |
| `analog_max_override` | 100 -- 500 | 350 | Maximum expected raw analog value from the keyboard |

## Default Gamepad Layout

### Hybrid Mode (default)

Only the left stick is active. All other keys work as normal keyboard input.

| Gamepad Action | Default Key | Notes |
|----------------|-------------|-------|
| Left Stick Up | W | Analog |
| Left Stick Down | S | Analog |
| Left Stick Left | A | Analog |
| Left Stick Right | D | Analog |

### Full Controller Mode

All inputs mapped to the virtual Xbox controller.

| Gamepad Action | Default Key | Notes |
|----------------|-------------|-------|
| Left Stick Up | W | Analog |
| Left Stick Down | S | Analog |
| Left Stick Left | A | Analog |
| Left Stick Right | D | Analog |
| Right Stick Up | I | Analog |
| Right Stick Down | K | Analog |
| Right Stick Left | J | Analog |
| Right Stick Right | L | Analog |
| A Button | SPACE | Digital (threshold) |
| B Button | LSHIFT | Digital (threshold) |
| X Button | E | Digital (threshold) |
| Y Button | Q | Digital (threshold) |
| Left Bumper | TAB | Digital (threshold) |
| Right Bumper | R | Digital (threshold) |
| Left Trigger | LCTRL | Analog |
| Right Trigger | F | Analog |
| D-Pad Up | UP | Digital (threshold) |
| D-Pad Down | DOWN | Digital (threshold) |
| D-Pad Left | LEFT | Digital (threshold) |
| D-Pad Right | RIGHT | Digital (threshold) |
| Start | ENTER | Digital (threshold) |
| Back | ESC | Digital (threshold) |
| Left Thumb Click | C | Digital (threshold) |
| Right Thumb Click | V | Digital (threshold) |

All bindings can be changed through the GUI settings panel or by editing `gamepad_config.json` directly.

## Supported Devices

| Device | Status |
|--------|--------|
| Attack Shark X68PRO HE | Confirmed working |
| Other Sonix-based HE keyboards | May work with key remapping -- use the key mapper to generate a new `key_config.json` |

If your keyboard uses the same Sonix chipset (VID `0x3151`) and exposes a similar vendor-specific HID interface, it is likely compatible. Run `key_mapper_gui.py` to map the keys for your specific model.

## Troubleshooting

**The keyboard is not detected**
- Ensure the keyboard is connected via USB (wireless mode does not expose the analog HID interface).
- Check that no other application has exclusive access to the device (close the manufacturer's software).
- Verify the VID/PID matches (`0x3151` / `0x5030`) using Device Manager or a HID enumeration tool.

**"ENABLE FAILED" when activating the gamepad**
- The config interface (`mi_02`) could not be found or opened. Try unplugging and reconnecting the keyboard.
- Run the application as Administrator if access is denied.

**"ViGEm ERROR" when activating**
- ViGEmBus is not installed or not running. Install it from the [releases page](https://github.com/nefarius/ViGEmBus/releases) and restart your computer.

**Stick input feels twitchy or too sensitive**
- Increase the **Deadzone** slider to filter out small noise near the resting position.
- Increase **Smoothing** to dampen rapid fluctuations (at the cost of slight input delay).
- Raise the **Sensitivity Curve** above 1.0 to make the lower end of key travel less responsive.

**Some keys are not registering**
- Run `key_mapper_gui.py` and verify all keys are mapped. Use **FREE MODE** to test individual keys.
- Check that the key label in your gamepad bindings matches exactly what is in `key_config.json`.

**The gamepad is not recognized by a game**
- Some games only detect controllers at startup. Launch the game after activating the virtual gamepad.
- Verify the controller appears in Windows Settings > Bluetooth & devices > Devices > Controllers.
- Use a tool like [Gamepad Tester](https://gamepad-tester.com/) in the browser to confirm the virtual controller is working.

**Game switches between keyboard and controller mode (flickering prompts)**
- The game does not support simultaneous gamepad + keyboard/mouse input. Switch to **full_controller** mode to map everything to the virtual Xbox controller, or check the [PCGamingWiki simultaneous input list](https://www.pcgamingwiki.com/wiki/List_of_games_that_support_simultaneous_input) to see if your game is compatible with hybrid mode.

## Project Structure

```
x68pro-he-gamepad/
├── virtual_gamepad.py      # Main application -- virtual Xbox 360 controller with GUI
├── key_mapper_gui.py       # Interactive key mapping tool
├── key_config.json         # Complete key mapping (67 keys, generated by mapper)
├── gamepad_config.json     # Gamepad bindings and settings (auto-generated)
├── intercept_webhid.js     # Browser WebHID traffic interceptor
├── run.vbs                 # One-click launcher (double-click to start, no terminal)
├── requirements.txt        # Python dependencies
├── TECHNICAL.md            # Protocol reverse engineering documentation
├── INSTALL.md              # Step-by-step installation guide
├── LICENSE                 # MIT License
└── README.md               # This file
```

## Contributing

Contributions are welcome. If you have a different Hall Effect keyboard and successfully get it working, please open an issue or pull request with:

1. Your keyboard model and VID/PID
2. Any protocol differences you discovered
3. Your generated `key_config.json` (if applicable)

To contribute code:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

Please follow the existing code style and include clear commit messages.

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

## Credits and Acknowledgments

- **ViGEmBus** by [nefarius](https://github.com/nefarius/ViGEmBus) -- Virtual gamepad emulation framework for Windows
- **vgamepad** -- Python bindings for ViGEmBus
- **pywinusb** -- Python HID access library for Windows
- **Sonix Technology** -- Manufacturer of the microcontroller used in the X68PRO HE

This project is not affiliated with, endorsed by, or connected to Attack Shark, Sonix Technology, or Microsoft. All trademarks belong to their respective owners. The protocol information was obtained through independent reverse engineering for interoperability purposes.

---

## Quick file sharing

Learn how to quickly share files locally and remotely: [droplnk.app](https://droplnk.app) · [droplnk.app/s/](https://droplnk.app/s/)
