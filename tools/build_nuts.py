#!/usr/bin/env python3
"""Gebietsgrenzen für MeteoAlarm-Warnungen bauen (app/data/nuts_meteoalarm.json).

Zweck:     MeteoAlarm nennt Warngebiete nur als NUTS-Code (BE34, FR413 ...), ohne Geometrie. Damit Warnungen auf der Karte
           als Fläche erscheinen und der Radiusfilter greift, liegen die Grenzen der betroffenen Gebiete im Repository.
Quelle:    Eurostat GISCO, NUTS 2021, 1:3 Mio (EPSG:4326). Nachweis: "© EuroGeographics bezüglich der Verwaltungsgrenzen"
           (Hinweis des Anbieters; Bedingungen vor Veröffentlichung gegenlesen, siehe lizenz_hinweis in sources.yaml).
Aufruf:    python tools/build_nuts.py --lvl2 NUTS_RG_03M_2021_4326_LEVL_2.geojson --lvl3 NUTS_RG_03M_2021_4326_LEVL_3.geojson
Ergebnis:  {"BE34": {"name": ..., "geometry": {...}}}: Belgien und Luxemburg auf Ebene 2, Frankreich auf Ebene 3,
           nur Gebiete, die den Radius berühren. Vereinfacht auf rund 300 m, das genügt für Warnflächen.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import geo  # noqa: E402

TOL = 0.003   # Grad, rund 300 m
MIN_RING = 6  # Ringe mit weniger Punkten nach der Vereinfachung fallen weg (Mini-Inseln)


def _dp(pts: list[list[float]], tol: float) -> list[list[float]]:
    """Douglas-Peucker, iterativ (kein Rekursionslimit)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = math.hypot(x - x1, y - y1) if norm == 0 else abs(dy * (x - x1) - dx * (y - y1)) / norm
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def simplify(geom: dict) -> dict | None:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    out = []
    for poly in polys:
        rings = []
        for ring in poly:
            r = [[round(x, 3), round(y, 3)] for x, y in _dp(ring, TOL)]
            if len(r) >= MIN_RING:
                rings.append(r)
        if rings:
            out.append(rings)
    if not out:
        return None
    return {"type": "Polygon", "coordinates": out[0]} if len(out) == 1 else {"type": "MultiPolygon", "coordinates": out}


def select(path: Path, prefixes: tuple[str, ...]) -> dict:
    res = {}
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        code = f["properties"]["NUTS_ID"]
        if not code.startswith(prefixes):
            continue
        g = simplify(f["geometry"])
        if g and geo.geometry_in_region(g):
            res[code] = {"name": f["properties"].get("NAME_LATN") or f["properties"].get("NUTS_NAME"), "geometry": g}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lvl2", type=Path, required=True)
    ap.add_argument("--lvl3", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "app" / "data" / "nuts_meteoalarm.json")
    a = ap.parse_args()
    res = {**select(a.lvl2, ("BE", "LU")), **select(a.lvl3, ("FR",))}
    a.out.write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(res)} Gebiete: {', '.join(sorted(res))}; {a.out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
