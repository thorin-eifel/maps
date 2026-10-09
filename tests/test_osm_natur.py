"""Landmarken aus Overpass: Parser, Radius, Datensparsamkeit, Nutzlast. Daten sind SYNTHETISCH (kein echter Abruf im Test)."""
from __future__ import annotations

import pytest

from app import payloads
from app.collectors import osm_natur
from app.collectors.base import SourceError


def _sample():
    return {"elements": [
        {"type": "node", "id": 1, "lat": 49.86, "lon": 6.45, "tags": {"natural": "cave_entrance"}},                       # unbenannt, bleibt
        {"type": "node", "id": 2, "lat": 49.87, "lon": 6.46, "tags": {"waterway": "waterfall", "name": "Irreler Wasserfälle", "ele": "195 m"}},
        {"type": "way", "id": 3, "center": {"lat": 49.80, "lon": 6.40}, "tags": {"tourism": "viewpoint", "name": "Aussicht Beispiel",
                                                                                  "description": "Freitext bleibt draußen", "operator": "Herr Muster"}},
        {"type": "node", "id": 4, "lat": 49.85, "lon": 6.44, "tags": {"natural": "spring"}},                              # unbenannte Quelle fällt weg
        {"type": "node", "id": 5, "lat": 49.85, "lon": 6.44, "tags": {"natural": "rock", "name": "Teufelsfels"}},
        {"type": "node", "id": 6, "lat": 50.92, "lon": 8.12, "tags": {"natural": "cave_entrance", "name": "Zu weit"}},     # im Kasten, außerhalb 120 km
        {"type": "node", "id": 7, "lat": 49.85, "lon": 6.45, "tags": {"natural": "peak", "name": "Gipfel gehört in die Kacheln"}},
        {"type": "node", "id": 8, "lat": "x", "lon": 6.45, "tags": {"natural": "volcano", "name": "Kaputt"}},
        "kein objekt",
    ]}


def test_parse_keeps_named_and_unnamed_where_allowed_SYNTHETISCH():
    items = osm_natur.parse_elements(_sample())
    by_id = {i["id"]: i for i in items}
    assert set(by_id) == {"node/1", "node/2", "way/3", "node/5"}
    assert by_id["node/1"]["kind"] == "cave" and by_id["node/1"]["name"] == ""
    assert by_id["node/2"]["ele"] == 195
    assert (by_id["way/3"]["lat"], by_id["way/3"]["lon"]) == (49.80, 6.40)


def test_parse_stores_no_free_text_SYNTHETISCH():
    items = osm_natur.parse_elements(_sample())
    blob = str(items)
    assert "Freitext" not in blob and "Herr Muster" not in blob
    assert all(set(i) <= {"id", "kind", "name", "lat", "lon", "ele"} for i in items)


def test_parse_rejects_garbage():
    with pytest.raises(SourceError):
        osm_natur.parse_elements({"nope": 1})
    with pytest.raises(SourceError):
        osm_natur.parse_elements([])


def test_query_per_kind_and_bbox():
    qs = [osm_natur.build_query(e) for e in osm_natur.KINDS]
    assert len(qs) == len(osm_natur.KINDS) and len(set(qs)) == len(qs)
    joined = " ".join(qs)
    for needle in ("cave_entrance", "waterfall", "viewpoint", "spring", "volcano", "48.76,4.78,50.93,8.13"):
        assert needle in joined
    assert all(q.startswith("[out:json]") and q.endswith("out center tags;") for q in qs)
    by = {e[1][1]: q for e, q in zip(osm_natur.KINDS, qs)}
    assert '["name"]' in by["spring"] and '["name"]' not in by["viewpoint"]


def test_landmarks_payload_empty_and_filled_SYNTHETISCH(registry, storage):
    assert payloads.landmarks_payload(storage, registry)["items"] == []
    storage.cache_put("landmarks", "osm_natur", {"items": osm_natur.parse_elements(_sample()), "counts": {}})
    out = payloads.landmarks_payload(storage, registry)
    assert len(out["items"]) == 4 and out["fetched_at"]


def _heritage():
    return {"elements": [
        {"type": "way", "id": 11, "center": {"lat": 49.97, "lon": 6.52}, "tags": {"historic": "castle", "name": "Burg Beispiel", "wikipedia": "de:X", "inscription": "Freitext"}},
        {"type": "node", "id": 12, "lat": 49.90, "lon": 6.47, "tags": {"historic": "ruins", "name": "Ruine Muster"}},
        {"type": "node", "id": 13, "lat": 49.91, "lon": 6.40, "tags": {"historic": "archaeological_site", "name": "Römische Villa Beispiel"}},
        {"type": "node", "id": 14, "lat": 49.91, "lon": 6.41, "tags": {"historic": "archaeological_site"}},                 # unbenannt fällt weg
        {"type": "node", "id": 15, "lat": 49.85, "lon": 6.45, "tags": {"historic": "memorial", "name": "Gedenkstein für Herrn X"}},   # Gedenkort: nie
        {"type": "node", "id": 16, "lat": 49.85, "lon": 6.46, "tags": {"historic": "memorial", "memorial": "stolperstein", "name": "Anna Beispiel"}},
        {"type": "node", "id": 17, "lat": 49.86, "lon": 6.47, "tags": {"historic": "monastery", "name": "Kloster Beispiel"}},
        {"type": "way", "id": 18, "center": {"lat": 49.88, "lon": 6.49}, "tags": {"historic": "city_gate", "name": "Stadttor"}},
        {"type": "node", "id": 19, "lat": 50.92, "lon": 8.12, "tags": {"historic": "castle", "name": "Zu weit"}},
    ]}


def test_heritage_kinds_named_only_and_no_memorials_SYNTHETISCH():
    items = {i["id"]: i for i in osm_natur.parse_elements(_heritage())}
    assert set(items) == {"way/11", "node/12", "node/13", "node/17", "way/18"}
    assert [items[k]["kind"] for k in ("way/11", "node/12", "node/13", "node/17", "way/18")] == ["castle", "ruins", "archaeological", "monastery", "building"]
    blob = str(items)
    assert "Freitext" not in blob and "Anna" not in blob and "Gedenkstein" not in blob and "wikipedia" not in blob


def test_heritage_queries_exist_and_memorial_is_not_queried():
    joined = " ".join(osm_natur.build_query(e) for e in osm_natur.KINDS)
    for needle in ("castle", "fort", "manor", "ruins", "archaeological_site", "monastery", "city_gate"):
        assert f'"historic"="{needle}"' in joined
    assert "memorial" not in joined
    assert all('["name"]' in osm_natur.build_query(e) for e in osm_natur.KINDS if e[1][0] == "historic")
