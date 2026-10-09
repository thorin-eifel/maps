"""IRCEL-CELINE: Lauf mit echten Beispielantworten (WFS, 2026-10-07), Fehler- und Randfälle."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from tests.test_collectors_umwelt import run, FIX

LAYER_FILE = {"pm10_hmean_station": "pm10", "pm25_hmean_station": "pm25", "no2_hmean_station": "no2", "o3_hmean_station": "o3"}


def _handler(fail: str | None = None, patch=None):
    def handler(req: httpx.Request) -> httpx.Response:
        layer = req.url.params["typeNames"].split(":")[1]
        if fail and layer == fail:
            return httpx.Response(503)
        data = json.loads((FIX / f"irceline_{LAYER_FILE[layer]}_real_2026-10-07.json").read_text())
        if patch:
            patch(data)
        return httpx.Response(200, json=data)
    return handler


def _freeze(monkeypatch):
    import app.collectors.irceline as mod
    monkeypatch.setattr(mod, "utcnow", lambda: datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc))


async def test_stations_in_radius_with_four_parameters(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    ok, _, _ = await run("irceline", registry, storage, settings, _handler())
    assert ok
    st = storage._query("SELECT * FROM stations WHERE source_id='irceline'")  # noqa: SLF001
    assert st and all(s["distance_km"] <= 120 for s in st)
    names = {s["name"] for s in st}
    assert any("Vielsalm" in n for n in names)            # Ardennen, rund 70 km entfernt
    assert not any("Hasselt" in n or "Aarschot" in n for n in names)   # flämische Stationen liegen außerhalb
    params = {r["parameter"] for r in storage._query("SELECT DISTINCT parameter FROM measurements WHERE source_id='irceline'")}  # noqa: SLF001
    assert params == {"PM10", "PM2.5", "NO2", "O3"}


async def test_missing_values_are_dropped(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    await run("irceline", registry, storage, settings, _handler())
    vals = [r["value"] for r in storage._query("SELECT value FROM measurements WHERE source_id='irceline'")]  # noqa: SLF001
    assert vals and min(vals) >= 0 and -9999 not in vals


async def test_duplicate_city_names_get_station_number(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    await run("irceline", registry, storage, settings, _handler())
    names = [r["name"] for r in storage._query("SELECT name FROM stations WHERE source_id='irceline'")]  # noqa: SLF001
    assert len(names) == len(set(names))


async def test_one_layer_down_is_partial_not_fatal(registry, storage, settings, monkeypatch):
    _freeze(monkeypatch)
    ok, _, c = await run("irceline", registry, storage, settings, _handler(fail="o3_hmean_station"))
    assert ok
    params = {r["parameter"] for r in storage._query("SELECT DISTINCT parameter FROM measurements WHERE source_id='irceline'")}  # noqa: SLF001
    assert "O3" not in params and "PM10" in params


async def test_schema_change_is_an_error(registry, storage, settings):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unerwartet": True})
    ok, err, _ = await run("irceline", registry, storage, settings, handler)
    assert not ok and err
