"""Blitze aus dem Lightning Imager des Satelliten Meteosat Third Generation (MTG-I1) als Bild für die Karte.

Quelle:     https://view.eumetsat.int/geoserver/wms  (Layer mtg_fd:li_afa, „LI Accumulated Flash Area“, 5-Minuten-Raster)
Betreiber:  EUMETSAT (europäische Wetter-Satellitenorganisation, von den Mitgliedsstaaten finanziert)
Lizenz:     siehe sources.yaml; Nutzungsbedingungen von EUMETView/MTG-Daten sind NICHT abschließend geprüft
Intervall:  300 s
Beispiel:   python -m app.collect --once --only eumetsat_li
Warum nicht Blitzortung/LightningMaps: deren Seite untersagt die kommerzielle Nutzung der Blitzdaten (CTW ist eine GmbH).

Vorgehen:   Die letzten 9 Zeitschritte (45 Minuten) werden als transparente Bilder geholt. Jeder Bildpunkt mit Blitzen wird nach
            Alter eingefärbt (wie bei LightningMaps: gelb = neu, orange, rot, dunkelrot = älter), zu einem Bild zusammengesetzt und
            weich vergrößert. Es entsteht kein Ereignis und keine Messreihe; auch „keine Blitze“ ist ein gültiges, sichtbares Ergebnis.
Grenzen:    Zellgröße rund 2 km, Verzögerung des Dienstes etwa 10 bis 20 Minuten. Das ist ein Lagebild, kein Blitzwarndienst.
            Fragt man einen Zeitschritt nach dem jüngsten vorhandenen ab, liefert der Dienst den jüngsten (nearestValue);
            zwei aufeinanderfolgende identische Bilder werden deshalb nur einmal gezählt.
"""
from __future__ import annotations

import asyncio
import base64
import io
import math
from datetime import datetime, timedelta
from typing import Any

import httpx
from PIL import Image, ImageFilter

from ..models import iso, utcnow
from .base import Collector, CollectResult, SourceError

LON0, LAT0, LON1, LAT1 = 4.4, 48.4, 8.5, 51.3   # wie das Regenradar
WIDTH = 187          # gleiche Auflösung wie zuvor (~45 Bildpunkte je Grad), nur größerer Ausschnitt
STEPS = 9            # 9 × 5 Minuten
LAG_MIN = 10
UPSCALE = 6
BLUR_PX = 1.6
ALPHA_GAIN = 1.9
# (bis Alter in Minuten, Farbe, Bezeichnung)
BANDS = [(10, (255, 230, 0), "bis 10 min"), (20, (255, 150, 0), "bis 20 min"), (30, (255, 59, 31), "bis 30 min"), (45, (163, 13, 13), "bis 45 min")]


def _merc(lon: float, lat: float) -> tuple[float, float]:
    r = 6378137.0
    return math.radians(lon) * r, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r


def render_flashes(frames: list[tuple[float, bytes]]) -> tuple[bytes, dict[str, int]]:
    """frames: (Alter in Minuten, PNG) von alt nach neu. Ergebnis: eingefärbtes, weich vergrößertes PNG und Zellzahl je Altersstufe."""
    counts = {label: 0 for _, _, label in BANDS}
    canvas: Image.Image | None = None
    for age, png in frames:
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        if canvas is None:
            canvas = Image.new("RGBA", im.size, (0, 0, 0, 0))
        band = next(((c, lbl) for limit, c, lbl in BANDS if age <= limit), None)
        if band is None:
            continue
        colour, label = band
        mask = im.getchannel("A").point(lambda a: 255 if a > 0 else 0)
        counts[label] += sum(1 for v in mask.getdata() if v)
        canvas.paste(Image.new("RGBA", im.size, (*colour, 255)), (0, 0), mask)
    if canvas is None:
        raise SourceError("kein Bild zum Zusammensetzen")
    big = canvas.convert("RGBa").resize((canvas.width * UPSCALE, canvas.height * UPSCALE), Image.NEAREST).filter(ImageFilter.GaussianBlur(BLUR_PX))
    big = big.convert("RGBA")
    big.putalpha(big.getchannel("A").point(lambda a: min(255, int(a * ALPHA_GAIN))))
    out = io.BytesIO()
    big.save(out, format="PNG", optimize=True)
    return out.getvalue(), counts


class EumetsatLiCollector(Collector):
    pause_s = 0.2

    async def _map(self, when: datetime) -> bytes | None:
        x0, y0 = _merc(LON0, LAT0)
        x1, y1 = _merc(LON1, LAT1)
        height = round(WIDTH * (y1 - y0) / (x1 - x0))
        resp = await self.client.get(self.entry.url, params={
            "service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": "mtg_fd:li_afa", "styles": "",
            "format": "image/png", "transparent": "true", "crs": "EPSG:3857", "bbox": f"{x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}",
            "width": WIDTH, "height": height, "time": when.strftime("%Y-%m-%dT%H:%M:00Z"),
        }, headers={"User-Agent": self.settings.user_agent}, timeout=self.settings.http_timeout_s)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code == 200 and ctype.startswith("image/png"):
            return resp.content
        if resp.status_code == 200 and b"InvalidDimensionValue" in resp.content:
            return None
        raise SourceError(f"WMS GetMap: HTTP {resp.status_code}, {ctype or 'ohne Content-Type'}")

    async def collect(self) -> CollectResult:
        now = utcnow()
        t0 = now - timedelta(minutes=LAG_MIN)
        t0 = t0.replace(minute=t0.minute // 5 * 5, second=0, microsecond=0)
        got: list[tuple[datetime, bytes]] = []   # neu → alt
        failed = 0
        for step in range(STEPS):
            when = t0 - timedelta(minutes=5 * step)
            png = None
            for attempt in range(3):   # der Dienst antwortet gelegentlich mit 500; ein Zeitschritt darf nicht den ganzen Lauf kosten
                try:
                    png = await self._map(when)
                    break
                except (httpx.HTTPError, SourceError) as exc:
                    self.log.warning("Zeitschritt %s, Versuch %d: %s", when.strftime("%H:%M"), attempt + 1, exc)
                    if attempt == 2:
                        failed += 1
                    else:
                        await asyncio.sleep(1.0 + attempt)
            if png:
                got.append((when, png))
            await asyncio.sleep(self.pause_s)
        if failed == STEPS:
            raise SourceError("WMS: alle Zeitschritte fehlgeschlagen")
        if not got:
            raise SourceError("WMS: kein Blitzbild für die letzten 45 Minuten")
        frames: list[tuple[float, bytes]] = []
        prev: bytes | None = None
        for when, png in reversed(got):   # alt → neu
            if png == prev:
                continue
            prev = png
            frames.append(((now - when).total_seconds() / 60, png))
        png, counts = render_flashes(frames)
        newest = got[0][0]
        payload: dict[str, Any] = {
            "time": iso(newest), "corners": [[LON0, LAT1], [LON1, LAT1], [LON1, LAT0], [LON0, LAT0]],
            "png_b64": base64.b64encode(png).decode("ascii"), "counts": counts, "window_min": STEPS * 5,
        }
        note = f"teilweise: {failed} von {STEPS} Zeitschritten fehlgeschlagen" if failed else None
        return CollectResult(cache={"blitz": payload}, writes_events=False, complete=not failed, note=note)


COLLECTOR = EumetsatLiCollector
