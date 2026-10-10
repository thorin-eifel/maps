"""Erstlauf der Desktop-App: Fortschritt je Quelle, langsame Quellen später, Ablauf von work()."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app import collect, desktop


def fake(id_, later=False, ok=True, delay=0.0, name=None):
    async def run_once():
        await asyncio.sleep(delay)
        return ok
    return SimpleNamespace(entry=SimpleNamespace(id=id_, erstlauf="spaeter" if later else "sofort", kurzname=name or id_, name=id_), run_once=run_once)


def test_registry_marks_overpass_sources_as_later(registry):
    later = {e.id for e in registry.entries if e.erstlauf == "spaeter"}
    assert later == {"osm_natur", "osm_infra", "osm_anbau", "osm_routen", "osm_tankstellen_lu"}
    assert all(e.collector.startswith("osm_") for e in registry.entries if e.id in later)


def test_select_collectors_filters():
    cs = [fake("a"), fake("b", later=True), fake("c")]
    ids = lambda xs: [c.entry.id for c in xs]
    assert ids(collect.select_collectors(cs)) == ["a", "b", "c"]
    assert ids(collect.select_collectors(cs, skip_later=True)) == ["a", "c"]
    assert ids(collect.select_collectors(cs, only_later=True)) == ["b"]
    assert collect.select_collectors(cs, skip_later=True, only_later=True) == []


def test_run_once_writes_progress_with_running_names(tmp_path):
    path = tmp_path / "p.json"
    seen = []

    async def go():
        slow = fake("slow", delay=0.6, name="Langsame Quelle")
        fast = fake("fast", ok=False)

        async def watch():
            for _ in range(8):
                await asyncio.sleep(0.1)
                seen.append(json.loads(path.read_text()))
        return await asyncio.gather(collect.run_once([slow, fast], path), watch())

    rc, _ = asyncio.run(go())
    assert rc == 1                                   # eine Quelle fehlgeschlagen
    assert any(p["done"] == 1 and p["running"] == ["Langsame Quelle"] for p in seen)   # "läuft noch: <Name>"
    final = json.loads(path.read_text())
    assert final == {"total": 2, "done": 2, "running": [], "failed": ["fast"]}
    assert not list(tmp_path.glob("*.tmp"))


def test_run_once_without_progress_path_and_unwritable_path(tmp_path):
    assert asyncio.run(collect.run_once([fake("a")])) == 0
    assert asyncio.run(collect.run_once([fake("a")], tmp_path / "gibt" / "es" / "nicht.json")) == 0   # Fortschritt ist Beiwerk


@pytest.fixture()
def app(tmp_path):
    return desktop.App(tmp_path / "d", tmp_path / "web", tmp_path / "pmtiles", tmp_path)


def test_job_snapshot_reads_collector_progress(app):
    app.job.set("collect", "Daten werden abgerufen", 70)
    assert app.job_snapshot()["msg"] == "Daten werden abgerufen"     # Datei fehlt noch: letzte Meldung bleibt
    app.progress_path.write_text(json.dumps({"total": 40, "done": 30, "running": ["OSM", "Pegel"], "failed": []}))
    j = app.job_snapshot()
    assert j["msg"] == "Quellen: 30 von 40 abgerufen, läuft noch: OSM, Pegel" and j["pct"] == 85
    app.progress_path.write_text("{kaputt")
    assert app.job_snapshot()["msg"] == "Daten werden abgerufen"
    app.job.set("ready", "Bereit", 100)
    assert app.job_snapshot()["msg"] == "Bereit"                     # nur in der Phase collect


def test_work_first_run_skips_later_sources_then_runs_them_in_background(app, monkeypatch):
    for n in ("region", "core", "ring"):
        (app.data_dir / "tiles" / f"{n}.pmtiles").write_bytes(b"x")
    calls = []
    monkeypatch.setattr(app, "_run", lambda args, s, progress=None, timeout=1800: calls.append((tuple(args), progress is not None)) or 0)

    class Stop(BaseException):   # work() fängt Exception ab, der Test will aber aus der Endlosschleife heraus
        pass
    monkeypatch.setattr(desktop.time, "sleep", lambda _s: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        app.work({"lat": 49.85, "lon": 6.45})
    app.later.join(timeout=5)
    assert calls[0] == (("app.collect", "--once", "--skip-later"), True)
    assert calls[1][0][0] == "app.export"
    assert (("app.collect", "--due", "--only-later"), True) in calls
    assert app.job.snapshot()["phase"] == "ready"                    # bereit, bevor der Nachlauf fertig sein muss
