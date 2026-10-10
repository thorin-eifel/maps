#!/usr/bin/env python3
"""Landesgrenze von Rheinland-Pfalz als GeoJSON bauen (web/geo/rlp.geojson).

Zweck:      Die Karte zeichnet die RLP-Grenze rot mit grauem Verlauf nach außen. Die Vektorkacheln tragen keine Eigenschaft, die ein Land
            vom anderen trennt, deshalb kommt die Linie aus der amtlichen Ländergrenze (BKG VG250, Ebene VG250_LAN, GF = 4).
Verfahren:  Fläche des Landes in UTM32 auf --simplify-m (Standard 20 m) vereinfachen, nach WGS84 umrechnen. Nur der Außenring, Innenringe
            entfallen. Ring gegen den Uhrzeigersinn (RFC 7946); in MapLibre liegt die Außenseite dann bei negativem
            `line-offset` (an der Karte geprüft, siehe stil.js). Abweichung zur OSM-Linie der Kacheln: Zehnermeter, bei Zoom 13 ein paar Pixel.
Quelle:     © GeoBasis-DE / BKG (dl-de/by-2.0), Namensnennung steht in quellen.html. Rohdaten: vg250_01-01.utm32s.shape.ebenen.zip
Aufruf:     python tools/build_landesgrenze.py --zip PFAD/vg250_01-01.utm32s.shape.ebenen.zip
            python tools/build_landesgrenze.py --zip ... --land 07 --simplify-m 20 --out web/geo/rlp.geojson
Exit:       0 = geschrieben, 1 = Land nicht gefunden
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import shapefile  # noqa: E402  (pyshp)
from shapely.geometry import MultiPolygon, Polygon, shape  # noqa: E402
from shapely.geometry.polygon import orient  # noqa: E402

from app import geo  # noqa: E402

log = logging.getLogger("landesgrenze")
ATTRIBUTION = ("Verwaltungsgrenzen: © BKG ({year}) dl-de/by-2-0, "
               "Datenquellen: https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf")


def outline(zip_path: Path, land: str, simplify_m: float) -> tuple[list[Polygon], str]:
    """Außenringe des Landes in WGS84 (lon, lat), gegen den Uhrzeigersinn; dazu das Stand-Datum der Daten."""
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zip_path) as z:
        stand = z.read("dokumentation/aktualitaet.txt").decode().strip()
        for ext in ("shp", "shx", "dbf", "cpg"):
            z.extract(f"vg250_ebenen_0101/VG250_LAN.{ext}", tmp)
        rd = shapefile.Reader(str(Path(tmp) / "vg250_ebenen_0101" / "VG250_LAN"), encoding="utf-8")
        found = [shape(sr.shape.__geo_interface__) for sr in rd.shapeRecords() if sr.record["SN_L"] == land and sr.record["GF"] == 4]
    if len(found) != 1:
        raise SystemExit(f"Land {land}: {len(found)} Flächen mit GF=4 gefunden, erwartet 1")
    g = found[0].simplify(simplify_m)
    polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
    out = []
    for p in polys:
        pts = []
        for x, y in list(p.exterior.coords)[:-1]:
            lat, lon = geo.utm32_to_wgs84(x, y)
            pts.append((round(lon, 5), round(lat, 5)))
        out.append(orient(Polygon(pts), sign=1.0))
    return [p for p in out if p.area > 1e-6], stand


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", type=Path, required=True, help="VG250-Archiv des BKG (utm32s, shape, ebenen)")
    ap.add_argument("--land", default="07", help="Schlüssel SN_L (07 = Rheinland-Pfalz)")
    ap.add_argument("--simplify-m", type=float, default=20.0)
    ap.add_argument("--out", type=Path, default=ROOT / "web/geo/rlp.geojson")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    polys, stand = outline(args.zip, args.land, args.simplify_m)
    mp = MultiPolygon(polys)
    fc = {"type": "FeatureCollection", "attribution": ATTRIBUTION.format(year=stand[-4:]), "licence": "dl-de/by-2-0", "stand": stand,
          "features": [{"type": "Feature", "properties": {"sn_l": args.land},
                        "geometry": {"type": "MultiPolygon", "coordinates": [[[list(c) for c in p.exterior.coords]] for p in polys]}}]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("%s: %d Polygone, %d Punkte, %.0f KB, Fläche %.0f km² (Grad²-Näherung)", args.out, len(mp.geoms),
             sum(len(p.exterior.coords) for p in mp.geoms), args.out.stat().st_size / 1e3, mp.area * 111 * 71)
    return 0


if __name__ == "__main__":
    sys.exit(main())
