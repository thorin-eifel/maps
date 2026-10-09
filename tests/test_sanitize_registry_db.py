"""Bereinigung externer Texte, Quellenregister, Speicher (Idempotenz, Snapshot-Semantik)."""
from datetime import datetime, timezone

import pytest

from app.models import Event, Measurement, Station
from app.registry import Registry
from app.sanitize import clean_text


# ------------------------------------------------------------------ sanitize
def test_html_is_stripped():
    assert clean_text("Hallo <b>Welt</b><br/>zweite&nbsp;Zeile &amp; mehr") == "Hallo Welt zweite Zeile & mehr"


def test_script_content_dropped_and_truncated():
    out = clean_text("A<script>alert(1)</script>B" + "x" * 900, max_len=50)
    assert "alert" not in out and "<" not in out and len(out) <= 50 and out.endswith("…")


def test_control_chars_removed():
    assert clean_text("a\x00b\x07c") == "abc"


# ------------------------------------------------------------------ registry
def test_registry_loads_and_all_have_collector(registry):
    from app.collectors import load_collector_class
    assert {e.id for e in registry.active()} == {"nina", "irceline", "kmi_stationen", "dwd_warnungen", "brightsky", "pegelonline", "autobahn", "adsblol", "lbm_baustellen", "hochwasser_rlp", "bfs_odl", "uba_luft", "emsc", "dwd_radar", "dwd_icon_d2_wind", "bison_fute", "tankerkoenig", "statec_sprit", "osm_tankstellen_lu", "dwd_stationen", "eumetsat_li", "nasa_firms", "gtfs_static", "gtfs_rt_de", "osm_natur", "osm_infra", "osm_routen", "osm_anbau", "meteolux", "metno", "sensor_community", "volksfreund", "lu_pegel", "cita_lu", "dwd_waldbrand", "dwd_gesundheit", "hubeau_pegel", "wallonie_pegel", "brf", "meteoalarm"}
    for e in registry.active():
        assert load_collector_class(e.collector)
        assert e.lizenz and e.namensnennung and e.zuletzt_geprüft


def test_registry_rejects_duplicates(tmp_path, registry):
    with pytest.raises(ValueError):
        Registry([registry.entries[0], registry.entries[0]])


def test_public_view_hides_params(registry):
    assert "params" not in registry.entries[0].public()


# ------------------------------------------------------------------------ db
def ev(i="a", title="T", sev="info", lat=49.85, lon=6.45, src="autobahn"):
    return Event(id=f"{src}:{i}", source_id=src, type="traffic", title=title, severity=sev,
                 geometry={"type": "Point", "coordinates": [lon, lat]}, fetched_at=datetime.now(timezone.utc))


def test_same_event_twice_is_one_row(storage):
    assert storage.replace_snapshot("autobahn", [ev()]) == (1, 1)
    assert storage.replace_snapshot("autobahn", [ev()]) == (0, 1)
    assert storage._query("SELECT COUNT(*) n FROM events")[0]["n"] == 1


def test_update_changes_fields_keeps_first_seen(storage):
    storage.replace_snapshot("autobahn", [ev(title="alt")])
    first = storage._query("SELECT first_seen FROM events")[0][0]
    storage.replace_snapshot("autobahn", [ev(title="neu", sev="warning")])
    row = storage._query("SELECT * FROM events")[0]
    assert row["title"] == "neu" and row["severity"] == "warning" and row["first_seen"] == first


def test_vanished_event_is_deactivated_only_on_complete_run(storage):
    storage.replace_snapshot("autobahn", [ev("a"), ev("b")])
    storage.replace_snapshot("autobahn", [ev("a")], complete=False)  # halber Abruf: nichts löschen
    assert {e["id"] for e in storage.active_events()} == {"autobahn:a", "autobahn:b"}
    storage.replace_snapshot("autobahn", [ev("a")], complete=True)
    assert {e["id"] for e in storage.active_events()} == {"autobahn:a"}


def test_snapshots_are_per_source(storage):
    storage.replace_snapshot("autobahn", [ev("a")])
    storage.replace_snapshot("nina", [ev("x", src="nina")])
    storage.replace_snapshot("nina", [])
    assert {e["id"] for e in storage.active_events()} == {"autobahn:a"}


def test_measurements_idempotent_and_naive_time_rejected(storage):
    m = Measurement(source_id="p", station_id="s", parameter="W", ts=datetime(2026, 9, 29, 12, tzinfo=timezone.utc), value=1.0, unit="cm")
    assert storage.add_measurements([m]) == 1
    assert storage.add_measurements([m]) == 0
    with pytest.raises(ValueError):
        Measurement(source_id="p", station_id="s", parameter="W", ts=datetime(2026, 9, 29, 12), value=1.0, unit="cm")


def test_readonly_connection_cannot_write(settings, storage):
    from app.db import Storage
    import sqlite3
    ro = Storage(settings.db_path, readonly=True)
    with pytest.raises(sqlite3.OperationalError):
        ro._conn.execute("DELETE FROM events")


def test_data_version_bumps(storage):
    v = storage.data_version()
    storage.replace_snapshot("autobahn", [ev()])
    assert storage.data_version() > v
