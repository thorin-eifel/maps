"""Tests der R3-Änderungen: Quellen auf Rheinland-Pfalz plus 80 km."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.collectors import load_collector_class, tankerkoenig
from conftest import make_client

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ Tankerkönig
def test_tank_grid_points_inside_margin_and_count():
    g = json.loads((ROOT / "app/data/region/tank_grid.json").read_text())
    from app import region
    big = region.load(ROOT / "region-rlp.yaml")
    assert 40 <= len(g["points"]) <= 90
    assert all(p["rad"] <= 25 for p in g["points"])
    assert all(big.contains(p["lat"], p["lon"], margin_km=30) for p in g["points"])


def test_tank_grid_covers_german_part_of_region():
    shapely = pytest.importorskip("shapely")
    import random
    from app import region
    big = region.load(ROOT / "region-rlp.yaml")
    gl = region.Gliederung()
    pts = json.loads((ROOT / "app/data/region/tank_grid.json").read_text())["points"]
    from app.geo import haversine_km
    rnd = random.Random(7)
    miss = tot = 0
    while tot < 1500:
        lat, lon = rnd.uniform(48.3, 51.6), rnd.uniform(5.0, 9.6)
        if not (big.contains(lat, lon) and gl.kreis(lat, lon)):
            continue
        tot += 1
        miss += not any(haversine_km(lat, lon, p["lat"], p["lon"]) <= 25 for p in pts)
    assert miss == 0, f"{miss} von {tot} deutschen Punkten außerhalb aller Kreise"


def test_tank_points_selection(monkeypatch):
    assert tankerkoenig.query_points({"points": [{"lat": 1, "lon": 2}]}) == [{"lat": 1, "lon": 2}]
    monkeypatch.setattr(tankerkoenig, "REGION", SimpleNamespace(mode="radius"))
    assert tankerkoenig.query_points({}) == tankerkoenig.DEFAULT_POINTS
    monkeypatch.setattr(tankerkoenig, "REGION", SimpleNamespace(mode="polygon"))
    assert len(tankerkoenig.query_points({})) >= 40


def _tank_reply(i):
    return {"ok": True, "stations": [{"id": f"id-{i}", "brand": "X", "place": "Ort", "lat": 49.8, "lng": 6.5, "isOpen": True, "e5": 1.9, "e10": 1.8, "diesel": 1.7}]}


async def test_tank_partial_failure_keeps_rest_and_flags_incomplete(registry, storage, settings, monkeypatch):
    monkeypatch.setenv("TANKERKOENIG_API_KEY", "k-test")
    monkeypatch.setattr(tankerkoenig, "REGION", SimpleNamespace(mode="polygon"))
    entry = registry.get("tankerkoenig")
    def h(req):
        lat = float(req.url.params["lat"])
        return httpx.Response(500) if int(lat * 100) % 3 == 0 else _tank_reply(int(lat * 1000))
    client, router = make_client(h)
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    c.pause_s = 0
    res = await c.collect()
    await client.aclose()
    assert res.complete is False and "fehlgeschlagen" in res.note
    assert 0 < len(res.stations) < 59 and "Punkte fehlgeschlagen" in res.note


# ------------------------------------------------------------------ Bildausschnitt
def test_extent_legacy_in_radius_mode_and_wide_in_polygon_mode(monkeypatch):
    from app import extent
    monkeypatch.setattr(extent, "REGION", SimpleNamespace(mode="radius", bbox=(48.76, 4.78, 50.93, 8.13)))
    assert extent.image_extent() == (4.4, 48.4, 8.5, 51.3) and extent.image_width() == 187
    monkeypatch.setattr(extent, "REGION", SimpleNamespace(mode="polygon", bbox=(48.247, 4.996, 51.661, 9.612)))
    lon0, lat0, lon1, lat1 = extent.image_extent()
    assert (lon0, lat0, lon1, lat1) == (4.6, 47.9, 10.01, 52.01)
    assert 240 < extent.image_width() < 260


# ------------------------------------------------------------------ Autobahn
@pytest.fixture
def _ab_clean():
    yield


def _ab_item(ident, lat=49.85, lon=6.45):
    return {"identifier": ident, "title": "A64", "subtitle": "x", "coordinate": {"lat": str(lat), "long": str(lon)},
            "isBlocked": "false", "startTimestamp": "2026-10-01T08:00:00.000+02:00", "description": ["Test"], "future": False,
            "extent": "", "display_type": "ROADWORKS"}


async def _ab_run(registry, storage, settings, handler, params_patch=None):
    entry = registry.get("autobahn")
    entry = entry.model_copy(update={"params": {**entry.params, **(params_patch or {})}})
    client, router = make_client(handler)
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    c.pause_s = 0
    res = await c.collect()
    await client.aclose()
    return res, router


async def test_autobahn_verify_roads_skips_unknown_without_failure(registry, storage, settings, _ab_clean):
    def h(req):
        parts = req.url.path.strip("/").split("/")
        if parts == ["o", "autobahn"]:
            return {"roads": ["A64", "A1", "A99"]}
        svc = parts[-1]
        return {svc: [_ab_item(f"{parts[-3]}-{svc}")] if svc == "closure" else []}
    res, router = await _ab_run(registry, storage, settings, h, {"roads": ["A64", "A1", "A3"], "services": ["closure"]})
    assert res.complete is True
    paths = {c.url.path for c in router.calls}
    assert "/o/autobahn/A3/services/closure" not in paths           # nicht in der Liste → gar nicht gefragt
    assert "/o/autobahn/A64/services/closure" in paths and len(res.events) == 2


async def test_autobahn_roadworks_cached_between_runs(registry, storage, settings, _ab_clean):
    def h(req):
        parts = req.url.path.strip("/").split("/")
        if parts == ["o", "autobahn"]:
            return {"roads": ["A64"]}
        svc = parts[-1]
        return {svc: [_ab_item(f"{svc}-1")]}
    patch = {"roads": ["A64"], "services": ["roadworks", "closure"]}
    r1, router1 = await _ab_run(registry, storage, settings, h, patch)
    r2, router2 = await _ab_run(registry, storage, settings, h, patch)
    assert sum(c.url.path.endswith("roadworks") for c in router1.calls) == 1
    assert sum(c.url.path.endswith("roadworks") for c in router2.calls) == 0     # aus dem Speicher
    assert sum(c.url.path.endswith("closure") for c in router2.calls) == 1       # Sperrungen jedes Mal frisch
    assert {e.id for e in r2.events} == {e.id for e in r1.events} and len(r2.events) == 2


async def test_autobahn_list_missing_is_an_error(registry, storage, settings, _ab_clean):
    from app.collectors.base import SourceError
    with pytest.raises(SourceError):
        await _ab_run(registry, storage, settings, lambda r: {"foo": []}, {"roads": ["A64"], "services": ["closure"]})


# ------------------------------------------------------------------ UBA
def test_uba_region_tag():
    from app.collectors.uba_luft import region_tag
    assert region_tag("DERP012") == "DE-RLP" and region_tag("DESL019") == "DE-SL"
    assert region_tag("DEBW118") == "DE-BW" and region_tag("DENW259") == "DE-NW" and region_tag("X") == "DE"


# ------------------------------------------------------------------ DWD Waldbrand
def test_waldbrand_thin_spreads_stations():
    from app.collectors.dwd_waldbrand import thin
    st = [{"id": str(i), "lat": 49.85 + 0.01 * i, "lon": 6.45} for i in range(50)]   # 50 Stationen auf 55 km Linie
    assert len(thin(st, 0, 10)) == 10 and thin(st, 0, 10)[0]["id"] == "0"
    spread = thin(st, 20, 10)
    assert [s["id"] for s in spread] == ["0", "18", "36"]       # alle ≥ 20 km auseinander
    assert len(thin(st, 20, 2)) == 2
