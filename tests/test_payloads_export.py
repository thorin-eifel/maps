"""Aufbereitung, statischer Export, Zeitfenster-Obermenge, Fälligkeit, Chaos-Test."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import export, payloads
from app.collect import is_due
from app.models import Event, iso, utcnow
from conftest import fixture
from test_collectors import autobahn_handler, run


def ev(i, valid_from=None, valid_to=None, sev="info", typ="traffic"):
    return Event(id=f"autobahn:{i}", source_id="autobahn", type=typ, title=f"E{i}", severity=sev,
                 geometry={"type": "Point", "coordinates": [6.46, 49.86]}, fetched_at=utcnow(),
                 valid_from=valid_from, valid_to=valid_to)


def test_meta_and_sources(storage, registry):
    m = payloads.meta_payload(storage)
    assert m["radius_km"] == 120 and m["center"]["name"] == "Irrel" and "Kein amtliches" in m["disclaimer"]
    s = payloads.sources_payload(registry)["sources"]
    assert len(s) == 43 and all("params" not in x and x["namensnennung"] for x in s)


def test_events_validation(storage, registry):
    with pytest.raises(ValueError):
        payloads.events_payload(storage, registry, types=["foo"])
    with pytest.raises(ValueError):
        payloads.events_payload(storage, registry, within="1y")


def test_time_window_superset_rules(storage, registry):
    now = utcnow()
    storage.replace_snapshot("autobahn", [
        ev("jetzt", valid_from=now - timedelta(hours=1)),
        ev("morgen", valid_from=now + timedelta(hours=20)),
        ev("naechste-woche", valid_from=now + timedelta(days=5)),
        ev("in-zehn-tagen", valid_from=now + timedelta(days=10)),
        ev("abgelaufen", valid_from=now - timedelta(days=3), valid_to=now - timedelta(days=1)),
    ])
    ids = lambda w: {f["id"] for f in payloads.events_payload(storage, registry, within=w)["features"]}
    assert ids("now") == {"autobahn:jetzt"}
    assert ids("24h") == {"autobahn:jetzt", "autobahn:morgen"}
    assert ids("7d") == {"autobahn:jetzt", "autobahn:morgen", "autobahn:naechste-woche"}


def test_geojson_carries_provenance(storage, registry):
    storage.replace_snapshot("autobahn", [ev("a", sev="warning")])
    f = payloads.events_payload(storage, registry)["features"][0]
    p = f["properties"]
    assert f["geometry"]["type"] == "Point"
    for key in ("source_name", "attribution", "fetched_at", "first_seen", "distance_km", "confidence", "ai_generated", "source_status"):
        assert key in p
    assert p["ai_generated"] is False and p["attribution"].startswith("Quelle:")


def test_source_status_rules(registry):
    e = registry.get("autobahn")  # Intervall 600 s
    now = utcnow()
    base = {"last_success": None, "last_attempt": None, "last_error": None, "failing_since": None,
            "consecutive_failures": 0, "open_until": None}
    st = lambda **kw: payloads.source_status(e, {**base, **kw}, 0, now)["status"]
    ago = lambda s: iso(now - timedelta(seconds=s))
    assert st() == "pending"
    assert st(last_attempt=ago(5)) == "down"
    assert st(last_success=ago(100)) == "ok"
    assert st(last_success=ago(100), consecutive_failures=1) == "degraded"
    assert st(last_success=ago(100), consecutive_failures=3) == "down"
    assert st(last_success=ago(1900)) == "stale"


def test_is_due(registry):
    e = registry.get("autobahn")  # 300 s
    now = utcnow()
    assert is_due(e, {"last_attempt": None}, now)
    assert not is_due(e, {"last_attempt": iso(now - timedelta(seconds=100))}, now)
    assert is_due(e, {"last_attempt": iso(now - timedelta(seconds=275))}, now)  # ≥ 90 %
    assert is_due(e, {"last_attempt": iso(now - timedelta(seconds=3000))}, now)


def test_gewaesser_thinning_keeps_last_point_and_trend(storage, registry):
    from app.models import Measurement, Station
    base = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=20)
    storage.upsert_stations([Station(source_id="pegelonline", station_id="s1", name="X", water="Mosel", lat=49.8, lon=6.5)])
    storage.add_measurements([Measurement(source_id="pegelonline", station_id="s1", parameter="W",
                                          ts=base + timedelta(minutes=15 * i), value=100 + i, unit="cm") for i in range(80)])
    full = payloads.gewaesser_payload(storage, registry, series_step=1)["stations"][0]
    thin = payloads.gewaesser_payload(storage, registry, series_step=4)["stations"][0]
    assert len(full["series"]) == 80 and len(thin["series"]) == 21
    assert thin["series"][-1] == full["series"][-1]
    assert thin["trend_cm_3h"] == full["trend_cm_3h"] == 12.0  # 12 Viertelstunden = 3 Std.


def _seed_all(registry, storage, settings):
    async def go():
        def h(req):
            p = req.url.path
            if "autobahn" in p:
                return autobahn_handler()(req)
            if p.endswith("stations.json"):
                return fixture("pegel_stations.json")
            if "pegel" in req.url.host:
                return [{"timestamp": "2026-09-29T10:00:00+02:00", "value": 200.0}]
            return fixture("brightsky_current.json") if p.endswith("current_weather") else fixture("brightsky_forecast.json")
        for name in ("autobahn", "pegelonline", "brightsky"):
            assert (await run(name, registry, storage, settings, h))[0]
    return go()


async def test_export_writes_complete_atomic_files(registry, storage, settings, tmp_path):
    await _seed_all(registry, storage, settings)
    out = tmp_path / "data"
    sizes = export.write_all(export.build_all(storage, registry), out)
    assert set(sizes) == {"meta.json", "events.json", "aircraft.json", "gewaesser.json", "wetter.json", "status.json", "sources.json", "umwelt.json", "indizes.json", "kraftstoff.json", "themen.json", "radar.json", "blitz.json", "wind.json", "haltestellen.json", "landmarks.json", "infrastruktur.json", "routen.json", "anbau.json", "sakral.json", "suche.json"}
    assert not list(out.glob(".*.tmp"))  # keine halben Dateien
    ev_ = json.loads((out / "events.json").read_text())
    assert ev_["type"] == "FeatureCollection" and ev_["features"] and ev_["generated_at"].endswith("Z")
    assert not any(f["properties"]["type"] == "aircraft" for f in ev_["features"])  # Flüge nur in aircraft.json
    air_ = json.loads((out / "aircraft.json").read_text())
    assert all(f["properties"]["type"] == "aircraft" for f in air_["features"])
    g = json.loads((out / "gewaesser.json").read_text())
    assert len(g["stations"]) == 16 and sizes["gewaesser.json"] < 150_000
    w = json.loads((out / "wetter.json").read_text())
    assert w["current"]["temperature"]["value"] == 27.0 and len(w["forecast"]["payload"]["hours"]) == 49


async def test_export_contains_no_personal_or_secret_fields(registry, storage, settings, tmp_path):
    await _seed_all(registry, storage, settings)
    export.write_all(export.build_all(storage, registry), tmp_path)
    blob = " ".join(p.read_text() for p in tmp_path.glob("*.json"))
    for needle in ("OSINT_CONTACT", "example.invalid", "api_key", "password", "@"):
        assert needle not in blob, needle


async def test_chaos_source_down_rest_stays_up(registry, storage, settings):
    """Autobahn fällt aus: Pegel und Wetter bleiben, der Status sagt es ehrlich, alte Daten bleiben sichtbar."""
    await _seed_all(registry, storage, settings)
    n_before = len(payloads.events_payload(storage, registry)["features"])
    assert n_before > 0
    for _ in range(3):
        assert not (await run("autobahn", registry, storage, settings, lambda r: httpx.Response(502)))[0]
    st = {s["id"]: s for s in payloads.status_payload(storage, registry)["sources"]}
    assert st["autobahn"]["status"] == "down" and st["autobahn"]["failing_since"]
    assert st["pegelonline"]["status"] == "ok" and st["brightsky"]["status"] == "ok"
    assert payloads.status_payload(storage, registry)["overall"] == "down"
    feats = payloads.events_payload(storage, registry)["features"]
    assert len(feats) == n_before and {f["properties"]["source_status"] for f in feats} == {"down"}
    assert len(payloads.gewaesser_payload(storage, registry)["stations"]) == 16
