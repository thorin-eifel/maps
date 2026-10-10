#!/usr/bin/env python3
"""Offene WMS-Dienste aus der Geoportal-RLP-Suche holen (Eingabe für build_landesdaten_katalog.py).

Zweck:      Liest die Suche des Geoportals (Mapbender, mod_callMetadata.php, nur offene Daten) seitenweise und schreibt je Dienst Titel,
            Betreiber, Lizenz, Adressen und Ebenenliste in eine JSON-Datei. Keine Kartenabrufe, nur der Katalog.
Quelle:     https://www.geoportal.rlp.de/search/  (Metadatensuche, öffentlich, ohne Anmeldung)
Höflichkeit: eine Sekunde Pause je Seite (99 Treffer), ehrlicher User-Agent, einmaliger Lauf (ca. 3 Minuten).
Aufruf:     python tools/crawl_geoportal.py --out /tmp/open_wms.json
Exit:       0 = vollständig, 1 = Seite nicht erreichbar (Teilergebnis wird nicht geschrieben)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Landblick/1.0 (+https://github.com/thorin-eifel/maps; Katalogabruf, einmalig)"
log = logging.getLogger("crawl_geoportal")
SRV_KEYS = ("id", "title", "abstract", "getMapUrl", "originalGetCapabilitiesUrl", "wmsGetCapabilitiesUrl", "respOrg", "isopen", "license_id",
            "bbox", "loadCount", "avail", "date", "iso3166", "wmsRootLayerId")
LAYER_KEYS = ("id", "title", "name", "abstract", "minScale", "maxScale", "queryable")


def seite(n: int) -> dict | None:
    p = dict(searchText="e", resultTarget="web", searchResources="wms", maxResults=99, searchPages=n, outputFormat="json", restrictToOpenData="true",
             languageCode="de", searchEPSG="EPSG:4326", orderBy="title", hostName="www.geoportal.rlp.de", searchId="landblick-katalog")
    url = "https://www.geoportal.rlp.de/mapbender/php/mod_callMetadata.php?" + urllib.parse.urlencode(p)
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            log.warning("Seite %d: %s", n, e)
            time.sleep(5)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out: dict = {}
    n = 1
    while True:
        d = seite(n)
        if not d:
            log.error("Seite %d nicht erreichbar, Abbruch", n)
            return 1
        w = d["wms"]
        total = int(w["md"]["nresults"])
        for s in w["srv"]:
            e = out.setdefault(s["id"], {k: s.get(k) for k in SRV_KEYS} | {"layers": []})
            e["layers"] += [{k: lay.get(k) for k in LAYER_KEYS} for lay in s.get("layer", [])]
        log.info("Seite %d: %d Dienste (gesamt %d)", n, len(w["srv"]), len(out))
        if n * 99 >= total:
            break
        n += 1
        time.sleep(1)
    args.out.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("%s: %d Dienste", args.out, len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
