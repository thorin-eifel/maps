#!/usr/bin/env python3
"""Gewässerhierarchie (Strom → Fluss → Bach) für die Pegelansicht aus Wikidata bauen.

Zweck:     Ordnet die Gewässernamen der Pegelstationen den Flussläufen in Wikidata zu (Eigenschaft "mündet in", P403), holt Mündungs- und
           Quellkoordinaten und schreibt web/data/gewaessernetz.json. Läuft von Hand (selten), nicht im Dauerbetrieb.
Quelle:    https://query.wikidata.org/sparql  (Wikidata, CC0). Namensnennung im UI unter "Quellen und Lizenzen".
Aufruf:    python tools/build_gewaessernetz.py --gewaesser web/data/gewaesser.json --out web/data/gewaessernetz.json
Hinweise:  Namen sind nicht eindeutig (Mühlbach, Schwarzbach). Je Quelle+Gewässername wird der Kandidat gewählt, dessen Koordinaten am nächsten
           an den Stationen liegen (höchstens MAX_KM). Ohne Treffer bleibt die Station in "Zuordnung offen"; geraten wird nicht.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("gewaessernetz")
ENDPOINT = "https://query.wikidata.org/sparql"
UA = "WasIstLosBeiUns/1.0 (Gewaessernetz-Tool; kontakt siehe Impressum)"
MAX_KM = 45.0
MAX_KM_UNIQUE = 400.0
TOPS = {"Q584", "Q41986"}   # Rhein, Maas — sonst endet die Kette, wo Wikidata kein "mündet in" mehr kennt

# Belgische und französische Bezeichnungen → Name, unter dem der Lauf in Wikidata steht. Fehlt ein Name hier, wird er nach Entfernen der
# Artikel ("La ", "Le ", "L'", "Ruisseau …" bleibt) unverändert gesucht.
ALIAS = {
    "La Meuse": "Maas", "Haute Meuse (amont Dinant)": "Maas", "Haute Meuse (aval Dinant)": "Maas", "Meuse moyenne": "Maas", "Basse Meuse": "Maas",
    "La Moselle": "Mosel", "La Moselle Canalisee": "Mosel", "La Sarre": "Saar", "La Semoy": "Semois", "Moyenne Semois": "Semois",
    "Basse Semois": "Semois", "Haute Semois": "Semois", "Ourthe inférieure": "Ourthe", "Ourthe moyenne": "Ourthe", "Ourthe supérieure": "Ourthe",
    "Basse Lesse": "Lesse", "Haute Lesse": "Lesse", "Sûre": "Sauer", "Eau d'Our": "Our", "Die Braunlauf": "Braunlauf",
    "La Nied Allemande": "Nied allemande", "Hoegne": "Hoëgne", "Lhomme": "Lomme", "La Nied": "Nied", "L'Orne": "Orne", "La Seille": "Seille", "La Chiers": "Chiers", "Chiers": "Chiers",
    "La Blies": "Blies", "La Bisten": "Bist", "La Houille": "Houille", "Houille": "Houille", "La Crusnes": "Crusnes", "L'Othain": "Othain",
    "L'Yron": "Yron", "Le Loison": "Loison", "Le Thon": "Thon", "La Fensch": "Fensch", "La Horn": "Horn", "L'Albe": "Albe", "L'Isch": "Isch",
    "La Petite Seille": "Petite Seille", "Ourthe Occidentale": "Ourthe occidentale", "Ourthe Orientale": "Ourthe orientale",
}
SKIP = {"Kommunale Messstelle"}
# Große Läufe, bei denen die Koordinaten in Wikidata weit weg von den Stationen liegen und der Name mehrfach vorkommt; Kennungen am 2026-10-07 geprüft
# (Rhein Q584 mündet in die Nordsee, Saar Q153972 in die Mosel, Lahn Q103148 in den Rhein).
FORCE = {"Rhein": "Q584", "Saar": "Q153972", "Lahn": "Q103148"}
KEEP_RAW = {"Eau d'Our"}      # nicht auf den Suchnamen "Our" umbenennen: es ist ein Zufluss der Lesse, nicht die Our der Grenze
GERMAN_SOURCES = {"pegelonline", "hochwasser_rlp", "lu_pegel"}
ARTICLE = re.compile(r"^(La|Le|Les|L')\s*", re.I)


def canon(raw: str | None) -> str | None:
    if not raw or raw in SKIP or raw == "-":
        return None
    return ALIAS.get(raw, raw).strip()


def hav(a: tuple[float, float], b: tuple[float, float]) -> float:
    p = math.radians
    x = math.sin(p(b[0] - a[0]) / 2) ** 2 + math.cos(p(a[0])) * math.cos(p(b[0])) * math.sin(p(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def sparql(query: str, retries: int = 3) -> list[dict]:
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(ENDPOINT, data=data, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as exc:   # noqa: BLE001 — Wikidata antwortet gelegentlich mit 504/429, dann kurz warten
            LOG.warning("SPARQL Versuch %d: %s", i + 1, exc)
            time.sleep(4 * (i + 1))
    raise SystemExit("Wikidata nicht erreichbar")


def pt(wkt: str) -> tuple[float, float] | None:
    m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", wkt)
    return (float(m.group(2)), float(m.group(1))) if m else None


def lit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_candidates(names: list[str]) -> dict[str, dict[str, dict]]:
    """name → {qid: {label, mouth:qid, pts:[(lat,lon)…]}} (Treffer über Bezeichnung de/fr/en/nl/lb, nur Läufe mit 'mündet in')."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for i in range(0, len(names), 20):
        part = names[i:i + 20]
        vals = " ".join(f"({lit(n)}@{lg} {lit(n)})" for n in part for lg in ("de", "fr", "en", "nl", "lb"))
        q = f"""SELECT ?n ?item ?itemLabel ?mouth ?c ?mc WHERE {{
          VALUES (?l ?n) {{ {vals} }}
          ?item rdfs:label ?l . ?item wdt:P403 ?mouth .
          OPTIONAL {{ ?item wdt:P625 ?c }} OPTIONAL {{ ?mouth wdt:P625 ?mc }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "de,fr,en". }} }}"""
        for r in sparql(q):
            qid = r["item"]["value"].rsplit("/", 1)[1]
            d = out[r["n"]["value"]].setdefault(qid, {"label": r["itemLabel"]["value"], "mouth": r["mouth"]["value"].rsplit("/", 1)[1], "pts": []})
            for k in ("c", "mc"):
                if k in r and (p := pt(r[k]["value"])):
                    d["pts"].append(p)
        LOG.info("Kandidaten %d/%d", min(i + 20, len(names)), len(names))
    return out


def river_geometry(qids: list[str]) -> dict[str, dict]:
    """qid → label, mouth (qid), mouth_pt, src_pt aus Aussagen mit Qualifikator 'Mündung' (Q1233637? nein: P518 'betrifft Teil') bzw. 'Quellgebiet'."""
    out: dict[str, dict] = {}
    for i in range(0, len(qids), 30):
        vals = " ".join(f"wd:{q}" for q in qids[i:i + 30])
        q = f"""SELECT ?item ?itemLabel ?mouth ?c ?partLabel WHERE {{
          VALUES ?item {{ {vals} }}
          OPTIONAL {{ ?item wdt:P403 ?mouth }}
          OPTIONAL {{ ?item p:P625 ?st . ?st ps:P625 ?c . OPTIONAL {{ ?st pq:P518 ?part }} }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "de,fr,en". }} }}"""
        for r in sparql(q):
            qid = r["item"]["value"].rsplit("/", 1)[1]
            d = out.setdefault(qid, {"label": r["itemLabel"]["value"], "mouth": None, "mouth_pt": None, "src_pt": None, "any": None})
            if "mouth" in r:
                d["mouth"] = r["mouth"]["value"].rsplit("/", 1)[1]
            if "c" in r and (p := pt(r["c"]["value"])):
                part = r.get("partLabel", {}).get("value", "").lower()
                if "mündung" in part or "mouth" in part or "embouchure" in part:
                    d["mouth_pt"] = p
                elif "quell" in part or "source" in part:
                    d["src_pt"] = p
                else:
                    d["any"] = p
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gewaesser", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(message)s")
    stations = json.loads(a.gewaesser.read_text())["stations"]
    groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for s in stations:
        groups[f"{s['source_id']}|{s.get('water') or ''}"].append((s["lat"], s["lon"]))
    names = sorted({c for k in groups if (c := canon(k.split("|", 1)[1]))})
    LOG.info("%d Schlüssel, %d Namen", len(groups), len(names))
    cands = find_candidates(names)
    mapping: dict[str, str] = {}
    for key, pts in groups.items():
        name = canon(key.split("|", 1)[1])
        if name in FORCE:
            mapping[key] = FORCE[name]
            continue
        if not name or name not in cands:
            continue
        cx = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        best = min(((min((hav(cx, p) for p in c["pts"]), default=9999.0), q) for q, c in cands[name].items()), default=None)
        # Große Läufe haben nur einen Koordinatenpunkt weit weg von der Station: bei genau einem Kandidaten reicht der weite Radius
        limit = MAX_KM if len(cands[name]) > 1 else MAX_KM_UNIQUE
        if best and best[0] <= limit:
            mapping[key] = best[1]
        else:
            LOG.info("offen: %s (%s)", key, f"{best[0]:.0f} km" if best else "kein Kandidat")
    rivers: dict[str, dict] = {}
    display: dict[str, str] = {}
    for key, q in mapping.items():
        src, raw = key.split("|", 1)
        if src in GERMAN_SOURCES:
            continue
        display.setdefault(q, raw if raw in KEEP_RAW else canon(raw) if raw in ALIAS else ARTICLE.sub("", raw).strip())
    todo = sorted(set(mapping.values()))
    for _ in range(8):   # Kette zur Mündung hochlaufen
        todo = [q for q in todo if q not in rivers]
        if not todo:
            break
        rivers.update(river_geometry(todo))
        todo = [rivers[q]["mouth"] for q in todo if q in rivers and q not in TOPS and rivers[q]["mouth"] and rivers[q]["mouth"] not in rivers]
    out = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "quelle": "Wikidata (CC0)", "map": mapping, "rivers": {}}
    for q, d in rivers.items():
        top = q in TOPS
        name = display.get(q) or re.sub(r"\s*\(.*\)$", "", d["label"])
        out["rivers"][q] = {"name": name, "parent": None if top else d["mouth"] if d["mouth"] in rivers and (d["mouth"] in TOPS or rivers[d["mouth"]]["mouth"]) else None,
                            "mouth": d["mouth_pt"] or d["any"] if d["mouth_pt"] or d["any"] else None, "src": d["src_pt"]}
    a.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    LOG.info("%s: %d Zuordnungen, %d Läufe", a.out, len(mapping), len(out["rivers"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
