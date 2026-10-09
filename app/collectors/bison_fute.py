"""Verkehrsmeldungen Frankreich, Nationalstraßen ohne Konzession (Bison Futé, DATEX II v2, Grand Est).

Quelle:     https://tipi.bison-fute.gouv.fr/bison-fute-ouvert/publicationsDIR/Evenementiel-DIR/grt/RRN/content.xml
            (SOAP-Hülle um DATEX II v2, Schnappschuss ganz Frankreich, rund 4 MB; wir filtern am Rand auf den Radius)
Betreiber:  Direction générale des infrastructures, des transports et des mobilités (DGITM) / Directions interdépartementales des routes (DIR)
Lizenz:     Licence Ouverte 2.0 (Etalab), Datensatz "Événements routiers sur le réseau routier national non concédé" auf transport.data.gouv.fr
Intervall:  600 s
Beispiel:   python -m app.collect --once --only bison_fute

Nicht enthalten sind konzessionierte Autobahnen (A4, A31 südlich von Metz? je nach Abschnitt: Betreiber wie SANEF/APRR liefern eigene Feeds).
Übernommen werden Unfälle, Hindernisse, liegengebliebene Fahrzeuge, Baustellen, Sperrungen und Fahrstreifensperrungen. Wegfallen: Umleitungs-,
Geschwindigkeits- und Hinweismeldungen, Mäharbeiten. Geometrie: Linie von Anfang bis Ende des Abschnitts, sonst Punkt. Kein Personenbezug;
Quellenangaben der Behörde (Bezirk, Dienststelle) und Verfügungsnummern werden nicht übernommen.
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

D = "{http://datex2.eu/schema/2/2_0}"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
NS = {"d": "http://datex2.eu/schema/2/2_0"}
URL_REF = "https://www.bison-fute.gouv.fr/"

# (Typ, Untertyp-Feld) → Untertyp → (kind, Bezeichnung, Stufe, sperr)
WORKS = {"grassCuttingWork"}
MANAGEMENT: dict[str, tuple[str, str, Severity, str | None]] = {
    "roadClosed": ("sperrung", "Vollsperrung", "warning", "voll"),
    "carriagewayClosures": ("sperrung", "Sperrung einer Richtung", "warning", "richtung"),
    "laneClosures": ("baustelle", "Fahrstreifensperrung", "info", None),
    "contraflow": ("baustelle", "Gegenverkehr", "info", None),
    "singleAlternateLineTraffic": ("baustelle", "Wechselseitige Verkehrsführung", "info", None),
    "narrowLanes": ("baustelle", "Fahrbahnverengung", "info", None),
}
VEHICLE = {"brokenDownVehicle": ("Liegengebliebenes Fahrzeug", "info"), "vehicleStuck": ("Liegengebliebenes Fahrzeug", "info"),
           "abandonedVehicle": ("Verlassenes Fahrzeug", "info"), "vehicleOnFire": ("Fahrzeugbrand", "warning")}
OBSTRUCTION = {"obstructionOnTheRoad": "Hindernis auf der Fahrbahn", "objectOnTheRoad": "Gegenstand auf der Fahrbahn",
               "incident": "Vorfall", "peopleOnRoadway": "Personen auf der Fahrbahn"}
ENVIRONMENT = {"subsidence": "Fahrbahnabsenkung", "rockfalls": "Steinschlag"}


def _dt(text: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat((text or "").strip())
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _points(rec: ET.Element) -> list[list[float]]:
    g = rec.find("d:groupOfLocations", NS)
    if g is None:
        return []
    out: list[list[float]] = []
    for pc in g.iter(D + "pointCoordinates"):
        lat, lon = pc.findtext("d:latitude", namespaces=NS), pc.findtext("d:longitude", namespaces=NS)
        try:
            p = [round(float(lon), 5), round(float(lat), 5)]  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not out or out[-1] != p:
            out.append(p)
    return out


def _geometry(rec: ET.Element) -> dict[str, Any] | None:
    pts = _points(rec)
    if not pts:
        return None
    return {"type": "LineString", "coordinates": [pts[0], pts[-1]]} if len(pts) >= 2 and pts[0] != pts[-1] else {"type": "Point", "coordinates": pts[0]}


def _descriptors(rec: ET.Element, kind: str) -> list[str]:
    res: list[str] = []
    for n in rec.iter(D + "name"):
        if n.findtext("d:tpegOtherPointDescriptorType", namespaces=NS) == kind:
            v = n.findtext(".//d:value", namespaces=NS)
            if v:
                res.append(v.strip())
    return res


def _classify(rec: ET.Element) -> tuple[str, str, Severity, str | None] | None:
    t = (rec.get(XSI_TYPE) or "").split(":")[-1]
    if t == "Accident":
        return "unfall", "Unfall", "notice", None
    if t in ("ConstructionWorks", "MaintenanceWorks"):
        sub = rec.findtext("d:roadMaintenanceType", namespaces=NS) or rec.findtext("d:constructionWorkType", namespaces=NS)
        if sub in WORKS:
            return None
        return "baustelle", "Baustelle" if t == "ConstructionWorks" else "Wartungsarbeiten", "info", None
    if t == "RoadOrCarriagewayOrLaneManagement":
        return MANAGEMENT.get(rec.findtext("d:roadOrCarriagewayOrLaneManagementType", namespaces=NS) or "")
    if t == "VehicleObstruction":
        v = VEHICLE.get(rec.findtext("d:vehicleObstructionType", namespaces=NS) or "")
        return ("warnung", v[0], v[1], None) if v else None  # type: ignore[return-value]
    if t == "GeneralObstruction":
        label = OBSTRUCTION.get(rec.findtext("d:obstructionType", namespaces=NS) or "")
        return ("warnung", label, "notice", None) if label else None
    if t == "EnvironmentalObstruction":
        label = ENVIRONMENT.get(rec.findtext("d:environmentalObstructionType", namespaces=NS) or "")
        return ("warnung", label, "notice", None) if label else None
    return None


def parse_situations(data: bytes, now: datetime, source_id: str = "bison_fute") -> tuple[list[Event], dict[str, int]]:
    """Reine Funktion: DATEX-II-v2-XML → Ereignisse im Radius."""
    if b"<!doctype" in data[:4096].lower() or b"<!entity" in data[:65536].lower():
        raise SourceError("Bison Futé: DOCTYPE/ENTITY im Dokument, abgelehnt")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SourceError(f"Bison Futé: kein gültiges XML ({exc})") from exc
    sits = list(root.iter(D + "situation"))
    if not sits and next(root.iter(D + "publicationTime"), None) is None:
        raise SourceError("Bison Futé: weder Situationen noch publicationTime, Schema geändert?")
    stats = {"situations": len(sits), "skipped_type": 0, "no_geometry": 0, "outside": 0, "ended": 0}
    events: dict[str, Event] = {}
    for sit in sits:
        for rec in sit.findall("d:situationRecord", NS):
            cls = _classify(rec)
            if cls is None:
                stats["skipped_type"] += 1
                continue
            geom = _geometry(rec)
            if geom is None:
                stats["no_geometry"] += 1
                continue
            if not geo.geometry_in_region(geom):
                stats["outside"] += 1
                continue
            start = _dt(rec.findtext("d:validity/d:validityTimeSpecification/d:overallStartTime", namespaces=NS))
            end = _dt(rec.findtext("d:validity/d:validityTimeSpecification/d:overallEndTime", namespaces=NS))
            if rec.findtext("d:validity/d:validityStatus", namespaces=NS) == "suspended" or (end is not None and end <= now):
                stats["ended"] += 1
                continue
            kind, label, sev, sperr = cls
            roads = [r for r in _descriptors(rec, "linkName") if re.match(r"^[A-Z]{1,2}\s?\d{1,4}\w?$", r)]
            road = roads[0].replace(" ", "") if roads else ""
            towns = _descriptors(rec, "townName")
            dirn = ""
            for c in rec.iterfind("d:generalPublicComment", NS):
                txt = c.findtext(".//d:value", namespaces=NS) or ""
                if re.search(r"\bvers\b", txt, re.I) and c.findtext("d:commentType", namespaces=NS) == "locationDescriptor":
                    dirn = txt.strip()
                    break
            attrs: dict[str, Any] = {"kind": "sperrung" if sperr else kind, "land": "FR"}
            if sperr:
                attrs["sperr"] = sperr
            title = clean_text(f"{label}{' ' + road if road else ''}" + (f", {towns[0]}" if towns else ""), 200)
            facts = [dirn] if dirn else []
            if len(towns) >= 2 and towns[0] != towns[-1]:
                facts.append(f"zwischen {towns[0]} und {towns[-1]}")
            rid = rec.get("id") or hashlib.sha1(title.encode()).hexdigest()[:10]
            ev = Event(id=f"{source_id}:{rid}", source_id=source_id, type="traffic", title=title,
                       summary=clean_text("; ".join(facts), 400), severity=sev, geometry=geom, region_tag="FR",
                       valid_from=start, valid_to=end, fetched_at=now, raw_ref=URL_REF, attrs=attrs)
            events[ev.id] = ev
    return list(events.values()), stats


class BisonFuteCollector(Collector):
    async def collect(self) -> CollectResult:
        data = await self.fetch_bytes(self.entry.url, timeout=90.0)
        events, st = parse_situations(data, utcnow(), self.entry.id)
        return CollectResult(events=events, note=f"{len(events)} von {st['situations']} Situationen im Radius (Typ übersprungen {st['skipped_type']}, "
                                                 f"außerhalb {st['outside']}, beendet {st['ended']})")


COLLECTOR = BisonFuteCollector
