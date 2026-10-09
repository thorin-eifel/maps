"""10-m-Wind aus dem DWD-Modell ICON-D2 als Gitter für die Partikelansicht.

Quelle:     https://opendata.dwd.de/weather/nwp/icon-d2/grib/{HH}/{u_10m|v_10m}/icon-d2_germany_regular-lat-lon_single-level_{JJJJMMTTHH}_{LLL}_2d_{u_10m|v_10m}.grib2.bz2
Betreiber:  Deutscher Wetterdienst (DWD)
Lizenz:     GeoNutzV, Quellenvermerk „Deutscher Wetterdienst (ICON-D2)“ (siehe sources.yaml)
Intervall:  3600 s (das Modell läuft alle 3 Stunden, die Dateien erscheinen etwa 1,5 bis 2 Stunden nach dem Laufzeitpunkt)
Beispiel:   python -m app.collect --once --only dwd_icon_d2_wind

Vorgehen:   Jüngsten Lauf suchen (vom aktuellen 3-Stunden-Zeitpunkt rückwärts), Vorhersageschritt = volle Stunden seit Lauf.
            Fehlt eine Datei (HTTP 404), wird der nächstältere Lauf versucht. Ausschnitt LON0..LAT1, jeder zweite Punkt (~0,04°,
            etwa 3 km), u und v auf 0,1 m/s gerundet. Zeilen von Nord nach Süd, wie Bilder.
Kein Ereignis, keine Messreihe, daher writes_events=False.
"""
from __future__ import annotations

import bz2
from datetime import datetime, timedelta, timezone
from typing import Any

from ..grib import GribError, GribField, read_field
from ..models import iso, utcnow
from .base import Collector, CollectResult, SourceError

LON0, LAT0, LON1, LAT1 = 4.4, 48.4, 8.5, 51.3   # wie das Radarbild
STRIDE = 2
RUN_STEP_H = 3
MAX_RUNS_BACK = 4   # bis 12 Stunden zurück
MAX_BZ2_BYTES = 40_000_000  # Schutz vor Dekompressionsbomben: Dateien sind ~2 MB entpackt


def file_url(base: str, run: datetime, lead_h: int, var: str) -> str:
    stamp = run.strftime("%Y%m%d%H")
    return (f"{base.rstrip('/')}/{run:%H}/{var}/icon-d2_germany_regular-lat-lon_single-level_"
            f"{stamp}_{lead_h:03d}_2d_{var}.grib2.bz2")


def decode(blob: bytes) -> GribField:
    d = bz2.BZ2Decompressor()
    try:
        raw = d.decompress(blob, MAX_BZ2_BYTES)
    except (OSError, ValueError, EOFError) as exc:
        raise SourceError(f"bz2 nicht lesbar: {exc}") from exc
    if not d.eof:
        raise SourceError("bz2 größer als erwartet oder abgeschnitten")
    try:
        return read_field(raw)
    except GribError as exc:
        raise SourceError(f"GRIB nicht lesbar: {exc}") from exc


def crop(u: GribField, v: GribField) -> dict[str, Any]:
    if (u.ni, u.nj, u.lat_first, u.lon_first) != (v.ni, v.nj, v.lat_first, v.lon_first) or u.valid_time != v.valid_time:
        raise SourceError("u und v liegen nicht auf demselben Gitter oder Zeitpunkt")
    cols = [i for i in range(0, u.ni, 1) if LON0 <= u.lon_of_col(i) <= LON1][::STRIDE]
    rows = [j for j in range(u.nj) if LAT0 <= u.lat_of_row(j) <= LAT1]
    if not cols or not rows:
        raise SourceError("Ausschnitt liegt nicht im Modellgitter")
    rows.sort(key=lambda j: -u.lat_of_row(j))   # Nord zuerst
    rows = rows[::STRIDE]

    def grid(f: GribField) -> list[list[float]]:
        return [[round(f.value(i, j) or 0.0, 1) for i in cols] for j in rows]

    return {
        "bbox": [round(u.lon_of_col(cols[0]), 4), round(u.lat_of_row(rows[-1]), 4), round(u.lon_of_col(cols[-1]), 4), round(u.lat_of_row(rows[0]), 4)],
        "nx": len(cols), "ny": len(rows),
        "dlon": round(u.dlon * STRIDE, 4), "dlat": round(u.dlat * STRIDE, 4),
        "u": grid(u), "v": grid(v),
    }


class DwdWindCollector(Collector):
    async def collect(self) -> CollectResult:
        now = utcnow()
        run = now.replace(minute=0, second=0, microsecond=0)
        run -= timedelta(hours=run.hour % RUN_STEP_H)
        last_err = "kein Lauf versucht"
        for back in range(MAX_RUNS_BACK + 1):
            r = run - timedelta(hours=RUN_STEP_H * back)
            lead = max(0, int((now - r).total_seconds() // 3600))
            try:
                ub = await self.fetch_bytes(file_url(self.entry.url, r, lead, "u_10m"))
                vb = await self.fetch_bytes(file_url(self.entry.url, r, lead, "v_10m"))
            except SourceError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                last_err = str(exc)
                continue
            u, v = decode(ub), decode(vb)
            payload = crop(u, v)
            payload.update(time=iso(u.valid_time), run=iso(u.ref_time), lead_h=u.lead_min // 60)
            return CollectResult(cache={"wind": payload}, writes_events=False)
        raise SourceError(f"ICON-D2: keine Windfelder der letzten {RUN_STEP_H * MAX_RUNS_BACK} Stunden ({last_err})")


COLLECTOR = DwdWindCollector
