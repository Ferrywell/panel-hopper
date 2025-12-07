"""
Panel Manager Service

Central service for managing BLE connections to LED panels.
This module provides a clean API that can be used by:
- The web interface (via REST API)
- CLI tools
- Custom scripts and automation

All panel data is stored in local config files, nothing is hardcoded.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any
import json

# Add vendor path for bk_light
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "vendor"))

from bk_light.display_session import BleDisplaySession

logger = logging.getLogger(__name__)


@dataclass
class PanelState:
    """State of a connected panel."""
    mac: str
    name: str = ""
    connected: bool = False
    connecting: bool = False
    brightness: int = 100
    rotation: int = 0  # 0-3 (0°, 90°, 180°, 270°)
    last_command: Optional[str] = None
    last_command_time: Optional[datetime] = None
    error: Optional[str] = None
    session: Optional[BleDisplaySession] = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class PanelManager:
    """
    Central manager for LED panel connections.
    
    This is a singleton-like service that maintains persistent BLE connections
    to panels and provides a clean API for all panel operations.
    
    Usage:
        manager = PanelManager()
        await manager.connect("68:D0:1D:58:69:76", name="Living Room")
        await manager.set_brightness("68:D0:1D:58:69:76", 80)
        await manager.send_image("68:D0:1D:58:69:76", png_bytes)
        await manager.disconnect("68:D0:1D:58:69:76")
    """
    
    _instance: Optional['PanelManager'] = None
    
    def __new__(cls):
        """Singleton pattern - only one manager instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._panels: Dict[str, PanelState] = {}
        self._scan_timeout: float = 15.0
        self._connect_timeout: float = 30.0
        self._command_delay: float = 0.15
        self._log_notifications: bool = True  # Enable for debugging
        self._initialized = True
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitor_interval: float = 5.0  # Check connections every 5 seconds
        
        # Safe mode tracking
        self._safe_mode_active: bool = False
        self._safe_mode_adapter: Optional[str] = None
        
        # Auto-save setting: automatically save to flash after sending
        # DISABLED by default - causes issues with animations overwriting content
        self._auto_save: bool = False
        
        # Set up safe mode callback
        def on_safe_mode(adapter_address: str, adapter_name: str):
            self._safe_mode_active = True
            self._safe_mode_adapter = adapter_name or adapter_address
            logger.warning(f"BLE Safe Mode activated for adapter: {self._safe_mode_adapter}")
        
        BleDisplaySession.set_safe_mode_callback(on_safe_mode)
        
        logger.info("Panel Manager initialized")
    
    @property
    def safe_mode(self) -> bool:
        """Check if safe mode is active."""
        return self._safe_mode_active
    
    @property
    def adapter_name(self) -> str:
        """Get the current adapter name."""
        if self._safe_mode_adapter:
            return self._safe_mode_adapter
        
        # Try to detect the actual Bluetooth adapter on Windows
        return self._detect_bluetooth_adapter()
    
    def _detect_bluetooth_adapter(self) -> str:
        """Detect the Bluetooth adapter name on Windows."""
        import subprocess
        import sys
        
        if sys.platform != "win32":
            return "Bluetooth Adapter"
        
        try:
            # Use PowerShell to get Bluetooth devices
            result = subprocess.run(
                ['powershell', '-Command', 
                 'Get-PnpDevice -Class Bluetooth | Where-Object {$_.Status -eq "OK" -and $_.FriendlyName -notlike "*Microsoft*" -and $_.FriendlyName -notlike "*RFCOMM*"} | Select-Object -First 1 -ExpandProperty FriendlyName'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Could not detect Bluetooth adapter: {e}")
        
        return "Bluetooth Adapter"
    
    def reset_safe_mode(self):
        """Reset safe mode to try fast mode again."""
        self._safe_mode_active = False
        BleDisplaySession.reset_safe_mode()
        logger.info("Safe mode reset - will try fast mode on next connection")
    
    @property
    def auto_save(self) -> bool:
        """Check if auto-save is enabled."""
        return self._auto_save
    
    @auto_save.setter
    def auto_save(self, value: bool):
        """Enable/disable auto-save after sending."""
        self._auto_save = value
        logger.info(f"Auto-save {'enabled' if value else 'disabled'}")
    
    # =========================================================================
    # Connection Monitoring
    # =========================================================================
    
    async def start_monitoring(self):
        """Start the background connection monitor."""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._connection_monitor())
            logger.info("Connection monitor started")
    
    async def stop_monitoring(self):
        """Stop the background connection monitor."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            logger.info("Connection monitor stopped")
    
    async def _connection_monitor(self):
        """
        Background task that monitors BLE connections.
        
        - Checks if connections are still alive
        - Updates connection status
        - Logs connection changes
        """
        logger.info("Connection monitor running...")
        
        while True:
            try:
                await asyncio.sleep(self._monitor_interval)
                
                for mac, panel in list(self._panels.items()):
                    if panel.connected and panel.session:
                        try:
                            # Check if the BLE client is still connected
                            if panel.session.client and panel.session.client.is_connected:
                                # Connection still alive
                                pass
                            else:
                                # Connection lost
                                if panel.connected:
                                    logger.warning(f"[{panel.name}] Connection lost (detected by monitor)")
                                    panel.connected = False
                                    panel.error = "Connection lost"
                        except Exception as e:
                            logger.warning(f"[{panel.name}] Monitor check error: {e}")
                            panel.connected = False
                            panel.error = str(e)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Connection monitor error: {e}")
    
    # =========================================================================
    # Connection Management
    # =========================================================================
    
    async def connect(
        self, 
        mac: str, 
        name: str = "",
        timeout: float = None
    ) -> bool:
        """
        Connect to a panel and maintain the connection.
        
        Args:
            mac: Panel MAC address (e.g., "68:D0:1D:58:69:76")
            name: Optional friendly name for the panel
            timeout: Connection timeout in seconds (default: 30)
            
        Returns:
            True if connected successfully, False otherwise
        """
        mac = mac.upper()
        timeout = timeout or self._connect_timeout
        
        # Get or create panel state
        if mac not in self._panels:
            self._panels[mac] = PanelState(mac=mac, name=name or mac)
        
        panel = self._panels[mac]
        
        # Update name if provided
        if name:
            panel.name = name
        
        async with panel._lock:
            # Already connected?
            if panel.connected and panel.session:
                logger.info(f"[{panel.name}] Already connected")
                return True
            
            # Already connecting?
            if panel.connecting:
                logger.warning(f"[{panel.name}] Connection already in progress")
                return False
            
            panel.connecting = True
            panel.error = None
            
            try:
                logger.info(f"[{panel.name}] Connecting...")
                
                # Create new session
                session = BleDisplaySession(
                    address=mac,
                    auto_reconnect=True,
                    max_retries=3,
                    scan_timeout=self._scan_timeout,
                    log_notifications=self._log_notifications,
                )
                
                # Connect with timeout
                await asyncio.wait_for(session._connect(), timeout=timeout)
                
                panel.session = session
                panel.connected = True
                panel.last_command = "connect"
                panel.last_command_time = datetime.now()
                
                logger.info(f"[{panel.name}] Connected successfully")
                return True
                
            except asyncio.TimeoutError:
                panel.error = "Connection timeout"
                logger.error(f"[{panel.name}] Connection timeout")
                return False
                
            except Exception as e:
                panel.error = str(e)
                logger.error(f"[{panel.name}] Connection failed: {e}")
                return False
                
            finally:
                panel.connecting = False
    
    async def disconnect(self, mac: str) -> bool:
        """
        Disconnect from a panel.
        
        Args:
            mac: Panel MAC address
            
        Returns:
            True if disconnected successfully
        """
        mac = mac.upper()
        
        if mac not in self._panels:
            return True  # Not connected anyway
        
        panel = self._panels[mac]
        
        async with panel._lock:
            if panel.session:
                try:
                    await panel.session._safe_disconnect()
                except Exception as e:
                    logger.warning(f"[{panel.name}] Disconnect error: {e}")
                
                panel.session = None
            
            panel.connected = False
            panel.last_command = "disconnect"
            panel.last_command_time = datetime.now()
            
            logger.info(f"[{panel.name}] Disconnected")
            return True
    
    async def disconnect_all(self) -> None:
        """Disconnect from all panels."""
        for mac in list(self._panels.keys()):
            await self.disconnect(mac)
    
    def is_connected(self, mac: str) -> bool:
        """Check if a panel is connected."""
        mac = mac.upper()
        if mac not in self._panels:
            return False
        return self._panels[mac].connected
    
    def get_status(self, mac: str) -> Optional[Dict[str, Any]]:
        """
        Get the current status of a panel.
        
        Returns:
            Dict with panel status or None if not found
        """
        mac = mac.upper()
        if mac not in self._panels:
            return None
        
        panel = self._panels[mac]
        return {
            "mac": panel.mac,
            "name": panel.name,
            "connected": panel.connected,
            "connecting": panel.connecting,
            "brightness": panel.brightness,
            "rotation": panel.rotation,
            "last_command": panel.last_command,
            "last_command_time": panel.last_command_time.isoformat() if panel.last_command_time else None,
            "error": panel.error,
        }
    
    def list_panels(self) -> List[Dict[str, Any]]:
        """Get status of all known panels."""
        return [self.get_status(mac) for mac in self._panels.keys()]
    
    def list_connected(self) -> List[str]:
        """Get list of connected panel MAC addresses."""
        return [mac for mac, panel in self._panels.items() if panel.connected]
    
    # =========================================================================
    # Panel Commands
    # =========================================================================
    
    async def _ensure_connected(self, mac: str) -> Optional[PanelState]:
        """Ensure panel is connected, return panel state or None."""
        mac = mac.upper()
        
        if mac not in self._panels:
            logger.error(f"Panel {mac} not found. Call connect() first.")
            return None
        
        panel = self._panels[mac]
        
        if not panel.connected or not panel.session:
            logger.error(f"[{panel.name}] Not connected. Call connect() first.")
            return None
        
        return panel
    
    async def set_brightness(self, mac: str, value: int) -> bool:
        """
        Set panel brightness.
        
        Args:
            mac: Panel MAC address
            value: Brightness value 0-100
            
        Returns:
            True if command was acknowledged
        """
        panel = await self._ensure_connected(mac)
        if not panel:
            return False
        
        value = max(0, min(100, value))
        
        async with panel._lock:
            try:
                logger.info(f"[{panel.name}] Setting brightness to {value}%")
                success = await panel.session.set_panel_brightness(value)
                
                if success:
                    panel.brightness = value
                    panel.last_command = f"brightness:{value}"
                    panel.last_command_time = datetime.now()
                    panel.error = None
                    logger.info(f"[{panel.name}] Brightness set to {value}%")
                else:
                    panel.error = "Command not acknowledged"
                    logger.warning(f"[{panel.name}] Brightness command not acknowledged")
                
                return success
                
            except Exception as e:
                panel.error = str(e)
                panel.connected = False  # Mark as disconnected on error
                logger.error(f"[{panel.name}] Brightness error: {e}")
                return False
    
    async def set_rotation(self, mac: str, rotation: int) -> bool:
        """
        Set panel rotation.
        
        Args:
            mac: Panel MAC address
            rotation: 0=0°, 1=90°, 2=180°, 3=270°
            
        Returns:
            True if command was acknowledged
        """
        panel = await self._ensure_connected(mac)
        if not panel:
            return False
        
        rotation = rotation % 4  # Ensure 0-3
        
        async with panel._lock:
            try:
                logger.info(f"[{panel.name}] Setting rotation to {rotation * 90}°")
                success = await panel.session.set_panel_rotation(rotation)
                
                if success:
                    panel.rotation = rotation
                    panel.last_command = f"rotation:{rotation}"
                    panel.last_command_time = datetime.now()
                    panel.error = None
                    logger.info(f"[{panel.name}] Rotation set to {rotation * 90}°")
                else:
                    panel.error = "Command not acknowledged"
                    logger.warning(f"[{panel.name}] Rotation command not acknowledged")
                
                return success
                
            except Exception as e:
                panel.error = str(e)
                panel.connected = False
                logger.error(f"[{panel.name}] Rotation error: {e}")
                return False
    
    async def send_image(self, mac: str, png_bytes: bytes, delay: float = None, auto_save: bool = None) -> bool:
        """
        Send an image to the panel.
        
        Args:
            mac: Panel MAC address
            png_bytes: PNG image data (should be 32x32)
            delay: Delay between packets (default: 0.15)
            auto_save: Auto-save to flash (default: use manager setting)
            
        Returns:
            True if image was sent successfully
        """
        panel = await self._ensure_connected(mac)
        if not panel:
            return False
        
        delay = delay or self._command_delay
        should_save = auto_save if auto_save is not None else self._auto_save
        
        async with panel._lock:
            try:
                logger.info(f"[{panel.name}] Sending image ({len(png_bytes)} bytes)")
                await panel.session.send_png(png_bytes, delay=delay)
                
                panel.last_command = "send_image"
                panel.last_command_time = datetime.now()
                panel.error = None
                
                logger.info(f"[{panel.name}] Image sent successfully")
                
                # Auto-save to flash so it persists after disconnect
                if should_save:
                    try:
                        await asyncio.sleep(0.2)  # Small delay before save
                        await panel.session.save_as_startup()
                        logger.info(f"[{panel.name}] Auto-saved to flash")
                    except Exception as save_err:
                        logger.warning(f"[{panel.name}] Auto-save failed: {save_err}")
                
                return True
                
            except Exception as e:
                panel.error = str(e)
                panel.connected = False
                logger.error(f"[{panel.name}] Send image error: {e}")
                return False
    
    async def send_gif(self, mac: str, gif_bytes: bytes, delay: float = None, auto_save: bool = None) -> bool:
        """
        Send an animated GIF to the panel.
        
        NOTE: Auto-save is disabled for GIFs because the save commands
        (EDIT_END) stop the animation and revert to the previous saved state.
        GIFs use a different storage mechanism on the panel.
        
        Args:
            mac: Panel MAC address
            gif_bytes: GIF file bytes
            delay: Delay between frames (default: 0.15)
            auto_save: Ignored for GIFs (always False)
            
        Returns:
            True if GIF was sent successfully
        """
        panel = await self._ensure_connected(mac)
        if not panel:
            return False
        
        delay = delay or self._command_delay
        # NOTE: Auto-save is DISABLED for GIFs - the EDIT_END command stops the animation!
        
        async with panel._lock:
            try:
                logger.info(f"[{panel.name}] Sending GIF ({len(gif_bytes)} bytes)")
                success = await panel.session.send_gif(gif_bytes, delay=delay)
                
                if success:
                    panel.last_command = "send_gif"
                    panel.last_command_time = datetime.now()
                    panel.error = None
                    logger.info(f"[{panel.name}] GIF sent successfully")
                    # No auto-save for GIFs - it breaks the animation!
                else:
                    panel.error = "GIF send failed"
                    logger.warning(f"[{panel.name}] GIF send failed")
                
                return success
                
            except Exception as e:
                panel.error = str(e)
                panel.connected = False
                logger.error(f"[{panel.name}] Send GIF error: {e}")
                return False
    
    async def identify(self, mac: str, number: int = 1) -> bool:
        """
        Flash an identification number on the panel.
        
        Args:
            mac: Panel MAC address
            number: Number to display (1-99)
            
        Returns:
            True if successful
        """
        panel = await self._ensure_connected(mac)
        if not panel:
            return False
        
        # Create a simple identification image with the number
        from PIL import Image, ImageDraw, ImageFont
        import io
        
        img = Image.new('RGB', (32, 32), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Draw number in center
        text = str(number)
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            font = ImageFont.load_default()
        
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (32 - text_width) // 2
        y = (32 - text_height) // 2 - 2
        
        draw.text((x, y), text, fill=(255, 153, 0), font=font)
        
        # Convert to PNG bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        png_bytes = buffer.getvalue()
        
        return await self.send_image(mac, png_bytes)
    
    async def save_as_startup(self, mac: str) -> bool:
        """
        Save current display as startup image.
        
        Args:
            mac: Panel MAC address
            
        Returns:
            True if successful
        """
        panel = await self._ensure_connected(mac)
        if not panel:
            return False
        
        async with panel._lock:
            try:
                logger.info(f"[{panel.name}] Saving as startup image")
                success = await panel.session.save_as_startup()
                
                if success:
                    panel.last_command = "save_startup"
                    panel.last_command_time = datetime.now()
                    panel.error = None
                    logger.info(f"[{panel.name}] Saved as startup image")
                else:
                    panel.error = "Save command not acknowledged"
                    logger.warning(f"[{panel.name}] Save command not acknowledged")
                
                return success
                
            except Exception as e:
                panel.error = str(e)
                logger.error(f"[{panel.name}] Save startup error: {e}")
                return False

    async def set_on_off(self, mac: str, on: bool) -> bool:
        """
        Turn panel display on or off.
        
        Based on iPixel sendLedOnOff command.
        
        Args:
            mac: Panel MAC address
            on: True = on, False = off
            
        Returns:
            True if command was acknowledged
        """
        panel = await self._ensure_connected(mac)
        if not panel:
            return False
        
        async with panel._lock:
            try:
                state = "on" if on else "off"
                logger.info(f"[{panel.name}] Turning display {state}")
                success = await panel.session.set_panel_on_off(on)
                
                if success:
                    panel.last_command = f"on_off:{state}"
                    panel.last_command_time = datetime.now()
                    panel.error = None
                    logger.info(f"[{panel.name}] Display turned {state}")
                else:
                    panel.error = "Command not acknowledged"
                    logger.warning(f"[{panel.name}] On/Off command not acknowledged")
                
                return success
                
            except Exception as e:
                panel.error = str(e)
                panel.connected = False
                logger.error(f"[{panel.name}] On/Off error: {e}")
                return False

    async def delete_all_data(self, mac: str) -> bool:
        """
        Delete all saved data from the panel.
        
        Based on iPixel deleteAllData command.
        
        Args:
            mac: Panel MAC address
            
        Returns:
            True if command was acknowledged
        """
        panel = await self._ensure_connected(mac)
        if not panel:
            return False
        
        async with panel._lock:
            try:
                logger.info(f"[{panel.name}] Deleting all data")
                success = await panel.session.delete_all_data()
                
                if success:
                    panel.last_command = "delete_all"
                    panel.last_command_time = datetime.now()
                    panel.error = None
                    logger.info(f"[{panel.name}] All data deleted")
                else:
                    panel.error = "Command not acknowledged"
                    logger.warning(f"[{panel.name}] Delete command not acknowledged")
                
                return success
                
            except Exception as e:
                panel.error = str(e)
                logger.error(f"[{panel.name}] Delete all error: {e}")
                return False
    
    # =========================================================================
    # Scanning
    # =========================================================================
    
    async def scan(self, timeout: float = 10.0) -> List[Dict[str, str]]:
        """
        Scan for nearby LED panels.
        
        Args:
            timeout: Scan timeout in seconds
            
        Returns:
            List of found panels with mac and name
        """
        from bleak import BleakScanner
        
        logger.info(f"Scanning for panels ({timeout}s)...")
        
        found = []
        
        try:
            devices = await BleakScanner.discover(timeout=timeout)
            
            for device in devices:
                # Look for panels by name pattern
                name = device.name or ""
                if name.startswith("Pixoo") or name.startswith("BK-") or "LED" in name.upper():
                    found.append({
                        "mac": device.address.upper(),
                        "name": name,
                    })
                    logger.info(f"Found panel: {name} ({device.address})")
            
            logger.info(f"Scan complete: found {len(found)} panels")
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
        
        return found


# Global manager instance
_manager: Optional[PanelManager] = None


def get_manager() -> PanelManager:
    """Get the global Panel Manager instance."""
    global _manager
    if _manager is None:
        _manager = PanelManager()
    return _manager

