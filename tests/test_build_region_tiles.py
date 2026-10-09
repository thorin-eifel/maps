"""Tests für tools/build_region_tiles.py: Zellplanung ohne Lücke, Ring ohne Kerne, Vereinen ohne Doppelte.
Brauchen shapely und pmtiles (requirements-tools.txt); ohne sie werden die Tests übersprungen."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("shapely")
pytest.importorskip("pmtiles")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_region_tiles as b  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def region():
    return b.load_polygon(ROOT / "region-rlp.yaml")


@pytest.fixture(scope="module")
def cores():
    return b.core_geometries(ROOT / "tools" / "tile_cores.yaml")


def test_cells_cover_region_without_gap(region):
    cells = b.plan_cells(region)
    assert abs(unary_union([g for _, g in cells]).area - region.area) < 1e-6
    ids = [c for c, _ in cells]
    assert len(ids) == len(set(ids))


def test_ring_excludes_cores_and_cores_cover_them(region, cores):
    core_union = unary_union([g for _, g in cores])
    ring = unary_union([g for _, g, _ in b.stage_plan("ring", region, cores)])
    assert ring.intersection(core_union).area < 1e-6
    both = unary_union([ring, core_union.intersection(region)])
    assert region.difference(both).area < 1e-6


@pytest.mark.parametrize("lat,lon", [(49.85, 6.45), (49.99, 8.25), (49.24, 7.0), (50.36, 7.59)])
def test_known_places_in_region_and_in_some_cell(region, lat, lon):
    p = Point(lon, lat)
    assert region.contains(p)
    assert any(g.intersects(p) for _, g in b.plan_cells(region))


def test_stage_zooms(region, cores):
    assert {z for _, _, z in b.stage_plan("region", region, cores)} == {(0, 13)}
    assert {z for _, _, z in b.stage_plan("ring", region, cores)} == {(14, 14)}
    assert {z for _, _, z in b.stage_plan("cores", region, cores)} == {(14, 15)}


def _write(path: Path, tiles: dict[int, bytes]) -> None:
    from pmtiles.tile import Compression, TileType
    from pmtiles.writer import Writer
    with open(path, "wb") as fh:
        w = Writer(fh)
        for tid in sorted(tiles):
            w.write_tile(tid, tiles[tid])
        w.finalize({"tile_type": TileType.MVT, "tile_compression": Compression.NONE, "min_zoom": 0, "max_zoom": 2,
                    "min_lon_e7": 0, "min_lat_e7": 0, "max_lon_e7": 10, "max_lat_e7": 10,
                    "center_zoom": 0, "center_lon_e7": 5, "center_lat_e7": 5}, {"name": "t"})


def test_merge_dedupes_and_keeps_order(tmp_path):
    _write(tmp_path / "a.pmtiles", {0: b"A0", 1: b"A1", 2: b"A2"})
    _write(tmp_path / "b.pmtiles", {2: b"A2", 3: b"B3", 5: b"B5"})
    stats = b.merge([tmp_path / "a.pmtiles", tmp_path / "b.pmtiles"], tmp_path / "m.pmtiles")
    assert stats["kacheln_gelesen"] == 6 and stats["kacheln"] == 5
    got = list(b._tiles(tmp_path / "m.pmtiles"))
    assert [t for t, _ in got] == [0, 1, 2, 3, 5]
    assert dict(got)[5] == b"B5"


def test_merge_without_chunks_fails(tmp_path):
    with pytest.raises(ValueError):
        b.merge([], tmp_path / "x.pmtiles")


def test_merge_header_center_zoom_within_range(tmp_path):
    from pmtiles.reader import MmapSource, Reader
    _write(tmp_path / "a.pmtiles", {0: b"A"})
    b.merge([tmp_path / "a.pmtiles"], tmp_path / "m.pmtiles")
    with open(tmp_path / "m.pmtiles", "rb") as fh:
        h = Reader(MmapSource(fh)).header()
    assert h["min_zoom"] <= h["center_zoom"] <= h["max_zoom"]
