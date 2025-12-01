#!/usr/bin/env python3
"""
Panel Hopper - Web Server

A minimalist FastAPI web interface for managing LED panels,
uploading images, and controlling displays.

Run with: python web/server.py
Or: uvicorn web.server:app --reload
"""

import asyncio
import json
import os
import shutil
import sys
from collections import deque
from dataclasses import asdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, List

from fastapi import FastAPI, File, HTTPException, UploadFile, Form, WebSocket, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont
import uvicorn
import urllib.request
import urllib.parse

# Giphy API key (free tier)
GIPHY_API_KEY = "dc6zaTOxFJmzC"  # Public beta key

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panel_hopper.core import PanelController, scan_for_panels, setup_logging, PersistentSession, get_persistent_session
from panel_hopper.config import load_config, save_config, Panel
from panel_hopper.graphics import (
    resize_for_panel,
    resize_for_grid,
    split_for_grid,
    create_text_image,
    create_dot_matrix_text,
    to_png_bytes,
    PANEL_SIZE,
    GRID_SIZE,
    GRID_POSITIONS,
)

# =============================================================================
# Configuration
# =============================================================================

# Paths
BASE_DIR = Path(__file__).parent.parent
ASSETS_DIR = BASE_DIR / "assets"
EXAMPLES_DIR = ASSETS_DIR / "examples"
UPLOADS_DIR = ASSETS_DIR / "uploads"
FONTS_DIR = ASSETS_DIR / "fonts"
GIFS_DIR = ASSETS_DIR / "gifs"
STATIC_DIR = Path(__file__).parent / "static"

# Ensure directories exist
ASSETS_DIR.mkdir(exist_ok=True)
EXAMPLES_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)
GIFS_DIR.mkdir(exist_ok=True)

SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
FONT_EXTENSIONS = {'.ttf', '.otf'}

# Live log buffer
LOG_BUFFER = deque(maxlen=100)

# Global brightness (0.0 - 1.0)
GLOBAL_BRIGHTNESS = 1.0



def add_log(message: str, level: str = "info"):
    """Add a message to the log buffer."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    LOG_BUFFER.append({
        "time": timestamp,
        "level": level,
        "message": message
    })


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="Panel Hopper",
    description="BLE LED Panel Controller",
    version="1.0.0"
)

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Static Files & Frontend
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def get_frontend():
    """Serve the main HTML page."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding='utf-8'))
    
    # Fallback: try parent web folder
    alt_path = Path(__file__).parent / "static" / "index.html"
    if alt_path.exists():
        return HTMLResponse(alt_path.read_text(encoding='utf-8'))
    
    return HTMLResponse("<h1>Frontend not found. Place index.html in web/static/</h1>")


# Serve static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# =============================================================================
# Image Endpoints
# =============================================================================

@app.get("/api/images")
async def list_images():
    """List all available images."""
    images = []
    
    for folder in [EXAMPLES_DIR, UPLOADS_DIR, GIFS_DIR]:
        if not folder.exists():
            continue
        
        for file in sorted(folder.iterdir()):
            if file.is_file() and file.suffix.lower() in SUPPORTED_EXTENSIONS:
                try:
                    with Image.open(file) as img:
                        w, h = img.size
                        is_animated = getattr(img, 'is_animated', False) if file.suffix.lower() == '.gif' else False
                        n_frames = getattr(img, 'n_frames', 1) if is_animated else 1
                except:
                    w, h = 0, 0
                    is_animated = False
                    n_frames = 1
                
                images.append({
                    "name": file.name,
                    "path": f"/assets/{file.parent.name}/{file.name}",
                    "folder": file.parent.name,
                    "width": w,
                    "height": h,
                    "is_gif": file.suffix.lower() == '.gif',
                    "is_animated": is_animated,
                    "frames": n_frames,
                })
    
    return {"images": images}


@app.get("/assets/{folder}/{filename}")
async def get_asset(folder: str, filename: str):
    """Serve an asset file."""
    file_path = ASSETS_DIR / folder / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(file_path)


@app.get("/api/images/{folder}/{filename}/preview")
async def get_image_preview(folder: str, filename: str, size: int = 32, grid: bool = False, animated: bool = False):
    """Get a preview of an image, optionally as grid layout or animated GIF."""
    file_path = ASSETS_DIR / folder / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    
    # For animated GIF preview, return the resized GIF with all frames
    if animated and filename.lower().endswith('.gif'):
        try:
            frames = []
            durations = []
            with Image.open(file_path) as gif:
                # Check if animated
                if not getattr(gif, 'is_animated', False):
                    animated = False
                else:
                    canvas = Image.new('RGB', gif.size, (0, 0, 0))
                    try:
                        while True:
                            if gif.mode == 'P':
                                frame = gif.convert('RGBA')
                            elif gif.mode == 'RGBA':
                                frame = gif.copy()
                            else:
                                frame = gif.convert('RGB')
                            
                            if frame.mode == 'RGBA':
                                canvas.paste(frame, (0, 0), frame)
                                rgb_frame = canvas.copy()
                            else:
                                rgb_frame = frame
                            
                            resized = rgb_frame.resize((size, size), Image.Resampling.NEAREST)
                            
                            # Apply brightness
                            if GLOBAL_BRIGHTNESS < 1.0:
                                from PIL import ImageEnhance
                                enhancer = ImageEnhance.Brightness(resized)
                                resized = enhancer.enhance(GLOBAL_BRIGHTNESS)
                            
                            frames.append(resized)
                            durations.append(gif.info.get('duration', 100))
                            gif.seek(gif.tell() + 1)
                    except EOFError:
                        pass
            
            if frames:
                buf = BytesIO()
                frames[0].save(
                    buf, 
                    format='GIF', 
                    save_all=True, 
                    append_images=frames[1:], 
                    duration=durations, 
                    loop=0
                )
                buf.seek(0)
                return StreamingResponse(buf, media_type="image/gif")
        except Exception as e:
            pass  # Fall back to static preview
    
    # Static preview
    with Image.open(file_path) as src:
        if src.mode == 'P':
            img = src.convert('RGBA').convert('RGB')
        elif src.mode != 'RGB':
            img = src.convert('RGB')
        else:
            img = src.copy()
    
    if grid:
        img = resize_for_grid(file_path)
    else:
        img = img.resize((PANEL_SIZE, PANEL_SIZE), Image.Resampling.NEAREST)
    
    # Apply brightness
    if GLOBAL_BRIGHTNESS < 1.0:
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(GLOBAL_BRIGHTNESS)
    
    if size != PANEL_SIZE and not grid:
        img = img.resize((size, size), Image.Resampling.NEAREST)
    
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    return StreamingResponse(buf, media_type="image/png")


@app.post("/api/images/upload")
async def upload_image(file: UploadFile = File(...)):
    """Upload a new image."""
    if not file.filename:
        raise HTTPException(400, "No filename")
    
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format. Use: {SUPPORTED_EXTENSIONS}")
    
    # Put GIFs in separate folder
    dest_folder = GIFS_DIR if ext == '.gif' else UPLOADS_DIR
    dest = dest_folder / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    add_log(f"Uploaded: {file.filename}", "success")
    return {"status": "ok", "filename": file.filename}


@app.delete("/api/images/{folder}/{filename}")
async def delete_image(folder: str, filename: str):
    """Delete an image."""
    if folder == "examples":
        raise HTTPException(400, "Cannot delete example images")
    
    file_path = ASSETS_DIR / folder / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    
    file_path.unlink()
    add_log(f"Deleted: {filename}", "info")
    return {"status": "ok"}


# =============================================================================
# Brightness Endpoints
# =============================================================================

@app.get("/api/brightness")
async def get_brightness():
    """Get current brightness."""
    return {"brightness": GLOBAL_BRIGHTNESS}


@app.post("/api/brightness")
async def set_brightness(brightness: float = Form(...), log: bool = Form(False)):
    """Set global brightness (0.0 - 1.0)."""
    global GLOBAL_BRIGHTNESS
    GLOBAL_BRIGHTNESS = max(0.0, min(1.0, brightness))
    if log:
        add_log(f"Brightness: {int(GLOBAL_BRIGHTNESS * 100)}%", "info")
    return {"brightness": GLOBAL_BRIGHTNESS}


# =============================================================================
# Panel Endpoints
# =============================================================================

@app.get("/api/panels")
async def list_panels():
    """List all configured panels."""
    config = load_config()
    panels = [
        {
            "mac": p.mac,
            "name": p.name,
            "enabled": p.enabled,
            "order": p.order,
            "grid_position": p.grid_position,
        }
        for p in sorted(config.panels.values(), key=lambda x: x.order)
    ]
    
    grid = {
        "linksboven": config.grid.linksboven,
        "rechtsboven": config.grid.rechtsboven,
        "linksonder": config.grid.linksonder,
        "rechtsonder": config.grid.rechtsonder,
    }
    
    return {"panels": panels, "grid": grid, "brightness": GLOBAL_BRIGHTNESS}


@app.post("/api/panels/scan")
async def scan_panels_endpoint():
    """Scan for BLE panels."""
    add_log("Scanning for panels...", "info")
    
    try:
        discovered = await scan_for_panels(timeout=10.0)
    except Exception as e:
        add_log(f"Scan failed: {e}", "error")
        raise HTTPException(500, str(e))
    
    config = load_config()
    added = 0
    
    for mac, name in discovered:
        if mac not in config.panels:
            config.add_panel(mac, name)
            added += 1
            add_log(f"Found new panel: {name}", "success")
    
    if added > 0:
        save_config(config)
    
    add_log(f"Scan complete: {len(discovered)} found, {added} new", "info")
    
    return {
        "found": len(discovered),
        "added": added,
        "panels": [{"mac": mac, "name": name} for mac, name in discovered]
    }


@app.post("/api/panels/{mac}/toggle")
async def toggle_panel(mac: str):
    """Toggle panel enabled state."""
    config = load_config()
    mac = mac.upper()
    
    if mac not in config.panels:
        raise HTTPException(404, "Panel not found")
    
    config.panels[mac].enabled = not config.panels[mac].enabled
    save_config(config)
    
    state = "enabled" if config.panels[mac].enabled else "disabled"
    add_log(f"{config.panels[mac].name}: {state}", "info")
    
    return {"status": "ok", "enabled": config.panels[mac].enabled}


@app.post("/api/panels/{mac}/rename")
async def rename_panel(mac: str, name: str = Form(...)):
    """Rename a panel."""
    config = load_config()
    mac = mac.upper()
    
    if mac not in config.panels:
        raise HTTPException(404, "Panel not found")
    
    old_name = config.panels[mac].name
    config.panels[mac].name = name
    save_config(config)
    
    add_log(f"Renamed: {old_name} → {name}", "info")
    return {"status": "ok", "name": name}


@app.post("/api/panels/identify")
async def identify_panel(panel_mac: str = Form(...), number: int = Form(...)):
    """Send identification number to a panel."""
    config = load_config()
    mac = panel_mac.upper()
    
    panel = config.get_panel_by_mac(mac)
    name = panel.name if panel else mac
    
    add_log(f"Identifying {name} with #{number}...", "info")
    
    # Create image with thin number (bold=False for thinner look)
    img = create_text_image(str(number), PANEL_SIZE, PANEL_SIZE, '#ff9900', font_size=26, bold=False)
    png_bytes = to_png_bytes(img)
    
    # Apply brightness
    if GLOBAL_BRIGHTNESS < 1.0:
        with Image.open(BytesIO(png_bytes)) as im:
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Brightness(im)
            brightened = enhancer.enhance(GLOBAL_BRIGHTNESS)
            buf = BytesIO()
            brightened.save(buf, format='PNG')
            png_bytes = buf.getvalue()
    
    # Send to panel
    controller = PanelController(timeout=15.0, retries=1)
    success, message = await controller.send_to_panel(mac, png_bytes, name)
    
    if success:
        add_log(f"✓ {name} identified as #{number}", "success")
        return {"status": "ok", "number": number}
    else:
        add_log(f"✗ {name}: {message}", "error")
        return {"status": "error", "message": message}




# =============================================================================
# Emoji Endpoints
# =============================================================================

@app.post("/api/emoji/render")
async def render_emoji(
    emoji: str = Form(...),
    size: int = Form(24),
    bg_color: str = Form("#000000"),
):
    """Render an emoji to panel image."""
    try:
        # Create image with emoji
        img = Image.new('RGB', (PANEL_SIZE, PANEL_SIZE), bg_color)
        draw = ImageDraw.Draw(img)
        
        # Try to use a font that supports emoji
        try:
            # Windows emoji font
            font = ImageFont.truetype("seguiemj.ttf", size)
        except:
            try:
                # Alternative
                font = ImageFont.truetype("arial.ttf", size)
            except:
                font = ImageFont.load_default()
        
        # Center the emoji
        bbox = draw.textbbox((0, 0), emoji, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (PANEL_SIZE - w) // 2
        y = (PANEL_SIZE - h) // 2
        
        draw.text((x, y), emoji, font=font, fill='white')
        
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        
        return StreamingResponse(buf, media_type="image/png")
        
    except Exception as e:
        raise HTTPException(500, str(e))


# =============================================================================
# Send Endpoints
# =============================================================================

@app.post("/api/send/single")
async def send_to_single(
    panel_mac: str = Form(...),
    image_path: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    color: str = Form("#ff9900"),
    bg_color: str = Form("#000000"),
    font_name: str = Form("default"),
    font_size: int = Form(18),
    font_style: str = Form("regular"),
):
    """Send image or text to a single panel."""
    config = load_config()
    panel = config.get_panel_by_mac(panel_mac)
    
    if not panel:
        raise HTTPException(404, "Panel not found")
    
    add_log(f"Sending to {panel.name}...", "info")
    
    # Prepare image
    if text:
        bold = font_style in ['bold', 'bold-italic']
        italic = font_style in ['italic', 'bold-italic']
        img = create_multiline_text_image(text, PANEL_SIZE, color, bg_color, font_name, font_size, bold, italic)
    elif image_path:
        full_path = ASSETS_DIR / image_path.replace("/assets/", "")
        if not full_path.exists():
            raise HTTPException(404, "Image not found")
        img = resize_for_panel(full_path)
    else:
        raise HTTPException(400, "Provide image_path or text")
    
    # Apply brightness
    if GLOBAL_BRIGHTNESS < 1.0:
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(GLOBAL_BRIGHTNESS)
    
    png_bytes = to_png_bytes(img)
    
    controller = PanelController()
    success, message = await controller.send_to_panel(panel.mac, png_bytes, panel.name)
    
    if success:
        add_log(f"✓ {panel.name}: sent", "success")
    else:
        add_log(f"✗ {panel.name}: {message}", "error")
    
    return {"status": "ok" if success else "error", "message": message}


@app.post("/api/send/all")
async def send_to_all(
    image_path: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    color: str = Form("#ff9900"),
    bg_color: str = Form("#000000"),
    font_name: str = Form("default"),
    font_size: int = Form(18),
    font_style: str = Form("regular"),
):
    """Send to all enabled panels."""
    config = load_config()
    enabled = config.get_enabled_panels()
    
    if not enabled:
        raise HTTPException(400, "No enabled panels")
    
    add_log(f"Sending to {len(enabled)} panels...", "info")
    
    # Prepare image
    if text:
        bold = font_style in ['bold', 'bold-italic']
        italic = font_style in ['italic', 'bold-italic']
        img = create_multiline_text_image(text, PANEL_SIZE, color, bg_color, font_name, font_size, bold, italic)
    elif image_path:
        full_path = ASSETS_DIR / image_path.replace("/assets/", "")
        if not full_path.exists():
            raise HTTPException(404, "Image not found")
        img = resize_for_panel(full_path)
    else:
        raise HTTPException(400, "Provide image_path or text")
    
    # Apply brightness
    if GLOBAL_BRIGHTNESS < 1.0:
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(GLOBAL_BRIGHTNESS)
    
    png_bytes = to_png_bytes(img)
    
    controller = PanelController()
    macs = [(p.mac, p.name) for p in enabled]
    results = await controller.send_same_to_all(macs, png_bytes)
    
    success_count = 0
    for mac, success, message in results:
        panel = config.get_panel_by_mac(mac)
        name = panel.name if panel else mac
        if success:
            add_log(f"✓ {name}", "success")
            success_count += 1
        else:
            add_log(f"✗ {name}: {message}", "error")
    
    add_log(f"Complete: {success_count}/{len(enabled)}", "info")
    
    return {
        "status": "ok",
        "success_count": success_count,
        "total": len(enabled),
        "results": [
            {"mac": mac, "success": success, "message": message}
            for mac, success, message in results
        ]
    }


@app.post("/api/send/grid")
async def send_to_grid(
    image_path: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    color: str = Form("#ff9900"),
    bg_color: str = Form("#000000"),
    font_name: str = Form("default"),
    font_size: int = Form(28),
    font_style: str = Form("regular"),
    dot_matrix: bool = Form(False),
):
    """Send to 4 grid panels (64x64 split)."""
    config = load_config()
    grid_panels = config.get_grid_panels()
    
    if len(grid_panels) < 4:
        raise HTTPException(400, f"Grid needs 4 panels, have {len(grid_panels)}")
    
    add_log("Sending to grid (64x64)...", "info")
    
    # Prepare 64x64 image
    if text:
        if dot_matrix:
            img = create_dot_matrix_text(text, GRID_SIZE, GRID_SIZE, color)
        else:
            bold = font_style in ['bold', 'bold-italic']
            italic = font_style in ['italic', 'bold-italic']
            img = create_multiline_text_image(text, GRID_SIZE, color, bg_color, font_name, font_size, bold, italic)
    elif image_path:
        full_path = ASSETS_DIR / image_path.replace("/assets/", "")
        if not full_path.exists():
            raise HTTPException(404, "Image not found")
        img = resize_for_grid(full_path)
    else:
        raise HTTPException(400, "Provide image_path or text")
    
    # Apply brightness
    if GLOBAL_BRIGHTNESS < 1.0:
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(GLOBAL_BRIGHTNESS)
    
    parts = split_for_grid(img)
    
    controller = PanelController()
    send_order = ['rechtsonder', 'linksonder', 'rechtsboven', 'linksboven']
    
    results = []
    success_count = 0
    
    for position in send_order:
        if position not in grid_panels:
            results.append({"position": position, "success": False, "message": "not configured"})
            continue
        
        panel = grid_panels[position]
        png_bytes = to_png_bytes(parts[position])
        
        success, message = await controller.send_to_panel(panel.mac, png_bytes, position)
        results.append({"position": position, "success": success, "message": message})
        
        if success:
            add_log(f"✓ {position}", "success")
            success_count += 1
        else:
            add_log(f"✗ {position}: {message}", "error")
    
    add_log(f"Grid complete: {success_count}/4", "info")
    
    return {"status": "ok", "success_count": success_count, "results": results}


# =============================================================================
# Text Preview Endpoint
# =============================================================================

def has_emoji(text: str) -> bool:
    """Check if text contains emoji characters."""
    for char in text:
        # Emoji ranges
        if ord(char) > 0x1F300:
            return True
        # Some emoji in BMP
        if ord(char) in range(0x2600, 0x27C0) or ord(char) in range(0x2300, 0x2400):
            return True
    return False


def create_multiline_text_image(
    text: str,
    size: int,
    color: str,
    bg_color: str,
    font_name: str,
    font_size: int,
    bold: bool = False,
    italic: bool = False,
) -> Image.Image:
    """Create a multi-line text image that auto-sizes to fit the panel. Supports emoji via pilmoji."""
    img = Image.new('RGB', (size, size), bg_color)
    
    # Handle various newline formats and clean up text
    clean_text = text.replace('\\n', '\n').replace('\r\n', '\n').replace('\r', '\n')
    # Keep emoji and printable characters
    clean_text = ''.join(char if char == '\n' or char.isprintable() else '' for char in clean_text)
    lines = clean_text.split('\n')
    # Strip whitespace from each line but keep empty lines for spacing
    lines = [line.strip() for line in lines]
    
    # Check if text contains emoji
    contains_emoji = has_emoji(text)
    
    def get_font(fsize: int):
        """Get font at specified size."""
        font = None
        
        if font_name not in ['default', 'dotmatrix', '__upload__']:
            # Check custom fonts first
            custom_font = FONTS_DIR / font_name
            if custom_font.exists():
                try:
                    font = ImageFont.truetype(str(custom_font), fsize)
                    return font
                except:
                    pass
        
        # Try system font with style
        try:
            if bold and italic:
                font_file = "arialbi.ttf"
            elif bold:
                font_file = "arialbd.ttf"
            elif italic:
                font_file = "ariali.ttf"
            else:
                font_file = "arial.ttf"
            font = ImageFont.truetype(font_file, fsize)
        except:
            try:
                font = ImageFont.truetype("arial.ttf", fsize)
            except:
                font = ImageFont.load_default()
        return font
    
    # Use pilmoji for emoji support if available
    try:
        from pilmoji import Pilmoji
        use_pilmoji = True
    except ImportError:
        use_pilmoji = False
    
    if use_pilmoji and contains_emoji:
        # Use pilmoji for emoji rendering
        current_size = font_size
        font = get_font(current_size)
        
        # Auto-size with pilmoji
        with Pilmoji(img) as pilmoji:
            while current_size >= 6:
                font = get_font(current_size)
                
                # Measure all lines
                max_width = 0
                total_height = 0
                line_heights = []
                
                for line in lines:
                    if line:
                        # pilmoji doesn't have getsize, use ImageDraw for measurement
                        temp_draw = ImageDraw.Draw(img)
                        try:
                            bbox = temp_draw.textbbox((0, 0), line, font=font)
                            line_w = bbox[2] - bbox[0]
                            line_h = bbox[3] - bbox[1]
                        except:
                            line_w, line_h = current_size * len(line), current_size
                        line_heights.append(line_h)
                        max_width = max(max_width, line_w)
                        total_height += line_h + 2
                    else:
                        line_heights.append(current_size)
                        total_height += current_size + 2
                
                total_height -= 2
                
                if max_width <= size - 4 and total_height <= size - 4:
                    break
                
                current_size -= 1
            
            # Recalculate heights
            line_heights = []
            total_height = 0
            for line in lines:
                if line:
                    temp_draw = ImageDraw.Draw(img)
                    try:
                        bbox = temp_draw.textbbox((0, 0), line, font=font)
                        line_h = bbox[3] - bbox[1]
                    except:
                        line_h = current_size
                    line_heights.append(line_h)
                    total_height += line_h + 2
                else:
                    line_heights.append(current_size)
                    total_height += current_size + 2
            total_height -= 2
            
            # Draw text centered
            y = (size - total_height) // 2
            
            for i, line in enumerate(lines):
                if line and i < len(line_heights):
                    temp_draw = ImageDraw.Draw(img)
                    try:
                        bbox = temp_draw.textbbox((0, 0), line, font=font)
                        line_w = bbox[2] - bbox[0]
                    except:
                        line_w = current_size * len(line)
                    x = (size - line_w) // 2
                    
                    # Draw with pilmoji for emoji support
                    pilmoji.text((x, y), line, font=font, fill=color, 
                                emoji_scale_factor=0.9, emoji_position_offset=(0, -1))
                    y += line_heights[i] + 2
                else:
                    y += current_size + 2
        
        return img
    
    # Standard rendering without emoji
    draw = ImageDraw.Draw(img)
    
    # Auto-size: start with requested size and shrink until it fits
    current_size = font_size
    font = get_font(current_size)
    
    while current_size >= 6:
        font = get_font(current_size)
        
        # Measure all lines using proper bounding boxes
        line_bboxes = []
        max_width = 0
        total_height = 0
        
        for line in lines:
            if line:
                bbox = draw.textbbox((0, 0), line, font=font)
                line_h = bbox[3] - bbox[1]
                line_w = bbox[2] - bbox[0]
                line_bboxes.append((line_w, line_h, bbox[1]))  # width, height, top offset
                max_width = max(max_width, line_w)
                total_height += line_h + 2  # 2px line spacing
            else:
                line_bboxes.append((0, current_size, 0))
                total_height += current_size + 2
        
        total_height -= 2  # Remove last spacing
        
        # Check if it fits (with 2px margin)
        if max_width <= size - 4 and total_height <= size - 4:
            break
        
        current_size -= 1
        line_bboxes = []
    
    # Recalculate for final size
    line_bboxes = []
    total_height = 0
    for line in lines:
        if line:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_h = bbox[3] - bbox[1]
            line_w = bbox[2] - bbox[0]
            top_offset = bbox[1]
            line_bboxes.append((line_w, line_h, top_offset))
            total_height += line_h + 2
        else:
            line_bboxes.append((0, current_size, 0))
            total_height += current_size + 2
    total_height -= 2
    
    # Draw text centered vertically and horizontally
    y = (size - total_height) // 2
    
    for i, line in enumerate(lines):
        if line and i < len(line_bboxes):
            line_w, line_h, top_offset = line_bboxes[i]
            x = (size - line_w) // 2
            # Adjust for font's top offset (ascender space)
            draw.text((x, y - top_offset), line, font=font, fill=color)
            y += line_h + 2
        else:
            y += current_size + 2
    
    return img


@app.post("/api/text/preview")
async def text_preview(
    text: str = Form(...),
    color: str = Form("#ff9900"),
    bg_color: str = Form("#000000"),
    font_name: str = Form("default"),
    font_size: int = Form(18),
    font_style: str = Form("regular"),
):
    """Generate a preview of text rendering."""
    bold = font_style in ['bold', 'bold-italic']
    italic = font_style in ['italic', 'bold-italic']
    
    img = create_multiline_text_image(text, PANEL_SIZE, color, bg_color, font_name, font_size, bold, italic)
    
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    return StreamingResponse(buf, media_type="image/png")


# =============================================================================
# Log Endpoint
# =============================================================================

@app.get("/api/logs")
async def get_logs(since: int = 0):
    """Get recent log entries."""
    return {"logs": list(LOG_BUFFER)}


# =============================================================================
# Fonts Endpoints
# =============================================================================

@app.get("/api/fonts")
async def list_fonts():
    """List available custom fonts."""
    fonts = []
    if FONTS_DIR.exists():
        for f in sorted(FONTS_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in FONT_EXTENSIONS:
                fonts.append(f.name)
    return {"fonts": fonts}


@app.post("/api/fonts/upload")
async def upload_font(file: UploadFile = File(...)):
    """Upload a custom font."""
    if not file.filename:
        raise HTTPException(400, "No filename")
    
    ext = Path(file.filename).suffix.lower()
    if ext not in FONT_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format. Use: {FONT_EXTENSIONS}")
    
    dest = FONTS_DIR / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    add_log(f"Font uploaded: {file.filename}", "success")
    return {"status": "ok", "filename": file.filename}


# =============================================================================
# Giphy API Endpoints
# =============================================================================

@app.get("/api/giphy/trending")
async def giphy_trending(limit: int = 12, offset: int = 0):
    """Get trending GIFs from Giphy."""
    try:
        url = f"https://api.giphy.com/v1/gifs/trending?api_key={GIPHY_API_KEY}&limit={limit}&offset={offset}&rating=g"
        
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
        
        gifs = []
        for gif in data.get('data', []):
            images = gif.get('images', {})
            gifs.append({
                'id': gif.get('id'),
                'title': gif.get('title', ''),
                'preview': images.get('fixed_width_small', {}).get('url', ''),
                'original': images.get('original', {}).get('url', ''),
                'small': images.get('fixed_width', {}).get('url', ''),
                'width': int(images.get('fixed_width', {}).get('width', 0)),
                'height': int(images.get('fixed_width', {}).get('height', 0)),
            })
        
        return {
            "gifs": gifs,
            "total": data.get('pagination', {}).get('total_count', 0),
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(500, f"Giphy error: {str(e)}")


@app.get("/api/giphy/search")
async def giphy_search(q: str, limit: int = 12, offset: int = 0):
    """Search GIFs on Giphy."""
    try:
        query = urllib.parse.quote(q)
        url = f"https://api.giphy.com/v1/gifs/search?api_key={GIPHY_API_KEY}&q={query}&limit={limit}&offset={offset}&rating=g"
        
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
        
        gifs = []
        for gif in data.get('data', []):
            images = gif.get('images', {})
            gifs.append({
                'id': gif.get('id'),
                'title': gif.get('title', ''),
                'preview': images.get('fixed_width_small', {}).get('url', ''),
                'original': images.get('original', {}).get('url', ''),
                'small': images.get('fixed_width', {}).get('url', ''),
                'width': int(images.get('fixed_width', {}).get('width', 0)),
                'height': int(images.get('fixed_width', {}).get('height', 0)),
            })
        
        return {
            "gifs": gifs,
            "query": q,
            "total": data.get('pagination', {}).get('total_count', 0),
            "offset": offset
        }
    except Exception as e:
        raise HTTPException(500, f"Giphy search error: {str(e)}")


@app.post("/api/giphy/download")
async def giphy_download(gif_url: str = Form(...), gif_id: str = Form(...)):
    """Download a GIF from Giphy and save it locally."""
    try:
        # Download the GIF
        with urllib.request.urlopen(gif_url, timeout=30) as response:
            gif_data = response.read()
        
        # Save to local gifs folder
        filename = f"giphy_{gif_id}.gif"
        dest = GIFS_DIR / filename
        
        with open(dest, "wb") as f:
            f.write(gif_data)
        
        add_log(f"Downloaded GIF: {filename}", "success")
        
        return {
            "status": "ok",
            "filename": filename,
            "path": f"/assets/gifs/{filename}"
        }
    except Exception as e:
        add_log(f"GIF download failed: {e}", "error")
        raise HTTPException(500, f"Download error: {str(e)}")


# =============================================================================
# Grid Preview Endpoint
# =============================================================================

@app.get("/api/grid-preview")
async def get_grid_preview(
    image_path: Optional[str] = None,
    text: Optional[str] = None,
    cols: int = 2,
    rows: int = 2,
):
    """Generate LED-style grid preview."""
    grid_w = cols * PANEL_SIZE
    grid_h = rows * PANEL_SIZE
    
    if text:
        img = create_dot_matrix_text(text, grid_w, grid_h, '#ff9900')
    elif image_path:
        full_path = ASSETS_DIR / image_path.replace("/assets/", "")
        if not full_path.exists():
            raise HTTPException(404, "Image not found")
        
        with Image.open(full_path) as src:
            if src.mode != 'RGB':
                src = src.convert('RGB')
            img = src.resize((grid_w, grid_h), Image.Resampling.NEAREST)
    else:
        img = Image.new('RGB', (grid_w, grid_h), (0, 0, 0))
    
    # Apply brightness
    if GLOBAL_BRIGHTNESS < 1.0:
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(GLOBAL_BRIGHTNESS)
    
    # Scale up for LED effect
    scale = 4
    gap = 2  # Gap between panels
    preview_w = grid_w * scale + (cols - 1) * gap
    preview_h = grid_h * scale + (rows - 1) * gap
    preview = Image.new('RGB', (preview_w, preview_h), (10, 10, 15))
    
    draw = ImageDraw.Draw(preview)
    
    for py in range(rows):
        for px in range(cols):
            for y in range(PANEL_SIZE):
                for x in range(PANEL_SIZE):
                    sx = px * PANEL_SIZE + x
                    sy = py * PANEL_SIZE + y
                    color = img.getpixel((sx, sy))
                    
                    dx = px * (PANEL_SIZE * scale + gap) + x * scale
                    dy = py * (PANEL_SIZE * scale + gap) + y * scale
                    
                    if color != (0, 0, 0):
                        draw.rectangle([dx, dy, dx + scale - 1, dy + scale - 1], fill=color)
                    else:
                        draw.rectangle([dx, dy, dx + scale - 1, dy + scale - 1], fill=(5, 5, 8))
    
    buf = BytesIO()
    preview.save(buf, format='PNG')
    buf.seek(0)
    
    return StreamingResponse(buf, media_type="image/png")


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """Run the web server."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Panel Hopper Web Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on changes")
    args = parser.parse_args()
    
    setup_logging()
    
    print("\n" + "=" * 50)
    print("   Panel Hopper - Web Interface")
    print("=" * 50)
    print(f"\n   URL: http://localhost:{args.port}")
    print(f"   Network: http://0.0.0.0:{args.port}")
    print("\n   Press Ctrl+C to stop\n")
    
    uvicorn.run(
        "web.server:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
