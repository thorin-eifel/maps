"""Spritpreise in der Grenzregion (Tankerkönig, Daten der Markttransparenzstelle für Kraftstoffe).

Quelle:     https://creativecommons.tankerkoenig.de/json/list.php (Umkreissuche, höchstens 25 km je Abfrage)
Betreiber:  Tankerkönig (Dienst), Daten: Markttransparenzstelle für Kraftstoffe (Bundeskartellamt, MTS-K)
Lizenz:     CC BY 4.0, Namensnennung "Tankerkönig", Hinweis: nur Deutschland; Luxemburg ist nicht enthalten
Schlüssel:  TANKERKOENIG_API_KEY in .env (kostenlos, Registrierung auf creativecommons.tankerkoenig.de). Ohne Schlüssel meldet der Collector
            einen klaren Fehler und die Quelle steht im Register auf aktiv: false, bis der Schlüssel eingetragen ist.
Intervall:  900 s; Abfragepunkte aus params.points (Standard: Irrel, Trier, Wittlich, Prüm, Saarburg, je 25 km), also fünf Abrufe je Lauf
Beispiel:   python -m app.collect --once --only tankerkoenig

Gespeichert werden Tankstelle (Marke, Ortsname, Koordinate), Preise für E5, E10 und Diesel als Messwerte. Straße und Hausnummer
werden nicht übernommen. Geschlossene Stationen und Preise ≤ 0 fallen weg. Der Schlüssel steht im Abfrage-Parameter und wird in
Fehlertexten maskiert. Preise sind Meldungen der Betreiber an die MTS-K, nicht die Tafel vor Ort.
"""
from __future__ import annotations

import os
from typing import Any

from .. import config, geo
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
        if not s.get("isOpen") or not geo.in_bbox(lat, lon) or geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
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


class TankerkoenigCollector(Collector):
    async def collect(self) -> CollectResult:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise SourceError(f"{KEY_ENV} fehlt (.env, siehe .env.example)")
        now = utcnow()
        stations: dict[str, Station] = {}
        meas: dict[tuple[str, str], Measurement] = {}
        for p in self.entry.params.get("points") or DEFAULT_POINTS:
            resp = await self._request(self.entry.url, {"lat": p["lat"], "lng": p["lon"], "rad": min(int(p.get("rad", 25)), 25),
                                                        "sort": "dist", "type": "all", "apikey": key}, "application/json", False, (key,))
            assert resp is not None
            try:
                st, ms = parse_list(resp.json(), now)
            except ValueError as exc:
                raise SourceError("Tankerkönig: kein gültiges JSON") from exc
            stations.update({s.station_id: s for s in st})
            meas.update({(m.station_id, m.parameter): m for m in ms})
        return CollectResult(stations=list(stations.values()), measurements=list(meas.values()), writes_events=False,
                             note=f"{len(stations)} Tankstellen, {len(meas)} Preise")


COLLECTOR = TankerkoenigCollector
