"""Routen aus Overpass: Parser, Vereinfachung, Radius, Datensparsamkeit. Daten sind SYNTHETISCH (kein echter Abruf im Test)."""
from __future__ import annotations

import pytest

from app import payloads
from app.collectors import osm_routen
from app.collectors.base import SourceError


def _way(*pts):
    return {"type": "way", "ref": 1, "geometry": [{"lat": la, "lon": lo} for lo, la in pts]}


def _sample():
    return {"elements": [
        {"type": "relation", "id": 1, "tags": {"route": "hiking", "network": "nwn", "name": "Beispielsteig", "ref": "BS", "operator": "Verein X", "description": "Freitext"},
         "members": [_way((6.40, 49.80), (6.41, 49.80), (6.42, 49.80), (6.43, 49.8001)), _way((8.9, 51.5), (8.91, 51.5))]},     # zweiter Weg außerhalb 120 km
        {"type": "relation", "id": 2, "tags": {"route": "hiking", "network": "nwn"}, "members": [_way((6.4, 49.8), (6.5, 49.8))]},  # ohne Namen
        {"type": "relation", "id": 3, "tags": {"route": "hiking", "name": "Weit weg"}, "members": [_way((8.9, 51.5), (8.91, 51.5))]},
        {"type": "node", "id": 4}, "kein objekt",
    ]}


def test_parse_keeps_named_routes_in_radius_SYNTHETISCH():
    got = osm_routen.parse_elements(_sample(), "hike")
    assert [r["id"] for r in got] == ["relation/1"]
    r = got[0]
    assert r["name"] == "Beispielsteig" and r["ref"] == "BS" and r["kind"] == "hike" and len(r["lines"]) == 1
    assert len(r["lines"][0]) == 2                                   # kollineare Zwischenpunkte entfallen
    blob = repr(got)
    for leak in ("Verein X", "Freitext"):
        assert leak not in blob


def test_simplify_keeps_corners():
    pts = [(0.0, 0.0), (0.001, 0.0), (0.002, 0.0), (0.002, 0.002)]
    assert osm_routen.simplify(pts) == [(0.0, 0.0), (0.002, 0.0), (0.002, 0.002)]


def test_parse_rejects_garbage():
    with pytest.raises(SourceError):
        osm_routen.parse_elements({"nope": 1}, "hike")


def test_queries_distinct():
    qs = [osm_routen.build_query(e) for e in osm_routen.KINDS]
    assert len(set(qs)) == 2 and "iwn|nwn|rwn" in qs[0] and "icn|ncn|rcn" in qs[1] and "out geom" in qs[0]


def test_routen_payload_empty_SYNTHETISCH(registry, storage):
    assert payloads.routen_payload(storage, registry)["items"] == []
