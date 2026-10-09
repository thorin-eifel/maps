"""Wetter Luxemburg (MeteoLux, Station Findel): Minutenwerte der Flughafenstation.

Quelle:     https://metapi.ana.lu/api/v1/hvd/observations  (+ /hvd/stations für Name und Lage)
Betreiber:  Administration de la navigation aérienne (ANA) / MeteoLux
Lizenz:     CC0 1.0 (laut API-Beschreibung und Portal data.public.lu), keine Namensnennung nötig, wir nennen sie trotzdem
Intervall:  600 s (Quelle liefert Minutenwerte; für die Kachel genügt das)
Beispiel:   python -m app.collect --once --only meteolux

Ein Abruf liefert eine flache Liste {id, value}; der Zeitstempel steht im Kopf (`timestamp`, UTC). Wir übernehmen nur
Temperatur, Feuchte, Luftdruck (auf Meereshöhe), Wind (Mittel der Bahnmitte, 10 m) und Böen. Windgeschwindigkeit
kommt in m/s und wird auf km/h umgerechnet, damit sie zu Bright Sky passt. Fehlende Werte (null) fallen weg.
Reine Messwerte, keine Ereignisse, kein Personenbezug.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import geo
from ..models import Measurement, Station
from .base import Collector, CollectResult, SourceError

# Quell-ID → (Parameter wie bei brightsky, Einheit, Faktor)
FIELDS: dict[str, tuple[str, str, float]] = {
    "st": ("temperature", "°C", 1.0),
    "su": ("relative_humidity", "%", 1.0),
    "spsl": ("pressure_msl", "hPa", 1.0),
    "s2ff_rwymd0": ("wind_speed_10", "km/h", 3.6),
    "s2ffgust_rwymd0": ("wind_gust_speed_10", "km/h", 3.6),
}
PLAUSIBLE = {"temperature": (-40, 50), "relative_humidity": (0, 100), "pressure_msl": (900, 1090),
             "wind_speed_10": (0, 250), "wind_gust_speed_10": (0, 300)}


def parse_observations(obs: Any, stations: Any) -> tuple[Station, list[Measurement]]:
    """Reine Funktion (testbar mit Fixtures): API-Antworten → Station und Messwerte."""
    if not isinstance(obs, dict) or not isinstance(obs.get("data"), list) or "timestamp" not in obs:
        raise SourceError("MeteoLux: unerwartete Antwort (data/timestamp fehlt)")
    if not isinstance(stations, dict) or not stations.get("data"):
        raise SourceError("MeteoLux: keine Stationsdaten")
    s = stations["data"][0]
    try:
        lon, lat = float(s["location"][0]), float(s["location"][1])   # GeoJSON-Reihenfolge lon,lat
        sid = str(s["id"])
        name = str(s.get("shortName") or s.get("name") or sid)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise SourceError(f"MeteoLux: Stationsschema geändert ({exc})") from exc
    ts = datetime.fromisoformat(str(obs["timestamp"]).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    station = Station(source_id="meteolux", station_id=sid, name=name, lat=lat, lon=lon,
                      meta={"wmo": s.get("wmoid"), "icao": s.get("icaoCode"), "height_m": s.get("masl")})
    values = {x.get("id"): x.get("value") for x in obs["data"] if isinstance(x, dict)}
    out: list[Measurement] = []
    for key, (param, unit, factor) in FIELDS.items():
        v = values.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        val = round(float(v) * factor, 1)
        lo, hi = PLAUSIBLE[param]
        if not lo <= val <= hi:
            continue
        out.append(Measurement(source_id="meteolux", station_id=sid, parameter=param, ts=ts, value=val, unit=unit))
    if not out:
        raise SourceError("MeteoLux: keine verwertbaren Messwerte")
    return station, out


class MeteoLuxCollector(Collector):
    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        obs = await self.fetch_json(f"{base}/hvd/observations")
        stations = await self.fetch_json(f"{base}/hvd/stations")
        station, measurements = parse_observations(obs, stations)
        if not geo.in_bbox(station.lat, station.lon) or not geo.geometry_in_region(
                {"type": "Point", "coordinates": [station.lon, station.lat]}):
            return CollectResult(note="Station liegt außerhalb der Region", writes_events=False)
        return CollectResult(stations=[station], measurements=measurements, writes_events=False)


COLLECTOR = MeteoLuxCollector
