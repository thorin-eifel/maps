"""Autobahn-API-Collector (Baustellen, Sperrungen, Verkehrsmeldungen).

Quelle:     https://verkehr.autobahn.de/o/autobahn  (/{road}/services/{roadworks|warning|closure})
Lizenz:     siehe sources.yaml (Nutzungsbedingungen noch zu bestätigen)
Intervall:  600 s
Beispiel:   python -m app.collect --once --only autobahn

Die API liefert je Autobahn das ganze Bundesgebiet; der Radiusfilter passiert hier am Rand.
Abrufe laufen nacheinander mit kleiner Pause (12 je Lauf). Schlägt einer fehl, ist der Lauf
unvollständig: geschrieben wird, abgeräumt wird nichts.
Zeitangaben: Laufende Meldungen übernehmen `startTimestamp`. Geplante Baustellen (`future`) nennen
ihren Beginn nur im Fließtext; dort wird der erste Termin („TT.MM.JJ von HH:MM“) gelesen. Findet
sich keiner, bleibt valid_from leer und der Titel trägt „(geplant)“.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..models import Event, Severity, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

TYPE_LABEL = {"roadworks": "Baustelle", "warning": "Verkehrsmeldung", "closure": "Sperrung"}
# Verkehrslage: Die API meldet in `warning` Einträge mit `abnormalTrafficType` (Stau, zähfließend,
# Stillstand), dazu Verzögerung in Minuten (`delayTimeValue`) und Durchschnittstempo (`averageSpeed`).
# „Stop-and-go“ kennt die API nicht als eigene Stufe; es liegt zwischen SLOW und QUEUING.
TRAFFIC_KIND: dict[str, tuple[str, str, Severity]] = {
    "STATIONARY_TRAFFIC": ("stillstand", "Stillstand", "warning"),
    "QUEUING_TRAFFIC": ("stau", "Stau", "notice"),
    "SLOW_TRAFFIC": ("zaehfliessend", "Zähfließender Verkehr", "info"),
}
STAU_LONG_DELAY_MIN = 30  # ab dieser Verzögerung wird aus „Stau“ eine Warnung


def _int(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _extent_line(item: dict[str, Any]) -> dict[str, Any] | None:
    """`extent` = „lat,lon,lat,lon“ (Anfang, Ende der Meldung). Gerade Linie, nur Näherung des Straßenverlaufs."""
    try:
        la1, lo1, la2, lo2 = (float(x) for x in str(item.get("extent")).split(","))
    except ValueError:
        return None
    if (la1, lo1) == (la2, lo2):
        return None
    return {"type": "LineString", "coordinates": [[lo1, la1], [lo2, la2]]}


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_BERLIN = ZoneInfo("Europe/Berlin")
_PLANNED = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})\s+von\s+(\d{1,2}):(\d{2})")


def _planned_start(description: Any) -> datetime | None:
    """Geplanter Beginn aus dem Fließtext („05.10.26 von 08:00 bis …“), lokale Zeit → UTC.

    Heuristik: erste Fundstelle. Keine Fundstelle → None (Ereignis bleibt als „geplant“ markiert).
    """
    text = " ".join(description) if isinstance(description, list) else str(description or "")
    m = _PLANNED.search(text)
    if not m:
        return None
    d, mo, y, h, mi = (int(x) for x in m.groups())
    try:
        return datetime(2000 + y, mo, d, h, mi, tzinfo=_BERLIN).astimezone(timezone.utc)
    except ValueError:
        return None


def _geometry(item: dict[str, Any]) -> dict[str, Any] | None:
    g = item.get("geometry")
    if isinstance(g, dict) and g.get("type") and g.get("coordinates"):
        return g
    c = item.get("coordinate")
    if isinstance(c, dict):
        try:
            return {"type": "Point", "coordinates": [float(c["long"]), float(c["lat"])]}
        except (KeyError, TypeError, ValueError):
            return None
    return None


class AutobahnCollector(Collector):
    pause_s = 0.4

    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        roads = self.entry.params["roads"]
        services = self.entry.params["services"]
        now = utcnow()
        events: dict[str, Event] = {}
        failed: list[str] = []
        ok_calls = 0
        for road in roads:
            for service in services:
                try:
                    data = await self.fetch_json(f"{base}/{road}/services/{service}")
                except SourceError as exc:
                    self.log.warning("%s/%s fehlgeschlagen: %s", road, service, exc)
                    failed.append(f"{road}/{service}")
                    continue
                ok_calls += 1
                items = data.get(service) if isinstance(data, dict) else None
                if not isinstance(items, list):
                    raise SourceError(f"{road}/{service}: Schlüssel '{service}' fehlt")
                for item in items:
                    ev = self._normalize(road, service, item, now)
                    if ev is not None:
                        events[ev.id] = ev
                await asyncio.sleep(self.pause_s)
        if ok_calls == 0:
            raise SourceError("Kein Abruf erfolgreich")
        note = f"teilweise: {', '.join(failed[:4])} fehlgeschlagen" if failed else None
        return CollectResult(events=list(events.values()), complete=not failed, note=note)

    def _normalize(self, road: str, service: str, item: dict[str, Any], now: datetime) -> Event | None:
        ident = item.get("identifier")
        geometry = _geometry(item)
        if not ident or geometry is None or not self.keep(geometry):
            return None
        blocked = str(item.get("isBlocked", "false")).lower() == "true"
        future = bool(item.get("future"))
        severity: Severity
        if service == "closure" or blocked:
            severity = "warning"
        elif service == "warning":
            severity = "notice"
        else:
            severity = "info"
        desc = item.get("description")
        if isinstance(desc, list):
            desc = " ".join(str(x) for x in desc if x)
        prefix = f"{TYPE_LABEL[service]}{' (geplant)' if future else ''}: "
        title = clean_text(f"{item.get('title', road)} {item.get('subtitle', '')}".strip(), 240)
        etype = "traffic"
        attrs: dict[str, Any] = {"kind": "sperrung" if service == "closure" or blocked else "baustelle" if service == "roadworks" else "warnung"}
        if attrs["kind"] == "sperrung":
            attrs["sperr"] = "voll"
        traffic = TRAFFIC_KIND.get(str(item.get("abnormalTrafficType") or ""))
        if service == "warning" and traffic and not future:
            kind, label, severity = traffic
            delay, speed = _int(item.get("delayTimeValue")), _int(item.get("averageSpeed"))
            if kind == "stau" and delay is not None and delay >= STAU_LONG_DELAY_MIN:
                severity = "warning"
            etype = "congestion"
            attrs = {"kind": kind}
            facts = []
            if delay is not None:
                attrs["delay_min"] = delay
                facts.append(f"rund {delay} Minuten Verzögerung")
            if speed is not None:
                attrs["speed_kmh"] = speed
                facts.append(f"Durchschnittstempo {speed} km/h")
            prefix = f"{label}{': ' + ', '.join(facts) if facts else ''}. "
            title = clean_text(f"{label}: {title}", 240)
            line = _extent_line(item)
            if line is not None and self.keep(line):
                geometry = line
        return Event(
            id=f"autobahn:{ident}",
            source_id=self.entry.id,
            type=etype,  # type: ignore[arg-type]
            attrs=attrs,
            title=title,
            summary=clean_text(prefix + str(desc or ""), 800),
            severity=severity,
            geometry=geometry,
            region_tag="DE",
            valid_from=_planned_start(item.get("description")) if future else _dt(item.get("startTimestamp")),
            fetched_at=now,
            raw_ref="https://autobahn.de/",
        )


COLLECTOR = AutobahnCollector
