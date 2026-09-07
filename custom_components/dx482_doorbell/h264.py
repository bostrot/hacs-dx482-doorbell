"""Tiny H.264 SPS parser: returns (width, height, profile_idc) or None."""

from __future__ import annotations


class _Bits:
    def __init__(self, data: bytes) -> None:
        # strip emulation-prevention bytes (00 00 03 -> 00 00)
        out = bytearray()
        i = 0
        while i < len(data):
            if i + 2 < len(data) and data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 3:
                out += b"\x00\x00"
                i += 3
            else:
                out.append(data[i])
                i += 1
        self.d = bytes(out)
        self.pos = 0

    def u(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.d[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def ue(self) -> int:
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
            if zeros > 32:
                raise ValueError("bad exp-golomb")
        return (1 << zeros) - 1 + (self.u(zeros) if zeros else 0)

    def se(self) -> int:
        k = self.ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)


def parse_sps(nal: bytes) -> tuple[int, int, int] | None:
    """``nal`` is the SPS NAL unit including its 1-byte header (0x67)."""
    try:
        b = _Bits(nal[1:])
        profile = b.u(8)
        b.u(8)  # constraint flags
        b.u(8)  # level
        b.ue()  # sps id
        if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
            cf = b.ue()
            if cf == 3:
                b.u(1)
            b.ue()
            b.ue()
            b.u(1)
            if b.u(1):  # scaling matrix
                for i in range(8 if cf != 3 else 12):
                    if b.u(1):
                        size = 16 if i < 6 else 64
                        last = 8
                        nxt = 8
                        for _ in range(size):
                            if nxt:
                                nxt = (last + b.se() + 256) % 256
                            last = last if nxt == 0 else nxt
        b.ue()  # log2_max_frame_num
        poc = b.ue()
        if poc == 0:
            b.ue()
        elif poc == 1:
            b.u(1)
            b.se()
            b.se()
            for _ in range(b.ue()):
                b.se()
        b.ue()  # num ref frames
        b.u(1)
        w_mbs = b.ue() + 1
        h_map = b.ue() + 1
        frame_mbs_only = b.u(1)
        if not frame_mbs_only:
            b.u(1)
        b.u(1)
        crop = b.u(1)
        cl = cr = ct = cb = 0
        if crop:
            cl, cr, ct, cb = b.ue(), b.ue(), b.ue(), b.ue()
        width = w_mbs * 16 - 2 * (cl + cr)
        height = (2 - frame_mbs_only) * h_map * 16 - 2 * (ct + cb) * (2 - frame_mbs_only)
        return width, height, profile
    except (IndexError, ValueError):
        return None
