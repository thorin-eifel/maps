"""Minimaler GRIB2-Leser für regelmäßige Breiten-/Längenraster mit einfacher Packung.

Zweck:      Die DWD-Modelldateien (ICON-D2, „regular-lat-lon“) lesen, ohne eccodes oder numpy nachzuinstallieren.
            Unterstützt genau das, was der DWD dafür ausliefert: Gitterschablone 3.0 (Breite/Länge), Datenschablone 5.0
            (einfache Packung, 8/16/24/32 Bit je Wert), optionale Bitmaske (Abschnitt 6). Alles andere ergibt einen
            klaren GribError statt falscher Zahlen.
Aufruf:     field = read_field(bz2.decompress(raw))        # genau eine Nachricht je Datei, wie beim DWD
            field.value(i, j)                               # i = Spalte (West→Ost), j = Zeile in Dateireihenfolge
Hinweis:    Zeilenreihenfolge steht in `field.south_to_north` (Scan-Bit 0x40). Längen sind auf -180..180 normiert.
"""
from __future__ import annotations

import struct
from array import array
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sys import byteorder


class GribError(ValueError):
    """Datei ist kein lesbares oder kein unterstütztes GRIB2."""


@dataclass
class GribField:
    discipline: int
    category: int
    number: int
    ref_time: datetime        # Modelllauf (UTC)
    lead_min: int             # Vorhersageschritt in Minuten
    ni: int                   # Punkte West→Ost
    nj: int                   # Punkte Nord–Süd
    lat_first: float
    lon_first: float          # -180..180
    dlat: float               # Schrittweite in Grad, immer positiv
    dlon: float
    south_to_north: bool      # True: Zeile 0 liegt im Süden
    values: list[float | None]  # ni*nj in Dateireihenfolge, None = laut Bitmaske ohne Wert

    @property
    def valid_time(self) -> datetime:
        return self.ref_time + timedelta(minutes=self.lead_min)

    def value(self, i: int, j: int) -> float | None:
        return self.values[j * self.ni + i]

    def lat_of_row(self, j: int) -> float:
        return self.lat_first + (j if self.south_to_north else -j) * self.dlat

    def lon_of_col(self, i: int) -> float:
        lon = self.lon_first + i * self.dlon
        return ((lon + 180.0) % 360.0) - 180.0


def _sm(raw: int, bits: int) -> int:
    """Vorzeichen-Betrag-Zahl (GRIB2 für Winkel und Skalenfaktoren)."""
    sign = 1 << (bits - 1)
    return -(raw & (sign - 1)) if raw & sign else raw


def _unpack(data: bytes, nbits: int, count: int) -> list[int]:
    if nbits == 0:
        return [0] * count
    if nbits in (8, 16, 32):
        code = {8: "B", 16: "H", 32: "I"}[nbits]
        arr = array(code)
        arr.frombytes(data[: count * nbits // 8])
        if byteorder == "little" and nbits > 8:
            arr.byteswap()
        if len(arr) != count:
            raise GribError(f"Datenabschnitt zu kurz: {len(arr)} von {count} Werten")
        return arr.tolist()
    if nbits == 24:
        if len(data) < count * 3:
            raise GribError("Datenabschnitt zu kurz")
        return [(data[k] << 16) | (data[k + 1] << 8) | data[k + 2] for k in range(0, count * 3, 3)]
    raise GribError(f"Packungsbreite {nbits} Bit nicht unterstützt")


def read_field(blob: bytes) -> GribField:
    if blob[:4] != b"GRIB":
        raise GribError("keine GRIB-Datei")
    if blob[7] != 2:
        raise GribError(f"GRIB-Edition {blob[7]} nicht unterstützt (erwartet 2)")
    discipline = blob[6]
    total = struct.unpack(">Q", blob[8:16])[0]
    if total > len(blob) or blob[total - 4: total] != b"7777":
        raise GribError("Datei abgeschnitten oder ohne Endmarke 7777")
    pos = 16
    ref_time = None
    grid = None
    cat = num = None
    lead = 0
    pack = None
    bitmap: bytes | None = None
    npts_grid = 0
    data: bytes | None = None
    while pos < total - 4:
        ln = struct.unpack(">I", blob[pos: pos + 4])[0]
        sec = blob[pos + 4]
        body = blob[pos: pos + ln]
        if sec == 1:
            y, mo, d, h, mi, s = struct.unpack(">HBBBBB", body[12:19])
            ref_time = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
        elif sec == 3:
            npts_grid = struct.unpack(">I", body[6:10])[0]
            tmpl = struct.unpack(">H", body[12:14])[0]
            if tmpl != 0:
                raise GribError(f"Gitterschablone 3.{tmpl} nicht unterstützt (erwartet 3.0)")
            ni, nj = struct.unpack(">II", body[30:38])
            la1, lo1, _, la2, lo2, di, dj, scan = struct.unpack(">IIBIIIIB", body[46:72])
            grid = (ni, nj, _sm(la1, 32) / 1e6, _sm(lo1, 32) / 1e6, abs(di) / 1e6, abs(dj) / 1e6, scan)
            if ni * nj != npts_grid:
                raise GribError("Gitterpunkte passen nicht zu Ni*Nj")
            if scan & 0x80 or scan & 0x20:
                raise GribError(f"Scan-Modus {scan:#04x} nicht unterstützt")
        elif sec == 4:
            tmpl = struct.unpack(">H", body[7:9])[0]
            if tmpl != 0:
                raise GribError(f"Produktschablone 4.{tmpl} nicht unterstützt (erwartet 4.0)")
            cat, num = body[9], body[10]
            unit, val = body[17], struct.unpack(">I", body[18:22])[0]
            mult = {0: 1, 1: 60, 2: 1440, 10: 180, 11: 360, 12: 720, 13: 1 / 60}.get(unit)
            if mult is None:
                raise GribError(f"Zeiteinheit {unit} nicht unterstützt")
            lead = int(round(val * mult))
        elif sec == 5:
            ndata = struct.unpack(">I", body[5:9])[0]
            tmpl = struct.unpack(">H", body[9:11])[0]
            if tmpl != 0:
                raise GribError(f"Datenschablone 5.{tmpl} nicht unterstützt (erwartet 5.0, einfache Packung)")
            ref = struct.unpack(">f", body[11:15])[0]
            e = _sm(struct.unpack(">H", body[15:17])[0], 16)
            dd = _sm(struct.unpack(">H", body[17:19])[0], 16)
            pack = (ndata, ref, e, dd, body[19])
        elif sec == 6:
            if body[5] == 0:
                bitmap = body[6:]
            elif body[5] != 255:
                raise GribError(f"Bitmaske-Indikator {body[5]} nicht unterstützt")
        elif sec == 7:
            data = body[5:]
        pos += ln
    if None in (ref_time, grid, cat, pack, data):
        raise GribError("Pflichtabschnitte fehlen")
    ndata, ref, e, dd, nbits = pack
    raw = _unpack(data, nbits, ndata)
    scale, dec = 2.0 ** e, 10.0 ** dd
    vals = [(ref + x * scale) / dec for x in raw]
    if bitmap is None:
        if ndata != npts_grid:
            raise GribError("Wertezahl passt nicht zum Gitter und es gibt keine Bitmaske")
        out: list[float | None] = vals
    else:
        out = []
        it = iter(vals)
        for k in range(npts_grid):
            present = bitmap[k >> 3] & (0x80 >> (k & 7))
            out.append(next(it) if present else None)
    ni, nj, la1, lo1, dlon, dlat, scan = grid
    return GribField(discipline, cat, num, ref_time, lead, ni, nj, la1, ((lo1 + 180.0) % 360.0) - 180.0, dlat, dlon, bool(scan & 0x40), out)
