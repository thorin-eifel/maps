#!/usr/bin/env python3
"""Kleiner PMTiles-v3-Leser (nur lesen, nur lokale Datei, keine Abhängigkeit außer der Standardbibliothek).

Zweck:    Kacheln aus web/tiles/region.pmtiles lesen, um daraus offline einen Suchindex zu bauen (tools/build_search_index.py).
Aufruf:   python tools/pmtiles_read.py web/tiles/region.pmtiles            # Kopfdaten und Zahl der Kacheln je Zoom
Format:   https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md (Kopf 127 Byte, Verzeichnisse mit Varints, Hilbert-Kachelnummer)
Grenzen:  Erwartet Verzeichnis-Kompression none/gzip und Kachel-Kompression none/gzip (so baut unser tools/build_tiles.sh).
"""
from __future__ import annotations

import gzip
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

COMP_NONE, COMP_GZIP = 1, 2


@dataclass(frozen=True)
class Header:
    root_off: int
    root_len: int
    leaf_off: int
    leaf_len: int
    data_off: int
    data_len: int
    n_tiles: int
    internal_comp: int
    tile_comp: int
    min_zoom: int
    max_zoom: int


def tile_id(z: int, x: int, y: int) -> int:
    """Hilbert-Nummer der Kachel (z, x, y) nach der PMTiles-Spezifikation."""
    if z > 26 or not (0 <= x < (1 << z)) or not (0 <= y < (1 << z)):
        raise ValueError("Kachel außerhalb des Bereichs")
    acc = sum(1 << (2 * t) for t in range(z))
    n = 1 << z
    d = 0
    s = n // 2
    while s > 0:
        rx = 1 if (x & s) > 0 else 0
        ry = 1 if (y & s) > 0 else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:                    # Drehung des Quadranten
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        s //= 2
    return acc + d


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    val = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if b < 0x80:
            return val, pos
        shift += 7


def _decomp(data: bytes, comp: int) -> bytes:
    if comp == COMP_GZIP:
        return gzip.decompress(data)
    if comp == COMP_NONE:
        return data
    raise ValueError(f"Kompression {comp} nicht unterstützt")


class PMTiles:
    def __init__(self, path: str | Path) -> None:
        self.f = open(path, "rb")
        head = self.f.read(127)
        if head[:7] != b"PMTiles" or head[7] != 3:
            raise ValueError("keine PMTiles-v3-Datei")
        o = struct.unpack("<8Q", head[8:72])
        n_tiles = struct.unpack("<Q", head[88:96])[0]
        self.h = Header(o[0], o[1], o[4], o[5], o[6], o[7], n_tiles, head[97], head[98], head[100], head[101])

    def close(self) -> None:
        self.f.close()

    def _read(self, off: int, length: int) -> bytes:
        self.f.seek(off)
        return self.f.read(length)

    def _dir(self, off: int, length: int) -> list[tuple[int, int, int, int]]:
        """Verzeichnis als Liste (tile_id, offset, length, run_length)."""
        buf = _decomp(self._read(off, length), self.h.internal_comp)
        n, pos = _varint(buf, 0)
        ids, runs, lens, offs = [], [], [], []
        last = 0
        for _ in range(n):
            d, pos = _varint(buf, pos)
            last += d
            ids.append(last)
        for _ in range(n):
            r, pos = _varint(buf, pos)
            runs.append(r)
        for _ in range(n):
            ln, pos = _varint(buf, pos)
            lens.append(ln)
        for i in range(n):
            o, pos = _varint(buf, pos)
            offs.append(offs[i - 1] + lens[i - 1] if (o == 0 and i > 0) else o - 1)
        return list(zip(ids, offs, lens, runs))

    def entries(self) -> Iterator[tuple[int, int, int, int]]:
        """Alle Kachel-Einträge (tile_id, offset, length, run_length), Blattverzeichnisse aufgelöst."""
        stack = [(self.h.root_off, self.h.root_len)]
        while stack:
            off, ln = stack.pop()
            for tid, o, length, run in self._dir(off, ln):
                if run == 0:
                    stack.append((self.h.leaf_off + o, length))
                else:
                    yield tid, self.h.data_off + o, length, run

    def tile(self, offset: int, length: int) -> bytes:
        return _decomp(self._read(offset, length), self.h.tile_comp)


def tile_xyz(tid: int) -> tuple[int, int, int]:
    """Umkehrung von tile_id (z, x, y)."""
    z = 0
    acc = 0
    while True:
        cnt = 1 << (2 * z)
        if tid < acc + cnt:
            break
        acc += cnt
        z += 1
    d = tid - acc
    n = 1 << z
    x = y = 0
    t = d
    s = 1
    while s < n:
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        t //= 4
        s *= 2
    return z, x, y


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    pm = PMTiles(argv[1])
    print(pm.h)
    per_zoom: dict[int, int] = {}
    for tid, _o, _l, run in pm.entries():
        z = tile_xyz(tid)[0]
        per_zoom[z] = per_zoom.get(z, 0) + run
    print(dict(sorted(per_zoom.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
