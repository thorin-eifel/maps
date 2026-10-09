"""Waldbrandgefahrenindex (WBI) und Graslandfeuerindex (GLFI) des DWD, Stationsvorhersagen.

Quelle:     https://opendata.dwd.de/climate_environment/CDC/derived_germany/fire_danger_index/{woodland|grassland}/forecast/recent/
            je Station eine Datei *.csv.gz (eine Zeile je Ausgabetag, 7-Tage-Vorhersage wbi_0..wbi_6) plus *_stations_list.txt
Betreiber:  Deutscher Wetterdienst (DWD)
Lizenz:     CC BY 4.0 laut Datensatzbeschreibung des DWD
Intervall:  10800 s (der DWD rechnet einmal täglich in den frühen Morgenstunden)
Beispiel:   python -m app.collect --once --only dwd_waldbrand

Stufen: 1 sehr gering, 2 gering, 3 mittel, 4 hoch, 5 sehr hoch. Ein Ereignis (Typ fire) entsteht je Station erst ab Stufe 3 für heute oder
morgen: notice bei 3, warning bei 4, critical bei 5. Alle Stationen im Radius stehen unabhängig davon mit ihrer 7-Tage-Reihe im Cache
"fire_index" (Anzeige in der Umwelt-Ansicht). Die Zeitangabe "Termin" ist im DWD-Dokument ohne Zeitzone; wir übernehmen nur das Datum.
Amtlich verbindlich sind die Waldbrandwarnungen der Länder, nicht diese Zahl.
"""
from __future__ import annotations

import asyncio
import csv
import gzip
import io
import zlib
from datetime import datetime, timedelta
from typing import Any

from .. import geo
from ..models import Event, Severity, utcnow
from .base import Collector, CollectResult, SourceError

LABEL = {1: "sehr gering", 2: "gering", 3: "mittel", 4: "hoch", 5: "sehr hoch"}
SEVERITY: dict[int, Severity] = {3: "notice", 4: "warning", 5: "critical"}
MAX_GZ_OUT = 2_000_000
PAUSE_S = 0.25


def parse_station_list(raw: bytes) -> list[dict[str, Any]]:
    """Stationsliste (Latin-1, Semikolon): Index; Höhe; Breite; Länge; Name; Bundesland."""
    out = []
    lines = raw.decode("latin-1").splitlines()
    if not lines or "Stationsindex" not in lines[0]:
        raise SourceError("WBI: Stationsliste hat nicht den erwarteten Kopf")
    for line in lines[1:]:
        p = [x.strip() for x in line.split(";")]
        if len(p) < 6:
            continue
        try:
            out.append({"id": p[0], "height": float(p[1]), "lat": float(p[2]), "lon": float(p[3]), "name": p[4], "land": p[5]})
        except ValueError:
            continue
    return out


def parse_series(gz: bytes, prefix: str) -> tuple[str, list[int]] | None:
    """Letzte Zeile einer Stationsdatei → (Ausgabedatum JJJJ-MM-TT, [Stufe Tag 0..6]). None bei leerer Datei."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    text = d.decompress(gz, MAX_GZ_OUT).decode("utf-8", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    if not rows:
        return None
    last = rows[-1]
    try:
        issued = datetime.strptime(last["Termin"].strip()[:8], "%Y%m%d").strftime("%Y-%m-%d")
        vals = [int(last[f"{prefix}_{i}"]) for i in range(7)]
    except (KeyError, ValueError) as exc:
        raise SourceError(f"WBI: Dateischema geändert ({exc})") from exc
    if not all(1 <= v <= 5 for v in vals):
        return None   # Fehlwerte (z. B. -999) nicht als Stufe anzeigen
    return issued, vals


def pick_stations(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    res = []
    for s in stations:
        if geo.in_region(s["lat"], s["lon"]):
            res.append({**s, "distance_km": round(geo.distance_to_ref_km(s["lat"], s["lon"]), 1)})
    return sorted(res, key=lambda s: s["distance_km"])


def thin(stations: list[dict[str, Any]], min_km: float, limit: int) -> list[dict[str, Any]]:
    """Gleichmäßig über die Fläche verteilen: Reihenfolge nach Entfernung vom Bezugspunkt, eine Station nur, wenn keine bereits gewählte
    näher als min_km liegt. Ohne Abstand (0) zählt nur das Limit (bisheriges Verhalten: die nächsten limit Stationen)."""
    if min_km <= 0:
        return stations[:limit]
    out: list[dict[str, Any]] = []
    for s in stations:
        if all(geo.haversine_km(s["lat"], s["lon"], o["lat"], o["lon"]) >= min_km for o in out):
            out.append(s)
            if len(out) >= limit:
                break
    return out


class WaldbrandCollector(Collector):
    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        wood = f"{base}/woodland/forecast/recent/derived_germany_fire_danger_index_woodland_forecast_recent"
        grass = f"{base}/grassland/forecast/recent/derived_germany_fire_danger_index_grassland_forecast_recent"
        stations = pick_stations(parse_station_list(await self.fetch_bytes(f"{wood}_v2-3--0_stations_list.txt", timeout=30.0)))
        stations = thin(stations, float(self.entry.params.get("min_spacing_km", 0)), int(self.entry.params.get("max_stations", 10)))
        if not stations:
            raise SourceError("WBI: keine Station im Radius (Liste geändert?)")
        now = utcnow()
        out, events, failed = [], [], 0
        for s in stations:
            try:
                w = parse_series(await self.fetch_bytes(f"{wood}_{s['id']}_v2-3--0.csv.gz", timeout=30.0), "wbi")
            except SourceError as exc:
                self.log.warning("WBI Station %s: %s", s["id"], exc)
                failed += 1
                continue
            await asyncio.sleep(PAUSE_S)
            try:
                g = parse_series(await self.fetch_bytes(f"{grass}_{s['id']}_v2-0--0.csv.gz", timeout=30.0), "glfi")
            except SourceError:
                g = None   # nicht jede Station hat beide Indizes
            await asyncio.sleep(PAUSE_S)
            if w is None:
                continue
            issued, wbi = w
            out.append({"id": s["id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"], "distance_km": s["distance_km"],
                        "issued": issued, "wbi": wbi, "glfi": g[1] if g else None})
            peak = max(wbi[:2])
            if peak >= 3:
                events.append(Event(
                    id=f"dwd_waldbrand:{s['id']}", source_id=self.entry.id, type="fire",
                    title=f"Waldbrandgefahr {LABEL[peak]} (Stufe {peak}), Station {s['name']}",
                    summary=f"Stufe heute {wbi[0]}, morgen {wbi[1]}. Stationswert des DWD, keine amtliche Waldbrandwarnung.",
                    severity=SEVERITY[peak], geometry={"type": "Point", "coordinates": [round(s["lon"], 4), round(s["lat"], 4)]},
                    region_tag="DE-RLP" if "Rheinland" in s["land"] else "DE", valid_from=now, valid_to=now + timedelta(hours=12),
                    fetched_at=now, raw_ref="https://www.dwd.de/DE/leistungen/waldbrandgef/waldbrandgef.html",
                    attrs={"kind": "waldbrandindex", "wbi": wbi[:3], "glfi": g[1][:3] if g else None, "station": s["name"]},
                ))
        if not out:
            raise SourceError("WBI: keine Station lieferte verwertbare Werte")
        return CollectResult(
            events=events, cache={"fire_index": {"stations": out, "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}},
            complete=failed == 0, note=f"{len(out)} Stationen, {len(events)} ab Stufe 3" + (f", {failed} ohne Antwort" if failed else ""),
        )


COLLECTOR = WaldbrandCollector
