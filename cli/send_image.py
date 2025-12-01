#!/usr/bin/env python3
"""
Send Image to Panels

Send an image file to one or more LED panels.
Supports single panel, all enabled panels, or grid mode.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.core import PanelController, setup_logging
from panel_hopper.config import load_config
from panel_hopper.graphics import (
    resize_for_panel,
    resize_for_grid,
    split_for_grid,
    to_png_bytes,
)


async def send_single(image_path: Path, panel_name: str):
    """Send image to a single panel by name."""
    config = load_config()
    panel = config.get_panel_by_name(panel_name)
    
    if not panel:
        print(f"❌ Panel '{panel_name}' not found.")
        print("\nAvailable panels:")
        for p in config.panels.values():
            print(f"  • {p.name} ({p.mac})")
        return
    
    print(f"\nPreparing image for {panel.name}...")
    img = resize_for_panel(image_path)
    png_bytes = to_png_bytes(img)
    
    print(f"Sending to {panel.name}...")
    controller = PanelController()
    success, message = await controller.send_to_panel(panel.mac, png_bytes, panel.name)
    
    if success:
        print(f"✓ Sent to {panel.name}!")
    else:
        print(f"❌ Failed: {message}")


async def send_all(image_path: Path):
    """Send image to all enabled panels."""
    config = load_config()
    enabled = config.get_enabled_panels()
    
    if not enabled:
        print("❌ No enabled panels found.")
        print("Run 'python cli/setup.py' to configure panels.")
        return
    
    print(f"\nPreparing image for {len(enabled)} panel(s)...")
    img = resize_for_panel(image_path)
    png_bytes = to_png_bytes(img)
    
    controller = PanelController()
    macs = [(p.mac, p.name) for p in enabled]
    
    results = await controller.send_same_to_all(macs, png_bytes)
    
    print("\nResults:")
    success_count = 0
    for mac, success, message in results:
        panel = config.get_panel_by_mac(mac)
        name = panel.name if panel else mac
        if success:
            print(f"  ✓ {name}")
            success_count += 1
        else:
            print(f"  ❌ {name}: {message}")
    
    print(f"\n{success_count}/{len(enabled)} panels updated.")


async def send_grid(image_path: Path):
    """Send image split across 4 grid panels (64x64 total)."""
    config = load_config()
    grid_panels = config.get_grid_panels()
    
    if len(grid_panels) < 4:
        print(f"❌ Grid requires 4 panels, only {len(grid_panels)} configured.")
        print("Run 'python cli/setup.py' to configure grid layout.")
        return
    
    print(f"\nPreparing 64x64 grid image...")
    img = resize_for_grid(image_path)
    parts = split_for_grid(img)
    
    # Save preview
    preview_path = Path("grid_preview.png")
    img.save(preview_path)
    print(f"Preview saved: {preview_path}")
    
    controller = PanelController()
    
    # Send order for stability
    send_order = ['rechtsonder', 'linksonder', 'rechtsboven', 'linksboven']
    
    print("\nSending to grid panels:")
    success_count = 0
    
    for position in send_order:
        if position not in grid_panels:
            print(f"  ⚠️  {position}: not configured")
            continue
        
        panel = grid_panels[position]
        png_bytes = to_png_bytes(parts[position])
        
        success, message = await controller.send_to_panel(panel.mac, png_bytes, position)
        
        if success:
            print(f"  ✓ {position}")
            success_count += 1
        else:
            print(f"  ❌ {position}: {message}")
    
    print(f"\n{success_count}/4 grid panels updated.")


async def main():
    """Main entry point."""
    setup_logging()
    
    if len(sys.argv) < 2:
        print_usage()
        return
    
    image_path = Path(sys.argv[1])
    
    if not image_path.exists():
        # Check assets folder
        assets_path = Path("assets") / image_path.name
        if assets_path.exists():
            image_path = assets_path
        else:
            examples_path = Path("assets/examples") / image_path.name
            if examples_path.exists():
                image_path = examples_path
            else:
                print(f"❌ Image not found: {image_path}")
                return
    
    print("\n" + "=" * 50)
    print("   Panel Hopper - Send Image")
    print("=" * 50)
    print(f"\nImage: {image_path}")
    
    # Parse mode
    if "--panel" in sys.argv:
        idx = sys.argv.index("--panel")
        if idx + 1 < len(sys.argv):
            await send_single(image_path, sys.argv[idx + 1])
    elif "--grid" in sys.argv:
        await send_grid(image_path)
    elif "--all" in sys.argv:
        await send_all(image_path)
    else:
        # Default: send to all enabled
        await send_all(image_path)


def print_usage():
    print("""
Panel Hopper - Send Image

Usage:
    python send_image.py <image> [options]

Options:
    --panel <name>   Send to specific panel by name
    --all            Send to all enabled panels (default)
    --grid           Send split across 4 grid panels (64x64)
    --help           Show this help

Examples:
    python send_image.py assets/examples/charmander.png
    python send_image.py my_image.png --panel simon
    python send_image.py logo.png --grid
""")


if __name__ == "__main__":
    if "--help" in sys.argv:
        print_usage()
    else:
        asyncio.run(main())

