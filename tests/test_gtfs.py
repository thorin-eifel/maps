"""GTFS-Fahrplanindex und Echtzeit-Verspätungen. Alle Feeds sind synthetisch (klein, selbst gebaut), Aufbau wie die echten Dateien."""
import io
import zipfile
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from google.transit import gtfs_realtime_pb2 as pb

from app import gtfs
from test_collectors_umwelt import run

STOPS = (
    "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
    "A,Irrel Bahnhof,49.8500,6.4500,0\n"
    "B,Bitburg Stadt,49.9700,6.5200,0\n"
    "D,Irrel Schule,49.8520,6.4520,0\n"
    "C,Paris Est,48.8767,2.3592,0\n"
    "S1,Irrel Fläche,49.8500,6.4500,1\n"
)
ROUTES = "route_id,route_short_name,route_type\nR1,RE 1,2\nR2,Bus 5,3\nR3,RE 9,2\n"
TRIPS = "route_id,trip_id,trip_headsign\nR1,T1,Trier Hbf\nR2,T2,Bitburg\nR3,T3,Paris\nR1,T4,Trier Hbf\n"
TIMES = ("trip_id,stop_id,stop_sequence\nT1,A,1\nT1,B,2\nT2,D,1\nT3,C,1\nT4,A,1\n")


def make_zip(**over) -> bytes:
    files = {"stops.txt": STOPS, "routes.txt": ROUTES, "trips.txt": TRIPS, "stop_times.txt": TIMES, **over}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, c in files.items():
            if c is not None:
                z.writestr(n, c)
    return buf.getvalue()


def test_index_radius_modes_and_trips_SYNTHETISCH():
    idx = gtfs.build_index(make_zip(), keep_trips=True)
    assert set(idx["stops"]) == {"A", "B", "D"}                      # Paris weit weg, S1 ist eine Bahnhofsfläche
    assert idx["stops"]["A"][3] == ["rail"] and idx["stops"]["D"][3] == ["bus"]
    assert set(idx["trips"]) == {"T1", "T2", "T4"}                   # T3 hält nur in Paris
    assert idx["trips"]["T1"] == ["RE 1", "Trier Hbf", "rail", "A"]
    assert "trips" not in gtfs.build_index(make_zip(), keep_trips=False)


def test_index_missing_file_is_error():
    with pytest.raises(ValueError):
        gtfs.build_index(make_zip(**{"routes.txt": None}), keep_trips=False)


def test_mode_of_extended_types():
    assert (gtfs.mode_of(2), gtfs.mode_of(109), gtfs.mode_of(3), gtfs.mode_of(714), gtfs.mode_of(0), gtfs.mode_of(1000)) == ("rail", "rail", "bus", "bus", "tram", "other")


def rt_feed(now, mutate=None) -> bytes:
    fm = pb.FeedMessage()
    fm.header.gtfs_realtime_version = "2.0"
    fm.header.timestamp = int(now.timestamp())
    e = fm.entity.add(); e.id = "1"                                   # T1: 12 Minuten Verspätung in Irrel
    e.trip_update.trip.trip_id = "T1"; e.trip_update.trip.start_date = f"{now:%Y%m%d}"
    su = e.trip_update.stop_time_update.add(); su.stop_id = "A"; su.departure.delay = 720
    su = e.trip_update.stop_time_update.add(); su.stop_id = "B"; su.departure.delay = 240
    e = fm.entity.add(); e.id = "2"                                   # T4: fällt aus
    e.trip_update.trip.trip_id = "T4"; e.trip_update.trip.schedule_relationship = pb.TripDescriptor.CANCELED
    e = fm.entity.add(); e.id = "3"                                   # unbekannte Fahrt (nicht im Index): ignorieren
    e.trip_update.trip.trip_id = "ZZ"; su = e.trip_update.stop_time_update.add(); su.stop_id = "A"; su.departure.delay = 3000
    e = fm.entity.add(); e.id = "4"                                   # 3 Minuten: unter der Schwelle
    e.trip_update.trip.trip_id = "T2"; su = e.trip_update.stop_time_update.add(); su.stop_id = "D"; su.departure.delay = 180
    e = fm.entity.add(); e.id = "5"                                   # Störung mit Haltestelle im Radius
    ie = e.alert.informed_entity.add(); ie.stop_id = "B"
    tr = e.alert.header_text.translation.add(); tr.text = "Signalstörung"; tr.language = "de"
    for i, txt in enumerate(("WLAN verfügbar", "Bei Fahrradmitnahme Sperrzeiten beachten")):   # Ausstattung, keine Störung
        e = fm.entity.add(); e.id = f"8{i}"; ie = e.alert.informed_entity.add(); ie.stop_id = "B"
        tr = e.alert.header_text.translation.add(); tr.text = txt; tr.language = "de"
    e = fm.entity.add(); e.id = "7"                                   # Herkunftshinweis wie im echten Feed: keine Störung
    ie = e.alert.informed_entity.add(); ie.trip.trip_id = "T1"; e.alert.effect = pb.Alert.UNKNOWN_EFFECT
    tr = e.alert.description_text.translation.add(); tr.text = "Echtzeitdaten aufbereitet von GTFS.de, bereitgestellt von DELFI"; tr.language = "de"
    e = fm.entity.add(); e.id = "6"                                   # Störung außerhalb des Radius: ignorieren
    ie = e.alert.informed_entity.add(); ie.stop_id = "C"
    if mutate:
        mutate(fm)
    return fm.SerializeToString()


@pytest.fixture
def seeded(storage):
    idx = gtfs.build_index(make_zip(), keep_trips=True)
    storage.cache_put("gtfs_index", "gtfs_static", {"feeds": {"de_rv": idx}})
    return storage


async def test_rt_delays_cancellations_alerts_SYNTHETISCH(registry, seeded, settings):
    now = datetime.now(timezone.utc)
    ok, router, _ = await run("gtfs_rt_de", registry, seeded, settings, lambda r: httpx.Response(200, content=rt_feed(now)))
    assert ok and len(router.calls) == 1
    rows = {r["id"]: r for r in seeded._query("SELECT * FROM events WHERE source_id='gtfs_rt_de'")}
    assert len(rows) == 3
    delay = next(r for r in rows.values() if '"verspaetung"' in r["attrs"])
    assert delay["severity"] == "notice" and delay["title"] == "RE 1 nach Trier Hbf: +12 min" and delay["type"] == "transit"
    assert '"stop":"Irrel Bahnhof"' in delay["attrs"] or '"stop": "Irrel Bahnhof"' in delay["attrs"]
    assert any(r["severity"] == "notice" and "fällt aus" in r["title"] for r in rows.values())
    assert any(r["severity"] == "notice" and r["title"] == "Signalstörung" for r in rows.values())
    await run("gtfs_rt_de", registry, seeded, settings, lambda r: httpx.Response(200, content=rt_feed(now)))
    assert seeded._query("SELECT COUNT(*) c FROM events WHERE source_id='gtfs_rt_de'")[0]["c"] == 3   # idempotent


async def test_rt_without_index_is_failure(registry, storage, settings):
    ok, router, _ = await run("gtfs_rt_de", registry, storage, settings, lambda r: httpx.Response(200, content=b""))
    assert not ok and router.calls == []
    assert "GTFS-Index fehlt" in storage.get_state("gtfs_rt_de")["last_error"]


async def test_rt_stale_feed_is_failure(registry, seeded, settings):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    ok, _, _ = await run("gtfs_rt_de", registry, seeded, settings, lambda r: httpx.Response(200, content=rt_feed(old)))
    assert not ok and "veraltet" in seeded.get_state("gtfs_rt_de")["last_error"]


async def test_rt_garbage_is_failure(registry, seeded, settings):
    ok, _, _ = await run("gtfs_rt_de", registry, seeded, settings, lambda r: httpx.Response(200, content=b"<html>Wartung</html>"))
    assert not ok


async def test_static_builds_index_and_survives_one_feed_down_SYNTHETISCH(registry, storage, settings):
    zipped = make_zip()
    def handler(req):
        u = str(req.url)
        if "data.public.lu/api" in u:
            return {"resources": [{"format": "zip", "url": "https://download.data.public.lu/x/alt.zip", "created_at": "2026-09-01"},
                                   {"format": "zip", "url": "https://download.data.public.lu/x/neu.zip", "created_at": "2026-09-25"}]}
        if u.endswith("neu.zip") or "download.gtfs.de" in u:
            return httpx.Response(200, content=zipped)
        return httpx.Response(404)
    ok, router, _ = await run("gtfs_static", registry, storage, settings, handler)
    assert ok
    feeds = storage.cache_get("gtfs_index")["payload"]["feeds"]
    assert set(feeds) == {"lu", "de_rv"} and "trips" not in feeds["lu"] and "T1" in feeds["de_rv"]["trips"]
    assert any(str(c.url).endswith("neu.zip") for c in router.calls)          # neuester Stand gewinnt

    def one_down(req):
        return httpx.Response(500) if "download.gtfs.de" in str(req.url) else handler(req)
    ok, _, _ = await run("gtfs_static", registry, storage, settings, one_down)
    assert ok and set(storage.cache_get("gtfs_index")["payload"]["feeds"]) == {"lu", "de_rv"}   # alter Stand von de_rv bleibt
    assert "de_rv" in (storage.get_state("gtfs_static")["last_error"] or "")


async def test_static_all_down_is_failure(registry, storage, settings):
    ok, _, _ = await run("gtfs_static", registry, storage, settings, lambda r: httpx.Response(500))
    assert not ok


def test_haltestellen_payload_rail_only_and_deduplicated_SYNTHETISCH(registry, storage):
    from app import payloads
    idx = gtfs.build_index(make_zip(), keep_trips=True)
    idx["stops"]["A2"] = ["Irrel Bahnhof", 49.85004, 6.45004, ["rail"]]          # zweites Gleis derselben Station
    storage.cache_put("gtfs_index", "gtfs_static", {"feeds": {"de_rv": {**idx, "region": "DE"}}})
    out = payloads.haltestellen_payload(storage, registry)
    names = [s["name"] for s in out["stops"]]
    assert names == ["Bitburg Stadt", "Irrel Bahnhof"]                            # Bus (Irrel Schule) fehlt, Gleise zusammengefasst
    assert all(s["mode"] == "rail" and s["region"] == "DE" for s in out["stops"])


def test_haltestellen_payload_empty_without_index(registry, storage):
    from app import payloads
    assert payloads.haltestellen_payload(storage, registry)["stops"] == []
