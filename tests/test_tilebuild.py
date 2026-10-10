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


def test_step_fraction_caps_running_file_below_done():
    assert t.step_fraction(0, 0, 360, 700) == 0
    assert 0.25 < t.step_fraction(0, 180, 360, 700) < 0.26
    assert t.step_fraction(0, 9999, 360, 700) < 360 / 700  # läuft nie über den eigenen Anteil, solange die Datei nicht fertig ist
    assert t.step_fraction(360, 130, 130, 700) < 490 / 700
    assert t.step_fraction(0, 0, 100, 0) == 0


def test_run_watched_reports_growing_size_and_raises_on_failure(tmp_path):
    import subprocess
    import sys
    tmp = tmp_path / ".x.tmp"
    code = "import sys,time\nf=open(sys.argv[1],'wb')\nfor _ in range(4):\n f.write(b'x'*1000000); f.flush(); time.sleep(0.3)\n"
    seen: list[float] = []
    t.run_watched([sys.executable, "-c", code, str(tmp)], tmp, seen.append, 30, interval=0.2)
    assert seen and seen == sorted(seen) and seen[-1] > 0
    with pytest.raises(subprocess.CalledProcessError):
        t.run_watched([sys.executable, "-c", "raise SystemExit(3)"], tmp, seen.append, 30, interval=0.2)
    with pytest.raises(subprocess.TimeoutExpired):
        t.run_watched([sys.executable, "-c", "import time; time.sleep(30)"], tmp, seen.append, 0.5, interval=0.2)


def test_build_reports_monotonic_progress_to_one(tmp_path, monkeypatch):
    fake = tmp_path / "pmtiles"
    fake.write_text('#!/bin/sh\n[ "$1" = show ] && exit 0\nhead -c 3000000 /dev/zero > "$3"\nsleep 1.2\n')
    fake.chmod(0o755)
    monkeypatch.setattr(t, "EXPECTED_MB", {"region.pmtiles": 3, "core.pmtiles": 3, "ring.pmtiles": 3})
    calls: list[tuple] = []
    out = tmp_path / "tiles"
    t.build(49.85, 6.45, out, fake, "20260101", progress=lambda *a: calls.append(a))
    fr = [c[3] for c in calls]
    assert fr == sorted(fr) and fr[-1] == 1.0 and fr[0] == 0.0
    assert any("MB von etwa" in c[2] for c in calls)
    assert {p.name for p in out.iterdir()} == {"region.pmtiles", "core.pmtiles", "ring.pmtiles"}
