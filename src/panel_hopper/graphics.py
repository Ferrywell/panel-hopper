"""
Graphics Module - Image processing and text rendering for LED panels.

Supports:
- Single panel (32x32 pixels)
- 2x2 Grid (64x64 pixels across 4 panels)
- Dot-matrix style text (highway sign aesthetic)
- Image resizing with various fit modes
"""

from io import BytesIO
from pathlib import Path
from typing import Literal, Union
from PIL import Image, ImageDraw, ImageFont

# =============================================================================
# Constants
# =============================================================================

PANEL_SIZE = 32
GRID_SIZE = 64  # 2x2 grid

# Common colors for LED panels
COLORS = {
    'black': (0, 0, 0),
    'white': (255, 255, 255),
    'red': (255, 0, 0),
    'green': (0, 255, 0),
    'blue': (0, 0, 255),
    'yellow': (255, 255, 0),
    'orange': (255, 153, 0),    # #ff9900
    'cyan': (0, 255, 255),
    'magenta': (255, 0, 255),
    'amber': (255, 191, 0),     # Highway sign color
    'purple': (128, 0, 255),
}

# Grid positions with their pixel coordinates
GRID_POSITIONS = {
    'linksboven': (0, 0),      # Top-left
    'rechtsboven': (32, 0),    # Top-right
    'linksonder': (0, 32),     # Bottom-left
    'rechtsonder': (32, 32),   # Bottom-right
}


# =============================================================================
# Dot Matrix Font (5x7 pixel characters - highway style)
# =============================================================================

DOT_MATRIX_FONT = {
    'A': [" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    'B': ["#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "],
    'C': [" ### ", "#   #", "#    ", "#    ", "#    ", "#   #", " ### "],
    'D': ["#### ", "#   #", "#   #", "#   #", "#   #", "#   #", "#### "],
    'E': ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"],
    'F': ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "],
    'G': [" ### ", "#   #", "#    ", "# ###", "#   #", "#   #", " ### "],
    'H': ["#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    'I': ["#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "#####"],
    'J': ["#####", "    #", "    #", "    #", "    #", "#   #", " ### "],
    'K': ["#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"],
    'L': ["#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"],
    'M': ["#   #", "## ##", "# # #", "#   #", "#   #", "#   #", "#   #"],
    'N': ["#   #", "##  #", "# # #", "#  ##", "#   #", "#   #", "#   #"],
    'O': [" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    'P': ["#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "],
    'Q': [" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"],
    'R': ["#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"],
    'S': [" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "],
    'T': ["#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "],
    'U': ["#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    'V': ["#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "],
    'W': ["#   #", "#   #", "#   #", "#   #", "# # #", "## ##", "#   #"],
    'X': ["#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"],
    'Y': ["#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "],
    'Z': ["#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"],
    '0': [" ### ", "#   #", "#  ##", "# # #", "##  #", "#   #", " ### "],
    '1': ["  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", "#####"],
    '2': [" ### ", "#   #", "    #", "  ## ", " #   ", "#    ", "#####"],
    '3': [" ### ", "#   #", "    #", "  ## ", "    #", "#   #", " ### "],
    '4': ["#   #", "#   #", "#   #", "#####", "    #", "    #", "    #"],
    '5': ["#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "],
    '6': [" ### ", "#    ", "#    ", "#### ", "#   #", "#   #", " ### "],
    '7': ["#####", "    #", "   # ", "  #  ", "  #  ", "  #  ", "  #  "],
    '8': [" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "],
    '9': [" ### ", "#   #", "#   #", " ####", "    #", "    #", " ### "],
    ' ': ["     ", "     ", "     ", "     ", "     ", "     ", "     "],
    '.': ["     ", "     ", "     ", "     ", "     ", " ##  ", " ##  "],
    ',': ["     ", "     ", "     ", "     ", "  #  ", "  #  ", " #   "],
    '!': ["  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "     ", "  #  "],
    '?': [" ### ", "#   #", "    #", "  ## ", "  #  ", "     ", "  #  "],
    ':': ["     ", "  #  ", "  #  ", "     ", "  #  ", "  #  ", "     "],
    '-': ["     ", "     ", "     ", "#####", "     ", "     ", "     "],
    '+': ["     ", "  #  ", "  #  ", "#####", "  #  ", "  #  ", "     "],
    '/': ["    #", "   # ", "  #  ", "  #  ", " #   ", "#    ", "#    "],
    '>': ["#    ", " #   ", "  #  ", "   # ", "  #  ", " #   ", "#    "],
    '<': ["    #", "   # ", "  #  ", " #   ", "  #  ", "   # ", "    #"],
    '=': ["     ", "     ", "#####", "     ", "#####", "     ", "     "],
    '_': ["     ", "     ", "     ", "     ", "     ", "     ", "#####"],
    '(': ["  #  ", " #   ", "#    ", "#    ", "#    ", " #   ", "  #  "],
    ')': ["  #  ", "   # ", "    #", "    #", "    #", "   # ", "  #  "],
}

CHAR_WIDTH = 5
CHAR_HEIGHT = 7
CHAR_SPACING = 1


# =============================================================================
# Color Helpers
# =============================================================================

def get_color(color: Union[str, tuple]) -> tuple:
    """Convert color name, hex, or tuple to RGB tuple."""
    if isinstance(color, tuple):
        return color
    if isinstance(color, str):
        # Handle hex colors like #ff9900
        if color.startswith('#'):
            hex_color = color.lstrip('#')
            if len(hex_color) == 6:
                return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        return COLORS.get(color.lower(), (255, 153, 0))  # Default: #ff9900
    return (255, 153, 0)


# =============================================================================
# Image Creation
# =============================================================================

def create_panel_image(color: Union[str, tuple] = 'black') -> Image.Image:
    """Create a blank 32x32 panel image."""
    return Image.new('RGB', (PANEL_SIZE, PANEL_SIZE), get_color(color))


def create_grid_image(color: Union[str, tuple] = 'black') -> Image.Image:
    """Create a blank 64x64 grid image (for 2x2 panels)."""
    return Image.new('RGB', (GRID_SIZE, GRID_SIZE), get_color(color))


# =============================================================================
# Image Resizing
# =============================================================================

def resize_image(
    img: Union[Image.Image, Path, str],
    width: int,
    height: int,
    mode: Literal['fit', 'fill', 'stretch'] = 'fill'
) -> Image.Image:
    """
    Resize an image to exact dimensions.
    
    Modes:
    - fit: Scale to fit within bounds, add black bars if needed
    - fill: Scale and crop to fill exactly (no bars, may crop)
    - stretch: Stretch to exact size (may distort)
    """
    if isinstance(img, (Path, str)):
        img = Image.open(img)
    
    img = img.convert('RGB')
    
    if mode == 'stretch':
        return img.resize((width, height), Image.Resampling.LANCZOS)
    
    elif mode == 'fill':
        # Scale and center crop to fill exactly
        src_ratio = img.width / img.height
        dst_ratio = width / height
        
        if src_ratio > dst_ratio:
            new_height = height
            new_width = int(height * src_ratio)
        else:
            new_width = width
            new_height = int(width / src_ratio)
        
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Center crop
        left = (new_width - width) // 2
        top = (new_height - height) // 2
        return img.crop((left, top, left + width, top + height))
    
    else:  # fit
        # Scale to fit, add black bars
        src_ratio = img.width / img.height
        dst_ratio = width / height
        
        if src_ratio > dst_ratio:
            new_width = width
            new_height = int(width / src_ratio)
        else:
            new_height = height
            new_width = int(height * src_ratio)
        
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Create black background and paste centered
        result = Image.new('RGB', (width, height), (0, 0, 0))
        x = (width - new_width) // 2
        y = (height - new_height) // 2
        result.paste(img, (x, y))
        return result


def resize_for_panel(
    img: Union[Image.Image, Path, str],
    mode: Literal['fit', 'fill', 'stretch'] = 'fill'
) -> Image.Image:
    """Resize image for a single 32x32 panel."""
    return resize_image(img, PANEL_SIZE, PANEL_SIZE, mode)


def resize_for_grid(
    img: Union[Image.Image, Path, str],
    mode: Literal['fit', 'fill', 'stretch'] = 'fill'
) -> Image.Image:
    """Resize image for 64x64 grid (2x2 panels)."""
    return resize_image(img, GRID_SIZE, GRID_SIZE, mode)


# =============================================================================
# Grid Splitting
# =============================================================================

def split_for_grid(img: Image.Image) -> dict[str, Image.Image]:
    """
    Split a 64x64 image into 4 panel images.
    
    Returns:
        Dict with keys: linksboven, rechtsboven, linksonder, rechtsonder
    """
    if img.size != (GRID_SIZE, GRID_SIZE):
        img = resize_for_grid(img)
    
    return {
        'linksboven': img.crop((0, 0, 32, 32)),
        'rechtsboven': img.crop((32, 0, 64, 32)),
        'linksonder': img.crop((0, 32, 32, 64)),
        'rechtsonder': img.crop((32, 32, 64, 64)),
    }


# =============================================================================
# Dot Matrix Text Rendering
# =============================================================================

def get_text_width(text: str) -> int:
    """Calculate pixel width of text in dot matrix font."""
    width = 0
    for char in text.upper():
        if char in DOT_MATRIX_FONT:
            width += CHAR_WIDTH + CHAR_SPACING
    return max(0, width - CHAR_SPACING)


def draw_dot_matrix_char(
    img: Image.Image,
    char: str,
    x: int,
    y: int,
    color: tuple = (255, 165, 0),
    scale: int = 1
) -> int:
    """Draw a single dot-matrix character. Returns width used."""
    char = char.upper()
    if char not in DOT_MATRIX_FONT:
        return CHAR_WIDTH * scale + CHAR_SPACING * scale
    
    pattern = DOT_MATRIX_FONT[char]
    
    for row_idx, row in enumerate(pattern):
        for col_idx, pixel in enumerate(row):
            if pixel == '#':
                px = x + col_idx * scale
                py = y + row_idx * scale
                
                for dx in range(scale):
                    for dy in range(scale):
                        if 0 <= px + dx < img.width and 0 <= py + dy < img.height:
                            img.putpixel((px + dx, py + dy), color)
    
    return CHAR_WIDTH * scale + CHAR_SPACING * scale


def draw_dot_matrix_text(
    img: Image.Image,
    text: str,
    x: int = 0,
    y: int = 0,
    color: Union[str, tuple] = 'amber',
    scale: int = 1,
    center: bool = False
) -> None:
    """Draw dot-matrix style text on an image."""
    color = get_color(color)
    
    text_width = get_text_width(text) * scale
    text_height = CHAR_HEIGHT * scale
    
    if center:
        x = x - text_width // 2
        y = y - text_height // 2
    
    cursor_x = x
    for char in text:
        cursor_x += draw_dot_matrix_char(img, char, cursor_x, y, color, scale)


def create_dot_matrix_text(
    text: str,
    width: int = PANEL_SIZE,
    height: int = PANEL_SIZE,
    color: Union[str, tuple] = 'amber',
    bg_color: Union[str, tuple] = 'black',
    auto_scale: bool = True
) -> Image.Image:
    """Create an image with centered dot-matrix text."""
    bg = get_color(bg_color)
    fg = get_color(color)
    
    img = Image.new('RGB', (width, height), bg)
    
    # Find best scale that fits
    scale = 1
    if auto_scale:
        for s in range(4, 0, -1):
            text_w = get_text_width(text) * s
            text_h = CHAR_HEIGHT * s
            if text_w <= width - 2 and text_h <= height - 2:
                scale = s
                break
    
    draw_dot_matrix_text(img, text, width // 2, height // 2, fg, scale, center=True)
    return img


# =============================================================================
# Text Image Creation (Using System Fonts)
# =============================================================================

def create_text_image(
    text: str,
    width: int = PANEL_SIZE,
    height: int = PANEL_SIZE,
    color: Union[str, tuple] = 'orange',
    bg_color: Union[str, tuple] = 'black',
    font_size: int = 18,
    bold: bool = True
) -> Image.Image:
    """
    Create an image with centered text using system fonts.
    Falls back to default font if no system fonts available.
    """
    bg = get_color(bg_color)
    fg = get_color(color)
    
    img = Image.new('RGB', (width, height), bg)
    draw = ImageDraw.Draw(img)
    
    # Try to find a font
    font = None
    font_names = ['arialbd.ttf', 'ariblk.ttf', 'impact.ttf', 'arial.ttf'] if bold else ['arial.ttf']
    
    for font_name in font_names:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except OSError:
            continue
    
    if font is None:
        font = ImageFont.load_default()
    
    # Auto-size font to fit
    while font_size > 8:
        try:
            font = ImageFont.truetype(font_names[0], font_size)
        except:
            font = ImageFont.load_default()
            break
        
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        if text_width <= width - 4 and text_height <= height - 4:
            break
        font_size -= 2
    
    # Calculate centered position
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (width - text_width) // 2
    y = (height - text_height) // 2 - 2
    
    # Draw with slight offsets for boldness
    if bold:
        for dx, dy in [(0, 0), (1, 0), (0, 1), (1, 1)]:
            draw.text((x + dx, y + dy), text, fill=fg, font=font)
    else:
        draw.text((x, y), text, fill=fg, font=font)
    
    return img


# =============================================================================
# PNG Conversion
# =============================================================================

def to_png_bytes(img: Image.Image) -> bytes:
    """Convert PIL Image to PNG bytes for sending to panel."""
    buf = BytesIO()
    img.save(buf, format='PNG', optimize=False)
    return buf.getvalue()


def load_and_prepare(
    image_path: Union[Path, str],
    size: int = PANEL_SIZE,
    mode: Literal['fit', 'fill', 'stretch'] = 'fill'
) -> bytes:
    """Load an image, resize it, and convert to PNG bytes."""
    img = resize_image(image_path, size, size, mode)
    return to_png_bytes(img)

