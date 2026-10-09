"""Regionale Schlagzeilen (Trierischer Volksfreund, RSS-Feed der Startseite).

Quelle:     https://www.volksfreund.de/feed.rss (RSS 2.0, vom Verlag öffentlich angeboten)
Betreiber:  Trierischer Volksfreund / Medienhaus (Verlag)
Lizenz:     keine offene Lizenz; nur Überschrift, Zeit und Link, kein Text, kein Bild (lizenz_geprueft false)
Intervall:  900 s
Beispiel:   python -m app.collect --once --only volksfreund

Der Feed enthält auch Sport, Magazin und Weltpolitik. Wir behalten nur Einträge der Rubriken "Region" und "Blaulicht" und nur,
wenn die Überschrift einen Ort im Radius nennt. Eine Schlagzeile ohne Ortsnamen wird verworfen, statt sie auf einen
Kreismittelpunkt zu setzen: ein Punkt, der nur geraten ist, gehört nicht auf die Karte.
robots.txt: der Feed ist nicht gesperrt; die dort gelisteten KI-Crawler sind ausgeschlossen, wir sind keiner und lesen nicht den Text.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from .. import geo
from ..geoparse import locate_text
from ..models import Event, Severity, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult
from .presseportal import NOTICE, PERSON_TARGETED
from .rsslib import parse_rss

VALID_HOURS = 48
KEEP_CATEGORIES = {"region", "blaulicht"}


def parse_feed(data: bytes, now, source_id: str = "volksfreund") -> tuple[list[Event], dict[str, int]]:
    stats = {"total": 0, "other_topic": 0, "no_place": 0, "person": 0}
    events: list[Event] = []
    for item in parse_rss(data):
        stats["total"] += 1
        cats = {c.casefold() for c in item.categories}
        if not cats & KEEP_CATEGORIES:
            stats["other_topic"] += 1
            continue
        if PERSON_TARGETED.search(item.title):
            stats["person"] += 1
            continue
        place = locate_text(item.title)
        if place is None or not geo.in_region(place.lat, place.lon):
            stats["no_place"] += 1
            continue
        sev: Severity = "notice" if NOTICE.search(item.title) else "info"
        uid = hashlib.sha1(item.link.encode()).hexdigest()[:16]
        events.append(Event(
            id=f"{source_id}:{uid}", source_id=source_id, type="news",
            title=clean_text(item.title, 300), summary=clean_text(f"Ort laut Schlagzeile: {place.name}", 200),
            severity=sev, confidence=place.confidence,
            geometry={"type": "Point", "coordinates": [place.lon, place.lat]},
            region_tag="DE-RLP", valid_from=item.published, valid_to=item.published + timedelta(hours=VALID_HOURS),
            fetched_at=now, raw_ref=item.link,
            attrs={"kind": "presse", "ort": place.name, "ort_genau": False},
        ))
    return events, stats


class VolksfreundCollector(Collector):
    async def collect(self) -> CollectResult:
        data = await self.fetch_bytes(self.entry.url, timeout=30.0)
        events, st = parse_feed(data, utcnow(), self.entry.id)
        note = (f"{len(events)} von {st['total']} Schlagzeilen verortet (andere Rubrik {st['other_topic']}, "
                f"ohne Ort {st['no_place']}, Personenbezug {st['person']})")
        return CollectResult(events=events, note=note)


COLLECTOR = VolksfreundCollector
