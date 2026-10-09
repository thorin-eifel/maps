"""Infrastruktur aus Overpass: Parser, Radius, Datensparsamkeit, Nutzlast. Daten sind SYNTHETISCH (kein echter Abruf im Test)."""
from __future__ import annotations

import pytest

from app import payloads
from app.collectors import osm_infra
from app.collectors.base import SourceError


def _sample():
    return {"elements": [
        {"type": "node", "id": 1, "lat": 49.90, "lon": 6.50, "tags": {"power": "generator", "generator:source": "wind", "name": "Windpark Beispiel",
                                                                       "generator:output:electricity": "3 MW", "operator": "Herr Muster"}},
        {"type": "node", "id": 2, "lat": 49.91, "lon": 6.51, "tags": {"power": "generator", "generator:source": "solar"}},        # kein Windrad
        {"type": "node", "id": 3, "lat": 49.85, "lon": 6.45, "tags": {"amenity": "charging_station", "capacity": "4", "operator": "Privat",
                                                                       "name": "Wohnadresse Müller", "phone": "+49 123"}},
        {"type": "node", "id": 4, "lat": 49.86, "lon": 6.46, "tags": {"emergency": "defibrillator", "name": "Praxis Dr. Muster",
                                                                       "contact:phone": "0651 123", "description": "Freitext"}},
        {"type": "way", "id": 5, "center": {"lat": 49.84, "lon": 6.44}, "tags": {"amenity": "fire_station", "name": "Feuerwehr Beispiel"}},
        {"type": "way", "id": 6, "center": {"lat": 49.75, "lon": 6.64}, "tags": {"amenity": "hospital"}},                         # ohne Namen fällt weg
        {"type": "way", "id": 7, "center": {"lat": 49.75, "lon": 6.64}, "tags": {"amenity": "hospital", "name": "Krankenhaus Beispiel"}},
        {"type": "node", "id": 8, "lat": 50.92, "lon": 8.12, "tags": {"emergency": "defibrillator"}},                              # außerhalb 120 km
        {"type": "node", "id": 9, "lat": "x", "lon": 6.45, "tags": {"emergency": "defibrillator"}},
        {"type": "node", "id": 10, "lat": 49.86, "lon": 6.47, "tags": {"historic": "wayside_cross", "name": "Kreuz der Familie Muster", "inscription": "Zum Gedenken an Hans"}},
        {"type": "way", "id": 11, "center": {"lat": 49.87, "lon": 6.47}, "tags": {"building": "church", "name": "St. Beispiel"}},
        {"type": "way", "id": 12, "center": {"lat": 49.80, "lon": 6.42}, "tags": {"bridge": "yes", "highway": "primary", "name": "Sauerbrücke"}},
        {"type": "way", "id": 13, "center": {"lat": 49.81, "lon": 6.43}, "tags": {"bridge": "yes", "highway": "service"}},
        {"type": "way", "id": 15, "center": {"lat": 49.8001, "lon": 6.4201}, "tags": {"bridge": "yes", "name": "Sauerbrücke"}},                  # Zwilling derselben Brücke
        {"type": "way", "id": 16, "center": {"lat": 49.83, "lon": 6.45}, "tags": {"bridge": "yes", "name": "Hauptstraße"}},                      # Name ohne Brücke fällt weg               # Brücke ohne Namen fällt weg
        {"type": "node", "id": 14, "lat": 49.82, "lon": 6.44, "tags": {"tourism": "picnic_site", "name": "Grillplatz Hans", "operator": "Privat"}},
        {"type": "node", "id": 17, "lat": 49.84, "lon": 6.46, "tags": {"man_made": "watermill", "name": "Schmitts Mühle"}},
        {"type": "way", "id": 18, "center": {"lat": 49.80, "lon": 6.43}, "tags": {"bridge": "yes", "name": "Alte Sauerbrücke"}},
        {"type": "way", "id": 19, "center": {"lat": 49.85, "lon": 6.46}, "tags": {"amenity": "school", "name": "Grundschule Beispiel", "phone": "0651 1"}},
        {"type": "way", "id": 20, "center": {"lat": 49.85, "lon": 6.47}, "tags": {"amenity": "townhall", "name": "Gemeindeverwaltung Beispiel"}},
        {"type": "way", "id": 21, "center": {"lat": 49.86, "lon": 6.48}, "tags": {"landuse": "cemetery", "name": "Familiengrab Schmitt"}},
        {"type": "way", "id": 22, "center": {"lat": 49.8501, "lon": 6.4601}, "tags": {"amenity": "school", "name": "Grundschule Beispiel"}},      # zweites Gebäude derselben Schule
        "kein objekt",
    ]}


def test_parse_keeps_kinds_and_drops_the_rest_SYNTHETISCH():
    items = {i["id"]: i for i in osm_infra.parse_elements(_sample())}
    assert set(items) == {"node/1", "node/3", "node/4", "way/5", "way/7", "node/10", "way/11", "way/12", "node/14", "node/17", "way/18", "way/19", "way/20", "way/21"}
    assert items["node/1"]["kind"] == "wind" and items["node/1"]["kw"] == 3000 and items["node/1"]["name"] == "Windpark Beispiel"
    assert items["node/3"]["kind"] == "charging" and items["node/3"]["points"] == 4


def test_parse_is_data_sparing_SYNTHETISCH():
    items = {i["id"]: i for i in osm_infra.parse_elements(_sample())}
    assert items["node/4"] == {"id": "node/4", "kind": "aed", "name": "", "lat": 49.86, "lon": 6.46}      # Defibrillator: nur Standort
    assert items["node/3"]["name"] == ""                                                                       # Ladesäule: kein Name
    assert items["node/10"] == {"id": "node/10", "kind": "cross", "name": "", "lat": 49.86, "lon": 6.47}     # Wegkreuz: nur Standort
    assert items["way/11"]["name"] == "St. Beispiel"
    assert items["way/12"]["kind"] == "bridge" and items["way/12"]["name"] == "Sauerbrücke"
    assert items["node/17"] == {"id": "node/17", "kind": "watermill", "name": "", "lat": 49.84, "lon": 6.46}     # Mühle: nur Standort (Name könnte ein Familienname sein)
    assert items["way/18"]["old"] == 1 and "old" not in items["way/12"]
    assert items["node/14"] == {"id": "node/14", "kind": "picnic", "name": "", "lat": 49.82, "lon": 6.44}      # Rastplatz: nur Standort
    assert items["way/21"] == {"id": "way/21", "kind": "cemetery", "name": "", "lat": 49.86, "lon": 6.48}      # Friedhof: nur Mittelpunkt, kein Name
    assert items["way/19"]["name"] == "Grundschule Beispiel" and "phone" not in items["way/19"]
    blob = repr(items)
    for leak in ("Müller", "Muster", "Privat", "+49", "0651", "Freitext", "Hans", "Familie", "Grillplatz", "Schmitt", "0651 1", "Familiengrab"):
        assert leak not in blob


@pytest.mark.parametrize("raw,kw", [("3 MW", 3000), ("2500 kW", 2500), ("2.3MW", 2300), ("3000000 W", 3000), ("viel", None), ("", None), ("0 kW", None)])
def test_kw(raw, kw):
    assert osm_infra._kw(raw) == kw


def test_parse_rejects_garbage():
    with pytest.raises(SourceError):
        osm_infra.parse_elements({"nope": 1})
    with pytest.raises(SourceError):
        osm_infra.parse_elements([])


def test_queries_are_distinct_and_filtered():
    qs = {e[0]: osm_infra.build_query(e) for e in osm_infra.KINDS}
    assert len(set(qs.values())) == len(qs)
    assert '["generator:source"="wind"]' in qs["wind"] and '["name"]' in qs["hospital"] and '["name"]' not in qs["aed"]


def test_infrastruktur_payload_empty_SYNTHETISCH(registry, storage):
    assert payloads.infrastruktur_payload(storage, registry)["items"] == []
