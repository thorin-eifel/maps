"""Landmarken aus OpenStreetMap: Natur (Höhlen, Wasserfälle, Quellen, Aussichtspunkte, Felsen, Vulkane) und Kultur (Burgen, Ruinen,
Ausgrabungen, Klöster, historische Gebäude).

Quelle:     Overpass API (https://overpass-api.de/api/interpreter), eine kurze Abfrage je Art (8 je Lauf, 3 s Pause) für den Vorfilter-Kasten
Betreiber:  OpenStreetMap-Mitwirkende, Overpass-Instanz von Roland Olbricht (Fair-Use-Richtlinie, keine Schlüssel)
Lizenz:     ODbL 1.0, Namensnennung "© OpenStreetMap-Mitwirkende" (steht schon in der Kartenquelle)
Intervall:  einmal je Woche (604800 s); Landmarken ändern sich selten, die Instanz soll geschont werden
Ablage:     Cache-Eintrag "landmarks" (Liste kompakter Objekte), kein Ereignis. Export als landmarks.json.
Beispiel:   python -m app.collect --once --only osm_natur

Kultur: historic=castle|fort|manor (Art castle), ruins, archaeological_site (archaeological), monastery, building|city_gate|tower (building).
Nur benannte Objekte. Gedenkorte (historic=memorial, Stolpersteine, Gedenktafeln) fehlen mit Absicht: sie nennen oft Personen.
Gipfel fehlen hier mit Absicht: Name und Höhe stehen schon in den eigenen Kacheln (pois/peak), das Frontend zeichnet sie von dort.
Gespeichert werden nur Art, Name, Höhe, Koordinate und OSM-Kennung. Freitextfelder (description, operator, contact:*, Fotos,
Bearbeiternamen) werden nicht übernommen. Unbenannte Quellen und Felsen fallen weg (zu viele, ohne Aussage);
unbenannte Höhlen, Wasserfälle und Aussichtspunkte bleiben, weil schon ihre Lage eine Aussage ist.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from .. import config, geo
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError
from .osm_tiles import tiles

ENDPOINT = "https://overpass-api.de/api/interpreter"
MIRRORS = ("https://z.overpass-api.de/api/interpreter", ENDPOINT, "https://overpass.private.coffee/api/interpreter")  # z. antwortet, wenn der Hauptname 504 gibt; danach der Reihe nach weiter
TIMEOUT_S = 70.0
PAUSE_S = 3.0
MAX_ITEMS = 60000   # Radius 120 km: über 6000 Objekte; Rheinland-Pfalz plus 80 km mehr, die Grenze schneidet sonst ganze Arten ab

# (Art, Tag-Prüfung, Name Pflicht)
KINDS = (
    ("cave", ("natural", "cave_entrance"), False),
    ("waterfall", ("waterway", "waterfall"), False),
    ("viewpoint", ("tourism", "viewpoint"), False),
    ("spring", ("natural", "spring"), True),
    ("rock", ("natural", "rock"), True),
    ("rock", ("natural", "stone"), True),
    ("rock", ("natural", "arch"), True),
    ("volcano", ("natural", "volcano"), True),
    # Kultur und Geschichte (nur benannt; Gedenkorte bewusst nicht)
    ("castle", ("historic", "castle"), True),
    ("castle", ("historic", "fort"), True),
    ("castle", ("historic", "manor"), True),
    ("ruins", ("historic", "ruins"), True),
    ("archaeological", ("historic", "archaeological_site"), True),
    ("monastery", ("historic", "monastery"), True),
    ("building", ("historic", "building"), True),
    ("building", ("historic", "city_gate"), True),
    ("building", ("historic", "tower"), True),
)


def build_query(entry: tuple[str, tuple[str, str], bool], box: tuple[float, float, float, float] | None = None) -> str:
    """Eine Abfrage je Eintrag in KINDS: kurze Läufe, ein Zeitlimit trifft nur eine Art statt alles."""
    s, w, n, e = box or config.BBOX
    _, (k, v), named = entry
    name_filter = '["name"]' if named else ""
    return f'[out:json][timeout:50];nwr["{k}"="{v}"]{name_filter}({s},{w},{n},{e});out center tags;'


def _kind_of(tags: dict[str, str]) -> tuple[str, bool] | None:
    for kind, (k, v), named in KINDS:
        if tags.get(k) == v:
            return kind, named
    return None


def _ele(tags: dict[str, str]) -> int | None:
    m = re.match(r"^\s*(-?\d{1,4})(?:[.,]\d+)?\s*(?:m)?\s*$", tags.get("ele", ""))
    return int(m.group(1)) if m else None


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
        name = clean_text(tags.get("name") or "", 80)
        if needs_name and not name:
            continue
        c = el.get("center") or el
        try:
            lat, lon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not geo.in_region(lat, lon):
            continue
        oid = f"{el.get('type', 'node')}/{el.get('id')}"
        item: dict[str, Any] = {"id": oid, "kind": kind, "name": name, "lat": round(lat, 5), "lon": round(lon, 5)}
        ele = _ele(tags)
        if ele is not None:
            item["ele"] = ele
        out[oid] = item
    items = sorted(out.values(), key=lambda i: (i["kind"], i["name"], i["id"]))
    return items[:MAX_ITEMS]


class OsmNaturCollector(Collector):
    async def _one(self, entry: tuple[str, tuple[str, str], bool]) -> list[dict[str, Any]]:
        """Eine Art über alle Kacheln; fällt eine Kachel aus, fällt die Art aus (kein halber Stand)."""
        found: dict[str, dict[str, Any]] = {}
        for n, box in enumerate(tiles()):
            if n:
                await asyncio.sleep(PAUSE_S)
            for it in await self._one_box(entry, box):
                found[it["id"]] = it
        return list(found.values())

    async def _one_box(self, entry: tuple[str, tuple[str, str], bool], box: tuple[float, float, float, float]) -> list[dict[str, Any]]:
        last: SourceError | None = None
        for url in MIRRORS:
            try:
                resp = await self._request(url, {"data": build_query(entry, box)}, "application/json", False, (), TIMEOUT_S)
                assert resp is not None
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise SourceError("Overpass: keine JSON-Antwort (Instanz überlastet?)") from exc
                if isinstance(data, dict) and data.get("remark") and not data.get("elements"):
                    raise SourceError(f"Overpass: {clean_text(str(data['remark']), 120)}")   # Zeitlimit o. ä.: kein Teilstand speichern
                return parse_elements(data)
            except SourceError as exc:
                last = exc
                self.log.warning("%s: %s, nächster Spiegel", url, exc)
        assert last is not None
        raise last

    async def collect(self) -> CollectResult:
        old = (self.storage.cache_get("landmarks") or {}).get("payload", {}).get("items", [])
        items: dict[str, dict[str, Any]] = {}
        failed: list[str] = []
        first_err = ""
        for n, entry in enumerate(KINDS):
            label = f"{entry[1][0]}={entry[1][1]}"
            if n:
                await asyncio.sleep(PAUSE_S)     # Fair Use: nicht im Sekundentakt hintereinander
            try:
                for it in await self._one(entry):
                    items[it["id"]] = it
            except SourceError as exc:
                failed.append(label)
                first_err = first_err or str(exc)
                self.log.warning("%s: %s", label, exc)
        if len(failed) == len(KINDS):
            raise SourceError(f"Overpass: keine Abfrage lieferbar ({first_err})")
        if failed:   # ausgefallene Art: letzter Stand bleibt (gleiche OSM-Kennung wie eine gelieferte Art gewinnt nie, Arten sind disjunkt)
            kinds_failed = {entry[0] for entry in KINDS if f"{entry[1][0]}={entry[1][1]}" in failed}
            kinds_ok = {entry[0] for entry in KINDS if f"{entry[1][0]}={entry[1][1]}" not in failed}
            for it in old:
                if it["kind"] in kinds_failed - kinds_ok:
                    items.setdefault(it["id"], it)
        out = sorted(items.values(), key=lambda i: (i["kind"], i["name"], i["id"]))[:MAX_ITEMS]
        counts: dict[str, int] = {}
        for i in out:
            counts[i["kind"]] = counts.get(i["kind"], 0) + 1
        self.log.info("%d Landmarken: %s", len(out), counts)
        note = f"teilweise: {', '.join(failed)} fehlgeschlagen, letzter Stand bleibt" if failed else (None if out else "keine Landmarken im Radius gefunden")
        return CollectResult(cache={"landmarks": {"items": out, "counts": counts}}, complete=not failed, note=note, writes_events=False)


COLLECTOR = OsmNaturCollector
