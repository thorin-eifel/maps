"""PEGELONLINE-Collector (Wasserstände, WSV).

Quelle:     https://www.pegelonline.wsv.de/webservices/rest-api/v2
Lizenz:     siehe sources.yaml
Intervall:  600 s
Beispiel:   python -m app.collect --once --only pegelonline

Ein Listenabruf mit Radius liefert Stationen samt aktuellem Messwert. Eine neue Station
bekommt einmalig 2 Tage Verlauf nachgeladen (Backfill), danach genügt der aktuelle Wert je Lauf.
Warnstufen: Es wird nur der Zustand angezeigt, den die Quelle selbst meldet
(stateMnwMhw / stateNswHsw). Eigene Hochwasser-Ereignisse entstehen erst in Phase 2
(Hochwasserportal RLP mit dokumentierten Meldestufen).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from .. import config, geo
from ..models import Measurement, Station
from .base import Collector, CollectResult, SourceError


import re


def _name(raw: str) -> str:
    """„TRIER UP“ → „Trier UP“: Ortsname normal, Kürzel (UP/OP/SKA/SKR) groß."""
    return re.sub(r"\b(Up|Op|Ska|Skr)\b", lambda m: m.group(1).upper(), str(raw).title())


class PegelonlineCollector(Collector):
    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        param = self.entry.params.get("parameter", "W")
        stations_raw = await self.fetch_json(f"{base}/stations.json", params={
            "latitude": config.CENTER_LAT, "longitude": config.CENTER_LON,
            "radius": int(config.RADIUS_KM),
            "includeTimeseries": "true", "includeCurrentMeasurement": "true",
        })
        if not isinstance(stations_raw, list):
            raise SourceError("stations.json: Liste erwartet")

        stations: list[Station] = []
        measurements: list[Measurement] = []
        failed: list[str] = []
        for s in stations_raw:
            try:
                lat, lon = float(s["latitude"]), float(s["longitude"])
            except (KeyError, TypeError, ValueError):
                continue  # Station ohne Koordinaten ist nicht verortbar
            if not geo.in_bbox(lat, lon) or geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
                continue
            ts = next((t for t in s.get("timeseries", []) if t.get("shortname") == param), None)
            if ts is None:
                continue
            sid = s["uuid"]
            stations.append(Station(
                source_id=self.entry.id, station_id=sid, name=_name(s.get("shortname", sid)),
                water=str(s.get("water", {}).get("shortname", "")).title() or None,
                km=s.get("km"), lat=lat, lon=lon,
                meta={"number": s.get("number"), "agency": s.get("agency"),
                      "gauge_zero": ts.get("gaugeZero")},
            ))
            cm = ts.get("currentMeasurement")
            if cm:
                measurements.append(self._measurement(sid, param, ts, cm))
            have = await asyncio.to_thread(self._count, sid, param)
            if have == 0:
                try:
                    hist = await self.fetch_json(f"{base}/stations/{sid}/{param}/measurements.json", params={"start": "P2D"})
                    for row in hist:
                        measurements.append(self._measurement(sid, param, ts, row))
                except SourceError as exc:
                    self.log.warning("Backfill %s fehlgeschlagen: %s", sid, exc)
                    failed.append(s.get("shortname", sid))
        note = f"teilweise: Backfill fehlgeschlagen für {', '.join(failed[:3])}" if failed else None
        return CollectResult(stations=stations, measurements=measurements, writes_events=False, note=note)

    def _count(self, station_id: str, parameter: str) -> int:
        rows = self.storage._query(  # noqa: SLF001 — interne Lesefunktion desselben Pakets
            "SELECT COUNT(*) n FROM measurements WHERE source_id=? AND station_id=? AND parameter=?",
            (self.entry.id, station_id, parameter))
        return rows[0]["n"]

    def _measurement(self, station_id: str, parameter: str, ts_meta: dict[str, Any], row: dict[str, Any]) -> Measurement:
        state = None
        if row.get("stateMnwMhw") or row.get("stateNswHsw"):
            state = f"{row.get('stateMnwMhw', '?')}/{row.get('stateNswHsw', '?')}"
        return Measurement(
            source_id=self.entry.id, station_id=station_id, parameter=parameter,
            ts=datetime.fromisoformat(row["timestamp"]), value=float(row["value"]),
            unit=ts_meta.get("unit", "cm"), state=state,
        )


COLLECTOR = PegelonlineCollector
