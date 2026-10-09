"""Baustellen und Sperrungen Rheinland-Pfalz (Mobilitätsatlas, WFS).

Quelle:     https://maps.mobilitaetsatlas.de/geoserver/ows  (WFS 2.0.0, Layer mwvlw:baustelle, mwvlw:verlauf)
Betreiber:  Ministerium für Wirtschaft, Verkehr, Landwirtschaft und Weinbau RLP (Mobilitätsatlas), Daten von
            Verkehrsbehörden RLP, LBM und Straßenbauverwaltung Luxemburg
Lizenz:     siehe sources.yaml (in Capabilities und Erläuterung keine Lizenzangabe; Anfrage nötig)
Intervall:  600 s (der Dienst aktualisiert alle 10 Minuten, bis 20 Minuten Verzug)
Beispiel:   python -m app.collect --once --only lbm_baustellen

Abfrage mit Bounding Box (Achsenfolge lat,lon mit CRS-Suffix urn:ogc:def:crs:EPSG::4326) und GeoJSON.
Der Radiusfilter passiert am Rand. Einträge mit quelle == "Autobahn GmbH" werden verworfen: die deckt
der Autobahn-Collector ab, sonst stünde jede Meldung doppelt in der Karte.
Geometrie: Der Verlauf (mwvlw:verlauf, Linien) wird über baustelleId zugeordnet und ersetzt den Punkt.
Ohne Verlauf bleibt der Punkt. Umleitungen (mwvlw:umleitung) sind noch nicht eingebaut.
Datenschutz: Das Feld `ansprechpartner` (Behörden-Postfächer) wird nie gelesen oder gespeichert.
Freitext wird bereinigt und von E-Mail-Adressen und Telefonnummern befreit.
Die Daten sind laut Betreiber nicht vollständig (nicht alle Kommunen liefern).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from .. import config
from ..models import Event, Severity, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

MAX_PAGES = 15   # Rheinland-Pfalz plus 80 km: rund 2.000 Baustellen, Verlauf mit über 5.000 Abschnitten
PAGE = 1000
EXCLUDED_SOURCES = {"autobahn gmbh"}
LU_SOURCES = {"straßenbauverwaltung luxemburg"}

# typ-Kürzel des Dienstes: G Vollsperrung, F Sperrung einer Fahrtrichtung, C halbseitig,
# N Sperrung für Lkw, B Verkehrsraumeinschränkung; Zusatz _GEPLANT = noch nicht begonnen
SEVERITY_BY_TYP: dict[str, Severity] = {"G": "warning", "F": "warning", "C": "notice", "N": "notice", "B": "info"}
_STRASSE = re.compile(r"^([A-Z]{1,2})\s?(\d{1,4})([A-Z]?)$")
_CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|(?:\+|00)?\d[\d\s/()-]{7,}\d")


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _strasse(raw: Any) -> str:
    s = str(raw or "").strip()
    if s == "G" or not s:
        return "Gemeindestraße"
    m = _STRASSE.match(s)
    return f"{m.group(1)} {m.group(2)}{m.group(3)}" if m else s


def _round(coords: Any) -> Any:
    if isinstance(coords, (int, float)):
        return round(float(coords), 5)
    return [_round(c) for c in coords]


class LbmBaustellenCollector(Collector):
    async def _features(self, layer: str) -> list[dict[str, Any]]:
        lat0, lon0, lat1, lon1 = config.BBOX
        out: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            data = await self.fetch_json(
                self.entry.url,
                params={
                    "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": f"mwvlw:{layer}",
                    "outputFormat": "application/json", "srsName": "EPSG:4326",
                    "bbox": f"{lat0},{lon0},{lat1},{lon1},urn:ogc:def:crs:EPSG::4326",
                    "count": PAGE, "startIndex": page * PAGE,
                },
            )
            feats = data.get("features") if isinstance(data, dict) else None
            if not isinstance(feats, list):
                raise SourceError(f"{layer}: Schlüssel 'features' fehlt")
            out.extend(f for f in feats if isinstance(f, dict))
            matched = data.get("numberMatched")
            if len(feats) < PAGE or (isinstance(matched, int) and len(out) >= matched):
                return out
        raise SourceError(f"{layer}: mehr als {MAX_PAGES * PAGE} Treffer, Abbruch")

    async def collect(self) -> CollectResult:
        sites = await self._features("baustelle")
        lines: dict[str, list[Any]] = {}
        note = None
        try:
            for f in await self._features("verlauf"):
                bid = (f.get("properties") or {}).get("baustelleId")
                g = f.get("geometry")
                if bid and isinstance(g, dict) and g.get("type") == "LineString":
                    lines.setdefault(bid, []).append(g["coordinates"])
        except SourceError as exc:
            self.log.warning("Verlauf nicht erreichbar, es bleiben Punkte: %s", exc)
            note = "Verlauf nicht erreichbar, Darstellung als Punkte"
        now = utcnow()
        events: dict[str, Event] = {}
        for f in sites:
            ev = self._normalize(f, lines, now)
            if ev is not None:
                events[ev.id] = ev
        return CollectResult(events=list(events.values()), complete=True, note=note)

    def _normalize(self, f: dict[str, Any], lines: dict[str, list[Any]], now: datetime) -> Event | None:
        fid = str(f.get("id") or "")
        p = f.get("properties")
        g = f.get("geometry")
        if not fid or not isinstance(p, dict) or not isinstance(g, dict):
            return None
        origin = str(p.get("quelle") or "").strip()
        if origin.lower() in EXCLUDED_SOURCES:
            return None
        key = fid.split(".", 1)[-1]
        segs = lines.get(key)
        if segs:
            geometry: dict[str, Any] = (
                {"type": "LineString", "coordinates": _round(segs[0])} if len(segs) == 1
                else {"type": "MultiLineString", "coordinates": _round(segs)}
            )
        else:
            geometry = {"type": g.get("type"), "coordinates": _round(g.get("coordinates"))}
        if not self.keep(geometry):
            return None
        typ = str(p.get("typ") or "")
        base, _, planned = typ.partition("_")
        severity: Severity = SEVERITY_BY_TYP.get(base, "info")
        art = clean_text(str(p.get("art_der_arbeiten") or "Verkehrseinschränkung"), 80)
        title = f"{_strasse(p.get('strasse'))}: {art}" + (" (geplant)" if planned else "")
        desc = _CONTACT.sub("", str(p.get("beschreibung") or ""))
        summary = clean_text(f"{desc} Quelle: {origin}".strip() if origin else desc, 700)
        return Event(
            id="lbmwfs:" + hashlib.sha1(fid.encode()).hexdigest()[:16],
            source_id=self.entry.id,
            type="traffic",
            title=clean_text(title, 200),
            summary=summary,
            severity=severity,
            attrs={"kind": "sperrung" if base in ("G", "F") else "baustelle", **({"sperr": "voll" if base == "G" else "richtung"} if base in ("G", "F") else {})},
            geometry=geometry,
            region_tag="LU" if origin.lower() in LU_SOURCES else "DE-RLP",
            valid_from=_dt(p.get("von")),
            valid_to=_dt(p.get("bis")),
            fetched_at=now,
            raw_ref="https://mobilitaetsatlas.de/",
        )


COLLECTOR = LbmBaustellenCollector
