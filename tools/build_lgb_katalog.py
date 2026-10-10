#!/usr/bin/env python3
"""Katalog der LGB-Kartendienste (WMS) bauen: web/geo/lgb.json.

Zweck:      Das Menü "LGB Daten" der Karte zeigt die Online-Karten des Landesamts für Geologie und Bergbau Rheinland-Pfalz (LGB) als
            Schalter nach Themen, so wie https://www.lgb-rlp.de/karten-und-produkte/online-karten sie gruppiert. Dieses Werkzeug liest
            einmalig die GetCapabilities-Dokumente der Dienste und schreibt Gruppen, Dienste und Ebenen (Name, Titel, Maßstabsbereich,
            Legende) in eine statische Datei. Die Seite selbst fragt die Capabilities nie ab.
Quelle:     https://mapserver.lgb-rlp.de/cgi-bin/<dienst>?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities  (Liste: .../karten-und-produkte/ogc-dienste)
Lizenz:     Datenlizenz Deutschland – Namensnennung – 2.0 (dl-de/by-2-0), Vermerk "©LGB-RLP <Jahr>, dl-de/by-2-0, www.lgb-rlp.de [Daten bearbeitet]"
            laut https://www.lgb-rlp.de/karten-und-produkte/online-karten/nutzungsbedingungen-fuer-online-karten
Höflichkeit: ein Abruf je Dienst, eine Sekunde Pause, ehrlicher User-Agent. Aufruf selten (bei Änderungen am Angebot).
Aufruf:     python tools/build_lgb_katalog.py                  schreibt web/geo/lgb.json
            python tools/build_lgb_katalog.py --from-dir DIR   liest DIR/<dienst>.xml statt zu laden (Tests, offline)
            python tools/build_lgb_katalog.py --save-dir DIR   legt die geladenen XML zusätzlich in DIR ab
Exit:       0 = geschrieben, 1 = Dienst fehlt oder ohne Ebenen
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://mapserver.lgb-rlp.de/cgi-bin/"
NS = {"w": "http://www.opengis.net/wms", "x": "http://www.w3.org/1999/xlink"}
UA = "WasIstLosBeiUns/1.0 (+https://github.com/thorin-eifel/maps; Katalogabruf, einmalig)"
log = logging.getLogger("lgb_katalog")

# Gruppen wie auf der LGB-Seite (Reihenfolge der OGC-Dienste-Seite), je Gruppe die Dienstkennungen (cgi-bin/<id>)
GRUPPEN: list[tuple[str, str, list[str]]] = [
    ("bergbau", "Bergbau", ["mc_berechtsamskarte", "mc_aak"]),
    ("boden", "Boden", ["mc_bfd5", "mc_bfd5w", "mc_bfd50_200", "mc_bfd50", "mc_bfd200", "mc_abag", "mc_bfd50_hgw"]),
    ("erdbeben", "Erdbeben", ["mc_erdbeben"]),
    ("geoldg", "Geologiedatengesetz", ["mc_geoldg"]),
    ("geologie", "Geologie", ["mc_guek300", "mc_gk25"]),
    ("geothermie", "Geothermie", ["mc_ewa_pruef", "mc_wlf", "mc_ewk"]),
    ("hydrogeologie", "Hydrogeologie", ["mc_huek200", "mc_huek300", "mc_hgp", "mc_hce", "mc_gwo", "mc_minwa", "mc_thorg"]),
    ("ingenieurgeologie", "Ingenieurgeologie", ["mc_ghk", "mc_hangstabilitaet", "mc_rutschung"]),
    ("rohstoffgeologie", "Rohstoffgeologie", ["mc_rohstoff"]),
]


# Technische Hilfsebenen der Dienste, die auf der LGB-Seite nicht als Karte erscheinen (Kachelquelle und Vektorabfrage dienen den LGB-Viewern,
# "Herunterladen" ist eine Auswahlebene für Downloads). Sie bleiben aus dem Katalog.
AUSGEBLENDET = {
    "amtlich_raster_kacheln", "amtlich_raster", "amtlich_poly_abfrage",
    "manuskript_raster_kacheln", "manuskript_raster", "manuskript_poly_abfrage", "download_karten",
}


def _t(el: ET.Element | None, path: str) -> str:
    n = el.find(path, NS) if el is not None else None
    return (n.text or "").strip() if n is not None and n.text else ""


def klartext(s: str, limit: int = 240) -> str:
    """Abstract ohne HTML, Entities aufgelöst, auf limit Zeichen gekürzt (Wortgrenze)."""
    s = re.sub(r"<[^>]+>", " ", html.unescape(s))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit].rsplit(" ", 1)[0] + " …"


def _scale(el: ET.Element, tag: str, inherit: float | None) -> float | None:
    v = _t(el, f"w:{tag}")
    try:
        return float(v) if v else inherit
    except ValueError:
        return inherit


def parse_layer(el: ET.Element, smin: float | None, smax: float | None) -> dict:
    smin, smax = _scale(el, "MinScaleDenominator", smin), _scale(el, "MaxScaleDenominator", smax)
    node: dict = {"title": _t(el, "w:Title")}
    name = _t(el, "w:Name")
    if name:
        node["name"] = name
        ab = klartext(_t(el, "w:Abstract"))
        if ab and ab != node["title"]:
            node["abstract"] = ab
        if smin:
            node["min_scale"] = round(smin)
        if smax:
            node["max_scale"] = round(smax)
        lg = el.find("w:Style/w:LegendURL/w:OnlineResource", NS)
        if lg is not None:
            node["legend"] = lg.get("{%s}href" % NS["x"], "")
        data = el.find("w:DataURL/w:OnlineResource", NS)
        if data is not None and data.get("{%s}href" % NS["x"]):
            node["info"] = data.get("{%s}href" % NS["x"])
    kids = [k for k in (parse_layer(c, smin, smax) for c in el.findall("w:Layer", NS) if _t(c, "w:Name") not in AUSGEBLENDET) if k]
    if kids:
        node["children"] = kids
    return node


def parse_capabilities(xml: bytes, dienst: str) -> dict:
    root = ET.fromstring(xml)
    svc = root.find("w:Service", NS)
    top = root.find("w:Capability/w:Layer", NS)
    if top is None:
        raise ValueError(f"{dienst}: keine Ebenen im Dokument")
    crs = {c.text for c in top.findall("w:CRS", NS)}
    if "EPSG:3857" not in crs:
        raise ValueError(f"{dienst}: EPSG:3857 nicht angeboten ({sorted(crs)[:6]})")
    smin, smax = _scale(top, "MinScaleDenominator", None), _scale(top, "MaxScaleDenominator", None)
    layers = [parse_layer(c, smin, smax) for c in top.findall("w:Layer", NS) if _t(c, "w:Name") not in AUSGEBLENDET]
    if not layers:
        raise ValueError(f"{dienst}: keine Ebenen")
    out = {"id": dienst, "title": _t(svc, "w:Title") or _t(top, "w:Title"), "url": BASE + dienst, "layers": layers}
    ab = klartext(_t(svc, "w:Abstract"), 400)
    if ab:
        out["abstract"] = ab
    return out


def fetch(dienst: str) -> bytes:
    url = f"{BASE}{dienst}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def count(layers: list[dict]) -> int:
    return sum((1 if "name" in n else 0) + count(n.get("children", [])) for n in layers)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "web/geo/lgb.json")
    ap.add_argument("--from-dir", type=Path)
    ap.add_argument("--save-dir", type=Path)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    gruppen, fehler = [], 0
    for gid, gname, dienste in GRUPPEN:
        svcs = []
        for d in dienste:
            try:
                if args.from_dir:
                    xml = (args.from_dir / f"{d}.xml").read_bytes()
                else:
                    xml = fetch(d)
                    time.sleep(1.0)
                if args.save_dir:
                    args.save_dir.mkdir(parents=True, exist_ok=True)
                    (args.save_dir / f"{d}.xml").write_bytes(xml)
                s = parse_capabilities(xml, d)
                svcs.append(s)
                log.info("%-22s %3d Ebenen  %s", d, count(s["layers"]), s["title"])
            except Exception as e:  # noqa: BLE001 - jeder Dienst einzeln, Fehler zählen
                fehler += 1
                log.error("%s: %s", d, e)
        gruppen.append({"id": gid, "title": gname, "services": svcs})
    if fehler:
        return 1
    doc = {
        "quelle": "Landesamt für Geologie und Bergbau Rheinland-Pfalz (LGB)",
        "seite": "https://www.lgb-rlp.de/karten-und-produkte/online-karten",
        "dienste": "https://www.lgb-rlp.de/karten-und-produkte/ogc-dienste",
        "nutzungsbedingungen": "https://www.lgb-rlp.de/karten-und-produkte/online-karten/nutzungsbedingungen-fuer-online-karten",
        "lizenz": "dl-de/by-2-0", "lizenz_url": "https://www.govdata.de/dl-de/by-2-0",
        "vermerk": "©LGB-RLP {jahr}, dl-de/by-2-0, www.lgb-rlp.de [Daten bearbeitet]",
        "ausgeblendet": sorted(AUSGEBLENDET),
        "abgerufen": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "groups": gruppen,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(count(s["layers"]) for g in gruppen for s in g["services"])
    log.info("%s: %d Gruppen, %d Dienste, %d Ebenen, %.0f KB", args.out, len(gruppen), sum(len(g["services"]) for g in gruppen), n, args.out.stat().st_size / 1e3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
