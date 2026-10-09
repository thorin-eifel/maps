"""Luftqualität der Messstationen des Umweltbundesamts (Luftdaten-API v3, Länder-Messnetze).

Quelle:     https://luftdaten.umweltbundesamt.de/api/air-data/v3  (stations/json, airquality/json)
Betreiber:  Umweltbundesamt (UBA), Daten der Landesmessnetze (RLP: Landesamt für Umwelt, Saarland: LUA)
Lizenz:     siehe sources.yaml (nach Kenntnisstand Datenlizenz Deutschland Namensnennung 2.0, nicht am Primärtext bestätigt)
Intervall:  1800 s (Stundenwerte, vorläufig geprüft)
Beispiel:   python -m app.collect --once --only uba_luft

Stationsliste (112 KB) wird 24 Stunden zwischengespeichert und auf den Radius gefiltert. Je Station ein Abruf der
letzten Stunden: `lqi` (Luftqualitätsindex 0 sehr gut bis 4 sehr schlecht) und die Komponenten PM10, PM2.5, NO2, O3, SO2, CO.
Die API rechnet in MEZ (UTC+1, ohne Sommerzeit); der Endzeitpunkt der Stunde wird nach UTC umgerechnet.
Luxemburg und Frankreich fehlen (das UBA-Netz endet an der deutschen Grenze).
Ereignis ab Index 3 (schlecht) als Hinweis, ab 4 als Warnung.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, geo
from ..models import Event, Measurement, Severity, Station, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

CET = timezone(timedelta(hours=1))
COMPONENTS = {1: ("PM10", "µg/m³"), 2: ("CO", "mg/m³"), 3: ("O3", "µg/m³"), 4: ("SO2", "µg/m³"), 5: ("NO2", "µg/m³"), 9: ("PM2.5", "µg/m³")}
LQI_NAME = {0: "sehr gut", 1: "gut", 2: "mäßig", 3: "schlecht", 4: "sehr schlecht"}
STATIONS_TTL = timedelta(hours=24)
LOOKBACK_H = 8


def _cet(value: str) -> datetime:
    """UBA-Zeitstempel in CET; die Quelle schreibt das Tagesende als „24:00:00“ (strptime kennt das nicht)."""
    if value.endswith(" 24:00:00"):
        base = datetime.strptime(value[:10], "%Y-%m-%d") + timedelta(days=1)
    else:
        base = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return base.replace(tzinfo=CET).astimezone(timezone.utc)


class UbaLuftCollector(Collector):
    async def _stations(self, base: str) -> list[dict[str, Any]]:
        row = await asyncio.to_thread(self.storage.cache_get, "uba:stations")
        if row and utcnow() - datetime.fromisoformat(row["payload"]["fetched"]) < STATIONS_TTL:
            return row["payload"]["stations"]
        raw = await self.fetch_json(f"{base}/stations/json", params={"use": "airquality", "lang": "de"})
        data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(data, dict):
            raise SourceError("stations: Schlüssel 'data' fehlt")
        out = []
        for v in data.values():
            try:
                lon, lat = float(v[7]), float(v[8])
            except (IndexError, TypeError, ValueError):
                continue
            if v[6] is not None:
                continue  # Station stillgelegt
            if not geo.in_bbox(lat, lon) or geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
                continue
            out.append({"id": str(v[0]), "code": v[1], "name": v[2], "city": v[3], "lat": lat, "lon": lon,
                        "setting": v[14], "type": v[16]})
        await asyncio.to_thread(self.storage.cache_put, "uba:stations", self.entry.id, {"fetched": utcnow().isoformat(), "stations": out})
        return out

    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        stations_raw = await self._stations(base)
        now = utcnow()
        cet_now = now.astimezone(CET)
        start = cet_now - timedelta(hours=LOOKBACK_H)
        stations: list[Station] = []
        measurements: list[Measurement] = []
        events: list[Event] = []
        failed: list[str] = []
        for s in stations_raw:
            try:
                resp = await self.fetch_json(f"{base}/airquality/json", params={
                    "station": s["id"], "lang": "de", "date_from": f"{start:%Y-%m-%d}", "time_from": start.hour,
                    "date_to": f"{cet_now:%Y-%m-%d}", "time_to": cet_now.hour,
                })
            except SourceError as exc:
                self.log.warning("Station %s: %s", s["id"], exc)
                failed.append(s["code"])
                continue
            rows = (resp.get("data") or {}).get(s["id"]) if isinstance(resp, dict) else None
            if not isinstance(rows, dict) or not rows:
                failed.append(s["code"])
                continue
            stations.append(Station(source_id=self.entry.id, station_id=s["id"], name=clean_text(s["name"], 80),
                                    lat=s["lat"], lon=s["lon"],
                                    meta={"code": s["code"], "full_name": s["name"], "setting": s["setting"], "type": s["type"]}))
            latest_end, latest_lqi = None, None
            for _, row in sorted(rows.items()):
                end = _cet(row[0])
                lqi = int(row[1])
                measurements.append(Measurement(source_id=self.entry.id, station_id=s["id"], parameter="lqi", ts=end,
                                                value=float(lqi), unit="", state=LQI_NAME.get(lqi)))
                for comp in row[3:]:
                    name_unit = COMPONENTS.get(int(comp[0]))
                    if name_unit:
                        measurements.append(Measurement(source_id=self.entry.id, station_id=s["id"], parameter=name_unit[0], ts=end,
                                                        value=float(comp[1]), unit=name_unit[1], state=LQI_NAME.get(int(comp[2]))))
                latest_end, latest_lqi = end, lqi
            sev: Severity | None = "warning" if (latest_lqi or 0) >= 4 else "notice" if (latest_lqi or 0) >= 3 else None
            if sev and latest_end and now - latest_end < timedelta(hours=4):
                events.append(Event(
                    id=f"uba:{s['id']}", source_id=self.entry.id, type="air",
                    title=f"Luftqualität {LQI_NAME[latest_lqi]}: {s['city']}", summary=clean_text(
                        f"Luftqualitätsindex {latest_lqi} ({LQI_NAME[latest_lqi]}) an der Station {s['name']}, Stunde bis {latest_end:%H:%M} UTC.", 300),
                    severity=sev, geometry={"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                    valid_from=latest_end, valid_to=latest_end + timedelta(hours=3), fetched_at=now,
                    region_tag="DE-SL" if s["code"].startswith("DESL") else "DE-RLP", raw_ref="https://luftdaten.umweltbundesamt.de/",
                    attrs={"kind": "luft", "lqi": latest_lqi},
                ))
        if not stations:
            raise SourceError("keine Station mit Daten (API geändert oder gestört?)")
        note = f"teilweise: keine Daten für {', '.join(failed)}" if failed else None
        return CollectResult(events=events, stations=stations, measurements=measurements, complete=not failed, note=note)


COLLECTOR = UbaLuftCollector
