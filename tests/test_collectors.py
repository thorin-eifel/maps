"""Collector gegen aufgezeichnete Antworten (echte Fixtures; DWD-Warnung und adsb.lol-Fixture synthetisch/anonymisiert)."""
import copy
from datetime import datetime, timezone

import httpx
import pytest

from app import config
from app.collectors import load_collector_class
from conftest import fixture, make_client


async def run(name, registry, storage, settings, handler):
    client, router = make_client(handler)
    entry = registry.get(name)
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    if hasattr(c, "pause_s"):
        c.pause_s = 0
    ok = await c.run_once()
    await client.aclose()
    return ok, router, c


# ------------------------------------------------------------------ Autobahn
def autobahn_handler(fail=None, stau=False):
    def h(req: httpx.Request):
        parts = req.url.path.strip("/").split("/")  # o/autobahn/A64/services/roadworks
        road, service = parts[-3], parts[-1]
        if fail and (road, service) == fail:
            return httpx.Response(503)
        if stau and (road, service) == ("A64", "warning"):
            return fixture("autobahn_A64_warning_STAU_SYNTHETISCH.json")
        return fixture(f"autobahn_{road}_{service}.json")
    return h


async def test_autobahn_congestion_kinds_severity_and_geometry(registry, storage, settings):
    ok, _, _ = await run("autobahn", registry, storage, settings, autobahn_handler(stau=True))
    assert ok
    import json
    rows = {r["id"]: r for r in storage._query("SELECT * FROM events WHERE type='congestion'")}
    assert set(rows) == {"autobahn:SYNTH--stau-lang", "autobahn:SYNTH--stau-kurz", "autobahn:SYNTH--zaeh", "autobahn:SYNTH--stillstand"}
    lang, kurz = rows["autobahn:SYNTH--stau-lang"], rows["autobahn:SYNTH--stau-kurz"]
    assert lang["severity"] == "warning" and kurz["severity"] == "notice"  # ab 30 Minuten Warnung
    assert rows["autobahn:SYNTH--zaeh"]["severity"] == "info" and rows["autobahn:SYNTH--stillstand"]["severity"] == "warning"
    assert json.loads(lang["attrs"]) == {"kind": "stau", "delay_min": 35, "speed_kmh": 15}
    assert json.loads(rows["autobahn:SYNTH--zaeh"]["attrs"]) == {"kind": "zaehfliessend", "speed_kmh": 40}
    assert json.loads(lang["geometry"])["type"] == "LineString"
    assert lang["title"].startswith("Stau: A64") and "35 Minuten" in lang["summary"] and "15 km/h" in lang["summary"]
    # Gefahrenmeldung ohne Verkehrslage bleibt gewöhnliche Meldung; Stau weit außerhalb wird am Rand verworfen
    other = storage._query("SELECT type, attrs FROM events WHERE id='autobahn:SYNTH--gefahr'")[0]
    assert other["type"] == "traffic" and json.loads(other["attrs"]) == {"kind": "warnung"}
    assert not storage._query("SELECT 1 FROM events WHERE id='autobahn:SYNTH--weit-weg'")


async def test_autobahn_congestion_disappears_when_gone(registry, storage, settings):
    await run("autobahn", registry, storage, settings, autobahn_handler(stau=True))
    await run("autobahn", registry, storage, settings, autobahn_handler())
    assert not storage._query("SELECT 1 FROM events WHERE type='congestion' AND active=1")


async def test_autobahn_filters_at_the_edge(registry, storage, settings):
    ok, router, _ = await run("autobahn", registry, storage, settings, autobahn_handler())
    assert ok and len(router.calls) == 12
    evs = storage.active_events()
    assert evs and all(e["distance_km"] <= 120 for e in evs)  # nichts außerhalb des Radius gespeichert
    assert all(e["type"] == "traffic" for e in evs)
    titles = " ".join(e["title"] for e in evs)
    assert "A64" in titles and "Köln-Lövenich" not in titles  # A1 bei Köln liegt weit draußen
    assert all(e["raw_ref"].startswith("https://") for e in evs)


async def test_autobahn_idempotent(registry, storage, settings):
    await run("autobahn", registry, storage, settings, autobahn_handler())
    n = len(storage.active_events())
    await run("autobahn", registry, storage, settings, autobahn_handler())
    assert len(storage.active_events()) == n
    assert storage._query("SELECT COUNT(*) n FROM events")[0]["n"] == n


async def test_autobahn_partial_failure_keeps_old_events(registry, storage, settings):
    await run("autobahn", registry, storage, settings, autobahn_handler())
    n = len(storage.active_events())
    ok, _, _ = await run("autobahn", registry, storage, settings, autobahn_handler(fail=("A1", "roadworks")))
    assert ok  # Lauf gilt als Erfolg mit Hinweis …
    assert len(storage.active_events()) == n  # … aber nichts wird abgeräumt
    st = storage.get_state("autobahn")
    assert "teilweise" in (st["last_error"] or "")


async def test_autobahn_planned_roadworks_get_start_from_text(registry, storage, settings):
    await run("autobahn", registry, storage, settings, autobahn_handler())
    row = storage._query("SELECT * FROM events WHERE title LIKE 'A64 | Sauertalbrücke%'")[0]
    assert row["summary"].startswith("Baustelle (geplant)")
    assert row["valid_from"] == "2026-10-05T06:00:00Z"  # 08:00 MESZ


# ------------------------------------------------------------------ PEGELONLINE
def pegel_handler(hist_calls):
    def h(req: httpx.Request):
        if req.url.path.endswith("stations.json"):
            return fixture("pegel_stations.json")
        hist_calls.append(req.url.path)
        return [{"timestamp": "2026-09-29T10:00:00+02:00", "value": 200.0},
                {"timestamp": "2026-09-29T10:15:00+02:00", "value": 201.5}]
    return h


async def test_pegelonline_stations_and_backfill_only_once(registry, storage, settings):
    hist: list[str] = []
    ok, _, _ = await run("pegelonline", registry, storage, settings, pegel_handler(hist))
    assert ok
    st = storage.stations_with_latest("pegelonline", "W", hours=24 * 30)
    assert len(st) == 16 and {s["water"] for s in st} == {"Mosel", "Saar"}
    assert len(hist) == 16
    assert any(s["name"] == "Trier UP" for s in st)
    hist.clear()
    await run("pegelonline", registry, storage, settings, pegel_handler(hist))
    assert hist == []  # zweiter Lauf: kein Backfill mehr
    t = next(s for s in st if s["name"] == "Trier UP")
    assert t["latest"]["unit"] == "cm" and t["latest"]["state"] == "low/normal"


# ------------------------------------------------------------------ Bright Sky
async def test_brightsky_current_and_forecast(registry, storage, settings):
    def h(req):
        return fixture("brightsky_current.json") if req.url.path.endswith("current_weather") else fixture("brightsky_forecast.json")
    ok, _, _ = await run("brightsky", registry, storage, settings, h)
    assert ok
    rows = storage._query("SELECT parameter, value FROM measurements WHERE station_id='83411'")
    assert dict((r["parameter"], r["value"]) for r in rows)["temperature"] == 27.0
    fc = storage.cache_get("forecast")
    assert len(fc["payload"]["hours"]) == 49 and fc["source_id"] == "brightsky"
    assert storage.active_events() == []  # Wetterwerte sind keine Ereignisse


# ------------------------------------------------------------------ DWD
async def test_dwd_bbox_axis_order_is_lon_lat(registry, storage, settings):
    seen = {}
    def h(req):
        seen.update(dict(req.url.params))
        return fixture("dwd_wfs_warnungen_gemeinden.json")  # echte, leere Antwort
    ok, _, _ = await run("dwd_warnungen", registry, storage, settings, h)
    assert ok and storage.active_events() == []
    assert seen["bbox"] == "4.78,48.76,8.13,50.93,EPSG:4326"  # lon,lat — nicht lat,lon!
    assert seen["typeName"] == "dwd:Warnungen_Landkreise"


async def test_dwd_groups_filters_and_maps_severity(registry, storage, settings):
    ok, _, _ = await run("dwd_warnungen", registry, storage, settings, lambda r: fixture("dwd_wfs_SYNTHETISCH_landkreise.json"))
    assert ok
    evs = storage.active_events()
    assert len(evs) == 1  # TEST1 (zwei Polygone → ein Ereignis); TEST2 zu weit; TEST3 aufgehoben
    e = evs[0]
    assert e["severity"] == "warning" and e["type"] == "weather" and e["distance_km"] == 0.0
    assert "<" not in e["summary"] and e["valid_from"] == "2026-09-30T10:00:00Z"


# ------------------------------------------------------------------ NINA
def nina_handler(lists=None, detail=None, geo=None):
    """lists: Kanal → mapData-Liste. Nicht genannte Kanäle liefern []."""
    lists = lists or {}
    def h(req):
        p = req.url.path
        if p.endswith("/mapData.json"):
            return lists.get(p.rsplit("/", 2)[1], [])
        if p.endswith(".geojson"):
            return geo if geo is not None else fixture("nina_warning_geo.json")
        return detail if detail is not None else fixture("nina_warning_detail.json")
    return h


WID = "mow.DE-SL-SLS-W038-20260904-000"
ENTRY = [{"id": WID, "version": 19}]


@pytest.fixture(autouse=True)
def _nina_cache_clear():
    from app.collectors import nina
    nina._CACHE.clear()


async def test_nina_real_edge_case_inside_radius(registry, storage, settings):
    h = nina_handler({"mowas": ENTRY, "katwarn": ENTRY})  # doppelt gemeldet → einmal
    ok, router, _ = await run("nina", registry, storage, settings, h)
    assert ok
    evs = storage.active_events()
    assert len(evs) == 1
    e = evs[0]
    assert e["id"] == f"nina:{WID}" and e["type"] == "warning" and e["severity"] == "notice"
    assert 48 < e["distance_km"] < 49 and e["confidence"] == 1.0
    assert "<" not in e["summary"]
    assert sum(1 for c in router.calls if c.url.path.endswith(f"{WID}.json")) == 1
    assert not any("/dwd/" in c.url.path for c in router.calls)   # DWD kommt über dwd_warnungen


async def test_nina_detail_fetched_once_per_version(registry, storage, settings):
    h = nina_handler({"mowas": ENTRY})
    _, r1, _ = await run("nina", registry, storage, settings, h)
    _, r2, _ = await run("nina", registry, storage, settings, h)
    assert sum(c.url.path.endswith(f"{WID}.json") for c in r2.calls) == 0   # aus dem Speicher
    assert len(storage.active_events()) == 1
    _, r3, _ = await run("nina", registry, storage, settings, nina_handler({"mowas": [{"id": WID, "version": 20}]}))
    assert sum(c.url.path.endswith(f"{WID}.json") for c in r3.calls) == 1   # neue Version → neu holen


async def test_nina_outside_region_is_dropped(registry, storage, settings):
    geo = copy.deepcopy(fixture("nina_warning_geo.json"))
    for f in geo["features"]:
        f["geometry"]["coordinates"] = [[[x, y - 4.0] for x, y in ring] for ring in f["geometry"]["coordinates"]]
    await run("nina", registry, storage, settings, nina_handler({"mowas": ENTRY}, geo=geo))
    assert storage.active_events() == []


async def test_nina_without_geometry_is_dropped_and_counted(registry, storage, settings):
    ok, _, c = await run("nina", registry, storage, settings, nina_handler({"mowas": ENTRY}, geo={"type": "FeatureCollection", "features": []}))
    assert ok and storage.active_events() == []
    from app.collectors import nina
    assert nina._CACHE[(WID, "19")] == (None, True)   # gemerkt: nur die Fläche fehlte


async def test_nina_cancel_and_test_messages_dropped(registry, storage, settings):
    for patch in ({"msgType": "Cancel"}, {"status": "Test"}):
        d = {**fixture("nina_warning_detail.json"), **patch}
        await run("nina", registry, storage, settings, nina_handler({"mowas": ENTRY}, detail=d))
        assert storage.active_events() == []


async def test_nina_partial_failure_is_not_a_wipe(registry, storage, settings):
    await run("nina", registry, storage, settings, nina_handler({"mowas": ENTRY}))
    assert len(storage.active_events()) == 1
    def h(req):
        if "/katwarn/" in req.url.path:
            return httpx.Response(500)
        return nina_handler({})(req)  # alle anderen Kanäle: leer
    ok, _, _ = await run("nina", registry, storage, settings, h)
    assert ok and len(storage.active_events()) == 1  # unvollständiger Lauf räumt nicht ab
    ok, _, _ = await run("nina", registry, storage, settings, nina_handler({}))
    assert ok and storage.active_events() == []  # vollständiger, leerer Lauf schon


async def test_nina_all_channels_down_is_an_error(registry, storage, settings):
    ok, _, _ = await run("nina", registry, storage, settings, lambda r: httpx.Response(500))
    assert not ok


# ------------------------------------------------------------------ Fehlerfälle
async def test_retry_then_success(registry, storage, settings):
    n = {"i": 0}
    def h(req):
        n["i"] += 1
        return httpx.Response(503) if n["i"] == 1 else fixture("dwd_wfs_warnungen_gemeinden.json")
    ok, router, _ = await run("dwd_warnungen", registry, storage, settings, h)
    assert ok and len(router.calls) == 2


async def test_client_error_is_not_retried(registry, storage, settings):
    ok, router, _ = await run("dwd_warnungen", registry, storage, settings, lambda r: httpx.Response(404))
    assert not ok and len(router.calls) == 1


async def test_schema_change_is_an_error_not_a_guess(registry, storage, settings):
    ok, _, _ = await run("dwd_warnungen", registry, storage, settings, lambda r: {"unerwartet": True})
    assert not ok
    assert "features" in storage.get_state("dwd_warnungen")["last_error"]


async def test_circuit_breaker_opens_and_skips_requests(registry, storage, settings):
    client, router = make_client(lambda r: httpx.Response(500))
    entry = registry.get("dwd_warnungen")
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    for _ in range(5):
        assert not await c.run_once()
    st = storage.get_state("dwd_warnungen")
    assert st["consecutive_failures"] == 5 and st["open_until"]
    calls = len(router.calls)
    assert not await c.run_once()
    assert len(router.calls) == calls  # Circuit offen: kein HTTP-Aufruf
    await client.aclose()


# ------------------------------------------------------------------ adsb.lol (Luftverkehr)
def adsb_handler(req: httpx.Request):
    return fixture("adsblol_point_ANONYMISIERT_SYNTHETISCH.json")


async def test_adsblol_filters_and_maps(registry, storage, settings):
    ok, router, _ = await run("adsblol", registry, storage, settings, adsb_handler)
    assert ok and len(router.calls) == 1
    assert router.calls[0].url.path.endswith(f"/v2/point/{config.CENTER_LAT}/{config.CENTER_LON}/70")
    evs = storage.active_events()
    assert evs and all(e["type"] == "aircraft" and e["distance_km"] <= 120 for e in evs)
    titles = [e["title"] for e in evs]
    assert any("Hubschrauber" in t for t in titles)
    assert not any(e["summary"].startswith("Position ohne") for e in evs)
    # drin: aaaa01-03, aaaa05, bbbb02-04. Fehlen: aaaa04 und aaaa06 (81 und 84 km, außerhalb),
    # bbbb01 (am Boden), bbbb05 (ohne Position)
    assert len(evs) == 9


async def test_adsblol_attrs_only_course_and_speed_and_short_validity(registry, storage, settings):
    import json
    from datetime import datetime
    await run("adsblol", registry, storage, settings, adsb_handler)
    rows = storage._query("SELECT attrs, valid_to, fetched_at FROM events")
    assert rows
    for r in rows:
        assert set(json.loads(r["attrs"] or "{}")) <= {"klass", "track", "speed_kmh"}
        span = (datetime.fromisoformat(r["valid_to"].replace("Z", "+00:00")) - datetime.fromisoformat(r["fetched_at"].replace("Z", "+00:00"))).total_seconds()
        assert 60 <= span <= 120  # Live-Intervall 15 s → 90 s


async def test_adsblol_emergency_squawk_is_notice_not_warning(registry, storage, settings):
    await run("adsblol", registry, storage, settings, adsb_handler)
    em = [e for e in storage.active_events() if "7700" in e["title"]]
    assert len(em) == 1
    assert em[0]["severity"] == "notice" and em[0]["confidence"] <= 0.5
    assert "nicht bestätigt" in em[0]["summary"]


async def test_adsblol_klass_civil_mil_heli_without_identifiers_SYNTHETISCH(registry, storage, settings):
    import json

    def h(req):  # SYNTHETISCH: dbFlags (Bit 0 = Militär) und Kategorie A7 auf vier der Fixture-Flugzeuge
        raw = copy.deepcopy(fixture("adsblol_point_ANONYMISIERT_SYNTHETISCH.json"))
        inside = [a for a in raw["ac"] if a.get("alt_baro") != "ground" and a.get("lat") is not None and a["hex"] in ("aaaa01", "aaaa02", "aaaa03", "aaaa04")][:3]
        inside[0]["dbFlags"] = 1
        inside[1]["dbFlags"] = 1; inside[1]["category"] = "A7"
        inside[2]["dbFlags"] = 8  # anderes Bit (LADD): kein Militär
        return raw
    await run("adsblol", registry, storage, settings, h)
    klass = [json.loads(r["attrs"]).get("klass") for r in storage._query("SELECT attrs FROM events")]
    assert {"mil", "milheli", "civil"} <= set(klass) and "heli" in klass  # Fixture enthält bereits einen Hubschrauber
    titles = [r["title"] for r in storage._query("SELECT title FROM events")]
    assert any(t.startswith("Militär") for t in titles)
    assert "dbflags" not in " ".join(str(dict(r)) for r in storage._query("SELECT * FROM events")).lower()


async def test_adsblol_stores_no_identifiers(registry, storage, settings):
    await run("adsblol", registry, storage, settings, adsb_handler)
    dump = " ".join(str(dict(r)) for r in storage._query("SELECT * FROM events"))
    raw = fixture("adsblol_point_ANONYMISIERT_SYNTHETISCH.json")
    for a in raw["ac"]:
        assert a["hex"] not in dump
    for word in ("hex", "flight", "squawk", "registration", "callsign"):
        assert word not in dump.lower().replace("transpondercode", "")  # Feldnamen tauchen nicht auf


async def test_adsblol_ids_stable_within_day_but_salt_rotates(registry, storage, settings):
    await run("adsblol", registry, storage, settings, adsb_handler)
    ids1 = {e["id"] for e in storage.active_events()}
    await run("adsblol", registry, storage, settings, adsb_handler)
    assert {e["id"] for e in storage.active_events()} == ids1  # idempotent, keine Spur
    assert storage._query("SELECT COUNT(*) n FROM events")[0]["n"] == len(ids1)
    # anderer Tag: anderes Salz, IDs nicht verknüpfbar
    storage.cache_put("adsblol:salt", "adsblol", {"day": "2000-01-01", "salt": "alt"})
    await run("adsblol", registry, storage, settings, adsb_handler)
    ids2 = {e["id"] for e in storage.active_events()}
    assert ids2 and not (ids1 & ids2)


async def test_adsblol_snapshot_removes_gone_aircraft_and_expires(registry, storage, settings):
    await run("adsblol", registry, storage, settings, adsb_handler)
    n = len(storage.active_events())
    empty = lambda req: {"ac": [], "msg": "No error"}  # noqa: E731
    await run("adsblol", registry, storage, settings, empty)
    assert len(storage.active_events()) == 0 and n > 0
    row = storage._query("SELECT valid_to, fetched_at FROM events LIMIT 1")[0]
    assert row["valid_to"] > row["fetched_at"]  # Gültigkeit begrenzt


async def test_adsblol_schema_change_is_an_error(registry, storage, settings):
    ok, _, _ = await run("adsblol", registry, storage, settings, lambda req: {"aircraft": []})
    assert not ok


# ------------------------------------------------------------------ Baustellen RLP (WFS Mobilitätsatlas)
def lbm_handler(fail_verlauf=False, paged=False):
    sites = fixture("lbm_wfs_baustelle_ANONYMISIERT_SYNTHETISCH.json")
    lines = fixture("lbm_wfs_verlauf.json")

    def h(req: httpx.Request):
        q = req.url.params
        layer = q["typeNames"]
        if layer == "mwvlw:verlauf" and fail_verlauf:
            return httpx.Response(503)
        src = sites if layer == "mwvlw:baustelle" else lines
        feats = src["features"]
        if paged:
            start, n = int(q["startIndex"]), int(q["count"])
            feats = feats[start:start + n]
        return {"type": "FeatureCollection", "features": feats, "numberMatched": len(src["features"]),
                "numberReturned": len(feats)}
    return h


async def test_lbm_filters_dedups_and_maps(registry, storage, settings):
    ok, router, _ = await run("lbm_baustellen", registry, storage, settings, lbm_handler())
    assert ok and len(router.calls) == 2
    q = router.calls[0].url.params
    assert q["typeNames"] == "mwvlw:baustelle" and q["outputFormat"] == "application/json"
    assert q["bbox"] == "48.76,4.78,50.93,8.13,urn:ogc:def:crs:EPSG::4326"  # lat,lon mit CRS-Suffix
    evs = storage.active_events()
    assert evs and all(e["type"] == "traffic" and e["distance_km"] <= 120 for e in evs)
    assert len(evs) == 11  # 9 aus DE, 2 aus LU (die zwei Fixtures zwischen 50 und 80 km sind jetzt drin); 2 Autobahn GmbH fehlen
    text = " ".join(e["title"] + e["summary"] for e in evs)
    assert "A60" not in text and "A64" not in text  # Dubletten zum Autobahn-Collector
    assert {e["region_tag"] for e in evs} == {"DE-RLP", "LU"}


async def test_lbm_severity_planned_and_line_geometry(registry, storage, settings):
    await run("lbm_baustellen", registry, storage, settings, lbm_handler())
    evs = {e["title"]: e for e in storage.active_events()}
    irrel = next(e for e in storage.active_events() if e["title"].startswith("L 4:"))
    assert irrel["severity"] == "warning" and "Vollsperrung" in irrel["title"]
    assert irrel["attrs"]["sperr"] == "voll" if isinstance(irrel["attrs"], dict) else "voll" in irrel["attrs"]
    k35 = next(e for e in storage.active_events() if e["title"].startswith("K 35:"))
    assert k35["severity"] == "notice"
    k31 = next(e for e in storage.active_events() if e["title"].startswith("K 31:"))
    assert k31["severity"] == "info"
    planned = [e for e in storage.active_events() if e["title"].endswith("(geplant)")]
    assert planned and planned[0]["valid_from"] > planned[0]["fetched_at"]  # beginnt erst später
    geoms = [json_geom(e) for e in storage.active_events()]
    assert any(g["type"] in ("LineString", "MultiLineString") for g in geoms)  # Verlauf ersetzt den Punkt
    assert any(g["type"] == "Point" for g in geoms)  # ohne Verlauf bleibt der Punkt
    assert evs


def json_geom(e):
    import json
    return json.loads(e["geometry"]) if isinstance(e["geometry"], str) else e["geometry"]


async def test_lbm_stores_no_contact_data(registry, storage, settings):
    await run("lbm_baustellen", registry, storage, settings, lbm_handler())
    dump = " ".join(str(dict(r)) for r in storage._query("SELECT * FROM events"))
    assert "example.invalid" not in dump and "@" not in dump  # weder Ansprechpartner noch Freitext-Adresse
    assert "06525" not in dump and "123456" not in dump  # Telefonnummer aus dem Freitext entfernt
    assert "ansprechpartner" not in dump.lower()


async def test_lbm_verlauf_failure_falls_back_to_points(registry, storage, settings):
    ok, _, _ = await run("lbm_baustellen", registry, storage, settings, lbm_handler(fail_verlauf=True))
    assert ok
    assert len(storage.active_events()) == 11
    assert all(json_geom(e)["type"] == "Point" for e in storage.active_events())
    assert "Verlauf nicht erreichbar" in (storage.get_state("lbm_baustellen")["last_error"] or "")


async def test_lbm_paging_collects_everything(registry, storage, settings, monkeypatch):
    import app.collectors.lbm_baustellen as mod
    monkeypatch.setattr(mod, "PAGE", 3)
    ok, router, _ = await run("lbm_baustellen", registry, storage, settings, lbm_handler(paged=True))
    assert ok and len(storage.active_events()) == 11
    assert any(r.url.params["startIndex"] != "0" for r in router.calls)


async def test_lbm_site_failure_is_an_error_and_keeps_old(registry, storage, settings):
    await run("lbm_baustellen", registry, storage, settings, lbm_handler())
    n = len(storage.active_events())
    ok, _, _ = await run("lbm_baustellen", registry, storage, settings, lambda req: httpx.Response(503))
    assert not ok and len(storage.active_events()) == n


async def test_lbm_schema_change_is_an_error(registry, storage, settings):
    ok, _, _ = await run("lbm_baustellen", registry, storage, settings, lambda req: {"items": []})
    assert not ok


# ------------------------------------------------------------------ Live-Schleife
async def test_live_loop_writes_only_aircraft_and_status(registry, settings, tmp_path, monkeypatch):
    import dataclasses
    import json
    from app import live
    real = httpx.AsyncClient
    monkeypatch.setattr(live.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=fixture("adsblol_point_ANONYMISIERT_SYNTHETISCH.json")))))
    monkeypatch.delenv("PUBLISH_ENABLED", raising=False)
    st = dataclasses.replace(settings, web_dir=tmp_path)
    assert await live.run(st, None, once=True) == 0
    files = {p.name for p in (tmp_path / "data").iterdir()}
    assert files == {"aircraft.json", "status.json"}
    air = json.loads((tmp_path / "data" / "aircraft.json").read_text())
    assert len(air["features"]) == 9 and all(f["properties"]["type"] == "aircraft" for f in air["features"])
    status = {s["id"]: s for s in json.loads((tmp_path / "data" / "status.json").read_text())["sources"]}
    assert status["adsblol"]["status"] == "ok"


def test_skip_live_filters_flight_source(registry):
    live_ids = [e.id for e in registry.active() if e.params.get("live")]
    assert live_ids == ["adsblol"]
