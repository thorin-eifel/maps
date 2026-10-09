"""Suchindex: ein Verzeichnis benannter Orte, Straßen, Gewässer und Einrichtungen für die Suchleiste der Karte.

Zweck:    Die Suche läuft vollständig im Browser, ohne Dienst von Dritten. Dieses Modul baut den Datenteil:
          - dynamischer Teil (Einrichtungen, Landmarken, Haltestellen, Routen, Pegel): payloads.suche_payload, geschrieben von
            app.export als web/data/suche.json (ändert sich mit den Collectorläufen)
          - statischer Teil (Orte, Straßen, Gewässer, Gelände aus den Kartenkacheln): tools/build_search_index.py schreibt
            web/data/suche_geo.json mit denselben Hilfen (Faltung, Ortszuordnung, Clustern)
Format:   {"v": 1, "t": [Typbezeichnungen], "o": [Ortsnamen], "e": [[Name, Typ, Breite*1e4, Länge*1e4, Ort-Index oder -1], ...]}
Datenschutz: Es werden nur Namen öffentlicher Orte, Straßen und Einrichtungen geführt: keine Hausnummern, keine Adressen,
          keine Namen von Personen, keine Konten. Friedhöfe und Mühlen fehlen mit Absicht (kein Name gespeichert).
Beispiel: from app.search import fold; fold("Straße der Überlegung") -> "strasse der uberlegung"
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from . import config, geo

DATA = Path(__file__).resolve().parent / "data" / "orte.json"
# Typen in Anzeigereihenfolge; der Index ist Teil des Dateiformats (nur anhängen, nie umsortieren)
TYPES = ["Stadt", "Ort", "Ortsteil", "Weiler", "Straße", "Gewässer", "Landmarke", "Haltestelle", "Schule", "Rathaus",
         "Krankenhaus", "Feuerwache", "Kirche", "Kapelle", "Brücke", "Tunnel", "Wehr", "Schleuse", "Fähre", "Badestelle",
         "Windpark", "Wanderweg", "Radroute", "Pegel", "Fluss", "Bach", "See", "Burg", "Aussicht", "Quelle", "Höhle", "Ruine",
         "Wasserfall", "Fels", "Kloster", "Vulkan", "Gipfel", "Ausgrabung", "Historisches Gebäude", "Gelände", "Wald", "Naturschutzgebiet", "Park", "Sehenswürdigkeit", "Museum", "Freizeit",
         "Campingplatz", "Flugplatz", "Steinbruch", "Gemeinde"]
T = {name: i for i, name in enumerate(TYPES)}
INFRA_TYPE = {"church": "Kirche", "chapel": "Kapelle", "hospital": "Krankenhaus", "fire_station": "Feuerwache", "school": "Schule",
              "townhall": "Rathaus", "bridge": "Brücke", "tunnel": "Tunnel", "weir": "Wehr", "lock": "Schleuse", "ferry": "Fähre",
              "bathing": "Badestelle", "wind": "Windpark"}
LANDMARK_WORD = {"viewpoint": "Aussicht", "castle": "Burg", "spring": "Quelle", "cave": "Höhle", "archaeological": "Ausgrabung",
                 "building": "Historisches Gebäude", "ruins": "Ruine", "rock": "Fels", "waterfall": "Wasserfall", "monastery": "Kloster",
                 "volcano": "Vulkan", "peak": "Gipfel"}
RANK_TYPE = {1: "Stadt", 2: "Stadt", 3: "Ort", 4: "Ortsteil", 5: "Weiler"}
_QUOTES = re.compile(r"[\"„“”«»]")


def fold(text: str) -> str:
    """Suchform: klein, ohne Akzente, ä/ö/ü zu a/o/u, ß zu ss, Satzzeichen zu Leerzeichen."""
    s = text.casefold().replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^0-9a-z]+", " ", s)
    return s.strip()


def clean_name(raw: Any, limit: int = 80) -> str:
    """Name säubern: Anführungszeichen und Steuerzeichen raus, Leerraum glätten, kürzen."""
    s = _QUOTES.sub("", str(raw or ""))
    s = re.sub(r"[\x00-\x1f\x7f<>]", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:limit]


def load_places(path: Path = DATA) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


class PlaceIndex:
    """Nächster Ort zu einem Punkt (Gitter, 0,1°-Zellen), für den Zusatz „Straße · Ort“."""

    def __init__(self, places: Iterable[dict[str, Any]], max_km: float = 6.0) -> None:
        self.max_km = max_km
        self.grid: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for p in places:
            self.grid[(int(p["lat"] * 10), int(p["lon"] * 10))].append(p)

    def nearest(self, lat: float, lon: float) -> str:
        ci, cj = int(lat * 10), int(lon * 10)
        best, best_d = "", self.max_km
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for p in self.grid.get((ci + di, cj + dj), ()):
                    d = geo.haversine_km(lat, lon, p["lat"], p["lon"])
                    if d < best_d:
                        best, best_d = p["n"], d
        return best


def cluster(points: list[tuple[float, float]], radius_km: float) -> list[list[int]]:
    """Punkte (lat, lon), die über Ketten von höchstens radius_km Abstand zusammenhängen, bilden eine Gruppe (Indexlisten)."""
    cell = radius_km / 111.0
    parent = list(range(len(points)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (lat, lon) in enumerate(points):
        ci, cj = int(lat / cell), int(lon / (cell / max(0.2, math.cos(math.radians(lat)))))
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for j in grid.get((ci + di, cj + dj), ()):
                    if geo.haversine_km(lat, lon, points[j][0], points[j][1]) <= radius_km:
                        parent[find(i)] = find(j)
        grid[(ci, cj)].append(i)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(points)):
        groups[find(i)].append(i)
    return list(groups.values())


def medoid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Der Punkt der Gruppe, der dem Mittelwert am nächsten liegt (liegt sicher auf dem Objekt, nicht daneben)."""
    mlat = sum(p[0] for p in points) / len(points)
    mlon = sum(p[1] for p in points) / len(points)
    return min(points, key=lambda p: (p[0] - mlat) ** 2 + ((p[1] - mlon) * math.cos(math.radians(mlat))) ** 2)


class Builder:
    """Sammelt Einträge, dedupliziert (Name, Typ, 100-m-Raster) und liefert das Dateiformat."""

    def __init__(self, places: PlaceIndex | None = None) -> None:
        self.places = places
        self.ort_ix: dict[str, int] = {}
        self.orte: list[str] = []
        self.entries: dict[tuple[str, int, int, int], list[Any]] = {}

    def add(self, name: str, typ: str, lat: float, lon: float, ort: str | None = None) -> bool:
        name = clean_name(name)
        if len(name) < 2 or not re.search(r"[^\W\d_]{2}", name) or typ not in T or not geo.in_bbox(lat, lon):
            return False
        if geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
            return False
        if ort is None and self.places is not None and typ not in ("Stadt", "Ort", "Ortsteil", "Weiler"):
            ort = self.places.nearest(lat, lon)
        ort = clean_name(ort or "", 60)
        if ort == name:
            ort = ""
        key = (fold(name), T[typ], round(lat * 1000), round(lon * 1000))
        if key in self.entries:
            return False
        ix = -1
        if ort:
            ix = self.ort_ix.setdefault(ort, len(self.orte))
            if ix == len(self.orte):
                self.orte.append(ort)
        self.entries[key] = [name, T[typ], round(lat * 1e4), round(lon * 1e4), ix]
        return True

    def payload(self, **extra: Any) -> dict[str, Any]:
        rows = sorted(self.entries.values(), key=lambda e: (e[1], fold(e[0]), e[2], e[3]))
        return {"v": 1, "t": TYPES, "o": self.orte, "e": rows, **extra}


def dynamic_entries(builder: Builder, *, infra: Iterable[dict[str, Any]], landmarks: Iterable[dict[str, Any]], stops: Iterable[dict[str, Any]],
                    routes: Iterable[dict[str, Any]], stations: Iterable[dict[str, Any]]) -> None:
    """Einrichtungen, Landmarken, Haltestellen, Routen und Pegel in den Builder (Namen werden gesäubert, Personenbezug gibt es dort nicht)."""
    for i in infra:
        typ = INFRA_TYPE.get(i.get("kind", ""))
        if typ and i.get("name"):
            builder.add(i["name"], typ, i["lat"], i["lon"])
    for m in landmarks:
        name = clean_name(m.get("name"))
        if name:
            builder.add(name, LANDMARK_WORD.get(m.get("kind", ""), "Landmarke"), m["lat"], m["lon"])
    for s in stops:
        if s.get("name"):
            builder.add(s["name"], "Haltestelle", s["lat"], s["lon"])
    for r in routes:
        lines = r.get("lines") or []
        pts = [p for ln in lines for p in ln]
        if not r.get("name") or not pts:
            continue
        lon, lat = pts[len(pts) // 2][:2]
        label = r["name"] if not r.get("ref") or r["ref"] in r["name"] else f"{r['name']} ({r['ref']})"
        builder.add(label, "Radroute" if r.get("kind") == "bike" else "Wanderweg", lat, lon)
    for st in stations:
        if st.get("name") and st.get("lat") is not None and st.get("lon") is not None:
            builder.add(st["name"], "Pegel", st["lat"], st["lon"])
