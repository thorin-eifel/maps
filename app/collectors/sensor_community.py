"""Bürgersensoren (Sensor.Community): Temperatur und Feuchte, nur als Raster-Mittel.

Quelle:     https://data.sensor.community/airrohr/v1/filter/area=LAT,LON,KM&type=BME280,DHT22,SHT31
Betreiber:  Sensor.Community (Verein und Mitwirkende, früher luftdaten.info)
Lizenz:     Datenbank ODbL 1.0, Inhalte DbCL; Namensnennung „Sensor.Community“ (Bedingungen des Betreibers prüfen, siehe sources.yaml)
Intervall:  600 s (die Quelle bittet um höchstens einen Abruf je 5 Minuten und einen erkennbaren User-Agent)
Beispiel:   python -m app.collect --once --only sensor_community

Datenschutz (Projektregel „Ereignisse statt Personen“): Die Rohdaten enthalten Sensor- und Standort-Kennungen sowie
Koordinaten privater Sensoren. Nichts davon wird gespeichert. Es entsteht nur ein Raster (0,1° ≈ 7 × 11 km):
je Zelle der Median, und nur wenn mindestens MIN_SENSORS Außensensoren beitragen. Innensensoren (indoor=1) und
unplausible Werte fallen vorher weg. Die Rasterzelle bekommt als Station den Zellmittelpunkt, keine Sensor-ID.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .. import config, geo
from ..models import Measurement, Station
from .base import Collector, CollectResult, SourceError

CELL_DEG = 0.1
MIN_SENSORS = 3
TYPES = "BME280,DHT22,SHT31"
# Feuchte ab 99,5 % fällt weg: gesättigte Ausgaben sind bei DHT22-Außensensoren meist ein Feuchteschaden, keine Messung
PLAUSIBLE = {"temperature": (-35.0, 45.0), "humidity": (5.0, 99.5)}
PARAMS = {"temperature": ("temperature", "°C"), "humidity": ("relative_humidity", "%")}


def _cell(lat: float, lon: float) -> tuple[float, float]:
    """Zellmittelpunkt des 0,1°-Rasters."""
    return (round((lat // CELL_DEG) * CELL_DEG + CELL_DEG / 2, 3), round((lon // CELL_DEG) * CELL_DEG + CELL_DEG / 2, 3))


def aggregate(data: Any) -> tuple[list[Station], list[Measurement]]:
    """Reine Funktion (testbar mit Fixtures): Rohliste → Raster-Stationen und Messwerte. Keine Kennungen im Ergebnis."""
    if not isinstance(data, list):
        raise SourceError("Sensor.Community: unerwartete Antwort (keine Liste)")
    cells: dict[tuple[float, float], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    stamp: dict[tuple[float, float], datetime] = {}
    for s in data:
        if not isinstance(s, dict):
            continue
        loc = s.get("location") or {}
        if str(loc.get("indoor")) == "1":
            continue
        try:
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
            ts = datetime.strptime(str(s["timestamp"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)   # UTC laut Quelle
        except (KeyError, TypeError, ValueError):
            continue
        if not geo.in_bbox(lat, lon) or geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
            continue
        vals: dict[str, float] = {}
        for v in s.get("sensordatavalues") or []:
            name = v.get("value_type")
            if name in PLAUSIBLE:
                try:
                    x = float(v["value"])
                except (KeyError, TypeError, ValueError):
                    continue
                lo, hi = PLAUSIBLE[name]
                if lo <= x <= hi:
                    vals[name] = x
        if "temperature" not in vals:      # ohne plausible Temperatur gar nicht zählen (defekte Fühler liefern oft beides falsch)
            continue
        c = _cell(lat, lon)
        for k, x in vals.items():
            cells[c][k].append(x)
        if c not in stamp or ts > stamp[c]:
            stamp[c] = ts
    stations: list[Station] = []
    meas: list[Measurement] = []
    for (clat, clon), vals in sorted(cells.items()):
        n = len(vals["temperature"])
        if n < MIN_SENSORS:
            continue
        sid = f"raster_{clat:.2f}_{clon:.2f}"
        stations.append(Station(source_id="sensor_community", station_id=sid, name=f"Raster {clat:.2f} N, {clon:.2f} O",
                                lat=clat, lon=clon, meta={"sensoren": n, "raster_grad": CELL_DEG}))
        for k, xs in vals.items():
            if len(xs) < MIN_SENSORS:
                continue
            param, unit = PARAMS[k]
            meas.append(Measurement(source_id="sensor_community", station_id=sid, parameter=param, ts=stamp[(clat, clon)],
                                    value=round(statistics.median(xs), 1), unit=unit))
    return stations, meas


class SensorCommunityCollector(Collector):
    async def collect(self) -> CollectResult:
        url = f"{self.entry.url.rstrip('/')}/airrohr/v1/filter/area={config.CENTER_LAT:.3f},{config.CENTER_LON:.3f},{config.RADIUS_KM:g}&type={TYPES}"
        data = await self.fetch_json(url)
        stations, meas = aggregate(data)
        note = None if stations else f"keine Rasterzelle mit mindestens {MIN_SENSORS} Außensensoren"
        return CollectResult(stations=stations, measurements=meas, note=note, writes_events=False)


COLLECTOR = SensorCommunityCollector
