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
