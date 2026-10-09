"""Wetterstationen des DWD im Radius (Bright Sky, Stundenwerte der SYNOP-Stationen).

Quelle:     https://api.brightsky.dev  (/sources zur Stationssuche, /current_weather?dwd_station_id=… je Station)
Betreiber:  Deutscher Wetterdienst (Daten), Bright Sky (Aufbereitung)
Lizenz:     DWD GeoNutzV; siehe sources.yaml
Intervall:  1800 s (die Stationen melden stündlich)
Beispiel:   python -m app.collect --once --only dwd_stationen

Die Stationsliste (nur Stationen mit SYNOP-Meldung der letzten Stunden, ohne reine Klima- und Vorhersagepunkte) wird einmal am Tag
neu geholt und im Cache gehalten; der Lauf selbst fragt je Station einen Abruf mit kleiner Pause, höchstens `max_stations`.
Ausfall einzelner Stationen stoppt den Lauf nicht. Gespeichert werden Messwerte je Station, keine Personendaten.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, geo
from ..models import Measurement, Station, utcnow
from .base import Collector, CollectResult, SourceError
from .brightsky import PARAMS

PAUSE_S = 0.25
LIST_MAX_AGE = timedelta(hours=24)
RECENT = timedelta(hours=12)       # SYNOP-Meldung nicht älter als das, sonst gilt die Station als stumm


def pick_stations(sources: list[dict[str, Any]], now: datetime, limit: int) -> list[dict[str, Any]]:
    """Bright-Sky-Quellenliste → nächste SYNOP-Stationen im Radius, je DWD-Kennung eine. Reine Funktion."""
    best: dict[str, dict[str, Any]] = {}
    for s in sources:
        sid, lat, lon = s.get("dwd_station_id"), s.get("lat"), s.get("lon")
        if s.get("observation_type") != "synop" or not sid or lat is None or lon is None:
            continue
        try:
            last = datetime.fromisoformat(str(s.get("last_record")))
        except ValueError:
            continue
        if now - last > RECENT:
            continue
        d = geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, float(lat), float(lon))
        if d > config.RADIUS_KM:
            continue
        cur = best.get(str(sid))
        if cur is None or d < cur["distance_km"]:
            best[str(sid)] = {"id": str(sid), "name": str(s.get("station_name") or sid), "lat": float(lat), "lon": float(lon),
                              "height": s.get("height"), "distance_km": round(d, 1)}
    return sorted(best.values(), key=lambda x: x["distance_km"])[:limit]


class DwdStationenCollector(Collector):
    async def _station_list(self, base: str, now: datetime, limit: int) -> list[dict[str, Any]]:
        row = self.storage.cache_get("dwd_station_list")
        if row and isinstance(row.get("payload"), dict):
            try:
                fetched = datetime.fromisoformat(str(row["fetched_at"]).replace("Z", "+00:00"))
                if now - fetched < LIST_MAX_AGE and row["payload"].get("stations"):
                    return row["payload"]["stations"]
            except ValueError:
                pass
        data = await self.fetch_json(f"{base}/sources", params={"lat": config.CENTER_LAT, "lon": config.CENTER_LON,
                                                               "max_dist": int(config.RADIUS_KM * 1000)})
        if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
            raise SourceError("Bright Sky /sources: unerwartete Antwort")
        stations = pick_stations(data["sources"], now, limit)
        if not stations:
            raise SourceError("Bright Sky /sources: keine SYNOP-Stationen im Radius")
        self._fresh_list = stations
        return stations

    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        limit = int(self.entry.params.get("max_stations", 60))
        now = utcnow()
        self._fresh_list: list[dict[str, Any]] | None = None
        listing = await self._station_list(base, now, limit)
        stations: list[Station] = []
        measurements: list[Measurement] = []
        failed = 0
        for n, st in enumerate(listing):
            if n:
                await asyncio.sleep(PAUSE_S)
            try:
                cur = await self.fetch_json(f"{base}/current_weather", params={"dwd_station_id": st["id"], "max_dist": 0})
                w = cur["weather"]
                ts = datetime.fromisoformat(w["timestamp"])
            except (SourceError, KeyError, TypeError, ValueError) as exc:
                failed += 1
                self.log.warning("Station %s (%s): %s", st["id"], st["name"], exc)
                continue
            if now - ts.astimezone(timezone.utc) > RECENT:
                continue   # alter Wert: besser keine Karte als ein veralteter Punkt
            got = 0
            for key, unit in PARAMS.items():
                val = w.get(key)
                if val is None:
                    continue
                got += 1
                measurements.append(Measurement(source_id=self.entry.id, station_id=st["id"], parameter=key, ts=ts, value=float(val), unit=unit,
                                                state=w.get("condition") if key == "temperature" else None))
            if got:
                stations.append(Station(source_id=self.entry.id, station_id=st["id"], name=st["name"].title(), lat=st["lat"], lon=st["lon"],
                                        meta={"dwd_station_id": st["id"], "height_m": st.get("height")}))
        if not stations:
            raise SourceError(f"keine Messwerte von {len(listing)} Stationen ({failed} Fehler)")
        note = f"teilweise: {failed} von {len(listing)} Stationen ohne Antwort" if failed else None
        cache = {"dwd_station_list": {"stations": self._fresh_list}} if self._fresh_list else {}
        return CollectResult(stations=stations, measurements=measurements, cache=cache, complete=not failed, note=note, writes_events=False)


COLLECTOR = DwdStationenCollector
