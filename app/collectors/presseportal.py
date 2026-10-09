"""Polizeimeldungen der Region (Presseportal, Blaulicht-Feeds je Dienststelle).

Quelle:     https://www.presseportal.de/rss/dienststelle_<ID>.rss2 (Register-URL: .../rss; RSS 2.0, öffentlich angeboten, robots.txt erlaubt Feeds)
Betreiber:  news aktuell GmbH (Presseportal); Inhalte stammen von den Dienststellen
Lizenz:     keine offene Lizenz; wir übernehmen nur Überschrift, Ort, Zeit und Link (siehe sources.yaml, lizenz_geprueft false)
Intervall:  600 s (Feed meldet ttl 6 Minuten)
Beispiel:   python -m app.collect --once --only presseportal

Gespeichert wird: Überschrift ohne Dienststellenkürzel ("POL-PPTR:"), Ort aus der Datumszeile ("Prüm (ots) - …"), Zeit, Link.
Der Meldungstext selbst wird nach dem Lesen der Datumszeile verworfen. Meldungen ohne erkennbaren Ort im Radius fallen weg.
Personenbezug: Fahndungen und Vermisstenmeldungen zielen auf einzelne Personen und werden nicht übernommen.
"""
from __future__ import annotations

import hashlib
import re
from datetime import timedelta

from .. import geo
from ..geoparse import locate_dateline
from ..models import Event, Severity, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError
from .rsslib import parse_rss

VALID_HOURS = 72
PREFIX = re.compile(r"^(POL|FW|BPOL|ZOLL|LKA)-[A-Z0-9äöüÄÖÜ]+(?:\s*[A-Z0-9]+)?:\s*", re.I)
DATELINE = re.compile(r"^\s*([^()\n]{2,80}?)\s*\(ots\)")
PERSON_TARGETED = re.compile(r"fahndung|vermisst|\bsuche nach\b|gesucht wird|identifizier", re.I)
NOTICE = re.compile(r"vollsperrung|gefahr|explosion|großbrand|evakuier|ausgetreten|amok|bedroh|gefährlich|schwer(er|e)?\b.*unfall", re.I)


def classify(title: str) -> tuple[str, Severity]:
    sev: Severity = "notice" if NOTICE.search(title) else "info"
    return "polizei", sev


def parse_feed(data: bytes, now, kind: str, feed_name: str) -> tuple[list[Event], dict[str, int]]:
    """Reine Funktion: RSS-Bytes → Ereignisse. Zählt Verworfenes (kein Ort, Personenbezug, außerhalb) für den Laufbericht."""
    stats = {"total": 0, "no_place": 0, "person": 0, "outside": 0}
    events: list[Event] = []
    for item in parse_rss(data, keep_description=True):
        stats["total"] += 1
        title = PREFIX.sub("", item.title).strip()
        if PERSON_TARGETED.search(title):
            stats["person"] += 1
            continue
        m = DATELINE.match(item.description)
        place = locate_dateline(m.group(1)) if m else None
        if place is None:
            stats["no_place"] += 1
            continue
        if not geo.in_region(place.lat, place.lon):
            stats["outside"] += 1
            continue
        _, sev = classify(title)
        uid = hashlib.sha1(item.link.encode()).hexdigest()[:16]
        events.append(Event(
            id=f"presseportal:{uid}", source_id="presseportal", type="news",
            title=clean_text(title, 300), summary=clean_text(f"{feed_name}, Ort laut Meldung: {m.group(1).strip()}", 200),
            severity=sev, confidence=place.confidence,
            geometry={"type": "Point", "coordinates": [place.lon, place.lat]},
            region_tag="DE-RLP", valid_from=item.published, valid_to=item.published + timedelta(hours=VALID_HOURS),
            fetched_at=now, raw_ref=item.link,
            attrs={"kind": kind, "ort": place.name, "ort_genau": place.confidence >= 0.85, "dienststelle": feed_name},
        ))
    return events, stats


class PresseportalCollector(Collector):
    async def collect(self) -> CollectResult:
        feeds = self.entry.params.get("feeds") or []
        if not feeds:
            raise SourceError("Presseportal: params.feeds fehlt im Register")
        now = utcnow()
        events: dict[str, Event] = {}
        failed: list[str] = []
        totals = {"total": 0, "no_place": 0, "person": 0, "outside": 0}
        for f in feeds:
            url = f"{self.entry.url.rstrip('/')}/dienststelle_{int(f['id'])}.rss2"
            try:
                data = await self.fetch_bytes(url, timeout=30.0)
                evs, st = parse_feed(data, now, f.get("kind", "polizei"), str(f.get("name", f["id"])))
            except SourceError as exc:
                self.log.warning("Feed %s: %s", f.get("id"), exc)
                failed.append(str(f.get("id")))
                continue
            events.update({e.id: e for e in evs})
            for k, v in st.items():
                totals[k] += v
        if len(failed) == len(feeds):
            raise SourceError("Presseportal: kein Feed erreichbar")
        note = (f"{len(events)} von {totals['total']} Meldungen verortet (ohne Ort {totals['no_place']}, "
                f"Personenbezug {totals['person']}, außerhalb {totals['outside']})")
        if failed:
            note += f"; Feeds ohne Antwort: {', '.join(failed)}"
        return CollectResult(events=list(events.values()), complete=not failed, note=note)


COLLECTOR = PresseportalCollector
