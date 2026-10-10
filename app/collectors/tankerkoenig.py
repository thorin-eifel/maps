"""Spritpreise in der Grenzregion (Tankerkönig, Daten der Markttransparenzstelle für Kraftstoffe).

Quelle:     https://creativecommons.tankerkoenig.de/json/list.php (Umkreissuche, höchstens 25 km je Abfrage)
Betreiber:  Tankerkönig (Dienst), Daten: Markttransparenzstelle für Kraftstoffe (Bundeskartellamt, MTS-K)
Lizenz:     CC BY 4.0, Namensnennung "Tankerkönig", Hinweis: nur Deutschland; Luxemburg ist nicht enthalten
Schlüssel:  TANKERKOENIG_API_KEY in .env (kostenlos, Registrierung auf creativecommons.tankerkoenig.de). Ohne Schlüssel meldet der Collector
            einen klaren Fehler und die Quelle steht im Register auf aktiv: false, bis der Schlüssel eingetragen ist.
Intervall:  120 s, je Lauf EIN Abfragepunkt (params.points_per_run, Standard 1). Der Betreiber begrenzt die Abfragefrequenz auf einen Request
            je Minute (creativecommons.tankerkoenig.de, gelesen 2026-10-09). Die Punkte werden reihum abgefragt; welcher dran ist, folgt aus der
            Uhrzeit (Epoche // Intervall, ohne Zustand, übersteht Neustarts). Abfragepunkte: params.points, sonst bei Polygon-Region das Gitter
            app/data/region/tank_grid.json (59 Kreise zu 25 km, tools/build_tank_grid.py; ein Umlauf dauert 59 x 2 min = knapp 2 h), sonst
            Irrel, Trier, Wittlich, Prüm, Saarburg (Umlauf 10 min). Jeder Preis trägt den Zeitstempel seines Abrufs.
Beispiel:   python -m app.collect --once --only tankerkoenig

Gespeichert werden Tankstelle (Marke, Ortsname, Koordinate), Preise für E5, E10 und Diesel als Messwerte. Straße und Hausnummer
werden nicht übernommen. Geschlossene Stationen und Preise ≤ 0 fallen weg. Der Schlüssel steht im Abfrage-Parameter und wird in
Fehlertexten maskiert. Preise sind Meldungen der Betreiber an die MTS-K, nicht die Tafel vor Ort.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from .. import config, geo
from ..region import REGION
from ..models import Measurement, Station, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

KEY_ENV = "TANKERKOENIG_API_KEY"
FUELS = ("e5", "e10", "diesel")
PLAUSIBLE = (0.5, 4.0)
# Die API liefert höchstens 25 km je Abfrage; fünf Punkte decken den deutschen Teil der Region ab (Luxemburg fehlt in der Quelle)
DEFAULT_POINTS = [{"lat": config.CENTER_LAT, "lon": config.CENTER_LON, "rad": 25},
                  {"lat": 49.7596, "lon": 6.6442, "rad": 25},   # Trier
                  {"lat": 49.9853, "lon": 6.8974, "rad": 25},   # Wittlich
                  {"lat": 50.2098, "lon": 6.4194, "rad": 25},   # Prüm
                  {"lat": 49.4400, "lon": 6.6100, "rad": 25}]   # Saarburg / Merzig


GRID_FILE = Path(__file__).resolve().parent.parent / "data" / "region" / "tank_grid.json"


def query_points(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Abfragepunkte: params.points, bei Polygon-Region das Gitter, sonst die fünf Standardpunkte."""
    if params.get("points"):
        return params["points"]
    if REGION.mode == "polygon" and GRID_FILE.exists():
        return json.loads(GRID_FILE.read_text(encoding="utf-8"))["points"]
    return DEFAULT_POINTS


def parse_list(data: Any, now) -> tuple[list[Station], list[Measurement]]:
    if not isinstance(data, dict) or not data.get("ok") or not isinstance(data.get("stations"), list):
        raise SourceError("Tankerkönig: Antwort nicht ok (" + clean_text(str((data or {}).get("message", "unbekannt")), 120) + ")")
    sts: dict[str, Station] = {}
    meas: list[Measurement] = []
    for s in data["stations"]:
        try:
            sid, lat, lon = str(s["id"]), float(s["lat"]), float(s["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if not s.get("isOpen") or not geo.in_region(lat, lon):
            continue
        got = []
        for f in FUELS:
            v = s.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and PLAUSIBLE[0] < v < PLAUSIBLE[1]:
                got.append(Measurement(source_id="tankerkoenig", station_id=sid, parameter=f, ts=now, value=round(float(v), 3), unit="€/l"))
        if not got:
            continue
        brand = clean_text(s.get("brand") or s.get("name"), 60)
        sts[sid] = Station(source_id="tankerkoenig", station_id=sid, name=brand or "Tankstelle", lat=round(lat, 5), lon=round(lon, 5),
                           meta={"ort": clean_text(s.get("place"), 60), "land": "DE"})
        meas.extend(got)
    return list(sts.values()), meas


def select_slice(points: list[dict[str, Any]], per_run: int, slot_s: int, epoch: float) -> list[dict[str, Any]]:
    """Die Punkte, die in diesem Zeitfenster dran sind (reihum, zustandslos). per_run <= 0 = alle."""
    if per_run <= 0 or per_run >= len(points):
        return points
    start = (int(epoch // max(slot_s, 1)) * per_run) % len(points)
    return [points[(start + i) % len(points)] for i in range(per_run)]


class TankerkoenigCollector(Collector):
    pause_s = 60.0   # nur relevant, wenn params.points_per_run > 1 (Betreiber: ein Request je Minute)

    async def collect(self) -> CollectResult:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise SourceError(f"{KEY_ENV} fehlt (.env, siehe .env.example; in der Desktop-App: Quellenübersicht → Zugangsdaten)")
        now = utcnow()
        stations: dict[str, Station] = {}
        meas: dict[tuple[str, str], Measurement] = {}
        allp = query_points(self.entry.params)
        points = select_slice(allp, int(self.entry.params.get("points_per_run", 1)), self.entry.intervall, time.time())
        failed = 0
        for n, p in enumerate(points):
            if n and self.pause_s:
                await asyncio.sleep(self.pause_s)
            try:
                resp = await self._request(self.entry.url, {"lat": p["lat"], "lng": p["lon"], "rad": min(int(p.get("rad", 25)), 25),
                                                            "sort": "dist", "type": "all", "apikey": key}, "application/json", False, (key,))
                assert resp is not None
                st, ms = parse_list(resp.json(), now)
            except (SourceError, ValueError) as exc:
                failed += 1
                self.log.warning("Punkt %d/%d (%.2f, %.2f): %s", n + 1, len(points), p["lat"], p["lon"], clean_text(str(exc), 160))
                continue
            stations.update({s.station_id: s for s in st})
            meas.update({(m.station_id, m.parameter): m for m in ms})
        if failed == len(points):
            raise SourceError("Tankerkönig: kein Abfragepunkt erreichbar")
        note = f"{len(stations)} Tankstellen, {len(meas)} Preise, {len(points)} von {len(allp)} Punkten"
        if failed:
            note += f" ({failed} Punkte fehlgeschlagen)"
        return CollectResult(stations=list(stations.values()), measurements=list(meas.values()), writes_events=False,
                             complete=False if len(points) < len(allp) else not failed, note=note)


COLLECTOR = TankerkoenigCollector
