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
    assert [g["id"] for g in doc["groups"]] == [g[0] for g in lgb.GRUPPEN]
    for g, (_, _, dienste) in zip(doc["groups"], lgb.GRUPPEN):
        assert [s["id"] for s in g["services"]] == dienste
    assert doc["lizenz"] == "dl-de/by-2-0" and "{jahr}" in doc["vermerk"]
    assert set(doc["ausgeblendet"]) == lgb.AUSGEBLENDET
