"""Raumzellen für den Export: welche Zelle(n) eine Geometrie berührt.

Zweck:     Das Frontend lädt nur die Zellen im Bildausschnitt nach. Dafür wird die Fläche in feste Zellen von 0,5 Grad geteilt.
Raster:    x = floor(lon * 2), y = floor(lat * 2); Zelle "x_y" deckt lon [x/2, x/2 + 0,5) und lat [y/2, y/2 + 0,5) ab.
           Beispiel Irrel (6,45 E, 49,85 N): x = 12, y = 99, also "12_99".
Regeln:    Punkt: genau eine Zelle; liegt er auf einer Kante, gehört er der höheren Zelle (floor).
           Linie: jede Zelle, die von einem Abschnitt berührt wird (Kante zählt mit, also im Zweifel beide Zellen).
           Fläche: jede Zelle, die Rand oder Innenfläche der Fläche berührt (Löcher werden beachtet).
           Eine Geometrie liegt also bei Bedarf in mehreren Zellen; das Frontend entfernt Dubletten über die Kennung.
Reine Funktionen, keine Abhängigkeiten.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

CELL_DEG = 0.5
PER_DEG = int(round(1 / CELL_DEG))
MAX_CELLS_PER_GEOMETRY = 400        # Schutz gegen entartete Eingaben; ganz Rheinland-Pfalz hat rund 70 Zellen

Cell = tuple[int, int]


def cell_of(lon: float, lat: float) -> Cell:
    return math.floor(lon * PER_DEG), math.floor(lat * PER_DEG)


def cell_id(c: Cell) -> str:
    return f"{c[0]}_{c[1]}"


def parse_cell_id(s: str) -> Cell:
    x, y = s.split("_")
    return int(x), int(y)


def cell_bbox(c: Cell) -> tuple[float, float, float, float]:
    """(west, süd, ost, nord)"""
    return c[0] / PER_DEG, c[1] / PER_DEG, (c[0] + 1) / PER_DEG, (c[1] + 1) / PER_DEG


def _seg_hits_rect(x1: float, y1: float, x2: float, y2: float, r: tuple[float, float, float, float]) -> bool:
    """Liang-Barsky: schneidet oder berührt die Strecke das Rechteck (Kanten zählen mit)?"""
    xmin, ymin, xmax, ymax = r
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - xmin), (dx, xmax - x1), (-dy, y1 - ymin), (dy, ymax - y1)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return False
            t0 = max(t0, t)
        else:
            if t < t0:
                return False
            t1 = min(t1, t)
    return t0 <= t1


def _line_cells(coords: list[list[float]], out: set[Cell]) -> None:
    prev = None
    for pt in coords:
        lon, lat = float(pt[0]), float(pt[1])
        out.add(cell_of(lon, lat))
        if prev is not None:
            (x1, y1), (x2, y2) = prev, (lon, lat)
            c0, c1 = cell_of(min(x1, x2), min(y1, y2)), cell_of(max(x1, x2), max(y1, y2))
            if c0 != c1:
                for cx in range(c0[0], c1[0] + 1):
                    for cy in range(c0[1], c1[1] + 1):
                        if (cx, cy) not in out and _seg_hits_rect(x1, y1, x2, y2, cell_bbox((cx, cy))):
                            out.add((cx, cy))
                if len(out) > MAX_CELLS_PER_GEOMETRY:
                    raise ValueError("Geometrie berührt zu viele Zellen")
        prev = (lon, lat)


def _inside(rings: list[list[list[float]]], lon: float, lat: float) -> bool:
    """Even-odd über alle Ringe (Löcher inklusive)."""
    inside = False
    for ring in rings:
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def _polygon_cells(rings: list[list[list[float]]], out: set[Cell]) -> None:
    edge: set[Cell] = set()
    for ring in rings:
        _line_cells(ring, edge)
    out |= edge
    xs = [p[0] for ring in rings[:1] for p in ring]
    ys = [p[1] for ring in rings[:1] for p in ring]
    if not xs:
        return
    c0, c1 = cell_of(min(xs), min(ys)), cell_of(max(xs), max(ys))
    if (c1[0] - c0[0] + 1) * (c1[1] - c0[1] + 1) > MAX_CELLS_PER_GEOMETRY * 4:
        raise ValueError("Fläche berührt zu viele Zellen")
    for cx in range(c0[0], c1[0] + 1):
        for cy in range(c0[1], c1[1] + 1):
            if (cx, cy) in edge:
                continue
            w, s, e, n = cell_bbox((cx, cy))
            if _inside(rings, (w + e) / 2, (s + n) / 2):    # Rand berührt die Zelle nicht: ganz drin oder ganz draußen
                out.add((cx, cy))
    if len(out) > MAX_CELLS_PER_GEOMETRY:
        raise ValueError("Fläche berührt zu viele Zellen")


def cells_for_geometry(geom: dict[str, Any] | None) -> set[Cell]:
    """GeoJSON-Geometrie → Menge von Zellen. Leere oder unbekannte Geometrie → leere Menge."""
    out: set[Cell] = set()
    if not isinstance(geom, dict):
        return out
    t, c = geom.get("type"), geom.get("coordinates")
    if not c:
        return out
    if t == "Point":
        out.add(cell_of(c[0], c[1]))
    elif t == "MultiPoint":
        out.update(cell_of(p[0], p[1]) for p in c)
    elif t == "LineString":
        _line_cells(c, out)
    elif t == "MultiLineString":
        for line in c:
            _line_cells(line, out)
    elif t == "Polygon":
        _polygon_cells(c, out)
    elif t == "MultiPolygon":
        for poly in c:
            _polygon_cells(poly, out)
    elif t == "GeometryCollection":
        for g in geom.get("geometries") or []:
            out |= cells_for_geometry(g)
    return out


def cells_for_lines(lines: Iterable[list[list[float]]]) -> set[Cell]:
    out: set[Cell] = set()
    for line in lines:
        _line_cells(line, out)
    return out


def cells_for_point(lat: Any, lon: Any) -> set[Cell]:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return set()
    if math.isnan(la) or math.isnan(lo):
        return set()
    return {cell_of(lo, la)}
