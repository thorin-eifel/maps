"""Wetterstationen des belgischen Wetterdienstes KMI/IRM im Radius (SYNOP-Stundenwerte, WFS-Dienst opendata.meteo.be).

Quelle:     https://opendata.meteo.be/geoserver/ows  (Ebenen synop:synop_station und synop:synop_data, GeoJSON)
Betreiber:  Königliches Meteorologisches Institut von Belgien (KMI/IRM)
Lizenz:     siehe sources.yaml (nach Kenntnisstand CC BY 4.0, am Primärtext nicht bestätigt)
Intervall:  1800 s (die Stationen melden stündlich)
Beispiel:   python -m app.collect --once --only kmi_stationen

Stationsliste einmal am Tag (ohne beendete Stationen, auf den Radius gefiltert), je Lauf eine Abfrage für alle Stationen mit Zeitfilter,
weil die Ebene sonst Jahrzehnte an Historie liefert. Parameternamen und Einheiten entsprechen den DWD-Stationen (°C, %, hPa, km/h),
damit Karte und Popup beide gleich behandeln. Windgeschwindigkeit: Code 0/1 = m/s, 3/4 = Knoten (WMO 1860), beides wird nach km/h umgerechnet.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import geo
from ..models import Measurement, Station, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

LIST_TTL = timedelta(hours=24)
LOOKBACK_H = 6
MS_TO_KMH, KT_TO_KMH = 3.6, 1.852
FIELDS = {"temp": ("temperature", "°C"), "humidity_relative": ("relative_humidity", "%"), "pressure": ("pressure_msl", "hPa")}


def _wfs(layer: str, **extra: str) -> dict[str, str]:
    return {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": layer,
            "outputFormat": "application/json", "srsName": "EPSG:4326", **extra}


def pick_stations(data: Any) -> list[dict[str, Any]]:
    """synop_station-Antwort → aktive Stationen im Radius, je Kennung eine. Reine Funktion."""
    out: dict[int, dict[str, Any]] = {}
    for f in (data or {}).get("features", []) if isinstance(data, dict) else []:
        try:
            p = f["properties"]
            lon, lat = (float(c) for c in f["geometry"]["coordinates"][:2])
            code = int(p["code"])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if p.get("date_end") is not None:
            continue
        if not geo.in_region(lat, lon):
            continue
        out[code] = {"code": code, "name": str(p.get("name", code)), "lat": lat, "lon": lon, "height": p.get("altitude")}
    return sorted(out.values(), key=lambda s: s["code"])


def _kmh(speed: float, unit: Any) -> float | None:
    try:
        u = int(unit)
    except (TypeError, ValueError):
        return None
    return speed * MS_TO_KMH if u in (0, 1) else speed * KT_TO_KMH if u in (3, 4) else None


class KmiStationenCollector(Collector):
    async def _stations(self, url: str) -> list[dict[str, Any]]:
        row = await self._cache_get("kmi:stations")
        if row and utcnow() - datetime.fromisoformat(row["fetched"]) < LIST_TTL:
            return row["stations"]
        stations = pick_stations(await self.fetch_json(url, params=_wfs("synop:synop_station")))
        await self._cache_put("kmi:stations", {"fetched": utcnow().isoformat(), "stations": stations})
        return stations

    async def _cache_get(self, key: str) -> Any:
        import asyncio
        row = await asyncio.to_thread(self.storage.cache_get, key)
        return row["payload"] if row else None

    async def _cache_put(self, key: str, payload: Any) -> None:
        import asyncio
        await asyncio.to_thread(self.storage.cache_put, key, self.entry.id, payload)

    async def collect(self) -> CollectResult:
        url = self.entry.url
        listing = await self._stations(url)
        if not listing:
            raise SourceError("keine KMI-Station im Radius (Stationsliste leer oder Schema geändert)")
        since = (utcnow() - timedelta(hours=LOOKBACK_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
        codes = ",".join(str(s["code"]) for s in listing)
        raw = await self.fetch_json(url, params=_wfs("synop:synop_data", cql_filter=f"code IN ({codes}) AND timestamp AFTER {since}"))
        feats = raw.get("features") if isinstance(raw, dict) else None
        if not isinstance(feats, list):
            raise SourceError("synop_data: Schlüssel 'features' fehlt")
        by_code = {s["code"]: s for s in listing}
        measurements: list[Measurement] = []
        have: set[int] = set()
        for f in feats:
            try:
                p = f["properties"]
                code = int(p["code"])
                ts = datetime.fromisoformat(str(p["timestamp"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue
            if code not in by_code:
                continue
            sid = f"be{code}"
            got = False
            for key, (name, unit) in FIELDS.items():
                if p.get(key) is not None:
                    measurements.append(Measurement(source_id=self.entry.id, station_id=sid, parameter=name, ts=ts, value=float(p[key]), unit=unit))
                    got = True
            for key, name in (("wind_speed", "wind_speed_10"), ("wind_peak_speed", "wind_gust_speed_10")):
                if p.get(key) is not None:
                    v = _kmh(float(p[key]), p.get("wind_speed_unit"))
                    if v is not None:
                        measurements.append(Measurement(source_id=self.entry.id, station_id=sid, parameter=name, ts=ts, value=round(v, 1), unit="km/h"))
                        got = True
            if got:
                have.add(code)
        if not have:
            raise SourceError(f"keine Messwerte von {len(listing)} Stationen in den letzten {LOOKBACK_H} Stunden")
        stations = [Station(source_id=self.entry.id, station_id=f"be{c}", name=clean_text(by_code[c]["name"].title(), 80), lat=by_code[c]["lat"],
                            lon=by_code[c]["lon"], meta={"kmi_code": c, "height_m": by_code[c]["height"]}) for c in sorted(have)]
        silent = [by_code[c]["name"] for c in by_code if c not in have]
        return CollectResult(stations=stations, measurements=measurements, complete=not silent,
                             note=f"ohne Werte: {', '.join(silent)}" if silent else None)


COLLECTOR = KmiStationenCollector
