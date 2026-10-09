"""Verkehrsmeldungen Luxemburg (CITA, DATEX II 3.6, Autobahnen und Schnellstraßen).

Quelle:     https://cita.lu/info_trafic/datex/situationrecord36 (XML, DATEX II v3)
Betreiber:  Centre d'information et de transport routier (CITA / Administration des ponts et chaussées)
Lizenz:     CC0 1.0 laut Datensatz auf data.public.lu
Intervall:  300 s
Beispiel:   python -m app.collect --once --only cita_lu

Je Situation entsteht ein Ereignis (mehrere Datensätze einer Situation sind meist die zwei Richtungen). Übernommen werden Unfälle, Baustellen und
Wartungsarbeiten, Hindernisse, Veranstaltungen und Störungen im Betrieb (Rastplätze). Technische Störungen von Anlagen fallen weg: sie sagen
dem Fahrer nichts. Geometrie: die Linie des ersten Datensatzes, sonst sein Punkt. Kein Personenbezug (Fahrzeugzahl, Fahrspuren, Straße).
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from .. import geo
from ..models import Event, Severity, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

NS = {"sit": "http://datex2.eu/schema/3/situation", "loc": "http://datex2.eu/schema/3/locationReferencing",
      "com": "http://datex2.eu/schema/3/common", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# DATEX-Typ → (kind, Bezeichnung, Grundstufe)
KINDS: dict[str, tuple[str, str, Severity]] = {
    "Accident": ("unfall", "Unfall", "notice"),
    "ConstructionWorks": ("baustelle", "Baustelle", "info"),
    "MaintenanceWorks": ("baustelle", "Wartungsarbeiten", "info"),
    "GeneralObstruction": ("warnung", "Hindernis", "notice"),
    "PublicEvent": ("warnung", "Veranstaltung", "info"),
    "ServiceDisruption": ("warnung", "Störung im Betrieb", "info"),
}
OBSTRUCTION = {"spillageOnTheRoad": "Verschmutzung der Fahrbahn", "animalsOnTheRoad": "Tiere auf der Fahrbahn",
               "vehicleStuck": "Liegengebliebenes Fahrzeug", "objectOnTheRoad": "Gegenstand auf der Fahrbahn"}


def _dt(text: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat((text or "").strip())
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _geometry(rec: ET.Element) -> dict[str, Any] | None:
    pl = rec.findtext(".//loc:gmlLineString/loc:posList", namespaces=NS)
    if pl:
        nums = [float(x) for x in pl.split()]
        pts = [[round(nums[i + 1], 5), round(nums[i], 5)] for i in range(0, len(nums) - 1, 2)]   # posList: lat lon
        uniq = {tuple(p) for p in pts}
        if len(uniq) >= 2:
            return {"type": "LineString", "coordinates": pts}
        if pts:
            return {"type": "Point", "coordinates": pts[0]}
    lat, lon = rec.findtext(".//loc:pointCoordinates/loc:latitude", namespaces=NS), rec.findtext(".//loc:pointCoordinates/loc:longitude", namespaces=NS)
    if lat and lon:
        return {"type": "Point", "coordinates": [round(float(lon), 5), round(float(lat), 5)]}
    return None


def parse_situations(data: bytes, now: datetime, source_id: str = "cita_lu") -> tuple[list[Event], dict[str, int]]:
    """Reine Funktion: DATEX-II-XML → Ereignisse."""
    if b"<!doctype" in data[:4096].lower() or b"<!entity" in data[:65536].lower():
        raise SourceError("CITA: DOCTYPE/ENTITY im Dokument, abgelehnt")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SourceError(f"CITA: kein gültiges XML ({exc})") from exc
    sits = root.findall("sit:situation", NS)
    if not sits and root.find("com:publicationTime", NS) is None:
        raise SourceError("CITA: weder Situationen noch publicationTime, Schema geändert?")
    stats = {"situations": len(sits), "skipped_type": 0, "no_geometry": 0, "outside": 0}
    events: list[Event] = []
    for sit in sits:
        recs = sit.findall("sit:situationRecord", NS)
        if not recs:
            continue
        rtype = (recs[0].get(XSI_TYPE) or "").split(":")[-1]
        if rtype not in KINDS:
            stats["skipped_type"] += 1
            continue
        geom = _geometry(recs[0])
        if geom is None:
            stats["no_geometry"] += 1
            continue
        if not geo.geometry_within_radius(geom):
            stats["outside"] += 1
            continue
        kind, label, sev = KINDS[rtype]
        road = clean_text(recs[0].findtext(".//loc:roadInformation/loc:roadName", namespaces=NS), 20)
        dest = clean_text(recs[0].findtext(".//loc:roadInformation/loc:roadDestination", namespaces=NS), 120)
        m = re.search(r"\bvers\s+(.+)$", dest, re.I)
        if rtype == "GeneralObstruction":
            label = OBSTRUCTION.get(recs[0].findtext("sit:obstructionType", namespaces=NS) or "", label)
        ops = [recs[i].findtext("sit:impact/sit:numberOfOperationalLanes", namespaces=NS) for i in range(len(recs))]
        blocked = any(o == "0" for o in ops)
        attrs: dict[str, Any] = {"kind": "sperrung" if blocked and rtype != "Accident" else kind, "land": "LU"}
        if blocked:
            sev = "warning"
            attrs["sperr"] = "voll"
        n_veh = recs[0].findtext("sit:totalNumberOfVehiclesInvolved", namespaces=NS)
        facts = [f"{n_veh} Fahrzeuge beteiligt"] if n_veh and n_veh.isdigit() else []
        title = clean_text(f"{label}{' ' + road if road else ''}" + (f", Richtung {m.group(1).strip()}" if m else ""), 200)
        starts = [d for d in (_dt(r.findtext("sit:validity/com:validityTimeSpecification/com:overallStartTime", namespaces=NS)) for r in recs) if d]
        ends = [d for d in (_dt(r.findtext("sit:validity/com:validityTimeSpecification/com:overallEndTime", namespaces=NS)) for r in recs) if d]
        sid = sit.get("id") or hashlib.sha1(title.encode()).hexdigest()[:10]
        events.append(Event(
            id=f"{source_id}:{sid}", source_id=source_id, type="traffic", title=title,
            summary=clean_text("; ".join(facts + ([dest] if dest else [])), 400), severity=sev,
            geometry=geom, region_tag="LU", valid_from=min(starts) if starts else None,
            valid_to=max(ends) if ends else None, fetched_at=now,
            raw_ref="https://cita.lu/info_trafic/", attrs=attrs,
        ))
    return events, stats


class CitaLuCollector(Collector):
    async def collect(self) -> CollectResult:
        data = await self.fetch_bytes(self.entry.url, timeout=45.0)
        events, st = parse_situations(data, utcnow(), self.entry.id)
        return CollectResult(events=events, note=f"{len(events)} von {st['situations']} Situationen (Typ übersprungen {st['skipped_type']}, außerhalb {st['outside']})")


COLLECTOR = CitaLuCollector
