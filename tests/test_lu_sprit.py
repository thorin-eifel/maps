"""Luxemburg: amtliche Höchstpreise (STATEC, echte Beispielantwort) und Tankstellen-Standorte (Overpass, synthetisch)."""
from __future__ import annotations

import httpx

from app.collectors.osm_tankstellen_lu import parse_elements
from app.collectors.statec_sprit import parse_csv
from app.payloads import luxembourg_fuel
from tests.test_collectors_umwelt import run, FIX


def _csv() -> str:
    return (FIX / "lustat_essence_real_2026-10-07.csv").read_text() + "\n" + "\n".join((FIX / "lustat_diesel_real_2026-10-07.csv").read_text().splitlines()[1:])


def test_parse_csv_takes_latest_value_per_fuel():
    got = parse_csv(_csv())
    assert got["sp95"] == {"value": 1.837, "valid_from": "2026-10-03"}
    assert got["sp98"]["value"] == 2.049 and got["diesel"]["value"] == 1.995 and got["diesel"]["valid_from"] == "2026-10-06"


def test_parse_csv_drops_implausible_and_garbage():
    bad = "MOTOR_ENERGY,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE\nDIE,2026-10-06,199.5,EUR_LI\nSP95,gestern,1.8,EUR_LI\nSP98,2026-10-06,2.0,EUR_HL\n"
    assert parse_csv(bad) == {}


def test_osm_parse_keeps_only_lu_radius_and_no_address():
    data = {"elements": [
        {"type": "node", "id": 1, "lat": 49.7, "lon": 6.35, "tags": {"amenity": "fuel", "brand": "Aral", "addr:street": "Rue X", "phone": "+352"}},
        {"type": "way", "id": 2, "center": {"lat": 49.61, "lon": 6.13}, "tags": {"amenity": "fuel"}},
        {"type": "node", "id": 3, "lat": 51.5, "lon": 6.35, "tags": {"amenity": "fuel", "name": "zu weit"}},
    ]}
    items = parse_elements(data)
    assert [i["id"] for i in items] == ["node/1", "way/2"]
    assert items[0]["name"] == "Aral" and items[1]["name"] == "Tankstelle"
    assert set(items[0]) == {"id", "name", "lat", "lon"}


async def test_collectors_end_to_end_and_payload_labels_max_price(registry, storage, settings):
    ok, _, _ = await run("statec_sprit", registry, storage, settings, lambda r: httpx.Response(200, text=_csv()))
    assert ok
    overpass = {"elements": [{"type": "node", "id": 1, "lat": 49.7, "lon": 6.35, "tags": {"amenity": "fuel", "brand": "Aral"}}]}
    ok2, _, _ = await run("osm_tankstellen_lu", registry, storage, settings, lambda r: httpx.Response(200, json=overpass))
    assert ok2
    lu = luxembourg_fuel(storage, registry)
    assert lu["kind"] == "max_price" and lu["max_prices"]["diesel"]["value"] == 1.995
    assert lu["stations"][0]["name"] == "Aral" and "prices" not in lu["stations"][0]


def test_private_sources_only_load_in_private_mode(tmp_path, monkeypatch):
    from app.registry import Registry
    src = tmp_path / "s.yaml"
    base = dict(name="x", betreiber="b", url="https://example.org", lizenz="CC BY-NC", namensnennung="n", intervall=60, ratenlimit="-",
                geo_bezug="g", datenschutz_risiko="niedrig", zuletzt_geprüft="2026-10-07", collector="c")
    import yaml
    src.write_text(yaml.safe_dump({"sources": [dict(base, id="a"), dict(base, id="b", nutzung="privat")]}, allow_unicode=True))
    monkeypatch.delenv("OSINT_MODE", raising=False)
    assert [e.id for e in Registry.load(src).entries] == ["a"]
    monkeypatch.setenv("OSINT_MODE", "privat")
    assert [e.id for e in Registry.load(src).entries] == ["a", "b"]
