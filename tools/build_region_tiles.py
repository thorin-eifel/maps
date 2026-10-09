#!/usr/bin/env python3
"""Baut die Basiskarte für die Landesfläche aus dem Protomaps-Build: Region (Zoom 0-13), Ring (Zoom 14), Kerne (Zoom 14-15).

Zweck:      Ersetzt tools/build_tiles.sh für Polygon-Regionen. Der Bau läuft in kleinen Stücken (Zellen), jedes Stück ist
            eine eigene Datei. Bricht der Server ab oder läuft die Zeit aus, bleibt alles Fertige liegen und der nächste Lauf
            macht dort weiter. Am Ende werden die Stücke zu einer Datei vereint (doppelte Kacheln fallen weg).
Quelle:     https://build.protomaps.com/<JJJJMMTT>.pmtiles (OSM, ODbL), Auswahl per `pmtiles extract`.
Aufruf:     python tools/build_region_tiles.py --pmtiles ./bin/pmtiles --stage region --budget-s 150
            python tools/build_region_tiles.py --dry-run                   # zeigt Zellen und Zahlen, ohne Netz
            Exit 0: Stufe vollständig und vereint. Exit 2: noch nicht fertig, Befehl wiederholen.
Parameter:  --stage region|ring|cores|all   --jobs 3 (parallele Abrufe)   --budget-s (keine neuen Abrufe nach dieser Zeit)
            --build JJJJMMTT (Standard: neuester)   --work build/tiles   --out web/tiles   --region region-rlp.yaml
Hinweis:    Der Server bricht bei vielen parallelen Strömen gern ab; darum wenige Threads je Abruf und Wiederholung mit
            Wartezeit. Das Ergebnis liegt zuerst in --work und wird erst nach der Prüfung nach --out gelegt.
Abhängig:   pip install -r requirements-tools.txt (shapely, pmtiles); pmtiles-CLI für die Plattform (go-pmtiles).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import heapq
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import yaml
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("build_region_tiles")

CELL_LON, CELL_LAT = 0.5, 0.34      # Zellgröße in Grad (rund 36 x 38 km)
REGION_MAXZOOM = 13
RING_ZOOM = 14
CORE_ZOOMS = (14, 15)
MARGIN_DEG = 0.02                   # Rand um die Fläche, damit Randkacheln nicht fehlen


# ------------------------------------------------------------------ Geometrie
def load_polygon(region_yaml: Path) -> Any:
    cfg = yaml.safe_load(region_yaml.read_text(encoding="utf-8"))
    if cfg.get("mode") != "polygon":
        raise SystemExit(f"{region_yaml.name}: nur mode: polygon")
    data = json.loads((ROOT / cfg["polygon_file"]).read_text(encoding="utf-8"))
    polys = [Polygon(rings[0], rings[1:]) for rings in data["polygons"]]
    return unary_union(polys).buffer(MARGIN_DEG)


def core_geometries(cores_yaml: Path) -> list[tuple[str, Any]]:
    out = []
    for k in yaml.safe_load(cores_yaml.read_text(encoding="utf-8"))["kerne"]:
        if "bbox" in k:
            out.append((k["name"], box(*k["bbox"])))
        else:
            c = k["kreis"]
            # Kreis als Ellipse in Grad (Breitenkreis-Korrektur), 64 Ecken
            dlat, dlon = c["km"] / 110.57, c["km"] / (111.32 * math.cos(math.radians(c["lat"])))
            pts = [(c["lon"] + dlon * math.sin(a), c["lat"] + dlat * math.cos(a)) for a in (2 * math.pi * i / 64 for i in range(64))]
            out.append((k["name"], Polygon(pts)))
    return out


def plan_cells(geom: Any, cell_lon: float = CELL_LON, cell_lat: float = CELL_LAT) -> list[tuple[str, Any]]:
    """Zellen (id, Ausschnitt der Fläche), die die Fläche vollständig und ohne Lücke abdecken."""
    minx, miny, maxx, maxy = geom.bounds
    cells = []
    i0, j0 = math.floor(minx / cell_lon), math.floor(miny / cell_lat)
    for j in range(j0, math.ceil(maxy / cell_lat)):
        for i in range(i0, math.ceil(maxx / cell_lon)):
            part = geom.intersection(box(i * cell_lon, j * cell_lat, (i + 1) * cell_lon, (j + 1) * cell_lat))
            if not part.is_empty and part.area > 1e-6:
                cells.append((f"x{i}_y{j}", part))
    return cells


def stage_plan(stage: str, region: Any, cores: list[tuple[str, Any]]) -> list[tuple[str, Any, tuple[int, int]]]:
    """(Stück-ID, Fläche, (minzoom, maxzoom)) je Stufe."""
    core_union = unary_union([g for _, g in cores])
    if stage == "region":
        return [(cid, g, (0, REGION_MAXZOOM)) for cid, g in plan_cells(region)]
    if stage == "ring":
        ring = region.difference(core_union)
        return [(cid, g, (RING_ZOOM, RING_ZOOM)) for cid, g in plan_cells(ring)]
    if stage == "cores":
        return [(f"kern{n:02d}", g.intersection(region), CORE_ZOOMS) for n, (_, g) in enumerate(cores)]
    raise ValueError(stage)


def to_geojson(geom: Any) -> dict[str, Any]:
    g = geom if geom.geom_type in ("Polygon", "MultiPolygon") else MultiPolygon([p for p in getattr(geom, "geoms", []) if p.geom_type == "Polygon"])
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": mapping(g)}]}


# ------------------------------------------------------------------ Abruf
def latest_build() -> str:
    import urllib.request
    req = urllib.request.Request("https://build-metadata.protomaps.dev/builds.json",
                                 headers={"User-Agent": "WasIstLosBeiUns/1.0 (+thorin.eifel@icloud.com)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return sorted(x["key"] for x in json.load(r))[-1].split(".")[0]


def extract_piece(pmtiles: str, src: str, geom: Any, zooms: tuple[int, int], out: Path, threads: int, timeout: float) -> bool:
    """Ein Stück holen. Erfolg nur, wenn die Datei lesbar ist; sonst bleibt nichts zurück."""
    part = out.with_suffix(".part")
    gj = out.with_suffix(".geojson")
    gj.write_text(json.dumps(to_geojson(geom)), encoding="utf-8")
    part.unlink(missing_ok=True)
    cmd = [pmtiles, "extract", src, str(part), f"--region={gj}", f"--minzoom={zooms[0]}", f"--maxzoom={zooms[1]}", f"--download-threads={threads}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0 and subprocess.run([pmtiles, "show", str(part)], capture_output=True, timeout=60).returncode == 0
        if not ok:
            log.warning("%s: %s", out.name, (r.stderr or r.stdout).strip().splitlines()[-1:] or "Fehler")
    except subprocess.TimeoutExpired:
        ok = False
        log.warning("%s: Zeitbudget überschritten, Stück verworfen", out.name)
    gj.unlink(missing_ok=True)
    if ok:
        os.replace(part, out)
    else:
        part.unlink(missing_ok=True)
    return ok


def run_stage(stage: str, pieces: list, pmtiles: str, src: str, work: Path, jobs: int, budget_s: float, threads: int, attempts: int = 3) -> tuple[int, int]:
    chunks = work / "chunks" / stage
    chunks.mkdir(parents=True, exist_ok=True)
    todo = [(cid, g, z) for cid, g, z in pieces if not (chunks / f"{cid}.pmtiles").exists()]
    log.info("Stufe %s: %d Stücke, %d fertig, %d offen", stage, len(pieces), len(pieces) - len(todo), len(todo))
    t0 = time.monotonic()

    def one(item):
        cid, g, z = item
        for a in range(attempts):
            left = budget_s - (time.monotonic() - t0)
            if left < 20:
                return cid, False
            if extract_piece(pmtiles, src, g, z, chunks / f"{cid}.pmtiles", threads, left - 5):
                return cid, True
            time.sleep(min(5 * (a + 1), max(0, left - 25)))
        return cid, False

    done = 0
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = []
        for item in todo:
            futs.append(ex.submit(one, item))
        for f in cf.as_completed(futs):
            cid, ok = f.result()
            done += ok
            log.info("%s %s (%d/%d)", cid, "ok" if ok else "offen", done, len(todo))
    return len(todo) - done, len(pieces)


# ------------------------------------------------------------------ Vereinen
def _tiles(path: Path) -> Iterator[tuple[int, bytes]]:
    """Kacheln einer Datei in aufsteigender Kachelnummer (Hilbert-Reihenfolge, wie im Verzeichnis gespeichert)."""
    from pmtiles.reader import MmapSource, all_tiles
    from pmtiles.tile import zxy_to_tileid
    with open(path, "rb") as fh:
        get_bytes = MmapSource(fh)
        for (z, x, y), data in all_tiles(get_bytes):
            yield zxy_to_tileid(z, x, y), data


def merge(chunk_files: list[Path], out: Path) -> dict[str, Any]:
    """Vereint Stücke zu einer Datei. Gleiche Kacheln aus überlappenden Stücken stammen aus demselben Build und
    sind gleich; sie werden einmal geschrieben. Kopf und Metadaten kommen vom ersten Stück, Zoomstufen,
    Ausdehnung und Zähler werden neu berechnet. Rückgabe: Kennzahlen."""
    from pmtiles.reader import MmapSource, Reader
    from pmtiles.writer import Writer
    if not chunk_files:
        raise ValueError("keine Stücke")
    with open(chunk_files[0], "rb") as fh:
        rd = Reader(MmapSource(fh))
        header, meta = rd.header(), rd.metadata()
    lon0 = lat0 = 1e9
    lon1 = lat1 = -1e9
    for f in chunk_files:
        with open(f, "rb") as fh:
            h = Reader(MmapSource(fh)).header()
        lon0, lat0 = min(lon0, h["min_lon_e7"]), min(lat0, h["min_lat_e7"])
        lon1, lat1 = max(lon1, h["max_lon_e7"]), max(lat1, h["max_lat_e7"])
    header.update(min_lon_e7=int(lon0), min_lat_e7=int(lat0), max_lon_e7=int(lon1), max_lat_e7=int(lat1),
                  center_lon_e7=int((lon0 + lon1) / 2), center_lat_e7=int((lat0 + lat1) / 2))
    n_in = n_out = 0
    last = -1
    tmp = out.with_suffix(".merge.tmp")
    with open(tmp, "wb") as fh:
        w = Writer(fh)
        for tid, data in heapq.merge(*(_tiles(f) for f in chunk_files), key=lambda t: t[0]):
            n_in += 1
            if tid == last:
                continue
            last = tid
            w.write_tile(tid, data)
            n_out += 1
        w.finalize(header, meta)
    os.replace(tmp, out)
    return {"stuecke": len(chunk_files), "kacheln_gelesen": n_in, "kacheln": n_out, "bytes": out.stat().st_size}


def verify(pmtiles: str, path: Path) -> bool:
    r = subprocess.run([pmtiles, "verify", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        log.error("verify %s: %s", path.name, (r.stderr or r.stdout).strip()[-300:])
    return r.returncode == 0


# ------------------------------------------------------------------ Lauf
FINAL = {"region": "region.pmtiles", "ring": "ring.pmtiles", "cores": "core.pmtiles"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", default="all", choices=["region", "ring", "cores", "all"])
    ap.add_argument("--region", type=Path, default=ROOT / "region-rlp.yaml")
    ap.add_argument("--cores", type=Path, default=ROOT / "tools" / "tile_cores.yaml")
    ap.add_argument("--pmtiles", default=os.environ.get("PMTILES") or shutil.which("pmtiles") or str(ROOT / "tools" / "bin" / "pmtiles"))
    ap.add_argument("--build", help="Build-Datum JJJJMMTT, Standard: neuester")
    ap.add_argument("--work", type=Path, default=ROOT / "build" / "tiles")
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "tiles" / "final", help="Zielordner der fertigen Dateien")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--threads", type=int, default=2, help="Threads je Abruf")
    ap.add_argument("--budget-s", type=float, default=150.0, help="nach dieser Zeit keine neuen Abrufe mehr")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")

    region = load_polygon(args.region)
    cores = core_geometries(args.cores)
    stages = ["region", "ring", "cores"] if args.stage == "all" else [args.stage]
    if args.dry_run:
        for st in stages:
            pcs = stage_plan(st, region, cores)
            log.info("Stufe %s: %d Stücke, Zoom %s, Fläche %.0f Grad² (grob)", st, len(pcs), sorted({z for _, _, z in pcs}), sum(g.area for _, g, _ in pcs))
        return 0
    build = args.build or latest_build()
    src = f"https://build.protomaps.com/{build}.pmtiles"
    (args.work).mkdir(parents=True, exist_ok=True)
    marker = args.work / "BUILD"
    if marker.exists() and marker.read_text().strip() != build:
        raise SystemExit("Build-Datum weicht vom angefangenen Lauf ab; --work leeren oder --build setzen")
    marker.write_text(build + "\n")
    unfinished = 0
    for st in stages:
        target = args.out / FINAL[st]
        if target.exists():
            log.info("Stufe %s: schon fertig (%s)", st, target.name)
            continue
        pcs = stage_plan(st, region, cores)
        open_, total = run_stage(st, pcs, args.pmtiles, src, args.work, args.jobs, args.budget_s, args.threads)
        if open_:
            unfinished += open_
            continue
        files = sorted((args.work / "chunks" / st).glob("*.pmtiles"))
        args.out.mkdir(parents=True, exist_ok=True)
        tmp = args.out / (FINAL[st] + ".tmp")
        stats = merge(files, tmp)
        if not verify(args.pmtiles, tmp):
            tmp.unlink(missing_ok=True)
            return 1
        os.replace(tmp, target)
        log.info("Stufe %s fertig: %s", st, json.dumps(stats))
    if unfinished:
        log.info("Noch offen: %d Stücke. Befehl wiederholen.", unfinished)
        return 2
    (args.out / "README.txt").write_text(
        f"Protomaps-Build {build}, Fläche aus {args.region.name}. region.pmtiles: Zoom 0-{REGION_MAXZOOM}; ring.pmtiles: Zoom {RING_ZOOM} außerhalb der Kerne; "
        f"core.pmtiles: Zoom {CORE_ZOOMS[0]}-{CORE_ZOOMS[1]} in den Kernen (tools/tile_cores.yaml).\n"
        "Daten: © OpenStreetMap-Mitwirkende (ODbL 1.0), Natural Earth (gemeinfrei); Kachelbau: Protomaps (Schema-Version 4).\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
