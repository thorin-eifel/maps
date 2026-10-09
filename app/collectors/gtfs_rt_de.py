"""Verspätungen und Störungen im Regionalverkehr (GTFS-Realtime, gtfs.de / DELFI).

Quelle:     https://realtime.gtfs.de/realtime-free.pb  (Protobuf, bundesweit, etwa 14 MB, Stand alle 10 Sekunden)
Betreiber:  DELFI e. V. / gtfs.de, Daten der Verkehrsverbünde und der DB
Lizenz:     CC BY-SA 4.0 (Namensnennung, Weitergabe unter gleichen Bedingungen; ohne Gewähr)
Intervall:  600 s (bei 14 MB je Abruf reicht das; der Feed selbst ist nicht abrufbeschränkt dokumentiert)
Voraussetzung: gtfs_static ist gelaufen (Cache "gtfs_index"); ohne Index wüssten wir nicht, welche Fahrten unseren Radius berühren.
Beispiel:   python -m app.collect --once --only gtfs_rt_de

Nur Fahrten, die an einer Haltestelle im Radius halten, werden übernommen; Ort des Ereignisses ist diese Haltestelle
(bei Verspätung die mit dem größten Verzug, bei Ausfall die erste im Radius). Keine Fahrzeugpositionen, keine Personen.
Verspätung ab 5 Minuten: info, ab 10: notice, ab 20: warning; Ausfall und entfallender Halt: notice; Störungsmeldungen
(ServiceAlerts) zu Haltestellen oder Fahrten im Radius, die nach Störung klingen (Sperrung, Ausfall, Umleitung ...): notice.
Ist der Feed selbst älter als 20 Minuten, gilt der Lauf als Fehler, damit keine alten Zahlen als aktuell erscheinen.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import Event, Severity, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

MIN_DELAY_S = 300
NOTICE_DELAY_S = 600
WARNING_DELAY_S = 1200
VALID_MIN = 30
MAX_FEED_AGE_MIN = 20
CANCELED = 3     # TripDescriptor.ScheduleRelationship.CANCELED
SKIPPED = 1      # StopTimeUpdate.ScheduleRelationship.SKIPPED
NO_SERVICE = 1   # Alert.Effect.NO_SERVICE
PROVENANCE = "Echtzeitdaten aufbereitet von"   # der Feed führt Herkunftshinweise als "Alerts" ohne Störungsinhalt
# Der Feed mischt unter "Alerts" Ausstattungshinweise (WLAN, Fahrradmitnahme, Rollstuhlstellplatz) mit echten Störungen; Effekt und Ursache
# sind bei allen gleich (unbekannt). Übernommen wird nur, was nach Störung klingt. Bewusst eng gefasst: lieber eine Meldung zu wenig.
DISRUPTION = re.compile(r"streckensperrung|sperrung|gesperrt|entfall|entfäll|ausfall|ausfäll|haltausf|störung|umleitung|schienenersatz|streik|unfall", re.I)


def _text(ts) -> str:
    """Übersetzungstext bevorzugt Deutsch, sonst die erste Fassung."""
    best = ""
    for tr in ts.translation:
        if tr.language.lower().startswith("de"):
            return tr.text
        best = best or tr.text
    return best


def parse_feed(blob: bytes, index: dict[str, Any], now: datetime) -> tuple[list[Event], dict[str, int]]:
    try:
        from google.transit import gtfs_realtime_pb2 as pb
    except ImportError as exc:  # pragma: no cover - Umgebungsfehler
        raise SourceError("Paket gtfs-realtime-bindings fehlt (pip install -r requirements.txt)") from exc
    fm = pb.FeedMessage()
    try:
        fm.ParseFromString(blob)
    except Exception as exc:  # noqa: BLE001 - das Protobuf-Paket wirft eigene Fehlertypen
        raise SourceError(f"GTFS-RT nicht lesbar: {type(exc).__name__}") from exc
    ts = fm.header.timestamp
    if ts and now - datetime.fromtimestamp(ts, timezone.utc) > timedelta(minutes=MAX_FEED_AGE_MIN):
        raise SourceError(f"Echtzeitfeed veraltet (Stand {datetime.fromtimestamp(ts, timezone.utc):%H:%M} UTC)")

    stops, trips = index["stops"], index["trips"]
    events: dict[str, Event] = {}
    stat = {"trips_in_feed": 0, "trips_matched": 0, "alerts_matched": 0}

    def place(stop_id: str | None) -> tuple[float, float, str] | None:
        s = stops.get(stop_id or "")
        return (s[2], s[1], s[0]) if s else None

    def make(uid: str, kind: str, title: str, summary: str, sev: Severity, loc: tuple[float, float, str], attrs: dict[str, Any]) -> None:
        events[uid] = Event(
            id=uid, source_id="gtfs_rt_de", type="transit", title=clean_text(title, 200), summary=clean_text(summary, 500),
            severity=sev, geometry={"type": "Point", "coordinates": [round(loc[0], 5), round(loc[1], 5)]}, region_tag="DE-RLP",
            valid_from=now, valid_to=now + timedelta(minutes=VALID_MIN), fetched_at=now, raw_ref=None,
            attrs={"kind": kind, "stop": loc[2], **attrs})

    for ent in fm.entity:
        if ent.HasField("trip_update"):
            tu = ent.trip_update
            stat["trips_in_feed"] += 1
            info = trips.get(tu.trip.trip_id)
            if info is None:
                continue
            stat["trips_matched"] += 1
            line, head, mode, first = info
            day = tu.trip.start_date or f"{now:%Y%m%d}"
            uid = f"gtfsrt:{tu.trip.trip_id}:{day}"
            label = f"{line} nach {head}" if head else line or "Fahrt"
            base = {"line": line, "headsign": head, "mode": mode}
            if tu.trip.schedule_relationship == CANCELED:
                loc = place(first)
                if loc:
                    make(uid, "ausfall", f"{label}: Fahrt fällt aus", f"Die Fahrt {label} entfällt laut Echtzeitdaten.", "notice", loc, base)
                continue
            worst: tuple[int, str] | None = None
            skipped: str | None = None
            for su in tu.stop_time_update:
                if su.stop_id not in stops:
                    continue
                if su.schedule_relationship == SKIPPED:
                    skipped = skipped or su.stop_id
                    continue
                d = su.departure.delay if su.HasField("departure") and su.departure.HasField("delay") else (
                    su.arrival.delay if su.HasField("arrival") and su.arrival.HasField("delay") else None)
                if d is not None and (worst is None or d > worst[0]):
                    worst = (d, su.stop_id)
            if worst and worst[0] >= MIN_DELAY_S:
                loc = place(worst[1])
                minutes = round(worst[0] / 60)
                sev: Severity = "warning" if worst[0] >= WARNING_DELAY_S else "notice" if worst[0] >= NOTICE_DELAY_S else "info"
                if loc:
                    make(uid, "verspaetung", f"{label}: +{minutes} min", f"{label} hat an dieser Haltestelle laut Echtzeitdaten {minutes} Minuten Verspätung.",
                         sev, loc, {**base, "delay_min": minutes})
            elif skipped and (loc := place(skipped)):
                make(uid, "halt_entfaellt", f"{label}: Halt entfällt", f"Die Fahrt {label} hält hier laut Echtzeitdaten nicht.", "notice", loc, base)
        elif ent.HasField("alert"):
            al = ent.alert
            headline = _text(al.header_text)
            body = _text(al.description_text)
            if not headline or body.startswith(PROVENANCE) or not DISRUPTION.search(headline):
                continue   # Herkunfts- oder Ausstattungshinweis, keine Störung
            loc = None
            for ie in al.informed_entity:
                loc = place(ie.stop_id) or (place(trips[ie.trip.trip_id][3]) if ie.trip.trip_id in trips else None)
                if loc:
                    break
            if not loc:
                continue
            stat["alerts_matched"] += 1
            head = headline
            make(f"gtfsrt-alert:{ent.id}", "stoerung", head, body or head,
                 "notice", loc, {})
    return list(events.values()), stat


class GtfsRtDeCollector(Collector):
    async def collect(self) -> CollectResult:
        cached = (self.storage.cache_get("gtfs_index") or {}).get("payload", {}).get("feeds", {})
        stops: dict[str, Any] = {}
        trips: dict[str, Any] = {}
        for f in cached.values():
            if f.get("trips"):
                stops.update(f["stops"])
                trips.update(f["trips"])
        if not trips:
            raise SourceError("GTFS-Index fehlt: zuerst python -m app.collect --once --only gtfs_static")
        blob = await self.fetch_bytes(self.entry.url, timeout=90.0)
        now = utcnow()
        events, stat = await asyncio.to_thread(parse_feed, blob, {"stops": stops, "trips": trips}, now)
        self.log.info("Feed: %d Fahrten, davon %d im Radius bekannt; %d Störungsmeldungen im Radius",
                      stat["trips_in_feed"], stat["trips_matched"], stat["alerts_matched"])
        note = None
        if stat["trips_in_feed"] and not stat["trips_matched"]:
            note = "keine Fahrt des Feeds im Fahrplanindex gefunden (Kennungen prüfen)"
        elif not events:
            note = "keine Verspätungen ab 5 Minuten im Radius"
        return CollectResult(events=events, complete=True, note=note)


COLLECTOR = GtfsRtDeCollector
