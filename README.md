# HE Analog Gamepad

**Turn your analog Hall Effect keyboard into a true analog Xbox 360 controller.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

Hall Effect keyboards measure how far you press each key. This app reads that value and sends it to a virtual Xbox 360 controller. The result is **true analog stick input from WASD**: press a key lightly to walk, press it fully to run.

## Supported Devices

| Device | Status |
|--------|--------|
| Attack Shark X68PRO HE (PID `0x5030`) | Confirmed working |
| Attack Shark X68HE (PID `0x502D`) | Confirmed working ([#8](https://github.com/adapt-to-it/he-analog-gamepad/issues/8)) |
| Attack Shark X98 HE (PID `0x5029`) | Config ready, waiting for user confirmation ([#4](https://github.com/adapt-to-it/he-analog-gamepad/issues/4)) |
| Attack Shark X82 PRO HE | In development -- data needed ([#4](https://github.com/adapt-to-it/he-analog-gamepad/issues/4)) |
| Other Sonix-based HE keyboards | May work -- run the [capture page](#help-add-your-keyboard) and send us the files |

The app detects the connected model automatically. Is your keyboard missing? See [Help add your keyboard](#help-add-your-keyboard).

## Features

- **True analog input** -- WASD drives the left stick with the full key travel, not on/off emulation
- **Two modes** -- **Hybrid** (only WASD becomes the left stick, keyboard and mouse keep working) and **Full Controller** (all keys become Xbox buttons, sticks and triggers)
- **Dual analog sticks and analog triggers** in Full Controller mode
- **Live controller view** -- See stick position, trigger bars and active buttons in real time
- **Adjustable feel** -- Deadzone, smoothing and sensitivity curve sliders
- **Custom bindings** -- Assign any key to any gamepad action; settings are saved automatically
- **Automatic model detection** -- The app loads the right config for the keyboard that is plugged in
- **Low latency** -- The gamepad updates as soon as a key moves ([details](#latency))
- **One-click launcher** -- Double-click `run.vbs`, no terminal needed

## Quick Start

### Requirements

- **OS:** Windows 10 or later
- **Python:** 3.10 or later
- **Keyboard:** a model from [Supported Devices](#supported-devices), connected with the USB cable
- **ViGEmBus driver:** creates the virtual Xbox 360 controller. Download it from [ViGEmBus releases](https://github.com/nefarius/ViGEmBus/releases)

A step-by-step guide for beginners is in [INSTALL.md](INSTALL.md).

### Installation

1. **Install ViGEmBus** from the [official releases page](https://github.com/nefarius/ViGEmBus/releases). A system restart may be required.

2. **Download the project**

   ```bash
   git clone https://github.com/adapt-to-it/he-analog-gamepad.git
   cd he-analog-gamepad
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

5. **Connect your keyboard** via USB.

### Launch

Double-click **`run.vbs`** in the project folder, or run from the terminal:

```bash
python virtual_gamepad.py
```

1. **Select a mode** with the **Hybrid** / **Full controller** switch in the top bar. The top bar also shows the detected keyboard model:
   - **hybrid** (default) -- Only WASD sends left stick data. Keyboard and mouse keep working. Use it for games that accept gamepad and keyboard/mouse at the same time (for example Halo Infinite, GTA V, Battlefield).
   - **full_controller** -- All keys are mapped to Xbox buttons, sticks and triggers. Use it for games that don't accept mixed input.
2. Click **ACTIVATE GAMEPAD**. Windows sees a standard Xbox 360 controller.
3. Check the stick and trigger response in the live view, and adjust the sliders in the **Tuning** tab if needed.
4. Click **DEACTIVATE** to turn off analog mode and remove the virtual controller.

The keys are already mapped for every supported model. You don't need to run the key mapper.

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

All inputs are mapped to the virtual Xbox controller.

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

To change a binding, open the **Bindings** tab, click the binding and press the key on the keyboard. A light touch is ignored: press the key at least halfway. Click the same binding again to cancel; after 6 seconds without a key press the old binding stays. Bindings are grouped by stick, triggers, buttons, D-pad and system; hybrid mode shows only the left stick.

## Settings

The sliders in the **Tuning** tab change how the keys feel. Every change is saved automatically in `gamepad_config.json`, together with the bindings and the selected mode, and loaded at startup. **Reset to defaults** restores the default settings and bindings.

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| `mode` | `hybrid` / `full_controller` | `hybrid` | Operating mode (see [Launch](#launch)) |
| `deadzone` | 0.00 -- 0.50 | 0.05 | Values below this threshold are treated as zero |
| `smoothing` | 0.00 -- 0.95 | 0.30 | Share of the previous value kept every 1/120 s (higher = smoother but more latent). Independent of the update rate |
| `sensitivity_curve` | 0.20 -- 3.00 | 1.00 | Response curve exponent (1.0 = linear, <1 = more sensitive at low travel, >1 = less sensitive at low travel) |
| `button_threshold` | 0.01 -- 0.50 | 0.15 | Normalized analog value required to register a digital button press (Full Controller only) |
| `trigger_threshold` | 0.01 -- 0.50 | 0.15 | Normalized analog value required to register a trigger press (Full Controller only) |
| `analog_max_override` | 100 -- 1.5 × `analog_max` (at least 500) | `analog_max` of the connected model | Maximum expected raw analog value from the keyboard |
| `analog_max_device` | -- | set on save | VID:PID of the keyboard the Analog Max was set on. With another keyboard the value from its config is used |

## Troubleshooting

**The keyboard is not detected**
- Connect the keyboard with the USB cable. Wireless mode does not expose the analog interface.
- Close the manufacturer's software: it can take exclusive access to the device.
- Check in Device Manager that the VID/PID matches a supported model: `0x3151` / `0x5030` (X68PRO HE), `0x3151` / `0x502D` (X68HE), `0x3151` / `0x5029` (X98 HE).

**"ENABLE FAILED" when activating the gamepad**
- The app could not open the keyboard's configuration interface. Unplug and reconnect the keyboard.
- If access is denied, run the application as Administrator.

**"ViGEm ERROR" when activating**
- ViGEmBus is not installed or not running. Install it from the [releases page](https://github.com/nefarius/ViGEmBus/releases) and restart your computer.

**Stick input feels twitchy or too sensitive**
- Increase **Deadzone** to filter out small noise near the resting position.
- Increase **Smoothing** to dampen rapid changes, at the cost of slight input delay.
- Raise **Sensitivity Curve** above 1.0 to make the first part of the key travel less responsive.

**The stick reaches full deflection with the key only half pressed, or never reaches it**
- The **Analog Max** value does not match the keyboard. Move the **Analog Max** slider to the highest value the key reaches.
- A saved Analog Max applies only to the keyboard it was set on. With a different keyboard the app uses the value from that keyboard's config.

**Some keys are not registering**
- Check that the key label in your gamepad bindings matches a key in the config of your model.
- On the X68PRO HE and X68HE you can run `key_mapper_gui.py` and use **FREE MODE** to test individual keys (see [Key mapper](#key-mapper)).

**The gamepad is not recognized by a game**
- Some games only detect controllers at startup. Launch the game after activating the virtual gamepad.
- Check that the controller appears in Windows Settings > Bluetooth & devices > Devices > Controllers.
- Use a tool like [Gamepad Tester](https://gamepad-tester.com/) in the browser to confirm the virtual controller works.

**The game switches between keyboard and controller mode (flickering prompts)**
- The game does not accept gamepad and keyboard/mouse at the same time. Switch to **full_controller** mode, or check the [PCGamingWiki simultaneous input list](https://www.pcgamingwiki.com/wiki/List_of_games_that_support_simultaneous_input) to see if your game works with hybrid mode.

## Help add your keyboard

If you own a Hall Effect keyboard that is not in the table, you can send the data needed to support it. No installation and no technical knowledge are required.

1. Open the **[capture page](https://adapt-to-it.github.io/he-analog-gamepad/tools/capture/)** in Chrome or Edge on a computer (Windows, macOS or Linux).
2. Connect the keyboard with the USB cable and follow the steps on screen. The check takes about five minutes.
3. At the end, click **Download JSON** and **Copy summary**.
4. Click **Open GitHub issue**, paste the summary, and attach the downloaded JSON file.

The page only reads the keyboard. On Attack Shark / Sonix keyboards (VID `0x3151`) it also asks permission to send the same analog-mode command used by this project, and turns it off before you leave. It sends no commands to keyboards from other vendors. To run it offline, download the `tools/capture/` folder and open `index.html`.

Keyboards with the same Sonix chipset (VID `0x3151`) and a similar vendor-specific HID interface are likely compatible.

---

The sections below are for advanced users and contributors.

## Advanced Tools

### Key mapper

`key_mapper_gui.py` maps each physical key to its internal analog key ID. Every supported model already has a complete mapping, so you need it only to remap keys or to test them.

```bash
python key_mapper_gui.py
```

- Click **START MAPPING** to begin the guided mapping process.
- Press each highlighted key on the keyboard when prompted, then release it.
- Use **SKIP** to skip a key or **UNDO** to redo the previous one.
- Use **FREE MODE** to test individual keys and see their IDs in real time.
- Click **SAVE CONFIG** when finished. The mapping is saved to the config of the connected model.

The mapper shows only the 65% layout, so it cannot map the extra keys of larger keyboards such as the X98 HE. For those models, use the [capture page](#help-add-your-keyboard).

### WebHID interceptor

To capture the keyboard's protocol traffic in a Chromium-based browser:

1. Open the keyboard's web configuration tool in Chrome or Edge.
2. Open DevTools (F12) and go to the Console tab.
3. Paste the contents of `intercept_webhid.js` and press Enter.
4. Interact with the web driver. All HID traffic is logged.
5. Run `__webhid_export()` in the console to copy the captured data to the clipboard.

## Model Configs

Each model has a JSON config with its device IDs, protocol and key mapping:

- `key_config.json` -- X68PRO HE (67 keys).
- `devices/*.json` -- other models, for example `devices/x68he_502d.json` and `devices/x98he_5029.json`.

At startup both apps check `key_config.json` first, then every file in `devices/`, and use the first one whose VID and PID match the connected keyboard. The config sets the analog commands and the analog range (`analog_max`: 350 on the X68PRO HE, 730 on the X68HE, 700 on the X98 HE).

To add a model, save the `key_config.json` produced by the capture page as `devices/<model>.json`. No code changes are needed. You should not need to edit these files by hand.

## Latency

The gamepad is not updated by the GUI. A dedicated thread waits for analog reports and updates the virtual controller as soon as one arrives:

- **Report to controller:** about 0.05 ms median, about 1 ms at the 99th percentile in a simulated test. Earlier versions updated from the GUI loop every 8–16 ms.
- **Update cap:** about 1000 updates per second. Faster reports are merged into one update.
- **Idle tick:** at least one update every 4 ms, so smoothing settles after the last key event.
- **Windows timer:** the app sets the system timer resolution to 1 ms while it runs and restores it on exit.

These numbers come from a test with simulated HID and ViGEm devices. Measurements on real hardware are welcome in the issues.

## How It Works

The supported keyboards use a **Sonix Technology** microcontroller (VID `0x3151`) with multiple HID interfaces. A vendor-specific configuration interface (usage page `0xFFFF`, usage `0x0002`, usually `mi_02`) switches the keyboard into analog mode when it receives a specific **HID Feature Report**:

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

The analog value is a 16-bit unsigned integer from **0** (key released) to the model's maximum (`analog_max`). The app reads these reports, normalizes the values, applies deadzone and sensitivity curves, and maps them to a virtual Xbox 360 controller created through ViGEmBus.

> The protocol was discovered through reverse engineering using HID descriptor analysis, raw USB sniffing, and a custom WebHID interceptor. Full technical documentation is available in [TECHNICAL.md](TECHNICAL.md).

## Project Structure

```
he-analog-gamepad/
├── virtual_gamepad.py      # Main application -- virtual Xbox 360 controller with GUI
├── key_mapper_gui.py       # Interactive key mapping tool
├── device_config.py        # Picks the config for the connected keyboard, reads IDs and protocol
├── key_config.json         # X68PRO HE config (67 keys)
├── devices/                # Configs for other models (one JSON per keyboard)
├── gamepad_config.json     # Gamepad bindings and settings (auto-generated)
├── intercept_webhid.js     # Browser WebHID traffic interceptor
├── tools/capture/          # Guided WebHID capture page for new keyboards
├── run.vbs                 # One-click launcher (double-click to start, no terminal)
├── requirements.txt        # Python dependencies
├── TECHNICAL.md            # Protocol reverse engineering documentation
├── INSTALL.md              # Step-by-step installation guide
├── LICENSE                 # MIT License
└── README.md               # This file
```

## Contributing

Contributions are welcome. To add a keyboard, the easiest way is the [capture page](#help-add-your-keyboard). If you got a different Hall Effect keyboard working on your own, open an issue or pull request with:

1. Your keyboard model and VID/PID
2. Any protocol differences you discovered
3. Your config JSON

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
- **Sonix Technology** -- Manufacturer of the microcontroller used in the supported keyboards

This project is not affiliated with, endorsed by, or connected to Attack Shark, Sonix Technology, or Microsoft. All trademarks belong to their respective owners. The protocol information was obtained through independent reverse engineering for interoperability purposes.

---

## Quick file sharing

Learn how to quickly share files locally and remotely: [droplnk.app](https://droplnk.app) · [droplnk.app/s/](https://droplnk.app/s/)
