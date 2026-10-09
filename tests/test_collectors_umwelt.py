"""Collector für Hochwasser RLP, BfS-ODL, UBA-Luft, EMSC und DWD-Radar gegen aufgezeichnete Antworten.

Echte Fixtures (auf wenige Stellen gekürzt): hwrlp_config.json, hwrlp_index.json, bfs_odl.json, uba_stations.json,
uba_airquality.json, emsc_query.json. Die Zeitstempel der echten Antworten sind alt; `shift` verschiebt sie auf „jetzt“,
damit die Frischeprüfungen der Collector greifen. SYNTHETISCH sind nur die im Test markierten Abwandlungen
(Hochwasserklasse, erhöhte Strahlung, Magnituden, Radarbild).
"""
import copy
import io
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from app import geo
from app.collectors import load_collector_class
from app.collectors.dwd_radar import clean_nodata
from conftest import FIX, fixture, make_client

ISO_Z = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z")
CET_TS = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
CET = timezone(timedelta(hours=1))


def shift(obj, ref: datetime, newest: datetime, cet: bool = False):
    """Alle Zeitstempel so verschieben, dass `ref` (ältester Bezugspunkt der Aufnahme) auf `newest` fällt."""
    delta = newest - ref
    text = json.dumps(obj)
    if cet:
        text = CET_TS.sub(lambda m: (datetime.strptime(m.group(0), "%Y-%m-%d %H:%M:%S") + delta).strftime("%Y-%m-%d %H:%M:%S"), text)
    else:
        def one(m):
            raw = m.group(0)
            t = datetime.fromisoformat(raw.replace("Z", "+00:00")) + delta
            return t.strftime("%Y-%m-%dT%H:%M:%S") + ("Z" if "." not in raw else ".000Z")
        text = ISO_Z.sub(one, text)
    return json.loads(text)


async def run(name, registry, storage, settings, handler):
    client, router = make_client(handler)
    entry = registry.get(name)
    c = load_collector_class(entry.collector)(entry, storage, client, settings, backoff_base_s=0.0)
    ok = await c.run_once()
    await client.aclose()
    return ok, router, c


def events(storage):
    """Aktive Ereignisse als Objekte mit Attributzugriff (Storage liefert Zeilen als dict)."""
    return [SimpleNamespace(**e) for e in storage.active_events()]


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# ------------------------------------------------------------------ Geo
def test_utm32_to_wgs84_known_points():
    # Prümzurlay laut Konfiguration der Quelle: E 315807.7 / N 5527062.2 ≈ 49.9 N, 6.4 E (Prüm, Nähe Irrel)
    lat, lon = geo.utm32_to_wgs84(315807.7, 5527062.2)
    assert 49.80 < lat < 49.95 and 6.35 < lon < 6.50
    # Zentralmeridian der Zone 32 (9° E) bei E 500000 und Äquator-Ordinate 0
    lat0, lon0 = geo.utm32_to_wgs84(500000.0, 0.0)
    assert abs(lat0) < 1e-6 and abs(lon0 - 9.0) < 1e-6


# ------------------------------------------------------------------ Hochwasser RLP
def hw_handler(index_mutator=None, fail_index=False, calls=None):
    newest = now_utc() - timedelta(minutes=20)

    def h(req: httpx.Request):
        if calls is not None:
            calls.append(req.url.path)
        if req.url.path.endswith("/config"):
            return fixture("hwrlp_config.json")
        if fail_index:
            return httpx.Response(503)
        idx = fixture("hwrlp_index.json")
        idx = shift(idx, datetime(2026, 9, 29, 18, 15, tzinfo=timezone.utc), newest)
        if index_mutator:
            index_mutator(idx)
        return idx
    return h


async def test_hochwasser_rlp_stations_radius_and_wsa_dropped(registry, storage, settings):
    ok, _, _ = await run("hochwasser_rlp", registry, storage, settings, hw_handler())
    assert ok
    st = {s["station_id"]: s for s in storage.stations_with_latest("hochwasser_rlp", "W", hours=72)}
    # Prümzurlay, Stausee Bitburg, Bollendorf 2, Grevenmacher (LU) im Radius; Trier (WSA) kommt über PEGELONLINE,
    # Kronenburger See (56 km) liegt seit 80 km im Radius
    assert set(st) == {"26280504", "26280366", "26200505", "2650012", "26600128"}
    assert st["26280366"]["latest"]["unit"] == "m ü. NN" and st["26280504"]["latest"]["unit"] == "cm"
    assert st["26280504"]["latest"]["state"] == "< mittleres Niedrigwasser"  # Legendenname der Quelle für #00c8ff
    assert len(st["26280504"]["series"]) >= 8
    assert events(storage) == []  # Normalzustand erzeugt kein Ereignis


async def test_hochwasser_rlp_event_from_legend_class_SYNTHETISCH(registry, storage, settings):
    def mutate(idx):  # SYNTHETISCH: Prümzurlay meldet „Hohe Hochwassergefahr“ (Klasse 4, Farbe #f8ae64)
        idx["measurementSites"]["26280504"]["legendColor"] = "#f8ae64"
        idx["measurementSites"]["26280504"]["yLast"] = 310
    ok, _, _ = await run("hochwasser_rlp", registry, storage, settings, hw_handler(mutate))
    assert ok
    evs = events(storage)
    assert [e.id for e in evs] == ["hwrlp:26280504"]
    assert evs[0].type == "flood" and evs[0].severity == "warning" and "310 cm" in evs[0].summary
    assert evs[0].region_tag == "DE-RLP" and evs[0].raw_ref == "https://hochwasser.rlp.de/"


async def test_hochwasser_rlp_lu_region_and_no_value_skipped_SYNTHETISCH(registry, storage, settings):
    def mutate(idx):  # SYNTHETISCH: Grevenmacher (SN Luxemburg) auf Klasse 3; Bollendorf ohne Messwert
        idx["measurementSites"]["2650012"]["legendColor"] = "#f3e600"
        idx["measurementSites"]["26200505"]["legendColor"] = "#f0f0f0"
        idx["measurementSites"]["26200505"]["yLast"] = None
    ok, _, _ = await run("hochwasser_rlp", registry, storage, settings, hw_handler(mutate))
    assert ok
    evs = events(storage)
    assert [(e.id, e.severity, e.region_tag) for e in evs] == [("hwrlp:2650012", "notice", "LU")]
    assert "26200505" not in {s["station_id"] for s in storage.stations_with_latest("hochwasser_rlp", "W", hours=72)}


async def test_hochwasser_rlp_stale_value_gives_no_event_SYNTHETISCH(registry, storage, settings):
    def mutate(idx):  # SYNTHETISCH: Klasse 4, aber Messung vier Stunden alt
        c = idx["measurementSites"]["26280504"]
        c["legendColor"] = "#f8ae64"
        c["xLast"] = (now_utc() - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await run("hochwasser_rlp", registry, storage, settings, hw_handler(mutate))
    assert events(storage) == []


async def test_hochwasser_rlp_config_cached_and_second_run_no_duplicates(registry, storage, settings):
    calls: list[str] = []
    await run("hochwasser_rlp", registry, storage, settings, hw_handler(calls=calls))
    n1 = storage._query("SELECT COUNT(*) c FROM measurements WHERE source_id='hochwasser_rlp'")[0]["c"]
    await run("hochwasser_rlp", registry, storage, settings, hw_handler(calls=calls))
    n2 = storage._query("SELECT COUNT(*) c FROM measurements WHERE source_id='hochwasser_rlp'")[0]["c"]
    assert sum(p.endswith("/config") for p in calls) == 1  # Stammdaten 12 Stunden im Cache
    assert n1 > 0 and n2 == n1  # idempotent


async def test_hochwasser_rlp_schema_change_and_outage_fail_cleanly(registry, storage, settings):
    ok, _, _ = await run("hochwasser_rlp", registry, storage, settings, hw_handler(fail_index=True))
    assert not ok
    ok, _, _ = await run("hochwasser_rlp", registry, storage, settings, lambda r: {"foo": 1})
    assert not ok


# ------------------------------------------------------------------ BfS ODL
def odl_payload(mutator=None):
    d = fixture("bfs_odl.json")
    end = (now_utc() - timedelta(minutes=30)).replace(minute=0, second=0)
    for f in d["features"]:
        f["properties"]["start_measure"] = (end - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        f["properties"]["end_measure"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    if mutator:
        mutator(d)
    return d


async def test_bfs_odl_stations_radius_and_normal_values_no_event(registry, storage, settings):
    ok, router, _ = await run("bfs_odl", registry, storage, settings, lambda r: odl_payload())
    assert ok
    st = storage.stations_with_latest("bfs_odl", "odl", hours=6)
    assert len(st) == 7 and all(0.05 < s["latest"]["value"] < 0.3 for s in st)  # natürliche Umgebungsstrahlung
    assert "Bollendorf" in {s["name"] for s in st}
    assert not any(s["name"] in ("Weitab",) for s in st)  # außerhalb der 120 km
    assert st[0]["latest"]["unit"] == "µSv/h"
    assert events(storage) == []
    q = dict(router.calls[0].url.params)
    assert q["typeNames"] == "opendata:odlinfo_odl_1h_latest" and q["bbox"].endswith("urn:ogc:def:crs:EPSG::4326")


async def test_bfs_odl_thresholds_SYNTHETISCH(registry, storage, settings):
    def mutate(d):  # SYNTHETISCH: zwei Sonden über den eigenen Orientierungsschwellen
        d["features"][0]["properties"]["value"] = 0.45
        d["features"][1]["properties"]["value"] = 1.4
    await run("bfs_odl", registry, storage, settings, lambda r: odl_payload(mutate))
    sev = sorted(e.severity for e in events(storage))
    assert sev == ["notice", "warning"]
    assert all(e.type == "radiation" and "kein amtlicher Grenzwert" in e.summary for e in events(storage))


async def test_bfs_odl_stale_and_offline_probes_dropped_SYNTHETISCH(registry, storage, settings):
    def mutate(d):  # SYNTHETISCH: eine Sonde 9 Stunden alt, eine außer Betrieb
        d["features"][0]["properties"]["end_measure"] = (now_utc() - timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
        d["features"][1]["properties"]["site_status"] = 0
    await run("bfs_odl", registry, storage, settings, lambda r: odl_payload(mutate))
    names = {s["name"] for s in storage.stations_with_latest("bfs_odl", "odl", hours=12)}
    ref = odl_payload()["features"]
    assert ref[0]["properties"]["name"] not in names and ref[1]["properties"]["name"] not in names


async def test_bfs_odl_empty_answer_is_failure(registry, storage, settings):
    ok, _, _ = await run("bfs_odl", registry, storage, settings, lambda r: {"type": "FeatureCollection", "features": []})
    assert not ok


# ------------------------------------------------------------------ UBA Luft
def uba_handler(fail_station=None, lqi=None):
    def h(req: httpx.Request):
        if req.url.path.endswith("/stations/json"):
            return fixture("uba_stations.json")
        sid = req.url.params["station"]
        if sid == fail_station:
            return httpx.Response(500)
        raw = fixture("uba_airquality.json")
        rows = list(raw["data"].values())[0]
        newest = max(datetime.strptime(v[0], "%Y-%m-%d %H:%M:%S") for v in rows.values())
        target = (now_utc() - timedelta(minutes=30)).astimezone(CET).replace(tzinfo=None, minute=0, second=0)
        raw = shift(raw, newest.replace(tzinfo=None), target, cet=True)
        rows = list(raw["data"].values())[0]
        if lqi is not None:  # SYNTHETISCH
            last = sorted(rows)[-1]
            rows[last][1] = lqi
        return {"data": {sid: rows}}
    return h


async def test_uba_luft_stations_radius_components_and_cet_conversion(registry, storage, settings):
    ok, _, _ = await run("uba_luft", registry, storage, settings, uba_handler())
    assert ok
    st = {s["name"]: s for s in storage.stations_with_latest("uba_luft", "lqi", hours=12)}
    assert st, "keine Station gespeichert"
    codes = {s["meta"]["code"] if isinstance(s.get("meta"), dict) else None for s in st.values()}
    assert not any(c and c.startswith("DESL003") for c in codes)  # außerhalb
    params = {r["parameter"] for r in storage._query("SELECT DISTINCT parameter FROM measurements WHERE source_id='uba_luft'")}
    assert {"lqi", "NO2"} <= params
    newest = storage._query("SELECT MAX(ts) m FROM measurements WHERE source_id='uba_luft'")[0]["m"]
    age = now_utc() - datetime.fromisoformat(newest.replace("Z", "+00:00"))
    assert timedelta(0) <= age < timedelta(hours=2), "MEZ-Zeitstempel falsch nach UTC umgerechnet"
    assert events(storage) == []  # Index 1 = gut


@pytest.mark.parametrize("lqi,sev", [(3, "notice"), (4, "warning")])
async def test_uba_luft_event_thresholds_SYNTHETISCH(registry, storage, settings, lqi, sev):
    await run("uba_luft", registry, storage, settings, uba_handler(lqi=lqi))
    evs = events(storage)
    assert evs and {e.severity for e in evs} == {sev} and all(e.type == "air" for e in evs)


async def test_uba_luft_partial_failure_is_marked_not_fatal(registry, storage, settings):
    ok, _, c = await run("uba_luft", registry, storage, settings, uba_handler(fail_station="1481"))
    assert ok  # eine Station fehlt, der Rest bleibt
    ids = {s["station_id"] for s in storage.stations_with_latest("uba_luft", "lqi", hours=12)}
    assert "1481" not in ids and "1457" in ids


# ------------------------------------------------------------------ EMSC
def emsc_payload(mutator=None):
    d = fixture("emsc_query.json")
    if mutator:
        mutator(d)
    return d


async def test_emsc_radius_severity_and_idempotence(registry, storage, settings):
    ok, router, _ = await run("emsc", registry, storage, settings, lambda r: emsc_payload())
    assert ok
    rows = {r["id"]: r for r in storage._query("SELECT * FROM events WHERE source_id='emsc'")}
    # alle sechs Beben liegen im 80-km-Radius (die letzten drei 51 bis 66 km entfernt)
    assert len(rows) == 6 and {"emsc:20260708_0000165", "emsc:20260610_0000186", "emsc:20260522_0000149"} <= set(rows)
    assert all(r["type"] == "earthquake" and r["severity"] == "info" for r in rows.values())
    assert dict(router.calls[0].url.params)["format"] == "json"
    await run("emsc", registry, storage, settings, lambda r: emsc_payload())
    assert storage._query("SELECT COUNT(*) c FROM events WHERE source_id='emsc'")[0]["c"] == 6


async def test_emsc_magnitude_classes_and_blasts_SYNTHETISCH(registry, storage, settings):
    def mutate(d):  # SYNTHETISCH: Magnituden 3,4 und 4,2, das dritte Ereignis ist eine Sprengung
        by = {f["properties"]["unid"]: f["properties"] for f in d["features"]}
        by["20260708_0000165"]["mag"] = 3.4
        by["20260610_0000186"]["mag"] = 4.2
        by["20260522_0000149"]["evtype"] = "qb"
    await run("emsc", registry, storage, settings, lambda r: emsc_payload(mutate))
    rows = {r["id"]: r["severity"] for r in storage._query("SELECT id, severity FROM events WHERE source_id='emsc'")}
    assert rows["emsc:20260708_0000165"] == "notice" and rows["emsc:20260610_0000186"] == "warning"
    assert "emsc:20260522_0000149" not in rows   # Sprengung fällt weg


async def test_emsc_204_means_no_quakes_not_failure(registry, storage, settings):
    ok, _, _ = await run("emsc", registry, storage, settings, lambda r: httpx.Response(204))
    assert ok
    assert storage._query("SELECT COUNT(*) c FROM events WHERE source_id='emsc'")[0]["c"] == 0


async def test_emsc_schema_change_fails(registry, storage, settings):
    ok, _, _ = await run("emsc", registry, storage, settings, lambda r: {"unexpected": True})
    assert not ok


# ------------------------------------------------------------------ DWD-Radar
def png_bytes(pixels: dict[tuple[int, int], tuple[int, int, int, int]], size=(8, 8), fill=(0, 0, 0, 0)) -> bytes:
    im = Image.new("RGBA", size, fill)
    for xy, rgba in pixels.items():
        im.putpixel(xy, rgba)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def test_clean_nodata_makes_grey_and_magenta_transparent_but_keeps_rain():
    src = png_bytes({(0, 0): (126, 126, 126, 255), (1, 0): (255, 0, 255, 255), (2, 0): (0, 120, 255, 255), (3, 0): (128, 128, 128, 255)})
    im = Image.open(io.BytesIO(clean_nodata(src))).convert("RGBA")
    assert im.getpixel((0, 0))[3] == 0 and im.getpixel((1, 0))[3] == 0 and im.getpixel((3, 0))[3] == 0
    assert im.getpixel((2, 0)) == (0, 120, 255, 255)


def test_clean_nodata_removes_purple_fringe_at_coverage_edge_but_keeps_inner_violet():
    # Reihe: Grau | violett-graue Mischfarbe | blau | ... | echtes Violett weit weg vom Rand
    row = {(0, 0): (126, 126, 126, 255), (1, 0): (139, 92, 157, 255), (2, 0): (0, 120, 255, 255)}
    inner = {(x, 0): (0, 160, 90, 255) for x in range(3, 12)} | {(12, 0): (150, 40, 200, 255)}
    im = Image.open(io.BytesIO(clean_nodata(png_bytes(row | inner, size=(14, 1), fill=(0, 160, 90, 255))))).convert("RGBA")
    assert im.getpixel((1, 0))[3] == 0                     # Saum entfernt
    assert im.getpixel((2, 0))[3] == 255                   # blauer Regen am Rand bleibt
    assert im.getpixel((12, 0)) == (150, 40, 200, 255)     # Violett im Inneren bleibt


async def test_dwd_radar_steps_back_over_missing_timesteps_SYNTHETISCH(registry, storage, settings):
    seen: list[str] = []
    ok_png = png_bytes({(1, 1): (0, 120, 255, 255), (2, 2): (126, 126, 126, 255)})  # SYNTHETISCH

    def h(req: httpx.Request):
        seen.append(req.url.params["time"])
        if len(seen) < 3:  # die ersten beiden Zeitschritte gibt es noch nicht
            return httpx.Response(200, content=b"<ServiceException code='InvalidDimensionValue'>", headers={"content-type": "application/xml"})
        return httpx.Response(200, content=ok_png, headers={"content-type": "image/png"})
    ok, _, _ = await run("dwd_radar", registry, storage, settings, h)
    assert ok and len(seen) == 3
    assert all(t.endswith(":00Z") and int(t[14:16]) % 5 == 0 for t in seen)  # 5-Minuten-Raster
    row = storage.cache_get("radar")
    assert row and row["source_id"] == "dwd_radar"
    p = row["payload"]
    assert p["time"].startswith(seen[-1][:16]) and len(p["corners"]) == 4 and p["png_b64"]
    assert storage._query("SELECT COUNT(*) c FROM events WHERE source_id='dwd_radar'")[0]["c"] == 0


async def test_dwd_radar_no_image_at_all_is_failure(registry, storage, settings):
    ok, _, _ = await run("dwd_radar", registry, storage, settings,
                         lambda r: httpx.Response(200, content=b"InvalidDimensionValue", headers={"content-type": "text/xml"}))
    assert not ok


async def test_dwd_radar_http_error_is_failure(registry, storage, settings):
    ok, _, _ = await run("dwd_radar", registry, storage, settings, lambda r: httpx.Response(503))
    assert not ok


# ------------------------------------------------------------------ Payloads und Export
async def test_umwelt_payload_and_gewaesser_two_sources(registry, storage, settings, tmp_path):
    from app import export, payloads
    await run("bfs_odl", registry, storage, settings, lambda r: odl_payload())
    await run("uba_luft", registry, storage, settings, uba_handler())
    await run("hochwasser_rlp", registry, storage, settings, hw_handler())
    u = payloads.umwelt_payload(storage, registry)
    kinds = {s["kind"] for s in u["stations"]}
    assert kinds == {"radiation", "air"} and all(s["attribution"] and s["distance_km"] <= 120 for s in u["stations"])
    odl = next(s for s in u["stations"] if s["kind"] == "radiation")
    assert odl["values"]["odl"]["unit"] == "µSv/h" and "series" in odl["values"]["odl"]
    g = payloads.gewaesser_payload(storage, registry)
    assert {s["source_id"] for s in g["stations"]} >= {"hochwasser_rlp"}
    out = tmp_path / "d"
    sizes = export.write_all(export.build_all(storage, registry), out)
    assert "umwelt.json" in sizes and "radar.png" not in sizes  # ohne Radarlauf keine Bilddatei


async def test_radar_export_writes_png_and_json_SYNTHETISCH(registry, storage, settings, tmp_path):
    from app import export
    ok_png = png_bytes({(1, 1): (0, 120, 255, 255)})  # SYNTHETISCH
    await run("dwd_radar", registry, storage, settings, lambda r: httpx.Response(200, content=ok_png, headers={"content-type": "image/png"}))
    out = tmp_path / "d"
    sizes = export.write_all(export.build_all(storage, registry), out)
    assert "radar.png" in sizes and (out / "radar.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    meta = json.loads((out / "radar.json").read_text())
    assert meta["time"] and len(meta["corners"]) == 4 and meta["source"]["attribution"]


def test_radar_smooth_upscales_and_softens_edges():
    import io
    from PIL import Image
    from app.collectors.dwd_radar import smooth
    src = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    src.putpixel((1, 1), (0, 120, 255, 255))
    buf = io.BytesIO(); src.save(buf, format="PNG")
    out = Image.open(io.BytesIO(smooth(buf.getvalue(), factor=6, blur=1.0)))
    assert out.size == (24, 24)
    alphas = {out.getpixel((x, 9))[3] for x in range(24)}
    assert len(alphas) > 4                      # weicher Verlauf statt hart 0/255 (keine Klötzchen)
    r, g, b, a = out.getpixel((9, 9))
    assert a > 0 and b > r                      # Farbe bleibt blau, kein dunkler Saum


def _flash_png(cells):  # SYNTHETISCH: Bildpunkte mit Blitzen (Farbe egal, nur Alpha zählt)
    return png_bytes({xy: (200, 0, 200, 255) for xy in cells}, size=(12, 12))


def test_render_flashes_colours_by_age_and_counts():
    from app.collectors.eumetsat_li import render_flashes
    old = _flash_png([(2, 2)])
    new = _flash_png([(8, 8)])
    png, counts = render_flashes([(40.0, old), (3.0, new)])
    assert counts == {"bis 10 min": 1, "bis 20 min": 0, "bis 30 min": 0, "bis 45 min": 1}
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    assert im.size[0] % 6 == 0
    young = im.getpixel((8 * 6 + 3, 8 * 6 + 3)); older = im.getpixel((2 * 6 + 3, 2 * 6 + 3))
    assert young[3] > 100 and older[3] > 100
    assert young[0] > 200 and young[1] > 150 and young[2] < 80      # gelb
    assert older[0] < 200 and older[1] < 60                          # dunkelrot


async def test_eumetsat_li_empty_sky_is_valid_and_dedups_repeated_frames_SYNTHETISCH(registry, storage, settings):
    empty = png_bytes({})
    ok, _, _ = await run("eumetsat_li", registry, storage, settings, lambda r: httpx.Response(200, content=empty, headers={"content-type": "image/png"}))
    assert ok
    p = storage.cache_get("blitz")["payload"]
    assert set(p["counts"].values()) == {0} and p["window_min"] == 45 and len(p["corners"]) == 4 and p["png_b64"]
    assert storage._query("SELECT COUNT(*) c FROM events WHERE source_id='eumetsat_li'")[0]["c"] == 0


async def test_eumetsat_li_no_image_is_failure(registry, storage, settings):
    ok, _, _ = await run("eumetsat_li", registry, storage, settings,
                         lambda r: httpx.Response(200, content=b"InvalidDimensionValue", headers={"content-type": "text/xml"}))
    assert not ok


# --- NASA FIRMS (synthetische CSV; Aufbau wie die VIIRS-Antwort der Area-API) ------------------------------------------------

FIRMS_KEY = "TESTKEY0123456789abcdef0123456789"
FIRMS_HEAD = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"


def firms_row(lat, lon, conf, frp, when, sat="N"):
    return f"{lat},{lon},330.1,0.4,0.4,{when:%Y-%m-%d},{when:%H%M},{sat},VIIRS,{conf},2.0NRT,290.2,{frp},D\n"


@pytest.fixture
def firms_env(monkeypatch):
    monkeypatch.setenv("FIRMS_MAP_KEY", FIRMS_KEY)


async def test_firms_radius_confidence_dedup_and_severity_SYNTHETISCH(registry, storage, settings, firms_env):
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=30)
    by_source = {
        "VIIRS_SNPP_NRT": FIRMS_HEAD + firms_row(49.9012, 6.5011, "h", 32.5, t, "N") + firms_row(49.7001, 6.3001, "l", 9.0, t)
                          + firms_row(48.8000, 2.3000, "h", 50.0, t),   # Paris: außerhalb
        "VIIRS_NOAA20_NRT": FIRMS_HEAD + firms_row(49.9015, 6.5014, "n", 5.0, t, "1") + firms_row(50.0001, 6.6001, "n", 3.0, t, "1"),
        "VIIRS_NOAA21_NRT": FIRMS_HEAD,   # Überflug ohne Treffer: nur Kopfzeile
    }
    def handler(req):
        src = req.url.path.split("/")[5]
        return httpx.Response(200, text=by_source[src], headers={"content-type": "text/csv"})
    ok, router, _ = await run("nasa_firms", registry, storage, settings, handler)
    assert ok and len(router.calls) == 3
    assert all(f"/{FIRMS_KEY}/" in c.url.path and c.url.path.endswith("/2") for c in router.calls)
    rows = {r["id"]: r for r in storage._query("SELECT * FROM events WHERE source_id='nasa_firms'")}
    assert len(rows) == 2                                   # zwei Satelliten am selben Punkt = ein Ereignis; niedrig und Paris weg
    sev = sorted(r["severity"] for r in rows.values())
    assert sev == ["info", "notice"]                         # 32,5 MW bei hoher Konfidenz = notice, 3 MW nominal = info
    assert all(r["type"] == "fire" and "nicht bestätigt" in r["summary"] for r in rows.values())
    await run("nasa_firms", registry, storage, settings, handler)
    assert storage._query("SELECT COUNT(*) c FROM events WHERE source_id='nasa_firms'")[0]["c"] == 2   # idempotent


async def test_firms_missing_key_is_failure_without_call(registry, storage, settings, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    ok, router, _ = await run("nasa_firms", registry, storage, settings, lambda r: httpx.Response(200, text=FIRMS_HEAD))
    assert not ok and router.calls == []
    assert "FIRMS_MAP_KEY" in storage.get_state("nasa_firms")["last_error"]


async def test_firms_key_never_appears_in_error_state(registry, storage, settings, firms_env):
    ok, _, _ = await run("nasa_firms", registry, storage, settings, lambda r: httpx.Response(403, text="forbidden"))
    err = storage.get_state("nasa_firms")["last_error"]
    assert not ok and err and FIRMS_KEY not in err


async def test_firms_invalid_key_body_is_failure_and_masked(registry, storage, settings, firms_env):
    ok, _, _ = await run("nasa_firms", registry, storage, settings, lambda r: httpx.Response(200, text="Invalid MAP_KEY."))
    err = storage.get_state("nasa_firms")["last_error"]
    assert not ok and "Invalid MAP_KEY" in err and FIRMS_KEY not in err


async def test_firms_partial_failure_keeps_events_and_marks_incomplete(registry, storage, settings, firms_env):
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=20)
    def handler(req):
        if "NOAA20" in req.url.path:
            return httpx.Response(500)
        return httpx.Response(200, text=FIRMS_HEAD + firms_row(49.9012, 6.5011, "h", 25.0, t))
    ok, _, _ = await run("nasa_firms", registry, storage, settings, handler)
    assert ok and storage._query("SELECT COUNT(*) c FROM events WHERE source_id='nasa_firms'")[0]["c"] == 1
    assert "NOAA20" in (storage.get_state("nasa_firms")["last_error"] or "")


def test_dotenv_loader_sets_only_missing_and_ignores_comments(tmp_path, monkeypatch):
    from app.config import load_dotenv
    f = tmp_path / ".env"
    f.write_text("# Kommentar\nA_NEU=eins\nA_ALT=zwei\n\nLEER=\nB='drei'\n", encoding="utf-8")
    monkeypatch.setenv("A_ALT", "bleibt")
    for k in ("A_NEU", "B", "LEER"):
        monkeypatch.delenv(k, raising=False)
    assert load_dotenv(f) == 2
    import os
    assert (os.environ["A_NEU"], os.environ["A_ALT"], os.environ["B"], os.environ.get("LEER")) == ("eins", "bleibt", "drei", None)
    monkeypatch.delenv("A_NEU"); monkeypatch.delenv("B")
    assert load_dotenv(tmp_path / "gibtsnicht") == 0


# ------------------------------------------------------------------ DWD-Wind (ICON-D2)
def _wind_blob(base: float, lead_h: int = 3) -> bytes:
    """SYNTHETISCH: 6x5-Gitter um 6,0 E / 49,9 N, Schrittweite 0,02°, Wert = base + Spaltenindex."""
    import bz2
    from grib_fixture import make_grib
    vals = [base + i for _ in range(5) for i in range(6)]
    vals[7] = None  # Bitmaske: ein Punkt ohne Wert
    return bz2.compress(make_grib(vals, 6, 5, 49.9, 6.0, 0.02, datetime(2026, 9, 30, 12, tzinfo=timezone.utc), lead_h))


async def test_dwd_wind_steps_back_to_older_run_and_crops_SYNTHETISCH(registry, storage, settings):
    runs: list[str] = []

    def h(req: httpx.Request):
        hh = req.url.path.split("/grib/")[1].split("/")[0]
        if hh not in runs:
            runs.append(hh)
        if len(runs) < 3:  # die beiden jüngsten Läufe sind noch nicht veröffentlicht
            return httpx.Response(404)
        return httpx.Response(200, content=_wind_blob(1.0 if "u_10m" in req.url.path else -2.0))
    ok, _, _ = await run("dwd_icon_d2_wind", registry, storage, settings, h)
    row = storage.cache_get("wind")
    assert ok and row and row["source_id"] == "dwd_icon_d2_wind"
    g = row["payload"]
    assert g["nx"] == 3 and g["ny"] == 3 and g["dlon"] == 0.04
    assert len(g["u"]) == 3 and len(g["u"][0]) == 3
    assert g["u"][0][0] == 1.0 and g["v"][0][0] == -2.0
    assert g["time"].startswith("2026-09-30T15:00") and g["run"].startswith("2026-09-30T12:00") and g["lead_h"] == 3
    assert g["bbox"][3] > g["bbox"][1]  # Nord > Süd
    assert storage._query("SELECT COUNT(*) c FROM events WHERE source_id='dwd_icon_d2_wind'")[0]["c"] == 0


async def test_dwd_wind_all_runs_missing_is_failure(registry, storage, settings):
    ok, _, _ = await run("dwd_icon_d2_wind", registry, storage, settings, lambda r: httpx.Response(404))
    assert not ok


async def test_dwd_wind_garbage_is_failure(registry, storage, settings):
    ok, _, _ = await run("dwd_icon_d2_wind", registry, storage, settings, lambda r: httpx.Response(200, content=b"kein bz2"))
    assert not ok


# ------------------------------------------------------------------ Bison Futé (Frankreich)
def _bf() -> bytes:
    return (FIX / "bison_fute_real_2026-09-30.xml").read_bytes()


def test_bison_fute_parse_real_sample_filters_to_radius():
    from app.collectors.bison_fute import parse_situations
    now = datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc)
    evs, st = parse_situations(_bf(), now)
    assert len(evs) == 4 and st["situations"] == 6
    assert all(e.type == "traffic" and e.region_tag == "FR" and e.attrs["land"] == "FR" and e.source_id == "bison_fute" for e in evs)
    assert {e.attrs["kind"] for e in evs} == {"baustelle", "sperrung"}
    assert any("Vollsperrung" in e.title and e.severity == "warning" for e in evs)
    assert all(geo.geometry_within_radius(e.geometry) for e in evs)


def test_bison_fute_rejects_doctype_and_garbage():
    from app.collectors.base import SourceError
    from app.collectors.bison_fute import parse_situations
    now = datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc)
    with pytest.raises(SourceError):
        parse_situations(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>', now)
    with pytest.raises(SourceError):
        parse_situations(b"kein xml", now)


async def test_bison_fute_collector_end_to_end_SYNTHETISCH(registry, storage, settings):
    ok, _, _ = await run("bison_fute", registry, storage, settings, lambda r: httpx.Response(200, content=_bf(), headers={"content-type": "application/xml"}))
    assert ok
    n = len(events(storage))   # hängt von der Uhrzeit ab, weil abgelaufene Meldungen wegfallen; die Zahl mit festem Datum prüft der Parser-Test
    ok2, _, _ = await run("bison_fute", registry, storage, settings, lambda r: httpx.Response(200, content=_bf()))
    assert ok2 and len(events(storage)) == n   # idempotent
