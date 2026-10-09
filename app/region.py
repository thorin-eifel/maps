"""Region: die Fläche, für die das Lagebild gilt.

Zweck:      Ersetzt die festen Konstanten RADIUS_KM, CENTER_* und BBOX. Eine Region ist entweder ein Kreis um einen
            Mittelpunkt (mode: radius) oder ein Polygon, z. B. Rheinland-Pfalz plus 80 km (mode: polygon).
Konfig:     region.yaml im Projektordner, anderer Pfad über OSINT_REGION. OSINT_CENTER_LAT/-LON überschreiben den
            Bezugspunkt (Desktop-App).
Beispiel:   from app.region import REGION
            REGION.contains(49.85, 6.45)          # True
            REGION.bbox                           # (lat_min, lon_min, lat_max, lon_max)
            python -m app.region                  # zeigt die aktive Region

Aufbau:     contains() prüft erst den Kasten (billig), dann den Kreis bzw. das Polygon. Das Polygon liegt fertig
            gepuffert in app/data/region/*.json (gebaut von tools/build_region.py aus BKG VG250). Punkt-im-Polygon
            läuft über einen Streifenindex der Kanten, damit ein Test nicht über tausende Kanten geht.
Hinweis:    Der Bezugspunkt (reference) ist nur der Ort, zu dem Entfernungen angezeigt werden (Irrel). Er sagt nichts
            darüber, was in der Region liegt.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
EARTH_RADIUS_KM = 6371.0088
STRIPS = 256

BBox = tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bbox_around(lat: float, lon: float, km: float) -> BBox:
    """Umschließender Kasten um den Kreis, nach außen auf 0,01° gerundet."""
    dlat = km / 111.195
    dlon = km / (111.195 * math.cos(math.radians(lat)))
    return (math.floor((lat - dlat) * 100) / 100, math.floor((lon - dlon) * 100) / 100,
            math.ceil((lat + dlat) * 100) / 100, math.ceil((lon + dlon) * 100) / 100)


class PolygonIndex:
    """Punkt-im-Polygon (gerade-ungerade Regel, Löcher und Teilflächen inklusive) mit Streifenindex über die Breite."""

    def __init__(self, polygons: list[list[list[list[float]]]]):
        # polygons: [[ring, ring, ...], ...], ring = [[lon, lat], ...]
        edges = []
        for poly in polygons:
            for ring in poly:
                n = len(ring)
                for i in range(n):
                    (x1, y1), (x2, y2) = ring[i][:2], ring[(i + 1) % n][:2]
                    if y1 != y2:
                        edges.append((x1, y1, x2, y2))
        if not edges:
            raise ValueError("Polygon ohne Kanten")
        self.lat_min = min(min(e[1], e[3]) for e in edges)
        self.lat_max = max(max(e[1], e[3]) for e in edges)
        self.lon_min = min(min(e[0], e[2]) for e in edges)
        self.lon_max = max(max(e[0], e[2]) for e in edges)
        self._h = (self.lat_max - self.lat_min) / STRIPS or 1e-9
        self._strips: list[list[tuple[float, float, float, float]]] = [[] for _ in range(STRIPS)]
        for e in edges:
            lo, hi = sorted((e[1], e[3]))
            for s in range(self._strip(lo), self._strip(hi) + 1):
                self._strips[s].append(e)

    def _strip(self, lat: float) -> int:
        return max(0, min(STRIPS - 1, int((lat - self.lat_min) / self._h)))

    def contains(self, lat: float, lon: float) -> bool:
        if not (self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max):
            return False
        inside = False
        for x1, y1, x2, y2 in self._strips[self._strip(lat)]:
            if (y1 > lat) != (y2 > lat) and x1 + (lat - y1) * (x2 - x1) / (y2 - y1) > lon:
                inside = not inside
        return inside


@dataclass(frozen=True)
class Region:
    name: str
    mode: str                      # "radius" | "polygon"
    ref_name: str
    ref_lat: float
    ref_lon: float
    bbox: BBox
    query_lat: float               # Kreis, der die Region umschließt: für Quellen, die nur "Mittelpunkt + Radius" können
    query_lon: float
    query_radius_km: float
    radius_km: float | None = None # nur im Modus radius
    attribution: str = ""
    source_file: str = ""
    _index: PolygonIndex | None = field(default=None, repr=False, compare=False)

    def contains(self, lat: float, lon: float, margin_km: float = 0.0) -> bool:
        """Liegt der Punkt in der Region? Kasten zuerst, dann Kreis bzw. Polygon.
        margin_km weitet die Region nach außen (Kreis: Radius plus Rand; Polygon: acht Prüfpunkte im Abstand des Rands)."""
        b, m = self.bbox, margin_km / 111.0
        if not (b[0] - m <= lat <= b[2] + m and b[1] - m <= lon <= b[3] + m):
            return False
        if self._index is None:
            return haversine_km(self.ref_lat, self.ref_lon, lat, lon) <= (self.radius_km or 0.0) + margin_km
        if self._index.contains(lat, lon):
            return True
        if margin_km <= 0:
            return False
        dlon = m / max(0.2, math.cos(math.radians(lat)))
        return any(self._index.contains(lat + dy * m, lon + dx * dlon)
                   for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (.7, .7), (.7, -.7), (-.7, .7), (-.7, -.7)))

    def distance_to_ref_km(self, lat: float, lon: float) -> float:
        return haversine_km(self.ref_lat, self.ref_lon, lat, lon)

    def meta(self) -> dict[str, Any]:
        return {"name": self.name, "mode": self.mode, "reference": {"name": self.ref_name, "lat": self.ref_lat, "lon": self.ref_lon},
                "radius_km": self.radius_km, "query_radius_km": round(self.query_radius_km, 1), "attribution": self.attribution}


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else BASE_DIR / p


def load(path: str | Path | None = None) -> Region:
    """Lädt die Region aus region.yaml (oder OSINT_REGION). Fehler sind laut: eine falsche Fläche darf nicht still laufen."""
    cfg_path = _resolve(path or os.environ.get("OSINT_REGION") or "region.yaml")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    mode = cfg.get("mode")
    ref = cfg.get("reference") or {}
    try:
        ref_lat = float(os.environ.get("OSINT_CENTER_LAT", ref["lat"]))
        ref_lon = float(os.environ.get("OSINT_CENTER_LON", ref["lon"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{cfg_path.name}: reference.lat/lon fehlt oder ist keine Zahl") from exc
    name, ref_name = str(cfg.get("name") or "Region"), str(ref.get("name") or "Bezugspunkt")
    if mode == "radius":
        km = float(cfg["radius_km"])
        if not 0 < km <= 1000:
            raise ValueError(f"{cfg_path.name}: radius_km außerhalb von 0 bis 1000")
        return Region(name, mode, ref_name, ref_lat, ref_lon, bbox_around(ref_lat, ref_lon, km),
                      ref_lat, ref_lon, km, km, str(cfg.get("attribution") or ""), cfg_path.name)
    if mode == "polygon":
        poly_path = _resolve(cfg["polygon_file"])
        data = json.loads(poly_path.read_text(encoding="utf-8"))
        polygons = data["polygons"]
        idx = PolygonIndex(polygons)
        bbox = (idx.lat_min, idx.lon_min, idx.lat_max, idx.lon_max)
        qlat, qlon = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        far = max(haversine_km(qlat, qlon, p[1], p[0]) for poly in polygons for ring in poly for p in ring)
        return Region(name, mode, ref_name, ref_lat, ref_lon, bbox, qlat, qlon, math.ceil(far),
                      None, str(cfg.get("attribution") or data.get("attribution") or ""), cfg_path.name, idx)
    raise ValueError(f"{cfg_path.name}: mode muss 'radius' oder 'polygon' sein, nicht {mode!r}")


class Gliederung:
    """Verwaltungsgliederung (Land, Kreis) zu einem Punkt. Daten aus app/data/region/kreise.json (BKG VG250)."""

    def __init__(self, path: str | Path = "app/data/region/kreise.json"):
        data = json.loads(_resolve(path).read_text(encoding="utf-8"))
        self.attribution = data.get("attribution", "")
        self._items = [(k, PolygonIndex(k["polygons"])) for k in data["kreise"]]

    def kreis(self, lat: float, lon: float) -> dict[str, str] | None:
        """{'ars': '07232', 'name': 'Eifelkreis Bitburg-Prüm', 'land': 'DE-RP'} oder None (außerhalb Deutschlands)."""
        for k, idx in self._items:
            if idx.contains(lat, lon):
                return {"ars": k["ars"], "name": k["name"], "land": k["land"]}
        return None


REGION = load()

if __name__ == "__main__":
    print(json.dumps(REGION.meta(), ensure_ascii=False, indent=2), "bbox", REGION.bbox, sep="\n")
