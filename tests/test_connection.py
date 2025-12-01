#!/usr/bin/env python3
"""
Test BLE Connection

Quick test to verify Bluetooth connectivity and panel discovery.
Run this to check if your BLE adapter is working properly.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.core import scan_for_panels, setup_logging


async def test_ble_adapter():
    """Test if BLE adapter is available and working."""
    print("\n" + "=" * 50)
    print("   BLE Adapter Test")
    print("=" * 50)
    
    print("\n[1/3] Checking BLE adapter...")
    
    try:
        from bleak import BleakScanner
        print("  ✓ Bleak library loaded")
    except ImportError:
        print("  ✗ Bleak not installed!")
        print("    Run: pip install bleak")
        return False
    
    print("\n[2/3] Scanning for any BLE devices (3 seconds)...")
    
    try:
        devices = await BleakScanner.discover(timeout=3.0)
        print(f"  ✓ Found {len(devices)} BLE device(s)")
        
        if len(devices) == 0:
            print("\n  ⚠ No devices found. This could mean:")
            print("    - Bluetooth is disabled")
            print("    - No BLE devices nearby")
            print("    - Adapter doesn't support BLE")
    except Exception as e:
        print(f"  ✗ Scan failed: {e}")
        print("\n  Troubleshooting:")
        print("    - Enable Bluetooth in system settings")
        print("    - On Windows, try running as Administrator")
        print("    - Check if your adapter supports BLE 4.0+")
        return False
    
    print("\n[3/3] Scanning for LED panels (5 seconds)...")
    
    panels = await scan_for_panels(timeout=5.0)
    
    if panels:
        print(f"  ✓ Found {len(panels)} panel(s):")
        for mac, name in panels:
            print(f"    • {name} ({mac})")
    else:
        print("  ⚠ No LED panels found")
        print("    Make sure panels are powered on and in range")
    
    print("\n" + "=" * 50)
    print("   Test Complete")
    print("=" * 50)
    
    return True


if __name__ == "__main__":
    setup_logging()
    asyncio.run(test_ble_adapter())

