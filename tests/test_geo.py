"""Geo-Filter: Punkte knapp innerhalb/außerhalb des Radius, Grenzfälle Luxemburg."""
import copy
import json

import pytest

from app import geo
from conftest import fixture


def pt(lat, lon):
    return {"type": "Point", "coordinates": [lon, lat]}


def test_haversine_irrel_bitburg():
    d = geo.haversine_km(49.850, 6.450, 49.9737, 6.5225)
    assert 14 < d < 16  # Luftlinie Irrel–Bitburg


@pytest.mark.parametrize("name,lat,lon,expected", [
    ("Irrel selbst", 49.850, 6.450, True),
    ("Echternach (LU)", 49.812, 6.418, True),
    ("Luxemburg-Stadt (LU, Randlage)", 49.611, 6.130, True),
    ("Trier", 49.750, 6.637, True),
    ("Südostecke der Box (zu weit)", 48.80, 8.10, False),
    ("Köln (weit außerhalb Bounding Box)", 50.938, 6.960, False),
    ("Bounding-Box-Ecke NO: in der Box, aber > 120 km", 50.92, 8.12, False),
    ("119 km östlich (knapp innen)", 49.850, 6.450 + 119 / (111.195 * 0.6461), True),
    ("121 km östlich (knapp außen)", 49.850, 6.450 + 121 / (111.195 * 0.6461), False),
])
def test_point_radius(name, lat, lon, expected):
    assert geo.geometry_in_region(pt(lat, lon)) is expected, name


def test_bbox_is_only_prefilter():
    corner = pt(50.92, 8.12)
    assert geo.in_bbox(50.92, 8.12)
    assert not geo.geometry_in_region(corner)


def test_polygon_containing_center_has_distance_zero():
    poly = {"type": "Polygon", "coordinates": [[[6.3, 49.7], [6.6, 49.7], [6.6, 50.0], [6.3, 50.0], [6.3, 49.7]]]}
    assert geo.geometry_distance_km(poly) == 0.0


def test_polygon_with_hole_around_center():
    outer = [[6.0, 49.5], [6.9, 49.5], [6.9, 50.2], [6.0, 50.2], [6.0, 49.5]]
    hole = [[6.4, 49.8], [6.5, 49.8], [6.5, 49.9], [6.4, 49.9], [6.4, 49.8]]
    d = geo.geometry_distance_km({"type": "Polygon", "coordinates": [outer, hole]})
    assert 0 < d < 6  # Zentrum liegt im Loch, nächster Rand einige km entfernt


def test_line_passing_near_center():
    line = {"type": "LineString", "coordinates": [[6.0, 49.90], [6.9, 49.90]]}  # ca. 5,6 km nördlich
    assert 5 < geo.geometry_distance_km(line) < 6.2


def test_real_nina_polygon_just_inside():
    """Echte Meldung Rehlingen-Siersburg (Saarland) liegt ca. 48,5 km entfernt."""
    g = fixture("nina_warning_geo.json")["features"][0]["geometry"]
    d = geo.geometry_distance_km(g)
    assert 48.0 < d < 49.0
    assert geo.geometry_in_region(g)


def test_real_nina_polygon_shifted_outside():
    g = copy.deepcopy(fixture("nina_warning_geo.json")["features"][0]["geometry"])
    g["coordinates"] = [[[x, y - 1.3] for x, y in ring] for ring in g["coordinates"]]  # ca. 145 km nach Süden
    assert geo.geometry_distance_km(g) > 120
    assert not geo.geometry_in_region(g)


def test_geometry_collection_and_unknown_type():
    gc = {"type": "GeometryCollection", "geometries": [pt(53.0, 9.0), pt(49.86, 6.46)]}
    assert geo.geometry_in_region(gc)
    with pytest.raises(ValueError):
        geo.geometry_distance_km({"type": "Blob", "coordinates": []})


def test_representative_point():
    assert geo.representative_point(pt(49.5, 6.5)) == (49.5, 6.5)
    lat, lon = geo.representative_point({"type": "LineString", "coordinates": [[6.0, 49.0], [7.0, 50.0]]})
    assert (lat, lon) == (49.5, 6.5)


# ---------------------------------------------------------------- Polygon-Region (Rheinland-Pfalz plus 80 km)
def test_geometry_in_region_polygon_mode(monkeypatch):
    from pathlib import Path

    from app import region
    rlp = region.load(Path(__file__).resolve().parent.parent / "region-rlp.yaml")
    monkeypatch.setattr(region, "REGION", rlp)
    line = {"type": "LineString", "coordinates": [[2.0, 48.0], [14.0, 52.5]]}               # quert die Region ohne Stützpunkt darin
    assert geo.geometry_in_region(line)
    assert not geo.geometry_in_region({"type": "LineString", "coordinates": [[2.0, 52.0], [3.0, 52.5]]})
    assert geo.geometry_in_region({"type": "Point", "coordinates": [8.27, 50.0]})          # Mainz
    assert not geo.geometry_in_region({"type": "Point", "coordinates": [13.4, 52.5]})      # Berlin
    big = {"type": "Polygon", "coordinates": [[[0, 40], [20, 40], [20, 60], [0, 60], [0, 40]]]}   # Fläche umschließt alles
    assert geo.geometry_in_region(big)
