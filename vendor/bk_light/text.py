from __future__ import annotations
import math
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont


def load_font(path: Optional[Path], size: int) -> ImageFont.ImageFont:
    if path is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


def build_text_bitmap(
    text: str,
    font_path: Optional[Path],
    size: int,
    spacing: int,
    color: tuple[int, int, int],
    antialias: bool,
    monospace_digits: bool = True,
) -> Image.Image:
    font = load_font(font_path, size)
    formatted = text.replace("\\n", "\n")
    lines = formatted.split("\n")
    mask_mode = "L" if antialias else "1"
    dummy = Image.new(mask_mode, (1, 1), 0)
    draw_dummy = ImageDraw.Draw(dummy)
    has_length = hasattr(font, "getlength")

    def advance_width(char: str) -> float:
        if has_length:
            value = font.getlength(char)
            if value > 0:
                return value
        width = draw_dummy.textlength(char, font=font)
        return float(width if width > 0 else 1)

    digit_data = {}
    max_digit_advance = 0.0
    digit_top = 0
    digit_bottom = 0
    for digit in "0123456789":
        bbox = draw_dummy.textbbox((0, 0), digit, font=font)
        if bbox is None:
            continue
        adv = advance_width(digit)
        digit_data[digit] = (bbox, adv)
        max_digit_advance = max(max_digit_advance, adv)
        digit_top = min(digit_top, bbox[1])
        digit_bottom = max(digit_bottom, bbox[3])
    ascent = descent = 0
    if hasattr(font, "getmetrics"):
        ascent, descent = font.getmetrics()
    if ascent == 0 and descent == 0:
        sample_bbox = draw_dummy.textbbox((0, 0), "0", font=font)
        if sample_bbox:
            ascent = max(ascent, -sample_bbox[1])
            descent = max(descent, sample_bbox[3])
    line_height = ascent + descent if ascent + descent > 0 else size
    placements: list[tuple[Image.Image, float, float]] = []
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf
    for index, line in enumerate(lines):
        cursor_x = 0.0
        baseline = index * (line_height + spacing) + ascent
        for char in line:
            bbox = draw_dummy.textbbox((0, 0), char, font=font)
            if bbox is None:
                continue
            width = max(1, bbox[2] - bbox[0])
            height = max(1, bbox[3] - bbox[1])
            mask = Image.new(mask_mode, (width, height), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.text((-bbox[0], -bbox[1]), char, fill=255, font=font)
            if not antialias:
                mask = mask.convert("L")
            glyph = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            fill_layer = Image.new("RGBA", (width, height), (*color, 255))
            glyph = Image.composite(fill_layer, glyph, mask)
            advance = advance_width(char)
            adjust = 0.0
            if monospace_digits and char in digit_data and max_digit_advance > 0:
                adjust = 0.5 * (max_digit_advance - advance)
                advance = max_digit_advance
            x = cursor_x + adjust + bbox[0]
            y = baseline + bbox[1]
            placements.append((glyph, x, y))
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + width)
            max_y = max(max_y, y + height)
            cursor_x += advance
    if min_x is math.inf or min_y is math.inf:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    width = int(math.ceil(max_x - min_x))
    height = int(math.ceil(max_y - min_y))
    width = max(width, 1)
    height = max(height, 1)
    bitmap = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for glyph, x, y in placements:
        px = int(round(x - min_x))
        py = int(round(y - min_y))
        bitmap.alpha_composite(glyph, (px, py))
    return bitmap
