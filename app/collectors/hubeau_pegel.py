"""Pegel Grand Est / Lothringen (Hub'eau Hydrométrie, Échtzeitdaten).

Quelle:     https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations  (Stationen, Koordinaten)
            https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr       (Wasserstand H in mm, rund 10-Minuten-Takt)
Betreiber:  Office français de la biodiversité / Schapi, Dienstportal Hub'eau (eaufrance.fr)
Lizenz:     Licence Ouverte 2.0 (Etalab) nach Kenntnis des Betreibers; Wortlaut der Nutzungsbedingungen bisher nicht gegengelesen
            (lizenz_geprueft false, siehe sources.yaml)
Intervall:  900 s
Beispiel:   python -m app.collect --once --only hubeau_pegel

Wir holen die Stationen der Bounding Box, die in Betrieb sind, und die Wasserstände der letzten 24 Stunden (Cursor-Seiten, höchstens
MAX_PAGES). Werte kommen in Millimetern und werden zu Zentimetern. Bergbau-Überläufe ("Débordement minier") sind keine Gewässerpegel
und fallen weg; Stationen außerhalb des Radius fallen am Rand weg. Warnstufen liefert diese Quelle nicht (das wäre Vigicrues);
die Kachel zeigt Wert und Trend ohne Farbe. Reine Messwerte, kein Personenbezug.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from .. import config, geo
from ..models import Measurement, Station, utcnow
from .base import Collector, CollectResult, SourceError

BASE = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"
PLAUSIBLE_CM = (-100.0, 2500.0)
MAX_PAGES = 6
PAGE = 5000
SKIP_NAME = re.compile(r"d[ée]bordement minier", re.I)
ABROAD = re.compile(r"^.{2,80}? en (Belgique|Allemagne|Luxembourg|France)\s*\[([^\]]{2,60})\]\s*$")  # "La Semoy en Belgique [Tintigny]"
LAND_DE = {"Belgique": "Belgien", "Allemagne": "Deutschland", "Luxembourg": "Luxemburg", "France": "Frankreich"}
AT_PLACE = re.compile(r"^.{2,60}? à (.{2,80})$")  # "La Bisten à Creutzwald" -> "Creutzwald"; der Flussname steht im Feld water


def _bbox_param() -> str:
    s, w, n, e = config.BBOX
    return f"{w},{s},{e},{n}"  # Hub'eau: lon_min,lat_min,lon_max,lat_max


def parse_stations(data: Any) -> dict[str, Station]:
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise SourceError("Hub'eau: Stationsliste ohne 'data'")
    out: dict[str, Station] = {}
    for r in rows:
        try:
            code = str(r["code_station"])
            lat, lon = float(r["latitude_station"]), float(r["longitude_station"])
            name = str(r.get("libelle_site") or r.get("libelle_station") or code)
        except (KeyError, TypeError, ValueError):
            continue
        if SKIP_NAME.search(name) or SKIP_NAME.search(str(r.get("libelle_station") or "")):
            continue
        if r.get("en_service") is False:
            continue
        if not geo.in_region(lat, lon):
            continue
        ab = ABROAD.match(name)
        if ab:
            name = f"{ab.group(2)} ({LAND_DE[ab.group(1)]})"
        m = AT_PLACE.match(name)
        out[code] = Station(source_id="hubeau_pegel", station_id=code, name=(m.group(1) if m else name)[:120], water=(r.get("libelle_cours_eau") or None),
                            lat=round(lat, 5), lon=round(lon, 5), meta={"land": "FR", "region": r.get("libelle_region") or "Grand Est"})
    return out


def parse_observations(pages: list[Any], stations: dict[str, Station]) -> tuple[list[Station], list[Measurement], dict[str, int]]:
    stats = {"rows": 0, "unknown": 0, "bad": 0, "implausible": 0}
    meas: list[Measurement] = []
    seen: set[tuple[str, datetime]] = set()
    used: set[str] = set()
    for page in pages:
        rows = page.get("data") if isinstance(page, dict) else None
        if not isinstance(rows, list):
            raise SourceError("Hub'eau: Beobachtungen ohne 'data'")
        for r in rows:
            stats["rows"] += 1
            code = str(r.get("code_station"))
            if code not in stations:
                stats["unknown"] += 1
                continue
            try:
                ts = datetime.strptime(str(r["date_obs"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                cm = float(r["resultat_obs"]) / 10.0
            except (KeyError, TypeError, ValueError):
                stats["bad"] += 1
                continue
            if not PLAUSIBLE_CM[0] <= cm <= PLAUSIBLE_CM[1]:
                stats["implausible"] += 1
                continue
            if (code, ts) in seen:
                continue
            seen.add((code, ts))
            used.add(code)
            meas.append(Measurement(source_id="hubeau_pegel", station_id=code, parameter="W", ts=ts, value=round(cm, 1), unit="cm"))
    if not meas:
        raise SourceError("Hub'eau: keine verwertbaren Wasserstände (Schemawechsel?)")
    return [stations[c] for c in sorted(used)], meas, stats


def _same_host(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and u.hostname == "hubeau.eaufrance.fr"


class HubeauPegelCollector(Collector):
    async def collect(self) -> CollectResult:
        st_raw = await self.fetch_json(f"{BASE}/referentiel/stations", params={
            "bbox": _bbox_param(), "en_service": 1, "size": 500, "format": "json",
            "fields": "code_station,libelle_site,libelle_station,libelle_cours_eau,latitude_station,longitude_station,libelle_region,en_service"})
        stations = parse_stations(st_raw)
        since = (utcnow() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        pages: list[Any] = []
        nxt: str | None = f"{BASE}/observations_tr"
        params: dict[str, Any] | None = {"bbox": _bbox_param(), "grandeur_hydro": "H", "date_debut_obs": since, "size": PAGE, "format": "json",
                                         "fields": "code_station,date_obs,resultat_obs"}
        complete = True
        for _ in range(MAX_PAGES):
            page = await self.fetch_json(nxt, params=params)
            pages.append(page)
            nxt = page.get("next") if isinstance(page, dict) else None
            params = None
            if not nxt:
                break
            if not _same_host(nxt):
                raise SourceError("Hub'eau: Folgeseite zeigt auf einen anderen Host, abgebrochen")
        else:
            complete = False
        used, meas, st = parse_observations(pages, stations)
        note = f"{len(used)} Stationen, {len(meas)} Werte in {len(pages)} Seite(n)" + ("" if complete else " (Seitenlimit erreicht, Liste unvollständig)")
        return CollectResult(stations=used, measurements=meas, writes_events=False, note=note, complete=complete)


COLLECTOR = HubeauPegelCollector
