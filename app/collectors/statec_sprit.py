"""Amtliche Höchstpreise für Kraftstoffe in Luxemburg (STATEC, LUSTAT).

Quelle:     https://lustat.statec.lu/rest/data/LU1,DSD_PRIX_ESSENCE@DF_E5301, (Super 95, Super 98) und @DF_E5302 (Diesel), SDMX-REST, CSV
Betreiber:  STATEC (Institut national de la statistique et des études économiques), Preise setzt das Wirtschaftsministerium fest
Lizenz:     CC0 1.0 laut Datensatz "Économie totale et prix - Prix - Prix de l'énergie" auf data.public.lu
Intervall:  1 h (die Preise ändern sich wöchentlich bis zweimal wöchentlich; TIME_PERIOD ist der Tag, ab dem sie gelten)
Ablage:     Cache-Eintrag "lu_fuel_max": {"fuels": {"sp95": {"value", "valid_from"}, "sp98": ..., "diesel": ...}}. Kein Ereignis.
Beispiel:   python -m app.collect --once --only statec_sprit

Wichtig für die Anzeige: Das sind Höchstpreise je Liter inklusive Steuern, keine Preise einzelner Tankstellen. Stationen dürfen darunter liegen.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from .base import Collector, CollectResult, SourceError

BASE = "https://lustat.statec.lu/rest/data/LU1,DSD_PRIX_ESSENCE@{flow},/all"
FLOWS = ("DF_E5301", "DF_E5302")                 # Benzin, Diesel
CODES = {"SP95": "sp95", "SP98": "sp98", "DIE": "diesel"}
ACCEPT = "application/vnd.sdmx.data+csv;version=1.0.0"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_csv(text: str) -> dict[str, dict[str, Any]]:
    """SDMX-CSV → je Sorte der jüngste Wert. Reine Funktion; unplausible Werte (außerhalb 0,5 bis 5 €/l) werden verworfen."""
    out: dict[str, dict[str, Any]] = {}
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error as exc:
        raise SourceError(f"LUSTAT: CSV nicht lesbar ({exc})") from exc
    for r in rows:
        key = CODES.get((r.get("MOTOR_ENERGY") or "").strip())
        day = (r.get("TIME_PERIOD") or "").strip()
        try:
            val = float(r.get("OBS_VALUE") or "")
        except ValueError:
            continue
        if not key or not DATE.match(day) or not 0.5 <= val <= 5 or (r.get("UNIT_MEASURE") or "") != "EUR_LI":
            continue
        if key not in out or day > out[key]["valid_from"]:
            out[key] = {"value": round(val, 3), "valid_from": day}
    return out


class StatecSpritCollector(Collector):
    async def collect(self) -> CollectResult:
        fuels: dict[str, dict[str, Any]] = {}
        for flow in FLOWS:
            resp = await self._request(BASE.format(flow=flow), {"lastNObservations": 1}, ACCEPT, False, ())
            assert resp is not None
            fuels.update(parse_csv(resp.text))
        if not fuels:
            raise SourceError("LUSTAT: keine Höchstpreise in der Antwort (Schema geändert?)")
        missing = [k for k in ("sp95", "sp98", "diesel") if k not in fuels]
        note = f"teilweise: {', '.join(missing)} fehlt" if missing else None
        return CollectResult(cache={"lu_fuel_max": {"fuels": fuels}}, complete=not missing, note=note, writes_events=False)


COLLECTOR = StatecSpritCollector
