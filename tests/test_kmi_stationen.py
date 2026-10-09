"""KMI/IRM-Stationen: Auswahl aus echter Stationsliste, Lauf mit echter Beispielantwort (2026-10-07)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.collectors.kmi_stationen import pick_stations, _kmh
from tests.test_collectors_umwelt import run, FIX


def _station_list():
    return json.loads((FIX / "kmi_synop_station_real_2026-10-07.json").read_text())


def test_pick_stations_radius_and_active_only():
    got = {s["name"] for s in pick_stations(_station_list())}
    assert {"ELSENBORN", "MONT RIGI", "BUZENOL", "SAINT-HUBERT"} <= got
    assert "UCCLE-UKKEL (FERME)" not in got and "KOKSIJDE" not in got and "BRUXELLES" not in got
    assert len({s["code"] for s in pick_stations(_station_list())}) == len(pick_stations(_station_list()))


def test_wind_units():
    assert _kmh(10, 1) == 36.0 and round(_kmh(10, 4), 2) == 18.52 and _kmh(10, None) is None and _kmh(10, 9) is None


def _handler(drop_data=False):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params["typeNames"] == "synop:synop_station":
            return httpx.Response(200, json=_station_list())
        if drop_data:
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        return httpx.Response(200, text=(FIX / "kmi_synop_data_real_2026-10-07.json").read_text())
    return handler


def _freeze(monkeypatch):
    import app.collectors.kmi_stationen as mod
    monkeypatch.setattr(mod, "utcnow", lambda: datetime(2026, 10, 7, 17, 40, tzinfo=timezone.utc))


async def test_collector_writes_values_in_dwd_units(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    ok, _, c = await run("kmi_stationen", registry, storage, settings, _handler())
    assert ok
    st = {r["name"] for r in storage._query("SELECT name FROM stations WHERE source_id='kmi_stationen'")}  # noqa: SLF001
    assert {"Mont Rigi", "Buzenol", "Saint-Hubert", "Humain"} <= st
    assert "Elsenborn" not in st      # meldet seit 13.08.2026 nichts mehr: die Station fehlt, statt mit Altdaten zu erscheinen
    units = {r["parameter"]: r["unit"] for r in storage._query("SELECT DISTINCT parameter, unit FROM measurements WHERE source_id='kmi_stationen'")}  # noqa: SLF001
    assert units["temperature"] == "°C" and units["wind_speed_10"] == "km/h" and units["pressure_msl"] == "hPa"


async def test_no_data_is_an_error_not_an_empty_map(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    ok, err, _ = await run("kmi_stationen", registry, storage, settings, _handler(drop_data=True))
    assert not ok and err
