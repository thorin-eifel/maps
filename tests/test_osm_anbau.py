"""Weinberge und Obstanlagen: Parser, Radiusfilter, Mindestfläche (ohne Netz)."""
import pytest

from app import config
from app.collectors import osm_anbau
from app.collectors.base import SourceError


def _ring(lat0: float, lon0: float, d: float = 0.002):
    pts = [(lon0, lat0), (lon0 + d, lat0), (lon0 + d, lat0 + d), (lon0, lat0 + d), (lon0, lat0)]
    return [{"lat": la, "lon": lo} for lo, la in pts]


def _el(i, landuse, geom, typ="way"):
    return {"type": typ, "id": i, "tags": {"landuse": landuse, "name": "Wingert Müller"}, "geometry": geom}


def test_parse_keeps_vineyard_inside_radius_without_names():
    data = {"elements": [_el(1, "vineyard", _ring(49.80, 6.90)), _el(2, "orchard", _ring(49.85, 6.45))]}
    got = osm_anbau.parse_elements(data)
    assert [g["kind"] for g in got] == ["orchard", "vineyard"]
    assert all(set(g) == {"id", "kind", "ring"} for g in got)     # kein Name, keine Tags
    assert got[0]["ring"][0] == got[0]["ring"][-1]


def test_parse_drops_outside_open_tiny_and_relations():
    far = _el(3, "vineyard", _ring(48.0, 11.0))
    opened = _el(4, "vineyard", _ring(49.8, 6.9)[:-1])
    tiny = _el(5, "vineyard", _ring(49.8, 6.9, 0.00003))
    rel = _el(6, "vineyard", _ring(49.8, 6.9), typ="relation")
    other = _el(7, "forest", _ring(49.8, 6.9))
    assert osm_anbau.parse_elements({"elements": [far, opened, tiny, rel, other]}) == []


def test_area_square_about_right():
    ring = [(p["lon"], p["lat"]) for p in _ring(49.8, 6.9, 0.001)]
    a = osm_anbau.area_m2(ring)
    assert 7000 < a < 9000      # 0,001° ≈ 72 m × 110 m


def test_bad_answer_raises():
    with pytest.raises(SourceError):
        osm_anbau.parse_elements({"nope": 1})


def test_quarters_cover_bbox():
    s, w, n, e = config.BBOX
    q = osm_anbau.quarters()
    assert len(q) == 4 and min(b[0] for b in q) == s and max(b[2] for b in q) == n and min(b[1] for b in q) == w and max(b[3] for b in q) == e
    assert 'landuse"="vineyard' in osm_anbau.build_query(q[0])
