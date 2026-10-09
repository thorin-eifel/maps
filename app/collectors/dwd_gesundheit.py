"""Pollenflug-Gefahrenindex und UV-Gefahrenindex des DWD (Medizin-Meteorologie).

Quelle:     https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json (Pollen, Teilregionen)
            https://opendata.dwd.de/climate_environment/health/alerts/uvi.json (UV, Stationen)
Betreiber:  Deutscher Wetterdienst (DWD)
Lizenz:     GeoNutzV, Namensnennung DWD (Datensatz ohne Lizenzzeile in der JSON-Beschreibung; Bedingungen siehe sources.yaml)
Intervall:  3600 s (Pollen täglich gegen 11 Uhr, UV täglich gegen 7:30 Uhr)
Beispiel:   python -m app.collect --once --only dwd_gesundheit

Keine Ereignisse, nur Cache-Eintrag "gesundheit". Pollen: Teilregionen aus params.pollen_regions (Standard 101 Rhein/Mosel, 102 Mittelgebirge
RLP). UV: Station aus params.uv_station (Standard Hahn, Hunsrück, die nächste Station im Radius). Stufen bleiben so, wie der DWD sie nennt
("0-1", "2-3"), samt Legende. Reine Vorhersagezahlen, kein Personenbezug.
"""
from __future__ import annotations

from typing import Any

from .base import Collector, CollectResult, SourceError

POLLEN_ORDER = ("Hasel", "Erle", "Esche", "Birke", "Graeser", "Roggen", "Beifuss", "Ambrosia")


def parse_pollen(data: Any, regions: list[int]) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("content"), list):
        raise SourceError("Pollen: 'content' fehlt")
    out = []
    for c in data["content"]:
        if c.get("partregion_id") not in regions:
            continue
        pol = c.get("Pollen") or {}
        out.append({
            "id": c["partregion_id"], "name": str(c.get("partregion_name", "")),
            "days": {d: {k: str((pol.get(k) or {}).get(d, "")) for k in POLLEN_ORDER if k in pol}
                     for d in ("today", "tomorrow", "dayafter_to")},
        })
    if not out:
        raise SourceError("Pollen: keine der gewünschten Teilregionen gefunden")
    legend = {str(v): data["legend"].get(f"{k}_desc") for k, v in (data.get("legend") or {}).items()
              if k.startswith("id") and not k.endswith("_desc")}
    return {"regions": out, "legend": legend, "last_update": data.get("last_update"), "next_update": data.get("next_update")}


def parse_uv(data: Any, station: str) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("content"), list):
        raise SourceError("UV: 'content' fehlt")
    for c in data["content"]:
        if str(c.get("city")) == station:
            f = c.get("forecast") or {}
            return {"station": station, "forecast_day": data.get("forecast_day"), "last_update": data.get("last_update"),
                    "today": f.get("today"), "tomorrow": f.get("tomorrow"), "dayafter": f.get("dayafter_to")}
    raise SourceError(f"UV: Station {station} nicht in der Liste")


class DwdGesundheitCollector(Collector):
    async def collect(self) -> CollectResult:
        base = self.entry.url.rstrip("/")
        regions = [int(r) for r in self.entry.params.get("pollen_regions", [101, 102])]
        pollen = parse_pollen(await self.fetch_json(f"{base}/s31fg.json"), regions)
        uv = parse_uv(await self.fetch_json(f"{base}/uvi.json"), str(self.entry.params.get("uv_station", "Hahn")))
        return CollectResult(cache={"gesundheit": {"pollen": pollen, "uv": uv}}, writes_events=False,
                             note=f"Pollen {len(pollen['regions'])} Teilregionen, UV Station {uv['station']}")


COLLECTOR = DwdGesundheitCollector
