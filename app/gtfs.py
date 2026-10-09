"""GTFS-Fahrplandaten auf den Radius zuschneiden.

Zweck:    Aus einem GTFS-ZIP (Luxemburg, DELFI/gtfs.de) die Haltestellen im 120-km-Radius und, wenn gewünscht, die Fahrten
          herausziehen, die dort halten. Ergebnis ist klein (einige 100 kB bis wenige MB) und liegt im Cache der Datenbank;
          das ZIP selbst wird nicht aufbewahrt.
Aufruf:   Nicht direkt; benutzt von app.collectors.gtfs_static (python -m app.collect --once --only gtfs_static).

Ablauf in zwei Durchgängen über stop_times.txt (Zeile für Zeile, nichts wird ganz in den Speicher geladen):
1. Fahrten, die an mindestens einer Haltestelle im Radius halten.
2. Verkehrsart je Haltestelle (Bahn, Tram, Bus) über die Fahrten, die dort halten.
Das Ergebnis enthält keine Personen und keine Fahrgastdaten, nur Fahrplan-Stammdaten.
"""
from __future__ import annotations

import csv
import io
import zipfile
from typing import Any, Iterator

from . import config, geo

# Verkehrsart aus route_type (GTFS-Basis und erweiterte Typen der Verkehrsverbünde)
def mode_of(route_type: int) -> str:
    if route_type == 2 or 100 <= route_type <= 199:
        return "rail"
    if route_type in (0, 1) or 900 <= route_type <= 999 or 400 <= route_type <= 499:
        return "tram"
    if route_type == 3 or 700 <= route_type <= 799 or 200 <= route_type <= 299:
        return "bus"
    return "other"


def _rows(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zf.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def _in_radius(lat: float, lon: float) -> bool:
    return geo.in_bbox(lat, lon) and geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) <= config.RADIUS_KM


def build_index(zip_bytes: bytes, keep_trips: bool) -> dict[str, Any]:
    """stops: {stop_id: [name, lat, lon, modi]}, trips (nur mit keep_trips): {trip_id: [Linie, Ziel, Modus, erste Haltestelle im Radius]}."""
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = set(zf.namelist())
    for need in ("stops.txt", "stop_times.txt", "trips.txt", "routes.txt"):
        if need not in names:
            raise ValueError(f"GTFS: {need} fehlt")

    stops: dict[str, list[Any]] = {}
    for r in _rows(zf, "stops.txt"):
        if r.get("location_type") not in (None, "", "0"):   # nur Haltepunkte, keine Bahnhofsflächen oder Eingänge
            continue
        try:
            lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
        except (KeyError, ValueError):
            continue
        if _in_radius(lat, lon):
            stops[r["stop_id"]] = [(r.get("stop_name") or "").strip(), round(lat, 5), round(lon, 5), set()]

    touching: dict[str, str] = {}      # trip_id → erste Haltestelle im Radius (Ortsangabe für ausfallende Fahrten)
    for r in _rows(zf, "stop_times.txt"):
        if r["stop_id"] in stops:
            touching.setdefault(r["trip_id"], r["stop_id"])

    route_of: dict[str, tuple[str, str]] = {}      # trip_id → (route_id, headsign)
    for r in _rows(zf, "trips.txt"):
        if r["trip_id"] in touching:
            route_of[r["trip_id"]] = (r["route_id"], (r.get("trip_headsign") or "").strip())
    routes: dict[str, tuple[str, int]] = {}
    for r in _rows(zf, "routes.txt"):
        try:
            rtype = int(r.get("route_type") or 3)
        except ValueError:
            rtype = 3
        routes[r["route_id"]] = ((r.get("route_short_name") or r.get("route_long_name") or "").strip(), rtype)

    trip_mode = {t: mode_of(routes.get(rid, ("", 3))[1]) for t, (rid, _) in route_of.items()}
    for r in _rows(zf, "stop_times.txt"):
        st = stops.get(r["stop_id"])
        if st is not None:
            m = trip_mode.get(r["trip_id"])
            if m:
                st[3].add(m)

    out_stops = {sid: [n, la, lo, sorted(m)] for sid, (n, la, lo, m) in stops.items() if m}
    out: dict[str, Any] = {"stops": out_stops, "trip_count": len(route_of)}
    if keep_trips:
        out["trips"] = {t: [routes.get(rid, ("", 3))[0], head, trip_mode[t], touching[t]] for t, (rid, head) in route_of.items()}
    return out
