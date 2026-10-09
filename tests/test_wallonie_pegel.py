"""Pegel Wallonien: Auswahl aus echten Beispielantworten des KiWIS-Dienstes (2026-10-07)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.collectors import wallonie_pegel as w
from app.collectors.base import SourceError
from tests.test_collectors_umwelt import run, FIX

NOW = datetime(2026, 10, 7, 21, 30, tzinfo=timezone.utc)


def fx(name):
    return json.loads((FIX / name).read_text())


def test_stations_radius_and_names():
    st = w.pick_stations(fx("wallonie_stations_real_2026-10-07.json"))
    assert {"L6290", "L6023", "9461", "5904", "8059", "7141", "6387"} <= set(st)
    assert len(st) == 10                       # die zwei Stationen außerhalb des Radius fehlen
    assert st["5904"].name == "Comblain-au-Pont" and st["5904"].water == "Ourthe moyenne"
    assert st["L6290"].name == "Amberloup"      # schon gemischt geschrieben: unverändert


def test_stations_bad_shape():
    with pytest.raises(SourceError):
        w.pick_stations({"x": 1})
    with pytest.raises(SourceError):
        w.pick_stations([["foo"], ["1"]])


def test_series_prefers_hourly_and_drops_stale():
    rows = {"10-Hauteur.1h.Moyen": fx("wallonie_ts_10_real_2026-10-07.json"),
            "02b-Hauteur.10min.Production": fx("wallonie_ts_02b_real_2026-10-07.json")}
    got = w.pick_series(rows, NOW)
    assert len(got) == 10
    hourly = {r[2]: r[0] for r in rows["10-Hauteur.1h.Moyen"][1:]}
    assert got["L6290"] == hourly["L6290"]
    # Station ohne Stundenreihe fällt auf die 10-Minuten-Reihe zurück
    rows["10-Hauteur.1h.Moyen"] = [r for r in rows["10-Hauteur.1h.Moyen"] if r[0] == "ts_id" or r[2] != "L6290"]
    assert w.pick_series(rows, NOW)["L6290"] != hourly["L6290"]
    # alles älter als 12 Stunden: nichts
    assert w.pick_series(rows, datetime(2026, 10, 9, tzinfo=timezone.utc)) == {}


def test_values_units_and_gaps():
    series = fx("wallonie_values_real_2026-10-07.json")
    m = w.parse_values(series, {series[0]["ts_id"]: "X1"})
    assert m and all(x.unit == "cm" and x.station_id == "X1" and x.ts.tzinfo is not None for x in m)
    raw = series[0]["data"][0]
    assert any(x.value == round(raw[1] * 100, 1) for x in m)
    bad = [{"ts_id": "1", "columns": "Timestamp,Value,Quality Code",
            "data": [["2026-10-07T00:00:00.000+02:00", None, -1], ["2026-10-07T01:00:00.000+02:00", 99.0, 200],
                     ["2026-10-07T02:00:00.000+02:00", 0.5, 200]]}]
    got = w.parse_values(bad, {"1": "S"})
    assert [x.value for x in got] == [50.0]      # None und 9900 cm (unplausibel) fallen weg
    assert got[0].ts == datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)   # 02:00+02:00 = 00:00 UTC
    with pytest.raises(SourceError):
        w.parse_values({"x": 1}, {})


def _handler(values=True, list_fails=False):
    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.params
        r = p["request"]
        if r == "getStationList":
            return httpx.Response(200, json=fx("wallonie_stations_real_2026-10-07.json"))
        if r == "getTimeseriesList":
            if list_fails:
                return httpx.Response(500)
            key = {"10-Hauteur.1h.Moyen": "10", "02b-Hauteur.10min.Production": "02b", "02a-Hauteur.10min.Origine": "02a"}[p["ts_name"]]
            return httpx.Response(200, json=fx(f"wallonie_ts_{key}_real_2026-10-07.json"))
        if r == "getTimeseriesValues":
            return httpx.Response(200, json=fx("wallonie_values_real_2026-10-07.json") if values else [])
        return httpx.Response(404)
    return handler


def _freeze(monkeypatch):
    monkeypatch.setattr(w, "utcnow", lambda: NOW)


async def test_collector_end_to_end(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    ok, _, c = await run("wallonie_pegel", registry, storage, settings, _handler())
    assert ok
    names = {r["name"] for r in storage._query("SELECT name FROM stations WHERE source_id='wallonie_pegel'")}  # noqa: SLF001
    assert {"Comblain-au-Pont", "Amberloup"} <= names
    units = {r["unit"] for r in storage._query("SELECT DISTINCT unit FROM measurements WHERE source_id='wallonie_pegel'")}  # noqa: SLF001
    assert units == {"cm"}


async def test_no_values_is_an_error(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    ok, _, _ = await run("wallonie_pegel", registry, storage, settings, _handler(values=False))
    assert not ok


async def test_list_down_without_cache_is_an_error(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    ok, _, _ = await run("wallonie_pegel", registry, storage, settings, _handler(list_fails=True))
    assert not ok
