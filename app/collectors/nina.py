"""NINA-Collector (Bevölkerungswarnungen, BBK).

Quelle:     https://warnung.bund.de/api31  (Dashboard je ARS, Detail und GeoJSON je Meldung)
Lizenz:     siehe sources.yaml (Eintrag `nina`, Lizenz noch zu bestätigen)
Intervall:  300 s
Beispiel:   python -m app.collect --once --only nina

Ablauf: Dashboard je Kreis-ARS → eindeutige Meldungs-IDs → Detail + GeoJSON →
Geometriefilter (Südeifel + 120 km). Hat eine Meldung keine Geometrie, wird sie am Kreissitz
verortet und mit confidence 0.5 gekennzeichnet — lieber unscharf als verschwiegen.
Meldungen vom Typ „Cancel“ und Testmeldungen werden verworfen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Event, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError
from .severity import cap_to_severity

# Kreissitze als Rückfallposition (Näherung, nur für Meldungen ohne Geometrie)
SEAT = {
    "072320000000": (49.9737, 6.5225),
    "072350000000": (49.7499, 6.6371),
    "072110000000": (49.7499, 6.6371),
    "072330000000": (50.1975, 6.8306),
    "072310000000": (49.9855, 6.8935),
    "100420000000": (49.4442, 6.6386),
    "071350000000": (50.1461, 7.1663),   # Cochem-Zell
    "071340000000": (49.6448, 7.1644),   # Birkenfeld
    "071370000000": (50.3569, 7.589),   # Mayen-Koblenz
    "071310000000": (50.5442, 7.0937),   # Ahrweiler
    "071400000000": (49.9833, 7.5194),   # Rhein-Hunsrück-Kreis
    "071110000000": (50.3569, 7.589),   # Stadt Koblenz
    "071330000000": (49.8454, 7.8677),   # Bad Kreuznach
    "100410000000": (49.2354, 6.9963),   # Regionalverband Saarbrücken
    "100430000000": (49.3446, 7.1808),   # Neunkirchen (Saar)
    "100440000000": (49.3134, 6.7519),   # Saarlouis
    "100450000000": (49.3264, 7.3387),   # Saarpfalz-Kreis
    "100460000000": (49.4667, 7.1667),   # St. Wendel
    "053660000000": (50.6613, 6.7872),   # Euskirchen
    "053340000000": (50.7753, 6.0839),   # Städteregion Aachen
}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _collect_geometry(geojson: Any) -> dict[str, Any] | None:
    if not isinstance(geojson, dict):
        return None
    geoms = [f["geometry"] for f in geojson.get("features", []) if f.get("geometry")]
    if not geoms:
        return None
    return geoms[0] if len(geoms) == 1 else {"type": "GeometryCollection", "geometries": geoms}


class NinaCollector(Collector):
    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        regions = self.entry.params["ars"]
        found: dict[str, str] = {}  # Meldungs-ID → ARS des ersten Fundorts
        failed: list[str] = []
        for region in regions:
            try:
                items = await self.fetch_json(f"{base}/dashboard/{region['ars']}.json")
            except SourceError as exc:
                self.log.warning("Region %s nicht erreichbar: %s", region["name"], exc)
                failed.append(region["name"])
                continue
            if not isinstance(items, list):
                raise SourceError(f"Dashboard {region['ars']}: Liste erwartet, {type(items).__name__} erhalten")
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    found.setdefault(item["id"], region["ars"])
        if len(failed) == len(regions):
            raise SourceError("Keine Region erreichbar")

        events: list[Event] = []
        now = utcnow()
        for wid, ars in found.items():
            try:
                detail = await self.fetch_json(f"{base}/warnings/{wid}.json")
                geojson = await self.fetch_json(f"{base}/warnings/{wid}.geojson")
            except SourceError as exc:
                self.log.warning("Meldung %s nicht abrufbar: %s", wid, exc)
                failed.append(wid)
                continue
            ev = self._normalize(wid, ars, detail, geojson, now)
            if ev is not None:
                events.append(ev)

        note = f"teilweise: {len(failed)} Abrufe fehlgeschlagen ({', '.join(failed[:3])})" if failed else None
        return CollectResult(events=events, complete=not failed, note=note)

    def _normalize(self, wid: str, ars: str, detail: dict[str, Any], geojson: Any, now: datetime) -> Event | None:
        if detail.get("status") not in (None, "Actual"):
            return None
        if detail.get("msgType") == "Cancel":
            return None
        infos = detail.get("info") or []
        if not infos:
            return None
        info = next((i for i in infos if i.get("language", "").startswith("de")), infos[0])
        title = clean_text(info.get("headline"), 300)
        if not title:
            return None

        geometry = _collect_geometry(geojson)
        confidence = 1.0
        summary = clean_text(info.get("description"), 700)
        if geometry is None:
            seat = SEAT.get(ars)
            if seat is None:
                return None
            geometry = {"type": "Point", "coordinates": [seat[1], seat[0]]}
            confidence = 0.5
            summary = ("Ort ungenau (Kreissitz), Meldung liefert keine Fläche. " + summary).strip()
        if not self.keep(geometry):
            return None

        valid_from = _parse_dt(info.get("onset")) or _parse_dt(detail.get("sent"))
        return Event(
            id=f"nina:{wid}",
            source_id=self.entry.id,
            type="warning",
            title=title,
            summary=summary,
            severity=cap_to_severity(info.get("severity")),
            confidence=confidence,
            geometry=geometry,
            region_tag="DE",
            valid_from=valid_from,
            valid_to=_parse_dt(info.get("expires")),
            fetched_at=now,
            raw_ref=f"{self.entry.url.rstrip('/')}/warnings/{wid}.json",
        )


COLLECTOR = NinaCollector
