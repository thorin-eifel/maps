#!/usr/bin/env python3
"""Synthetischer Datenstand für Rheinland-Pfalz plus 80 km: Lasttest für Export und Frontend.

Zweck:     Das Frontend (Zellenlader, Verdichtung, Bildrate) braucht einen Datenstand in der Größe des R3-Laufs, den der Sandkasten
           nicht hat. Dieses Werkzeug füllt eine leere Datenbank mit ERFUNDENEN Ereignissen, Pegeln, Messstellen und Landmarken,
           verteilt über die Fläche mit Schwerpunkten in den Städten. Danach läuft der echte Export (`python -m app.export`).
Wichtig:   Alles hier ist Spielmaterial. Die Datenbank trägt die Meta-Zeile `synthetic=1`; nichts davon gehört auf den Webspace.
           Der Aufruf bricht ab, wenn die Zieldatenbank schon Daten enthält (kein Überschreiben echter Daten).
Aufruf:    python tools/synth_rlp.py --db /tmp/r5/synth.sqlite [--seed 7] [--scale 1.0]
           OSINT_DB_PATH=/tmp/r5/synth.sqlite OSINT_REGION=region-rlp.yaml python -m app.export --out /tmp/r5/data
Parameter: --scale   Faktor auf alle Mengen (1.0 entspricht ungefähr R3: 4.200 Ereignisse, 1.500 Stationen, 110.000 Messwerte)
Datenschutz: keine Personen, keine Adressen; Namen sind Platzhalter wie "Pegel 17".
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import random
import sys
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("OSINT_REGION", "region-rlp.yaml")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import Storage  # noqa: E402
from app.models import Event, Measurement, Station, utcnow  # noqa: E402
from app.region import REGION  # noqa: E402
from app.registry import Registry  # noqa: E402

log = logging.getLogger("osint.synth")

# Schwerpunkte (Name, Breite, Länge, Gewicht): hier ballen sich Verkehr, Messstellen und Infrastruktur
HUBS = [
    ("Mainz", 50.00, 8.27, 9), ("Wiesbaden", 50.08, 8.24, 6), ("Frankfurt", 50.11, 8.68, 12), ("Trier", 49.75, 6.64, 7),
    ("Kaiserslautern", 49.44, 7.77, 6), ("Saarbrücken", 49.23, 7.00, 8), ("Koblenz", 50.36, 7.59, 6), ("Ludwigshafen", 49.48, 8.44, 7),
    ("Mannheim", 49.49, 8.47, 6), ("Luxemburg", 49.61, 6.13, 7), ("Bitburg", 49.98, 6.53, 2), ("Idar-Oberstein", 49.71, 7.31, 2),
    ("Bad Kreuznach", 49.84, 7.87, 3), ("Worms", 49.63, 8.36, 3), ("Speyer", 49.32, 8.43, 3), ("Landau", 49.20, 8.12, 2),
    ("Pirmasens", 49.20, 7.60, 2), ("Neuwied", 50.43, 7.46, 3), ("Cochem", 50.15, 7.17, 1), ("Wittlich", 49.99, 6.89, 2),
    ("Metz", 49.12, 6.18, 4), ("Karlsruhe", 49.01, 8.40, 4), ("Darmstadt", 49.87, 8.65, 4), ("Bonn", 50.74, 7.10, 3),
    ("Aachen", 50.78, 6.08, 3), ("Gießen", 50.58, 8.68, 3), ("Heidelberg", 49.40, 8.69, 3), ("Prüm", 50.21, 6.42, 1),
]
# Bundesautobahnen als grobe Linienzüge (Länge, Breite): nur Form für Lastzwecke, keine Abbildung der Wirklichkeit
ROADS = [
    [(6.5, 49.7), (7.0, 49.8), (7.6, 50.0), (8.27, 50.0)], [(6.13, 49.61), (6.64, 49.75), (7.2, 50.3)],
    [(7.0, 49.23), (7.77, 49.44), (8.44, 49.48)], [(8.27, 50.0), (8.68, 50.11), (9.2, 50.2)], [(7.59, 50.36), (8.0, 50.1), (8.27, 50.0)],
    [(8.36, 49.63), (8.44, 49.48), (8.4, 49.0)], [(6.9, 50.6), (7.4, 50.4), (7.59, 50.36)],
]
WATERS = ["Rhein", "Mosel", "Nahe", "Lahn", "Saar", "Main", "Neckar", "Sauer", "Our", "Prüm", "Kyll", "Ahr", "Lauter", "Queich", "Alsenz", "Glan", "Wied", "Sieg"]
LANDMARK_KINDS = ["cave", "waterfall", "viewpoint", "spring", "rock", "volcano", "castle", "ruins", "archaeological", "monastery", "building"]
INFRA_KINDS = ["wind", "charging", "aed", "fire_station", "hospital", "weir", "lock", "bridge", "tunnel", "ferry", "picnic", "shelter", "bathing", "school", "townhall", "cemetery", "church", "chapel", "cross"]


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.weights = [h[3] for h in HUBS]

    def point(self, spread_km: float = 14.0, hub_share: float = 0.7) -> tuple[float, float]:
        """Punkt in der Region: meist um einen Schwerpunkt gestreut, sonst gleichmäßig im Rechteck (und dann gefiltert)."""
        for _ in range(200):
            if self.r.random() < hub_share:
                _, la, lo, _ = self.r.choices(HUBS, self.weights)[0]
                d, b = abs(self.r.gauss(0, spread_km)), self.r.uniform(0, 2 * math.pi)
                lat, lon = la + d * math.cos(b) / 111.2, lo + d * math.sin(b) / (111.2 * math.cos(math.radians(la)))
            else:
                lat, lon = self.r.uniform(48.5, 51.5), self.r.uniform(5.3, 9.5)
            if REGION.contains(lat, lon):
                return round(lat, 5), round(lon, 5)
        return 49.846, 6.456

    def line(self, km: float = 4.0, n: int = 4) -> list[list[float]]:
        lat, lon = self.point()
        b = self.r.uniform(0, 2 * math.pi)
        out = [[lon, lat]]
        for _ in range(n - 1):
            b += self.r.gauss(0, 0.3)
            lat += km / n * math.cos(b) / 111.2
            lon += km / n * math.sin(b) / (111.2 * math.cos(math.radians(lat)))
            out.append([round(lon, 5), round(lat, 5)])
        return out

    def ring(self, km: float) -> list[list[float]]:
        lat, lon = self.point(spread_km=30.0, hub_share=0.4)
        k = self.r.randint(8, 14)
        pts = []
        for i in range(k):
            a = 2 * math.pi * i / k
            rr = km * self.r.uniform(0.6, 1.2)
            pts.append([round(lon + rr * math.sin(a) / (111.2 * math.cos(math.radians(lat))), 5), round(lat + rr * math.cos(a) / 111.2, 5)])
        pts.append(pts[0])
        return pts


def build(db: Path, seed: int, scale: float) -> dict[str, int]:
    g, r = Gen(seed), random.Random(seed + 1)
    storage = Storage(db)
    if storage._query("SELECT 1 FROM events LIMIT 1") or storage._query("SELECT 1 FROM stations LIMIT 1"):  # noqa: SLF001
        raise SystemExit("Zieldatenbank enthält schon Daten, Abbruch (kein Überschreiben)")
    reg = Registry.load(Path(__file__).resolve().parent.parent / "sources.yaml")
    now = utcnow()
    n = lambda k: max(1, int(k * scale))  # noqa: E731

    def ev(src: str, typ: str, i: int, geom: dict, sev: str, title: str, attrs: dict | None = None, hours: float = 12) -> Event:
        return Event(id=f"{src}:{i}", source_id=src, type=typ, title=title, summary=f"Synthetischer Eintrag {i}", severity=sev, geometry=geom,
                     region_tag="DE-RLP", valid_from=now - timedelta(hours=r.uniform(0, 6)), valid_to=now + timedelta(hours=r.uniform(1, hours)),
                     fetched_at=now, attrs=attrs or {})

    sev = lambda: r.choices(["info", "notice", "warning", "critical"], [60, 25, 12, 3])[0]  # noqa: E731
    counts: dict[str, int] = {}
    # Verkehr: Baustellen (Punkte, Linien), Staus, Sperrungen
    groups: dict[str, list[Event]] = {"lbm_baustellen": [], "autobahn": [], "nina": [], "dwd_warnungen": [], "hochwasser_rlp": []}
    for i in range(n(2400)):
        lat, lon = g.point()
        if r.random() < 0.45:
            geom = {"type": "LineString", "coordinates": g.line(r.uniform(0.5, 6), 4)}
        else:
            geom = {"type": "Point", "coordinates": [lon, lat]}
        groups["lbm_baustellen"].append(ev("lbm_baustellen", "traffic", i, geom, r.choices(["info", "notice", "warning"], [70, 25, 5])[0], f"Baustelle {i}", {"kind": "baustelle"}, 200))
    for i in range(n(500)):
        road = r.choice(ROADS)
        a = r.randint(0, len(road) - 2)
        t = r.random()
        lon, lat = road[a][0] + (road[a + 1][0] - road[a][0]) * t, road[a][1] + (road[a + 1][1] - road[a][1]) * t
        if r.random() < 0.5:
            geom = {"type": "LineString", "coordinates": [[round(lon, 5), round(lat, 5)], [round(lon + 0.05, 5), round(lat + 0.02, 5)]]}
            groups["autobahn"].append(ev("autobahn", "congestion", i, geom, sev(), f"Stau {i}", {"kind": "stau"}, 4))
        else:
            groups["autobahn"].append(ev("autobahn", "traffic", i, {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}, sev(), f"Sperrung {i}", {"kind": "sperrung"}, 30))
    for i in range(n(400)):   # Warnungen als Flächen (Kreise bis Gemeinden)
        groups["nina"].append(ev("nina", "warning", i, {"type": "Polygon", "coordinates": [g.ring(r.choice([4, 8, 15, 25]))]}, r.choices(["notice", "warning", "critical"], [50, 40, 10])[0], f"Warnung {i}", {}, 24))
    for i in range(n(150)):
        groups["dwd_warnungen"].append(ev("dwd_warnungen", "weather", i, {"type": "Polygon", "coordinates": [g.ring(r.choice([20, 35, 50]))]}, r.choices(["notice", "warning", "critical"], [60, 35, 5])[0], f"Unwetter {i}", {}, 12))
    for i in range(n(160)):
        lat, lon = g.point(spread_km=25.0, hub_share=0.3)
        groups["hochwasser_rlp"].append(ev("hochwasser_rlp", "flood", i, {"type": "Point", "coordinates": [lon, lat]}, r.choices(["info", "notice", "warning", "critical"], [50, 30, 15, 5])[0], f"Hochwasser {i}", {}, 48))
    for sid, evs in groups.items():
        storage.replace_snapshot(sid, evs)
        counts[f"events:{sid}"] = len(evs)

    # Pegel
    for sid, k in (("pegelonline", 125), ("hochwasser_rlp", 240), ("lu_pegel", 40), ("hubeau_pegel", 60)):
        sts, rows = [], []
        for i in range(n(k)):
            lat, lon = g.point(spread_km=22.0, hub_share=0.5)
            water = r.choice(WATERS)
            sts.append(Station(source_id=sid, station_id=f"{sid}-{i}", name=f"Pegel {i}", water=water, km=round(r.uniform(0, 400), 1), lat=lat, lon=lon, meta={"operator": "Synthetisch"}))
            base = r.uniform(60, 400)
            for h in range(48):
                rows.append(Measurement(source_id=sid, station_id=f"{sid}-{i}", parameter="W", ts=now - timedelta(hours=47 - h), value=round(base + 12 * math.sin(h / 7) + r.gauss(0, 2), 1), unit="cm", state=r.choice(["normal", "normal", "high"])))
        storage.upsert_stations(sts)
        storage.add_measurements(rows)
        counts[f"stations:{sid}"] = len(sts)

    # Umwelt: Strahlung, Luft, Wetter
    for sid, par, unit, lo, hi, k in (("bfs_odl", "odl", "µSv/h", 0.06, 0.14, 180), ("uba_luft", "NO2", "µg/m³", 5, 60, 70), ("dwd_stationen", "temperature", "°C", 4, 22, 150)):
        sts, rows = [], []
        for i in range(n(k)):
            lat, lon = g.point(spread_km=20.0, hub_share=0.5)
            sts.append(Station(source_id=sid, station_id=f"{sid}-{i}", name=f"Messstelle {i}", lat=lat, lon=lon, meta={}))
            for h in range(24):
                rows.append(Measurement(source_id=sid, station_id=f"{sid}-{i}", parameter=par, ts=now - timedelta(hours=23 - h, minutes=r.randint(0, 20)), value=round(r.uniform(lo, hi), 3), unit=unit))
        storage.upsert_stations(sts)
        storage.add_measurements(rows)
        counts[f"stations:{sid}"] = len(sts)

    # Tankstellen
    sts, rows = [], []
    for i in range(n(260)):
        lat, lon = g.point(spread_km=12.0, hub_share=0.85)
        sts.append(Station(source_id="tankerkoenig", station_id=f"tk-{i}", name=f"Tankstelle {i}", lat=lat, lon=lon, meta={"ort": "Ort"}))
        for code, base in (("e5", 1.85), ("e10", 1.79), ("diesel", 1.69)):
            rows.append(Measurement(source_id="tankerkoenig", station_id=f"tk-{i}", parameter=code, ts=now - timedelta(minutes=r.randint(1, 90)), value=round(base + r.uniform(-0.1, 0.15), 3), unit="EUR"))
    storage.upsert_stations(sts)
    storage.add_measurements(rows)
    counts["stations:tankerkoenig"] = len(sts)

    # Zwischenspeicher: Landmarken, Infrastruktur, Haltestellen, Routen, Anbau
    pts = lambda kinds, k, extra=None: [{"id": f"s{i}", "kind": r.choice(kinds), "name": r.choice(["", f"Ort {i}"]), "lat": (p := g.point(spread_km=25.0, hub_share=0.35))[0], "lon": p[1], **(extra(i) if extra else {})} for i in range(k)]  # noqa: E731
    storage.cache_put("landmarks", "osm_natur", {"items": pts(LANDMARK_KINDS, n(3500), lambda i: {"ele": r.randint(100, 800)})})
    storage.cache_put("infrastruktur", "osm_infra", {"items": pts(INFRA_KINDS, n(9000))})
    stops = {f"h{i}": [f"Halt {i}", (p := g.point(spread_km=18.0, hub_share=0.6))[0], p[1], ["rail"]] for i in range(n(1200))}
    storage.cache_put("gtfs_index", "gtfs_static", {"feeds": {"synthetisch": {"region": "DE", "stops": stops}}})
    routes = [{"kind": r.choice(["hike", "bike"]), "name": f"Route {i}", "ref": str(i), "network": "rwn", "lines": [g.line(r.uniform(8, 40), 12) for _ in range(r.randint(1, 3))]} for i in range(n(220))]
    storage.cache_put("routen", "osm_routen", {"items": routes})
    storage.cache_put("anbau", "osm_anbau", {"items": [{"id": f"a{i}", "kind": r.choice(["vineyard", "orchard"]), "ring": g.ring(r.uniform(0.2, 1.2))} for i in range(n(900))]})
    counts["landmarks"], counts["infrastruktur"], counts["haltestellen"], counts["routen"], counts["anbau"] = n(3500), n(9000), len(stops), len(routes), n(900)

    # Quellenzustand: alle aktiven Quellen als erfolgreich abgerufen
    for e in reg.entries:
        if e.aktiv:
            storage.record_run(e.id, now, 800, True, n_new=1, n_seen=1)
    storage._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('synthetic', '1')")  # noqa: SLF001
    storage._conn.commit()  # noqa: SLF001
    storage.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    counts = build(a.db, a.seed, a.scale)
    for k, v in counts.items():
        log.info("%-28s %6d", k, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
