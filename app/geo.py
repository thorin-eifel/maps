"""Geo-Hilfen: Haversine, Bounding-Box-Vorfilter, Distanz zu Geometrien.

Zweck:    Alles, was außerhalb der Region (region.yaml) liegt, wird am Rand verworfen
          (Collector-Regel), nicht erst im UI.
Beispiel: from app.geo import in_region, geometry_in_region
          in_region(49.85, 6.45)
          geometry_in_region({"type": "Point", "coordinates": [6.45, 49.85]})

Hinweis:  Distanz zu Linien/Flächen wird in einer lokalen ebenen Projektion
          (Äquirektangular um den Bezugspunkt) berechnet. Auf 120 km Skala liegt der
          Fehler im Bereich weniger Meter. Für Polygon-Regionen prüft geometry_in_region
          Stützpunkte und alle 2 km einen Punkt auf den Strecken.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Iterator

from . import region as _region

EARTH_RADIUS_KM = 6371.0088

Coord = tuple[float, float]  # (lon, lat) — GeoJSON-Reihenfolge


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def in_region(lat: float, lon: float, margin_km: float = 0.0) -> bool:
    """Liegt der Punkt in der Region? (Kasten als Vorfilter, dann Kreis oder Polygon; siehe app/region.py)"""
    return _region.REGION.contains(lat, lon, margin_km)


def distance_to_ref_km(lat: float, lon: float) -> float:
    """Entfernung zum Bezugspunkt der Region (Irrel), nur zur Anzeige."""
    return _region.REGION.distance_to_ref_km(lat, lon)


def in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float] | None = None) -> bool:
    bbox = bbox or _region.REGION.bbox
    lat_min, lon_min, lat_max, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _project(lon: float, lat: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Lokale ebene Projektion in km, Ursprung im Zentrum."""
    x = math.radians(lon - lon0) * math.cos(math.radians(lat0)) * EARTH_RADIUS_KM
    y = math.radians(lat - lat0) * EARTH_RADIUS_KM
    return x, y


def _dist_point_segment(ax: float, ay: float, bx: float, by: float) -> float:
    """Abstand des Ursprungs (0,0) zur Strecke A–B."""
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
    return math.hypot(ax + t * dx, ay + t * dy)


def _point_in_ring(ring: list[tuple[float, float]]) -> bool:
    """Liegt der Ursprung (0,0) im Ring? (Ray Casting)"""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > 0) != (y2 > 0):
            x_cross = x1 + (0 - y1) * (x2 - x1) / (y2 - y1)
            if x_cross > 0:
                inside = not inside
    return inside


def _iter_parts(geom: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "GeometryCollection":
        for g in geom.get("geometries", []):
            yield from _iter_parts(g)
    elif gtype == "Point":
        yield "point", coords
    elif gtype == "MultiPoint":
        for c in coords:
            yield "point", c
    elif gtype == "LineString":
        yield "line", coords
    elif gtype == "MultiLineString":
        for c in coords:
            yield "line", c
    elif gtype == "Polygon":
        yield "polygon", coords
    elif gtype == "MultiPolygon":
        for poly in coords:
            yield "polygon", poly
    else:
        raise ValueError(f"Unbekannter Geometrietyp: {gtype!r}")


def geometry_distance_km(
    geom: dict[str, Any], lat0: float | None = None, lon0: float | None = None
) -> float:
    """Kleinster Abstand der Geometrie zum Bezugspunkt in km (0 bei Bezugspunkt innerhalb einer Fläche)."""
    lat0 = _region.REGION.ref_lat if lat0 is None else lat0
    lon0 = _region.REGION.ref_lon if lon0 is None else lon0
    best = math.inf
    for kind, part in _iter_parts(geom):
        if kind == "point":
            x, y = _project(part[0], part[1], lat0, lon0)
            best = min(best, math.hypot(x, y))
        elif kind == "line":
            pts = [_project(c[0], c[1], lat0, lon0) for c in part]
            for a, b in zip(pts, pts[1:]):
                best = min(best, _dist_point_segment(*a, *b))
            if len(pts) == 1:
                best = min(best, math.hypot(*pts[0]))
        else:  # polygon: Außenring + Löcher
            rings = [[_project(c[0], c[1], lat0, lon0) for c in ring] for ring in part]
            if not rings or not rings[0]:
                continue
            outer, holes = rings[0], rings[1:]
            if _point_in_ring(outer) and not any(_point_in_ring(h) for h in holes):
                return 0.0
            for ring in rings:
                for a, b in zip(ring, ring[1:] + ring[:1]):
                    best = min(best, _dist_point_segment(*a, *b))
    if math.isinf(best):
        raise ValueError("Leere Geometrie")
    return best


def iter_coords(geom: dict[str, Any]) -> Iterable[Coord]:
    for _, part in _iter_parts(geom):
        if isinstance(part[0], (int, float)):
            yield part[0], part[1]
        elif isinstance(part[0][0], (int, float)):
            for c in part:
                yield c[0], c[1]
        else:
            for ring in part:
                for c in ring:
                    yield c[0], c[1]


def geometry_bbox(geom: dict[str, Any]) -> tuple[float, float, float, float]:
    """(lat_min, lon_min, lat_max, lon_max) der Geometrie."""
    coords = list(iter_coords(geom))
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return min(lats), min(lons), max(lats), max(lons)


def bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _densified(coords: list[Coord], step_km: float = 2.0) -> Iterator[Coord]:
    """Stützpunkte plus Zwischenpunkte im Abstand von höchstens step_km auf jeder Strecke."""
    for i, (lon, lat) in enumerate(coords):
        yield lon, lat
        if i + 1 < len(coords):
            lon2, lat2 = coords[i + 1]
            n = int(haversine_km(lat, lon, lat2, lon2) // step_km)
            for k in range(1, n + 1):
                t = k / (n + 1)
                yield lon + (lon2 - lon) * t, lat + (lat2 - lat) * t


def geometry_in_region(geom: dict[str, Any]) -> bool:
    """Berührt die Geometrie die Region? Vorfilter über den Kasten, dann Feinfilter.
    Kreis: Abstand der Geometrie zum Mittelpunkt höchstens Radius. Polygon: ein Stützpunkt oder ein Punkt auf einer
    Strecke liegt in der Region, oder die Region liegt innerhalb einer Fläche (Bezugspunkt in der Fläche)."""
    reg = _region.REGION
    if not bbox_intersects(geometry_bbox(geom), reg.bbox):
        return False
    if reg.mode == "radius":
        return geometry_distance_km(geom, reg.ref_lat, reg.ref_lon) <= (reg.radius_km or 0.0)
    for kind, part in _iter_parts(geom):
        if kind == "point":
            if reg.contains(part[1], part[0]):
                return True
        else:
            rings = [part] if kind == "line" else part
            for ring in rings:
                if any(reg.contains(la, lo) for lo, la in _densified([(c[0], c[1]) for c in ring])):
                    return True
    return geometry_distance_km(geom, reg.ref_lat, reg.ref_lon) == 0.0  # Bezugspunkt liegt in einer Fläche


def representative_point(geom: dict[str, Any]) -> tuple[float, float]:
    """(lat, lon) für Kartenmarker und Listen: Punkt selbst, sonst Mitte der Bounding Box."""
    if geom.get("type") == "Point":
        lon, lat = geom["coordinates"][:2]
        return lat, lon
    lat_min, lon_min, lat_max, lon_max = geometry_bbox(geom)
    return (lat_min + lat_max) / 2, (lon_min + lon_max) / 2


def utm32_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """ETRS89 / UTM Zone 32N (EPSG:25832) → (lat, lon) in Grad. Umkehrabbildung der Gauß-Krüger-Reihe (Snyder),
    Genauigkeit im Meterbereich, reicht für Pegelpunkte. ETRS89 und WGS84 unterscheiden sich um unter einen Meter."""
    a, f, k0 = 6378137.0, 1 / 298.257222101, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    x, y = easting - 500000.0, northing
    mu = (y / k0) / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu) + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
           + (151 * e1**3 / 96) * math.sin(6 * mu) + (1097 * e1**4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(phi), math.cos(phi), math.tan(phi)
    n1 = a / math.sqrt(1 - e2 * s * s)
    t1, c1 = t * t, ep2 * c * c
    r1 = a * (1 - e2) / (1 - e2 * s * s) ** 1.5
    d = x / (n1 * k0)
    lat = phi - (n1 * t / r1) * (d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
                                 + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d**3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120) / c
    return math.degrees(lat), 9.0 + math.degrees(lon)
