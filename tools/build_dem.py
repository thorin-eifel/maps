#!/usr/bin/env python3
"""Höhenmodell-Kacheln für das Relief holen (Terrarium-Kodierung) und lokal ablegen.

Zweck:      Lädt die Terrarium-Höhenkacheln (Mapzen Terrain Tiles auf AWS Open Data) für die Region (region.yaml, bei OSINT_REGION=region-rlp.yaml Rheinland-Pfalz plus 80 km)
            einmalig nach web/tiles/dem/{z}/{x}/{y}.png. Die Karte zeigt daraus Schummerung, Höhenfärbung
            und Höhenlinien; beim Betrachten wird kein Drittserver angefragt.
Quelle:     https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png
            Datenbasis laut Mapzen/Nextzen-Dokumentation für Europa: SRTM (30 m), EU-DEM und weitere.
Namensnennung: "Produced using Copernicus data and information funded by the European Union - EU-DEM layers." (quellen.html)
Aufruf:     python tools/build_dem.py                 fehlende Kacheln holen (Zoom 6 bis 12)
            python tools/build_dem.py --max-zoom 11   gröber, deutlich kleiner
            python tools/build_dem.py --check         nur zählen und Größe schätzen, nichts laden
Höflichkeit: 4 gleichzeitige Abrufe, ehrlicher User-Agent, vorhandene Dateien werden übersprungen.
Exit:       0 = alles da, 1 = Kacheln fehlen
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402  (Gebiet aus region.yaml bzw. OSINT_REGION)

_S, _W, _N, _E = config.BBOX
# Gebiet der Region plus Rand, deckt maxBounds der Karte ab
BBOX = {"lat_min": _S - 0.3, "lat_max": _N + 0.3, "lon_min": _W - 0.4, "lon_max": _E + 0.4}
# Grobe Zoomstufen bis 9 großzügiger, damit am Kartenrand bei kleinem Maßstab keine Lücken entstehen
BBOX_WIDE = {"lat_min": _S - 1.0, "lat_max": _N + 1.0, "lon_min": _W - 1.5, "lon_max": _E + 1.5}
WIDE_MAX_ZOOM = 9
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
UA = "WasIstLosBeiUns/1.0 (DEM tiles, one-off fetch)"
DEST = Path(__file__).resolve().parent.parent / "web" / "tiles" / "dem"


def tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def tiles(min_zoom: int, max_zoom: int):
    for z in range(min_zoom, max_zoom + 1):
        box = BBOX_WIDE if z <= WIDE_MAX_ZOOM else BBOX
        x0, y1 = tile(box["lat_min"], box["lon_min"], z)
        x1, y0 = tile(box["lat_max"], box["lon_max"], z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def fetch(client: httpx.Client, z: int, x: int, y: int, dest: Path = DEST) -> bool:
    target = dest / str(z) / str(x) / f"{y}.png"
    if target.exists() and target.stat().st_size > 100:
        return True
    for attempt in range(3):
        try:
            r = client.get(URL.format(z=z, x=x, y=y))
            if r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n":
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(".tmp")
                tmp.write_bytes(r.content)
                tmp.replace(target)
                return True
        except httpx.HTTPError:
            pass
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-zoom", type=int, default=6)
    ap.add_argument("--max-zoom", type=int, default=12)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dest", type=Path, default=DEST, help="Zielordner (Standard web/tiles/dem)")
    ap.add_argument("--budget-s", type=float, default=0, help="nach dieser Zeit aufhören (Exit 2 = Befehl wiederholen), 0 = unbegrenzt")
    args = ap.parse_args()
    dest = args.dest
    todo = [t for t in tiles(args.min_zoom, args.max_zoom) if not (dest / str(t[0]) / str(t[1]) / f"{t[2]}.png").exists()] if args.budget_s else list(tiles(args.min_zoom, args.max_zoom))
    print(f"{len(todo)} Kacheln (Zoom {args.min_zoom} bis {args.max_zoom})")
    if args.check:
        return 0
    missing = 0
    start = time.monotonic()
    if args.budget_s:
        todo = todo[: int(args.budget_s * 25)]   # grob 25 Kacheln/s; der Rest folgt im nächsten Lauf
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=False) as client, ThreadPoolExecutor(4) as pool:
        for i, ok in enumerate(pool.map(lambda t: fetch(client, *t, dest=dest), todo), 1):
            missing += not ok
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    size = sum(p.stat().st_size for p in dest.rglob("*.png")) / 1e6
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "README.txt").write_text(
        "Höhenkacheln (Terrarium-Kodierung), Quelle: Mapzen Terrain Tiles auf AWS Open Data\n"
        "https://registry.opendata.aws/terrain-tiles/  ·  Datenbasis u. a. SRTM, EU-DEM\n"
        f"Erzeugt mit tools/build_dem.py, Zoom {args.min_zoom} bis {args.max_zoom}, {size:.0f} MB.\n", encoding="utf-8")
    print(f"fertig: {size:.0f} MB, fehlend: {missing}")
    if args.budget_s and any(not (dest / str(z) / str(x) / f"{y}.png").exists() for z, x, y in tiles(args.min_zoom, args.max_zoom)):
        return 2
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
