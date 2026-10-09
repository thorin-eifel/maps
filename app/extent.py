"""Bildausschnitt für Rasterquellen (Radar, Wind, Blitze), abgeleitet aus der Region.

Zweck:    Radar, Modellwind und Blitze werden als Bild bzw. Gitter für einen Kasten geholt. Der Kasten hängt an der Region:
          - Modus radius (Irrel plus 120 km): feste, bisher bewährte Werte, damit sich dort nichts ändert
          - Modus polygon: Kasten der Region plus Rand (0,4° Länge, 0,35° Breite), damit die Kante bei kleinem Maßstab nicht sichtbar wird
Bildbreite: 45,6 Bildpunkte je Grad Länge, wie bisher (187 Punkte für 4,1°).
Beispiel: from app.extent import image_extent, image_width; lon0, lat0, lon1, lat1 = image_extent()
"""
from __future__ import annotations

from .region import REGION

LEGACY = (4.4, 48.4, 8.5, 51.3)        # lon0, lat0, lon1, lat1
MARGIN_LON, MARGIN_LAT = 0.4, 0.35
PX_PER_DEG = 187 / 4.1


def image_extent() -> tuple[float, float, float, float]:
    """(lon0, lat0, lon1, lat1)."""
    if REGION.mode == "radius":
        return LEGACY
    lat0, lon0, lat1, lon1 = REGION.bbox
    return (round(lon0 - MARGIN_LON, 2), round(lat0 - MARGIN_LAT, 2), round(lon1 + MARGIN_LON, 2), round(lat1 + MARGIN_LAT, 2))


def image_width(extent: tuple[float, float, float, float] | None = None) -> int:
    lon0, _, lon1, _ = extent or image_extent()
    return round((lon1 - lon0) * PX_PER_DEG)
