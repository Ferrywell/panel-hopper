#!/usr/bin/env python3
"""
Send to Grid Panels

Specialized tool for 2x2 grid operations.
Sends images or text split across 4 panels as a 64x64 display.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.core import PanelController, setup_logging
from panel_hopper.config import load_config
from panel_hopper.graphics import (
    resize_for_grid,
    create_dot_matrix_text,
    create_text_image,
    split_for_grid,
    to_png_bytes,
    GRID_SIZE,
)


def list_assets():
    """List available images in assets folder."""
    assets_dir = Path("assets")
    examples_dir = assets_dir / "examples"
    uploads_dir = assets_dir / "uploads"
    
    images = []
    extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
    
    for folder in [examples_dir, uploads_dir, assets_dir]:
        if folder.exists():
            for f in folder.iterdir():
                if f.is_file() and f.suffix.lower() in extensions:
                    images.append(f)
    
    return images


async def interactive_mode():
    """Interactive mode for grid operations."""
    print("\n" + "=" * 50)
    print("   Panel Hopper - Grid Display (64x64)")
    print("=" * 50)
    
    config = load_config()
    grid_panels = config.get_grid_panels()
    
    if len(grid_panels) < 4:
        print(f"\n⚠️  Grid requires 4 panels, only {len(grid_panels)} configured.")
        print("Run 'python cli/setup.py' to configure grid layout.")
        print("\nCurrent grid config:")
        for pos in ['linksboven', 'rechtsboven', 'linksonder', 'rechtsonder']:
            panel = grid_panels.get(pos)
            if panel:
                print(f"  {pos}: {panel.name}")
            else:
                print(f"  {pos}: (not set)")
        return
    
    print("\nGrid layout:")
    print("  ┌─────────────┬─────────────┐")
    print(f"  │ {grid_panels.get('linksboven', type('', (), {'name': '?'})()).name:^11} │ {grid_panels.get('rechtsboven', type('', (), {'name': '?'})()).name:^11} │")
    print("  ├─────────────┼─────────────┤")
    print(f"  │ {grid_panels.get('linksonder', type('', (), {'name': '?'})()).name:^11} │ {grid_panels.get('rechtsonder', type('', (), {'name': '?'})()).name:^11} │")
    print("  └─────────────┴─────────────┘")
    
    print("\nWhat do you want to send?")
    print("  [1] Image (from assets)")
    print("  [2] Text")
    print("  [0] Cancel")
    
    choice = input("\nChoice: ").strip()
    
    if choice == '1':
        # Image mode
        images = list_assets()
        
        if not images:
            print("\nNo images found in assets/")
            return
        
        print("\nAvailable images:")
        for i, img in enumerate(images, 1):
            print(f"  [{i}] {img.name}")
        
        try:
            idx = int(input("\nSelect image: ").strip()) - 1
            if 0 <= idx < len(images):
                await send_grid_image(images[idx])
            else:
                print("Invalid selection.")
        except ValueError:
            print("Invalid input.")
    
    elif choice == '2':
        # Text mode
        text = input("\nEnter text: ").strip()
        if not text:
            print("No text entered.")
            return
        
        color = input("Color (orange/amber/green/red) [orange]: ").strip() or 'orange'
        dot_matrix = input("Use dot-matrix style? (Y/n): ").strip().lower() != 'n'
        
        await send_grid_text(text, color, dot_matrix)


async def send_grid_image(image_path: Path):
    """Send image to grid panels."""
    config = load_config()
    grid_panels = config.get_grid_panels()
    
    print(f"\nPreparing 64x64 grid image from {image_path.name}...")
    img = resize_for_grid(image_path)
    parts = split_for_grid(img)
    
    # Save preview
    preview_path = Path("grid_preview.png")
    img.save(preview_path)
    print(f"Preview saved: {preview_path}")
    
    await send_parts(grid_panels, parts)


async def send_grid_text(text: str, color: str, dot_matrix: bool):
    """Send text to grid panels."""
    config = load_config()
    grid_panels = config.get_grid_panels()
    
    print(f"\nCreating 64x64 text image...")
    
    if dot_matrix:
        img = create_dot_matrix_text(text, GRID_SIZE, GRID_SIZE, color)
    else:
        img = create_text_image(text, GRID_SIZE, GRID_SIZE, color, font_size=28)
    
    parts = split_for_grid(img)
    
    # Save preview
    preview_path = Path("grid_preview.png")
    img.save(preview_path)
    print(f"Preview saved: {preview_path}")
    
    await send_parts(grid_panels, parts)


async def send_parts(grid_panels: dict, parts: dict):
    """Send split image parts to grid panels."""
    controller = PanelController()
    
    # Order optimized for BLE stability
    send_order = ['rechtsonder', 'linksonder', 'rechtsboven', 'linksboven']
    
    print("\nSending to grid:")
    success_count = 0
    
    for position in send_order:
        if position not in grid_panels:
            print(f"  ⚠️  {position}: not configured")
            continue
        
        panel = grid_panels[position]
        png_bytes = to_png_bytes(parts[position])
        
        success, message = await controller.send_to_panel(panel.mac, png_bytes, position)
        
        if success:
            print(f"  ✓ {position} ({panel.name})")
            success_count += 1
        else:
            print(f"  ❌ {position}: {message}")
    
    print(f"\n{'=' * 40}")
    print(f"Result: {success_count}/4 panels updated")


async def main():
    """Main entry point."""
    setup_logging()
    
    if len(sys.argv) < 2:
        await interactive_mode()
        return
    
    arg = sys.argv[1]
    
    # Check if it's an image file
    image_path = Path(arg)
    if not image_path.exists():
        assets_path = Path("assets") / arg
        if assets_path.exists():
            image_path = assets_path
        else:
            examples_path = Path("assets/examples") / arg
            if examples_path.exists():
                image_path = examples_path
    
    if image_path.exists():
        await send_grid_image(image_path)
    else:
        # Treat as text
        color = 'orange'
        dot_matrix = '--dot-matrix' in sys.argv
        
        for i, a in enumerate(sys.argv):
            if a == '--color' and i + 1 < len(sys.argv):
                color = sys.argv[i + 1]
        
        await send_grid_text(arg, color, dot_matrix)


def print_usage():
    print("""
Panel Hopper - Grid Display

Send images or text to a 2x2 grid of panels (64x64 total).

Usage:
    python send_grid.py [image or text] [options]

Options:
    --color <name>   Text color (orange, amber, green, red)
    --dot-matrix     Use highway-style dot matrix font
    --help           Show this help

Without arguments, runs in interactive mode.

Examples:
    python send_grid.py                           # Interactive
    python send_grid.py charmander.png            # Image
    python send_grid.py "HOP" --color amber       # Text
    python send_grid.py "STOP" --dot-matrix       # Dot matrix text
""")


if __name__ == "__main__":
    if "--help" in sys.argv:
        print_usage()
    else:
        asyncio.run(main())

