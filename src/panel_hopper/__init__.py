"""
Panel Hopper - BLE LED Panel Controller

A Python toolkit for controlling BK-Light ACT1026 32x32 RGB LED panels
over Bluetooth Low Energy (BLE).

Supports:
- Single panel control (32x32)
- 2x2 grid mode (64x64 across 4 panels)
- Image and text display
- Web interface for easy management
- CLI tools for scripting

Repository: https://github.com/YOUR_USERNAME/panel-hopper
License: MIT
"""

__version__ = "1.0.0"
__author__ = "Panel Hopper Contributors"

from .config import PanelConfig, load_config, save_config
from .core import PanelController, scan_for_panels
from .graphics import (
    create_panel_image,
    create_grid_image,
    create_text_image,
    create_dot_matrix_text,
    resize_for_panel,
    resize_for_grid,
    split_for_grid,
    to_png_bytes,
)

__all__ = [
    # Config
    "PanelConfig",
    "load_config",
    "save_config",
    # Core
    "PanelController",
    "scan_for_panels",
    # Graphics
    "create_panel_image",
    "create_grid_image",
    "create_text_image",
    "create_dot_matrix_text",
    "resize_for_panel",
    "resize_for_grid",
    "split_for_grid",
    "to_png_bytes",
]

