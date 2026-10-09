"""Schlagzeilen aus Ostbelgien (BRF, Belgischer Rundfunk der Deutschsprachigen Gemeinschaft, RSS-Feed).

Quelle:     https://brf.be/feed/ (RSS 2.0, vom Sender öffentlich angeboten; robots.txt sperrt nur zwei Profilseiten)
Betreiber:  BRF, Eupen
Lizenz:     keine offene Lizenz; nur Überschrift, Zeit und Link, kein Text, kein Bild (lizenz_geprueft false)
Intervall:  900 s
Beispiel:   python -m app.collect --once --only brf

Wir behalten nur die Rubrik "Regional" (Ostbelgien); National und International fallen weg. Der Ort kommt aus der Überschrift, ersatzweise
aus den Schlagwörtern des Eintrags (BRF verschlagwortet Orte wie "Eupen" oder "Baelen"). Ohne Ort im Radius wird verworfen, nicht geraten.
Personenbezogene Meldungen (Fahndung, Vermisste) fallen weg, wie bei den anderen Pressequellen.
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
KEEP_CATEGORIES = {"regional"}
GENERIC_TAGS = {"regional", "top news", "national", "international", "sport", "kultur", "wirtschaft", "politik"}


def _in_radius(place) -> bool:
    return place is not None and geo.in_region(place.lat, place.lon)


def parse_feed(data: bytes, now, source_id: str = "brf") -> tuple[list[Event], dict[str, int]]:
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
        if not _in_radius(place):
            for tag in item.categories:
                if tag.casefold() in GENERIC_TAGS:
                    continue
                cand = locate_text(tag)
                if _in_radius(cand):
                    place = cand
                    break
        if not _in_radius(place):
            stats["no_place"] += 1
            continue
        sev: Severity = "notice" if NOTICE.search(item.title) else "info"
        uid = hashlib.sha1(item.link.encode()).hexdigest()[:16]
        events.append(Event(
            id=f"{source_id}:{uid}", source_id=source_id, type="news",
            title=clean_text(item.title, 300), summary=clean_text(f"Ort laut Schlagzeile oder Schlagwort: {place.name}", 200),
            severity=sev, confidence=min(place.confidence, 0.7),
            geometry={"type": "Point", "coordinates": [place.lon, place.lat]},
            region_tag="BE", valid_from=item.published, valid_to=item.published + timedelta(hours=VALID_HOURS),
            fetched_at=now, raw_ref=item.link,
            attrs={"kind": "presse", "ort": place.name, "ort_genau": False},
        ))
    return events, stats


class BrfCollector(Collector):
    async def collect(self) -> CollectResult:
        data = await self.fetch_bytes(self.entry.url, timeout=30.0)
        events, st = parse_feed(data, utcnow(), self.entry.id)
        note = (f"{len(events)} von {st['total']} Schlagzeilen verortet (andere Rubrik {st['other_topic']}, "
                f"ohne Ort {st['no_place']}, Personenbezug {st['person']})")
        return CollectResult(events=events, note=note)


COLLECTOR = BrfCollector
