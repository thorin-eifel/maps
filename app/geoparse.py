"""Ortserkennung für Meldungen (regelbasiert, ohne Modell, ohne externen Dienst).

Zweck:    Aus einem Ortsnamen oder einer Schlagzeile einen Punkt im Radius ableiten. Grundlage ist das kleine
          Ortsverzeichnis app/data/orte.json (OpenStreetMap, ODbL; Bauanleitung: tools/build_gazetteer.py).
Regeln:   - Treffer nur auf ganze Wörter ("Trier" trifft nicht "Trierer").
          - Mehrdeutige Namen: Datumszeile "A/B" nutzt B als Hinweis (Nachbarort), sonst gewinnt der Treffer
            nächst dem Mittelpunkt; die Zuordnung wird als unsicher markiert (confidence 0.6).
          - In Schlagzeilen zählen nur Städte, Gemeinden, Dörfer und Stadtteile mit mindestens 4 Buchstaben, Stoppliste für
            Namen, die auch gewöhnliche Wörter sind. Ohne Treffer bleibt die Meldung ohne Ort und wird verworfen.
Beispiel: locate_dateline("Steinebrück/Wittlich") -> Place("Steinebrück", 49.9.., 6.8.., 0.9)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from . import geo

DATA = Path(__file__).resolve().parent / "data" / "orte.json"
# Ortsnamen, die zugleich gewöhnliche Wörter oder Eigennamen anderer Art sind; in Fließtext nicht auswerten.
NEIGHBOUR_KM = 15.0
STOP = {"hof", "berg", "tal", "land", "stadt", "heide", "bach", "brück", "mühle", "eifel", "wald", "feld", "dorf",
        "nord", "süd", "ost", "west", "mitte", "busch", "born", "rech", "hahn", "mehren", "neuerburg-land", "wahl",
        "dann", "sonne", "frei", "wirft", "kell", "ohne", "gold", "kopf", "lauf", "hausen", "berge", "brand"}


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    confidence: float
    rank: int = 3


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.casefold().strip())


@lru_cache(maxsize=1)
def _load(path: str = str(DATA)) -> tuple[dict[str, list[dict]], "re.Pattern[str] | None"]:
    try:
        orte = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    by_name: dict[str, list[dict]] = {}
    for o in orte:
        by_name.setdefault(_norm(o["n"]), []).append(o)
    names = [n for n, lst in by_name.items()
             if len(n) >= 4 and n not in STOP and any(o["k"] <= 4 for o in lst)]
    names.sort(key=len, reverse=True)
    if not names:
        return by_name, None
    pat = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])", re.I)
    return by_name, pat


def _dist(o: dict) -> float:
    return geo.distance_to_ref_km(o["lat"], o["lon"])


def _inside(o: dict) -> bool:
    return geo.in_region(o["lat"], o["lon"])


def _pick(cands: list[dict], hints: Iterable[dict] = ()) -> tuple[dict, float]:
    inside = [c for c in cands if _inside(c)]
    if not inside:
        raise LookupError("außerhalb")
    hints = list(hints)
    if hints and len(inside) > 1:
        best = min(inside, key=lambda c: min(geo.haversine_km(c["lat"], c["lon"], h["lat"], h["lon"]) for h in hints))
        return best, 0.85
    if len(inside) == 1:
        return inside[0], 0.9 if len(cands) == 1 else 0.75   # Namensvetter außerhalb des Radius: weniger sicher
    return min(inside, key=_dist), 0.6


def locate_dateline(dateline: str) -> Place | None:
    """Datumszeile einer Pressemeldung ("Prüm", "Steinebrück/Wittlich", "Trier-Mitte")."""
    by_name, _ = _load()
    parts = [p for p in re.split(r"[/,]|\s+-\s+", dateline or "") if p.strip()]
    found = [(p.strip(), by_name.get(_norm(p))) for p in parts]
    found = [(p, c) for p, c in found if c]
    if not found:   # "Trier-Mitte", "Bitburg Land": erst der Teil vor dem Bindestrich oder Leerzeichen
        sub = [t for t in re.split(r"[-\s]+", dateline or "") if len(t) >= 4][:1]
        found = [(t, by_name.get(_norm(t))) for t in sub]
        found = [(t, c) for t, c in found if c]
    if not found:
        return None
    first, cands = found[0]
    hints = [h for _, c in found[1:] for h in c if _inside(h)]
    try:
        o, conf = _pick(cands, hints)
        if hints and min(geo.haversine_km(o["lat"], o["lon"], h["lat"], h["lon"]) for h in hints) > NEIGHBOUR_KM:
            # "A/B": A liegt weit von B, also meint die Meldung einen Ortsteil ohne eigenen Eintrag. Dann gilt B.
            o, conf = _pick(hints)
            conf = min(conf, 0.7)
    except LookupError:
        if not hints:
            return None
        o, conf = _pick(hints)
        conf = min(conf, 0.7)
    return Place(o["n"], o["lat"], o["lon"], conf, o["k"])


def locate_text(text: str) -> Place | None:
    """Erster tragfähiger Ortsname in einer Schlagzeile. Längster Name zuerst, größerer Ort vor kleinerem."""
    by_name, pat = _load()
    if not pat or not text:
        return None
    hits: list[tuple[int, int, dict, float]] = []
    for m in pat.finditer(text):
        cands = [o for o in by_name.get(_norm(m.group(1)), []) if o["k"] <= 4]
        try:
            o, conf = _pick(cands)
        except LookupError:
            continue
        hits.append((-len(m.group(1)), o["k"], o, conf))
    if not hits:
        return None
    hits.sort(key=lambda h: (h[1], h[0]))
    _, _, o, conf = hits[0]
    return Place(o["n"], o["lat"], o["lon"], min(conf, 0.7), o["k"])   # Schlagzeilen-Treffer nie über 0.7
