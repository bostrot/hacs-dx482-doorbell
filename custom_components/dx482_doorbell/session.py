"""Local stand-in for the vendor cloud: SIP endpoint + media proxy + RTP fan-out.

Pure asyncio, no Home Assistant imports, so it can be exercised standalone.

Lifecycle of a video/unlock session:
  1. We INVITE the doorbell directly (udp/5069) as the "phone" identity.
  2. The doorbell answers and connects to our media proxy (tcp/8850), logs in,
     sends a status frame which we acknowledge.
  3. We send the monitor code -> the doorbell pushes H.264 RTP to our video port.
  4. Control commands (unlock, light) are sent on the same proxy link.
  5. RTP is depacketized to Annex-B H.264 and served on local TCP ports to ffmpeg consumers.
A ring is an INVITE *from* the doorbell to us (it calls the phone account).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Callable
from typing import Any

from . import vdp

_LOGGER = logging.getLogger(__name__)

EVENT_RING = "ring"
EVENT_CALL = "call"          # data: "idle" | "calling" | "established" | "ended"
EVENT_PROXY = "proxy"        # data: "connected" | "logged_in" | "disconnected"
EVENT_VIDEO = "video"        # data: "on" | "off"
EVENT_REGISTERED = "registered"

EventCallback = Callable[[str, Any], None]


class _SipProtocol(asyncio.DatagramProtocol):
    def __init__(self, session: "DX482Session") -> None:
        self.session = session
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        self.session._on_sip(data, addr)


class _RtpProtocol(asyncio.DatagramProtocol):
    def __init__(self, session: "DX482Session", kind: str) -> None:
        self.session = session
        self.kind = kind

    def datagram_received(self, data: bytes, addr) -> None:
        self.session._on_rtp(self.kind, data, addr)


class DX482Session:
    """Owns all sockets and the call/proxy state for one doorbell."""

    def __init__(
        self,
        *,
        local_ip: str,
        device_ip: str,
        device_user: str,
        phone_user: str,
        mon_code: str,
        sip_port: int = 5068,
        proxy_port: int = 8850,
        audio_port: int = 30000,
        video_port: int = 30002,
        device_sip_port: int = 5069,
        idle_timeout: float = 30.0,
        auto_answer: bool = False,
        on_event: EventCallback | None = None,
    ) -> None:
        self.local_ip = local_ip
        self.device_ip = device_ip
        self.device_user = device_user
        self.phone_user = phone_user
        self.mon_code = mon_code
        self.sip_port = sip_port
        self.proxy_port = proxy_port
        self.audio_port = audio_port
        self.video_port = video_port
        self.device_sip_port = device_sip_port
        self.idle_timeout = idle_timeout
        self.auto_answer = auto_answer
        self._on_event = on_event or (lambda *_: None)

        self._loop = asyncio.get_event_loop()
        self._sip: _SipProtocol | None = None
        self._rtp_transports: list[asyncio.DatagramTransport] = []
        self._server: asyncio.AbstractServer | None = None
        self._proxy_writer: asyncio.StreamWriter | None = None
        self._logged_in = asyncio.Event()
        self._call_established = asyncio.Event()
        self._call_failed: str | None = None
        self._pending_acks: dict[int, asyncio.Future] = {}
        self._dialog: vdp.Dialog | None = None
        self._incoming: dict[str, str] | None = None   # headers of the doorbell's INVITE (ring)
        self._video_on = False
        self._consumers: dict[int, dict[str, Any]] = {}  # tcp port -> {server, writers}
        self._sps: bytes | None = None
        self._pps: bytes | None = None
        self._fu_type = 0
        self._lock = asyncio.Lock()
        self._last_activity = 0.0
        self._idle_task: asyncio.Task | None = None
        self.registered_at: float | None = None
        self.last_ring_at: float | None = None
        self.rtp_video_packets = 0
        self.last_rtp_at: float | None = None

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        _, self._sip = await loop.create_datagram_endpoint(
            lambda: _SipProtocol(self), local_addr=(self.local_ip, self.sip_port)
        )
        for kind, port in (("audio", self.audio_port), ("video", self.video_port)):
            t, _ = await loop.create_datagram_endpoint(
                lambda k=kind: _RtpProtocol(self, k), local_addr=(self.local_ip, port)
            )
            self._rtp_transports.append(t)
        self._server = await asyncio.start_server(self._on_proxy_client, self.local_ip, self.proxy_port)
        self._idle_task = loop.create_task(self._idle_loop())
        _LOGGER.info(
            "DX482 session up: sip %s:%d proxy tcp/%d rtp audio/%d video/%d",
            self.local_ip, self.sip_port, self.proxy_port, self.audio_port, self.video_port,
        )

    async def stop(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
        await self.hangup()
        if self._server:
            self._server.close()
        for t in self._rtp_transports:
            t.close()
        if self._sip and self._sip.transport:
            self._sip.transport.close()
        for port in list(self._consumers):
            self.remove_consumer(port)

    # ------------------------------------------------------------------ properties
    @property
    def call_active(self) -> bool:
        return self._call_established.is_set()

    @property
    def proxy_logged_in(self) -> bool:
        return self._logged_in.is_set()

    @property
    def video_active(self) -> bool:
        return self._video_on

    def _emit(self, event: str, data: Any = None) -> None:
        try:
            self._on_event(event, data)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("event callback failed")

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    # ------------------------------------------------------------------ SIP
    def _sip_send(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._sip and self._sip.transport:
            _LOGGER.debug("SIP -> %s: %s", addr, vdp.sip_first_line(data))
            self._sip.transport.sendto(data, addr)

    def _on_sip(self, data: bytes, addr: tuple[str, int]) -> None:
        if data.startswith(b"jaK") or len(data) < 12:
            return  # doorbell keepalive
        text = data.decode("utf-8", "replace")
        first = vdp.sip_first_line(data)
        _LOGGER.debug("SIP <- %s: %s", addr, first)
        if first.startswith("SIP/2.0"):
            self._on_sip_response(text, first, addr)
            return
        method = first.split(" ", 1)[0]
        if method in ("REGISTER", "OPTIONS"):
            # Mirror exactly what the doorbell accepted from the standalone stand-in:
            # echoed Via/From/To/Call-ID/CSeq (no To tag), its Contact untouched, Expires.
            contact = vdp.sip_header(text, "Contact") or ""
            extra = (f"Contact: {contact}\r\n" if contact else "") + ("Expires: 3600\r\n" if method == "REGISTER" else "")
            rsp = vdp.sip_response(text, 200, "OK", extra, to_tag=False)
            _LOGGER.debug("SIP -> %s: %s", addr, rsp.decode("utf-8", "replace").replace("\r\n", " | ")[:400])
            self._sip_send(rsp, addr)
            if method == "REGISTER" and addr[0] == self.device_ip:
                first_time = self.registered_at is None
                self.registered_at = time.time()
                if first_time:
                    self._emit(EVENT_REGISTERED, True)
        elif method == "INVITE":
            self._on_incoming_invite(text, addr)
        elif method == "ACK":
            if self._incoming and not self._call_established.is_set():
                self._call_established.set()
                self._emit(EVENT_CALL, "established")
        elif method == "BYE":
            self._sip_send(vdp.sip_response(text, 200, "OK"), addr)
            self._end_call(notify=True)
        elif method == "CANCEL":
            self._sip_send(vdp.sip_response(text, 200, "OK"), addr)
            self._incoming = None
        else:
            self._sip_send(vdp.sip_response(text, 200, "OK"), addr)

    def _on_incoming_invite(self, text: str, addr: tuple[str, int]) -> None:
        """The doorbell button was pressed: it calls the phone account through 'the cloud' (us)."""
        self.last_ring_at = time.time()
        self._touch()
        self._sip_send(vdp.sip_response(text, 100, "Trying"), addr)
        ringing = vdp.sip_response(text, 180, "Ringing")
        self._sip_send(ringing, addr)
        self._emit(EVENT_RING, {"from": vdp.sip_header(text, "From")})
        if not self.auto_answer or self._dialog is not None:
            return
        # Answer so the doorbell opens its proxy link and we can stream / unlock.
        sdp = vdp.sdp_offer(self.local_ip, self.audio_port, self.video_port)
        rsp = vdp.sip_response(
            text, 200, "OK",
            f"Contact: <sip:{self.phone_user}@{self.local_ip}:{self.sip_port}>\r\nContent-Type: application/sdp\r\n",
            sdp,
        )
        to_tag = re.search(rb"^To:.*?;tag=([^\s;>]+)", rsp, re.M)
        self._incoming = {
            "text": text,
            "addr": addr,
            "to_tag": to_tag.group(1).decode() if to_tag else "",
        }
        self._sip_send(rsp, addr)
        self._emit(EVENT_CALL, "calling")

    def _on_sip_response(self, text: str, first: str, addr) -> None:
        dlg = self._dialog
        if dlg is None:
            return
        if vdp.sip_header(text, "Call-ID") != dlg.call_id:
            return
        code = int(first.split()[1])
        m = re.search(r"^To:.*?;tag=([^\s;>]+)", text, re.M)
        if m:
            dlg.to_tag = m.group(1)
        cseq = vdp.sip_header(text, "CSeq") or ""
        if "INVITE" not in cseq:
            return
        if code < 200:
            return
        dlg.remote_addr = addr
        if code == 200:
            self._sip_send(dlg.ack(), addr)
            if not dlg.established:
                dlg.established = True
                self._call_established.set()
                self._emit(EVENT_CALL, "established")
        else:
            self._sip_send(dlg.ack(), addr)
            self._call_failed = first
            self._call_established.set()  # wake waiter; it checks _call_failed

    # ------------------------------------------------------------------ media proxy (tcp/8850)
    async def _on_proxy_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("proxy client %s", peer)
        if self._proxy_writer is not None and not self._proxy_writer.is_closing():
            self._proxy_writer.close()
        self._proxy_writer = writer
        self._emit(EVENT_PROXY, "connected")
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                for frame in vdp.split_frames(chunk):
                    await self._on_proxy_frame(frame, writer)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if self._proxy_writer is writer:
                self._proxy_writer = None
                self._logged_in.clear()
                self._set_video(False)
                self._emit(EVENT_PROXY, "disconnected")
            writer.close()

    async def _on_proxy_frame(self, frame: bytes, writer: asyncio.StreamWriter) -> None:
        _LOGGER.debug("proxy <- %s", frame[:16].hex())
        if vdp.is_login(frame):
            info = vdp.parse_login(frame)
            _LOGGER.debug("proxy login acct=%s rel=%s", info.acct, info.rel_acct)
            writer.write(vdp.login_ok(frame, self.audio_port, self.video_port))
            await writer.drain()
            self._logged_in.set()
            self._touch()
            self._emit(EVENT_PROXY, "logged_in")
        elif vdp.is_device_cmd(frame):
            writer.write(vdp.CMD_STATUS_OK)
            await writer.drain()
        elif vdp.is_ctrl_ack(frame):
            sub = vdp.ack_sub(frame)
            fut = self._pending_acks.pop(sub, None)
            if fut and not fut.done():
                fut.set_result(frame)

    async def _send_ctrl(self, frame: bytes, timeout: float = 5.0) -> bytes:
        writer = self._proxy_writer
        if writer is None or writer.is_closing():
            raise ConnectionError("doorbell proxy link is not connected")
        sub = int.from_bytes(frame[4:6], "little")
        fut: asyncio.Future = self._loop.create_future()
        self._pending_acks[sub] = fut
        writer.write(frame)
        await writer.drain()
        self._touch()
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as err:
            self._pending_acks.pop(sub, None)
            raise TimeoutError(f"no ack for control sub={sub}") from err

    # ------------------------------------------------------------------ RTP -> H.264 fan-out
    def _on_rtp(self, kind: str, data: bytes, addr) -> None:
        if kind != "video":
            return
        self.rtp_video_packets += 1
        self.last_rtp_at = time.time()
        if not self._video_on and self._logged_in.is_set():
            self._set_video(True)
        nal = self._depacketize(data)
        if nal:
            self._broadcast(nal)

    def _depacketize(self, pkt: bytes) -> bytes:
        """RFC 6184 -> Annex-B bytes (single NAL, STAP-A, FU-A). Caches SPS/PPS for late joiners."""
        if len(pkt) < 13:
            return b""
        cc = pkt[0] & 0x0F
        hdr = 12 + 4 * cc
        if pkt[0] & 0x10 and len(pkt) >= hdr + 4:
            hdr += 4 + 4 * int.from_bytes(pkt[hdr + 2:hdr + 4], "big")
        p = pkt[hdr:]
        if not p:
            return b""
        t = p[0] & 0x1F
        out = b""
        if 1 <= t <= 23:
            out = b"\x00\x00\x00\x01" + p
            self._cache_param(t, p)
        elif t == 24:  # STAP-A
            j = 1
            while j + 2 <= len(p):
                sz = int.from_bytes(p[j:j + 2], "big")
                j += 2
                unit = p[j:j + sz]
                j += sz
                if unit:
                    out += b"\x00\x00\x00\x01" + unit
                    self._cache_param(unit[0] & 0x1F, unit)
        elif t == 28 and len(p) >= 2:  # FU-A
            start, fu_type = p[1] & 0x80, p[1] & 0x1F
            if start:
                out = b"\x00\x00\x00\x01" + bytes([(p[0] & 0xE0) | fu_type]) + p[2:]
                self._fu_type = fu_type
            else:
                out = p[2:]
        return out

    def _cache_param(self, t: int, unit: bytes) -> None:
        if t == 7:
            self._sps = b"\x00\x00\x00\x01" + unit
        elif t == 8:
            self._pps = b"\x00\x00\x00\x01" + unit

    def _broadcast(self, data: bytes) -> None:
        for port, cons in list(self._consumers.items()):
            for w in list(cons["writers"]):
                if w.is_closing():
                    cons["writers"].discard(w)
                    continue
                try:
                    w.write(data)
                except (ConnectionError, OSError):
                    cons["writers"].discard(w)

    def _set_video(self, on: bool) -> None:
        if self._video_on != on:
            self._video_on = on
            self._emit(EVENT_VIDEO, "on" if on else "off")

    async def add_consumer(self) -> tuple[int, str]:
        """Start a local TCP server that streams raw Annex-B H.264 to whoever connects.

        Returns (port, ffmpeg input string).  The input string carries the input
        options because HA's ffmpeg helper appends ``extra_cmd`` after the output.
        """
        cons: dict[str, Any] = {"writers": set()}

        async def on_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            # Prime late joiners with the last parameter sets so decoding can start at the next IDR.
            for unit in (self._sps, self._pps):
                if unit:
                    writer.write(unit)
            cons["writers"].add(writer)
            try:
                await reader.read()  # wait for the client to go away
            except (ConnectionError, OSError):
                pass
            finally:
                cons["writers"].discard(writer)
                writer.close()

        server = await asyncio.start_server(on_conn, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        cons["server"] = server
        self._consumers[port] = cons
        self._touch()
        return port, f"-f h264 -fflags nobuffer -flags low_delay -i tcp://127.0.0.1:{port}"

    def remove_consumer(self, port: int) -> None:
        cons = self._consumers.pop(port, None)
        if not cons:
            return
        for w in list(cons["writers"]):
            w.close()
        cons["server"].close()
        self._touch()

    # ------------------------------------------------------------------ high level actions
    async def ensure_call(self, timeout: float = 12.0) -> None:
        """Make sure a call with the doorbell is up and its proxy link is logged in."""
        async with self._lock:
            self._touch()
            if self._call_established.is_set() and self._logged_in.is_set():
                return
            if self._dialog is None and self._incoming is None:
                self._call_failed = None
                self._call_established.clear()
                self._logged_in.clear()
                dlg = vdp.new_dialog(
                    self.local_ip, self.sip_port, self.phone_user,
                    self.device_ip, self.device_sip_port, self.device_user,
                )
                self._dialog = dlg
                self._emit(EVENT_CALL, "calling")
                sdp = vdp.sdp_offer(self.local_ip, self.audio_port, self.video_port)
                self._sip_send(dlg.invite(sdp), (self.device_ip, self.device_sip_port))
            try:
                await asyncio.wait_for(self._call_established.wait(), timeout)
                if self._call_failed:
                    raise ConnectionError(f"doorbell rejected call: {self._call_failed}")
                await asyncio.wait_for(self._logged_in.wait(), timeout)
            except asyncio.TimeoutError as err:
                await self._hangup_locked()
                raise TimeoutError("doorbell did not answer / connect to proxy") from err

    async def start_video(self) -> None:
        await self.ensure_call()
        await self._send_ctrl(vdp.ctrl_open_video(self.mon_code))

    async def unlock(self, index: int = 1) -> None:
        await self.ensure_call()
        ack = await self._send_ctrl(vdp.ctrl_unlock(index))
        _LOGGER.debug("unlock %d ack %s", index, ack.hex())

    async def light(self, index: int = 1) -> None:
        await self.ensure_call()
        await self._send_ctrl(vdp.ctrl_light(index))

    async def hangup(self) -> None:
        async with self._lock:
            await self._hangup_locked()

    async def _hangup_locked(self) -> None:
        dlg = self._dialog
        if dlg is not None:
            addr = dlg.remote_addr or (self.device_ip, self.device_sip_port)
            self._sip_send(dlg.bye() if dlg.established else dlg.cancel(), addr)
        inc = self._incoming
        if inc is not None:
            self._sip_send(self._incoming_bye(inc), inc["addr"])
        self._end_call(notify=dlg is not None or inc is not None)

    def _incoming_bye(self, inc: dict[str, str]) -> bytes:
        t = inc["text"]
        frm = vdp.sip_header(t, "From") or ""
        to = vdp.sip_header(t, "To") or ""
        to_tagged = to if ";tag=" in to else f"{to};tag={inc['to_tag']}"
        uri = re.search(r"<([^>]+)>", vdp.sip_header(t, "Contact") or "")
        req_uri = uri.group(1) if uri else f"sip:{self.device_user}@{inc['addr'][0]}:{inc['addr'][1]}"
        return (
            f"BYE {req_uri} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch=z9hG4bK{random.randint(1, 1 << 31):x};rport\r\n"
            "Max-Forwards: 70\r\n"
            f"From: {to_tagged}\r\n"
            f"To: {frm}\r\n"
            f"Call-ID: {vdp.sip_header(t, 'Call-ID')}\r\n"
            "CSeq: 2 BYE\r\n"
            "Content-Length: 0\r\n\r\n"
        ).encode()

    def _end_call(self, notify: bool) -> None:
        self._dialog = None
        self._incoming = None
        self._call_established.clear()
        self._call_failed = None
        self._set_video(False)
        if self._proxy_writer is not None:
            self._proxy_writer.close()
            self._proxy_writer = None
        self._logged_in.clear()
        if notify:
            self._emit(EVENT_CALL, "ended")

    async def _idle_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            if (self._dialog is None and self._incoming is None) or self._consumers:
                continue
            if time.monotonic() - self._last_activity > self.idle_timeout:
                _LOGGER.debug("idle timeout, hanging up")
                await self.hangup()
