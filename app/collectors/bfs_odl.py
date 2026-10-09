"""Ortsdosisleistung (Gamma-ODL) des BfS-Messnetzes.

Quelle:     https://www.imis.bfs.de/ogc/opendata/ows  (WFS 2.0.0, Layer opendata:odlinfo_odl_1h_latest)
Betreiber:  Bundesamt für Strahlenschutz (BfS), ODL-Messnetz mit rund 1.700 Sonden
Lizenz:     siehe sources.yaml (nach Kenntnisstand Datenlizenz Deutschland Namensnennung 2.0, nicht am Primärtext bestätigt)
Intervall:  1800 s (Stundenmittelwerte, der Dienst aktualisiert stündlich)
Beispiel:   python -m app.collect --once --only bfs_odl

Ein Abruf mit Bounding Box (Achsenfolge lat,lon), Feinfilter auf 120 km am Rand. Jede Sonde ist eine Station, der
Stundenwert (µSv/h, Brutto) eine Messreihe `odl`. Die BfS-Sonden decken Deutschland ab; Luxemburg und Frankreich
(Cattenom) fehlen in diesem Dienst. Ereignisse entstehen nur über eigene Orientierungsschwellen, siehe unten.
Schwellen (eigene Orientierung, KEIN amtlicher Grenzwert): ab 0,3 µSv/h Hinweis, ab 1,0 µSv/h Warnung. Die natürliche
Umgebungsstrahlung liegt in der Region typischerweise bei etwa 0,07 bis 0,20 µSv/h.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, geo
from ..models import Event, Measurement, Severity, Station, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

NOTICE_USVH = 0.3
WARNING_USVH = 1.0
MAX_AGE = timedelta(hours=6)  # ältere Sondenwerte gelten als ausgefallen und werden nicht angezeigt


def _dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class BfsOdlCollector(Collector):
    async def collect(self) -> CollectResult:
        lat0, lon0, lat1, lon1 = config.BBOX
        data = await self.fetch_json(self.entry.url, params={
            "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "opendata:odlinfo_odl_1h_latest",
            "outputFormat": "application/json", "srsName": "EPSG:4326",
            "bbox": f"{lat0},{lon0},{lat1},{lon1},urn:ogc:def:crs:EPSG::4326",
        })
        feats = data.get("features") if isinstance(data, dict) else None
        if not isinstance(feats, list):
            raise SourceError("ODL: Schlüssel 'features' fehlt")
        now = utcnow()
        stations: list[Station] = []
        measurements: list[Measurement] = []
        events: list[Event] = []
        for f in feats:
            p, g = f.get("properties") or {}, f.get("geometry") or {}
            try:
                lon, lat = g["coordinates"][:2]
                lon, lat, value = float(lon), float(lat), float(p["value"])
            except (KeyError, TypeError, ValueError):
                continue
            end = _dt(p.get("end_measure"))
            if end is None or now - end > MAX_AGE or p.get("site_status") != 1:
                continue
            if not geo.in_bbox(lat, lon) or geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
                continue
            sid = str(p.get("id") or p.get("kenn"))
            name = clean_text(str(p.get("name") or sid), 80)
            stations.append(Station(source_id=self.entry.id, station_id=sid, name=name, lat=lat, lon=lon,
                                    meta={"height_m": p.get("height_above_sea"), "cosmic": p.get("value_cosmic"),
                                          "terrestrial": p.get("value_terrestrial")}))
            measurements.append(Measurement(source_id=self.entry.id, station_id=sid, parameter="odl", ts=end, value=value,
                                            unit="µSv/h", state="validiert" if p.get("validated") == 1 else "vorläufig"))
            sev: Severity | None = "warning" if value >= WARNING_USVH else "notice" if value >= NOTICE_USVH else None
            if sev:
                events.append(Event(
                    id="odl:" + hashlib.sha1(sid.encode()).hexdigest()[:12], source_id=self.entry.id, type="radiation",
                    title=f"Erhöhte Ortsdosisleistung: {name}",
                    summary=f"{value:.3f} µSv/h (Stundenmittel bis {end:%H:%M} UTC). Eigene Orientierungsschwelle, kein amtlicher Grenzwert; die Region liegt sonst bei etwa 0,07 bis 0,20 µSv/h.",
                    severity=sev, geometry={"type": "Point", "coordinates": [lon, lat]}, valid_from=end,
                    valid_to=end + timedelta(hours=3), fetched_at=now, raw_ref="https://odlinfo.bfs.de/",
                    attrs={"kind": "strahlung", "value": value, "unit": "µSv/h"},
                ))
        if not stations:
            raise SourceError("keine ODL-Sonde im Radius mit frischem Wert (Schema geändert oder Dienst gestört?)")
        return CollectResult(events=events, stations=stations, measurements=measurements, complete=True)


COLLECTOR = BfsOdlCollector
