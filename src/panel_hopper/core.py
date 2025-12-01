"""
Core BLE Communication Module

Handles Bluetooth Low Energy scanning, connection, and image transmission
to BK-Light LED panels.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Callable

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

# Import the BK-Light toolkit
# Try multiple import paths for flexibility
try:
    from bk_light.display_session import BleDisplaySession
except ImportError:
    # Try vendor path
    vendor_path = Path(__file__).parent.parent.parent / "vendor" / "bk_light"
    if vendor_path.exists():
        sys.path.insert(0, str(vendor_path.parent))
        from bk_light.display_session import BleDisplaySession
    else:
        # Try project root
        root_path = Path(__file__).parent.parent.parent.parent / "Bk-Light-AppBypass"
        if root_path.exists():
            sys.path.insert(0, str(root_path))
            from bk_light.display_session import BleDisplaySession
        else:
            raise ImportError(
                "Could not find bk_light module. Please ensure the Bk-Light-AppBypass "
                "toolkit is installed in vendor/bk_light/ or Bk-Light-AppBypass/"
            )

logger = logging.getLogger(__name__)

# Panel identification prefix
PANEL_NAME_PREFIX = "LED_BLE_"


async def scan_for_panels(
    timeout: float = 10.0,
    name_prefix: str = PANEL_NAME_PREFIX,
    progress_callback: Optional[Callable[[str, str], None]] = None
) -> list[tuple[str, str]]:
    """
    Scan for BLE devices that match the LED panel naming pattern.
    
    Args:
        timeout: How long to scan in seconds.
        name_prefix: Device name prefix to filter for (default: "LED_BLE_")
        progress_callback: Optional callback(mac, name) called for each discovery.
        
    Returns:
        List of (mac_address, device_name) tuples for discovered panels.
    """
    logger.info(f"Scanning for BLE devices for {timeout} seconds...")
    logger.info(f"Looking for devices starting with '{name_prefix}'")
    
    discovered: list[tuple[str, str]] = []
    
    try:
        devices: list[BLEDevice] = await BleakScanner.discover(timeout=timeout)
        
        for device in devices:
            name = device.name or ""
            if name.startswith(name_prefix):
                discovered.append((device.address, name))
                logger.info(f"  Found panel: {name} ({device.address})")
                if progress_callback:
                    progress_callback(device.address, name)
        
        if not discovered:
            logger.warning("No LED panels found during scan")
        else:
            logger.info(f"Scan complete: found {len(discovered)} panel(s)")
            
    except Exception as e:
        logger.error(f"BLE scan failed: {e}")
        raise
    
    return discovered


class PersistentSession:
    """
    Manages a persistent BLE connection for streaming frames.
    """
    
    def __init__(self, mac: str, name: str = "", log_notifications: bool = False):
        self.mac = mac
        self.name = name or mac
        self.log_notifications = log_notifications
        self.session: Optional[BleDisplaySession] = None
        self.connected = False
        self._lock = asyncio.Lock()
    
    async def connect(self, timeout: float = 30.0) -> bool:
        """Connect to the panel."""
        async with self._lock:
            if self.connected and self.session:
                return True
            
            try:
                self.session = BleDisplaySession(
                    address=self.mac,
                    auto_reconnect=True,
                    max_retries=3,
                    scan_timeout=15,
                    log_notifications=self.log_notifications,
                )
                await asyncio.wait_for(self.session._connect(), timeout=timeout)
                self.connected = True
                logger.info(f"[{self.name}] Persistent connection established")
                return True
            except Exception as e:
                logger.error(f"[{self.name}] Failed to connect: {e}")
                self.connected = False
                return False
    
    async def send_frame(self, png_bytes: bytes, delay: float = 0.1) -> bool:
        """Send a single frame. Assumes already connected."""
        if not self.connected or not self.session:
            return False
        
        try:
            await self.session.send_png(png_bytes, delay=delay)
            return True
        except Exception as e:
            logger.error(f"[{self.name}] Frame send error: {e}")
            self.connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from the panel."""
        async with self._lock:
            if self.session:
                try:
                    await self.session._safe_disconnect()
                except Exception:
                    pass
                self.session = None
            self.connected = False
            logger.info(f"[{self.name}] Disconnected")


# Global persistent sessions (for ≤3 panels)
PERSISTENT_SESSIONS: dict[str, PersistentSession] = {}


async def get_persistent_session(mac: str, name: str = "") -> Optional[PersistentSession]:
    """Get or create a persistent session for a panel."""
    mac = mac.upper()
    if mac not in PERSISTENT_SESSIONS:
        if len(PERSISTENT_SESSIONS) >= 3:
            # Too many sessions, don't add more
            return None
        PERSISTENT_SESSIONS[mac] = PersistentSession(mac, name)
    
    session = PERSISTENT_SESSIONS[mac]
    if not session.connected:
        await session.connect()
    
    return session if session.connected else None


async def close_all_sessions():
    """Close all persistent sessions."""
    for session in PERSISTENT_SESSIONS.values():
        await session.disconnect()
    PERSISTENT_SESSIONS.clear()


class PanelController:
    """
    Controller for sending images to LED panels.
    
    This class wraps the BleDisplaySession and provides a high-level interface
    for sending images with automatic retries and proper cleanup.
    """
    
    def __init__(
        self,
        timeout: float = 30.0,
        delay: float = 0.15,
        retries: int = 3,
        panel_delay: float = 1.5,
        log_notifications: bool = False,
        use_persistent: bool = True
    ):
        """
        Initialize the panel controller.
        
        Args:
            timeout: Timeout for each send operation in seconds.
            delay: Delay between BLE writes (for stability).
            retries: Number of retry attempts per panel.
            panel_delay: Delay between sending to different panels.
            log_notifications: Whether to log BLE notifications.
            use_persistent: Try to use persistent connections for faster sends.
        """
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.panel_delay = panel_delay
        self.log_notifications = log_notifications
        self.use_persistent = use_persistent
    
    async def send_to_panel(
        self,
        mac: str,
        png_bytes: bytes,
        name: Optional[str] = None,
        progress_callback: Optional[Callable[[str, str, bool], None]] = None
    ) -> tuple[bool, str]:
        """
        Send an image to a single panel with retries.
        
        Args:
            mac: Bluetooth MAC address of the panel.
            png_bytes: PNG image data to send.
            name: Optional friendly name for logging.
            progress_callback: Optional callback(mac, status, success) for progress.
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        display_name = name or mac
        
        # Try persistent connection first (for ≤3 panels)
        if self.use_persistent:
            persistent = await get_persistent_session(mac, display_name)
            if persistent and persistent.connected:
                logger.info(f"[{display_name}] Using persistent connection...")
                if progress_callback:
                    progress_callback(mac, "sending", False)
                
                success = await persistent.send_frame(png_bytes, delay=self.delay)
                if success:
                    logger.info(f"[{display_name}] Sent successfully!")
                    if progress_callback:
                        progress_callback(mac, "success", True)
                    return True, "OK"
                else:
                    logger.warning(f"[{display_name}] Persistent send failed, trying fresh connection...")
        
        # Fall back to fresh connection
        for attempt in range(1, self.retries + 1):
            if attempt > 1:
                logger.info(f"[{display_name}] Retry {attempt}/{self.retries}...")
            else:
                logger.info(f"[{display_name}] Connecting...")
            
            if progress_callback:
                progress_callback(mac, "connecting", False)
            
            session = None
            try:
                async def send_with_session():
                    nonlocal session
                    session = BleDisplaySession(
                        address=mac,
                        auto_reconnect=False,
                        max_retries=1,
                        scan_timeout=15,
                        log_notifications=self.log_notifications,
                    )
                    await session._connect()
                    logger.info(f"[{display_name}] Connected, sending...")
                    
                    if progress_callback:
                        progress_callback(mac, "sending", False)
                    
                    await session.send_png(png_bytes, delay=self.delay)
                    
                    # Wait for panel to process image before disconnect
                    await asyncio.sleep(0.5)
                    
                    logger.info(f"[{display_name}] Sent successfully!")
                    return True
                
                result = await asyncio.wait_for(
                    send_with_session(),
                    timeout=self.timeout
                )
                
                if progress_callback:
                    progress_callback(mac, "success", True)
                
                return True, "OK"
                
            except asyncio.TimeoutError:
                logger.error(f"[{display_name}] Timeout!")
                if attempt == self.retries:
                    if progress_callback:
                        progress_callback(mac, "timeout", False)
                    return False, "Connection timeout"
                    
            except Exception as e:
                error_msg = str(e)
                logger.error(f"[{display_name}] Error: {error_msg}")
                if attempt == self.retries:
                    if progress_callback:
                        progress_callback(mac, f"error: {error_msg}", False)
                    return False, error_msg
                    
            finally:
                # Always try to disconnect cleanly (unless using persistent)
                if session and not self.use_persistent:
                    try:
                        await session._safe_disconnect()
                    except Exception:
                        pass
                
                # Delay between attempts/panels for BLE stability
                await asyncio.sleep(self.panel_delay)
        
        return False, "Max retries exceeded"
    
    async def send_to_multiple(
        self,
        panels: list[tuple[str, str, bytes]],  # [(mac, name, png_bytes), ...]
        progress_callback: Optional[Callable[[str, str, bool], None]] = None
    ) -> list[tuple[str, bool, str]]:
        """
        Send images to multiple panels sequentially.
        
        Args:
            panels: List of (mac, name, png_bytes) tuples.
            progress_callback: Optional callback for progress updates.
            
        Returns:
            List of (mac, success, message) tuples.
        """
        results = []
        
        for mac, name, png_bytes in panels:
            success, message = await self.send_to_panel(
                mac, png_bytes, name, progress_callback
            )
            results.append((mac, success, message))
        
        return results
    
    async def send_same_to_all(
        self,
        macs: list[tuple[str, str]],  # [(mac, name), ...]
        png_bytes: bytes,
        progress_callback: Optional[Callable[[str, str, bool], None]] = None
    ) -> list[tuple[str, bool, str]]:
        """
        Send the same image to multiple panels.
        
        Args:
            macs: List of (mac, name) tuples.
            png_bytes: PNG image data to send to all panels.
            progress_callback: Optional callback for progress updates.
            
        Returns:
            List of (mac, success, message) tuples.
        """
        panels = [(mac, name, png_bytes) for mac, name in macs]
        return await self.send_to_multiple(panels, progress_callback)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging for panel operations."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

