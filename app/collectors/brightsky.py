"""Wetter (Bright Sky, DWD-Daten): aktuelle Werte und 48-Stunden-Vorhersage für Irrel.

Quelle:     https://api.brightsky.dev  (/current_weather, /weather)
Lizenz:     DWD GeoNutzV; siehe sources.yaml
Intervall:  900 s
Beispiel:   python -m app.collect --once --only brightsky

Aktuelle Werte gehen in die Messreihen (Station = DWD-Messstation laut `sources`-Block der Antwort),
die Vorhersage als Ganzes in den Cache. Kein Ereignis, daher writes_events=False.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config
from ..models import Measurement, Station, utcnow
from .base import Collector, CollectResult, SourceError

PARAMS = {
    "temperature": "°C",
    "relative_humidity": "%",
    "pressure_msl": "hPa",
    "wind_speed_10": "km/h",
    "wind_gust_speed_10": "km/h",
    "precipitation_60": "mm",
    "cloud_cover": "%",
    "visibility": "m",
}


class BrightSkyCollector(Collector):
    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        pos = {"lat": config.CENTER_LAT, "lon": config.CENTER_LON}
        cur = await self.fetch_json(f"{base}/current_weather", params=pos)
        if "weather" not in cur:
            raise SourceError("current_weather ohne 'weather'")
        w = cur["weather"]
        ts = datetime.fromisoformat(w["timestamp"])
        src = next((s for s in cur.get("sources", []) if s.get("id") == w.get("source_id")), None)

        stations: list[Station] = []
        measurements: list[Measurement] = []
        station_id = str(w.get("source_id"))
        if src:
            stations.append(Station(
                source_id=self.entry.id, station_id=station_id,
                name=str(src.get("station_name", station_id)).title(),
                lat=float(src["lat"]), lon=float(src["lon"]),
                meta={"dwd_station_id": src.get("dwd_station_id"), "height_m": src.get("height")},
            ))
        for key, unit in PARAMS.items():
            val = w.get(key)
            if val is None:
                continue
            measurements.append(Measurement(
                source_id=self.entry.id, station_id=station_id, parameter=key,
                ts=ts, value=float(val), unit=unit, state=w.get("condition") if key == "temperature" else None,
            ))

        hours = int(self.entry.params.get("forecast_hours", 48))
        start = utcnow().replace(minute=0, second=0, microsecond=0)
        fc = await self.fetch_json(f"{base}/weather", params={
            **pos,
            "date": start.strftime("%Y-%m-%dT%H:%M"),
            "last_date": (start + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M"),
            "tz": "UTC",
        })
        if "weather" not in fc:
            raise SourceError("weather ohne 'weather'")
        keep = ("timestamp", "temperature", "precipitation", "wind_speed", "wind_gust_speed",
                "cloud_cover", "condition", "icon", "precipitation_probability")
        hourly = [{k: r.get(k) for k in keep} for r in fc["weather"]]
        return CollectResult(
            stations=stations,
            measurements=measurements,
            cache={"forecast": {"hours": hourly, "location": {"lat": pos["lat"], "lon": pos["lon"], "name": "Irrel"}}},
            writes_events=False,
        )


COLLECTOR = BrightSkyCollector
