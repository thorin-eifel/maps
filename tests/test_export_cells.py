"""Zellenexport: Zuordnung, Manifest, Startpaket, Stabilität, Größenwarnung."""
import json
from datetime import timedelta

from app import export, export_cells
from app.models import Event, utcnow



def mk(i, coords, typ="traffic", sev="info", gtype="Point", title=None, summary=None):
    return Event(id=f"autobahn:{i}", source_id="autobahn", type=typ, title=title or f"E{i}", severity=sev, summary=summary or "",
                 geometry={"type": gtype, "coordinates": coords}, fetched_at=utcnow())


def load(out, rel):
    return json.loads((out / rel).read_text(encoding="utf-8"))


def test_events_land_in_the_right_cells_and_lines_in_several(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [
        mk("punkt", [6.45, 49.85]),                                     # 12_99
        mk("kante", [6.5, 49.7]),                                       # genau auf der Kante, gehört 13_99
        mk("linie", [[6.4, 49.95], [6.6, 49.95]], gtype="LineString"),  # 12_99 und 13_99
    ])
    m = export.run_export(storage, registry, tmp_path)
    ids = lambda c: {f["id"] for f in load(tmp_path, f"z/{c}/events.json")["features"]}
    assert ids("12_99") == {"autobahn:punkt", "autobahn:linie"}
    assert ids("13_99") == {"autobahn:kante", "autobahn:linie"}
    assert set(m["cells"]) >= {"12_99", "13_99"}


def test_every_cell_file_carries_source_licence_stand_and_no_clock_fields(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85], sev="warning")])
    export.run_export(storage, registry, tmp_path)
    d = load(tmp_path, "z/12_99/events.json")
    src = d["sources"][0]
    assert src["id"] == "autobahn" and src["license"] and src["attribution"] and src["betreiber"]
    assert d["cell"] == "12_99" and d["stand"].endswith("Z") and d["kind"] == "events"
    p = d["features"][0]["properties"]
    for volatile in ("age_s", "source_status", "fetched_at"):
        assert volatile not in p
    assert "age_s" not in json.dumps(d) and "last_success" not in json.dumps(d)


def test_manifest_hashes_match_files_and_list_every_file(storage, registry, tmp_path):
    import hashlib
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85])])
    m = export.run_export(storage, registry, tmp_path)
    for rel, info in m["files"].items():
        raw = (tmp_path / rel).read_bytes()
        assert info["bytes"] == len(raw) and info["sha256"] == hashlib.sha256(raw).hexdigest(), rel
    assert "start.json" in m["files"] and m["files"]["start.json"]["kind"] == "start"
    assert m["grid"]["cell_deg"] == 0.5 and m["budgets"]["cell_bytes"] == 512000
    on_disk = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file() and not p.name.startswith(".") and p.name != "manifest.json" and not p.name.startswith("t.sqlite")}
    assert on_disk == set(m["files"])


def test_start_package_has_warnband_counts_and_stays_small(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk("w", [6.45, 49.85], sev="critical", typ="warning", title="Sperrung"), mk("i", [6.45, 49.85])])
    m = export.run_export(storage, registry, tmp_path)
    s = load(tmp_path, "start.json")
    assert [w["id"] for w in s["warnband"]] == ["autobahn:w"] and s["warnband_total"] == 1
    assert s["counts"]["events"] == 2 and s["cells"]["12_99"]["max_severity"] == "critical"
    assert s["meta"]["name"] and s["disclaimer"] and any(x["id"] == "autobahn" for x in s["sources"])
    assert m["files"]["start.json"]["bytes"] < export_cells.START_BUDGET_BYTES


def test_unchanged_data_keeps_cell_bytes_and_stand(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85]), mk("b", [[6.4, 49.95], [6.6, 49.95]], gtype="LineString")])
    m1 = export.run_export(storage, registry, tmp_path)
    before = (tmp_path / "z/12_99/events.json").read_bytes()
    # neuer Abruf derselben Daten: fetched_at, last_seen ändern sich, der Inhalt nicht
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85]), mk("b", [[6.4, 49.95], [6.6, 49.95]], gtype="LineString")])
    m2 = export.run_export(storage, registry, tmp_path)
    assert (tmp_path / "z/12_99/events.json").read_bytes() == before
    cell_files = [r for r in m1["files"] if r.startswith("z/")]
    assert cell_files and all(m1["files"][r]["sha256"] == m2["files"][r]["sha256"] for r in cell_files)


def test_changed_event_changes_only_its_cells(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85]), mk("far", [8.2, 49.2])])
    m1 = export.run_export(storage, registry, tmp_path)
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85], title="geändert"), mk("far", [8.2, 49.2])])
    m2 = export.run_export(storage, registry, tmp_path)
    changed = {r for r in m1["files"] if r.startswith("z/") and m1["files"][r]["sha256"] != m2["files"][r]["sha256"]}
    assert changed == {"z/12_99/events.json"}


def test_removed_cell_is_deleted_locally_and_dropped_from_manifest(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85]), mk("far", [8.2, 49.2])])
    export.run_export(storage, registry, tmp_path)
    assert (tmp_path / "z/16_98/events.json").exists()
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85])])
    m = export.run_export(storage, registry, tmp_path)
    assert not (tmp_path / "z/16_98").exists() and "z/16_98/events.json" not in m["files"]


def test_cell_over_budget_is_reported_not_truncated(storage, registry, tmp_path, caplog):
    big = "x" * 900
    storage.replace_snapshot("autobahn", [mk(f"n{i}", [6.45 + (i % 40) / 1000, 49.85], summary=big) for i in range(700)])
    m = export.run_export(storage, registry, tmp_path)
    info = m["files"]["z/12_99/events.json"]
    assert info["over_budget"] is True and info["items"] == 700
    assert any("z/12_99/events.json" in w for w in m["warnings"])
    assert len(load(tmp_path, "z/12_99/events.json")["features"]) == 700


def test_event_limit_not_cut_at_2000(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk(f"n{i}", [6.45 + (i % 40) / 1000, 49.85 + (i % 7) / 100]) for i in range(2300)])
    m = export.run_export(storage, registry, tmp_path)
    assert sum(i["items"] for r, i in m["files"].items() if r.endswith("/events.json")) == 2300
    assert len(load(tmp_path, "events.json")["features"]) == 2000      # Flachdatei (bis R5) bleibt bei 2000


def test_no_cells_flag_writes_only_flat_files(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85])])
    assert export.run_export(storage, registry, tmp_path, cells=False) == {}
    assert (tmp_path / "events.json").exists() and not (tmp_path / "manifest.json").exists() and not (tmp_path / "z").exists()


def test_no_legacy_drops_replaced_flat_files_but_keeps_global_ones(storage, registry, tmp_path):
    storage.replace_snapshot("autobahn", [mk("a", [6.45, 49.85])])
    m = export.run_export(storage, registry, tmp_path, legacy=False)
    assert not (tmp_path / "events.json").exists() and (tmp_path / "status.json").exists() and (tmp_path / "meta.json").exists()
    assert m["files"]["status.json"]["upload"] == "always" and m["files"]["suche.json"]["kind"] == "global"


def test_export_time_budget_with_realistic_volume(storage, registry, tmp_path):
    import time
    storage.replace_snapshot("autobahn", [mk(f"n{i}", [6.0 + (i % 90) / 40, 49.0 + (i % 70) / 40]) for i in range(4000)])
    t = time.monotonic()
    export.run_export(storage, registry, tmp_path)
    assert time.monotonic() - t < 60
