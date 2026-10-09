"""Schreibt kleine GRIB2-Nachrichten (Gitter 3.0, Daten 5.0, 16 Bit, optional Bitmaske) für Tests. SYNTHETISCH."""
from __future__ import annotations

import struct
from datetime import datetime


def _sm32(v: float) -> int:
    n = int(round(abs(v) * 1e6))
    return n | 0x80000000 if v < 0 else n


def make_grib(values: list[float | None], ni: int, nj: int, lat_first: float, lon_first: float, step: float,
              ref_time: datetime, lead_h: int, cat: int = 2, num: int = 2, south_to_north: bool = True,
              decimals: int = 1) -> bytes:
    """values in Dateireihenfolge (ni*nj); None wird über die Bitmaske ausgelassen."""
    assert len(values) == ni * nj
    present = [v is not None for v in values]
    ints = [round(v * 10 ** decimals) for v in values if v is not None]
    ref = min(ints) if ints else 0
    packed = [i - ref for i in ints]
    assert all(0 <= p < 65536 for p in packed)

    s1 = bytearray(21)
    struct.pack_into(">IB", s1, 0, 21, 1)
    struct.pack_into(">HHBBB", s1, 5, 78, 0, 28, 0, 1)
    struct.pack_into(">HBBBBB", s1, 12, ref_time.year, ref_time.month, ref_time.day, ref_time.hour, ref_time.minute, ref_time.second)

    lat_last = lat_first + (nj - 1) * step * (1 if south_to_north else -1)
    s3 = bytearray(72)
    struct.pack_into(">IB", s3, 0, 72, 3)
    struct.pack_into(">I", s3, 6, ni * nj)
    struct.pack_into(">H", s3, 12, 0)
    struct.pack_into(">II", s3, 30, ni, nj)
    st = int(round(step * 1e6))
    struct.pack_into(">IIBIIIIB", s3, 46, _sm32(lat_first), _sm32(lon_first), 48, _sm32(lat_last),
                     _sm32(lon_first + (ni - 1) * step), st, st, 0x40 if south_to_north else 0)

    s4 = bytearray(34)
    struct.pack_into(">IB", s4, 0, 34, 4)
    s4[9], s4[10] = cat, num
    s4[17] = 1  # Einheit Stunden
    struct.pack_into(">I", s4, 18, lead_h)

    s5 = bytearray(21)
    struct.pack_into(">IB", s5, 0, 21, 5)
    struct.pack_into(">I", s5, 5, len(ints))
    struct.pack_into(">f", s5, 11, float(ref))
    struct.pack_into(">HH", s5, 15, 0, decimals)
    s5[19] = 16

    if all(present):
        s6 = struct.pack(">IBB", 6, 6, 255)
    else:
        bits = bytearray((len(values) + 7) // 8)
        for k, p in enumerate(present):
            if p:
                bits[k >> 3] |= 0x80 >> (k & 7)
        s6 = struct.pack(">IBB", 6 + len(bits), 6, 0) + bytes(bits)

    data = b"".join(struct.pack(">H", p) for p in packed)
    s7 = struct.pack(">IB", 5 + len(data), 7) + data
    body = bytes(s1) + bytes(s3) + bytes(s4) + bytes(s5) + s6 + s7
    total = 16 + len(body) + 4
    return b"GRIB\x00\x00\x00\x02" + struct.pack(">Q", total) + body + b"7777"
