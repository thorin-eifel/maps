"""Pegel der Hochwasservorhersagezentrale Rheinland-Pfalz (LfU RLP).

Quelle:     https://hochwasser.rlp.de/api/v1/{config,index}  (JSON-Schnittstelle der Webseite, nicht als offene API dokumentiert)
Betreiber:  Landesamt für Umwelt RLP; die Messwerte gehören den Pegelbetreibern (SGD Nord, Kommunen, AGE Luxemburg, SPW Belgien)
Lizenz:     siehe sources.yaml (Nutzungsbedingungen der Schnittstelle nicht gefunden, Anfrage nötig)
Intervall:  900 s (die Seite selbst holt `index` alle 5 Minuten; die Datei ist ca. 3 MB)
Beispiel:   python -m app.collect --once --only hochwasser_rlp

`config` (Stammdaten: Name, UTM-32-Koordinaten, Gewässer, Betreiber, Farblegende) ändert sich selten und wird 12 Stunden
im Cache gehalten. `index` liefert je Messstelle die letzten zwei Tage in 15-Minuten-Schritten (Wasserstand W).
Filter: Radius am Rand. Stellen der WSV (WSA …) werden verworfen, die kommen schon über PEGELONLINE.
Zustand: Der Collector zeigt die Klasse laut Legende der Quelle (legendColor). Ab „Mäßige Hochwassergefahr“ (HW 2)
entsteht zusätzlich ein Ereignis; Niedrigwasser bleibt eine reine Anzeige.
Seen (isSeaSite, Talsperren) melden Meter über NN, Flüsse Zentimeter Pegelstand.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import geo
from ..models import Event, Measurement, Severity, Station, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

CONFIG_TTL = timedelta(hours=12)
BACKFILL = timedelta(hours=48)
NO_VALUE = "#f0f0f0"
# alertClassId der Legende → Schweregrad; Klassen unter 3 sind Normalzustand
SEVERITY_BY_CLASS: dict[int, Severity] = {3: "notice", 4: "warning", 5: "warning", 6: "critical", 7: "critical"}


def _dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _region(operator: str) -> str:
    o = operator.lower()
    return "LU" if "luxemburg" in o else "BE" if "belgien" in o else "DE-RLP"


class HochwasserRlpCollector(Collector):
    async def _config(self, base: str) -> dict[str, Any]:
        row = await asyncio.to_thread(self.storage.cache_get, "hwrlp:config")
        if row:
            cached = row["payload"]
            fetched = _dt(cached.get("fetched"))
            if fetched and utcnow() - fetched < CONFIG_TTL:
                return cached
        raw = await self.fetch_json(f"{base}/config")
        if not isinstance(raw, dict) or "measurementsite" not in raw or "legends" not in raw:
            raise SourceError("config: Schlüssel 'measurementsite' oder 'legends' fehlt")
        legend = {v["color"].lower(): {"name": v["name"], "desc": v.get("description", ""), "cls": v.get("alertClassId")}
                  for v in (raw["legends"].get("W") or {}).values()}
        sites: dict[str, Any] = {}
        for num, s in raw["measurementsite"].items():
            try:
                lat, lon = geo.utm32_to_wgs84(float(s["easting"]), float(s["northing"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not geo.in_region(lat, lon):
                continue  # Filter am Rand: außerhalb wird gar nicht erst gemerkt
            op = (raw.get("operators") or {}).get(num) or {}
            rivers = [raw.get("rivers", {}).get(r, {}).get("name") for r in s.get("rivers") or []]
            sites[num] = {
                "name": str(s.get("name") or num), "lat": round(lat, 5), "lon": round(lon, 5),
                "river": next((r for r in rivers if r), None), "km": s.get("riverKilometer"),
                "lake": bool(s.get("isSeaSite")), "municipal": s.get("type") == "municipal",
                "operator": str(op.get("op_name") or ""), "url": op.get("ms_url"),
            }
        out = {"fetched": utcnow().isoformat(), "legend": legend, "sites": sites}
        await asyncio.to_thread(self.storage.cache_put, "hwrlp:config", self.entry.id, out)
        return out

    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        cfg = await self._config(base)
        legend, sites = cfg["legend"], cfg["sites"]
        index = await self.fetch_json(f"{base}/index")
        data = index.get("measurementSites") if isinstance(index, dict) else None
        if not isinstance(data, dict):
            raise SourceError("index: Schlüssel 'measurementSites' fehlt")
        newest = {r["station_id"]: r["m"] for r in await asyncio.to_thread(
            self.storage._query,  # noqa: SLF001 — interne Lesefunktion desselben Pakets
            "SELECT station_id, MAX(ts) m FROM measurements WHERE source_id=? AND parameter='W' GROUP BY station_id", (self.entry.id,))}
        now = utcnow()
        stations: list[Station] = []
        measurements: list[Measurement] = []
        events: dict[str, Event] = {}
        for num, site in sites.items():
            op = site["operator"]
            if op.startswith("WSA"):
                continue  # kommt über PEGELONLINE
            cur = data.get(num)
            if not isinstance(cur, dict) or cur.get("yLast") is None or str(cur.get("legendColor", "")).lower() == NO_VALUE:
                continue
            unit = "m ü. NN" if site["lake"] else "cm"
            last = _dt(cur.get("xLast"))
            if last is None:
                continue
            klass = legend.get(str(cur.get("legendColor", "")).lower(), {"name": "unbekannt", "desc": "", "cls": None})
            stations.append(Station(
                source_id=self.entry.id, station_id=num, name=clean_text(site["name"], 80),
                water=site["river"] or ("Kommunale Messstelle" if site["municipal"] else None), km=site["km"],
                lat=site["lat"], lon=site["lon"], meta={"operator": op, "url": site["url"], "unit": unit},
            ))
            have = newest.get(num)
            cutoff = (_dt(have) if have else None) or now - BACKFILL
            for row in cur.get("measurements") or []:
                ts = _dt(row.get("x"))
                if ts is None or row.get("y") is None or ts <= cutoff:
                    continue
                measurements.append(Measurement(source_id=self.entry.id, station_id=num, parameter="W", ts=ts,
                                                value=float(row["y"]), unit=unit, state=klass["name"] if ts == last else None))
            sev = SEVERITY_BY_CLASS.get(klass["cls"] or 0)
            if sev and now - last < timedelta(hours=3):
                ev = Event(
                    id=f"hwrlp:{num}", source_id=self.entry.id, type="flood",
                    title=clean_text(f"Hochwasser: Pegel {site['name']}" + (f" ({site['river']})" if site["river"] else ""), 200),
                    summary=clean_text(f"{klass['name']} ({klass['desc']}), Wasserstand {cur['yLast']} {unit}, Messung {last:%d.%m. %H:%M} UTC. Betreiber: {op}", 500),
                    severity=sev, geometry={"type": "Point", "coordinates": [site["lon"], site["lat"]]},
                    region_tag=_region(op), valid_from=last, valid_to=last + timedelta(hours=3), fetched_at=now,
                    raw_ref="https://hochwasser.rlp.de/", attrs={"kind": "hochwasser"},
                )
                events[ev.id] = ev
        if not stations:
            raise SourceError("keine Messstelle im Radius mit Wert (Schema geändert?)")
        return CollectResult(events=list(events.values()), stations=stations, measurements=measurements, complete=True)


COLLECTOR = HochwasserRlpCollector
