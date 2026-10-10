"""Tests für tools/build_lgb_katalog.py: Capabilities lesen, HTML aus Texten, Pflicht-CRS, ausgeblendete Hilfsebenen, Katalogdatei."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("lgb_katalog", ROOT / "tools" / "build_lgb_katalog.py")
lgb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lgb)
FIX = ROOT / "tests" / "fixtures" / "lgb_wms_erdbeben_capabilities.xml"


def _flat(nodes):
    for n in nodes:
        if n.get("name"):
            yield n
        yield from _flat(n.get("children", []))


def test_capabilities_erdbeben():
    s = lgb.parse_capabilities(FIX.read_bytes(), "mc_erdbeben")
    names = [n["name"] for n in _flat(s["layers"])]
    assert len(names) == 6
    assert {"Erdbebenereignisse", "Erdbebenzonen"} <= set(names)
    assert s["url"] == "https://mapserver.lgb-rlp.de/cgi-bin/mc_erdbeben"
    assert "<a" not in s.get("abstract", "")   # HTML aus dem Abstract entfernt
    first = next(_flat(s["layers"]))
    assert first["legend"].startswith("https://mapserver.lgb-rlp.de/")


def test_ohne_webmercator_wird_abgelehnt():
    xml = FIX.read_text(encoding="utf-8").replace("<CRS>EPSG:3857</CRS>", "")
    with pytest.raises(ValueError, match="3857"):
        lgb.parse_capabilities(xml.encode("utf-8"), "mc_x")


def test_hilfsebenen_bleiben_draussen():
    xml = FIX.read_text(encoding="utf-8")
    marker = "<Layer queryable=\"1\" opaque=\"0\" cascaded=\"0\">\n        <Name>Erdbebenzonen</Name>"
    assert marker in xml
    xml = xml.replace("<Name>Erdbebenzonen</Name>", "<Name>amtlich_raster</Name>")
    names = [n["name"] for n in _flat(lgb.parse_capabilities(xml.encode("utf-8"), "mc_erdbeben")["layers"])]
    assert "amtlich_raster" not in names and len(names) == 5


def test_klartext():
    assert lgb.klartext("Hallo &lt;b&gt;Welt&lt;/b&gt; <i>x</i>") == "Hallo Welt x"
    assert len(lgb.klartext("wort " * 200, 50)) <= 52


def test_katalogdatei_stimmt_mit_gruppen_ueberein():
    doc = json.loads((ROOT / "web" / "geo" / "lgb.json").read_text(encoding="utf-8"))
    # Der Katalog enthält nur die redaktionelle Auswahl (tools/katalog_auswahl.json), in der Reihenfolge von GRUPPEN.
    gewaehlt = {e["dienst"] for e in json.loads((ROOT / "tools" / "katalog_auswahl.json").read_text(encoding="utf-8"))["lgb"]}
    erwartet = [(gid, [d for d in dienste if d in gewaehlt]) for gid, _, dienste in lgb.GRUPPEN]
    erwartet = [(gid, d) for gid, d in erwartet if d]
    assert [(g["id"], [s["id"] for s in g["services"]]) for g in doc["groups"]] == erwartet
    assert doc["lizenz"] == "dl-de/by-2-0" and "{jahr}" in doc["vermerk"]
    assert set(doc["ausgeblendet"]) == lgb.AUSGEBLENDET


# ---- tools/build_landesdaten_katalog.py ----
spec2 = importlib.util.spec_from_file_location("landesdaten_katalog", ROOT / "tools" / "build_landesdaten_katalog.py")
lad = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(lad)


def test_basis_url_erzwingt_https_und_entfernt_wms_parameter():
    assert lad.basis_url("http://geo5.service24.rlp.de/wms/x.fcgi?") == "https://geo5.service24.rlp.de/wms/x.fcgi"
    assert lad.basis_url("https://h.de:443/cgi-bin/mapserv?map=/data/a.map&SERVICE=WMS&REQUEST=GetCapabilities") == "https://h.de/cgi-bin/mapserv?map=/data/a.map"
    assert lad.basis_url("ftp://h.de/x") is None


def test_mit_params_trennzeichen():
    assert lad.mit_params("https://h/x", "A=1") == "https://h/x?A=1"
    assert lad.mit_params("https://h/x?map=a", "A=1") == "https://h/x?map=a&A=1"
    assert lad.mit_params("https://h/x?", "A=1") == "https://h/x?A=1"


def test_anbieter_nur_landesstellen():
    assert lad.anbieter_von("Landesamt für Vermessung und Geobasisinformationen")[0] == "Landesamt für Vermessung"
    assert lad.anbieter_von("Verbandsgemeinde Südeifel") is None
    assert lad.anbieter_von("Stadt Trier") is None
    assert lad.anbieter_von("Ortsgemeinde Glees") is None


def test_nacktes_und_wird_maskiert_und_fertiges_bleibt():
    kaputt = b'<a href="x?a=1&b=2&amp;c=3&#38;d=4"/>'
    assert lad.repariere(kaputt) == b'<a href="x?a=1&amp;b=2&amp;c=3&#38;d=4"/>'


def test_crs_kleinschreibung_wird_akzeptiert():
    xml = FIX.read_text(encoding="utf-8").replace("<CRS>EPSG:3857</CRS>", "<CRS>epsg:3857</CRS>")
    assert lgb.parse_capabilities(xml.encode("utf-8"), "mc_x")["layers"]


def test_katalogdatei_ist_stimmig():
    d = json.loads((ROOT / "web/geo/landesdaten.json").read_text(encoding="utf-8"))
    assert d["lizenz_geprueft"] is False and d["groups"]
    assert not set(d["hosts"]) & lad.OHNE_CORS and "mapserver.lgb-rlp.de" not in d["hosts"]
    for g in d["groups"]:
        for s in g["services"]:
            assert s["url"].startswith("https://") and s["lizenz"] and s["vermerk"]
