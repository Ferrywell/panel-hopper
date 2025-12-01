#!/usr/bin/env python3
"""
Interactive Panel Setup

Connects to each panel one by one, displays a test pattern,
and asks the user to name each panel.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.core import scan_for_panels, PanelController, setup_logging
from panel_hopper.config import load_config, save_config, PanelConfig
from panel_hopper.graphics import create_text_image, to_png_bytes


async def identify_panel(controller: PanelController, mac: str, number: int) -> bool:
    """Send identification number to a panel."""
    # Create image with panel number
    img = create_text_image(str(number), color='orange', font_size=24)
    png_bytes = to_png_bytes(img)
    
    success, message = await controller.send_to_panel(mac, png_bytes)
    return success


async def main():
    """Interactive panel setup."""
    setup_logging()
    
    print("\n" + "=" * 50)
    print("   Panel Hopper - Interactive Setup")
    print("=" * 50)
    
    # Step 1: Scan for panels
    print("\nStep 1: Scanning for panels...")
    print("(Make sure all panels are powered on)\n")
    
    try:
        discovered = await scan_for_panels(timeout=10.0)
    except Exception as e:
        print(f"❌ Scan failed: {e}")
        return
    
    if not discovered:
        print("❌ No panels found.")
        return
    
    print(f"\n✓ Found {len(discovered)} panel(s)")
    
    # Step 2: Identify each panel
    print("\n" + "-" * 50)
    print("Step 2: Panel Identification")
    print("-" * 50)
    print("\nI'll connect to each panel and show a number.")
    print("Tell me what name you want to give each panel.\n")
    
    controller = PanelController(timeout=30.0, delay=0.15, retries=2)
    config = load_config()
    
    for i, (mac, ble_name) in enumerate(discovered, 1):
        print(f"\n--- Panel {i}/{len(discovered)} ---")
        print(f"BLE Name: {ble_name}")
        print(f"MAC: {mac}")
        
        # Check if already configured
        existing = config.get_panel_by_mac(mac)
        if existing:
            print(f"Current name: {existing.name}")
            update = input("Update this panel? (y/N): ").strip().lower()
            if update != 'y':
                print("Skipped.")
                continue
        
        print(f"\nConnecting and displaying '{i}'...")
        
        success = await identify_panel(controller, mac, i)
        
        if success:
            print("✓ Panel should now show the number!")
            
            # Ask for name
            while True:
                name = input(f"Enter name for this panel (or 's' to skip): ").strip()
                
                if name.lower() == 's':
                    print("Skipped.")
                    break
                
                if not name:
                    print("Please enter a name or 's' to skip.")
                    continue
                
                # Check for duplicate names
                existing_name = config.get_panel_by_name(name)
                if existing_name and existing_name.mac != mac:
                    print(f"⚠️  Name '{name}' already used for another panel.")
                    continue
                
                # Save panel
                if mac in config.panels:
                    config.panels[mac].name = name
                else:
                    config.add_panel(mac, name)
                
                config.panels[mac].order = i
                
                print(f"✓ Saved as '{name}'")
                break
        else:
            print("❌ Failed to connect to this panel.")
            skip = input("Skip and continue? (Y/n): ").strip().lower()
            if skip == 'n':
                print("Setup cancelled.")
                return
    
    # Step 3: Grid configuration
    print("\n" + "-" * 50)
    print("Step 3: Grid Configuration (Optional)")
    print("-" * 50)
    print("\nDo you have 4 panels arranged in a 2x2 grid?")
    
    setup_grid = input("Configure grid layout? (y/N): ").strip().lower()
    
    if setup_grid == 'y':
        print("\nEnter the name of the panel for each position:")
        print("(Leave empty to skip a position)\n")
        
        positions = ['linksboven', 'rechtsboven', 'linksonder', 'rechtsonder']
        position_names = {
            'linksboven': 'Top-left',
            'rechtsboven': 'Top-right', 
            'linksonder': 'Bottom-left',
            'rechtsonder': 'Bottom-right'
        }
        
        for pos in positions:
            name = input(f"  {position_names[pos]} ({pos}): ").strip()
            if name:
                panel = config.get_panel_by_name(name)
                if panel:
                    setattr(config.grid, pos, panel.mac)
                    panel.grid_position = pos
                    print(f"    ✓ Set to {panel.name} ({panel.mac})")
                else:
                    print(f"    ⚠️  Panel '{name}' not found, skipped.")
    
    # Save configuration
    save_config(config)
    
    print("\n" + "=" * 50)
    print("   Setup Complete!")
    print("=" * 50)
    print(f"\nConfigured {len(config.panels)} panel(s)")
    
    if config.grid.linksboven or config.grid.rechtsboven:
        print("Grid layout configured!")
    
    print("\nYou can now use:")
    print("  python cli/send_image.py <image>")
    print("  python cli/send_text.py <text>")
    print("  python web/server.py")


if __name__ == "__main__":
    asyncio.run(main())

