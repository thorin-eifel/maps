"""Ostbelgien, Wallonie-Rand und Grand Est: Hub'eau, BRF, MeteoAlarm gegen aufgezeichnete Antworten (Stand 30.09.2026).

Echte Fixtures: hubeau_stations.json, hubeau_obs.json (3 Stunden, gekürzt), brf_feed.xml, meteoalarm_france.json (Einträge zu FR411 bis
FR413 plus zwei fremde), meteoalarm_belgium.json (erste drei Warnungen). SYNTHETISCH sind die im Test markierten Abwandlungen,
vor allem Warnungen für BE34 und Luxemburg (am Testtag lag dort nichts vor).
"""
import copy
import json
from datetime import datetime, timezone

import httpx
import pytest

from app import payloads
from app.collectors import hubeau_pegel, load_collector_class, meteoalarm, rss_brf
from app.collectors.base import SourceError
from app.models import utcnow
from conftest import FIX, fixture, make_client

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)
AREAS = meteoalarm.load_areas()


async def run(name, registry, storage, settings, handler):
    client, router = make_client(handler)
    entry = registry.get(name)
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    ok = await c.run_once()
    await client.aclose()
    return ok, router, c


# ---------------------------------------------------------------- Hub'eau
def test_hubeau_stations_radius_and_mine_overflow_dropped():
    st = hubeau_pegel.parse_stations(fixture("hubeau_stations.json"))
    assert st, "keine Station im Radius"
    assert all(s.meta["land"] == "FR" for s in st.values())
    assert not any("minier" in s.name.lower() for s in st.values())
    from app import config, geo
    assert all(geo.haversine_km(config.CENTER_LAT, config.CENTER_LON, s.lat, s.lon) <= config.RADIUS_KM for s in st.values())


def test_hubeau_station_name_is_place_not_river_sentence():
    st = hubeau_pegel.parse_stations(fixture("hubeau_stations.json"))
    assert not any(s.name.startswith(("La ", "Le ", "Les ", "L'")) for s in st.values())   # "Hagondange et à Hauconcourt" darf bleiben
    assert any(s.water and s.name and s.name.lower() not in s.water.lower() for s in st.values())
    data = {"data": [{"code_station": "X1", "libelle_site": "La Bisten à Creutzwald", "libelle_cours_eau": "La Bisten",
                      "latitude_station": 49.2258, "longitude_station": 6.6887, "en_service": True}]}     # SYNTHETISCH
    assert hubeau_pegel.parse_stations(data)["X1"].name == "Creutzwald"


def test_hubeau_observations_mm_to_cm_and_dedupe():
    stations = hubeau_pegel.parse_stations(fixture("hubeau_stations.json"))
    page = fixture("hubeau_obs.json")
    used, meas, stats = hubeau_pegel.parse_observations([page, page], stations)   # zweite Seite doppelt: keine Dopplung
    assert used and meas
    assert len({(m.station_id, m.ts) for m in meas}) == len(meas)
    assert all(m.unit == "cm" and m.ts.tzinfo is not None for m in meas)
    first = next(r for r in page["data"] if str(r["code_station"]) in stations)
    m = next(x for x in meas if x.station_id == str(first["code_station"]) and x.ts.strftime("%Y-%m-%dT%H:%M:%SZ") == first["date_obs"])
    assert m.value == round(first["resultat_obs"] / 10, 1)


def test_hubeau_implausible_and_schema_change_SYNTHETISCH():
    stations = hubeau_pegel.parse_stations(fixture("hubeau_stations.json"))
    code = next(iter(stations))
    bad = {"data": [{"code_station": code, "date_obs": "2026-09-30T08:00:00Z", "resultat_obs": 9_999_999}]}
    with pytest.raises(SourceError):
        hubeau_pegel.parse_observations([bad], stations)
    with pytest.raises(SourceError):
        hubeau_pegel.parse_observations([{"x": 1}], stations)
    with pytest.raises(SourceError):
        hubeau_pegel.parse_stations({"x": 1})


async def test_hubeau_collector_and_payload(registry, storage, settings):
    def handler(r):
        if "referentiel/stations" in str(r.url):
            return fixture("hubeau_stations.json")
        return fixture("hubeau_obs.json")
    ok, _, _ = await run("hubeau_pegel", registry, storage, settings, handler)
    assert ok
    assert storage._query("SELECT 1 FROM stations WHERE source_id='hubeau_pegel'")   # noqa: SLF001
    g = payloads.gewaesser_payload(storage, registry)
    assert "hubeau_pegel" in [s["id"] for s in g["sources"]]


async def test_hubeau_next_page_other_host_aborts_SYNTHETISCH(registry, storage, settings):
    page = fixture("hubeau_obs.json")
    page["next"] = "https://evil.example/steal"

    def handler(r):
        if "referentiel/stations" in str(r.url):
            return fixture("hubeau_stations.json")
        return httpx.Response(200, json=page)
    ok, router, _ = await run("hubeau_pegel", registry, storage, settings, handler)
    assert not ok
    assert not any("evil.example" in str(u) for u in getattr(router, "urls", []))


# ---------------------------------------------------------------- BRF
def test_brf_keeps_only_regional_with_place_in_radius():
    ev, st = rss_brf.parse_feed((FIX / "brf_feed.xml").read_bytes(), NOW)
    assert st["total"] == 10 and st["other_topic"] >= 4
    assert all(e.type == "news" and e.region_tag == "BE" and e.raw_ref.startswith("https://brf.be/") for e in ev)
    assert all(e.confidence <= 0.7 and e.attrs["ort_genau"] is False for e in ev)


def test_brf_person_targeted_and_place_from_tag_SYNTHETISCH():
    xml = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
           b'<item><title>Fahndung nach vermisster Frau</title><link>https://brf.be/regional/1/</link>'
           b'<pubDate>Wed, 30 Sep 2026 10:16:00 +0000</pubDate><category>Regional</category><category>Amel</category></item>'
           b'<item><title>Sperrung der Ortsdurchfahrt ab Montag</title><link>https://brf.be/regional/2/</link>'
           b'<pubDate>Wed, 30 Sep 2026 10:17:00 +0000</pubDate><category>Regional</category><category>Amel</category></item>'
           b'</channel></rss>')
    ev, st = rss_brf.parse_feed(xml, NOW)
    assert st["person"] == 1 and len(ev) == 1 and ev[0].attrs["ort"] == "Amel"


def test_brf_rejects_doctype():
    with pytest.raises(Exception):
        rss_brf.parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss><channel/></rss>', NOW)


# ---------------------------------------------------------------- MeteoAlarm
def test_meteoalarm_areas_file_covers_expected_regions():
    assert {"BE33", "BE34", "FR411", "FR412", "FR413", "LU00"} <= set(AREAS)


def test_meteoalarm_france_real_fixture_yellow_only_in_radius_area():
    data = fixture("meteoalarm_france.json")
    ev, st = meteoalarm.parse_feed(data, "FR", datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc), AREAS)
    assert ev and all(e.severity == "notice" and e.region_tag == "FR" and e.type == "weather" for e in ev)
    assert all("Meuse" in e.title or "Meurthe" in e.title or "Moselle" in e.title for e in ev)
    assert all(e.raw_ref is None or e.raw_ref.startswith("https://") for e in ev)
    assert len({e.id for e in ev}) == len(ev)           # keine Sprachdopplung
    assert st["outside"] >= 1


def test_meteoalarm_expired_dropped():
    data = fixture("meteoalarm_france.json")
    ev, st = meteoalarm.parse_feed(data, "FR", datetime(2026, 12, 1, tzinfo=timezone.utc), AREAS)
    assert ev == [] and st["expired"] >= 1


def _synthetic_be(level: int, code: str = "BE34", msg: str = "Alert", status: str = "Actual", ident: str = "X1", refs: str | None = None):
    def info(lang, text):
        return {"area": [{"areaDesc": "x", "geocode": [{"value": code, "valueName": "NUTS2"}]}], "category": ["Met"], "event": text,
                "expires": "2026-09-30T20:00:00+02:00", "headline": text, "language": lang, "onset": "2026-09-30T08:00:00+02:00",
                "parameter": [{"value": f"{level}; x", "valueName": "awareness_level"}, {"value": "1; Wind", "valueName": "awareness_type"}],
                "senderName": "KMI/IRM", "web": "https://www.meteo.be/"}
    alert = {"identifier": ident, "msgType": msg, "status": status, "sender": "kmi-irm",
             "info": [info("nl-BE", "Oranje waarschuwing voor wind"), info("fr-BE", "Avertissement orange vent"), info("de-BE", "Orange Warnung Wind")]}
    if refs:
        alert["references"] = refs
    return {"alert": alert}


def test_meteoalarm_levels_language_and_area_SYNTHETISCH():
    ev, _ = meteoalarm.parse_feed({"warnings": [_synthetic_be(3)]}, "BE", NOW, AREAS)
    assert len(ev) == 1 and ev[0].severity == "warning" and ev[0].title.startswith("Orange Warnung Wind")   # Deutsch vor Französisch vor Niederländisch
    ev, _ = meteoalarm.parse_feed({"warnings": [_synthetic_be(4)]}, "BE", NOW, AREAS)
    assert ev[0].severity == "critical"
    ev, st = meteoalarm.parse_feed({"warnings": [_synthetic_be(1)]}, "BE", NOW, AREAS)
    assert ev == [] and st["green"] == 1
    ev, st = meteoalarm.parse_feed({"warnings": [_synthetic_be(3, code="BE10")]}, "BE", NOW, AREAS)
    assert ev == [] and st["outside"] >= 1


def test_meteoalarm_cancel_update_and_test_status_SYNTHETISCH():
    w = [_synthetic_be(3, ident="A"), _synthetic_be(4, ident="B", msg="Update", refs="kmi-irm,A,2026-09-30T06:00:00+02:00")]
    ev, st = meteoalarm.parse_feed({"warnings": w}, "BE", NOW, AREAS)
    assert len(ev) == 1 and ev[0].severity == "critical" and st["superseded"] == 1        # A ist durch B ersetzt
    ev, st = meteoalarm.parse_feed({"warnings": [_synthetic_be(3, msg="Cancel")]}, "BE", NOW, AREAS)
    assert ev == [] and st["not_actual"] == 1
    ev, st = meteoalarm.parse_feed({"warnings": [_synthetic_be(3, status="Test")]}, "BE", NOW, AREAS)
    assert ev == []


def test_meteoalarm_luxembourg_code_alias_and_empty_SYNTHETISCH():
    ev, _ = meteoalarm.parse_feed({"warnings": [_synthetic_be(2, code="LU000")]}, "LU", NOW, AREAS)
    assert len(ev) == 1 and ev[0].region_tag == "LU"
    ev, _ = meteoalarm.parse_feed({"warnings": []}, "LU", NOW, AREAS)
    assert ev == []
    with pytest.raises(SourceError):
        meteoalarm.parse_feed({"x": 1}, "LU", NOW, AREAS)


def test_meteoalarm_no_description_text_and_no_html_SYNTHETISCH():
    w = _synthetic_be(3)
    w["alert"]["info"][2]["event"] = "<script>alert(1)</script>Orange Warnung"
    w["alert"]["info"][2]["description"] = "Lange Beschreibung, die wir nicht übernehmen"
    w["alert"]["info"][2]["web"] = "javascript:alert(1)"
    ev, _ = meteoalarm.parse_feed({"warnings": [w]}, "BE", NOW, AREAS)
    blob = json.dumps(ev[0].model_dump(mode="json"), ensure_ascii=False)
    assert "<script" not in blob and "Lange Beschreibung" not in blob and ev[0].raw_ref is None


async def test_meteoalarm_collector_one_country_down_is_partial(registry, storage, settings):
    def handler(r):
        u = str(r.url)
        if "feeds-belgium" in u:
            return fixture("meteoalarm_belgium.json")
        if "feeds-france" in u:
            return fixture("meteoalarm_france.json")
        return httpx.Response(503)
    ok, _, c = await run("meteoalarm", registry, storage, settings, handler)
    assert ok
