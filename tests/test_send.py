#!/usr/bin/env python3
"""
Test Panel Send

Test sending a simple pattern to a panel to verify communication.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.core import PanelController, scan_for_panels, setup_logging
from panel_hopper.config import load_config
from panel_hopper.graphics import create_panel_image, to_png_bytes
from PIL import ImageDraw


def create_test_pattern() -> bytes:
    """Create a simple test pattern (colored quadrants)."""
    img = create_panel_image('black')
    draw = ImageDraw.Draw(img)
    
    # Four colored quadrants
    draw.rectangle([0, 0, 15, 15], fill=(255, 0, 0))     # Top-left: Red
    draw.rectangle([16, 0, 31, 15], fill=(0, 255, 0))    # Top-right: Green
    draw.rectangle([0, 16, 15, 31], fill=(0, 0, 255))    # Bottom-left: Blue
    draw.rectangle([16, 16, 31, 31], fill=(255, 255, 0)) # Bottom-right: Yellow
    
    return to_png_bytes(img)


async def test_send_to_first_panel():
    """Find first available panel and send test pattern."""
    print("\n" + "=" * 50)
    print("   Panel Send Test")
    print("=" * 50)
    
    # Try to get panel from config first
    config = load_config()
    enabled = config.get_enabled_panels()
    
    if enabled:
        panel = enabled[0]
        mac = panel.mac
        name = panel.name
        print(f"\nUsing configured panel: {name}")
    else:
        # Scan for panels
        print("\nNo configured panels, scanning...")
        discovered = await scan_for_panels(timeout=5.0)
        
        if not discovered:
            print("  ✗ No panels found!")
            print("    Run 'python cli/scan.py' to find panels")
            return False
        
        mac, name = discovered[0]
        print(f"  Found: {name} ({mac})")
    
    print(f"\nCreating test pattern...")
    png_bytes = create_test_pattern()
    print(f"  Pattern size: {len(png_bytes)} bytes")
    
    print(f"\nSending to {name}...")
    controller = PanelController(timeout=30.0, retries=2)
    success, message = await controller.send_to_panel(mac, png_bytes, name)
    
    if success:
        print(f"\n  ✓ SUCCESS!")
        print(f"    Panel should show colored quadrants:")
        print(f"    ┌───────┬───────┐")
        print(f"    │  RED  │ GREEN │")
        print(f"    ├───────┼───────┤")
        print(f"    │ BLUE  │YELLOW │")
        print(f"    └───────┴───────┘")
    else:
        print(f"\n  ✗ FAILED: {message}")
        print("\n  Troubleshooting:")
        print("    - Move closer to the panel")
        print("    - Power cycle the panel")
        print("    - Try running as Administrator")
    
    print("\n" + "=" * 50)
    return success


if __name__ == "__main__":
    setup_logging()
    asyncio.run(test_send_to_first_panel())

