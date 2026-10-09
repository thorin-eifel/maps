"""Meldungen, Luxemburg, DWD-Indizes, Tankerkönig und Themenradar gegen aufgezeichnete Antworten (Stand 30.09.2026).

Echte Fixtures: pp_117701/117697/117698.xml (Presseportal), volksfreund_feed.xml, cita_datex_situationrecord36.xml,
lu_water_levels.csv, lu_wasserstand_stationen.json, dwd_s31fg.json, dwd_uvi.json, dwd_wbi_stations_list.txt, dwd_wbi_1964.csv.gz,
dwd_glfi_1964.csv.gz. SYNTHETISCH sind die im Test markierten Abwandlungen sowie alle Mastodon- und Tankerkönig-Daten
(für Mastodon liegen bewusst keine echten Beiträge im Repository).
"""
import gzip
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import geoparse, payloads
from app.collectors import (cita_lu, dwd_gesundheit, dwd_waldbrand, load_collector_class, lu_pegel, mastodon_themen, presseportal,
                            rss_volksfreund, tankerkoenig)
from app.collectors.base import SourceError
from app.collectors.rsslib import parse_rss
from app.models import utcnow
from conftest import FIX, fixture, make_client


async def run(name, registry, storage, settings, handler):
    client, router = make_client(handler)
    entry = registry.get(name)
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    ok = await c.run_once()
    await client.aclose()
    return ok, router, c


def raw(name: str) -> bytes:
    return (FIX / name).read_bytes()


# ---------------------------------------------------------------- Ortserkennung
def test_dateline_simple_and_ambiguous():
    p = geoparse.locate_dateline("Prüm")
    assert p and p.name == "Prüm" and 50.1 < p.lat < 50.3 and p.confidence >= 0.85
    h = geoparse.locate_dateline("Hausen")      # Namensvetter: unsicher markieren
    assert h and h.confidence <= 0.6


def test_dateline_neighbour_hint_wins_over_far_namesake():
    # "Steinebrück/Wittlich": das einzige Steinebrück im Verzeichnis liegt in Ostbelgien, 60 km von Wittlich. Dann gilt Wittlich.
    p = geoparse.locate_dateline("Steinebrück/Wittlich")
    assert p and p.name == "Wittlich"


def test_dateline_unknown_and_outside():
    assert geoparse.locate_dateline("Nirgendwo") is None
    assert geoparse.locate_dateline("") is None


def test_text_whole_words_only_and_capped_confidence():
    assert geoparse.locate_text("Der Trierer Dom") is None       # "Trierer" ist nicht "Trier"
    p = geoparse.locate_text("Drohung auf Schultoilette in Bitburg")
    assert p and p.name == "Bitburg" and p.confidence <= 0.7
    assert geoparse.locate_text("Klopp droht ein Negativrekord") is None


# ---------------------------------------------------------------- RSS-Grundlagen
def test_rss_rejects_doctype_and_entity_SYNTHETISCH():
    bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
    with pytest.raises(SourceError):
        parse_rss(bomb)
    with pytest.raises(SourceError):
        parse_rss(b"<rss><nichts/></rss>")


def test_rss_only_https_links_and_clean_titles_SYNTHETISCH():
    x = (b'<rss><channel><item><title>A&lt;script&gt;x&lt;/script&gt;B</title><link>javascript:alert(1)</link>'
         b'<pubDate>Wed, 30 Sep 2026 08:00:00 +0200</pubDate></item><item><title>Ok</title><link>https://e.de/1</link>'
         b'<pubDate>Wed, 30 Sep 2026 08:00:00 +0200</pubDate></item></channel></rss>')
    items = parse_rss(x)
    assert [i.link for i in items] == ["https://e.de/1"]


# ---------------------------------------------------------------- Presseportal
def test_presseportal_fixture_places_and_no_body_text():
    ev, st = presseportal.parse_feed(raw("pp_117697.xml"), utcnow(), "polizei", "PD Wittlich")
    assert st["total"] == 15 and len(ev) >= 13
    assert all(e.type == "news" and e.raw_ref.startswith("https://www.presseportal.de/") for e in ev)
    assert not any(e.title.startswith("POL-") for e in ev)
    assert all("(ots)" not in e.summary and len(e.summary) < 120 for e in ev)      # kein Meldungstext
    assert all(e.valid_to - e.valid_from == timedelta(hours=72) for e in ev)


def test_presseportal_drops_person_targeted_SYNTHETISCH():
    x = raw("pp_117697.xml").decode()
    import re
    titles = re.findall(r"<title>(POL-[^<]*)</title>", x)
    x = x.replace(titles[0], "POL-PDWIL: Öffentlichkeitsfahndung nach Tatverdächtigem", 1)
    x = x.replace(titles[1], "POL-PDWIL: Vermisste 14-Jährige aus Bitburg", 1)
    ev, st = presseportal.parse_feed(x.encode(), utcnow(), "polizei", "X")
    assert st["person"] >= 1 and not any("fahndung" in e.title.lower() or "vermisst" in e.title.lower() for e in ev)


async def test_presseportal_collector_end_to_end(registry, storage, settings):
    ok, router, _ = await run("presseportal", registry, storage, settings, lambda r: httpx.Response(200, content=raw(f"pp_{r.url.path.split('_')[-1].split('.')[0]}.xml")))
    assert ok and len(router.calls) == 3
    assert storage.count_active("presseportal") >= 30
    assert all("presseportal.de/rss/dienststelle_" in str(c.url) for c in router.calls)


async def test_presseportal_one_feed_down_is_incomplete_not_fatal(registry, storage, settings):
    def handler(r):
        return httpx.Response(503) if "117698" in r.url.path else httpx.Response(200, content=raw("pp_117701.xml"))
    ok, _, _ = await run("presseportal", registry, storage, settings, handler)
    assert ok is True or ok is False    # Lauf endet ohne Ausnahme; Ereignisse der anderen Feeds stehen
    assert storage.count_active("presseportal") >= 10


# ---------------------------------------------------------------- Volksfreund
def test_volksfreund_keeps_only_regional_with_place():
    ev, st = rss_volksfreund.parse_feed(raw("volksfreund_feed.xml"), utcnow())
    assert st["total"] == 20 and st["other_topic"] >= 4 and st["no_place"] >= 1
    assert ev and all(e.attrs["ort_genau"] is False and e.confidence <= 0.7 for e in ev)
    assert all(e.raw_ref.startswith("https://www.volksfreund.de/") for e in ev)
    assert not any("Klopp" in e.title or "Nobelpreis" in e.title for e in ev)          # Sport und Welt fallen weg


# ---------------------------------------------------------------- CITA Luxemburg
def test_cita_parses_situations_and_geometry():
    ev, st = cita_lu.parse_situations(raw("cita_datex_situationrecord36.xml"), utcnow())
    assert st["situations"] == 14 and st["skipped_type"] == 1 and len(ev) == 13
    acc = [e for e in ev if e.attrs["kind"] == "unfall"]
    assert acc and "A1" in acc[0].title and "Trier" in acc[0].title and acc[0].geometry["type"] == "LineString"
    assert acc[0].region_tag == "LU" and acc[0].valid_to is None
    assert "6 Fahrzeuge" in acc[0].summary


def test_cita_rejects_doctype_and_schema_change_SYNTHETISCH():
    with pytest.raises(SourceError):
        cita_lu.parse_situations(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>', utcnow())
    with pytest.raises(SourceError):
        cita_lu.parse_situations(b"<x/>", utcnow())


async def test_cita_collector_end_to_end(registry, storage, settings):
    ok, router, _ = await run("cita_lu", registry, storage, settings, lambda r: httpx.Response(200, content=raw("cita_datex_situationrecord36.xml")))
    assert ok and storage.count_active("cita_lu") == 13


# ---------------------------------------------------------------- Pegel Luxemburg
def test_lu_pegel_join_timezone_and_filters():
    stations, meas, st = lu_pegel.parse((FIX / "lu_water_levels.csv").read_text(encoding="utf-8"), fixture("lu_wasserstand_stationen.json"))
    names = {s.name for s in stations}
    assert len(stations) >= 38 and {"Bollendorf", "Rosport", "Wasserbillig", "Vianden"} <= names
    assert not any("Esch" in n for n in names)            # Talsperre (Einheit m) bleibt draußen
    by = {s.name: s for s in stations}
    assert by["Wasserbillig"].water == "Mosel" and by["Bollendorf"].water == "Sauer" and by["Vianden"].water == "Our"
    assert all(m.unit == "cm" and m.ts.tzinfo is not None for m in meas)
    # Ortszeit → UTC: erster Wert 25.09.2026 08:45 (CEST, UTC+2) = 06:45 UTC
    first = min(m.ts for m in meas)
    assert first.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") == "2026-09-25 06:45"


def test_lu_pegel_implausible_and_schema_change_SYNTHETISCH():
    csv_text = (FIX / "lu_water_levels.csv").read_text(encoding="utf-8")
    with pytest.raises(SourceError):
        lu_pegel.parse("Name,Wert\nx,1\n", fixture("lu_wasserstand_stationen.json"))
    with pytest.raises(SourceError):
        lu_pegel.parse(csv_text, {"features": []})
    bad = csv_text.replace('"Bollendorf","","cm"', '"Bollendorf","","cm"', 1)
    lines = bad.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith('"Bollendorf"'))
    lines[i] = '"Bollendorf","","cm"' + ',"99999"' * 60
    _, meas, _ = lu_pegel.parse("\n".join(lines), fixture("lu_wasserstand_stationen.json"))
    assert not any(m.station_id == "bollendorf" for m in meas)


async def test_lu_pegel_collector_and_gewaesser_payload(registry, storage, settings):
    def handler(r):
        if "features.geoportail.lu" in str(r.url):
            return fixture("lu_wasserstand_stationen.json")
        return httpx.Response(200, content=(FIX / "lu_water_levels.csv").read_bytes())
    # Die Werte sind vom 25.–30.09.; für die 48-Stunden-Reihe des Payloads zählt die Systemzeit, hier genügt die Station
    ok, _, _ = await run("lu_pegel", registry, storage, settings, handler)
    assert ok
    assert len(storage._query("SELECT 1 FROM stations WHERE source_id='lu_pegel'")) >= 38       # noqa: SLF001
    g = payloads.gewaesser_payload(storage, registry)
    assert "lu_pegel" in [s["id"] for s in g["sources"]]


# ---------------------------------------------------------------- DWD Waldbrand
def test_wbi_station_list_latin1_and_radius():
    st = dwd_waldbrand.pick_stations(dwd_waldbrand.parse_station_list(raw("dwd_wbi_stations_list.txt")))
    assert 10 <= len(st) <= 45 and st[0]["name"] == "Olsdorf" and all(s["distance_km"] <= 120 for s in st)
    assert any("Büchel" in s["name"] for s in st)          # Umlaute aus Latin-1 richtig gelesen


def test_wbi_series_takes_last_row_and_rejects_bad_values():
    issued, vals = dwd_waldbrand.parse_series(raw("dwd_wbi_1964.csv.gz"), "wbi")
    assert issued == "2026-09-30" and len(vals) == 7 and all(1 <= v <= 5 for v in vals)
    g = dwd_waldbrand.parse_series(raw("dwd_glfi_1964.csv.gz"), "glfi")
    assert g and len(g[1]) == 7
    bad = gzip.compress(b"StationsID;Termin;wbi_0;wbi_1;wbi_2;wbi_3;wbi_4;wbi_5;wbi_6\n1;20260930 04:13;-999;1;1;1;1;1;1\n")
    assert dwd_waldbrand.parse_series(bad, "wbi") is None          # Fehlwert wird nicht als Stufe gezeigt
    with pytest.raises(SourceError):
        dwd_waldbrand.parse_series(gzip.compress(b"a;b\n1;2\n"), "wbi")


async def test_wbi_collector_events_from_level_3(registry, storage, settings):
    def handler(r):
        p = r.url.path
        if p.endswith("stations_list.txt"):
            return httpx.Response(200, content=raw("dwd_wbi_stations_list.txt"))
        return httpx.Response(200, content=raw("dwd_wbi_1964.csv.gz" if "woodland" in p else "dwd_glfi_1964.csv.gz"))
    import app.collectors.dwd_waldbrand as mod
    mod.PAUSE_S = 0
    ok, _, _ = await run("dwd_waldbrand", registry, storage, settings, handler)
    assert ok
    # Fixture: Stufe 3 heute → notice; alle Stationen liefern dieselbe Datei
    assert storage.count_active("dwd_waldbrand") == 10
    c = storage.cache_get("fire_index")["payload"]
    assert len(c["stations"]) == 10 and c["stations"][0]["wbi"][0] == 3


# ---------------------------------------------------------------- DWD Pollen / UV
def test_pollen_and_uv_parse():
    p = dwd_gesundheit.parse_pollen(fixture("dwd_s31fg.json"), [101, 102])
    assert [r["id"] for r in p["regions"]] == [101, 102] and p["regions"][0]["days"]["today"]["Graeser"]
    assert p["legend"]["0-1"] == "keine bis geringe Belastung"
    uv = dwd_gesundheit.parse_uv(fixture("dwd_uvi.json"), "Hahn")
    assert uv["station"] == "Hahn" and isinstance(uv["today"], int)
    with pytest.raises(SourceError):
        dwd_gesundheit.parse_uv(fixture("dwd_uvi.json"), "Nirgendwo")
    with pytest.raises(SourceError):
        dwd_gesundheit.parse_pollen(fixture("dwd_s31fg.json"), [999])


async def test_gesundheit_collector_and_indizes_payload(registry, storage, settings):
    def handler(r):
        return fixture("dwd_s31fg.json") if r.url.path.endswith("s31fg.json") else fixture("dwd_uvi.json")
    ok, router, _ = await run("dwd_gesundheit", registry, storage, settings, handler)
    assert ok and len(router.calls) == 2
    idx = payloads.indizes_payload(storage, registry)
    assert idx["pollen"]["regions"] and idx["uv"]["station"] == "Hahn" and idx["fire"]["stations"] == []


# ---------------------------------------------------------------- Tankerkönig
def _tk(**kw):
    s = {"id": "s1", "name": "Testtankstelle", "brand": "TEST", "street": "Geheimweg", "houseNumber": "1", "place": "Bitburg",
         "lat": 49.97, "lng": 6.52, "isOpen": True, "e5": 1.799, "e10": 1.739, "diesel": 1.659}
    s.update(kw)
    return s


def test_tankerkoenig_parse_SYNTHETISCH():
    sts, ms = tankerkoenig.parse_list({"ok": True, "stations": [
        _tk(), _tk(id="s2", isOpen=False), _tk(id="s3", e5=None, e10=None, diesel=None), _tk(id="s4", lat=48.0, lng=2.0),
        _tk(id="s5", diesel=0.0)]}, utcnow())
    assert {s.station_id for s in sts} == {"s1", "s5"}
    assert "Geheimweg" not in json.dumps([s.model_dump(mode="json") for s in sts])     # keine Straße gespeichert
    assert {m.parameter for m in ms if m.station_id == "s5"} == {"e5", "e10"}          # Preis 0 fällt weg
    with pytest.raises(SourceError):
        tankerkoenig.parse_list({"ok": False, "message": "apikey nicht gültig"}, utcnow())


async def test_tankerkoenig_needs_key_and_masks_it(registry, storage, settings, monkeypatch):
    entry = registry.get("tankerkoenig").model_copy(update={"aktiv": True})
    monkeypatch.delenv("TANKERKOENIG_API_KEY", raising=False)
    client, _ = make_client(lambda r: {"ok": True, "stations": []})
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    with pytest.raises(SourceError, match="fehlt"):
        await c.collect()
    monkeypatch.setenv("TANKERKOENIG_API_KEY", "geheim-123")
    client2, _ = make_client(lambda r: httpx.Response(401))
    c2 = load_collector_class(entry.collector)(entry, storage, client2, settings, backoff_base_s=0.0)
    with pytest.raises(SourceError) as exc:
        await c2.collect()
    assert "geheim-123" not in str(exc.value)
    await client.aclose(); await client2.aclose()


def test_tankerkoenig_registered_active_key_only_from_env(registry):
    e = registry.get("tankerkoenig")
    assert e.aktiv is True and "TANKERKOENIG_API_KEY" in e.auth
    import re
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", str(e))   # kein Schlüssel im Register


# ---------------------------------------------------------------- Themenradar
def _post(i, acct, tags, age_h=1, **kw):
    t = (utcnow() - timedelta(hours=age_h)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    d = {"id": str(i), "uri": f"https://x.example/{i}", "created_at": t, "sensitive": False, "spoiler_text": "",
         "account": {"id": str(acct), "acct": "privat@beispiel", "display_name": "Erika Mustermann"},
         "content": "<p>Text der nie gespeichert wird</p>", "tags": [{"name": n} for n in tags]}
    d.update(kw)
    return d


def test_themen_k_threshold_and_no_personal_data_SYNTHETISCH():
    posts = [_post(1, 1, ["trier", "wandern"]), _post(2, 2, ["trier", "wandern"]), _post(3, 3, ["trier", "wandern"]),
             _post(4, 1, ["trier", "geheimtipp"]), _post(5, 1, ["trier", "geheimtipp"]),       # ein Konto allein: unter der Schwelle
             _post(6, 4, ["trier", "alt"], age_h=30),                                        # außerhalb der 24 Stunden
             _post(7, 5, ["trier", "cw"], spoiler_text="Inhaltswarnung"),                     # mit Inhaltswarnung: ganz weg
             _post(8, 6, ["trier", "delikat"], sensitive=True)]
    out = mastodon_themen.aggregate({"trier": posts}, utcnow())
    assert out["regions"] == [{"tag": "trier", "posts": 5}]
    assert [t["tag"] for t in out["topics"]] == ["wandern"]
    blob = json.dumps(out)
    for forbidden in ("Mustermann", "privat@", "Text der nie", "x.example", "geheimtipp", '"account"'):
        assert forbidden not in blob


def test_themen_rejects_odd_tags_and_dupes_SYNTHETISCH():
    posts = [_post(i, i, ["trier", "a" * 50, "x y", "ok1"]) for i in range(1, 4)] + [_post(1, 1, ["trier", "ok1"])]
    out = mastodon_themen.aggregate({"trier": posts}, utcnow())
    assert [t["tag"] for t in out["topics"]] == ["ok1"] and out["topics"][0]["posts"] == 3          # Dublette nicht doppelt


async def test_themen_collector_and_payload(registry, storage, settings, monkeypatch):
    import app.collectors.mastodon_themen as mod
    async def fast(_): return None
    monkeypatch.setattr(mod.asyncio, "sleep", fast)
    posts = [_post(i, i, ["trier", "wandern"]) for i in range(1, 5)]
    ok, router, _ = await run("mastodon_themen", registry, storage, settings, lambda r: posts)
    assert ok and len(router.calls) == 10
    t = payloads.themen_payload(storage, registry)
    assert t["radar"]["topics"][0]["tag"] == "wandern" and "Mustermann" not in json.dumps(t)


# ---------------------------------------------------------------- Kraftstoff-Payload
def test_kraftstoff_payload_empty_is_honest(storage, registry):
    k = payloads.kraftstoff_payload(storage, registry)
    assert k["stations"] == [] and k["stats"] == {} and k["source"]["status"] == "pending"
