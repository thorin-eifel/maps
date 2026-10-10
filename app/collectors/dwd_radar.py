"""Regenradar des Deutschen Wetterdienstes als Bild für die Karte.

Quelle:     https://maps.dwd.de/geoserver/dwd/wms  (Layer dwd:Niederschlagsradar, RV-Produkt, 1 km, 5 Minuten, mm/h)
Betreiber:  Deutscher Wetterdienst (DWD)
Lizenz:     GeoNutzV, Quellenvermerk „Deutscher Wetterdienst“ (siehe sources.yaml)
Intervall:  300 s
Beispiel:   python -m app.collect --once --only dwd_radar

Der Collector holt ein transparentes PNG (Web Mercator) für den Kartenausschnitt und legt es im Cache ab;
der Export schreibt daraus `radar.png` und `radar.json` (Zeitstempel, Ecken). Der Browser fragt den DWD nie an.
Zeit: das jüngste Bild mit vorhandenem Zeitschritt (5-Minuten-Raster, ab 10 Minuten zurück, bis zu 4 Schritte weiter zurück).
Glättung: Abruf in Rasterauflösung (~1 km), dann bilinear ×6 und Weichzeichner (2 px), siehe smooth().
Nachbearbeitung: Der DWD malt Gebiete ohne Radarabdeckung grau und mit magentafarbenem Rand. Diese Pixel werden
transparent gemacht; „keine Farbe“ heißt darum: kein Niederschlag ODER außerhalb der Radarreichweite (Südwesten, Luxemburg-Süd).
Kein Ereignis, keine Messreihe, daher writes_events=False.
"""
from __future__ import annotations

import base64
import io
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from PIL import Image, ImageFilter

from ..models import iso, utcnow
from ..extent import image_extent, image_width
from .base import Collector, CollectResult, SourceError

# Bildausschnitt: großzügig um die Region, damit auch bei kleinem Maßstab Regen von außen zu sehen ist
LON0, LAT0, LON1, LAT1 = image_extent()   # Region plus Rand, siehe app/extent.py
WIDTH = image_width()   # 45,6 Bildpunkte je Grad, wie bisher
UPSCALE = 6          # Glättung hier: bilinear vergrößern und leicht weichzeichnen, damit die Karte keine Klötzchen zeigt
BLUR_PX = 2.0
NODATA_GREY = (126, 126, 126)


def _merc(lon: float, lat: float) -> tuple[float, float]:
    r = 6378137.0
    return math.radians(lon) * r, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r


def _purple(r: int, g: int, b: int) -> bool:
    return r > g + 15 and b > g + 15


def clean_nodata(png: bytes) -> bytes:
    """Grauflächen (keine Radarabdeckung) und deren magentafarbenen Rand transparent machen.

    Am Rand der Abdeckung bleiben Mischfarben aus Grau und Magenta übrig (violett-graue Pixel, 1 bis 2 Pixel breit). Sie sehen aus wie
    stärkster Regen, sind aber nur der Saum der Abdeckung: Violette Pixel in höchstens 2 Pixeln Abstand zu einem entfernten Pixel
    werden ebenfalls entfernt. Starker Regen im Inneren (violett, weit vom Rand) bleibt."""
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    px = im.load()
    w, h = im.size
    gone = Image.new("L", (w, h), 0)
    gp = gone.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if (abs(r - 126) < 14 and abs(g - 126) < 14 and abs(b - 126) < 14) or (r > 170 and b > 170 and g < 120 and abs(r - b) < 70):
                px[x, y] = (0, 0, 0, 0)
                gp[x, y] = 255
    near = gone.filter(ImageFilter.MaxFilter(5))   # 2 Pixel Umkreis um entfernte Pixel
    np = near.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and np[x, y] and _purple(r, g, b):
                px[x, y] = (0, 0, 0, 0)
    out = io.BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()


def smooth(png: bytes, factor: int = UPSCALE, blur: float = BLUR_PX) -> bytes:
    """Radarraster bilinear vergrößern und leicht weichzeichnen. Mit vormultiplizierter Transparenz (RGBa), sonst entstehen dunkle
    Säume an den Rändern; die Ränder laufen so weich in die Transparenz aus."""
    im = Image.open(io.BytesIO(png)).convert("RGBA").convert("RGBa")
    im = im.resize((im.width * factor, im.height * factor), Image.BILINEAR)
    if blur > 0:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    out = io.BytesIO()
    im.convert("RGBA").save(out, format="PNG", optimize=True)
    return out.getvalue()


class DwdRadarCollector(Collector):
    async def _map(self, when: datetime) -> bytes | None:
        x0, y0 = _merc(LON0, LAT0)
        x1, y1 = _merc(LON1, LAT1)
        height = round(WIDTH * (y1 - y0) / (x1 - x0))
        resp = await self.client.get(self.entry.url, params={
            "service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": "dwd:Niederschlagsradar", "styles": "",
            "format": "image/png", "transparent": "true", "crs": "EPSG:3857", "bbox": f"{x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}",
            "width": WIDTH, "height": height, "time": when.strftime("%Y-%m-%dT%H:%M:00Z"),
        }, headers={"User-Agent": self.settings.user_agent}, timeout=self.settings.http_timeout_s)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code == 200 and ctype.startswith("image/png"):
            return resp.content
        if resp.status_code == 200 and b"InvalidDimensionValue" in resp.content:
            return None  # dieser Zeitschritt existiert (noch) nicht
        raise SourceError(f"WMS GetMap: HTTP {resp.status_code}, {ctype or 'ohne Content-Type'}")

    async def collect(self) -> CollectResult:
        t = utcnow() - timedelta(minutes=10)
        t = t.replace(minute=t.minute // 5 * 5, second=0, microsecond=0)
        png = None
        for step in range(5):
            when = t - timedelta(minutes=5 * step)
            try:
                png = await self._map(when)
            except httpx.HTTPError as exc:
                raise SourceError(f"WMS nicht erreichbar: {type(exc).__name__}: {exc}") from exc
            if png:
                break
        if not png:
            raise SourceError("WMS: kein Radarbild für die letzten 30 Minuten")
        clean = smooth(clean_nodata(png))
        payload: dict[str, Any] = {
            "time": iso(when), "corners": [[LON0, LAT1], [LON1, LAT1], [LON1, LAT0], [LON0, LAT0]],
            "png_b64": base64.b64encode(clean).decode("ascii"),
        }
        return CollectResult(cache={"radar": payload}, writes_events=False)


COLLECTOR = DwdRadarCollector
