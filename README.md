# Panel Hopper 🪱

A Python toolkit for controlling **BK-Light ACT1026 32×32 RGB LED panels** over Bluetooth Low Energy (BLE).

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- 🔍 **Auto-discovery** - Scan for LED panels via BLE
- 🖼️ **Image display** - Send any image (auto-resized to 32×32)
- 📝 **Text display** - Pixel-perfect dot-matrix or system fonts
- 🔲 **Grid mode** - Treat 4 panels as one 64×64 display
- 🌐 **Web interface** - Browser-based control panel
- ⌨️ **CLI tools** - Scriptable command-line utilities
- 📱 **Cross-platform** - Windows, macOS, Linux

## Hardware Requirements

### Bluetooth Adapter

Your Bluetooth adapter must support:
- **BLE 4.0** or newer (Bluetooth Low Energy)
- **GATT Client mode** (Central role)
- **Long ATT writes** (for image data transfer)

Most USB BLE dongles work. Built-in laptop Bluetooth may or may not work depending on the chipset.

**Tested adapters:**
- Generic CSR8510 USB dongles
- Realtek RTL8761B
- Intel AX200/AX210 (built-in)

### LED Panels

This toolkit is designed for the **BK-Light ACT1026 32×32 LED Pixel Board**:
- ✅ **Supported:** [LED Pixelbord (32×32)](https://www.action.com/nl-nl/p/3217439/led-pixelbord/) - €14.95 at Action
- 🔜 **Planned:** [LED Pixel Scherm (16×32)](https://www.action.com/nl-nl/p/3217438/led-pixel-scherm/) - support coming in a future update

The panels advertise via BLE as `LED_BLE_*`.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/ferrywell/panel-hopper.git
cd panel-hopper
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. (Windows only) Run as Administrator

For reliable BLE access on Windows, run your terminal as Administrator.

## Quick Start

### 1. Scan for panels

```bash
python cli/scan.py
```

### 2. Interactive setup

Name your panels and configure grid layout:

```bash
python cli/setup.py
```

### 3. Send an image

```bash
python cli/send_image.py assets/examples/charmander.png
```

### 4. Or launch the web interface

```bash
python web/server.py
```

Open http://localhost:8000 in your browser.

## Project Structure

```
panel-hopper/
├── src/panel_hopper/     # Core library
│   ├── config.py         # Panel configuration
│   ├── core.py           # BLE communication
│   └── graphics.py       # Image processing
│
├── cli/                  # Command-line tools
│   ├── scan.py           # Discover panels
│   ├── setup.py          # Interactive setup
│   ├── send_image.py     # Send images
│   ├── send_text.py      # Send text
│   └── send_grid.py      # Grid operations
│
├── web/                  # Web interface
│   ├── server.py         # FastAPI backend
│   └── static/           # Frontend files
│
├── assets/               # Image storage
│   ├── examples/         # Example images
│   ├── uploads/          # User uploads
│   ├── gifs/             # Downloaded GIFs
│   └── fonts/            # Custom fonts
│
├── tests/                # Test scripts
├── vendor/               # Third-party (bk_light)
│
├── panels.json           # Your panel config (gitignored)
├── panels.json.example   # Example config template
└── requirements.txt      # Dependencies
```

## CLI Usage

### Scan for panels

```bash
python cli/scan.py                    # Discover panels
python cli/scan.py --timeout 15       # Longer scan
python cli/scan.py --save             # Add to config
```

### Send images

```bash
python cli/send_image.py image.png              # To all panels
python cli/send_image.py image.png --panel foo  # To specific panel
python cli/send_image.py image.png --grid       # Split across 4 panels
```

### Send text

```bash
python cli/send_text.py "HOP"                   # To all panels
python cli/send_text.py "OK" --color green      # Custom color
python cli/send_text.py "STOP" --grid           # 64×64 text
python cli/send_text.py "A1" --dot-matrix       # Highway sign style
```

### Grid mode

```bash
python cli/send_grid.py                         # Interactive
python cli/send_grid.py image.png               # Split image
python cli/send_grid.py "HI" --color amber      # Grid text
```

## Web Interface

Launch the web server:

```bash
python web/server.py
python web/server.py --port 3000              # Custom port
python web/server.py --host 192.168.1.100     # Network access
```

Features:
- Panel management (enable/disable, rename)
- Image upload and gallery
- Text input with color picker
- Grid mode with LED pixel preview
- Live activity log

## Grid Layout

For 2×2 grid mode, arrange 4 panels like this:

```
┌─────────────┬─────────────┐
│ linksboven  │ rechtsboven │
│ (top-left)  │ (top-right) │
├─────────────┼─────────────┤
│ linksonder  │ rechtsonder │
│ (bot-left)  │ (bot-right) │
└─────────────┴─────────────┘
```

Configure positions during `python cli/setup.py` or edit `panels.json`.

## Configuration

### panels.json

Your panels are stored in `panels.json` (created after first scan):

```json
{
  "panels": {
    "AA:BB:CC:DD:EE:FF": {
      "mac": "AA:BB:CC:DD:EE:FF",
      "name": "my_panel",
      "enabled": true,
      "order": 1,
      "grid_position": "linksboven"
    }
  },
  "grid": {
    "linksboven": "AA:BB:CC:DD:EE:FF",
    "rechtsboven": null,
    "linksonder": null,
    "rechtsonder": null
  },
  "settings": {
    "scan_timeout": 10.0,
    "send_delay": 0.15,
    "retry_count": 3
  }
}
```

## Troubleshooting

### "No panels found"

- Ensure panels are powered on
- Move closer (within 10 meters)
- Check no other app is connected to them
- Try a longer scan: `python cli/scan.py --timeout 20`

### "Connection timeout"

- Power cycle the panel
- Reset your Bluetooth adapter
- On Windows, run as Administrator
- Increase retry count in config

### "Bleak not found" / Import errors

```bash
pip install -r requirements.txt
```

### Built-in Bluetooth doesn't work

Some laptop Bluetooth chips have limited BLE support. Try a USB BLE dongle.

## Testing

```bash
# Test BLE adapter
python tests/test_connection.py

# Test image sending
python tests/test_send.py

# Test graphics (no BLE needed)
python tests/test_graphics.py
```

## Credits & Acknowledgments

This project is built upon the excellent reverse-engineering work by **Puparia**:

🙏 **[Bk-Light-AppBypass](https://github.com/Pupariaa/Bk-Light-AppBypass)** - The original Python toolkit that decoded the BLE protocol for BK-Light LED panels. Without this foundational work, Panel Hopper would not exist.

Panel Hopper extends this with a web interface, multi-panel grid support, and additional features while keeping the core BLE communication from the original project.

## License

MIT License - see [LICENSE](LICENSE)

---

Made with 🧡 for LED panel enthusiasts

