"""Read and change the doorbell's own settings over FTP/telnet (root, empty password).

The DX482 keeps user settings as overrides in ``/mnt/nand1-2/Settings/io_data_value.json``
(``{"value": {"<paraId>": "<string>"}}``); defaults and ranges come from the firmware
table ``/mnt/nand1-1/App/res/io_data_default_table.csv``.  The app only reads the file
at boot, so a change is followed by a reboot (telnet ``reboot``).  The SIP server the
doorbell dials into lives in ``/mnt/nand1-2/Settings/sipcfg.cfg``.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import socket
from dataclasses import dataclass
from ftplib import FTP

_LOGGER = logging.getLogger(__name__)

SETTINGS_DIR = "/mnt/nand1-2/Settings"
VALUES_FILE = f"{SETTINGS_DIR}/io_data_value.json"
SIPCFG_FILE = f"{SETTINGS_DIR}/sipcfg.cfg"
SIPCFG_BACKUP = f"{SETTINGS_DIR}/sipcfg.cfg.orig"
VENDOR_SERVER = "47.91.88.33"


@dataclass(frozen=True)
class Param:
    para_id: str
    key: str
    name: str
    default: int
    min: int
    max: int
    unit: str | None = None
    step: int = 1


# Curated subset of the 300-entry firmware table: the ones a home user wants.
PARAMS: dict[str, Param] = {
    p.key: p
    for p in (
        Param("1122", "unlock_time", "Unlock time", 5, 1, 99, "s"),
        Param("1130", "unlock2_time", "Unlock 2 time", 5, 1, 99, "s"),
        Param("1022", "monitor_time_limit", "Monitor time limit", 30, 6, 600, "s"),
        Param("1051", "divert_time", "Divert delay", 30, 0, 60, "s"),
        Param("1017", "day_call_volume", "Day call volume", 4, 0, 5),
        Param("1018", "night_call_volume", "Night call volume", 6, 0, 9),
        Param("1026", "talk_volume", "Talk volume", 6, 0, 9),
        Param("1053", "mic_volume", "Microphone volume", 0, 0, 30),
        Param("1054", "speaker_volume", "Speaker volume", 0, 0, 30),
        Param("1035", "doorbell_tune", "Doorbell tune", 4, 0, 255),
        Param("1029", "call_tune_time", "Ring duration", 35, 3, 255, "s"),
        Param("1726", "auto_unlock_start", "Auto unlock start hour", 0, 0, 23, "h"),
        Param("1727", "auto_unlock_end", "Auto unlock end hour", 23, 0, 23, "h"),
    )
}

# Boolean parameters exposed as switches.
BOOL_PARAMS: dict[str, Param] = {
    p.key: p
    for p in (
        Param("1248", "auto_unlock", "Auto unlock", 0, 0, 1),
        Param("1157", "auto_close_after_unlock", "Auto close after unlock", 0, 0, 1),
    )
}
PARAMS_BY_ID = {p.para_id: p for p in (*PARAMS.values(), *BOOL_PARAMS.values())}


class DeviceConfig:
    """Thin async wrapper around the doorbell's FTP and telnet services."""

    def __init__(self, host: str, ftp_user: str = "root", ftp_password: str = "") -> None:
        self.host = host
        self.user = ftp_user
        self.password = ftp_password
        self.values: dict[str, str] = {}
        self.reboot_required = False
        self.sip_server: str | None = None

    # ---------------------------------------------------------------- FTP primitives (blocking)
    def _ftp(self) -> FTP:
        ftp = FTP()
        ftp.connect(self.host, 21, timeout=20)
        ftp.login(self.user, self.password)
        ftp.set_pasv(True)
        return ftp

    def _read(self, path: str) -> bytes:
        ftp = self._ftp()
        try:
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {path}", buf.write)
            return buf.getvalue()
        finally:
            ftp.quit()

    def _write(self, path: str, data: bytes) -> None:
        ftp = self._ftp()
        try:
            ftp.storbinary(f"STOR {path}", io.BytesIO(data))
        finally:
            ftp.quit()

    def _exists(self, path: str) -> bool:
        ftp = self._ftp()
        try:
            d, name = path.rsplit("/", 1)
            return name in ftp.nlst(d)
        finally:
            ftp.quit()

    # ---------------------------------------------------------------- telnet (blocking)
    def _telnet(self, command: str) -> str:
        s = socket.create_connection((self.host, 23), timeout=10)

        def rd(t: float) -> str:
            s.settimeout(t)
            buf = b""
            while True:
                try:
                    c = s.recv(4096)
                except socket.timeout:
                    break
                if not c:
                    break
                buf += c
            return buf.decode("latin1")

        try:
            rd(2)
            s.sendall(b"root\r\n")
            rd(1.5)
            s.sendall(self.password.encode() + b"\r\n")
            rd(2)
            s.sendall(f"{command}\r\n".encode())
            return rd(2)
        finally:
            s.close()

    # ---------------------------------------------------------------- async API
    async def async_refresh(self) -> dict[str, str]:
        raw = await asyncio.to_thread(self._read, VALUES_FILE)
        self.values = dict(json.loads(raw.decode("utf-8", "replace")).get("value", {}))
        cfg = (await asyncio.to_thread(self._read, SIPCFG_FILE)).decode("utf-8", "replace")
        m = re.search(r"^\[server\]\s*=\s*([^:\s]+)", cfg, re.M)
        self.sip_server = m.group(1) if m else None
        return self.values

    def get(self, key: str) -> int:
        p = PARAMS.get(key) or BOOL_PARAMS[key]
        try:
            return int(self.values.get(p.para_id, p.default))
        except ValueError:
            return p.default

    async def async_set(self, key: str, value: int) -> None:
        p = PARAMS.get(key) or BOOL_PARAMS[key]
        value = max(p.min, min(p.max, int(value)))
        raw = await asyncio.to_thread(self._read, VALUES_FILE)
        doc = json.loads(raw.decode("utf-8", "replace"))
        doc.setdefault("value", {})[p.para_id] = str(value)
        await asyncio.to_thread(self._write, VALUES_FILE, json.dumps(doc, indent=8).encode())
        self.values = dict(doc["value"])
        self.reboot_required = True
        _LOGGER.info("Doorbell parameter %s (%s) set to %s; reboot required", p.name, p.para_id, value)

    async def async_reboot(self) -> None:
        await asyncio.to_thread(self._telnet, "sync; reboot")
        self.reboot_required = False

    async def async_point_sip_server(self, server_ip: str) -> None:
        """Point the doorbell's SIP/media server at ``server_ip`` (keeps a backup of the original)."""
        cfg = await asyncio.to_thread(self._read, SIPCFG_FILE)
        if not await asyncio.to_thread(self._exists, SIPCFG_BACKUP):
            await asyncio.to_thread(self._write, SIPCFG_BACKUP, cfg)
        text = cfg.decode("utf-8", "replace")
        current = re.search(r"^\[server\]\s*=\s*([^:\s]+)", text, re.M)
        old = current.group(1) if current else VENDOR_SERVER
        new = text.replace(old, server_ip)
        await asyncio.to_thread(self._write, SIPCFG_FILE, new.encode())
        self.sip_server = server_ip
        self.reboot_required = True

    async def async_restore_vendor_cloud(self) -> None:
        if await asyncio.to_thread(self._exists, SIPCFG_BACKUP):
            cfg = await asyncio.to_thread(self._read, SIPCFG_BACKUP)
            await asyncio.to_thread(self._write, SIPCFG_FILE, cfg)
        else:
            await self.async_point_sip_server(VENDOR_SERVER)
        self.sip_server = VENDOR_SERVER
        self.reboot_required = True
