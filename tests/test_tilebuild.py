import math
import pytest
from app import tilebuild as t


def test_region_bbox_matches_shell_script_for_irrel():
    b = t.region_bbox(49.846, 6.456)
    assert abs(b[0] - 4.63) < 0.05 and abs(b[1] - 48.61) < 0.05 and abs(b[2] - 8.28) < 0.05 and abs(b[3] - 51.08) < 0.05


def test_core_bbox_matches_shell_script_for_irrel():
    assert t.core_bbox(49.846, 6.456) == (5.9, 49.49, 7.02, 50.21)


def test_ring_is_closed_has_hole_and_radius():
    g = t.ring_geojson(52.52, 13.40)["features"][0]["geometry"]["coordinates"]
    outer, hole = g
    assert outer[0] == outer[-1] and hole[0] == hole[-1]
    lon, lat = outer[0]
    d = math.hypot((lon - 13.40) * 111.32 * math.cos(math.radians(52.52)), (lat - 52.52) * 110.57)
    assert abs(d - t.RING_KM) < 1


def test_plan_has_three_files_and_rejects_bad_center():
    assert [n for n, _ in t.plan(49.8, 6.4)] == ["region.pmtiles", "core.pmtiles", "ring.pmtiles"]
    for lat, lon in [(95, 0), (0, 200), (float("nan"), 1)]:
        with pytest.raises(ValueError):
            t.plan(lat, lon)


def test_build_dry_run_writes_nothing(tmp_path):
    assert t.build(49.8, 6.4, tmp_path / "x", tmp_path / "pmtiles", "20260101", dry_run=True) == []
    with pytest.raises(ValueError):
        t.build(49.8, 6.4, tmp_path, tmp_path / "p", "bad")
