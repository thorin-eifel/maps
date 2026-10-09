"""Pegel Luxemburg (Administration de la gestion de l'eau, Hochwasserportal inondations.public.lu).

Quelle:     CSV  https://inondations.public.lu/dam-assets/ctie/datas/Water-Levels-LocalTime.csv (15-Minuten-Werte, rund 2 Tage, Ortszeit)
            Orte https://features.geoportail.lu/collections/655/items (Stationskoordinaten, pygeoapi)
Betreiber:  Administration de la gestion de l'eau (AGE), Luxembourg
Lizenz:     CC0 1.0 laut Datensatz "Niveau d'eau" auf data.public.lu
Intervall:  900 s
Beispiel:   python -m app.collect --once --only lu_pegel

Das CSV enthält Zeilen je Station (Name, Einheit) und Spalten je Zeitpunkt, nicht alle Felder sind gefüllt. Die Koordinaten liefert der
zweite Dienst; beide Listen werden über den normalisierten Namen verbunden (mit kleiner Aliasliste für abweichende Schreibweisen).
Stationen ohne Treffer, Talsperren (Einheit m, Stauziel statt Pegel) und Werte außerhalb des plausiblen Bereichs fallen weg.
Warnstufen veröffentlicht die Quelle nicht; die Kachel zeigt Wert und Trend, keine Farbe. Reine Messwerte, kein Personenbezug.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .. import geo
from ..models import Measurement, Station
from .base import Collector, CollectResult, SourceError

TZ = ZoneInfo("Europe/Luxembourg")
STATIONS_URL = "https://features.geoportail.lu/collections/655/items"
PLAUSIBLE_CM = (-50.0, 1500.0)
ALIAS = {"gemundour": "gemund", "hunnebuer": "hunnebour", "roodtsursyre": "roodtsyre", "ubersyren": "uebersyren",
         "stadtbredimus": "stadtbrediums", "sdiekirch": "diekirch"}
# Gewässer nur, wo sicher bekannt; sonst bleibt das Feld leer und die Liste zeigt nur den Ortsnamen.
WATER = {"snwasserbillig": "Mosel", "sngrevenmacher": "Mosel", "snremich": "Mosel", "snstadtbredimus": "Mosel", "perl": "Mosel",
         "bollendorf": "Sauer", "rosport": "Sauer", "diekirch": "Sauer", "heiderscheidergrund": "Sauer",
         "gemund": "Our", "vianden": "Our", "dasbourg": "Our",
         "steinsel": "Alzette", "walferdange": "Alzette", "pfaffenthal": "Alzette", "ettelbruckalzette": "Alzette",
         "livange": "Alzette", "hesperange": "Alzette"}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return ALIAS.get(s, s)


def _local(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
    except ValueError:
        return None


def parse(csv_text: str, stations_geo: Any) -> tuple[list[Station], list[Measurement], dict[str, int]]:
    """Reine Funktion (testbar mit Fixtures)."""
    feats = stations_geo.get("features") if isinstance(stations_geo, dict) else None
    if not isinstance(feats, list):
        raise SourceError("Pegel Luxemburg: Stationsliste ohne 'features'")
    coords: dict[str, tuple[str, float, float]] = {}
    for f in feats:
        try:
            lon, lat = f["geometry"]["coordinates"][:2]
            name = str(f["properties"]["Nom"])
        except (KeyError, TypeError, ValueError):
            continue
        coords.setdefault(norm(name), (name, float(lat), float(lon)))
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    if len(rows) < 2 or rows[0][:3] != ["Name", "Number", "Unit"]:
        raise SourceError("Pegel Luxemburg: CSV-Kopf nicht wie erwartet (Name, Number, Unit)")
    times = [_local(h) for h in rows[0][3:]]
    if not any(times):
        raise SourceError("Pegel Luxemburg: keine Zeitspalten lesbar")
    stats = {"rows": 0, "no_coords": 0, "not_cm": 0, "empty": 0, "outside": 0}
    stations: list[Station] = []
    meas: list[Measurement] = []
    for row in rows[1:]:
        if len(row) < 4:
            continue
        stats["rows"] += 1
        raw_name, unit = row[0].strip(), row[2].strip()
        key = norm(re.sub(r"^SN_", "sn", raw_name)) if raw_name.startswith("SN_") else norm(raw_name)
        if unit != "cm":
            stats["not_cm"] += 1
            continue
        hit = coords.get(key) or coords.get(norm(raw_name.replace("SN_", "")))
        if hit is None:
            stats["no_coords"] += 1
            continue
        name, lat, lon = hit
        if not geo.in_region(lat, lon):
            stats["outside"] += 1
            continue
        values = []
        for t, cell in zip(times, row[3:]):
            if t is None or not cell.strip():
                continue
            try:
                v = float(cell)
            except ValueError:
                continue
            if PLAUSIBLE_CM[0] <= v <= PLAUSIBLE_CM[1]:
                values.append((t, v))
        if not values:
            stats["empty"] += 1
            continue
        sid = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", raw_name).encode("ascii", "ignore").decode().lower()).strip("-")
        pretty = re.sub(r"^SN_", "", raw_name).replace("_", " ")
        stations.append(Station(source_id="lu_pegel", station_id=sid, name=pretty, water=WATER.get(key) or WATER.get(norm(pretty)),
                                lat=round(lat, 5), lon=round(lon, 5), meta={"land": "LU"}))
        meas.extend(Measurement(source_id="lu_pegel", station_id=sid, parameter="W", ts=t, value=v, unit="cm") for t, v in values)
    if not stations:
        raise SourceError("Pegel Luxemburg: keine Station mit Koordinaten und Werten (Schemawechsel?)")
    return stations, meas, stats


class LuPegelCollector(Collector):
    async def collect(self) -> CollectResult:
        raw = await self.fetch_bytes(self.entry.url, timeout=60.0)
        geo_json = await self.fetch_json(STATIONS_URL, params={"f": "json", "limit": 200})
        stations, meas, st = parse(raw.decode("utf-8-sig", errors="replace"), geo_json)
        note = f"{len(stations)} Stationen, {len(meas)} Werte (ohne Koordinaten {st['no_coords']}, Talsperre {st['not_cm']}, leer {st['empty']})"
        return CollectResult(stations=stations, measurements=meas, writes_events=False, note=note)


COLLECTOR = LuPegelCollector
