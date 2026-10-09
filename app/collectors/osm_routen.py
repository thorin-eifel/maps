"""Wander- und Radrouten aus OpenStreetMap (nur überregional benannte Routen), als Linien für die Karte.

Quelle:     Overpass API (https://overpass-api.de/api/interpreter), je eine Abfrage für Wanderrouten und Radrouten (Relationen mit Geometrie)
Betreiber:  OpenStreetMap-Mitwirkende, Overpass-Instanz von Roland Olbricht (Fair-Use-Richtlinie, keine Schlüssel)
Lizenz:     ODbL 1.0, Namensnennung "© OpenStreetMap-Mitwirkende"
Intervall:  einmal je Woche (604800 s); Routen ändern sich selten
Auswahl:    Wandern: Fern-, National- und Regionalwanderwege (iwn, nwn, rwn); Rad: internationale, nationale, regionale Routen (icn, ncn, rcn).
            Lokale Rundwege fehlen mit Absicht (Menge).
Ablage:     Cache-Eintrag "routen" (Liste von Routen mit vereinfachten Linien), kein Ereignis. Export als routen.json.
Beispiel:   python -m app.collect --once --only osm_routen

Gespeichert werden Art, Name, Kennzeichen (ref), Netzebene und die Linie, auf 4 Nachkommastellen (ca. 10 m) gerundet und vereinfacht
(Douglas-Peucker, ca. 25 m). Keine Betreiber, Kontakte, Beschreibungen oder Bearbeiternamen.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

from .. import config, geo
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

ENDPOINT = "https://overpass-api.de/api/interpreter"
MIRRORS = ("https://z.overpass-api.de/api/interpreter", ENDPOINT, "https://overpass.private.coffee/api/interpreter")
TIMEOUT_S = 120.0
PAUSE_S = 5.0
TOLERANCE_DEG = 0.0004
MAX_PER_KIND = 300       # je Art; bei Überschuss gewinnen höhere Netzebene (international vor regional), dann längere Routen
MAX_POINTS = 100000       # Gesamtbudget (je Art die Hälfte)
NET_RANK = {"iwn": 0, "icn": 0, "nwn": 1, "ncn": 1, "rwn": 2, "rcn": 2}

KINDS = (("hike", "hiking", "iwn|nwn|rwn"), ("bike", "bicycle", "icn|ncn|rcn"))


def build_query(entry: tuple[str, str, str]) -> str:
    s, w, n, e = config.BBOX
    _, route, nets = entry
    return f'[out:json][timeout:110];relation["route"="{route}"]["network"~"^({nets})$"]["name"]({s},{w},{n},{e});out geom;'


def _perp(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def simplify(pts: list[tuple[float, float]], tol: float = TOLERANCE_DEG) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterativ (kein Rekursionslimit bei langen Wegen)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        far, idx = 0.0, -1
        for k in range(i + 1, j):
            d = _perp(pts[k], pts[i], pts[j])
            if d > far:
                far, idx = d, k
        if idx >= 0 and far > tol:
            keep[idx] = True
            stack.extend(((i, idx), (idx, j)))
    return [p for p, k in zip(pts, keep) if k]


def parse_elements(data: Any, kind: str) -> list[dict[str, Any]]:
    """Overpass-JSON (Relationen mit Geometrie) in Routen mit Linien im Radius. Reine Funktion für Fixtures."""
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise SourceError("Overpass: unerwartete Antwort (kein 'elements')")
    out: list[dict[str, Any]] = []
    for el in data["elements"]:
        if not isinstance(el, dict) or el.get("type") != "relation":
            continue
        tags = el.get("tags") or {}
        name = clean_text(tags.get("name") or "", 80)
        if not name:
            continue
        lines: list[list[list[float]]] = []
        for m in el.get("members") or []:
            geom = m.get("geometry") if isinstance(m, dict) and m.get("type") == "way" else None
            if not isinstance(geom, list):
                continue
            pts: list[tuple[float, float]] = []
            for g in geom:
                try:
                    pts.append((float(g["lon"]), float(g["lat"])))
                except (KeyError, TypeError, ValueError):
                    continue
            if len(pts) < 2:
                continue
            if not any(geo.in_region(la, lo) for lo, la in pts):
                continue
            lines.append([[round(lo, 4), round(la, 4)] for lo, la in simplify(pts)])
        if lines:
            out.append({"id": f"relation/{el.get('id')}", "kind": kind, "name": name, "ref": clean_text(tags.get("ref") or "", 20),
                        "network": clean_text(tags.get("network") or "", 4), "lines": lines})
    return out


class OsmRoutenCollector(Collector):
    async def _one(self, entry: tuple[str, str, str]) -> list[dict[str, Any]]:
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
                return parse_elements(data, entry[0])
            except SourceError as exc:
                last = exc
                self.log.warning("%s: %s, nächster Spiegel", url, exc)
        assert last is not None
        raise last

    async def collect(self) -> CollectResult:
        old = (self.storage.cache_get("routen") or {}).get("payload", {}).get("items", [])
        items: list[dict[str, Any]] = []
        failed: list[str] = []
        first_err = ""
        for n, entry in enumerate(KINDS):
            if n:
                await asyncio.sleep(PAUSE_S)
            try:
                items.extend(await self._one(entry))
            except SourceError as exc:
                failed.append(entry[0])
                first_err = first_err or str(exc)
                self.log.warning("%s: %s", entry[0], exc)
        if len(failed) == len(KINDS):
            raise SourceError(f"Overpass: keine Abfrage lieferbar ({first_err})")
        items.extend(i for i in old if i["kind"] in failed)       # ausgefallene Art: letzter Stand bleibt
        kept: list[dict[str, Any]] = []
        for kind, _, _ in KINDS:
            mine = [i for i in items if i["kind"] == kind]
            mine.sort(key=lambda i: (NET_RANK.get(i["network"], 3), -sum(len(x) for x in i["lines"]), i["id"]))
            budget = MAX_POINTS // len(KINDS)                      # Punktbudget je Art: höhere Netzebene zuerst, Rest entfällt
            for it in mine[:MAX_PER_KIND]:
                n_pts = sum(len(x) for x in it["lines"])
                if n_pts > budget:
                    continue
                budget -= n_pts
                kept.append(it)
        items = sorted(kept, key=lambda i: (i["kind"], i["name"], i["id"]))
        total = 0
        for it in items:                                          # Gesamtgröße deckeln
            total += sum(len(line) for line in it["lines"])
        if total > MAX_POINTS:
            raise SourceError(f"Routen zu groß ({total} Punkte), Abfrage prüfen")
        counts = {k: sum(1 for i in items if i["kind"] == k) for k, _, _ in KINDS}
        self.log.info("%d Routen, %d Punkte: %s", len(items), total, counts)
        note = f"teilweise: {', '.join(failed)} fehlgeschlagen, letzter Stand bleibt" if failed else (None if items else "keine Routen im Radius gefunden")
        return CollectResult(cache={"routen": {"items": items, "counts": counts}}, complete=not failed, note=note, writes_events=False)


COLLECTOR = OsmRoutenCollector
