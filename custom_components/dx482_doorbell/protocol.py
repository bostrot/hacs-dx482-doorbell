"""Async client for the 2easy DX482 doorbell binary protocol (TCP port 8765).

Wire format (reverse-engineered from the DX482 firmware, confirmed by live testing):

    REQUEST  = struct.pack("<I", dispatcher) + payload      # 4-byte LE dispatcher + payload
    RESPONSE = 10-byte "Format B" header + payload
               [2B op][2B sid][2B rsp][2B len][2B chk] + payload

    rsp == 0x0000  -> query OK, payload holds data
    rsp == 0x0001  -> action acknowledged

The device is single-threaded and unstable: it accepts only one command per TCP
connection and can crash if hammered.  Therefore every command opens a fresh
connection, sends one request, reads the reply, and closes.  All access is
serialised through an ``asyncio.Lock`` and rate-limited by a small cooldown.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

# --- Dispatchers (see INSTRUCTIONS.md from the RE work) --------------------
DISP_DOOR_TRIGGER = 0x06  # momentary unlock pulse; payload 01 00 00 00
DISP_DOOR_UNLOCK = 0x08  # lock(0)/unlock(1); payload NN 00 00 00
DISP_DOORBELL_LIST = 0x09
DISP_JPEG_CAPTURE = 0x0B  # payload 01 00 00 00 -> JPEG frame in payload
DISP_DOOR_STATE = 0x0D  # query current door state
DISP_BATTERY = 0x10
DISP_CALL_LOG = 0x11
DISP_LED = 0x12  # payload 00.. off / 01.. on
DISP_RELAY = 0x15  # payload 00.. off / 01.. on
DISP_WIFI = 0x1B  # RSSI

# Door-state byte -> human label (payload byte, see RE notes).
DOOR_STATES = {
    0x04: "locked_closed",
    0x06: "closed",
    0x09: "open",
    0x0C: "locked",
    0x16: "open_triggered",
    0x40: "closed_autoclosed",
}
# States that mean the latch is currently released / door openable.
OPEN_STATE_BYTES = {0x09, 0x16}


@dataclass
class DX482Response:
    """Parsed response from the doorbell."""

    raw: bytes
    op: int | None = None
    sid: int | None = None
    rsp: int | None = None
    length: int | None = None
    payload: bytes = b""

    @property
    def ok(self) -> bool:
        return self.rsp is not None


class DX482Error(Exception):
    """Base error talking to the doorbell."""


class DX482ConnectionError(DX482Error):
    """Could not reach / talk to the doorbell."""


def _parse(data: bytes) -> DX482Response:
    if len(data) < 10:
        # Short reply: still return raw so callers can inspect it.
        return DX482Response(raw=data, payload=data)
    op, sid, rsp, length, _chk = struct.unpack_from("<HHHHH", data, 0)
    return DX482Response(
        raw=data,
        op=op,
        sid=sid,
        rsp=rsp,
        length=length,
        payload=data[10:],
    )


def extract_jpeg(data: bytes) -> bytes | None:
    """Return the first embedded JPEG frame (SOI..EOI) in ``data`` if any."""
    start = data.find(b"\xff\xd8")
    if start < 0:
        return None
    end = data.find(b"\xff\xd9", start + 2)
    if end < 0:
        return None
    frame = data[start : end + 2]
    return frame if len(frame) > 200 else None


class DX482Client:
    """Serialised async client for one doorbell."""

    def __init__(
        self,
        host: str,
        port: int = 8765,
        *,
        timeout: float = 6.0,
        cooldown: float = 0.4,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._cooldown = cooldown
        self._lock = asyncio.Lock()

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def lock(self) -> asyncio.Lock:
        """Lock that serialises all traffic to the device."""
        return self._lock

    async def command(
        self, dispatcher: int, payload: bytes = b"", *, read_bytes: int = 65536
    ) -> DX482Response:
        """Send one command on a fresh connection and return the parsed reply."""
        request = struct.pack("<I", dispatcher) + payload
        async with self._lock:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=self._timeout,
                )
            except (OSError, asyncio.TimeoutError) as err:
                raise DX482ConnectionError(
                    f"cannot connect to {self._host}:{self._port}: {err}"
                ) from err

            try:
                writer.write(request)
                await writer.drain()
                data = await asyncio.wait_for(
                    self._read_all(reader, read_bytes), timeout=self._timeout
                )
            except (OSError, asyncio.TimeoutError) as err:
                raise DX482ConnectionError(
                    f"no reply to dispatcher 0x{dispatcher:02X}: {err}"
                ) from err
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
                # Give the (fragile) device a breather before the next command.
                await asyncio.sleep(self._cooldown)

        if not data:
            raise DX482ConnectionError(
                f"empty reply to dispatcher 0x{dispatcher:02X}"
            )
        _LOGGER.debug(
            "0x%02X -> %d bytes: %s", dispatcher, len(data), data[:16].hex()
        )
        return _parse(data)

    async def _read_all(self, reader: asyncio.StreamReader, cap: int) -> bytes:
        """Read until the device stops sending (short idle) or cap reached."""
        buf = bytearray()
        while len(buf) < cap:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=0.6)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    # -- High level helpers -------------------------------------------------

    async def async_ping(self) -> bool:
        """Return True if the doorbell answers a door-state query."""
        try:
            await self.command(DISP_DOOR_STATE)
        except DX482Error:
            return False
        return True

    async def async_trigger_door(self) -> DX482Response:
        """Momentary unlock pulse (relay 1)."""
        return await self.command(DISP_DOOR_TRIGGER, b"\x01\x00\x00\x00")

    async def async_set_lock(self, unlock: bool) -> DX482Response:
        payload = b"\x01\x00\x00\x00" if unlock else b"\x00\x00\x00\x00"
        return await self.command(DISP_DOOR_UNLOCK, payload)

    async def async_door_state(self) -> tuple[str | None, int | None]:
        """Return (label, raw_byte) for the current door state, best effort."""
        resp = await self.command(DISP_DOOR_STATE)
        raw = resp.payload or resp.raw
        # The state byte location varies across firmware; scan the first few
        # payload bytes for a known state code, preferring an "open" marker.
        candidate: int | None = None
        for b in raw[:8]:
            if b in DOOR_STATES:
                candidate = b
                if b in OPEN_STATE_BYTES:
                    break
        if candidate is None:
            return None, None
        return DOOR_STATES[candidate], candidate

    async def async_snapshot(self) -> bytes | None:
        """Capture a single JPEG frame from the camera."""
        resp = await self.command(DISP_JPEG_CAPTURE, b"\x01\x00\x00\x00")
        return extract_jpeg(resp.raw)

    async def async_set_led(self, on: bool) -> DX482Response:
        payload = b"\x01\x00\x00\x00" if on else b"\x00\x00\x00\x00"
        return await self.command(DISP_LED, payload)

    async def async_set_relay(self, on: bool) -> DX482Response:
        payload = b"\x01\x00\x00\x00" if on else b"\x00\x00\x00\x00"
        return await self.command(DISP_RELAY, payload)

    async def async_wifi_rssi(self) -> int | None:
        """Best-effort Wi-Fi RSSI (signed dBm) from dispatcher 0x1B."""
        resp = await self.command(DISP_WIFI)
        raw = resp.payload or resp.raw
        if not raw:
            return None
        val = raw[0]
        # Reported as an unsigned byte; interpret as negative dBm.
        return val - 256 if val > 127 else -val


class DX482PersistentConnection:
    """One long-lived TCP connection used for rapid repeated queries.

    Unlike ``DX482Client.command`` (fresh connection per command) this keeps
    the socket open and reads replies frame-by-frame using the 10-byte header
    length.  It reconnects transparently after any error.  All traffic still
    goes through the shared client lock so it never interleaves with other
    commands to the single-threaded device.
    """

    def __init__(self, client: DX482Client, *, timeout: float = 2.0) -> None:
        self._client = client
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        await self.close()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._client.host, self._client.port),
                timeout=self._timeout,
            )
        except (OSError, asyncio.TimeoutError) as err:
            self._reader = self._writer = None
            raise DX482ConnectionError(f"connect failed: {err}") from err

    async def close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is None:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    async def query(self, dispatcher: int, payload: bytes = b"") -> DX482Response:
        """Send one request on the open socket and read exactly one reply."""
        async with self._client.lock:
            if not self.connected:
                await self.connect()
            assert self._reader is not None and self._writer is not None
            try:
                self._writer.write(struct.pack("<I", dispatcher) + payload)
                await self._writer.drain()
                header = await asyncio.wait_for(
                    self._read_header(dispatcher), timeout=self._timeout
                )
                length = struct.unpack_from("<H", header, 6)[0]
                body = await asyncio.wait_for(
                    self._reader.readexactly(length), timeout=self._timeout
                )
            except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as err:
                await self.close()
                raise DX482ConnectionError(
                    f"persistent query 0x{dispatcher:02X} failed: {err}"
                ) from err
        return _parse(header + body)

    async def _read_header(self, dispatcher: int, max_skip: int = 4096) -> bytes:
        """Read a 10-byte header whose op echoes ``dispatcher``.

        Some firmware appends a few stray bytes after a reply.  Rather than
        cancelling a read (which can wedge a StreamReader), slide forward one
        byte at a time until the header lines up with our dispatcher.
        """
        assert self._reader is not None
        buf = bytearray(await self._reader.readexactly(10))
        skipped = 0
        while struct.unpack_from("<H", buf, 0)[0] != dispatcher:
            if skipped >= max_skip:
                raise DX482ConnectionError("could not resync reply header")
            del buf[0]
            buf += await self._reader.readexactly(1)
            skipped += 1
        if skipped:
            _LOGGER.debug("resynced header after skipping %d bytes", skipped)
        return bytes(buf)
