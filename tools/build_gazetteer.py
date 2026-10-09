#!/usr/bin/env python3
"""Ortsverzeichnis für die Ortszuordnung von Meldungen bauen (app/data/orte.json).

Zweck:     Meldungen nennen Orte ("Steinebrück/Wittlich (ots)"), keine Koordinaten. Damit wir sie ohne externen
           Geocoder verorten können, liegt ein kleines Verzeichnis aus OpenStreetMap-Ortsknoten im Repository.
Quelle:    OpenStreetMap-Mitwirkende, ODbL 1.0 (Overpass-Abfrage place=city|town|village|hamlet|suburb)
Aufruf:    python tools/build_gazetteer.py                # holt Daten über Overpass-Spiegel
           python tools/build_gazetteer.py --input places.json   # liest eine vorhandene Overpass-Antwort
Ergebnis:  app/data/orte.json: [{"n": Name, "lat": .., "lon": .., "k": Rang}], nur Orte im Radius plus 5 km Rand.
Gespeichert werden nur Name, Koordinate und Rang. Keine weiteren Tags.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, geo  # noqa: E402

log = logging.getLogger("gazetteer")
MIRRORS = ("https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter")
RANK = {"city": 1, "town": 2, "village": 3, "suburb": 4, "hamlet": 5}
QUERY = ('[out:json][timeout:80];node["place"~"^(city|town|village|hamlet|suburb)$"]["name"](%s,%s,%s,%s);'
         "out tags center;")


def fetch() -> dict:
    s, w, n, e = config.BBOX
    body = urllib.parse.urlencode({"data": QUERY % (s, w, n, e)}).encode()
    last: Exception | None = None
    for url in MIRRORS:
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": f"WasIstLosBeiUns/1.0 (+{config.CONTACT})"})
            with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (feste https-Ziele)
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: %s", url, exc)
            last = exc
    raise SystemExit(f"Overpass nicht erreichbar: {last}")


def build(data: dict) -> list[dict]:
    out, seen = [], set()
    for el in data.get("elements", []):
        t = el.get("tags") or {}
        name, kind = (t.get("name") or "").strip(), t.get("place")
        if not name or kind not in RANK or "lat" not in el:
            continue
        lat, lon = float(el["lat"]), float(el["lon"])
        if geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM + 5:
            continue
        key = (name, round(lat, 3), round(lon, 3))
        if key in seen:
            continue
        seen.add(key)
        out.append({"n": name, "lat": round(lat, 4), "lon": round(lon, 4), "k": RANK[kind]})
    out.sort(key=lambda o: (o["k"], o["n"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path)
    ap.add_argument("--output", type=Path, default=config.BASE_DIR / "app" / "data" / "orte.json")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data = json.loads(a.input.read_text(encoding="utf-8")) if a.input else fetch()
    orte = build(data)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(orte, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("%d Orte nach %s", len(orte), a.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
