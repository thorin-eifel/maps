"""NINA-Collector (Bevölkerungswarnungen, BBK).

Quelle:     https://warnung.bund.de/api31  (mapData je Kanal, Detail und GeoJSON je Meldung)
Lizenz:     siehe sources.yaml (Eintrag `nina`, Lizenz noch zu bestätigen)
Intervall:  300 s
Beispiel:   python -m app.collect --once --only nina

Ablauf: mapData.json je Kanal (mowas, katwarn, biwapp, lhp, police; bundesweit, nur aktive Meldungen) → je neue Meldung
Detail + GeoJSON → Geometriefilter (Region). Das Dashboard je Kreis-ARS (bisheriges Verfahren) entfällt: für eine Fläche
mit über 130 Kreisen wären das 130 Abrufe je Lauf, die Länder-ARS fassen Kreise nicht zusammen (am 9.10.2026 geprüft).
Eine Meldung ohne Geometrie hat keinen Ort und wird verworfen (früher: Kreissitz mit confidence 0.5); die Zahl steht im Lauf-Vermerk.
Das Ergebnis je (Meldung, Version) bleibt im Arbeitsspeicher, damit nur neue oder geänderte Meldungen Detailabrufe kosten.
Der Kanal dwd ist abgeschaltet, weil die DWD-Warnungen über den Sammler dwd_warnungen kommen (Standard: params.channels).
Meldungen vom Typ „Cancel“ und Testmeldungen werden verworfen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Event, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError
from .severity import cap_to_severity

DEFAULT_CHANNELS = ("mowas", "katwarn", "biwapp", "lhp", "police")
_CACHE: dict[tuple[str, str], tuple[Any, bool]] = {}   # (Kennung, Version) → (Event oder None, ohne Geometrie)
_CACHE_MAX = 5000


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
        channels = self.entry.params.get("channels") or DEFAULT_CHANNELS
        current: dict[str, str] = {}   # Meldungs-ID → Version
        failed: list[str] = []
        for ch in channels:
            try:
                items = await self.fetch_json(f"{base}/{ch}/mapData.json")
            except SourceError as exc:
                self.log.warning("Kanal %s nicht erreichbar: %s", ch, exc)
                failed.append(ch)
                continue
            if not isinstance(items, list):
                raise SourceError(f"mapData {ch}: Liste erwartet, {type(items).__name__} erhalten")
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    current.setdefault(str(item["id"]), str(item.get("version", "")))
        if len(failed) == len(channels):
            raise SourceError("Kein Kanal erreichbar")

        events: list[Event] = []
        now = utcnow()
        no_geometry = 0
        for wid, version in current.items():
            key = (wid, version)
            if key not in _CACHE:
                try:
                    detail = await self.fetch_json(f"{base}/warnings/{wid}.json")
                    geojson = await self.fetch_json(f"{base}/warnings/{wid}.geojson")
                except SourceError as exc:
                    self.log.warning("Meldung %s nicht abrufbar: %s", wid, exc)
                    failed.append(wid)
                    continue
                if len(_CACHE) >= _CACHE_MAX:
                    _CACHE.clear()
                _CACHE[key] = self._normalize(wid, detail, geojson, now)
            ev, missing = _CACHE[key]
            no_geometry += missing
            if ev is not None:
                events.append(ev.model_copy(update={"fetched_at": now}))   # Abrufzeit gilt für diesen Lauf, auch wenn der Inhalt aus dem Speicher kommt

        parts = []
        if failed:
            parts.append(f"teilweise: {len(failed)} Abrufe fehlgeschlagen ({', '.join(failed[:3])})")
        if no_geometry:
            parts.append(f"{no_geometry} Meldungen ohne Fläche verworfen")
        return CollectResult(events=events, complete=not failed, note="; ".join(parts) or None)

    def _normalize(self, wid: str, detail: dict[str, Any], geojson: Any, now: datetime) -> tuple[Event | None, bool]:
        """(Ereignis oder None, True wenn nur die fehlende Geometrie der Grund war)."""
        ev = self._build(wid, detail, geojson, now)
        return (None, True) if ev is False else (ev, False)

    def _build(self, wid: str, detail: dict[str, Any], geojson: Any, now: datetime) -> Event | None | bool:
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
            return False
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
