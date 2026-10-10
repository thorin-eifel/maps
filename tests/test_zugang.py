"""Zugangsdaten je Quelle: Ablage, Freigabeliste, Schnittstelle der Desktop-App, Weitergabe an Kindprozesse."""
import json
import os
import stat
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError

import pytest

from app import desktop
from app.registry import Registry
from app.zugang import ZugangError, ZugangStore
from conftest import ROOT


@pytest.fixture()
def store(tmp_path):
    return ZugangStore(tmp_path / "zugang.json", Registry.load(ROOT / "sources.yaml").entries)


def test_register_declares_credentials_for_key_sources(registry):
    got = {e.id: [(f.env, f.art) for f in e.zugang] for e in registry.entries if e.zugang}
    assert got == {"nasa_firms": [("FIRMS_MAP_KEY", "schluessel")], "tankerkoenig": [("TANKERKOENIG_API_KEY", "schluessel")]}
    assert all("zugang" not in e.public() for e in registry.entries)      # nicht auf die öffentliche Quellenseite


def test_set_status_delete_roundtrip_without_leaking_values(store):
    st = {q["source_id"]: q for q in store.status()}
    assert set(st) == {"nasa_firms", "tankerkoenig"} and not st["tankerkoenig"]["felder"][0]["gesetzt"]
    store.set("TANKERKOENIG_API_KEY", "  geheim-123  ")
    assert store.env() == {"TANKERKOENIG_API_KEY": "geheim-123"}
    assert {q["source_id"]: q["felder"][0]["gesetzt"] for q in store.status()} == {"nasa_firms": False, "tankerkoenig": True}
    assert "geheim-123" not in json.dumps(store.status())
    store.delete("TANKERKOENIG_API_KEY")
    assert store.env() == {}


@pytest.mark.skipif(os.name == "nt", reason="Dateirechte")
def test_file_is_private_and_atomic(store, tmp_path):
    store.set("FIRMS_MAP_KEY", "abc")
    assert stat.S_IMODE((tmp_path / "zugang.json").stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("env", ["LD_PRELOAD", "PATH", "OSINT_DB_PATH", "", "tankerkoenig_api_key"])
def test_only_registered_variables_are_accepted(store, env):
    with pytest.raises(ZugangError):
        store.set(env, "x")
    with pytest.raises(ZugangError):
        store.delete(env)


@pytest.mark.parametrize("value", ["", "   ", "a\nb", "a\x00b", "x" * 257, None, 12, ["a"]])
def test_values_are_validated(store, value):
    with pytest.raises(ZugangError) as err:
        store.set("FIRMS_MAP_KEY", value)
    assert "x" * 50 not in str(err.value)           # Meldungen nennen nie den Wert


def test_foreign_entries_in_file_are_ignored(store, tmp_path):
    (tmp_path / "zugang.json").write_text(json.dumps({"LD_PRELOAD": "/evil.so", "FIRMS_MAP_KEY": "ok", "TANKERKOENIG_API_KEY": 5}))
    assert store.env() == {"FIRMS_MAP_KEY": "ok"}
    (tmp_path / "zugang.json").write_text("{kaputt")
    assert store.env() == {}


@pytest.fixture()
def srv(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    app = desktop.App(tmp_path / "d", web, tmp_path / "pmtiles", ROOT)
    box = [0]
    s = ThreadingHTTPServer(("127.0.0.1", 0), desktop.make_handler(app, box)); box[0] = s.server_address[1]
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield app, box[0]
    s.shutdown()


def call(port, path, method="GET", body=None, headers=None, host=None):
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_api_set_read_delete_and_child_env(srv, monkeypatch):
    monkeypatch.delenv("TANKERKOENIG_API_KEY", raising=False)
    app, port = srv
    x = {"X-OSINT": "1"}
    code, j = call(port, "/api/zugang")
    assert code == 200 and {q["source_id"] for q in j["quellen"]} == {"nasa_firms", "tankerkoenig"}
    code, j = call(port, "/api/zugang", "POST", {"env": "TANKERKOENIG_API_KEY", "wert": "streng-geheim"}, x)
    assert code == 200 and "streng-geheim" not in json.dumps(j)
    assert "streng-geheim" not in json.dumps(call(port, "/api/zugang")[1])
    assert app.env({"lat": 1, "lon": 2})["TANKERKOENIG_API_KEY"] == "streng-geheim"      # nur Kindprozesse bekommen den Wert
    code, j = call(port, "/api/zugang", "POST", {"env": "TANKERKOENIG_API_KEY", "loeschen": True}, x)
    assert code == 200 and "TANKERKOENIG_API_KEY" not in app.env({"lat": 1, "lon": 2})


def test_api_rejects_foreign_names_bad_values_and_missing_header(srv):
    app, port = srv
    x = {"X-OSINT": "1"}
    assert call(port, "/api/zugang", "POST", {"env": "LD_PRELOAD", "wert": "x"}, x)[0] == 400
    assert call(port, "/api/zugang", "POST", {"env": "FIRMS_MAP_KEY", "wert": "a\nb"}, x)[0] == 400
    assert call(port, "/api/zugang", "POST", {"env": ["x"], "wert": "a"}, x)[0] == 400
    assert call(port, "/api/zugang", "POST", {"env": "FIRMS_MAP_KEY", "wert": "ok"})[0] == 403                  # ohne X-OSINT
    assert call(port, "/api/zugang", "POST", {"env": "FIRMS_MAP_KEY", "wert": "ok"}, {**x, "Origin": "http://evil.example"})[0] == 403
    assert call(port, "/api/zugang", host="evil.example")[0] == 403                                            # DNS-Rebinding
    assert app.zugang.env() == {}
