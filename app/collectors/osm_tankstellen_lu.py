"""Tankstellen in Luxemburg aus OpenStreetMap (nur Standort und Marke).

Quelle:     Overpass API, eine Abfrage: amenity=fuel im Staatsgebiet Luxemburg (ISO3166-1 = LU)
Betreiber:  OpenStreetMap-Mitwirkende, Overpass-Instanz (Fair-Use-Richtlinie)
Lizenz:     ODbL 1.0, Namensnennung "© OpenStreetMap-Mitwirkende"
Intervall:  einmal je Woche
Ablage:     Cache-Eintrag "lu_stations": {"items": [{id, name, lat, lon}]}. Kein Ereignis.
Beispiel:   python -m app.collect --once --only osm_tankstellen_lu

Gespeichert werden nur Marke oder Name, Koordinate und OSM-Kennung; keine Adressen, Telefonnummern, Öffnungszeiten, Betreiber- oder Freitextfelder.
Preise gibt es hier nicht: Die Anzeige verbindet die Standorte mit dem amtlichen Höchstpreis (statec_sprit) und sagt das auch so.
"""
from __future__ import annotations

from typing import Any

from .. import geo
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError
from .osm_natur import MIRRORS

QUERY = '[out:json][timeout:50];area["ISO3166-1"="LU"][admin_level=2]->.a;nwr["amenity"="fuel"](area.a);out center tags;'
TIMEOUT_S = 70.0
MAX_ITEMS = 400


def parse_elements(data: Any) -> list[dict[str, Any]]:
    """Overpass-JSON → Tankstellen im Radius. Reine Funktion."""
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise SourceError("Overpass: unerwartete Antwort (kein 'elements')")
    out: dict[str, dict[str, Any]] = {}
    for el in data["elements"]:
        if not isinstance(el, dict):
            continue
        tags = el.get("tags") if isinstance(el.get("tags"), dict) else {}
        c = el.get("center") or el
        try:
            lat, lon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not geo.in_region(lat, lon):
            continue
        oid = f"{el.get('type', 'node')}/{el.get('id')}"
        name = clean_text(tags.get("brand") or tags.get("name") or "", 60) or "Tankstelle"
        out[oid] = {"id": oid, "name": name, "lat": round(lat, 5), "lon": round(lon, 5)}
    return sorted(out.values(), key=lambda i: i["id"])[:MAX_ITEMS]


class OsmTankstellenLuCollector(Collector):
    async def collect(self) -> CollectResult:
        last: SourceError | None = None
        for url in MIRRORS:
            try:
                resp = await self._request(url, {"data": QUERY}, "application/json", False, (), TIMEOUT_S)
                assert resp is not None
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise SourceError("Overpass: keine JSON-Antwort (Instanz überlastet?)") from exc
                if isinstance(data, dict) and data.get("remark") and not data.get("elements"):
                    raise SourceError(f"Overpass: {clean_text(str(data['remark']), 120)}")
                items = parse_elements(data)
                if not items:
                    raise SourceError("Overpass: keine Tankstellen in Luxemburg gefunden")
                return CollectResult(cache={"lu_stations": {"items": items}}, writes_events=False)
            except SourceError as exc:
                last = exc
                self.log.warning("%s: %s, nächster Spiegel", url, exc)
        assert last is not None
        raise last


COLLECTOR = OsmTankstellenLuCollector
