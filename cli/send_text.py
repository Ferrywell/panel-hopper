#!/usr/bin/env python3
"""
Send Text to Panels

Display text on LED panels using dot-matrix or system fonts.
Supports single panel, all panels, or grid mode (64x64).
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.core import PanelController, setup_logging
from panel_hopper.config import load_config
from panel_hopper.graphics import (
    create_text_image,
    create_dot_matrix_text,
    split_for_grid,
    to_png_bytes,
    PANEL_SIZE,
    GRID_SIZE,
)


async def send_text_single(text: str, panel_name: str, color: str, dot_matrix: bool):
    """Send text to a single panel by name."""
    config = load_config()
    panel = config.get_panel_by_name(panel_name)
    
    if not panel:
        print(f"❌ Panel '{panel_name}' not found.")
        return
    
    print(f"\nCreating text image for {panel.name}...")
    
    if dot_matrix:
        img = create_dot_matrix_text(text, PANEL_SIZE, PANEL_SIZE, color)
    else:
        img = create_text_image(text, PANEL_SIZE, PANEL_SIZE, color)
    
    png_bytes = to_png_bytes(img)
    
    controller = PanelController()
    success, message = await controller.send_to_panel(panel.mac, png_bytes, panel.name)
    
    if success:
        print(f"✓ Sent '{text}' to {panel.name}!")
    else:
        print(f"❌ Failed: {message}")


async def send_text_all(text: str, color: str, dot_matrix: bool):
    """Send same text to all enabled panels."""
    config = load_config()
    enabled = config.get_enabled_panels()
    
    if not enabled:
        print("❌ No enabled panels found.")
        return
    
    print(f"\nCreating text image for {len(enabled)} panel(s)...")
    
    if dot_matrix:
        img = create_dot_matrix_text(text, PANEL_SIZE, PANEL_SIZE, color)
    else:
        img = create_text_image(text, PANEL_SIZE, PANEL_SIZE, color)
    
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


async def send_text_grid(text: str, color: str, dot_matrix: bool):
    """Send text across 4 grid panels (64x64 total)."""
    config = load_config()
    grid_panels = config.get_grid_panels()
    
    if len(grid_panels) < 4:
        print(f"❌ Grid requires 4 panels, only {len(grid_panels)} configured.")
        return
    
    print(f"\nCreating 64x64 grid text image...")
    
    if dot_matrix:
        img = create_dot_matrix_text(text, GRID_SIZE, GRID_SIZE, color)
    else:
        img = create_text_image(text, GRID_SIZE, GRID_SIZE, color, font_size=32)
    
    parts = split_for_grid(img)
    
    # Save preview
    preview_path = Path("grid_preview.png")
    img.save(preview_path)
    print(f"Preview saved: {preview_path}")
    
    controller = PanelController()
    send_order = ['rechtsonder', 'linksonder', 'rechtsboven', 'linksboven']
    
    print("\nSending to grid panels:")
    success_count = 0
    
    for position in send_order:
        if position not in grid_panels:
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


async def interactive_mode():
    """Interactive text input mode."""
    print("\n" + "=" * 50)
    print("   Panel Hopper - Text Sender")
    print("=" * 50)
    
    text = input("\nEnter text to display: ").strip()
    if not text:
        print("No text entered.")
        return
    
    print("\nMode:")
    print("  [1] Send to all enabled panels")
    print("  [2] Send to specific panel")
    print("  [3] Send to grid (64x64)")
    
    mode = input("\nChoice (1-3): ").strip()
    
    color = input("Color (orange/amber/green/red/blue) [orange]: ").strip() or 'orange'
    dot_matrix = input("Use dot-matrix style? (y/N): ").strip().lower() == 'y'
    
    if mode == '2':
        config = load_config()
        print("\nAvailable panels:")
        for p in config.panels.values():
            status = "✓" if p.enabled else "○"
            print(f"  {status} {p.name}")
        
        panel_name = input("\nPanel name: ").strip()
        await send_text_single(text, panel_name, color, dot_matrix)
    
    elif mode == '3':
        await send_text_grid(text, color, dot_matrix)
    
    else:
        await send_text_all(text, color, dot_matrix)


async def main():
    """Main entry point."""
    setup_logging()
    
    if len(sys.argv) < 2:
        await interactive_mode()
        return
    
    text = sys.argv[1]
    
    # Parse options
    color = 'orange'
    dot_matrix = '--dot-matrix' in sys.argv or '--matrix' in sys.argv
    
    for i, arg in enumerate(sys.argv):
        if arg == '--color' and i + 1 < len(sys.argv):
            color = sys.argv[i + 1]
    
    print("\n" + "=" * 50)
    print("   Panel Hopper - Send Text")
    print("=" * 50)
    print(f"\nText: '{text}'")
    print(f"Color: {color}")
    print(f"Style: {'dot-matrix' if dot_matrix else 'system font'}")
    
    if '--panel' in sys.argv:
        idx = sys.argv.index('--panel')
        if idx + 1 < len(sys.argv):
            await send_text_single(text, sys.argv[idx + 1], color, dot_matrix)
    elif '--grid' in sys.argv:
        await send_text_grid(text, color, dot_matrix)
    else:
        await send_text_all(text, color, dot_matrix)


def print_usage():
    print("""
Panel Hopper - Send Text

Usage:
    python send_text.py [text] [options]

Options:
    --panel <name>   Send to specific panel
    --grid           Send across 4 grid panels (64x64)
    --color <name>   Text color (orange, amber, green, red, blue)
    --dot-matrix     Use highway-style dot matrix font
    --help           Show this help

Without arguments, runs in interactive mode.

Examples:
    python send_text.py "HOP"
    python send_text.py "HELLO" --grid
    python send_text.py "OK" --panel simon --color green
    python send_text.py "STOP" --dot-matrix --color amber
""")


if __name__ == "__main__":
    if "--help" in sys.argv:
        print_usage()
    else:
        asyncio.run(main())

