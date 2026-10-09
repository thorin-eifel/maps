"""Satelliten-Wärmepunkte (NASA FIRMS, VIIRS Near-Real-Time).

Quelle:     https://firms.modaps.eosdis.nasa.gov/api/area/csv/<MAP_KEY>/<QUELLE>/<west,süd,ost,nord>/<Tage>
Betreiber:  NASA LANCE / FIRMS (VIIRS auf Suomi NPP, NOAA-20, NOAA-21; 375 m Pixel)
Lizenz:     NASA Earthdata-Datennutzungsrichtlinie: frei, auch kommerziell, Quellenangabe erbeten
Schlüssel:  FIRMS_MAP_KEY in .env (kostenlos). Der Schlüssel steht im URL-Pfad; er wird in Meldungen maskiert.
Intervall:  1800 s (Satelliten überfliegen ohnehin nur wenige Male am Tag, Verzögerung meist 1 bis 3 Stunden)
Beispiel:   python -m app.collect --once --only nasa_firms

Ein Wärmepunkt ist kein bestätigter Brand: Feldbrand, Kamin, Stahlwerk oder Biogasanlage sehen im Infrarot gleich aus.
Deshalb heißt das Ereignis "Brandverdacht", steht ohne Warnstufe (info; notice nur bei hoher Konfidenz und starker
Strahlungsleistung) und trägt den Hinweis im Text. Niedrige Konfidenz wird verworfen. Mehrere Satelliten über
demselben Punkt (Raster von etwa 1 km, 3-Stunden-Fenster) werden zu einem Ereignis.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta, timezone

from .. import config, geo
from ..models import Event, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
DAYS = 2
KEY_ENV = "FIRMS_MAP_KEY"
VALID_H = 12
NOTICE_FRP_MW = 20.0
CONF = {"h": 0.9, "high": 0.9, "n": 0.6, "nominal": 0.6}   # l / low fällt weg
MAP_URL = "https://firms.modaps.eosdis.nasa.gov/map/"


def _when(date: str, hhmm: str) -> datetime | None:
    try:
        return datetime.strptime(f"{date} {hhmm.zfill(4)}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_csv(text: str) -> list[dict]:
    """CSV-Antwort in Zeilen. Ein Text ohne Kopfzeile 'latitude' ist eine Fehlermeldung des Dienstes."""
    body = text.lstrip("﻿").strip()
    if not body.lower().startswith("latitude"):
        raise SourceError(f"FIRMS: keine CSV-Antwort ({clean_text(body, 80) or 'leer'})")
    return list(csv.DictReader(io.StringIO(body)))


class NasaFirmsCollector(Collector):
    async def _one(self, key: str, source: str) -> list[dict]:
        lat0, lon0, lat1, lon1 = config.BBOX
        url = f"{self.entry.url.rstrip('/')}/{key}/{source}/{lon0},{lat0},{lon1},{lat1}/{DAYS}"
        return parse_csv(await self.fetch_text(url, secrets=(key,)))

    async def collect(self) -> CollectResult:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise SourceError(f"{KEY_ENV} fehlt (.env, siehe .env.example)")
        now = utcnow()
        rows: list[tuple[str, dict]] = []
        failed: list[str] = []
        first_err = ""
        for source in SOURCES:
            try:
                rows += [(source, r) for r in await self._one(key, source)]
            except SourceError as exc:
                msg = str(exc).replace(key, "***")   # ein Dienst könnte den Schlüssel in seiner Fehlermeldung wiederholen
                self.log.warning("%s: %s", source, msg)
                failed.append(source)
                first_err = first_err or msg
        if len(failed) == len(SOURCES):
            raise SourceError(f"FIRMS: alle Satellitenquellen fehlgeschlagen ({first_err})")

        best: dict[str, tuple[float, Event]] = {}
        low = 0
        for source, r in rows:
            try:
                lat, lon = float(r["latitude"]), float(r["longitude"])
                frp = float(r.get("frp") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            conf = CONF.get(str(r.get("confidence", "")).strip().lower())
            if conf is None:
                low += 1
                continue
            t = _when(str(r.get("acq_date", "")), str(r.get("acq_time", "")))
            if t is None or not geo.in_region(lat, lon):
                continue
            bucket = f"{t:%Y%m%d}{t.hour // 3}"
            uid = f"firms:{lat:.2f}:{lon:.2f}:{bucket}"
            sev = "notice" if conf >= 0.9 and frp >= NOTICE_FRP_MW else "info"
            sat = str(r.get("satellite") or source.split("_")[1]).strip()
            ev = Event(
                id=uid, source_id=self.entry.id, type="fire",
                title="Satelliten-Wärmepunkt (Brandverdacht)",
                summary=clean_text(
                    f"VIIRS-Wärmeanomalie {t:%d.%m.%Y %H:%M} UTC, Strahlungsleistung {frp:.1f} MW, Konfidenz "
                    f"{'hoch' if conf >= 0.9 else 'nominal'}. Kann Feuer, Feldbrand oder Industriewärme sein; nicht bestätigt.", 400),
                severity=sev, confidence=conf, geometry={"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                region_tag="EU", valid_from=t, valid_to=t + timedelta(hours=VALID_H), fetched_at=now, raw_ref=MAP_URL,
                attrs={"kind": "brand", "frp": frp, "satellite": sat, "daynight": str(r.get("daynight") or "").strip() or None},
            )
            if uid not in best or frp > best[uid][0]:
                best[uid] = (frp, ev)
        parts = []
        if failed:
            parts.append(f"teilweise: {', '.join(failed)} fehlgeschlagen")
        if low:
            parts.append(f"{low} Punkte mit niedriger Konfidenz verworfen")
        if not best:
            parts.append("keine Wärmepunkte im Fenster")
        return CollectResult(events=[e for _, e in best.values()], complete=not failed, note="; ".join(parts) or None)


COLLECTOR = NasaFirmsCollector
