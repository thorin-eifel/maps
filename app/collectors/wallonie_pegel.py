"""Pegel Wallonien (SPW Mobilité et Infrastructures, Dienst Hydrométrie, KiWIS-Webdienst).

Quelle:     https://hydrometrie.wallonie.be/services/KiWIS/KiWIS  (getStationList, getTimeseriesList, getTimeseriesValues; JSON, anonym)
Betreiber:  Service public de Wallonie (SPW), Direction des Voies hydrauliques / Hydrométrie
Lizenz:     keine ausdrückliche Angabe am Dienst gefunden (lizenz_geprueft false, siehe sources.yaml); Quellenangabe wird mitgeführt
Intervall:  900 s (Stundenmittel, die Stationen melden zur vollen Stunde)
Beispiel:   python -m app.collect --once --only wallonie_pegel

Ablauf: Stationsliste der Bounding Box (Radiusfilter am Rand), je Station die Zeitreihe des Wasserstands. Bevorzugt "10-Hauteur.1h.Moyen"
(Stundenmittel, validiert), sonst die 10-Minuten-Reihen "02b-Hauteur.10min.Production" und "02a-Hauteur.10min.Origine". Stationsliste und
Reihenkennungen ändern sich selten und werden 12 Stunden zwischengespeichert; je Lauf wird nur getimeseriesValues für die letzten 24 Stunden
abgefragt. Der Dienst antwortet auf Reihenlisten gelegentlich minutenlang nicht: dafür gilt ein großzügiges Zeitlimit, und eine
zwischengespeicherte Liste bleibt bis 3 Tage nach Ablauf als Notbehelf gültig. Werte kommen in Metern und werden zu Zentimetern
(Pegelnullpunkt je Station, nicht über NN: die Werte sind mit PEGELONLINE-Werten nicht vergleichbar, nur im Verlauf je Station).
Reine Messwerte, kein Personenbezug.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, geo
from ..models import Measurement, Station, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

BASE = "https://hydrometrie.wallonie.be/services/KiWIS/KiWIS"
COMMON = {"service": "kisters", "type": "queryServices", "datasource": "0", "format": "json"}
SERIES = ("10-Hauteur.1h.Moyen", "02b-Hauteur.10min.Production", "02a-Hauteur.10min.Origine")   # Vorzugsreihenfolge
LIST_TTL = timedelta(hours=12)
LIST_GRACE = timedelta(days=3)
CURRENT_WITHIN = timedelta(hours=12)      # Reihen, die älter enden, gelten als stillgelegt
LOOKBACK_H = 24
BATCH_LIST, BATCH_VALUES = 20, 50
LIST_TIMEOUT_S = 90.0
PLAUSIBLE_CM = (-100.0, 2500.0)
SMALL = {"au", "aux", "en", "sur", "sous", "de", "du", "des", "la", "le", "les", "lez", "lès", "et"}
UPPER = re.compile(r"^[^a-zà-ÿ]*$")


def _title(name: str) -> str:
    """'ANGLEUR Aval RD' → 'Angleur Aval RD'; reine Großschreibung des ersten Worts wird zu Titelschreibweise, Rest bleibt."""
    parts = name.split()
    if parts and UPPER.match(parts[0]) and len(parts[0]) > 3:
        parts[0] = "-".join(p.lower() if i and p.lower() in SMALL else p.capitalize() for i, p in enumerate(parts[0].split("-")))
    return " ".join(parts)


def pick_stations(data: Any) -> dict[str, Station]:
    """getStationList-Antwort (Kopfzeile + Zeilen) → Stationen im Radius. Reine Funktion."""
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise SourceError("KiWIS: Stationsliste hat nicht das erwartete Format")
    head = data[0]
    try:
        i_no, i_name, i_lat, i_lon = (head.index(k) for k in ("station_no", "station_name", "station_latitude", "station_longitude"))
    except ValueError as exc:
        raise SourceError("KiWIS: Stationsliste ohne Pflichtfelder") from exc
    i_river = head.index("river_name") if "river_name" in head else None
    out: dict[str, Station] = {}
    for row in data[1:]:
        try:
            no = str(row[i_no])
            lat, lon = float(row[i_lat]), float(row[i_lon])
        except (TypeError, ValueError, IndexError):
            continue
        if not geo.in_bbox(lat, lon) or geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, lat, lon) > config.RADIUS_KM:
            continue
        river = clean_text(str(row[i_river]), 80) if i_river is not None and row[i_river] else None
        out[no] = Station(source_id="wallonie_pegel", station_id=no, name=_title(clean_text(str(row[i_name]), 100) or no),
                          water=river or None, lat=round(lat, 5), lon=round(lon, 5), meta={"land": "BE", "region": "Wallonien"})
    return out


def pick_series(rows_by_name: dict[str, Any], now: datetime) -> dict[str, str]:
    """Je Station die beste noch laufende Reihe (Kennung). rows_by_name: Reihenname → getTimeseriesList-Antwort."""
    best: dict[str, tuple[int, str]] = {}
    for pri, name in enumerate(SERIES):
        data = rows_by_name.get(name)
        if not isinstance(data, list) or len(data) < 1:
            continue
        head = data[0]
        try:
            i_id, i_no, i_to = head.index("ts_id"), head.index("station_no"), head.index("to")
        except ValueError as exc:
            raise SourceError("KiWIS: Reihenliste ohne Pflichtfelder") from exc
        for row in data[1:]:
            try:
                end = datetime.fromisoformat(str(row[i_to]))
            except (TypeError, ValueError):
                continue
            if end.tzinfo is None or now - end > CURRENT_WITHIN:
                continue
            no = str(row[i_no])
            if no not in best or pri < best[no][0]:
                best[no] = (pri, str(row[i_id]))
    return {no: ts for no, (_, ts) in best.items()}


def parse_values(data: Any, ts_to_station: dict[str, str]) -> list[Measurement]:
    if not isinstance(data, list):
        raise SourceError("KiWIS: Werteantwort ist keine Liste")
    meas: list[Measurement] = []
    for series in data:
        if not isinstance(series, dict):
            continue
        sid = ts_to_station.get(str(series.get("ts_id")))
        if sid is None:
            continue
        cols = [c.strip() for c in str(series.get("columns", "Timestamp,Value")).split(",")]
        try:
            i_t, i_v = cols.index("Timestamp"), cols.index("Value")
        except ValueError as exc:
            raise SourceError("KiWIS: Werteantwort ohne Timestamp/Value") from exc
        for row in series.get("data") or []:
            try:
                if row[i_v] is None:
                    continue
                ts = datetime.fromisoformat(str(row[i_t])).astimezone(timezone.utc)
                cm = round(float(row[i_v]) * 100.0, 1)
            except (TypeError, ValueError, IndexError):
                continue
            if PLAUSIBLE_CM[0] <= cm <= PLAUSIBLE_CM[1]:
                meas.append(Measurement(source_id="wallonie_pegel", station_id=sid, parameter="W", ts=ts, value=cm, unit="cm"))
    return meas


class WalloniePegelCollector(Collector):
    async def _get(self, request: str, timeout: float | None = None, **params: Any) -> Any:
        resp = await self._request(BASE, {**COMMON, "request": request, **params}, "application/json", False, (), timeout)
        assert resp is not None
        try:
            return resp.json()
        except ValueError as exc:
            raise SourceError(f"KiWIS {request}: kein gültiges JSON") from exc

    async def _cache_get(self, key: str) -> Any:
        row = await asyncio.to_thread(self.storage.cache_get, key)
        return row["payload"] if row else None

    async def _cache_put(self, key: str, payload: Any) -> None:
        await asyncio.to_thread(self.storage.cache_put, key, self.entry.id, payload)

    async def _directory(self) -> tuple[dict[str, Station], dict[str, str], bool]:
        """Stationen + Reihenkennungen; (stations, station_no→ts_id, frisch)."""
        cached = await self._cache_get("wallonie:dir")
        age = utcnow() - datetime.fromisoformat(cached["fetched"]) if cached else None
        if cached and age is not None and age < LIST_TTL:
            return {k: Station(**v) for k, v in cached["stations"].items()}, cached["series"], False
        try:
            s, w, n, e = config.BBOX
            stations = pick_stations(await self._get("getStationList", bbox=f"{w},{s},{e},{n}",
                                                     returnfields="station_no,station_name,station_latitude,station_longitude,river_name"))
            ids = sorted(stations)
            rows_by_name: dict[str, Any] = {}
            for name in SERIES:
                merged: list[Any] = []
                for i in range(0, len(ids), BATCH_LIST):
                    part = await self._get("getTimeseriesList", LIST_TIMEOUT_S, ts_name=name, station_no=",".join(ids[i:i + BATCH_LIST]),
                                           returnfields="ts_id,ts_name,station_no,coverage")
                    if not isinstance(part, list) or not part:
                        raise SourceError("KiWIS: Reihenliste leer oder ungültig")
                    merged = merged or [part[0]]
                    merged.extend(part[1:])
                rows_by_name[name] = merged
            series = pick_series(rows_by_name, utcnow())
        except SourceError:
            if cached and age is not None and age < LIST_TTL + LIST_GRACE:
                self.log.warning("Stationsliste nicht erneuerbar, nutze Zwischenspeicher (%s alt)", age)
                return {k: Station(**v) for k, v in cached["stations"].items()}, cached["series"], False
            raise
        await self._cache_put("wallonie:dir", {"fetched": utcnow().isoformat(), "series": series,
                                               "stations": {k: v.model_dump() for k, v in stations.items() if k in series}})
        return {k: v for k, v in stations.items() if k in series}, series, True

    async def collect(self) -> CollectResult:
        stations, series, _fresh = await self._directory()
        if not series:
            raise SourceError("KiWIS: keine laufende Wasserstandsreihe im Radius (Schemawechsel?)")
        since = (utcnow() - timedelta(hours=LOOKBACK_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_to_station = {ts: no for no, ts in series.items() if no in stations}
        ids = sorted(ts_to_station)
        meas: list[Measurement] = []
        complete = True
        for i in range(0, len(ids), BATCH_VALUES):
            try:
                data = await self._get("getTimeseriesValues", ts_id=",".join(ids[i:i + BATCH_VALUES]), returnfields="Timestamp,Value,Quality Code",
                                       **{"from": since})
            except SourceError as exc:
                if not meas and i + BATCH_VALUES >= len(ids):
                    raise
                self.log.warning("Werte-Block %d fehlgeschlagen: %s", i // BATCH_VALUES, exc)
                complete = False
                continue
            meas.extend(parse_values(data, ts_to_station))
        if not meas:
            raise SourceError("KiWIS: keine verwertbaren Wasserstände (Schemawechsel?)")
        used = sorted({m.station_id for m in meas})
        note = f"{len(used)} von {len(stations)} Stationen, {len(meas)} Werte" + ("" if complete else " (Teilabruf, Liste unvollständig)")
        return CollectResult(stations=[stations[u] for u in used], measurements=meas, writes_events=False, note=note, complete=complete)


COLLECTOR = WalloniePegelCollector
