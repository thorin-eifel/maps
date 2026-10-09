"""DWD-Stationen über Bright Sky: Auswahl aus echter Quellenliste, Lauf mit echter Beispielantwort."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.collectors.dwd_stationen import pick_stations
from tests.test_collectors_umwelt import run, FIX


def _sources():
    return json.loads((FIX / "brightsky_sources_real_2026-10-07.json").read_text())["sources"]


def test_pick_stations_keeps_recent_synop_once_per_station():
    now = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
    got = pick_stations(_sources(), now, 60)
    ids = [s["id"] for s in got]
    assert len(ids) == len(set(ids)) and "05100" in ids and "03584" in ids
    assert all(s["distance_km"] <= 120 for s in got)
    assert ids == sorted(ids, key=lambda i: next(s["distance_km"] for s in got if s["id"] == i))
    assert pick_stations(_sources(), datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc), 60) == []   # zu alt = stumm


async def test_collector_writes_stations_and_values(registry, storage, settings, monkeypatch):
    sample = (FIX / "brightsky_station_05100_real_2026-10-07.json").read_text()
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("/sources"):
            return httpx.Response(200, json={"sources": _sources()})
        return httpx.Response(200, text=sample)

    import app.collectors.dwd_stationen as mod
    monkeypatch.setattr(mod, "utcnow", lambda: datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc))   # Beispieldaten sind von 13:00 UTC
    ok, _, _ = await run("dwd_stationen", registry, storage, settings, handler)
    assert ok
    rows = storage._query("SELECT * FROM stations WHERE source_id='dwd_stationen'")  # noqa: SLF001
    assert rows and any(r["station_id"] == "05100" for r in rows)
    temp = storage._query("SELECT value FROM measurements WHERE source_id='dwd_stationen' AND parameter='temperature' AND station_id='05100'")  # noqa: SLF001
    assert temp and temp[0]["value"] == 22.8
