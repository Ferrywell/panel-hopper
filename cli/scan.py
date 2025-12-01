#!/usr/bin/env python3
"""
Scan for LED Panels

Scans for BLE devices that match the LED panel naming pattern (LED_BLE_*)
and optionally adds them to the configuration.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.core import scan_for_panels, setup_logging
from panel_hopper.config import load_config, save_config


async def main():
    """Scan for panels and display results."""
    setup_logging()
    
    print("\n" + "=" * 50)
    print("   Panel Hopper - BLE Scanner")
    print("=" * 50)
    
    # Parse arguments
    timeout = 10.0
    save = "--save" in sys.argv
    
    for i, arg in enumerate(sys.argv):
        if arg == "--timeout" and i + 1 < len(sys.argv):
            try:
                timeout = float(sys.argv[i + 1])
            except ValueError:
                pass
    
    print(f"\nScanning for {timeout} seconds...")
    print("Looking for devices starting with 'LED_BLE_'\n")
    
    try:
        discovered = await scan_for_panels(timeout=timeout)
    except Exception as e:
        print(f"\n❌ Scan failed: {e}")
        print("\nTroubleshooting:")
        print("  - Ensure Bluetooth is enabled")
        print("  - Check that your BLE adapter supports scanning")
        print("  - Try running as Administrator (Windows)")
        return
    
    if not discovered:
        print("\n⚠️  No panels found.")
        print("\nMake sure:")
        print("  - Panels are powered on")
        print("  - Panels are in range (within ~10 meters)")
        print("  - No other app is connected to them")
        return
    
    print(f"\n✓ Found {len(discovered)} panel(s):\n")
    for mac, name in discovered:
        print(f"  • {name}")
        print(f"    MAC: {mac}\n")
    
    if save:
        # Load existing config and add new panels
        config = load_config()
        added = 0
        
        for mac, name in discovered:
            if mac not in config.panels:
                config.add_panel(mac, name)
                added += 1
                print(f"  ➕ Added: {name}")
        
        if added > 0:
            save_config(config)
            print(f"\n✓ Added {added} new panel(s) to config")
        else:
            print("\n(All panels already in config)")
    else:
        print("Tip: Run with --save to add panels to config")


def print_usage():
    print("""
Panel Hopper - BLE Scanner

Usage:
    python scan.py [options]

Options:
    --timeout <seconds>  Scan duration (default: 10)
    --save               Add discovered panels to config
    --help               Show this help

Examples:
    python scan.py
    python scan.py --timeout 15
    python scan.py --save
""")


if __name__ == "__main__":
    if "--help" in sys.argv:
        print_usage()
    else:
        asyncio.run(main())

