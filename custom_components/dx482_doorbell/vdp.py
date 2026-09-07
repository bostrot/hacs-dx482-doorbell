"""Wire protocol for the 2easy/V-Tec DX482 "VDP" media-proxy link and its SIP signalling.

Reverse-engineered from the vdpconnect app and confirmed against a captured
doorbell <-> vendor-cloud session.  Home Assistant impersonates the vendor cloud:

* SIP registrar on udp/5068 (the doorbell's ``[server]``): answer REGISTER with 200.
* Media proxy on tcp/8850: during any call the doorbell connects here, logs in,
  and only then accepts control commands and pushes H.264 RTP to the video port
  we hand it in the login response.

Frames (little-endian):

    device -> proxy  LOGIN     02 10 xx 00 | acct[31]@4 | pwd[15]@36 | rel[31]@52          (84 B)
    proxy  -> device LOGIN OK  03 10 xx 00 | same 80 bytes | audioPort u16 | videoPort u16 | 00 00  (90 B)
    device -> proxy  STATUS    00 40 00 00 | 01 00 06 00 01 00 00 00 00 00                  (byte1 & 0x40 = device-initiated)
    proxy  -> device STATUS OK 00 20 00 00 01 00 00 00                                       (required, else no video)
    proxy  -> device CTRL      10 10 01 00 | sub u16 | payload
    device -> proxy  CTRL ACK  11 10 sid16 | sub u16 | ...

Control sub-commands: 1 = unlock (payload = relay index u16), 2 = DTMF/monitor code
(payload = "<code>#", starts video), 4 = push-to-talk, 5/6 = IPC list/switch, 7 = light.
"""

from __future__ import annotations

import random
import re
import struct
from dataclasses import dataclass

CMD_LOGIN = 0x1002
CMD_LOGIN_OK = 0x1003
CMD_CTRL = 0x1010
CMD_CTRL_ACK = 0x1011  # bytes 11 10 on the wire
CMD_STATUS_OK = b"\x00\x20\x00\x00\x01\x00\x00\x00"

SUB_UNLOCK = 1
SUB_DTMF = 2
SUB_P2T = 4
SUB_LIGHT = 7


def cmd_code(frame: bytes) -> int:
    return frame[0] | (frame[1] << 8)


def is_login(frame: bytes) -> bool:
    return len(frame) >= 84 and cmd_code(frame) == CMD_LOGIN


def is_device_cmd(frame: bytes) -> bool:
    return len(frame) >= 2 and bool(frame[1] & 0x40)


def is_ctrl_ack(frame: bytes) -> bool:
    return len(frame) >= 6 and cmd_code(frame) == CMD_CTRL_ACK


@dataclass
class Login:
    acct: str
    pwd: str
    rel_acct: str
    flags: int


def parse_login(frame: bytes) -> Login:
    def s(b: bytes) -> str:
        return b.split(b"\0", 1)[0].decode("ascii", "replace")

    return Login(s(frame[4:35]), s(frame[36:51]), s(frame[52:83]), frame[2])


def login_ok(frame: bytes, audio_port: int, video_port: int) -> bytes:
    rsp = bytearray(90)
    rsp[0] = 0x03
    rsp[1] = 0x10
    rsp[2] = frame[2]
    rsp[4:84] = frame[4:84]
    struct.pack_into("<HH", rsp, 84, audio_port, video_port)
    return bytes(rsp)


def ctrl(sub: int, payload: bytes) -> bytes:
    return b"\x10\x10\x01\x00" + struct.pack("<H", sub) + payload


def ctrl_unlock(index: int = 1) -> bytes:
    return ctrl(SUB_UNLOCK, struct.pack("<H", index))


def ctrl_open_video(mon_code: str) -> bytes:
    return ctrl(SUB_DTMF, f"{mon_code}#".encode("ascii"))


def ctrl_light(index: int = 1) -> bytes:
    return ctrl(SUB_LIGHT, struct.pack("<H", index))


def ack_sub(frame: bytes) -> int:
    return struct.unpack_from("<H", frame, 4)[0]


def split_frames(chunk: bytes) -> list[bytes]:
    """Split one TCP read into protocol frames.

    Observed sizes: login 84 B; device status frame 8 + u16@6 (= 14 B); control
    acks are variable and always the last thing in a read, so they take the rest.
    """
    frames: list[bytes] = []
    i = 0
    while i < len(chunk):
        rest = chunk[i:]
        if is_login(rest):
            n = 84
        elif is_device_cmd(rest) and len(rest) >= 8:
            n = max(8, 8 + struct.unpack_from("<H", rest, 6)[0])
            n = min(n, len(rest))
        else:
            n = len(rest)
        frames.append(rest[:n])
        i += n
    return frames


# --------------------------------------------------------------------------
# SIP helpers (just enough of RFC 3261 for one doorbell)
# --------------------------------------------------------------------------


def sip_first_line(data: bytes) -> str:
    return data.split(b"\r\n", 1)[0].decode("ascii", "replace")


def sip_header(text: str, name: str) -> str | None:
    m = re.search(rf"^{re.escape(name)}\s*:\s*(.*?)\s*$", text, re.M | re.I)
    return m.group(1) if m else None


def sip_echo_headers(text: str) -> str:
    keep = ("via", "from", "to", "call-id", "cseq")
    return "\r\n".join(
        l for l in text.split("\r\n") if l.split(":", 1)[0].strip().lower() in keep
    )


def sip_response(request: str, code: int, reason: str, extra: str = "", body: str = "") -> bytes:
    to_line = sip_header(request, "To") or ""
    hdrs = sip_echo_headers(request)
    if code >= 200 and ";tag=" not in to_line:
        # Add a To tag on final responses so the dialog is well formed.
        hdrs = re.sub(r"^(To\s*:.*?)$", rf"\1;tag={random.randint(1, 1 << 31):x}", hdrs, flags=re.M | re.I)
    msg = f"SIP/2.0 {code} {reason}\r\n{hdrs}\r\n"
    if extra:
        msg += extra if extra.endswith("\r\n") else extra + "\r\n"
    msg += f"Content-Length: {len(body)}\r\n\r\n{body}"
    return msg.encode()


def sdp_offer(local_ip: str, audio_port: int, video_port: int) -> str:
    sess = random.randint(1, 1 << 30)
    return (
        "v=0\r\n"
        f"o=ha {sess} {sess} IN IP4 {local_ip}\r\n"
        "s=ha\r\n"
        f"c=IN IP4 {local_ip}\r\n"
        "t=0 0\r\n"
        f"m=audio {audio_port} RTP/AVP 0 8 101\r\n"
        "a=rtpmap:0 PCMU/8000\r\n"
        "a=rtpmap:8 PCMA/8000\r\n"
        "a=rtpmap:101 telephone-event/8000\r\n"
        "a=fmtp:101 0-15\r\n"
        "a=sendrecv\r\n"
        f"m=video {video_port} RTP/AVP 96\r\n"
        "a=rtpmap:96 H264/90000\r\n"
        "a=fmtp:96 packetization-mode=1;profile-level-id=42001F\r\n"
        "a=recvonly\r\n"
    )


def sdp_for_ffmpeg(port: int) -> str:
    """SDP file content so ffmpeg can receive the H.264 RTP we re-emit locally."""
    return (
        "v=0\r\n"
        "o=- 0 0 IN IP4 127.0.0.1\r\n"
        "s=dx482\r\n"
        "c=IN IP4 127.0.0.1\r\n"
        "t=0 0\r\n"
        f"m=video {port} RTP/AVP 96\r\n"
        "a=rtpmap:96 H264/90000\r\n"
        "a=fmtp:96 packetization-mode=1\r\n"
    )


@dataclass
class Dialog:
    """State for one outgoing call we place to the doorbell."""

    call_id: str
    from_tag: str
    branch: str
    to_uri: str
    from_uri: str
    contact: str
    cseq: int = 1
    to_tag: str = ""
    remote_addr: tuple[str, int] | None = None
    established: bool = False

    def _headers(self, method: str, cseq: int, to_extra: str = "") -> str:
        via_host = self.contact.split("@", 1)[1].rstrip(">")
        return (
            f"Via: SIP/2.0/UDP {via_host};branch={self.branch};rport\r\n"
            "Max-Forwards: 70\r\n"
            f"From: <{self.from_uri}>;tag={self.from_tag}\r\n"
            f"To: <{self.to_uri}>{to_extra}\r\n"
            f"Call-ID: {self.call_id}\r\n"
            f"CSeq: {cseq} {method}\r\n"
            f"Contact: <{self.contact}>\r\n"
            "User-Agent: home-assistant-dx482\r\n"
        )

    def invite(self, sdp: str) -> bytes:
        return (
            f"INVITE {self.to_uri} SIP/2.0\r\n"
            + self._headers("INVITE", self.cseq)
            + "Allow: INVITE, ACK, CANCEL, BYE, INFO, OPTIONS\r\n"
            "Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp)}\r\n\r\n{sdp}"
        ).encode()

    def ack(self) -> bytes:
        return (
            f"ACK {self.to_uri} SIP/2.0\r\n"
            + self._headers("ACK", self.cseq, f";tag={self.to_tag}" if self.to_tag else "")
            + "Content-Length: 0\r\n\r\n"
        ).encode()

    def bye(self) -> bytes:
        self.cseq += 1
        return (
            f"BYE {self.to_uri} SIP/2.0\r\n"
            + self._headers("BYE", self.cseq, f";tag={self.to_tag}" if self.to_tag else "")
            + "Content-Length: 0\r\n\r\n"
        ).encode()

    def cancel(self) -> bytes:
        return (
            f"CANCEL {self.to_uri} SIP/2.0\r\n"
            + self._headers("CANCEL", self.cseq)
            + "Content-Length: 0\r\n\r\n"
        ).encode()


def new_dialog(local_ip: str, local_port: int, from_user: str, device_ip: str, device_port: int, device_user: str) -> Dialog:
    return Dialog(
        call_id=f"{random.randint(1, 1 << 31)}@{local_ip}",
        from_tag=f"{random.randint(1, 1 << 31):x}",
        branch=f"z9hG4bK{random.randint(1, 1 << 31):x}",
        to_uri=f"sip:{device_user}@{device_ip}:{device_port}",
        from_uri=f"sip:{from_user}@{local_ip}:{local_port}",
        contact=f"sip:{from_user}@{local_ip}:{local_port}",
    )
