import asyncio
import binascii
import os
from io import BytesIO
from typing import Optional
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from PIL import Image, ImageEnhance

DEFAULT_ADDRESS = os.getenv("BK_LIGHT_ADDRESS")
UUID_WRITE = "0000fa02-0000-1000-8000-00805f9b34fb"
UUID_NOTIFY = "0000fa03-0000-1000-8000-00805f9b34fb"
HANDSHAKE_FIRST = bytes.fromhex("08 00 01 80 0E 06 32 00")
HANDSHAKE_SECOND = bytes.fromhex("04 00 05 80")
ACK_STAGE_ONE = bytes.fromhex("0C 00 01 80 81 06 32 00 00 01 00 01")
ACK_STAGE_TWO = bytes.fromhex("08 00 05 80 0B 03 07 02")
ACK_STAGE_THREE = bytes.fromhex("05 00 02 00 03")
FRAME_VALIDATION = bytes.fromhex("05 00 00 01 00")

# ============================================================================
# Panel control commands (from iPixel APK decompilation)
# Format: [length_low, length_high, command_id_low, command_id_high, value(s)]
# ============================================================================

# Basic control commands (confirmed from BaseSend.java)
CMD_BRIGHTNESS = bytes.fromhex("05 00 04 80")       # + 1 byte value (0x00-0x64 = 0-100%)
CMD_ROTATION = bytes.fromhex("05 00 06 80")         # + 1 byte value (0-3 = 0°, 90°, 180°, 270°)
CMD_ON_OFF = bytes.fromhex("05 00 07 01")           # + 1 byte (0=off, 1=on)
CMD_DELETE_ALL = bytes.fromhex("04 00 03 80")       # Delete all saved data
CMD_DIY_MODE = bytes.fromhex("05 00 04 01")         # + 1 byte mode value

# Display mode and save commands
CMD_EDIT_END = bytes.fromhex("05 00 04 01 00")      # End editing / commit display
CMD_SAVE_PREPARE = bytes.fromhex("07 00 02 01 01 00 01")  # Prepare save to flash
CMD_SAVE_COMMIT = bytes.fromhex("07 00 02 01 01 00 02")   # Commit save to flash
CMD_DISPLAY_MODE = bytes.fromhex("07 00 08 80 01 00")     # + 1 byte mode (01=static, 03=animation)

# Data types for image/GIF packets (from SendCore.java getDataType())
# TYPE_CAMERA = 0 → {0x00, 0x00}
# TYPE_IMAGE = 1  → {0x01, 0x00}
# TYPE_VIDEO = 2  → {0x02, 0x00}
# TYPE_GIF = 3    → {0x03, 0x00}
# TYPE_TEXT = 4   → {0x00, 0x01}
DATA_TYPE_IMAGE = bytes([0x02, 0x00])  # We use 0x02 for static images (video/stream)
DATA_TYPE_GIF = bytes([0x03, 0x00])    # GIF animation type

# Expected ACK responses for panel commands
ACK_BRIGHTNESS = bytes.fromhex("05 00 04 80 01")
ACK_ROTATION = bytes.fromhex("05 00 06 80 01")
ACK_ON_OFF = bytes.fromhex("05 00 07 01 01")
ACK_SAVE = bytes.fromhex("05 00 02 01 01")
ACK_DISPLAY_MODE = bytes.fromhex("05 00 08 80 01")


def bytes_to_hex(data: bytes) -> str:
    return "-".join(f"{value:02X}" for value in data)


def build_frame(png_bytes: bytes, is_gif_frame: bool = False, frame_index: int = 0) -> bytes:
    """
    Build a frame packet following iPixel protocol.
    
    Packet structure (from SendCore.java payload function):
    [0-1]   Total packet length (little endian)
    [2-3]   Data type: 0x02,0x00 for image, 0x03,0x00 for GIF
    [4]     Option: 0=FIRST_SEND, 2=CONTINUE_SEND
    [5-8]   Frame/data length (4 bytes, little endian)
    [9-12]  CRC32 of image data (4 bytes, little endian)
    [13]    Extra byte: 0x00 for images, 0x02 for GIF animation
    [14]    Channel index / 0x65 for single channel
    [15+]   Pixel data
    """
    data_length = len(png_bytes)
    total_length = data_length + 15
    
    frame = bytearray()
    # [0-1] Total length
    frame += total_length.to_bytes(2, "little")
    
    # [2-3] Data type
    if is_gif_frame:
        frame += DATA_TYPE_GIF  # 0x03, 0x00
    else:
        frame += DATA_TYPE_IMAGE  # 0x02, 0x00
    
    # [4] Option: 0 = first/single, 2 = continuation
    if frame_index > 0:
        frame.append(0x02)  # CONTINUE_SEND
    else:
        frame.append(0x00)  # FIRST_SEND
    
    # [5-8] Data length (4 bytes)
    frame += data_length.to_bytes(4, "little")
    
    # [9-12] CRC32 of the image data
    frame += binascii.crc32(png_bytes).to_bytes(4, "little")
    
    # [13] Extra byte: 0x02 for GIF (animation indicator), 0x00 for static
    if is_gif_frame:
        frame.append(0x02)  # Animation flag from iPixel
    else:
        frame.append(0x00)
    
    # [14] Channel index (0x65 = 101 = single channel mode)
    frame.append(0x65)
    
    # [15+] Pixel data
    frame += png_bytes
    
    return bytes(frame)


def adjust_image(png_bytes: bytes, rotation: int, brightness: float) -> bytes:
    image = Image.open(BytesIO(png_bytes)).convert("RGB")
    if rotation:
        image = image.rotate(rotation % 360, expand=False)
    if brightness != 1.0:
        enhancer = ImageEnhance.Brightness(image)
        image = enhancer.enhance(brightness)
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


class AckWatcher:
    """
    Watches for BLE notification ACKs from the panel.
    
    The panel sends specific byte sequences to acknowledge different commands.
    This class tracks those ACKs to ensure reliable communication.
    """
    
    def __init__(self, verbose: bool) -> None:
        self.stage_one = asyncio.Event()
        self.stage_two = asyncio.Event()
        self.stage_three = asyncio.Event()
        self.command_ack = asyncio.Event()  # For panel commands
        self.frame_ack = asyncio.Event()    # For GIF chunk ACKs (0500 0300 01)
        self.gif_complete = asyncio.Event() # For GIF complete ACK (0500 0300 03)
        self.last_response: Optional[bytes] = None
        self.verbose = verbose

    def reset(self) -> None:
        self.stage_one.clear()
        self.stage_two.clear()
        self.stage_three.clear()
        self.command_ack.clear()
        self.frame_ack.clear()
        self.gif_complete.clear()
        self.last_response = None

    def handler(self, _sender: int, data: bytearray) -> None:
        payload = bytes(data)
        if self.verbose:
            print("NOTIF", bytes_to_hex(payload))
        
        # Standard handshake ACKs
        if payload == ACK_STAGE_ONE:
            self.stage_one.set()
        elif payload == ACK_STAGE_TWO:
            self.stage_two.set()
        elif payload == ACK_STAGE_THREE:
            self.stage_three.set()
        # Handle GIF data ACKs (0500 0300 XX)
        # - 0500 0300 01 = chunk received
        # - 0500 0300 03 = GIF complete
        elif len(payload) == 5 and payload[0:4] == bytes([0x05, 0x00, 0x03, 0x00]):
            if payload[4] == 0x01:
                self.frame_ack.set()
                if self.verbose:
                    print("GIF_CHUNK_ACK")
            elif payload[4] == 0x03:
                self.gif_complete.set()
                self.frame_ack.set()  # Also set frame_ack for waiting code
                if self.verbose:
                    print("GIF_COMPLETE_ACK")
        # Handle panel command ACKs based on command ID bytes [2:4]
        # Commands from iPixel:
        # - 0x04 0x80: Brightness
        # - 0x06 0x80: Rotation  
        # - 0x07 0x01: On/Off
        # - 0x02 0x01: Save
        # - 0x08 0x80: Display mode
        # - 0x04 0x01: Edit end / DIY mode
        # - 0x03 0x80: Delete all
        elif len(payload) >= 4:
            cmd_id = payload[2:4]
            if cmd_id in [b'\x04\x80', b'\x06\x80', b'\x07\x01', b'\x02\x01', 
                          b'\x08\x80', b'\x04\x01', b'\x03\x80']:
                self.last_response = payload
                self.command_ack.set()
                if self.verbose:
                    print(f"CMD_ACK: {bytes_to_hex(cmd_id)}")


async def wait_for_ack(event: asyncio.Event, label: str, verbose: bool) -> None:
    try:
        await asyncio.wait_for(event.wait(), timeout=5.0)
        if verbose:
            print(label + "_OK")
    except asyncio.TimeoutError as timeout_error:
        if verbose:
            print(label + "_TIMEOUT")
        raise timeout_error


class BleDisplaySession:
    # Class-level safe mode tracking (shared across instances per adapter)
    _adapter_safe_mode: dict = {}  # adapter_address -> bool
    _safe_mode_callback = None  # Callback when entering safe mode
    
    def __init__(
        self,
        address: Optional[str] = None,
        auto_reconnect: bool = True,
        reconnect_delay: float = 2.0,
        rotation: int = 0,
        brightness: float = 1.0,
        mtu: int = 512,
        log_notifications: bool = False,
        max_retries: int = 3,
        scan_timeout: float = 6.0,
    ) -> None:
        resolved = address or DEFAULT_ADDRESS
        if not resolved:
            raise ValueError("Missing target address. Pass it explicitly or set BK_LIGHT_ADDRESS.")
        self.address = resolved
        self.auto_reconnect = auto_reconnect
        self.reconnect_delay = reconnect_delay
        self.rotation = rotation
        self.brightness = brightness
        self.mtu = mtu
        self.log_notifications = log_notifications
        self.max_retries = max_retries
        self.scan_timeout = scan_timeout
        self.client: Optional[BleakClient] = None
        self.watcher = AckWatcher(log_notifications)
        self.adapter_address: Optional[str] = None  # Will be set after connection
        self.adapter_name: Optional[str] = None     # Adapter name if available
    
    @property
    def safe_mode(self) -> bool:
        """Check if we're in safe mode for current adapter."""
        if self.adapter_address:
            return BleDisplaySession._adapter_safe_mode.get(self.adapter_address, False)
        return False
    
    @safe_mode.setter
    def safe_mode(self, value: bool):
        """Set safe mode for current adapter."""
        if self.adapter_address:
            was_safe = BleDisplaySession._adapter_safe_mode.get(self.adapter_address, False)
            BleDisplaySession._adapter_safe_mode[self.adapter_address] = value
            # Notify callback when entering safe mode
            if value and not was_safe and BleDisplaySession._safe_mode_callback:
                BleDisplaySession._safe_mode_callback(self.adapter_address, self.adapter_name)
    
    @classmethod
    def set_safe_mode_callback(cls, callback):
        """Set callback for when safe mode is activated. callback(adapter_address, adapter_name)"""
        cls._safe_mode_callback = callback
    
    @classmethod
    def reset_safe_mode(cls, adapter_address: str = None):
        """Reset safe mode for adapter (try fast mode again)."""
        if adapter_address:
            cls._adapter_safe_mode.pop(adapter_address, None)
        else:
            cls._adapter_safe_mode.clear()
    
    async def _safe_write(self, data: bytes, chunk_name: str = "data") -> None:
        """
        Write to BLE characteristic with automatic fallback to safe mode.
        
        If response=False fails, falls back to response=True and enables safe mode
        for this adapter going forward.
        """
        if self.safe_mode:
            # Already in safe mode - use response=True directly
            await self.client.write_gatt_char(UUID_WRITE, data, response=True)
            return
        
        try:
            await self.client.write_gatt_char(UUID_WRITE, data, response=False)
        except Exception as e:
            # Failed! Enable safe mode and retry with response=True
            if self.log_notifications:
                print(f"BLE_SAFE_MODE: write_gatt_char failed ({e}), enabling safe mode")
            self.safe_mode = True
            await self.client.write_gatt_char(UUID_WRITE, data, response=True)

    async def _safe_disconnect(self) -> None:
        if self.client is None:
            return
        try:
            if self.client.is_connected:
                try:
                    await self.client.stop_notify(UUID_NOTIFY)
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            await self.client.disconnect()
        except Exception:
            pass
        finally:
            self.client = None
            self._handshake_done = False  # Reset handshake flag on disconnect

    async def _connect(self) -> None:
        attempt = 0
        while True:
            attempt += 1
            try:
                if self.client and self.client.is_connected:
                    return
                if self.client:
                    await self._safe_disconnect()
                try:
                    device = await BleakScanner.find_device_by_address(
                        self.address, timeout=self.scan_timeout, cached=False
                    )
                except TypeError:
                    device = await BleakScanner.find_device_by_address(
                        self.address, timeout=self.scan_timeout
                    )
                if device is None:
                    try:
                        device = await BleakScanner.find_device_by_address(
                            self.address, timeout=self.scan_timeout, cached=True
                        )
                    except TypeError:
                        device = await BleakScanner.find_device_by_address(
                            self.address, timeout=self.scan_timeout
                        )
                if device is None:
                    raise BleakError(f"Device with address {self.address} was not found")
                self.client = BleakClient(device)
                self.watcher = AckWatcher(self.log_notifications)
                await self.client.connect()
                if not self.client.is_connected:
                    raise ConnectionError("Bluetooth link failed")
                if self.mtu:
                    try:
                        await self.client.exchange_mtu(self.mtu)
                    except Exception:
                        pass
                await self.client.start_notify(UUID_NOTIFY, self.watcher.handler)
                
                # Try to get adapter info for safe mode tracking
                try:
                    # Use a hash of the BleakClient's backend adapter as identifier
                    # This helps track which adapter is being used
                    import hashlib
                    adapter_id = hashlib.md5(str(id(self.client)).encode()).hexdigest()[:8]
                    self.adapter_address = f"adapter_{adapter_id}"
                    self.adapter_name = "Local Bluetooth Adapter"
                except Exception:
                    self.adapter_address = "default_adapter"
                    self.adapter_name = "Bluetooth Adapter"
                
                return
            except Exception as error:
                if not self.auto_reconnect or attempt > self.max_retries:
                    await self._safe_disconnect()
                    raise error
                await asyncio.sleep(self.reconnect_delay)

    async def _ensure_connected(self) -> None:
        if not self.client or not self.client.is_connected:
            await self._connect()

    async def __aenter__(self) -> "BleDisplaySession":
        await self._connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._safe_disconnect()

    async def send_png(self, png_bytes: bytes, delay: float = 0.2, stop_animation: bool = True) -> None:
        """
        Send a PNG image to the panel.
        
        Based on iPixel BLE analysis:
        1. Stop any running animation first (set display mode to static)
        2. Send CMD_EDIT_END (05 00 04 01 00) before image
        3. Send image data (with header)
        
        Args:
            png_bytes: PNG image data
            delay: Delay between operations
            stop_animation: If True (default), stop any running animation BEFORE sending.
                           This prevents the animation from taking over after the image is sent.
        """
        # IMPORTANT: Stop animation BEFORE sending image, not after!
        # This prevents stored animations from taking over the display.
        if stop_animation:
            if self.log_notifications:
                print("STOP_ANIMATION_BEFORE_SEND")
            await self.set_display_mode(1)  # Static mode
            await asyncio.sleep(0.2)
        
        processed = adjust_image(png_bytes, self.rotation, self.brightness)
        frame = build_frame(processed)
        await self.send_frame(frame, delay, set_static_mode=False)

    async def send_frame(self, frame: bytes, delay: float = 0.2, set_static_mode: bool = False) -> None:
        """
        Send a frame to the panel using iPixel-compatible protocol.
        
        Protocol (from BLE capture analysis):
        1. Handshake (only if not already done in this session)
        2. Send CMD_EDIT_END (05 00 04 01 00)
        3. Send frame data (with header)
        4. Wait for ACK
        5. Optionally set display mode to static
        
        Args:
            frame: Frame data with header
            delay: Delay between operations
            set_static_mode: If True, set display mode 1 after sending
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                await self._ensure_connected()
                
                # Do handshake only if not already done
                if not hasattr(self, '_handshake_done') or not self._handshake_done:
                    self.watcher.reset()
                    await self._safe_write(HANDSHAKE_FIRST, "handshake1")
                    try:
                        await wait_for_ack(self.watcher.stage_one, "HANDSHAKE_STAGE_ONE", self.log_notifications)
                    except asyncio.TimeoutError:
                        if self.log_notifications:
                            print("HANDSHAKE_STAGE_ONE timeout (continuing)")
                    await asyncio.sleep(delay)
                    
                    self.watcher.stage_two.clear()
                    try:
                        await self._safe_write(HANDSHAKE_SECOND, "handshake2")
                        await wait_for_ack(self.watcher.stage_two, "HANDSHAKE_STAGE_TWO", self.log_notifications)
                    except asyncio.TimeoutError:
                        if self.log_notifications:
                            print("HANDSHAKE_STAGE_TWO_SKIPPED")
                    await asyncio.sleep(delay)
                    
                    self._handshake_done = True
                
                # Send CMD_EDIT_END before image (like iPixel does)
                # This command: 05 00 04 01 00
                await self._safe_write(CMD_EDIT_END, "edit_end")
                await asyncio.sleep(0.05)
                
                # Send frame data
                self.watcher.stage_three.clear()
                await self.client.write_gatt_char(UUID_WRITE, frame, response=True)
                
                try:
                    await wait_for_ack(self.watcher.stage_three, "FRAME_ACK", self.log_notifications)
                except asyncio.TimeoutError:
                    if self.log_notifications:
                        print("FRAME_ACK timeout (continuing)")
                
                await asyncio.sleep(delay)
                
                # Optionally set display mode to static
                # Only do this if explicitly requested - don't interrupt animations!
                if set_static_mode:
                    if self.log_notifications:
                        print("Setting display mode to 1 (static)")
                    await self.set_display_mode(1)
                
                return
                
            except (asyncio.TimeoutError, BleakError, ConnectionError) as error:
                self._handshake_done = False
                if not self.auto_reconnect or attempt > self.max_retries:
                    await self._safe_disconnect()
                    raise error
                await self._safe_disconnect()
                await asyncio.sleep(self.reconnect_delay)
            except Exception as error:
                self._handshake_done = False
                if not self.auto_reconnect or attempt > self.max_retries:
                    await self._safe_disconnect()
                    raise error
                await self._safe_disconnect()
                await asyncio.sleep(self.reconnect_delay)

    async def _send_command(self, command: bytes, timeout: float = 2.0) -> bool:
        """Send a simple command and wait for ACK."""
        await self._ensure_connected()
        self.watcher.command_ack.clear()
        self.watcher.last_response = None
        
        if self.log_notifications:
            print("CMD_SEND", bytes_to_hex(command))
        
        await self._safe_write(command, "command")
        
        try:
            await asyncio.wait_for(self.watcher.command_ack.wait(), timeout=timeout)
            if self.log_notifications:
                print("CMD_ACK_OK")
            return True
        except asyncio.TimeoutError:
            if self.log_notifications:
                print("CMD_ACK_TIMEOUT")
            return False

    async def set_panel_brightness(self, value: int) -> bool:
        """
        Set the panel's hardware brightness.
        
        Args:
            value: Brightness level 0-100
            
        Returns:
            True if command was acknowledged
        """
        value = max(0, min(100, value))  # Clamp to 0-100
        command = CMD_BRIGHTNESS + bytes([value])
        return await self._send_command(command)

    async def set_panel_rotation(self, rotation: int) -> bool:
        """
        Set the panel's display rotation.
        
        Args:
            rotation: 0=0°, 1=90°, 2=180°, 3=270°
            
        Returns:
            True if command was acknowledged
        """
        rotation = rotation % 4  # Ensure 0-3
        command = CMD_ROTATION + bytes([rotation])
        return await self._send_command(command)

    async def save_as_startup(self) -> bool:
        """
        Save the currently displayed image as the startup/idle image.
        
        The image will persist and show when the panel powers on or
        when there's no active BLE connection.
        
        Returns:
            True if save commands were acknowledged
        """
        # NOTE: We don't clear existing data here - the image should already be
        # on screen and we just want to save it. Clearing would delete our image!
        
        # Send end editing command
        if self.log_notifications:
            print("EDIT_END")
        result1 = await self._send_command(CMD_EDIT_END)
        
        if not result1:
            if self.log_notifications:
                print("EDIT_END_FAILED (continuing anyway)")
        
        await asyncio.sleep(0.2)
        
        # Send prepare save command
        if self.log_notifications:
            print("SAVE_PREPARE")
        result2 = await self._send_command(CMD_SAVE_PREPARE, timeout=3.0)
        
        if not result2:
            if self.log_notifications:
                print("SAVE_PREPARE_FAILED")
            # Continue anyway - some panels might not ACK
        
        await asyncio.sleep(0.2)
        
        # Send commit save command
        if self.log_notifications:
            print("SAVE_COMMIT")
        result3 = await self._send_command(CMD_SAVE_COMMIT, timeout=3.0)
        
        if self.log_notifications:
            if result3:
                print("SAVE_COMPLETE")
            else:
                print("SAVE_COMMIT_FAILED")
        
        return result2 or result3  # Return true if at least one worked

    async def set_display_mode(self, mode: int) -> bool:
        """
        Set the display mode.
        
        Args:
            mode: 1=static image, 3=animation/GIF mode
            
        Returns:
            True if command was acknowledged
        """
        command = CMD_DISPLAY_MODE + bytes([mode])
        if self.log_notifications:
            print(f"DISPLAY_MODE: {mode}")
        return await self._send_command(command)

    async def set_panel_on_off(self, on: bool) -> bool:
        """
        Turn the panel display on or off.
        
        From iPixel: sendLedOnOff in BaseSend.java
        Command: {5, 0, 7, 1, value}
        
        Args:
            on: True = on, False = off
            
        Returns:
            True if command was acknowledged
        """
        value = 1 if on else 0
        command = CMD_ON_OFF + bytes([value])
        if self.log_notifications:
            print(f"PANEL_ON_OFF: {value}")
        return await self._send_command(command)

    async def delete_all_data(self) -> bool:
        """
        Delete all saved data from the panel.
        
        From iPixel: deleteAllData in BaseSend.java
        Command: {4, 0, 3, 0x80}
        
        Returns:
            True if command was acknowledged
        """
        if self.log_notifications:
            print("DELETE_ALL_DATA")
        return await self._send_command(CMD_DELETE_ALL)

    async def send_gif(self, gif_bytes: bytes, delay: float = 0.05) -> bool:
        """
        Send an animated GIF to the panel using iPixel protocol.
        
        IMPORTANT: Based on BLE capture analysis, iPixel sends the RAW GIF file
        to the panel, NOT individual PNG frames. The panel parses the GIF internally!
        
        The GIF is automatically resized to 32x32 to fit within BLE packet limits.
        
        Protocol (from BLE capture):
        1. Connect and handshake
        2. Resize GIF to 32x32 (panel size)
        3. Build packet with header + optimized GIF bytes
        4. Send packet in chunks (BLE MTU limit)
        5. Set display mode 3 (animation) to start playback
        
        Packet structure:
        [0-1]   Total packet length (little endian, max 65535)
        [2-3]   Data type: 0x03,0x00 for GIF
        [4]     Option: 0=FIRST_SEND
        [5-8]   Data length (4 bytes, little endian)
        [9-12]  CRC32 of GIF data (4 bytes, little endian)
        [13]    Extra byte: 0x00
        [14]    Channel: 0x65
        [15+]   Raw GIF file data
        
        Args:
            gif_bytes: Raw GIF file bytes
            delay: Delay between packet chunks
            
        Returns:
            True if GIF was sent successfully
        """
        try:
            # Verify it's a valid GIF
            if gif_bytes[:3] != b'GIF':
                if self.log_notifications:
                    print("GIF: Not a valid GIF file, trying as image")
                # Try to convert and send as static
                img = Image.open(BytesIO(gif_bytes))
                buf = BytesIO()
                img.convert('RGB').resize((32, 32), Image.Resampling.LANCZOS).save(buf, format='PNG')
                await self.send_png(buf.getvalue(), 0.1)
                return True
            
            # Check if it's animated
            gif = Image.open(BytesIO(gif_bytes))
            n_frames = getattr(gif, 'n_frames', 1)
            is_animated = getattr(gif, 'is_animated', False)
            
            if self.log_notifications:
                print(f"GIF: Original {len(gif_bytes)} bytes, {n_frames} frames, animated={is_animated}")
            
            # For static GIFs, just send as regular image
            if not is_animated or n_frames == 1:
                if self.log_notifications:
                    print("GIF: Static/single frame, sending as image")
                buf = BytesIO()
                gif.convert('RGB').resize((32, 32), Image.Resampling.LANCZOS).save(buf, format='PNG')
                await self.send_png(buf.getvalue(), 0.1)
                return True
            
            # Check if GIF is already 32x32 or smaller (iPixel GIFs are pre-optimized!)
            width, height = gif.size
            needs_resize = width > 32 or height > 32
            
            if not needs_resize and len(gif_bytes) < 50000:
                # GIF is already small enough - use original bytes directly!
                # This preserves iPixel's optimization
                if self.log_notifications:
                    print(f"GIF: Already {width}x{height}, using original bytes (no resize needed)")
                gif_data = gif_bytes
            else:
                # === Resize GIF to 32x32 for the panel ===
                if self.log_notifications:
                    print(f"GIF: Resizing {n_frames} frames from {width}x{height} to 32x32...")
                
                frames = []
                durations = []
                
                for i in range(n_frames):
                    gif.seek(i)
                    
                    # Get frame duration (in ms)
                    duration = gif.info.get('duration', 100)
                    durations.append(duration)
                    
                    # Convert and resize frame - use RGB then P for better compatibility
                    frame = gif.convert('RGBA')
                    frame = frame.resize((32, 32), Image.Resampling.LANCZOS)
                    
                    # Convert to palette mode (P) like iPixel GIFs use
                    # This creates a more compatible format for the panel
                    frame_rgb = frame.convert('RGB')
                    frame_p = frame_rgb.convert('P', palette=Image.Palette.ADAPTIVE, colors=256)
                    frames.append(frame_p)
                
                # Create GIF with settings that match iPixel format better
                output = BytesIO()
                frames[0].save(
                    output,
                    format='GIF',
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=0,  # Loop forever
                    optimize=False,  # Don't optimize - can cause issues with some decoders
                    disposal=0  # No disposal (simpler, more compatible)
                )
                gif_data = output.getvalue()
                
                if self.log_notifications:
                    print(f"GIF: Resized to {len(gif_data)} bytes ({len(gif_bytes) - len(gif_data)} bytes saved)")
            
            # If too many frames/too large, reduce frames for better performance
            # (chunking handles size, but fewer frames = faster send + better playback)
            # Only do this if we created frames (i.e., we resized the GIF)
            max_reasonable_size = 50000  # Keep GIFs under 50KB for smooth BLE transfer
            
            # If too large and we have frames to reduce, try reducing frames
            while needs_resize and len(gif_data) > max_reasonable_size and len(frames) > 10:
                if self.log_notifications:
                    print(f"GIF: Too large ({len(gif_data)} bytes), reducing frames from {len(frames)}...")
                
                # Skip every other frame
                frames = frames[::2]
                durations = [d * 2 for d in durations[::2]]  # Double duration to maintain speed
                
                # Re-encode with compatible settings
                output = BytesIO()
                frames[0].save(
                    output,
                    format='GIF',
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=0,
                    optimize=False,
                    disposal=0
                )
                gif_data = output.getvalue()
                
                if self.log_notifications:
                    print(f"GIF: Reduced to {len(frames)} frames, {len(gif_data)} bytes")
            
            # If still too large and we have frames, try reducing colors
            if needs_resize and len(gif_data) > max_reasonable_size:
                if self.log_notifications:
                    print(f"GIF: Still too large ({len(gif_data)} bytes), reducing colors...")
                
                # Convert to P mode with limited palette before saving
                output = BytesIO()
                p_frames = []
                for f in frames:
                    # Convert to P mode with 64 colors (frames are already P mode now)
                    p_frame = f.convert('RGB').convert('P', palette=Image.Palette.ADAPTIVE, colors=64)
                    p_frames.append(p_frame)
                
                p_frames[0].save(
                    output,
                    format='GIF',
                    save_all=True,
                    append_images=p_frames[1:],
                    duration=durations,
                    loop=0,
                    optimize=False,
                    disposal=0
                )
                gif_data = output.getvalue()
                
                if self.log_notifications:
                    print(f"GIF: After color reduction: {len(gif_data)} bytes")
            
            # Note: Chunking now handles large GIFs, no need for single-frame fallback
            
            if self.log_notifications:
                frame_count = len(frames) if needs_resize else n_frames
                print(f"GIF: Final size: {len(gif_data)} bytes, {frame_count} frames")
            
            # === Build GIF packets (split into chunks like iPixel does) ===
            # iPixel uses 12KB chunks for large GIFs
            CHUNK_SIZE = 12288  # 12KB per chunk (from iPixel APK)
            total_gif_length = len(gif_data)
            crc = binascii.crc32(gif_data) & 0xFFFFFFFF
            
            # Calculate number of chunks
            num_chunks = (total_gif_length + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            if self.log_notifications:
                print(f"GIF: Splitting into {num_chunks} chunks of max {CHUNK_SIZE} bytes")
            
            # Build all chunk packets
            chunk_packets = []
            for chunk_idx in range(num_chunks):
                start = chunk_idx * CHUNK_SIZE
                end = min(start + CHUNK_SIZE, total_gif_length)
                chunk_data = gif_data[start:end]
                
                # Header for this chunk (matching iPixel protocol exactly)
                # From BLE capture: frame_length is TOTAL GIF size, not chunk size
                chunk_length = len(chunk_data) + 15  # chunk data + header
                header = bytearray()
                header += chunk_length.to_bytes(2, "little")      # [0-1] This chunk's total length (header + data)
                header += bytes([0x03, 0x00])                     # [2-3] Data type: GIF
                header.append(0x00 if chunk_idx == 0 else 0x02)   # [4] Option: 0=first, 2=continue
                header += total_gif_length.to_bytes(4, "little")  # [5-8] Frame length = TOTAL GIF size
                header += crc.to_bytes(4, "little")               # [9-12] CRC32 of TOTAL GIF data
                header.append(0x00)                               # [13] Extra flag (0x00 like iPixel)
                header.append(0x65)                               # [14] Channel index
                
                chunk_packet = bytes(header) + chunk_data
                chunk_packets.append(chunk_packet)
                
                if self.log_notifications and chunk_idx == 0:
                    print(f"GIF: Chunk 1 header: {' '.join(f'{b:02X}' for b in header)}")
            
            # === Connect (and handshake if needed) ===
            await self._ensure_connected()
            
            # Do handshake only if not already done in this session
            if not hasattr(self, '_handshake_done') or not self._handshake_done:
                self.watcher.reset()
                await self._safe_write(HANDSHAKE_FIRST, "gif_handshake1")
                try:
                    await asyncio.wait_for(self.watcher.stage_one.wait(), timeout=2.0)
                    if self.log_notifications:
                        print("GIF: Handshake 1 OK")
                except asyncio.TimeoutError:
                    if self.log_notifications:
                        print("GIF: Handshake 1 timeout (continuing)")
                
                await asyncio.sleep(delay)
                
                self.watcher.stage_two.clear()
                await self._safe_write(HANDSHAKE_SECOND, "gif_handshake2")
                try:
                    await asyncio.wait_for(self.watcher.stage_two.wait(), timeout=1.0)
                    if self.log_notifications:
                        print("GIF: Handshake 2 OK")
                except asyncio.TimeoutError:
                    pass
                
                await asyncio.sleep(delay)
                self._handshake_done = True
            else:
                if self.log_notifications:
                    print("GIF: Skipping handshake (already done)")
            
            # === Send all GIF chunk packets (with per-chunk ACK like iPixel) ===
            # iPixel waits for ACK after EACH chunk before sending the next
            MTU_SIZE = 500  # BLE MTU for data packets
            total_ble_packets = 0
            
            for chunk_idx, chunk_packet in enumerate(chunk_packets):
                if self.log_notifications:
                    print(f"GIF: Sending data chunk {chunk_idx + 1}/{len(chunk_packets)} ({len(chunk_packet)} bytes)")
                
                # Clear watcher for this chunk's ACK
                self.watcher.frame_ack.clear()
                
                # Send this chunk packet in BLE MTU-sized pieces
                offset = 0
                while offset < len(chunk_packet):
                    ble_chunk = chunk_packet[offset:offset + MTU_SIZE]
                    total_ble_packets += 1
                    
                    # Use _safe_write for automatic fallback
                    await self._safe_write(ble_chunk, f"gif_chunk_{chunk_idx}")
                    
                    offset += MTU_SIZE
                    await asyncio.sleep(0.005)  # Small delay between BLE packets
                
                # Wait for chunk ACK (0500 0300 01) before sending next chunk
                try:
                    await asyncio.wait_for(self.watcher.frame_ack.wait(), timeout=2.0)
                    if self.log_notifications:
                        print(f"GIF: Chunk {chunk_idx + 1} ACK received")
                except asyncio.TimeoutError:
                    if self.log_notifications:
                        print(f"GIF: Chunk {chunk_idx + 1} ACK timeout (continuing)")
                    await asyncio.sleep(0.1)
            
            if self.log_notifications:
                print(f"GIF: Sent {len(chunk_packets)} data chunks in {total_ble_packets} BLE packets")
            
            # Wait for final data ACK (0500 0300 03) which means "all data received"
            if self.log_notifications:
                print("GIF: Waiting for final data ACK (0500 0300 03)...")
            
            await asyncio.sleep(0.5)  # Give panel time to process
            
            # === Set display mode like iPixel does ===
            # iPixel sends mode 01 first, then mode 02 for animation!
            if self.log_notifications:
                print("GIF: Setting display mode 1 (prepare)")
            await self.set_display_mode(1)
            
            await asyncio.sleep(0.3)
            
            if self.log_notifications:
                print("GIF: Setting display mode 2 (animation)")
            success = await self.set_display_mode(2)
            if self.log_notifications:
                print(f"GIF: Display mode set result: {success}")
            
            if self.log_notifications:
                print(f"GIF: Upload complete! Animation should be playing.")
            
            return True
            
        except Exception as e:
            if self.log_notifications:
                print(f"GIF ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False

