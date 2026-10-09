"""Tests für app/region.py: Kreis (Regression zur alten Konfiguration), Polygon, Löcher, Gliederung, Geschwindigkeit."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest

from app import region
from app.region import Gliederung, PolygonIndex

BASE = Path(__file__).resolve().parent.parent
RLP = region.load(BASE / "region-rlp.yaml")


# ---------------------------------------------------------------- Kreis: gleiche Fläche wie vor R1
def test_radius_region_matches_old_constants():
    r = region.load(BASE / "region.yaml")
    assert r.mode == "radius" and r.radius_km == 120.0
    assert r.bbox == (48.76, 4.78, 50.93, 8.13)          # alter Wert von config.BBOX
    assert (r.ref_lat, r.ref_lon) == (49.84615562322509, 6.456057281843173)
    assert r.contains(49.85, 6.45) and r.contains(49.61, 6.13)         # Irrel, Luxemburg-Stadt
    assert not r.contains(48.58, 7.75)                                  # Straßburg: 130 km
    assert not r.contains(50.93, 4.78)                                  # Kastenecke: im Kasten, außerhalb des Kreises


def test_radius_edge_points():
    r = region.load(BASE / "region.yaml")
    d_lat = 120 / 111.195
    assert r.contains(r.ref_lat + d_lat * 0.995, r.ref_lon) and not r.contains(r.ref_lat + d_lat * 1.005, r.ref_lon)


def test_center_override_by_env(monkeypatch):
    monkeypatch.setenv("OSINT_CENTER_LAT", "50.0")
    monkeypatch.setenv("OSINT_CENTER_LON", "8.0")
    r = region.load(BASE / "region.yaml")
    assert (r.ref_lat, r.ref_lon) == (50.0, 8.0) and r.contains(50.0, 8.0) and not r.contains(49.0, 5.5)


# ---------------------------------------------------------------- Polygon: Rheinland-Pfalz plus 80 km
@pytest.mark.parametrize("name,lat,lon", [
    ("Irrel", 49.85, 6.45), ("Mainz", 50.00, 8.27), ("Trier", 49.75, 6.64), ("Koblenz", 50.36, 7.59),
    ("Ludwigshafen", 49.48, 8.44), ("Saarbrücken", 49.24, 6.99), ("Luxemburg", 49.61, 6.13), ("Metz", 49.12, 6.18),
    ("Frankfurt", 50.11, 8.68), ("Köln", 50.94, 6.96), ("Aachen", 50.78, 6.08), ("Lüttich", 50.63, 5.57),
    ("Karlsruhe", 49.01, 8.40), ("Straßburg", 48.58, 7.75), ("Stuttgart", 48.78, 9.18),
])
def test_polygon_contains_core_and_buffer(name, lat, lon):
    assert RLP.contains(lat, lon), name


@pytest.mark.parametrize("name,lat,lon", [
    ("Nancy", 48.69, 6.18), ("Brüssel", 50.85, 4.35), ("Paris", 48.85, 2.35), ("Würzburg", 49.79, 9.95),
    ("Münster", 51.96, 7.63), ("Berlin", 52.52, 13.40), ("Zürich", 47.37, 8.54),
])
def test_polygon_excludes_far_places(name, lat, lon):
    assert not RLP.contains(lat, lon), name


def test_polygon_edges_just_inside_and_outside():
    """An den äußersten Eckpunkten: 0,01° (ca. 1 km) nach innen liegt drin, 0,01° nach außen nicht."""
    data = json.loads((BASE / "app/data/region/rlp_plus80.json").read_text(encoding="utf-8"))
    pts = [p for poly in data["polygons"] for ring in poly for p in ring]
    n, s = max(pts, key=lambda p: p[1]), min(pts, key=lambda p: p[1])
    e, w = max(pts, key=lambda p: p[0]), min(pts, key=lambda p: p[0])
    assert RLP.contains(n[1] - 0.01, n[0]) and not RLP.contains(n[1] + 0.01, n[0])
    assert RLP.contains(s[1] + 0.01, s[0]) and not RLP.contains(s[1] - 0.01, s[0])
    assert RLP.contains(e[1], e[0] - 0.01) and not RLP.contains(e[1], e[0] + 0.01)
    assert RLP.contains(w[1], w[0] + 0.01) and not RLP.contains(w[1], w[0] - 0.01)


def test_polygon_bbox_and_query_circle_cover_everything():
    lat0, lon0, lat1, lon1 = RLP.bbox
    assert lat0 < 48.3 and lat1 > 51.6 and lon0 < 5.1 and lon1 > 9.5
    data = json.loads((BASE / "app/data/region/rlp_plus80.json").read_text(encoding="utf-8"))
    assert all(region.haversine_km(RLP.query_lat, RLP.query_lon, p[1], p[0]) <= RLP.query_radius_km
               for poly in data["polygons"] for ring in poly for p in ring)
    assert RLP.radius_km is None and "BKG" in RLP.attribution


def test_polygon_input_licence_and_checksum_documented():
    data = json.loads((BASE / "app/data/region/rlp_plus80.json").read_text(encoding="utf-8"))
    assert data["licence"] == "dl-de/by-2-0" and len(data["sha256_input"]) == 64 and data["buffer_km"] == 80.0


# ---------------------------------------------------------------- Löcher, Teilflächen
def test_index_hole_and_second_part():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6]]
    island = [[20, 0], [22, 0], [22, 2], [20, 2]]
    idx = PolygonIndex([[outer, hole], [island]])
    assert idx.contains(1, 1) and not idx.contains(5, 5)           # Loch (lat 5, lon 5)
    assert idx.contains(1, 21) and not idx.contains(1, 15)         # zweite Teilfläche, Lücke dazwischen
    assert not idx.contains(11, 5) and not idx.contains(-1, 5)


def test_index_rejects_empty():
    with pytest.raises(ValueError):
        PolygonIndex([[[[0, 0], [1, 0]]]])


@pytest.mark.parametrize("cfg,msg", [
    ("mode: kreis\nreference: {lat: 1, lon: 2}\n", "mode"),
    ("mode: radius\nreference: {lat: 1}\nradius_km: 5\n", "reference"),
    ("mode: radius\nreference: {lat: 1, lon: 2}\nradius_km: 0\n", "radius_km"),
])
def test_bad_config_fails_loudly(tmp_path, cfg, msg):
    p = tmp_path / "r.yaml"
    p.write_text(cfg)
    with pytest.raises(ValueError, match=msg):
        region.load(p)


# ---------------------------------------------------------------- Gliederung
def test_gliederung_kreis_and_land():
    g = Gliederung()
    assert g.kreis(49.85, 6.45) == {"ars": "07232", "name": "Eifelkreis Bitburg-Prüm", "land": "DE-RP"}
    assert g.kreis(50.00, 8.27)["ars"] == "07315"                        # Mainz
    assert g.kreis(49.24, 6.99)["land"] == "DE-SL" and g.kreis(50.11, 8.68)["land"] == "DE-HE"
    assert g.kreis(50.94, 6.96)["land"] == "DE-NW" and g.kreis(48.78, 9.18)["land"] == "DE-BW"
    assert g.kreis(49.61, 6.13) is None and g.kreis(50.63, 5.57) is None   # Luxemburg, Lüttich: nicht in VG250
    assert "BKG" in g.attribution


# ---------------------------------------------------------------- Tempo
def test_contains_speed_after_prefilter():
    rnd = random.Random(7)
    pts = [(rnd.uniform(48.3, 51.6), rnd.uniform(5.0, 9.6)) for _ in range(20000)]
    t = time.perf_counter()
    for la, lo in pts:
        RLP.contains(la, lo)
    per_point_us = (time.perf_counter() - t) / len(pts) * 1e6
    assert per_point_us < 20, f"{per_point_us:.1f} µs je Punkt"


# ---------------------------------------------------------------- Regression: Kreis entscheidet wie die alte Formel
def test_radius_region_equals_old_formula_on_random_points():
    r = region.load(BASE / "region.yaml")
    lat0, lon0, lat1, lon1 = 48.76, 4.78, 50.93, 8.13               # alte BBOX
    rnd = random.Random(42)
    diff = 0
    for _ in range(30000):
        la, lo = rnd.uniform(48.5, 51.2), rnd.uniform(4.5, 8.5)
        old = lat0 <= la <= lat1 and lon0 <= lo <= lon1 and region.haversine_km(49.84615562322509, 6.456057281843173, la, lo) <= 120.0
        diff += old != r.contains(la, lo)
    assert diff == 0


def test_margin_extends_radius_and_polygon():
    r = region.load(BASE / "region.yaml")
    d = 120 / 111.195
    assert not r.contains(r.ref_lat + d * 1.02, r.ref_lon) and r.contains(r.ref_lat + d * 1.02, r.ref_lon, margin_km=5)
    data = json.loads((BASE / "app/data/region/rlp_plus80.json").read_text(encoding="utf-8"))
    n = max((p for poly in data["polygons"] for ring in poly for p in ring), key=lambda p: p[1])
    assert not RLP.contains(n[1] + 0.03, n[0]) and RLP.contains(n[1] + 0.03, n[0], margin_km=5)
