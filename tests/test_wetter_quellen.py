"""MeteoLux, MET Norway und Sensor.Community gegen aufgezeichnete Antworten (Stand 30.09.2026).

Echte Fixtures: meteolux_observations.json, meteolux_stations.json, metno_locationforecast.json,
sensorcommunity_area_temp_ANONYMISIERT.json (Kennungen entfernt, Koordinaten auf 0,01° gerundet, auf 60 Sensoren gekürzt).
SYNTHETISCH sind nur die im Test markierten Abwandlungen.
"""
import copy
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import payloads
from app.collectors import load_collector_class, meteolux, metno, sensor_community
from app.collectors.base import SourceError
from conftest import fixture, make_client

SC = "sensorcommunity_area_temp_ANONYMISIERT.json"


async def run(name, registry, storage, settings, handler):
    client, router = make_client(handler)
    entry = registry.get(name)
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    ok = await c.run_once()
    await client.aclose()
    return ok, router, c


def _fresh_meteolux():
    d = fixture("meteolux_observations.json")
    d["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return d


def _fresh_sc():
    d = copy.deepcopy(fixture(SC))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for s in d:
        s["timestamp"] = now
    return d


# ---------------------------------------------------------------- MeteoLux
def test_meteolux_parse_units_and_station():
    st, ms = meteolux.parse_observations(fixture("meteolux_observations.json"), fixture("meteolux_stations.json"))
    assert st.station_id == "LUX0000001" and "Findel" in st.name and 49.6 < st.lat < 49.7 and 6.2 < st.lon < 6.3
    by = {m.parameter: m for m in ms}
    assert set(by) == {"temperature", "relative_humidity", "pressure_msl", "wind_speed_10", "wind_gust_speed_10"}
    assert by["wind_speed_10"].unit == "km/h" and by["wind_speed_10"].value == pytest.approx(2.6 * 3.6, abs=0.1)   # m/s → km/h
    assert by["temperature"].ts.tzinfo is not None


def test_meteolux_drops_null_and_implausible_SYNTHETISCH():
    obs = fixture("meteolux_observations.json")
    for x in obs["data"]:
        if x["id"] == "su":
            x["value"] = None
        if x["id"] == "spsl":
            x["value"] = 5000
    _, ms = meteolux.parse_observations(obs, fixture("meteolux_stations.json"))
    assert {m.parameter for m in ms} == {"temperature", "wind_speed_10", "wind_gust_speed_10"}


def test_meteolux_schema_change_fails():
    with pytest.raises(SourceError):
        meteolux.parse_observations({"data": []}, fixture("meteolux_stations.json"))
    with pytest.raises(SourceError):
        meteolux.parse_observations(fixture("meteolux_observations.json"), {"data": []})


async def test_meteolux_collector_end_to_end(registry, storage, settings):
    def handler(req: httpx.Request):
        return _fresh_meteolux() if req.url.path.endswith("/observations") else fixture("meteolux_stations.json")
    ok, router, _ = await run("meteolux", registry, storage, settings, handler)
    assert ok and len(router.calls) == 2
    st = storage.stations_with_latest("meteolux", "temperature", hours=3)
    assert len(st) == 1 and st[0]["latest"]["value"] == 16.8 and st[0]["distance_km"] < 40


# ---------------------------------------------------------------- MET Norway
NOW = datetime(2026, 9, 30, 5, 30, tzinfo=timezone.utc)


def test_metno_parse_window_and_units():
    fc = metno.parse_forecast(fixture("metno_locationforecast.json"), 48, NOW)
    hrs = fc["hours"]
    assert 45 <= len(hrs) <= 49 and hrs[0]["timestamp"] == "2026-09-30T05:00:00Z"
    assert all(h["timestamp"] <= "2026-10-02T05:00:00Z" for h in hrs)
    assert hrs[0]["wind_speed"] == pytest.approx(3.1 * 3.6, abs=0.1) and hrs[0]["symbol"]
    assert fc["updated_at"].startswith("2026-09-30")


def test_metno_schema_change_and_empty_window_fail():
    with pytest.raises(SourceError):
        metno.parse_forecast({"properties": {}}, 48, NOW)
    with pytest.raises(SourceError):
        metno.parse_forecast(fixture("metno_locationforecast.json"), 48, NOW + timedelta(days=30))


async def test_metno_collector_sends_limited_coordinates_and_identifies(registry, storage, settings, monkeypatch):
    monkeypatch.setattr(metno, "_now", lambda: NOW)   # feste Uhr: Fixture stammt vom 30.09.2026
    ok, router, _ = await run("metno", registry, storage, settings, lambda r: fixture("metno_locationforecast.json"))
    assert ok
    q = router.calls[0].url.params
    assert len(q["lat"].split(".")[1]) <= 4 and len(q["lon"].split(".")[1]) <= 4   # Bedingung der Quelle (sonst HTTP 403)
    assert router.calls[0].headers["user-agent"].startswith("Landblick")
    assert storage.cache_get("forecast_metno")["payload"]["hours"]


# ---------------------------------------------------------------- Sensor.Community
def test_sensor_community_only_grid_medians_no_ids():
    stations, ms = sensor_community.aggregate(fixture(SC))
    assert stations and all(s.meta["sensoren"] >= sensor_community.MIN_SENSORS for s in stations)
    blob = (str([s.model_dump() for s in stations]) + str([m.model_dump() for m in ms])).replace("sensor_community", "").replace("sensoren", "")
    assert "sensor" not in blob and "88105" not in blob   # keine Sensor- oder Standortkennung
    assert all(set(s.meta) == {"sensoren", "raster_grad"} for s in stations)
    assert all(s.station_id.startswith("raster_") for s in stations)
    assert all(-35 <= m.value <= 100 for m in ms)


def test_sensor_community_drops_indoor_small_cells_and_saturated_humidity_SYNTHETISCH():
    def sensor(lat, lon, t, h=None, indoor=0):
        vals = [{"value_type": "temperature", "value": str(t)}] + ([{"value_type": "humidity", "value": str(h)}] if h is not None else [])
        return {"timestamp": "2026-09-30 05:00:00", "location": {"latitude": str(lat), "longitude": str(lon), "indoor": indoor},
                "sensordatavalues": vals}
    data = [sensor(49.83, 6.44, 10, 50), sensor(49.84, 6.45, 12, 99.9), sensor(49.85, 6.46, 14, 60),   # Zelle A: 3 Sensoren
            sensor(49.86, 6.47, 40, 10, indoor=1),                                                 # Innensensor: raus
            sensor(49.55, 6.05, 11, 55), sensor(49.56, 6.06, 12, 55)]                                # Zelle B: nur 2 → raus
    st, ms = sensor_community.aggregate(data)
    assert len(st) == 1 and st[0].meta["sensoren"] == 3
    by = {m.parameter: m.value for m in ms}
    assert by["temperature"] == 12.0                       # Median, Innensensor zählt nicht
    assert "relative_humidity" not in by                   # nur 2 gültige Feuchtewerte (99,9 % ist Sättigung) < 3


def test_sensor_community_outside_radius_dropped_SYNTHETISCH():
    far = [{"timestamp": "2026-09-30 05:00:00", "location": {"latitude": "50.92", "longitude": "8.12", "indoor": 0},
            "sensordatavalues": [{"value_type": "temperature", "value": "10"}]}] * 5
    assert sensor_community.aggregate(far) == ([], [])


def test_sensor_community_garbage_fails():
    with pytest.raises(SourceError):
        sensor_community.aggregate({"x": 1})


async def test_sensor_community_collector_and_wetter_payload(registry, storage, settings):
    ok, router, _ = await run("sensor_community", registry, storage, settings, lambda r: _fresh_sc())
    assert ok and "area=" in str(router.calls[0].url)
    await run("meteolux", registry, storage, settings,
              lambda r: _fresh_meteolux() if r.url.path.endswith("/observations") else fixture("meteolux_stations.json"))
    await run("metno", registry, storage, settings, lambda r: fixture("metno_locationforecast.json"))
    w = payloads.wetter_payload(storage, registry)
    ids = [o["source_id"] for o in w["others"]]
    assert ids[0] == "meteolux" and "sensor_community" in ids and all(o["attribution"] for o in w["others"])
    assert all("sensor_id" not in o["meta"] for o in w["others"])
    assert w["forecast_alt"]["source"]["id"] == "metno" and isinstance(w["forecast_alt"]["hours"], list)
