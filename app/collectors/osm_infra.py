"""Infrastruktur aus OpenStreetMap: Windräder, Ladesäulen, Notfallpunkte (Defibrillatoren, Feuerwachen, Krankenhäuser)
Sakrales für die Karte um 1450 (Kirchen, Kapellen, Wegkreuze, Bildstöcke),
Wasserbauwerke (Wehre, Schleusen), benannte Brücken und Tunnel, Fähranleger, Rast-, Schutzhütten- und Badeplätze sowie
Mühlen, Furten, Grenzsteine, Galgen und Brunnen (Karte um 1450) sowie Schulen, Rathäuser und Friedhöfe.

Quelle:     Overpass API (https://overpass-api.de/api/interpreter), eine kurze Abfrage je Art (25 je Lauf, 3 s Pause) für den Vorfilter-Kasten
Betreiber:  OpenStreetMap-Mitwirkende, Overpass-Instanz von Roland Olbricht (Fair-Use-Richtlinie, keine Schlüssel)
Lizenz:     ODbL 1.0, Namensnennung "© OpenStreetMap-Mitwirkende"
Intervall:  einmal je Woche (604800 s); Anlagen ändern sich selten
Ablage:     Cache-Eintrag "infrastruktur" (Liste kompakter Objekte), kein Ereignis. Export als infrastruktur.json.
Beispiel:   python -m app.collect --once --only osm_infra
            OSM_INFRA_ONLY=church,weir python -m app.collect --once --only osm_infra   (nur diese Arten neu abfragen, der Rest bleibt vom letzten Stand)

Gespeichert werden nur Art, Koordinate, OSM-Kennung und je Art ein Sachwert: Windrad (Leistung in kW, Name nur wenn vorhanden),
Ladesäule (Zahl der Ladepunkte), Feuerwache, Krankenhaus, Kirche, Kapelle, Schule und Rathaus (Name der Einrichtung). Friedhöfe nur als Punkt (Mittelpunkt der Fläche), ohne Namen. Rast-, Schutzhütten-, Wegkreuz- und Bildstock-Punkte bekommen nur den Standort (keine Inschriften, keine Stifternamen). Defibrillatoren bekommen nur den Standort:
Namen, Betreiber, Telefonnummern, Öffnungszeiten, Freitext und Bearbeiternamen werden nicht übernommen, ebenso keine Adressen.
Sirenen, Hydranten, Umspannwerke und Wasserwerke fehlen mit Absicht (Menge bzw. kritische Infrastruktur).
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from .. import config, geo
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

ENDPOINT = "https://overpass-api.de/api/interpreter"
MIRRORS = ("https://z.overpass-api.de/api/interpreter", ENDPOINT, "https://overpass.private.coffee/api/interpreter")
TIMEOUT_S = 70.0
PAUSE_S = 3.0
MAX_ITEMS = 80000

# (Art, Tag-Bedingungen, Name Pflicht)
KINDS = (
    ("wind", (("power", "generator"), ("generator:source", "wind")), False),
    ("charging", (("amenity", "charging_station"),), False),
    ("aed", (("emergency", "defibrillator"),), False),
    ("fire_station", (("amenity", "fire_station"),), False),
    ("hospital", (("amenity", "hospital"),), True),
    ("church", (("building", "church"),), False),
    ("chapel", (("building", "chapel"),), False),
    ("cross", (("historic", "wayside_cross"),), False),
    ("shrine", (("historic", "wayside_shrine"),), False),
    ("weir", (("waterway", "weir"),), False),
    ("lock", (("waterway", "lock_gate"),), False),
    ("bridge", (("bridge", "yes"),), r"[Bb]r(ü|ue)cke|[Vv]iadu[ck]t|[Pp]ont\b|[Bb]rug\b"),      # nur Brücken, die ihrem Namen nach Brücken sind (sonst jede benannte Straße über Wasser)
    ("tunnel", (("tunnel", "yes"),), r"[Tt]unnel|[Tt]unnel"),
    ("ferry", (("amenity", "ferry_terminal"),), False),
    ("watermill", (("man_made", "watermill"),), False),         # ab hier: Zeichen der Karte um 1450 (Mühlen, Furten, Grenzsteine, Galgen, Brunnen); Namen bleiben weg, Mühlen tragen oft Familiennamen
    ("windmill", (("man_made", "windmill"),), False),
    ("ford", (("ford", "yes"),), False),
    ("border", (("historic", "boundary_stone"),), False),
    ("gallows", (("historic", "gallows"),), False),
    ("well", (("man_made", "water_well"),), False),
    ("picnic", (("tourism", "picnic_site"),), False),
    ("shelter", (("amenity", "shelter"), ("shelter_type", "basic_hut")), False),      # Wanderhütten; Bushaltestellen-Häuschen (shelter_type=public_transport) bleiben draußen
    ("bathing", (("leisure", "bathing_place"),), False),
    ("school", (("amenity", "school"),), True),                # Gemeinwesen: Schulen und Rathäuser als Einrichtung (Name der Einrichtung), Friedhöfe nur als Fläche ohne Namen
    ("townhall", (("amenity", "townhall"),), True),
    ("cemetery", (("landuse", "cemetery"),), False),
)
NAMED_KINDS = ("wind", "fire_station", "hospital", "church", "chapel", "weir", "lock", "bridge", "tunnel", "ferry", "bathing", "school", "townhall")


def build_query(entry: tuple[str, tuple[tuple[str, str], ...], bool]) -> str:
    """Eine Abfrage je Eintrag in KINDS: kurze Läufe, ein Zeitlimit trifft nur eine Art statt alles."""
    s, w, n, e = config.BBOX
    _, tags, named = entry
    cond = "".join(f'["{k}"="{v}"]' for k, v in tags) + (f'["name"~"{named}"]' if isinstance(named, str) else '["name"]' if named else "")
    return f"[out:json][timeout:50];nwr{cond}({s},{w},{n},{e});out center tags;"


def _kind_of(tags: dict[str, str]) -> tuple[str, bool] | None:
    for kind, conds, named in KINDS:
        if all(tags.get(k) == v for k, v in conds):
            return kind, named
    return None


def _kw(raw: str) -> int | None:
    """'3 MW', '2500 kW', '2.3MW', '3000000 W' in Kilowatt; alles andere None."""
    m = re.match(r"^\s*(\d{1,8}(?:[.,]\d+)?)\s*(MW|kW|W)?\s*$", raw or "", re.I)
    if not m:
        return None
    val = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "W").lower()
    kw = val * 1000 if unit == "mw" else val if unit == "kw" else val / 1000
    return int(round(kw)) if 0 < kw < 100000 else None


def _points(raw: str) -> int | None:
    m = re.match(r"^\s*(\d{1,3})\s*$", raw or "")
    return int(m.group(1)) if m and 0 < int(m.group(1)) <= 200 else None


def parse_elements(data: Any) -> list[dict[str, Any]]:
    """Overpass-JSON in kompakte Objekte im Radius. Reine Funktion, damit sie sich mit Fixtures testen lässt."""
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise SourceError("Overpass: unerwartete Antwort (kein 'elements')")
    out: dict[str, dict[str, Any]] = {}
    for el in data["elements"]:
        if not isinstance(el, dict):
            continue
        tags = el.get("tags") or {}
        got = _kind_of(tags) if isinstance(tags, dict) else None
        if not got:
            continue
        kind, needs_name = got
        name = clean_text(tags.get("name") or "", 80) if kind in NAMED_KINDS else ""
        if needs_name and not name:
            continue
        if isinstance(needs_name, str) and not re.search(needs_name, name):
            continue
        c = el.get("center") or el
        try:
            lat, lon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not geo.in_bbox(lat, lon) or geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
            continue
        oid = f"{el.get('type', 'node')}/{el.get('id')}"
        item: dict[str, Any] = {"id": oid, "kind": kind, "name": name, "lat": round(lat, 5), "lon": round(lon, 5)}
        if kind == "wind":
            kw = _kw(tags.get("generator:output:electricity", ""))
            if kw:
                item["kw"] = kw
        elif kind == "charging":
            cap = _points(tags.get("capacity", ""))
            if cap:
                item["points"] = cap
        if kind in ("bridge", "tunnel", "school", "townhall"):          # eine Brücke hat oft mehrere Wege (Richtungsfahrbahnen), ein Schulgelände mehrere Gebäude: je Name und 500-m-Raster einmal
            oid = f"{kind}:{name}:{round(lat / 0.005)}:{round(lon / 0.005)}"
            item["id"] = f"{el.get('type', 'node')}/{el.get('id')}"
            if oid in out:
                continue
        if kind == "bridge" and (tags.get("historic") or re.search(r"\b[Aa]lte[rn]?\b|\b[Vv]ieux\b|\b[Vv]ieille\b|[Rr]ömer|[Rr]oman|[Ss]teinbrücke|[Rr]omain", name)):
            item["old"] = 1                                    # alte Brücke: erscheint auch auf der Karte um 1450
        out[oid] = item
    items = sorted(out.values(), key=lambda i: (i["kind"], i["name"], i["id"]))
    return items[:MAX_ITEMS]


class OsmInfraCollector(Collector):
    async def _one(self, entry: tuple[str, tuple[tuple[str, str], ...], bool]) -> list[dict[str, Any]]:
        last: SourceError | None = None
        for url in MIRRORS:
            try:
                resp = await self._request(url, {"data": build_query(entry)}, "application/json", False, (), TIMEOUT_S)
                assert resp is not None
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise SourceError("Overpass: keine JSON-Antwort (Instanz überlastet?)") from exc
                if isinstance(data, dict) and data.get("remark") and not data.get("elements"):
                    raise SourceError(f"Overpass: {clean_text(str(data['remark']), 120)}")
                return parse_elements(data)
            except SourceError as exc:
                last = exc
                self.log.warning("%s: %s, nächster Spiegel", url, exc)
        assert last is not None
        raise last

    async def collect(self) -> CollectResult:
        old = (self.storage.cache_get("infrastruktur") or {}).get("payload", {}).get("items", [])
        items: dict[str, dict[str, Any]] = {}
        failed: list[str] = []
        first_err = ""
        only = {k.strip() for k in os.environ.get("OSM_INFRA_ONLY", "").split(",") if k.strip()}
        todo = [e for e in KINDS if not only or e[0] in only]
        skipped = [e[0] for e in KINDS if e not in todo]        # nicht abgefragte Arten behalten den letzten Stand
        for n, entry in enumerate(todo):
            if n:
                await asyncio.sleep(PAUSE_S)
            try:
                for it in await self._one(entry):
                    items[it["id"]] = it
            except SourceError as exc:
                failed.append(entry[0])
                first_err = first_err or str(exc)
                self.log.warning("%s: %s", entry[0], exc)
        if len(failed) == len(todo):
            raise SourceError(f"Overpass: keine Abfrage lieferbar ({first_err})")
        for it in old:            # ausgefallene Art: letzter Stand bleibt
            if it["kind"] in failed or it["kind"] in skipped:
                items.setdefault(it["id"], it)
        out = sorted(items.values(), key=lambda i: (i["kind"], i["name"], i["id"]))[:MAX_ITEMS]
        counts: dict[str, int] = {}
        for i in out:
            counts[i["kind"]] = counts.get(i["kind"], 0) + 1
        self.log.info("%d Infrastrukturpunkte: %s", len(out), counts)
        note = f"teilweise: {', '.join(failed)} fehlgeschlagen, letzter Stand bleibt" if failed else (None if out else "keine Objekte im Radius gefunden")
        return CollectResult(cache={"infrastruktur": {"items": out, "counts": counts}}, complete=not failed, note=note, writes_events=False)


COLLECTOR = OsmInfraCollector
