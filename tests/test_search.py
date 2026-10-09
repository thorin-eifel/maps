"""Suchindex: Faltung, Ortszuordnung, Clustern, Datensparsamkeit. Daten sind SYNTHETISCH."""
from __future__ import annotations

from app import payloads, search


def test_fold_umlaut_and_eszett():
    assert search.fold("Straße der Überlegung – Tünnes") == "strasse der uberlegung tunnes"
    assert search.fold("  Saint-Étienne ") == "saint etienne"


def test_clean_name_strips_quotes_and_control():
    assert search.clean_name('"Südöstliche Ecke"\n<b>') == "Südöstliche Ecke b"


def test_place_index_nearest_within_limit():
    px = search.PlaceIndex([{"n": "Irrel", "lat": 49.8467, "lon": 6.4562}, {"n": "Prümzurlay", "lat": 49.86, "lon": 6.47}], max_km=3)
    assert px.nearest(49.847, 6.457) == "Irrel"
    assert px.nearest(50.5, 7.5) == ""


def test_cluster_chains_and_splits():
    pts = [(49.80, 6.40), (49.81, 6.40), (49.82, 6.40), (50.50, 7.00)]
    groups = sorted(sorted(g) for g in search.cluster(pts, 1.5))
    assert groups == [[0, 1, 2], [3]]


def test_builder_filters_radius_dedupes_and_assigns_place():
    b = search.Builder(search.PlaceIndex([{"n": "Irrel", "lat": 49.8467, "lon": 6.4562}]))
    assert b.add("Hauptstraße", "Straße", 49.847, 6.457)
    assert not b.add("Hauptstraße", "Straße", 49.8470, 6.4572)            # gleicher Name, gleiches 100-m-Raster
    assert not b.add("Weit weg", "Straße", 51.5, 10.0)                    # außerhalb des Radius
    assert not b.add("X", "Straße", 49.85, 6.45)                          # zu kurz
    out = b.payload()
    assert out["e"] == [["Hauptstraße", search.T["Straße"], 498470, 64570, 0]] and out["o"] == ["Irrel"]
    assert len(out["t"]) == len(search.TYPES)


def test_dynamic_entries_types_and_no_unnamed():
    b = search.Builder(search.PlaceIndex([{"n": "Irrel", "lat": 49.8467, "lon": 6.4562}]))
    search.dynamic_entries(
        b,
        infra=[{"kind": "school", "name": "Grundschule Beispiel", "lat": 49.85, "lon": 6.46}, {"kind": "cemetery", "name": "", "lat": 49.85, "lon": 6.46},
               {"kind": "aed", "name": "Praxis", "lat": 49.85, "lon": 6.46}],
        landmarks=[{"kind": "castle", "name": '"Burg Beispiel"', "lat": 49.84, "lon": 6.44}],
        stops=[{"name": "Irrel Ort", "lat": 49.84, "lon": 6.45, "mode": "rail"}],
        routes=[{"kind": "hike", "name": "Eifelsteig", "ref": "", "lines": [[[6.4, 49.8], [6.5, 49.9]]]}],
        stations=[{"name": "Irrel Pegel", "lat": 49.85, "lon": 6.45}],
    )
    rows = {(e[0], search.TYPES[e[1]]) for e in b.payload()["e"]}
    assert rows == {("Grundschule Beispiel", "Schule"), ("Burg Beispiel", "Burg"), ("Irrel Ort", "Haltestelle"), ("Eifelsteig", "Wanderweg"), ("Irrel Pegel", "Pegel")}


def test_suche_payload_empty_SYNTHETISCH(registry, storage):
    out = payloads.suche_payload(storage, registry)
    assert out["v"] == 1 and out["e"] == [] and "generated_at" in out


def test_builder_skips_numeric_only_names():
    from app.search import Builder
    b = Builder()
    assert not b.add("40", "Wald", 49.85, 6.45)
    assert b.add("Wald 40", "Wald", 49.85, 6.45)
