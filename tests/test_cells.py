"""Zellenzuordnung (app/cells.py): Kanten, Linien und Flächen über mehrere Zellen."""
import pytest

from app import cells
from app.cells import cell_id, cell_of, cells_for_geometry, cells_for_lines, cells_for_point, parse_cell_id


def test_cell_of_irrel_and_id_roundtrip():
    assert cell_of(6.45, 49.85) == (12, 99)
    assert cell_id((12, 99)) == "12_99" and parse_cell_id("12_99") == (12, 99)
    assert cells.cell_bbox((12, 99)) == (6.0, 49.5, 6.5, 50.0)


def test_point_on_cell_edge_belongs_to_higher_cell_only():
    assert cells_for_geometry({"type": "Point", "coordinates": [6.5, 49.7]}) == {(13, 99)}      # Ostkante
    assert cells_for_geometry({"type": "Point", "coordinates": [6.2, 50.0]}) == {(12, 100)}     # Nordkante
    assert cells_for_geometry({"type": "Point", "coordinates": [6.5, 50.0]}) == {(13, 100)}     # Ecke
    assert cells_for_geometry({"type": "Point", "coordinates": [6.4999999, 49.9999999]}) == {(12, 99)}


def test_point_helpers_reject_garbage():
    assert cells_for_point(None, 6.0) == set() and cells_for_point("x", 6.0) == set() and cells_for_point(float("nan"), 6.0) == set()
    assert cells_for_point(49.85, 6.45) == {(12, 99)}
    assert cells_for_geometry(None) == set() and cells_for_geometry({}) == set() and cells_for_geometry({"type": "Point", "coordinates": []}) == set()


def test_line_across_cells_lists_every_cell_it_touches():
    line = {"type": "LineString", "coordinates": [[6.4, 49.9], [7.1, 49.9]]}
    assert cells_for_geometry(line) == {(12, 99), (13, 99), (14, 99)}


def test_diagonal_line_does_not_claim_cells_it_misses():
    # von (6.1, 49.1) nach (6.9, 49.9): läuft diagonal durch (12,98), (13,98)?, (13,99) – nie durch (12,99)-Nordwesten oder (13,98)-Südosten fern der Diagonalen
    got = cells_for_geometry({"type": "LineString", "coordinates": [[6.1, 49.1], [6.9, 49.9]]})
    assert (12, 98) in got and (13, 99) in got
    assert (14, 98) not in got and (11, 99) not in got and (12, 100) not in got


def test_line_through_corner_touches_all_four_cells():
    got = cells_for_geometry({"type": "LineString", "coordinates": [[6.4, 49.4], [6.6, 49.6]]})
    assert {(12, 98), (13, 99)} <= got


def test_multilinestring_and_route_lines():
    g = {"type": "MultiLineString", "coordinates": [[[6.1, 49.6], [6.2, 49.6]], [[7.6, 49.6], [7.7, 49.6]]]}
    assert cells_for_geometry(g) == {(12, 99), (15, 99)}
    assert cells_for_lines([[[6.1, 49.6], [6.9, 49.6]]]) == {(12, 99), (13, 99)}


def test_polygon_spanning_cells_includes_interior_cells_without_edge():
    sq = [[5.2, 48.2], [8.8, 48.2], [8.8, 51.8], [5.2, 51.8], [5.2, 48.2]]
    got = cells_for_geometry({"type": "Polygon", "coordinates": [sq]})
    assert (13, 99) in got                                  # Innenzelle ohne Randberührung
    assert len(got) == (17 - 10 + 1) * (103 - 96 + 1)       # x 10..17, y 96..103
    assert (9, 99) not in got and (18, 99) not in got


def test_polygon_hole_cells_are_excluded():
    outer = [[5.0, 48.0], [9.0, 48.0], [9.0, 52.0], [5.0, 52.0], [5.0, 48.0]]
    hole = [[6.0, 49.0], [8.0, 49.0], [8.0, 51.0], [6.0, 51.0], [6.0, 49.0]]
    got = cells_for_geometry({"type": "Polygon", "coordinates": [outer, hole]})
    assert (13, 99) not in got and (14, 99) not in got      # ganz im Loch
    assert (10, 96) in got and (11, 97) in got
    assert (12, 98) in got                                  # Lochrand läuft durch die Zelle


def test_multipolygon_union_and_tiny_polygon_in_one_cell():
    tiny = [[6.10, 49.60], [6.11, 49.60], [6.11, 49.61], [6.10, 49.60]]
    other = [[7.60, 49.60], [7.61, 49.60], [7.61, 49.61], [7.60, 49.60]]
    assert cells_for_geometry({"type": "Polygon", "coordinates": [tiny]}) == {(12, 99)}
    assert cells_for_geometry({"type": "MultiPolygon", "coordinates": [[tiny], [other]]}) == {(12, 99), (15, 99)}


def test_runaway_geometry_is_refused():
    huge = {"type": "LineString", "coordinates": [[-170.0, -80.0], [170.0, 80.0]]}
    with pytest.raises(ValueError):
        cells_for_geometry(huge)
