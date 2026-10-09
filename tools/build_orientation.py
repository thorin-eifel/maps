#!/usr/bin/env python3
"""Baut die statische Orientierungsebene der Karte (Kreisgrenzen im Radius).

Zweck:      Bis eigene Tiles vorliegen (Phase 2), bekommt die Karte Kreisgrenzen als Anhalt.
Quelle:     DWD-WFS, Layer dwd:Warngebiete_Kreise (GeoNutzV, „Quelle: Deutscher Wetterdienst“).
Parameter:  --out PFAD     Zieldatei (Standard web/geo/kreise.geojson)
            --tolerance    Vereinfachungstoleranz in Grad (Standard 0.0008, ca. 90 m)
Beispiel:   python tools/build_orientation.py
Hinweis:    Luxemburg und Belgien fehlen, weil der DWD dort keine Warngebiete führt.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

URL = "https://maps.dwd.de/geoserver/dwd/ows"
log = logging.getLogger("build_orientation")


def _perp(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def simplify(points: list[list[float]], tol: float) -> list[list[float]]:
    """Douglas-Peucker, iterativ (kein Rekursionslimit bei langen Ringen)."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        dmax, idx = 0.0, -1
        for k in range(i + 1, j):
            d = _perp(points[k], points[i], points[j])
            if d > dmax:
                dmax, idx = d, k
        if idx != -1 and dmax > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(points, keep) if k]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "web" / "geo" / "kreise.geojson"))
    ap.add_argument("--tolerance", type=float, default=0.0008)
    args = ap.parse_args()
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")

    lat_min, lon_min, lat_max, lon_max = config.BBOX
    resp = httpx.get(URL, timeout=60, headers={"User-Agent": f"OSINT-by-CTW/1.0 (+{config.CONTACT}) orientation build"}, params={
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeName": "dwd:Warngebiete_Kreise",
        "outputFormat": "application/json", "srsName": "EPSG:4326",
        "bbox": f"{lon_min},{lat_min},{lon_max},{lat_max},EPSG:4326",
    })
    resp.raise_for_status()
    feats = []
    for f in resp.json()["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out = []
        for poly in polys:
            rings = [[[round(x, 4), round(y, 4)] for x, y in simplify(ring, args.tolerance)] for ring in poly]
            out.append(rings)
        p = f["properties"]
        feats.append({"type": "Feature", "properties": {"name": p.get("NAME") or p.get("KURZNAME")},
                      "geometry": {"type": "MultiPolygon", "coordinates": out}})
    doc = {"type": "FeatureCollection",
           "_quelle": "Quelle: Deutscher Wetterdienst (dwd:Warngebiete_Kreise), vereinfacht",
           "features": feats}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("%d Kreise, %d Bytes → %s", len(feats), Path(args.out).stat().st_size, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
