#!/usr/bin/env python3
"""Katalog der offenen Kartendienste der Landesstellen bauen: web/geo/landesdaten.json.

Zweck:      Das Menü "Landesdaten" der Karte zeigt WMS-Dienste der Landesstellen Rheinland-Pfalz, die im Geoportal RLP als offene Daten
            geführt sind (Landesamt für Vermessung, Landesamt für Umwelt, Landesforsten, SGD, LBM, GDKE …) als Schalter nach Anbietern.
            Dieses Werkzeug wählt die Dienste aus der Geoportal-Suche aus, liest je Dienst einmal die GetCapabilities und schreibt Gruppen,
            Dienste und Ebenen in eine statische Datei. Die Seite selbst fragt nie Capabilities ab.
Quelle:     Geoportal RLP, Suche (Mapbender mod_callMetadata.php, restrictToOpenData=true), dazu je Dienst GetCapabilities beim Betreiber.
Lizenz:     je Dienst aus dem Geoportal (dl-de/by-2-0, dl-de/zero-2-0, CC BY 3.0/4.0, ODbL 1.0); der Vermerk steht je Dienst im Katalog.
            Die Lizenzangaben stammen aus dem Geoportal und sind nicht rechtlich geprüft (lizenz_geprueft: false).
Auswahl:    Nur Landesstellen (Liste ANBIETER), nur https, nur Dienste, die EPSG:3857 anbieten und ihre Capabilities ohne Zertifikatsfehler
            liefern. Kommunen (Städte, Verbandsgemeinden, Ortsgemeinden), der LGB (eigenes Menü) und Dienste außerhalb von RLP fehlen.
            Was herausfällt, steht mit Grund in `ausgelassen` im Katalog und im Log.
Höflichkeit: ein Abruf je Dienst, eine Sekunde Pause, ehrlicher User-Agent. Aufruf selten (bei Änderungen am Angebot).
Aufruf:     python tools/crawl_geoportal.py --out /tmp/open_wms.json         Suche im Geoportal (einmalig, ca. 3 Minuten)
            python tools/build_landesdaten_katalog.py --meta /tmp/open_wms.json
            python tools/build_landesdaten_katalog.py --meta M.json --from-dir DIR   liest DIR/<id>.xml statt zu laden (Tests, offline)
            python tools/build_landesdaten_katalog.py --meta M.json --save-dir DIR   legt die geladenen XML zusätzlich in DIR ab
Exit:       0 = geschrieben
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.parse as up
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_lgb_katalog as lgb  # noqa: E402  (gleicher Parser für Capabilities)

ROOT = Path(__file__).resolve().parent.parent
UA = "Landblick/1.0 (+https://github.com/thorin-eifel/maps; Katalogabruf, einmalig)"
log = logging.getLogger("landesdaten_katalog")

# Landesstellen: Präfix des Betreibernamens im Geoportal → (Gruppentitel, Betreibername für den Vermerk). Reihenfolge = Menüreihenfolge.
ANBIETER: list[tuple[str, str, str]] = [
    ("Landesamt für Vermessung", "Vermessung und Geobasisdaten", "Landesamt für Vermessung und Geobasisinformationen Rheinland-Pfalz"),
    ("Landesamt für Umwelt", "Umwelt (Landesamt für Umwelt)", "Landesamt für Umwelt Rheinland-Pfalz"),
    ("MLWUF", "Wasserwirtschaft (Ministerium)", "Ministerium für Klimaschutz, Umwelt, Energie und Mobilität Rheinland-Pfalz"),
    ("LfU-Naturschutz", "Naturschutz", "Landesamt für Umwelt Rheinland-Pfalz"),
    ("SGD-Nord - LANIS", "Naturschutz (LANIS)", "Struktur- und Genehmigungsdirektion Nord"),
    ("Landesforsten", "Forsten", "Landesforsten Rheinland-Pfalz"),
    ("Zentrale Stelle GDI", "Geodateninfrastruktur (Zentrale Stelle GDI-RP)", "Zentrale Stelle GDI-RP"),
    ("SGD Nord", "Raumordnung und Hochwasser (SGD Nord)", "Struktur- und Genehmigungsdirektion Nord"),
    ("SGD Süd", "Raumordnung (SGD Süd)", "Struktur- und Genehmigungsdirektion Süd"),
    ("LBM", "Straßen (Landesbetrieb Mobilität)", "Landesbetrieb Mobilität Rheinland-Pfalz"),
    ("DLR", "Ländlicher Raum (DLR)", "Dienstleistungszentrum Ländlicher Raum Rheinland-Pfalz"),
    ("Generaldirektion Kulturelles Erbe", "Kulturelles Erbe", "Generaldirektion Kulturelles Erbe Rheinland-Pfalz"),
    ("LBZ", "Bildung (LBZ)", "Landesbibliothekszentrum Rheinland-Pfalz"),
    ("StaLa", "Statistik (Statistisches Landesamt)", "Statistisches Landesamt Rheinland-Pfalz"),
]
# Eigene Menüs oder fremde Länder: nicht hier.
AUSGESCHLOSSEN_HOSTS = {"mapserver.lgb-rlp.de", "www.wms.nrw.de", "sg.geodatenzentrum.de", "sgx.geodatenzentrum.de"}
# Geoportal-Lizenzkennung → (Kurzname, Adresse)
LIZENZEN = {
    "dl-de-by-2.0": ("dl-de/by-2-0", "https://www.govdata.de/dl-de/by-2-0"),
    "dl-de-zero-2.0": ("dl-de/zero-2-0", "https://www.govdata.de/dl-de/zero-2-0"),
    "cc-by-3.0": ("CC BY 3.0", "https://creativecommons.org/licenses/by/3.0/de/"),
    "cc-by-4.0": ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/deed.de"),
    "odc-odbl-1.0": ("ODbL 1.0", "https://opendatacommons.org/licenses/odbl/1-0/"),
}


def anbieter_von(org: str):
    org = org.strip()
    for pre, titel, name in ANBIETER:
        if org.startswith(pre):
            return pre, titel, name
    return None


def basis_url(meta_url: str) -> str | None:
    """GetMap-Basis-URL: https erzwingen, WMS-Parameter der Vorlage entfernen. None, wenn kein https möglich ist."""
    u = up.urlsplit(meta_url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    host = u.netloc.removesuffix(":443")
    q = [(k, v) for k, v in up.parse_qsl(u.query, keep_blank_values=True) if k.upper() not in ("SERVICE", "REQUEST", "VERSION")]
    return up.urlunsplit(("https", host, u.path, up.urlencode(q, safe="/"), ""))


def mit_params(basis: str, params: str) -> str:
    """Hängt Parameter an eine Basis-URL, die schon eine Abfrage (z. B. map=…) tragen darf."""
    if basis.endswith(("?", "&")):
        return basis + params
    return basis + ("&" if "?" in basis else "?") + params


def fetch(basis: str) -> bytes:
    req = urllib.request.Request(mit_params(basis, "SERVICE=WMS&VERSION=1.3.0&REQUEST=GetCapabilities"), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


_NACKTES_UND = re.compile(rb"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)")


def repariere(xml: bytes) -> bytes:
    """Einige Server schreiben unmaskierte & in URLs (Legenden, Metadaten). Das ist kein gültiges XML; wir maskieren sie, sonst nichts."""
    return _NACKTES_UND.sub(b"&amp;", xml)


def vermerk(name: str, lizenz: str) -> str:
    kurz = LIZENZEN.get(lizenz, (lizenz, ""))[0]
    return f"©{name} {{jahr}}, {kurz} [Daten bearbeitet]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "web/geo/landesdaten.json")
    ap.add_argument("--from-dir", type=Path)
    ap.add_argument("--save-dir", type=Path)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    gruppen: dict[str, dict] = {pre: {"id": pre, "title": titel, "services": []} for pre, titel, _ in ANBIETER}
    ausgelassen: list[dict] = []
    hosts: set[str] = set()
    gesehen: set[str] = set()
    for sid, s in sorted(meta.items(), key=lambda kv: (kv[1]["respOrg"], kv[1]["title"])):
        a = anbieter_von(s["respOrg"])
        if not a:
            continue
        pre, titel, name = a
        basis = basis_url(s["getMapUrl"])
        host = up.urlsplit(basis).hostname if basis else ""
        if not basis or host in AUSGESCHLOSSEN_HOSTS or s.get("license_id") not in LIZENZEN or str(s.get("isopen")) != "1":
            ausgelassen.append({"geoportal_id": sid, "titel": s["title"], "grund": "Host/Lizenz/Adresse nicht zugelassen"})
            continue
        if basis in gesehen:   # derselbe Dienst unter mehreren Geoportal-Einträgen
            continue
        gesehen.add(basis)
        try:
            if args.from_dir:
                xml = (args.from_dir / f"{sid}.xml").read_bytes()
            else:
                xml = fetch(basis)
                time.sleep(1.0)
            if args.save_dir:
                args.save_dir.mkdir(parents=True, exist_ok=True)
                (args.save_dir / f"{sid}.xml").write_bytes(xml)
            xml = repariere(xml)
            if b"<WMT_MS_Capabilities" in xml[:2000]:
                raise ValueError("Dienst antwortet nur mit WMS 1.1.1 (1.3.0 nicht angeboten)")
            dienst = lgb.parse_capabilities(xml, sid)
        except Exception as e:  # noqa: BLE001 - jeder Dienst einzeln
            grund = str(e).splitlines()[0][:140]
            log.warning("%s %s: %s", sid, s["title"], grund)
            ausgelassen.append({"geoportal_id": sid, "titel": s["title"], "host": host, "grund": grund})
            continue
        lic = LIZENZEN[s["license_id"]]
        dienst.update({
            "id": f"gp{sid}", "title": s["title"], "url": basis, "betreiber": name,
            "lizenz": lic[0], "lizenz_url": lic[1], "vermerk": vermerk(name, s["license_id"]),
            "geoportal": f"https://www.geoportal.rlp.de/mapbender/php/mod_exportIso19139.php?url=https%3A%2F%2Fwww.geoportal.rlp.de%2Fmapbender%2Fphp%2Fmod_dataISOMetadata.php%3Fid%3D{sid}",
        })
        if s.get("abstract"):
            dienst["abstract"] = lgb.klartext(s["abstract"], 400)
        gruppen[pre]["services"].append(dienst)
        hosts.add(host)
        log.info("%-6s %3d Ebenen  %s", sid, lgb.count(dienst["layers"]), s["title"])
    out_gr = [g for g in gruppen.values() if g["services"]]
    doc = {
        "quelle": "Landesstellen Rheinland-Pfalz über das Geoportal RLP (offene Daten)",
        "seite": "https://www.geoportal.rlp.de/search/",
        "lizenz": "je Dienst", "lizenz_geprueft": False,
        "hosts": sorted(hosts),
        "ausgeblendet": sorted(lgb.AUSGEBLENDET),
        "abgerufen": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "ausgelassen": ausgelassen,
        "groups": out_gr,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(lgb.count(s["layers"]) for g in out_gr for s in g["services"])
    log.info("%s: %d Gruppen, %d Dienste, %d Ebenen, %d Hosts, %d ausgelassen, %.0f KB", args.out, len(out_gr),
             sum(len(g["services"]) for g in out_gr), n, len(hosts), len(ausgelassen), args.out.stat().st_size / 1e3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
