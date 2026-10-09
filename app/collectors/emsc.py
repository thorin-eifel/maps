"""Erdbeben im Umkreis (EMSC / SeismicPortal, FDSN-Ereignisdienst).

Quelle:     https://www.seismicportal.eu/fdsnws/event/1/query  (format=json)
Betreiber:  Euro-Mediterranean Seismological Centre (EMSC); Herkunft je Ereignis: nationale Dienste (z. B. LED, ReNaSS)
Lizenz:     CC BY 4.0 (laut Angabe auf der Dienstseite), Namensnennung EMSC
Intervall:  900 s
Beispiel:   python -m app.collect --once --only emsc

Abfrage der letzten 7 Tage im Bounding Box, Feinfilter auf 120 km am Rand. Die Eifel und der Hunsrück haben viele
Kleinstbeben (Magnitude unter 2), die niemand spürt: Sie stehen als Info, ab Magnitude 3,0 als Hinweis, ab 4,0 als Warnung.
Die Orte sind Herdkoordinaten laut Katalog, keine Schadensmeldungen. Ein Beben bleibt 24 Stunden im Fenster „jetzt“.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, geo
from ..models import Event, Severity, utcnow
from ..sanitize import clean_text
from .base import Collector, CollectResult, SourceError

DAYS = 7
NOTICE_MAG = 3.0
WARNING_MAG = 4.0


def _dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class EmscCollector(Collector):
    async def collect(self) -> CollectResult:
        lat0, lon0, lat1, lon1 = config.BBOX
        now = utcnow()
        data = await self.fetch_json(self.entry.url, params={
            "format": "json", "minlat": lat0, "maxlat": lat1, "minlon": lon0, "maxlon": lon1,
            "starttime": (now - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%S"), "orderby": "time", "limit": 500,
        }, allow_empty=True)  # 204 = keine Beben im Fenster
        if data is None:
            return CollectResult(events=[], complete=True, note="keine Beben in den letzten 7 Tagen")
        feats = data.get("features") if isinstance(data, dict) else None
        if not isinstance(feats, list):
            raise SourceError("EMSC: Schlüssel 'features' fehlt")
        events: dict[str, Event] = {}
        for f in feats:
            p = f.get("properties") or {}
            try:
                lat, lon, mag = float(p["lat"]), float(p["lon"]), float(p["mag"])
            except (KeyError, TypeError, ValueError):
                continue
            t = _dt(p.get("time"))
            if t is None or not geo.in_region(lat, lon):
                continue
            if p.get("evtype") not in (None, "ke", "se"):  # ke = bekanntes Erdbeben; Sprengungen und Sonstiges nicht
                continue
            uid = str(p.get("unid") or f.get("id"))
            sev: Severity = "warning" if mag >= WARNING_MAG else "notice" if mag >= NOTICE_MAG else "info"
            depth = p.get("depth")
            region = str(p.get("flynn_region") or "").title()
            events[uid] = Event(
                id=f"emsc:{uid}", source_id=self.entry.id, type="earthquake",
                title=clean_text(f"Erdbeben M {mag:.1f}" + (f", {region}" if region else ""), 200),
                summary=clean_text(f"Magnitude {mag:.1f} ({str(p.get('magtype') or '').upper() or '?'}), Herdtiefe {depth:.0f} km, "
                                   f"Zeit {t:%d.%m.%Y %H:%M} UTC, Meldung von {p.get('auth') or 'unbekannt'}. Herd laut Katalog, vorläufig."
                                   if isinstance(depth, (int, float)) else f"Magnitude {mag:.1f}, Zeit {t:%d.%m.%Y %H:%M} UTC.", 400),
                severity=sev, geometry={"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                region_tag="EU", valid_from=t, valid_to=t + timedelta(hours=24),
                fetched_at=now, raw_ref=f"https://www.emsc-csem.org/Earthquake_information/earthquake.php?id={p.get('source_id') or uid}",
                attrs={"kind": "erdbeben", "mag": mag, "depth_km": depth if isinstance(depth, (int, float)) else None},
            )
        return CollectResult(events=list(events.values()), complete=True)


COLLECTOR = EmscCollector
