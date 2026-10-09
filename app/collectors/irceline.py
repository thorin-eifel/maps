"""Luftqualität der belgischen Messstationen (IRCEL-CELINE, WFS-Dienst geo.irceline.be, Ebenen `realtime:*_hmean_station`).

Quelle:     https://geo.irceline.be/wfs  (GeoServer, Ausgabe GeoJSON)
Betreiber:  IRCEL - CELINE (Belgian Interregional Environment Agency) mit den Netzen Flandern, Wallonien, Brüssel
Lizenz:     siehe sources.yaml (nach Kenntnisstand CC BY 4.0, am Primärtext nicht bestätigt)
Intervall:  1800 s (Stundenmittel)
Beispiel:   python -m app.collect --once --only irceline

Je Messgröße (PM10, PM2.5, NO2, O3) ein Abruf: Stationen in der Bounding-Box, Stundenwerte der letzten Stunden. Der Dienst liefert
ohne Zeitfilter die ganze Historie, deshalb steht der Zeitfilter in der Abfrage. -9999 heißt „kein Wert“ und wird verworfen.
Koordinaten kommen in WGS84 (lon, lat) über srsName=EPSG:4326; die Rohdaten liegen in Belgisch Lambert 72.
Der Dienst liefert keinen amtlichen Index; hier wird deshalb keiner gerechnet. Ereignisse entstehen nicht (reine Messwerte).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, geo
from ..models import Measurement, Station, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

LAYERS = {"PM10": "pm10_hmean_station", "PM2.5": "pm25_hmean_station", "NO2": "no2_hmean_station", "O3": "o3_hmean_station"}
LOOKBACK_H = 6
MISSING = -9999


def _city(ab_name: str) -> tuple[str, str]:
    """„43H201 - Liège“ → („Liège“, „43H201“). Ohne Trennstrich bleibt der Name, der Code ist leer."""
    code, sep, name = ab_name.partition(" - ")
    return (name.strip(), code.strip()) if sep else (ab_name.strip(), "")


class IrcelineCollector(Collector):
    async def collect(self) -> CollectResult:
        base = self.entry.url
        lat0, lon0, lat1, lon1 = config.BBOX
        since = (utcnow() - timedelta(hours=LOOKBACK_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cql = f"timestamp AFTER {since} AND BBOX(the_geom,{lon0},{lat0},{lon1},{lat1},'EPSG:4326')"
        stations: dict[str, dict[str, Any]] = {}
        measurements: list[Measurement] = []
        failed: list[str] = []
        for param, layer in LAYERS.items():
            try:
                raw = await self.fetch_json(base, params={
                    "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": f"realtime:{layer}",
                    "outputFormat": "application/json", "srsName": "EPSG:4326", "cql_filter": cql})
            except SourceError as exc:
                self.log.warning("%s: %s", param, exc)
                failed.append(param)
                continue
            feats = raw.get("features") if isinstance(raw, dict) else None
            if not isinstance(feats, list):
                failed.append(param)
                continue
            for f in feats:
                try:
                    p = f["properties"]
                    lon, lat = (float(c) for c in f["geometry"]["coordinates"][:2])
                    value = float(p["value"])
                    ts = datetime.fromisoformat(str(p["timestamp"]).replace("Z", "+00:00")).astimezone(timezone.utc)
                    code = str(p["ab_eoi_code"])
                except (KeyError, TypeError, ValueError, IndexError):
                    continue
                if value <= MISSING or value < 0:
                    continue
                if not geo.in_bbox(lat, lon) or geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
                    continue
                city, num = _city(str(p.get("ab_name", code)))
                stations.setdefault(code, {"name": city, "num": num, "lat": lat, "lon": lon, "network": p.get("network")})
                measurements.append(Measurement(source_id=self.entry.id, station_id=code, parameter=param, ts=ts, value=value, unit="µg/m³"))
        if not stations:
            raise SourceError("keine Station mit Werten im Radius (Dienst geändert oder gestört?)")
        names = [s["name"] for s in stations.values()]
        out = []
        for code, s in sorted(stations.items()):
            label = f"{s['name']} ({s['num']})" if names.count(s["name"]) > 1 and s["num"] else s["name"]
            out.append(Station(source_id=self.entry.id, station_id=code, name=clean_text(label, 80), lat=s["lat"], lon=s["lon"],
                               meta={"code": code, "network": s["network"]}))
        note = f"teilweise: keine Daten für {', '.join(failed)}" if failed else None
        return CollectResult(stations=out, measurements=measurements, complete=not failed, note=note)


COLLECTOR = IrcelineCollector
