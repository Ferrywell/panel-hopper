#!/usr/bin/env python3
"""
Test Graphics Module

Test image processing and text rendering without BLE.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.graphics import (
    create_panel_image,
    create_grid_image,
    create_text_image,
    create_dot_matrix_text,
    resize_for_panel,
    resize_for_grid,
    split_for_grid,
    to_png_bytes,
    PANEL_SIZE,
    GRID_SIZE,
)


def test_panel_image():
    """Test creating basic panel images."""
    print("\n[1] Testing panel image creation...")
    
    img = create_panel_image('black')
    assert img.size == (PANEL_SIZE, PANEL_SIZE), "Wrong panel size"
    assert img.mode == 'RGB', "Wrong mode"
    print(f"  ✓ Created {img.size} panel image")
    
    img = create_panel_image('red')
    assert img.getpixel((0, 0)) == (255, 0, 0), "Wrong color"
    print(f"  ✓ Color fill works")


def test_grid_image():
    """Test creating grid images."""
    print("\n[2] Testing grid image creation...")
    
    img = create_grid_image()
    assert img.size == (GRID_SIZE, GRID_SIZE), "Wrong grid size"
    print(f"  ✓ Created {img.size} grid image")


def test_text_images():
    """Test text rendering."""
    print("\n[3] Testing text rendering...")
    
    img = create_text_image("HI", PANEL_SIZE, PANEL_SIZE, 'orange')
    assert img.size == (PANEL_SIZE, PANEL_SIZE)
    print(f"  ✓ System font text works")
    
    img = create_dot_matrix_text("AB", PANEL_SIZE, PANEL_SIZE, 'amber')
    assert img.size == (PANEL_SIZE, PANEL_SIZE)
    print(f"  ✓ Dot matrix text works")
    
    img = create_dot_matrix_text("HELLO", GRID_SIZE, GRID_SIZE, 'green')
    assert img.size == (GRID_SIZE, GRID_SIZE)
    print(f"  ✓ Large dot matrix text works")


def test_resize():
    """Test image resizing."""
    print("\n[4] Testing image resize...")
    
    # Create a test image
    from PIL import Image
    test_img = Image.new('RGB', (100, 100), (255, 0, 0))
    
    resized = resize_for_panel(test_img, mode='fill')
    assert resized.size == (PANEL_SIZE, PANEL_SIZE)
    print(f"  ✓ resize_for_panel works")
    
    resized = resize_for_grid(test_img, mode='fill')
    assert resized.size == (GRID_SIZE, GRID_SIZE)
    print(f"  ✓ resize_for_grid works")


def test_grid_split():
    """Test grid splitting."""
    print("\n[5] Testing grid split...")
    
    # Create a gradient image
    from PIL import Image
    img = Image.new('RGB', (GRID_SIZE, GRID_SIZE))
    for x in range(GRID_SIZE):
        for y in range(GRID_SIZE):
            img.putpixel((x, y), (x * 4, y * 4, 128))
    
    parts = split_for_grid(img)
    
    assert len(parts) == 4, "Should have 4 parts"
    assert 'linksboven' in parts
    assert 'rechtsboven' in parts
    assert 'linksonder' in parts
    assert 'rechtsonder' in parts
    
    for name, part in parts.items():
        assert part.size == (PANEL_SIZE, PANEL_SIZE), f"{name} wrong size"
    
    print(f"  ✓ Grid splits into 4 parts correctly")


def test_png_bytes():
    """Test PNG conversion."""
    print("\n[6] Testing PNG conversion...")
    
    img = create_panel_image('blue')
    png_bytes = to_png_bytes(img)
    
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 0
    assert png_bytes[:8] == b'\x89PNG\r\n\x1a\n', "Not valid PNG"
    
    print(f"  ✓ PNG conversion works ({len(png_bytes)} bytes)")


def test_save_examples():
    """Generate example images for visual inspection."""
    print("\n[7] Saving example images...")
    
    output_dir = Path("tests/output")
    output_dir.mkdir(exist_ok=True)
    
    # Panel text
    img = create_text_image("HOP", PANEL_SIZE, PANEL_SIZE, 'orange')
    img.save(output_dir / "panel_text.png")
    print(f"  ✓ Saved panel_text.png")
    
    # Dot matrix
    img = create_dot_matrix_text("STOP", GRID_SIZE, GRID_SIZE, 'amber')
    img.save(output_dir / "dot_matrix.png")
    print(f"  ✓ Saved dot_matrix.png")
    
    # Grid split demo
    parts = split_for_grid(img)
    for name, part in parts.items():
        part.save(output_dir / f"grid_{name}.png")
    print(f"  ✓ Saved grid split images")


def main():
    print("\n" + "=" * 50)
    print("   Graphics Module Tests")
    print("=" * 50)
    
    try:
        test_panel_image()
        test_grid_image()
        test_text_images()
        test_resize()
        test_grid_split()
        test_png_bytes()
        test_save_examples()
        
        print("\n" + "=" * 50)
        print("   All tests passed! ✓")
        print("=" * 50)
        print("\nCheck tests/output/ for generated images.")
        
    except AssertionError as e:
        print(f"\n  ✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n  ✗ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

