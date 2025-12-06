#!/usr/bin/env python3
"""
Panel Control CLI

Command-line tool for controlling LED panels.
Can be used standalone or for automation/scripting.

Usage:
    python panel_ctl.py scan                              # Scan for panels
    python panel_ctl.py connect <mac>                     # Connect to panel
    python panel_ctl.py disconnect <mac>                  # Disconnect from panel
    python panel_ctl.py brightness <mac> <0-100>          # Set brightness
    python panel_ctl.py rotate <mac> <0|90|180|270>       # Set rotation
    python panel_ctl.py send <mac> <image.png>            # Send image
    python panel_ctl.py identify <mac> [number]           # Flash ID number
    python panel_ctl.py save <mac>                        # Save as startup
    python panel_ctl.py status [mac]                      # Show status
    python panel_ctl.py interactive                       # Interactive mode
"""

import argparse
import asyncio
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / "vendor"))

from panel_hopper.manager import get_manager, PanelManager
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


async def cmd_scan(args):
    """Scan for panels."""
    manager = get_manager()
    
    print("🔍 Scanning for LED panels...")
    panels = await manager.scan(timeout=args.timeout)
    
    if not panels:
        print("No panels found.")
        return
    
    print(f"\n✓ Found {len(panels)} panel(s):\n")
    for p in panels:
        print(f"  MAC: {p['mac']}")
        print(f"  Name: {p['name']}")
        print()


async def cmd_connect(args):
    """Connect to a panel."""
    manager = get_manager()
    
    mac = args.mac.upper()
    name = args.name or mac
    
    print(f"🔌 Connecting to {name} ({mac})...")
    
    success = await manager.connect(mac, name=name)
    
    if success:
        print(f"✓ Connected to {name}")
    else:
        status = manager.get_status(mac)
        error = status.get('error', 'Unknown error') if status else 'Unknown error'
        print(f"✗ Connection failed: {error}")
        sys.exit(1)


async def cmd_disconnect(args):
    """Disconnect from a panel."""
    manager = get_manager()
    
    mac = args.mac.upper()
    
    print(f"🔌 Disconnecting from {mac}...")
    
    await manager.disconnect(mac)
    print(f"✓ Disconnected")


async def cmd_brightness(args):
    """Set panel brightness."""
    manager = get_manager()
    
    mac = args.mac.upper()
    value = args.value
    
    # Auto-connect if not connected
    if not manager.is_connected(mac):
        print(f"🔌 Connecting to {mac}...")
        if not await manager.connect(mac):
            print("✗ Connection failed")
            sys.exit(1)
    
    print(f"☀ Setting brightness to {value}%...")
    
    success = await manager.set_brightness(mac, value)
    
    if success:
        print(f"✓ Brightness set to {value}%")
    else:
        print("✗ Brightness command failed")
        sys.exit(1)


async def cmd_rotate(args):
    """Set panel rotation."""
    manager = get_manager()
    
    mac = args.mac.upper()
    
    # Convert degrees to rotation value
    rotation_map = {0: 0, 90: 1, 180: 2, 270: 3}
    rotation = rotation_map.get(args.degrees, 0)
    
    # Auto-connect if not connected
    if not manager.is_connected(mac):
        print(f"🔌 Connecting to {mac}...")
        if not await manager.connect(mac):
            print("✗ Connection failed")
            sys.exit(1)
    
    print(f"↻ Setting rotation to {args.degrees}°...")
    
    success = await manager.set_rotation(mac, rotation)
    
    if success:
        print(f"✓ Rotation set to {args.degrees}°")
    else:
        print("✗ Rotation command failed")
        sys.exit(1)


async def cmd_send(args):
    """Send image to panel."""
    manager = get_manager()
    
    mac = args.mac.upper()
    image_path = Path(args.image)
    
    if not image_path.exists():
        print(f"✗ Image not found: {image_path}")
        sys.exit(1)
    
    # Auto-connect if not connected
    if not manager.is_connected(mac):
        print(f"🔌 Connecting to {mac}...")
        if not await manager.connect(mac):
            print("✗ Connection failed")
            sys.exit(1)
    
    # Load and resize image
    from PIL import Image
    import io
    
    print(f"📷 Loading {image_path.name}...")
    
    img = Image.open(image_path)
    
    # Convert to RGB if necessary
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Resize to 32x32
    img = img.resize((32, 32), Image.Resampling.LANCZOS)
    
    # Convert to PNG bytes
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    png_bytes = buffer.getvalue()
    
    print(f"📤 Sending to panel...")
    
    success = await manager.send_image(mac, png_bytes)
    
    if success:
        print(f"✓ Image sent successfully")
    else:
        print("✗ Send failed")
        sys.exit(1)


async def cmd_identify(args):
    """Flash identification number on panel."""
    manager = get_manager()
    
    mac = args.mac.upper()
    number = args.number
    
    # Auto-connect if not connected
    if not manager.is_connected(mac):
        print(f"🔌 Connecting to {mac}...")
        if not await manager.connect(mac):
            print("✗ Connection failed")
            sys.exit(1)
    
    print(f"🔦 Flashing number {number}...")
    
    success = await manager.identify(mac, number)
    
    if success:
        print(f"✓ Identification sent")
    else:
        print("✗ Identify failed")
        sys.exit(1)


async def cmd_save(args):
    """Save current display as startup image."""
    manager = get_manager()
    
    mac = args.mac.upper()
    
    # Auto-connect if not connected
    if not manager.is_connected(mac):
        print(f"🔌 Connecting to {mac}...")
        if not await manager.connect(mac):
            print("✗ Connection failed")
            sys.exit(1)
    
    print(f"💾 Saving as startup image...")
    
    success = await manager.save_as_startup(mac)
    
    if success:
        print(f"✓ Saved as startup image")
    else:
        print("✗ Save failed")
        sys.exit(1)


async def cmd_status(args):
    """Show panel status."""
    manager = get_manager()
    
    if args.mac:
        mac = args.mac.upper()
        status = manager.get_status(mac)
        
        if status:
            print(f"\nPanel: {status['name']}")
            print(f"  MAC: {status['mac']}")
            print(f"  Connected: {'✓' if status['connected'] else '✗'}")
            print(f"  Brightness: {status['brightness']}%")
            print(f"  Rotation: {status['rotation'] * 90}°")
            if status['error']:
                print(f"  Error: {status['error']}")
        else:
            print(f"Panel {mac} not found in manager.")
    else:
        panels = manager.list_panels()
        
        if not panels:
            print("No panels in manager. Use 'scan' to find panels.")
            return
        
        print(f"\n{len(panels)} panel(s) in manager:\n")
        for p in panels:
            connected = "✓ Connected" if p['connected'] else "✗ Disconnected"
            print(f"  {p['name']} ({p['mac']})")
            print(f"    Status: {connected}")
            print(f"    Brightness: {p['brightness']}%  Rotation: {p['rotation'] * 90}°")
            if p['error']:
                print(f"    Error: {p['error']}")
            print()


async def cmd_interactive(args):
    """Interactive mode."""
    manager = get_manager()
    
    print("\n" + "=" * 50)
    print("  Panel Control - Interactive Mode")
    print("=" * 50)
    print("\nCommands:")
    print("  scan              - Scan for panels")
    print("  connect <mac>     - Connect to panel")
    print("  disconnect <mac>  - Disconnect from panel")
    print("  brightness <mac> <0-100>")
    print("  rotate <mac> <0|90|180|270>")
    print("  send <mac> <image.png>")
    print("  identify <mac> [number]")
    print("  save <mac>")
    print("  status [mac]")
    print("  quit / exit")
    print()
    
    while True:
        try:
            line = input("panel> ").strip()
            if not line:
                continue
            
            parts = line.split()
            cmd = parts[0].lower()
            
            if cmd in ('quit', 'exit', 'q'):
                print("Disconnecting all panels...")
                await manager.disconnect_all()
                print("Bye!")
                break
            
            elif cmd == 'scan':
                panels = await manager.scan()
                if panels:
                    for p in panels:
                        print(f"  {p['mac']} - {p['name']}")
                else:
                    print("  No panels found")
            
            elif cmd == 'connect' and len(parts) >= 2:
                mac = parts[1].upper()
                name = parts[2] if len(parts) > 2 else mac
                if await manager.connect(mac, name=name):
                    print(f"  Connected to {name}")
                else:
                    print(f"  Connection failed")
            
            elif cmd == 'disconnect' and len(parts) >= 2:
                await manager.disconnect(parts[1].upper())
                print("  Disconnected")
            
            elif cmd == 'brightness' and len(parts) >= 3:
                mac = parts[1].upper()
                value = int(parts[2])
                if await manager.set_brightness(mac, value):
                    print(f"  Brightness: {value}%")
                else:
                    print("  Command failed")
            
            elif cmd == 'rotate' and len(parts) >= 3:
                mac = parts[1].upper()
                degrees = int(parts[2])
                rotation = {0: 0, 90: 1, 180: 2, 270: 3}.get(degrees, 0)
                if await manager.set_rotation(mac, rotation):
                    print(f"  Rotation: {degrees}°")
                else:
                    print("  Command failed")
            
            elif cmd == 'send' and len(parts) >= 3:
                mac = parts[1].upper()
                image_path = Path(parts[2])
                if image_path.exists():
                    from PIL import Image
                    import io
                    img = Image.open(image_path).convert('RGB').resize((32, 32))
                    buffer = io.BytesIO()
                    img.save(buffer, format='PNG')
                    if await manager.send_image(mac, buffer.getvalue()):
                        print("  Image sent")
                    else:
                        print("  Send failed")
                else:
                    print(f"  Image not found: {image_path}")
            
            elif cmd == 'identify' and len(parts) >= 2:
                mac = parts[1].upper()
                number = int(parts[2]) if len(parts) > 2 else 1
                if await manager.identify(mac, number):
                    print(f"  Flashed #{number}")
                else:
                    print("  Identify failed")
            
            elif cmd == 'save' and len(parts) >= 2:
                if await manager.save_as_startup(parts[1].upper()):
                    print("  Saved as startup")
                else:
                    print("  Save failed")
            
            elif cmd == 'status':
                mac = parts[1].upper() if len(parts) > 1 else None
                if mac:
                    status = manager.get_status(mac)
                    if status:
                        print(f"  {status['name']}: {'Connected' if status['connected'] else 'Disconnected'}")
                    else:
                        print(f"  Panel not found")
                else:
                    for p in manager.list_panels():
                        print(f"  {p['name']}: {'Connected' if p['connected'] else 'Disconnected'}")
            
            else:
                print("  Unknown command. Type 'quit' to exit.")
        
        except KeyboardInterrupt:
            print("\nUse 'quit' to exit.")
        except Exception as e:
            print(f"  Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Panel Control CLI - Control LED panels from command line",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s scan                          # Find nearby panels
  %(prog)s connect 68:D0:1D:58:69:76     # Connect to panel
  %(prog)s brightness 68:D0:1D:58:69:76 80  # Set 80%% brightness
  %(prog)s send 68:D0:1D:58:69:76 image.png # Send image
  %(prog)s interactive                   # Interactive mode
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    # scan
    p_scan = subparsers.add_parser('scan', help='Scan for panels')
    p_scan.add_argument('--timeout', type=float, default=10.0, help='Scan timeout (default: 10)')
    
    # connect
    p_connect = subparsers.add_parser('connect', help='Connect to panel')
    p_connect.add_argument('mac', help='Panel MAC address')
    p_connect.add_argument('--name', help='Friendly name for panel')
    
    # disconnect
    p_disconnect = subparsers.add_parser('disconnect', help='Disconnect from panel')
    p_disconnect.add_argument('mac', help='Panel MAC address')
    
    # brightness
    p_brightness = subparsers.add_parser('brightness', help='Set brightness')
    p_brightness.add_argument('mac', help='Panel MAC address')
    p_brightness.add_argument('value', type=int, help='Brightness 0-100')
    
    # rotate
    p_rotate = subparsers.add_parser('rotate', help='Set rotation')
    p_rotate.add_argument('mac', help='Panel MAC address')
    p_rotate.add_argument('degrees', type=int, choices=[0, 90, 180, 270], help='Rotation degrees')
    
    # send
    p_send = subparsers.add_parser('send', help='Send image')
    p_send.add_argument('mac', help='Panel MAC address')
    p_send.add_argument('image', help='Image file path')
    
    # identify
    p_identify = subparsers.add_parser('identify', help='Flash identification number')
    p_identify.add_argument('mac', help='Panel MAC address')
    p_identify.add_argument('number', type=int, nargs='?', default=1, help='Number to display (default: 1)')
    
    # save
    p_save = subparsers.add_parser('save', help='Save as startup image')
    p_save.add_argument('mac', help='Panel MAC address')
    
    # status
    p_status = subparsers.add_parser('status', help='Show panel status')
    p_status.add_argument('mac', nargs='?', help='Panel MAC address (optional)')
    
    # interactive
    p_interactive = subparsers.add_parser('interactive', help='Interactive mode')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(0)
    
    # Map commands to functions
    commands = {
        'scan': cmd_scan,
        'connect': cmd_connect,
        'disconnect': cmd_disconnect,
        'brightness': cmd_brightness,
        'rotate': cmd_rotate,
        'send': cmd_send,
        'identify': cmd_identify,
        'save': cmd_save,
        'status': cmd_status,
        'interactive': cmd_interactive,
    }
    
    try:
        asyncio.run(commands[args.command](args))
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(0)


if __name__ == '__main__':
    main()

