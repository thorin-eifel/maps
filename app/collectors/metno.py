"""Wettervorhersage (MET Norway, Locationforecast 2.0): zweites Modell neben DWD/Bright Sky, 48 Stunden für Irrel.

Quelle:     https://api.met.no/weatherapi/locationforecast/2.0/compact
Betreiber:  Norwegian Meteorological Institute (MET Norway)
Lizenz:     CC BY 4.0, Namensnennung „Wetterdaten: MET Norway“ (Bedingungen: api.met.no/doc/TermsOfService)
Intervall:  3600 s (Modell wird etwa stündlich aktualisiert)
Bedingungen der Quelle, die hier eingehalten werden: ehrlicher User-Agent mit Kontakt, Koordinaten auf höchstens
4 Nachkommastellen, HTTPS, Caching über das Intervall (kein Abruf öfter als stündlich), ein Abruf statt Serien.
Beispiel:   python -m app.collect --once --only metno

Ablage:     Cache-Eintrag "forecast_metno" (Stundenwerte), kein Ereignis. Windgeschwindigkeit m/s → km/h.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config
from .base import Collector, CollectResult, SourceError


def _now() -> datetime:
    """Eigene Uhr, damit Tests die Zeit festnageln können."""
    return datetime.now(timezone.utc)


def parse_forecast(data: Any, hours: int = 48, now: datetime | None = None) -> dict[str, Any]:
    """Reine Funktion (testbar mit Fixtures): Antwort → Stundenliste ab jetzt."""
    try:
        series = data["properties"]["timeseries"]
        updated = data["properties"]["meta"]["updated_at"]
    except (KeyError, TypeError) as exc:
        raise SourceError(f"MET Norway: unerwartete Antwort ({exc})") from exc
    if not isinstance(series, list) or not series:
        raise SourceError("MET Norway: leere Zeitreihe")
    now = now or _now()
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=hours)
    out: list[dict[str, Any]] = []
    for row in series:
        try:
            ts = datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00"))
            inst = row["data"]["instant"]["details"]
        except (KeyError, TypeError, ValueError):
            continue
        if not start <= ts <= end:
            continue
        n1 = row["data"].get("next_1_hours") or {}
        n6 = row["data"].get("next_6_hours") or {}
        prec = (n1.get("details") or {}).get("precipitation_amount")
        if prec is None and n6:     # ab ca. 2,5 Tagen nur noch Sechsstundenwerte: gleichmäßig verteilt
            p6 = (n6.get("details") or {}).get("precipitation_amount")
            prec = round(p6 / 6, 2) if isinstance(p6, (int, float)) else None
        wind = inst.get("wind_speed")
        out.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "temperature": inst.get("air_temperature"),
            "precipitation": prec,
            "wind_speed": round(wind * 3.6, 1) if isinstance(wind, (int, float)) else None,
            "cloud_cover": inst.get("cloud_area_fraction"),
            "symbol": ((n1 or n6).get("summary") or {}).get("symbol_code"),
        })
    if not out:
        raise SourceError("MET Norway: keine Stunden im gewünschten Fenster")
    return {"hours": out, "updated_at": updated}


class MetNoCollector(Collector):
    async def collect(self) -> CollectResult:
        # 4 Nachkommastellen sind die Obergrenze der Quelle (mehr ergibt HTTP 403)
        params = {"lat": f"{config.CENTER_LAT:.4f}", "lon": f"{config.CENTER_LON:.4f}"}
        data = await self.fetch_json(self.entry.url, params=params)
        fc = parse_forecast(data, int(self.entry.params.get("forecast_hours", 48)))
        fc["location"] = {"lat": float(params["lat"]), "lon": float(params["lon"]), "name": "Irrel"}
        return CollectResult(cache={"forecast_metno": fc}, writes_events=False)


COLLECTOR = MetNoCollector
