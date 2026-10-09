"""Weinberge und Obstanlagen aus OpenStreetMap als Flächen für die Karte.

Quelle:     Overpass API (https://overpass-api.de/api/interpreter), je Kartenviertel eine Abfrage für landuse=vineyard und landuse=orchard (nur Wege)
Betreiber:  OpenStreetMap-Mitwirkende, Overpass-Instanz von Roland Olbricht (Fair-Use-Richtlinie, keine Schlüssel)
Lizenz:     ODbL 1.0, Namensnennung "© OpenStreetMap-Mitwirkende" (steht schon in der Kartenquelle)
Intervall:  einmal je Woche (604800 s); Anbauflächen ändern sich selten
Grund:      Die eigenen Kacheln (Protomaps-Build) führen weder Weinberge noch Obstanlagen; an Mosel, Saar und Sauer fehlte der Schalter "Obst und Wein" deshalb ohne Wirkung.
Ablage:     Cache-Eintrag "anbau" (Flächen je Art, Ringe vereinfacht), kein Ereignis. Export als anbau.json (GeoJSON).
Beispiel:   python -m app.collect --once --only osm_anbau

Gespeichert werden nur Art, Außenring (auf 5 Nachkommastellen gerundet, Douglas-Peucker ca. 3 m) und OSM-Kennung. Keine Namen, Betreiber, Tags oder
Bearbeiternamen. Relationen (Multipolygone) fehlen: Weinberge sind fast immer einfache Wege. Flächen unter 300 m² fallen weg.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

from .. import config, geo
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError
from .osm_routen import simplify

ENDPOINT = "https://overpass-api.de/api/interpreter"
MIRRORS = ("https://z.overpass-api.de/api/interpreter", ENDPOINT, "https://overpass.private.coffee/api/interpreter")
TIMEOUT_S = 120.0
PAUSE_S = 20.0     # Overpass antwortet bei dichter Folge mit 429
TOLERANCE_DEG = 0.00003
MIN_AREA_M2 = 300.0
MAX_POLYGONS = 30000
KINDS = ("vineyard", "orchard")


def quarters() -> list[tuple[float, float, float, float]]:
    """Vorfilter-Kasten in vier Viertel: kleine Antworten, ein Zeitlimit trifft nur ein Viertel."""
    s, w, n, e = config.BBOX
    ms, mw = (s + n) / 2, (w + e) / 2
    return [(s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)]


def build_query(box: tuple[float, float, float, float]) -> str:
    s, w, n, e = box
    return f'[out:json][timeout:110];(way["landuse"="vineyard"]({s},{w},{n},{e});way["landuse"="orchard"]({s},{w},{n},{e}););out geom tags;'


def area_m2(ring: list[tuple[float, float]]) -> float:
    """Fläche eines Rings (lon, lat) in m² mit lokaler ebener Näherung (Gauß'sche Trapezformel)."""
    if len(ring) < 4:
        return 0.0
    lat0 = sum(p[1] for p in ring) / len(ring)
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 110574.0
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        a += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(a) / 2


def parse_elements(data: Any) -> list[dict[str, Any]]:
    """Overpass-JSON in Flächen im Radius. Reine Funktion, mit Fixtures testbar."""
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise SourceError("Overpass: unerwartete Antwort (kein 'elements')")
    out: dict[str, dict[str, Any]] = {}
    for el in data["elements"]:
        if not isinstance(el, dict) or el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        kind = tags.get("landuse") if isinstance(tags, dict) else None
        if kind not in KINDS:
            continue
        try:
            ring = [(float(p["lon"]), float(p["lat"])) for p in el.get("geometry") or []]
        except (KeyError, TypeError, ValueError):
            continue
        if len(ring) < 4 or ring[0] != ring[-1]:
            continue    # offene Wege sind keine Flächen
        if area_m2(ring) < MIN_AREA_M2:
            continue
        clat = sum(p[1] for p in ring) / len(ring)
        clon = sum(p[0] for p in ring) / len(ring)
        if not geo.in_region(clat, clon):
            continue
        simp = simplify(ring, TOLERANCE_DEG)
        if len(simp) < 4 or simp[0] != simp[-1]:
            simp = ring
        oid = f"way/{el.get('id')}"
        out[oid] = {"id": oid, "kind": kind, "ring": [[round(x, 5), round(y, 5)] for x, y in simp]}
    return sorted(out.values(), key=lambda i: (i["kind"], i["id"]))


class OsmAnbauCollector(Collector):
    async def _one(self, box: tuple[float, float, float, float]) -> list[dict[str, Any]]:
        last: SourceError | None = None
        for url in MIRRORS:
            try:
                resp = await self._request(url, {"data": build_query(box)}, "application/json", False, (), TIMEOUT_S)
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
        old = (self.storage.cache_get("anbau") or {}).get("payload", {}).get("items", [])
        items: dict[str, dict[str, Any]] = {}
        failed = 0
        first_err = ""
        boxes = quarters()
        for n, box in enumerate(boxes):
            if n:
                await asyncio.sleep(PAUSE_S)
            try:
                for it in await self._one(box):
                    items[it["id"]] = it
            except SourceError as exc:
                failed += 1
                first_err = first_err or str(exc)
                self.log.warning("Viertel %d: %s", n, exc)
        if failed == len(boxes):
            raise SourceError(f"Overpass: keine Abfrage lieferbar ({first_err})")
        if failed:    # ein Viertel fehlt: letzter Stand bleibt für Flächen, die diesmal nicht kamen (Randflächen doppelt gleiche Kennung)
            for it in old:
                items.setdefault(it["id"], it)
        out = sorted(items.values(), key=lambda i: (i["kind"], i["id"]))[:MAX_POLYGONS]
        counts: dict[str, int] = {}
        for i in out:
            counts[i["kind"]] = counts.get(i["kind"], 0) + 1
        self.log.info("%d Anbauflächen: %s", len(out), counts)
        note = f"teilweise: {failed} von {len(boxes)} Vierteln fehlgeschlagen, letzter Stand bleibt" if failed else (None if out else "keine Anbauflächen im Radius gefunden")
        return CollectResult(cache={"anbau": {"items": out, "counts": counts}}, complete=not failed, note=note, writes_events=False)


COLLECTOR = OsmAnbauCollector
