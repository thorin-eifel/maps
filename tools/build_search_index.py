#!/usr/bin/env python3
"""Statischer Teil des Suchindex aus den Kartenkacheln bauen (web/data/suche_geo.json).

Zweck:     Die Suchleiste der Karte findet Orte, Straßen, Gewässer und benanntes Gelände ohne externen Geocoder. Die Namen stehen
           ohnehin in unseren eigenen Kacheln (Protomaps-Basiskarte aus OpenStreetMap); dieses Werkzeug liest sie einmal aus.
Quelle:    web/tiles/region.pmtiles (Zoom 13, alle Kacheln im Radius), web/tiles/core.pmtiles (nur Ebene roads, Zoom 15, Kern um Irrel),
           Orte aus app/data/orte.json
Lizenz:    ODbL 1.0, © OpenStreetMap-Mitwirkende (steht auch auf der Seite Quellen und Lizenzen)
Aufruf:    python tools/build_search_index.py                  # liest die Kacheln (einige Minuten) und schreibt web/data/suche_geo.json
           python tools/build_search_index.py --stats          # nur zählen, was an benannten Objekten in den Kacheln steht
           python tools/build_search_index.py --raw data/search_raw.json.gz   # Zwischenstand lesen/schreiben (spart den Kachellauf)
Ergebnis:  Straßen je (Name, nächster Ort; im Kern alle benannten, außerhalb nur Haupt- und Landstraßen), Gewässer je zusammenhängendem Lauf, Orte aus orte.json, benanntes Gelände.
Datenschutz: Keine Hausnummern, keine Adressen (die Ebene buildings aus core.pmtiles wird nicht gelesen), keine Personen. Straßennamen
           sind Namen öffentlicher Orte; Straßen ohne Namen fehlen. Pfade und Wege fehlen (Wanderwege kommen aus den Routen).
Fallstricke: Nach neuem Kachelbau (tools/build_tiles.sh) neu laufen lassen. Laufzeit ca. 3 bis 8 Minuten.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from app import config, geo, search  # noqa: E402
from pmtiles_read import PMTiles, tile_id, tile_xyz  # noqa: E402

log = logging.getLogger("suche")
ZOOM = 13
SKIP_LAYERS = {"places", "buildings", "boundaries", "landuse", "earth", "transit", "physical_line", "physical_point"}
ROAD_KINDS = {"highway", "major_road", "medium_road", "minor_road", "other"}
WATER_CLASS = {"river": ("Fluss", 25.0), "canal": ("Fluss", 10.0), "stream": ("Bach", 4.0), "lake": ("See", 3.0), "reservoir": ("See", 3.0), "water": ("See", 3.0), "basin": ("See", 3.0)}
CORE_BBOX = (49.49, 5.90, 50.21, 7.02)      # lat_min, lon_min, lat_max, lon_max wie in tools/build_tiles.sh; dort liegen die Kacheln bis Zoom 15 mit Nebenstraßen
# benannte Punkte der Ebene pois -> Typ (Auswahl: öffentliche Orte und Landschaft, keine Betriebe, keine Höfe, keine Vereine)
POI_TYPE = {"peak": "Gipfel", "volcano": "Vulkan", "forest": "Wald", "wood": "Wald", "nature_reserve": "Naturschutzgebiet", "protected_area": "Naturschutzgebiet",
            "national_park": "Naturschutzgebiet", "park": "Park", "garden": "Park", "attraction": "Sehenswürdigkeit", "castle": "Burg", "fort": "Burg",
            "ruins": "Ruine", "archaeological_site": "Ausgrabung", "monastery": "Kloster", "museum": "Museum", "zoo": "Freizeit", "theme_park": "Freizeit",
            "golf_course": "Freizeit", "stadium": "Freizeit", "camp_site": "Campingplatz", "aerodrome": "Flugplatz", "quarry": "Steinbruch", "administrative": "Gemeinde"}


def _tile_range(bbox: tuple[float, float, float, float], z: int) -> tuple[range, range]:
    lat_min, lon_min, lat_max, lon_max = bbox
    n = 1 << z

    def tx(lon: float) -> int:
        return int((lon + 180.0) / 360.0 * n)

    def ty(lat: float) -> int:
        return int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)

    return range(tx(lon_min), tx(lon_max) + 1), range(ty(lat_max), ty(lat_min) + 1)


def _lonlat(z: int, x: int, y: int, px: float, py: float, extent: int) -> tuple[float, float]:
    """Kachelpunkt (px, py von oben links) in (lat, lon)."""
    n = 1 << z
    gx, gy = (x + px / extent) / n, (y + py / extent) / n
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy)))), gx * 360.0 - 180.0


def _rep_point(geom: dict) -> tuple[float, float] | None:
    """Ein Punkt (px, py) auf oder in der Geometrie: Punkt selbst, Mitte der längsten Linie, Mitte der Hülle der Fläche."""
    t, c = geom.get("type"), geom.get("coordinates")
    if not c:
        return None
    if t == "Point":
        return float(c[0]), float(c[1])
    if t == "MultiPoint":
        return float(c[0][0]), float(c[0][1])
    if t == "LineString":
        return float(c[len(c) // 2][0]), float(c[len(c) // 2][1])
    if t == "MultiLineString":
        ln = max(c, key=len)
        return float(ln[len(ln) // 2][0]), float(ln[len(ln) // 2][1])
    ring = c[0] if t == "Polygon" else c[0][0] if t == "MultiPolygon" else None
    if not ring:
        return None
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def scan(pm: PMTiles, zoom: int, bbox: tuple[float, float, float, float], only: set[str] | None = None, flip: bool | None = None) -> tuple[list[dict], bool]:
    """Alle benannten Objekte aus Kacheln eines Zooms im Kasten: Ebene, Art, Name, Kennzeichen, Punkt. Gibt auch die geprüfte y-Ausrichtung zurück."""
    import mapbox_vector_tile as mvt

    xr, yr = _tile_range(bbox, zoom)
    wanted = {tile_id(zoom, x, y): (x, y) for x in xr for y in yr}
    todo = [(tid, off, ln) for tid, off, ln, run in pm.entries() if run == 1 and tid in wanted]
    log.info("%d Kacheln bei Zoom %d im Kasten", len(todo), zoom)
    out: list[dict] = []
    t0 = time.time()
    for n, (tid, off, ln) in enumerate(todo, 1):
        z, x, y = tile_xyz(tid)
        tile = mvt.decode(pm.tile(off, ln))
        if flip is None:        # Ausrichtung der y-Achse einmalig am Ortsnamen prüfen (Bibliotheksversionen unterscheiden sich)
            probe = next((f for f in tile.get("places", {}).get("features", []) if f["properties"].get("name")), None)
            if probe:
                px, py = probe["geometry"]["coordinates"][:2]
                ext = tile["places"].get("extent", 4096)
                a, b = _lonlat(z, x, y, px, py, ext), _lonlat(z, x, y, px, ext - py, ext)
                names = [p for p in search.load_places() if p["n"] == probe["properties"]["name"]]
                da = min((geo.haversine_km(a[0], a[1], p["lat"], p["lon"]) for p in names), default=99)
                db = min((geo.haversine_km(b[0], b[1], p["lat"], p["lon"]) for p in names), default=99)
                if min(da, db) < 3.0:
                    flip = db < da
                    log.info("y-Achse: %s (Abweichung %.2f km)", "gespiegelt" if flip else "von oben", min(da, db))
        for lname, layer in tile.items():
            if lname in SKIP_LAYERS or (only and lname not in only):
                continue
            ext = layer.get("extent", 4096)
            for f in layer["features"]:
                p = f["properties"]
                name = search.clean_name(p.get("name"))
                ref = search.clean_name(p.get("ref"), 20)
                if not name and not (lname == "roads" and ref):
                    continue
                pt = _rep_point(f["geometry"])
                if not pt:
                    continue
                lat, lon = _lonlat(z, x, y, pt[0], (ext - pt[1]) if flip else pt[1], ext)
                out.append({"l": lname, "k": p.get("kind") or "", "d": p.get("kind_detail") or "", "n": name, "r": ref, "lat": round(lat, 5), "lon": round(lon, 5)})
        if n % 500 == 0:
            log.info("%d/%d Kacheln, %d Objekte, %.0f s", n, len(todo), len(out), time.time() - t0)
    if flip is None:
        raise SystemExit("y-Achse nicht prüfbar (kein Ort mit Namen in einer Kachel gefunden)")
    return out, flip


def assemble(raw: list[dict]) -> dict:
    places = search.load_places()
    px = search.PlaceIndex(places)
    b = search.Builder(px)
    known: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for p in places:      # Orte: aus dem Ortsverzeichnis
        b.add(p["n"], search.RANK_TYPE[p["k"]], p["lat"], p["lon"])
        known[search.fold(p["n"])].append((p["lat"], p["lon"]))

    streets: dict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    waters: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for o in raw:
        lat, lon = o["lat"], o["lon"]
        if geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
            continue
        if o["l"] == "roads":
            if o["k"] not in ROAD_KINDS:
                continue
            ort = px.nearest(lat, lon)
            if o["n"]:
                streets[(o["n"], ort, "n")].append((lat, lon))
            if o["r"] and o["k"] in ("highway", "major_road"):         # A 64, B 51: auch über das Kennzeichen finden
                streets[(o["r"], ort, "r")].append((lat, lon))
        elif o["l"] == "water":
            cls = WATER_CLASS.get(o["k"])
            if cls and o["n"]:
                waters[(o["n"], o["k"])].append((lat, lon))
        elif o["l"] == "pois" and o["n"] and o["k"] in POI_TYPE:
            if o["k"] == "administrative" and any(abs(q[0] - lat) < 0.03 and abs(q[1] - lon) < 0.05 for q in known.get(search.fold(o["n"]), ())):
                continue            # Gemeindename, der schon als Ort im Verzeichnis steht
            b.add(o["n"], POI_TYPE[o["k"]], lat, lon)
    for (name, ort, _src), pts in streets.items():
        lat, lon = search.medoid(pts)
        b.add(name, "Straße", lat, lon, ort)
    for (name, kind), pts in waters.items():
        label, radius = WATER_CLASS[kind]
        for grp in search.cluster(pts, radius):
            lat, lon = search.medoid([pts[i] for i in grp])
            b.add(name, label, lat, lon)
    return b.payload(source="Protomaps-Basiskarte (OpenStreetMap, ODbL 1.0)")


def stats(raw: list[dict]) -> None:
    c = Counter((o["l"], o["k"], o["d"] if o["l"] == "roads" else "") for o in raw if o["n"])
    for (layer, kind, det), n in c.most_common(60):
        print(f"{n:8d}  {layer:10s} {kind:16s} {det}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiles", type=Path, default=ROOT / "web" / "tiles" / "region.pmtiles")
    ap.add_argument("--core", type=Path, default=ROOT / "web" / "tiles" / "core.pmtiles")
    ap.add_argument("--out", type=Path, default=ROOT / "web" / "data" / "suche_geo.json")
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "search_raw.json.gz", help="Zwischenstand (wird gelesen, wenn vorhanden)")
    ap.add_argument("--rescan", action="store_true", help="Kacheln neu lesen, auch wenn ein Zwischenstand vorliegt")
    ap.add_argument("--stats", action="store_true", help="nur Zählung ausgeben")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.raw.exists() and not a.rescan:
        raw = json.loads(gzip.decompress(a.raw.read_bytes()))
        log.info("Zwischenstand gelesen: %d Objekte", len(raw))
    else:
        pm = PMTiles(a.tiles)
        raw, flip = scan(pm, ZOOM, config.BBOX)
        pm.close()
        if a.core.exists():       # Kern: Nebenstraßen (Zoom 15); Hausnummern und Gebäude werden nicht gelesen
            pc = PMTiles(a.core)
            core, _ = scan(pc, pc.h.max_zoom, CORE_BBOX, only={"roads"}, flip=flip)
            pc.close()
            raw += core
        a.raw.parent.mkdir(parents=True, exist_ok=True)
        a.raw.write_bytes(gzip.compress(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")))
        log.info("Zwischenstand geschrieben: %s", a.raw)
    if a.stats:
        stats(raw)
        return 0
    payload = assemble(raw)
    payload["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(a.out)
    c = Counter(search.TYPES[e[1]] for e in payload["e"])
    log.info("%d Einträge nach %s: %s", len(payload["e"]), a.out, dict(c.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
