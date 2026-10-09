#!/usr/bin/env python3
"""Baut die Region (Landesgrenze plus Puffer) und die Kreisgliederung aus BKG VG250.

Zweck:      Erzeugt app/data/region/<name>.json (gepuffertes Polygon, lon/lat) und kreise.json (Kreise der
            Fläche mit Landkürzel) für app/region.py. Läuft einmal pro Jahresstand der Verwaltungsgrenzen,
            nicht im Betrieb.
Quelle:     BKG Verwaltungsgebiete 1:250 000 (VG250), vg250_01-01.utm32s.shape.ebenen.zip, Lizenz dl-de/by-2-0.
            Pflichtvermerk: "© BKG (Jahr) dl-de/by-2-0", Link auf bkg.bund.de und govdata.de/dl-de/by-2-0.
            https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_0101/aktuell/ (Prüfsumme dort als .md5)
Abhängig:   pip install -r requirements-tools.txt (shapely BSD-3, pyshp MIT)
Beispiel:   python tools/build_region.py --zip /pfad/vg250_01-01.utm32s.shape.ebenen.zip \
                --land 07 --buffer-km 80 --name rlp_plus80
Hinweis:    Der Puffer wird in UTM 32N (EPSG:25832) in Metern gerechnet. Die Maßstabsabweichung der Projektion
            liegt in der Region unter 0,04 Prozent, bei 80 km also unter 32 m. Das Ergebnis wird auf --simplify-m
            vereinfacht (Standard 150 m) und auf fünf Nachkommastellen gerundet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shapefile  # noqa: E402  (pyshp)
from shapely.geometry import shape  # noqa: E402

from app import geo  # noqa: E402

log = logging.getLogger("build_region")

LAND_ISO = {"01": "DE-SH", "02": "DE-HH", "03": "DE-NI", "04": "DE-HB", "05": "DE-NW", "06": "DE-HE", "07": "DE-RP",
            "08": "DE-BW", "09": "DE-BY", "10": "DE-SL", "11": "DE-BE", "12": "DE-BB", "13": "DE-MV", "14": "DE-SN",
            "15": "DE-ST", "16": "DE-TH"}
ATTRIBUTION = ("Verwaltungsgrenzen: © BKG ({year}) dl-de/by-2-0, "
               "Datenquellen: https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf")


def _lonlat(geom):
    """Shapely-Geometrie in UTM32 → Liste von Polygonen [[Ring, Loch, ...], ...] in [lon, lat], 5 Nachkommastellen."""
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    out = []
    for p in polys:
        rings = []
        for ring in [p.exterior, *p.interiors]:
            pts = []
            for x, y in list(ring.coords)[:-1]:
                lat, lon = geo.utm32_to_wgs84(x, y)
                pts.append([round(lon, 5), round(lat, 5)])
            rings.append(pts)
        out.append(rings)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", required=True, type=Path, help="vg250_01-01.utm32s.shape.ebenen.zip")
    ap.add_argument("--land", default="07", help="Schlüssel des Bundeslandes (SN_L), Standard 07 Rheinland-Pfalz")
    ap.add_argument("--buffer-km", type=float, default=80.0)
    ap.add_argument("--simplify-m", type=float, default=150.0)
    ap.add_argument("--name", default="rlp_plus80")
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent.parent / "app" / "data" / "region")
    args = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")

    sha = hashlib.sha256(args.zip.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(args.zip) as z:
        stand = z.read("dokumentation/aktualitaet.txt").decode().strip()
        for layer in ("VG250_LAN", "VG250_KRS"):
            for ext in ("shp", "shx", "dbf", "cpg"):
                z.extract(f"vg250_ebenen_0101/{layer}.{ext}", tmp)
        base = Path(tmp) / "vg250_ebenen_0101"
        land = [shape(sr.shape.__geo_interface__) for sr in shapefile.Reader(str(base / "VG250_LAN"), encoding="utf-8").shapeRecords()
                if sr.record["SN_L"] == args.land and sr.record["GF"] == 4]
        if len(land) != 1:
            log.error("Land %s: %d Flächen mit GF=4 gefunden, erwartet 1", args.land, len(land))
            return 1
        buffered = land[0].buffer(args.buffer_km * 1000, quad_segs=32).simplify(args.simplify_m)
        log.info("Land %s: %.0f km², gepuffert um %.0f km: %.0f km², %d Stützpunkte", args.land,
                 land[0].area / 1e6, args.buffer_km, buffered.area / 1e6,
                 sum(len(r) for p in _lonlat(buffered) for r in p))
        kreise = []
        for sr in shapefile.Reader(str(base / "VG250_KRS"), encoding="utf-8").shapeRecords():
            rec = sr.record
            if rec["GF"] != 4:
                continue
            g = shape(sr.shape.__geo_interface__)
            if not g.intersects(buffered):
                continue
            kreise.append({"ars": f"{rec['SN_L']}{rec['SN_R']}{rec['SN_K']}", "name": f"{rec['BEZ']} {rec['GEN']}".strip()
                           if rec["BEZ"] in ("Kreisfreie Stadt", "Stadtkreis") else rec["GEN"],
                           "land": LAND_ISO.get(rec["SN_L"], "DE"), "polygons": _lonlat(g.simplify(args.simplify_m))})
        kreise.sort(key=lambda k: k["ars"])
    year = stand[-4:]
    att = ATTRIBUTION.format(year=year)
    meta = {"source": "BKG VG250 (vg250_01-01.utm32s.shape.ebenen.zip)", "stand": stand, "sha256_input": sha,
            "licence": "dl-de/by-2-0", "attribution": att, "land": args.land, "buffer_km": args.buffer_km,
            "simplify_m": args.simplify_m, "tool": "tools/build_region.py"}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{args.name}.json").write_text(
        json.dumps({**meta, "polygons": _lonlat(buffered)}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (args.out_dir / "kreise.json").write_text(
        json.dumps({**meta, "kreise": kreise}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for f in (f"{args.name}.json", "kreise.json"):
        log.info("%s: %d KB", f, (args.out_dir / f).stat().st_size // 1024)
    log.info("Kreise in der Fläche: %d", len(kreise))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
