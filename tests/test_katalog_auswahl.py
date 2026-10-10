"""Tests für tools/katalog_auswahl.py und die Auswahl in den Katalogen (je 16 Ebenen, keine Dubletten, keine Karte doppelt)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("katalog_auswahl", ROOT / "tools" / "katalog_auswahl.py")
ka = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ka)


def test_auswahl_hat_je_menue_16_eintraege_ohne_dubletten():
    for m in ("lgb", "landesdaten"):
        e = ka.lade(m)
        assert len(e) == 16, m
        assert len({(x["dienst"], x["ebene"]) for x in e}) == 16


def test_doppelter_eintrag_wird_abgelehnt(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"lgb": [{"dienst": "a", "ebene": "b"}, {"dienst": "a", "ebene": "b"}]}))
    with pytest.raises(ValueError, match="doppelt"):
        ka.lade("lgb", p)
    p.write_text(json.dumps({"lgb": [{"dienst": "a"}]}))
    with pytest.raises(ValueError, match="ohne dienst"):
        ka.lade("lgb", p)


def test_mojibake_wird_repariert_und_normaler_text_bleibt():
    assert ka.repariere_titel("LangzeitzÃ¤hlstellen 2016") == "Langzeitzählstellen 2016"
    assert ka.repariere_titel("Überflutungsflächen") == "Überflutungsflächen"
    assert ka.repariere_titel("Ã") == "Ã"


def test_kuerze_behaelt_gewaehlte_ebenen_und_ordnerpfad():
    baum = [{"title": "A", "name": "a"}, {"title": "Ordner", "children": [{"title": "B", "name": "b"}, {"title": "C", "name": "c"}]}, {"title": "Leer", "children": [{"title": "D", "name": "d"}]}]
    k = ka.kuerze(baum, {"b"})
    assert [n["title"] for n in k] == ["Ordner"]
    assert [c["name"] for c in k[0]["children"]] == ["b"]
    assert ka.namen_im_baum(k) == {"b"}


def test_kataloge_enthalten_genau_die_auswahl():
    for datei, menue in (("lgb.json", "lgb"), ("landesdaten.json", "landesdaten")):
        d = json.loads((ROOT / "web/geo" / datei).read_text(encoding="utf-8"))
        gewaehlt = {(s["id"], n) for g in d["groups"] for s in g["services"] for n in ka.namen_im_baum(s["layers"])}
        assert gewaehlt == {(e["dienst"], e["ebene"]) for e in ka.lade(menue)}, datei


def test_keine_ebene_in_beiden_menues_und_titel_ohne_mojibake():
    titel = []
    for datei in ("lgb.json", "landesdaten.json"):
        d = json.loads((ROOT / "web/geo" / datei).read_text(encoding="utf-8"))
        for g in d["groups"]:
            for s in g["services"]:
                titel.append(s["title"])
    assert not any("Ã" in t for t in titel)
