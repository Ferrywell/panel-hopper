# Panel Hopper 🪱

A Python toolkit for controlling **BK-Light ACT1026 32×32 RGB LED panels** over Bluetooth Low Energy (BLE).

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- 🔍 **Auto-discovery** - Scan for LED panels via BLE
- 🖼️ **Image display** - Send any image (auto-resized to 32×32)
- 🎬 **GIF animations** - Full animated GIF support with automatic optimization
- 📝 **Text display** - Pixel-perfect dot-matrix or system fonts
- 🔲 **Grid mode** - Treat multiple panels as one large display
- 🌐 **Web interface** - Browser-based control panel with LED preview
- 🎮 **Panel Manager** - Persistent BLE connections with real-time status
- 📚 **iPixel Library** - 380+ pre-made animations included
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

### 1. Launch the web interface

```bash
python web/server.py
```

Open http://localhost:8000 in your browser.

### 2. Scan for panels

Click "Scan for Panels" in the sidebar to discover your LED panels.

### 3. Connect and send content

Click "Connect" on a panel, then choose an image, GIF, or type text to send!

---

# Architecture

Panel Hopper uses a **decoupled architecture** separating BLE communication from the web interface:

```
┌─────────────────────────────────────────────────────────────┐
│                      Web Interface                          │
│                   (HTML/CSS/JavaScript)                     │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP/REST API
┌─────────────────────────▼───────────────────────────────────┐
│                    FastAPI Server                           │
│                    (web/server.py)                          │
└─────────────────────────┬───────────────────────────────────┘
                          │ Python calls
┌─────────────────────────▼───────────────────────────────────┐
│                   Panel Manager Service                     │
│               (src/panel_hopper/manager.py)                 │
│  • Persistent BLE connections                               │
│  • Connection monitoring                                    │
│  • Command queue management                                 │
└─────────────────────────┬───────────────────────────────────┘
                          │ BLE (Bluetooth Low Energy)
┌─────────────────────────▼───────────────────────────────────┐
│                   BLE Display Session                       │
│              (vendor/bk_light/display_session.py)           │
│  • Low-level BLE protocol                                   │
│  • GIF chunking & encoding                                  │
│  • Handshake & ACK management                               │
└─────────────────────────────────────────────────────────────┘
```

---

# Backend & API

## Panel Manager Service

The `PanelManager` (`src/panel_hopper/manager.py`) provides:

- **Persistent connections** - BLE connections stay open for fast commands
- **Connection monitoring** - Background task checks connection health
- **Thread-safe operations** - Uses asyncio locks for concurrent access
- **Error recovery** - Automatic reconnection on connection loss

### Panel State

Each panel tracks:
```python
@dataclass
class PanelState:
    mac: str
    name: str
    session: BleDisplaySession
    connected: bool
    brightness: int      # 0-100
    rotation: int        # 0-3 (0°, 90°, 180°, 270°)
    last_error: str
    last_activity: datetime
```

## REST API Endpoints

### Panels

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/panels` | List all configured panels |
| GET | `/api/panels/status` | Get real-time status of all panels |
| POST | `/api/panels/{mac}/connect` | Connect to a panel |
| POST | `/api/panels/{mac}/disconnect` | Disconnect from a panel |
| POST | `/api/panels/{mac}/brightness` | Set brightness (1-100) |
| POST | `/api/panels/{mac}/rotation` | Set rotation (0-3) |
| POST | `/api/panels/{mac}/save-startup` | Save current image as startup |
| POST | `/api/panels/{mac}/identify` | Flash panel for identification |
| POST | `/api/panels/{mac}/on-off` | Toggle panel power |
| PUT | `/api/panels/{mac}/rename` | Rename a panel |
| PUT | `/api/panels/{mac}/toggle` | Enable/disable a panel |

### Images & GIFs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/images` | List all available images |
| GET | `/api/ipixel-gifs` | List iPixel library GIFs |
| POST | `/api/send/single` | Send image to one panel |
| POST | `/api/send/all` | Send image to all panels |
| POST | `/api/send/base64` | Send base64-encoded image |
| POST | `/api/upload` | Upload new image |

### Text

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/text/preview` | Generate text preview |
| POST | `/api/text/send` | Send text to panels |
| GET | `/api/fonts` | List available fonts |

### Grid Mode

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/grid-preview` | Generate grid preview |
| POST | `/api/grid/send` | Send image split across grid |

## GIF Protocol

Panel Hopper implements the iPixel GIF protocol discovered through BLE capture analysis:

### Packet Structure
```
[0-1]   Total packet length (little endian)
[2-3]   Data type: 0x03,0x00 for GIF
[4]     Option: 0x00=first chunk, 0x02=continue
[5-8]   Total GIF length (4 bytes, little endian)
[9-12]  CRC32 of complete GIF (4 bytes, little endian)
[13]    Reserved: 0x00
[14]    Channel: 0x65
[15+]   Raw GIF data
```

### Chunking
- Large GIFs are split into 12KB chunks
- Each chunk receives an ACK (`05 00 03 00 01`)
- Final chunk receives completion ACK (`05 00 03 00 03`)

### Display Modes
After sending GIF data:
1. Send display mode 1 (prepare): `07 00 08 80 01 00 01`
2. Send display mode 2 (animate): `07 00 08 80 01 00 02`

### Automatic Optimization
GIFs are automatically optimized for the panel:
- Resized to 32×32 if larger
- Pre-optimized GIFs (≤32×32, <50KB) sent as-is
- Frame reduction if needed to fit BLE limits
- Palette mode encoding for compatibility

---

# Frontend

## Web Interface Features

### Panel Management
- **Real-time status** - Connection state, brightness, rotation
- **Per-panel controls** - Individual brightness/rotation sliders
- **Connection monitor** - Live connection status updates
- **Scan for new panels** - Auto-discovery via BLE

### Image Gallery
- **Drag & drop upload** - Add images easily
- **LED-style preview** - See how images look on panel
- **Delete images** - Remove unwanted uploads

### iPixel Library
- **380+ animations** - Pre-made GIFs organized by category
- **Categories**: Animations, Backgrounds, Emoji, Eyes
- **Instant send** - Click to preview, send to panel

### Text Editor
- **Live preview** - See text before sending
- **Color picker** - Any color for text
- **Font selection** - Multiple font styles
- **Auto-sizing** - Text fits panel automatically

### Grid Setup
- **Multi-panel layouts** - 1×2, 2×1, 2×2, etc.
- **Visual preview** - See how image splits
- **Drag to assign** - Position panels visually

### Activity Log
- **Command history** - See all operations
- **Error reporting** - Debug connection issues
- **Real-time updates** - Live log stream

## File Structure

```
web/
├── server.py              # FastAPI backend
└── static/
    ├── index.html         # Main application (SPA)
    ├── favicon.ico        # Browser icon
    └── ipixel_gifs/       # iPixel library (380+ GIFs)
        ├── animations/    # Animated text & effects
        ├── backgrounds/   # Animated backgrounds
        ├── emoji_32/      # Emoji graphics
        └── eyes/          # Eye animations
```

---

# CLI Usage

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
python cli/send_image.py image.png --grid       # Split across grid
```

### Send text

```bash
python cli/send_text.py "HOP"                   # To all panels
python cli/send_text.py "OK" --color green      # Custom color
python cli/send_text.py "A1" --dot-matrix       # Highway sign style
```

---

# Configuration

## panels.json

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

---

# Troubleshooting

### "No panels found"

- Ensure panels are powered on
- Move closer (within 10 meters)
- Check no other app is connected to them
- Try a longer scan timeout

### "Connection timeout"

- Power cycle the panel
- Reset your Bluetooth adapter
- On Windows, run as Administrator

### "GIF not animating"

- Check GIF isn't too large (>50KB after resize may have issues)
- Try a GIF from the iPixel library (known to work)
- Pre-optimized 32×32 GIFs work best

### "Bleak not found" / Import errors

```bash
pip install -r requirements.txt
```

---

# Credits & Acknowledgments

This project is built upon the excellent reverse-engineering work by **Puparia**:

🙏 **[Bk-Light-AppBypass](https://github.com/Pupariaa/Bk-Light-AppBypass)** - The original Python toolkit that decoded the BLE protocol for BK-Light LED panels.

The GIF animation protocol was reverse-engineered from the **iPixel Color** app through BLE capture analysis.

---

# License

MIT License - see [LICENSE](LICENSE)

---

Made with 🧡 for LED panel enthusiasts
