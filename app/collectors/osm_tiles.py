"""Kacheln für Overpass-Abfragen über ein großes Gebiet.

Zweck:   Eine Abfrage über ganz Rheinland-Pfalz plus 80 km läuft auf den öffentlichen Overpass-Instanzen in das Zeitlimit
         (Fair-Use-Richtlinie, Abfragen über 70 s sind unerwünscht). Das Gebiet wird deshalb in Kacheln geschnitten; jede Kachel ist
         eine kurze Abfrage. Dubletten an den Kachelrändern fallen über die OSM-Kennung weg (die Sammler führen ein Wörterbuch nach id).
Regel:   Im Radius-Modus (Irrel plus 120 km) bleibt es bei einer Kachel wie bisher; nur der Polygon-Modus teilt auf.
         Kacheln, die ganz außerhalb der Region liegen (Ecken des Kastens), werden übersprungen.
Aufruf:  tiles() -> [(süd, west, nord, ost), ...]
"""
from __future__ import annotations

import math

from .. import config
from ..region import REGION

TILE_LAT = 0.8   # Grad, rund 90 km
TILE_LON = 1.2   # Grad, rund 85 km bei 50° N


def tiles(box: tuple[float, float, float, float] | None = None, tile_lat: float = TILE_LAT, tile_lon: float = TILE_LON) -> list[tuple[float, float, float, float]]:
    s, w, n, e = box or config.BBOX
    if REGION.mode != "polygon" and box is None:
        return [(s, w, n, e)]
    rows = max(1, math.ceil((n - s) / tile_lat))
    cols = max(1, math.ceil((e - w) / tile_lon))
    dlat, dlon = (n - s) / rows, (e - w) / cols
    out = []
    for r in range(rows):
        for c in range(cols):
            t = (round(s + r * dlat, 4), round(w + c * dlon, 4), round(s + (r + 1) * dlat, 4), round(w + (c + 1) * dlon, 4))
            if REGION.mode == "polygon" and not _touches_region(t):
                continue
            out.append(t)
    return out


def _touches_region(t: tuple[float, float, float, float]) -> bool:
    """Kachel berührt die Region: Mitte oder eine Ecke liegt in der Region (mit Rand), sonst fällt sie weg."""
    s, w, n, e = t
    pts = [((s + n) / 2, (w + e) / 2), (s, w), (s, e), (n, w), (n, e), (s, (w + e) / 2), (n, (w + e) / 2), ((s + n) / 2, w), ((s + n) / 2, e)]
    return any(REGION.contains(la, lo, margin_km=15) for la, lo in pts)
