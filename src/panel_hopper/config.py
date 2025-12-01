"""
Panel Configuration Management

Handles loading, saving, and managing panel configurations.
Configurations are stored in JSON format for easy editing.
"""

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_CONFIG_FILE = Path("panels.json")
DEFAULT_ASSETS_DIR = Path("assets")


@dataclass
class Panel:
    """Information about a single LED panel."""
    mac: str
    name: str
    enabled: bool = True
    order: int = 99
    grid_position: Optional[str] = None  # linksboven, rechtsboven, linksonder, rechtsonder
    notes: str = ""

    def __post_init__(self):
        # Normalize MAC address to uppercase
        self.mac = self.mac.upper()


@dataclass
class GridConfig:
    """Configuration for 2x2 grid mode."""
    linksboven: Optional[str] = None   # MAC address
    rechtsboven: Optional[str] = None
    linksonder: Optional[str] = None
    rechtsonder: Optional[str] = None


@dataclass
class PanelConfig:
    """Complete panel configuration."""
    panels: dict[str, Panel] = field(default_factory=dict)
    grid: GridConfig = field(default_factory=GridConfig)
    
    # BLE settings
    scan_timeout: float = 10.0
    send_timeout: float = 30.0
    send_delay: float = 0.15
    retry_count: int = 3
    panel_delay: float = 1.5  # Delay between sending to different panels
    
    # Server settings
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    def get_panel_by_name(self, name: str) -> Optional[Panel]:
        """Find a panel by its name."""
        for panel in self.panels.values():
            if panel.name.lower() == name.lower():
                return panel
        return None

    def get_panel_by_mac(self, mac: str) -> Optional[Panel]:
        """Find a panel by its MAC address."""
        return self.panels.get(mac.upper())

    def get_enabled_panels(self) -> list[Panel]:
        """Get all enabled panels, sorted by order."""
        enabled = [p for p in self.panels.values() if p.enabled]
        return sorted(enabled, key=lambda p: p.order)

    def get_grid_panels(self) -> dict[str, Panel]:
        """Get the 4 grid panels with their positions."""
        result = {}
        grid_macs = {
            'linksboven': self.grid.linksboven,
            'rechtsboven': self.grid.rechtsboven,
            'linksonder': self.grid.linksonder,
            'rechtsonder': self.grid.rechtsonder,
        }
        for position, mac in grid_macs.items():
            if mac and mac in self.panels:
                result[position] = self.panels[mac]
        return result

    def add_panel(self, mac: str, name: str, enabled: bool = True) -> Panel:
        """Add a new panel to the configuration."""
        mac = mac.upper()
        panel = Panel(mac=mac, name=name, enabled=enabled)
        self.panels[mac] = panel
        return panel

    def remove_panel(self, mac: str) -> bool:
        """Remove a panel from the configuration."""
        mac = mac.upper()
        if mac in self.panels:
            del self.panels[mac]
            # Also remove from grid if present
            if self.grid.linksboven == mac:
                self.grid.linksboven = None
            if self.grid.rechtsboven == mac:
                self.grid.rechtsboven = None
            if self.grid.linksonder == mac:
                self.grid.linksonder = None
            if self.grid.rechtsonder == mac:
                self.grid.rechtsonder = None
            return True
        return False


def load_config(config_file: Path = DEFAULT_CONFIG_FILE) -> PanelConfig:
    """
    Load panel configuration from JSON file.
    
    Args:
        config_file: Path to the configuration file.
        
    Returns:
        PanelConfig object with loaded or default settings.
    """
    config = PanelConfig()
    
    if not config_file.exists():
        logger.info(f"No config file found at {config_file}, using defaults")
        return config
    
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Load panels
        for mac, info in data.get("panels", {}).items():
            config.panels[mac.upper()] = Panel(
                mac=info.get("mac", mac),
                name=info.get("name", f"Panel {mac[-5:]}"),
                enabled=info.get("enabled", True),
                order=info.get("order", 99),
                grid_position=info.get("grid_position"),
                notes=info.get("notes", ""),
            )
        
        # Load grid config
        grid_data = data.get("grid", {})
        config.grid = GridConfig(
            linksboven=grid_data.get("linksboven"),
            rechtsboven=grid_data.get("rechtsboven"),
            linksonder=grid_data.get("linksonder"),
            rechtsonder=grid_data.get("rechtsonder"),
        )
        
        # Load settings
        settings = data.get("settings", {})
        config.scan_timeout = settings.get("scan_timeout", config.scan_timeout)
        config.send_timeout = settings.get("send_timeout", config.send_timeout)
        config.send_delay = settings.get("send_delay", config.send_delay)
        config.retry_count = settings.get("retry_count", config.retry_count)
        config.panel_delay = settings.get("panel_delay", config.panel_delay)
        config.server_host = settings.get("server_host", config.server_host)
        config.server_port = settings.get("server_port", config.server_port)
        
        logger.info(f"Loaded {len(config.panels)} panels from {config_file}")
        
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
    
    return config


def save_config(config: PanelConfig, config_file: Path = DEFAULT_CONFIG_FILE) -> bool:
    """
    Save panel configuration to JSON file.
    
    Args:
        config: PanelConfig object to save.
        config_file: Path to the configuration file.
        
    Returns:
        True if saved successfully, False otherwise.
    """
    data = {
        "panels": {
            mac: {
                "mac": panel.mac,
                "name": panel.name,
                "enabled": panel.enabled,
                "order": panel.order,
                "grid_position": panel.grid_position,
                "notes": panel.notes,
            }
            for mac, panel in config.panels.items()
        },
        "grid": {
            "linksboven": config.grid.linksboven,
            "rechtsboven": config.grid.rechtsboven,
            "linksonder": config.grid.linksonder,
            "rechtsonder": config.grid.rechtsonder,
        },
        "settings": {
            "scan_timeout": config.scan_timeout,
            "send_timeout": config.send_timeout,
            "send_delay": config.send_delay,
            "retry_count": config.retry_count,
            "panel_delay": config.panel_delay,
            "server_host": config.server_host,
            "server_port": config.server_port,
        },
    }
    
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(config.panels)} panels to {config_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


def create_example_config(config_file: Path = Path("config.example.json")) -> None:
    """Create an example configuration file for new users."""
    example = {
        "panels": {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "name": "panel_1",
                "enabled": True,
                "order": 1,
                "grid_position": "linksboven",
                "notes": "Example panel - replace with your panel's MAC"
            }
        },
        "grid": {
            "linksboven": None,
            "rechtsboven": None,
            "linksonder": None,
            "rechtsonder": None
        },
        "settings": {
            "scan_timeout": 10.0,
            "send_timeout": 30.0,
            "send_delay": 0.15,
            "retry_count": 3,
            "panel_delay": 1.5,
            "server_host": "0.0.0.0",
            "server_port": 8000
        }
    }
    
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(example, f, indent=2)
    
    print(f"Created example config: {config_file}")

