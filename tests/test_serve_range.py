"""Lokaler Vorschauserver und Range-Prüfwerkzeug gegeneinander getestet."""
import importlib.util
import sys
import threading
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


serve = _load("serve_local", "deploy/serve-local.py")
check_range = _load("check_range", "tools/check_range.py")


@pytest.fixture
def server(tmp_path):
    (tmp_path / "tiles").mkdir()
    (tmp_path / "tiles" / "region.pmtiles").write_bytes(b"PMTiles" + bytes(range(256)) * 8)
    (tmp_path / "index.html").write_text("<p>hallo</p>")
    srv = serve.make_server(str(tmp_path), 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_range_partial_and_suffix(server):
    data = b"PMTiles" + bytes(range(256)) * 8
    r = httpx.get(f"{server}/tiles/region.pmtiles", headers={"Range": "bytes=0-6"})
    assert r.status_code == 206 and r.content == b"PMTiles"
    assert r.headers["content-range"] == f"bytes 0-6/{len(data)}"
    r = httpx.get(f"{server}/tiles/region.pmtiles", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == data[100:200]
    r = httpx.get(f"{server}/tiles/region.pmtiles", headers={"Range": "bytes=-10"})
    assert r.status_code == 206 and r.content == data[-10:]
    r = httpx.get(f"{server}/tiles/region.pmtiles", headers={"Range": f"bytes={len(data) - 5}-"})
    assert r.status_code == 206 and r.content == data[-5:]


def test_range_edge_cases(server):
    r = httpx.get(f"{server}/tiles/region.pmtiles", headers={"Range": "bytes=999999-"})
    assert r.status_code == 416
    r = httpx.get(f"{server}/tiles/region.pmtiles")  # ohne Range: ganze Datei
    assert r.status_code == 200 and r.content.startswith(b"PMTiles")
    r = httpx.get(f"{server}/index.html", headers={"Range": "bytes=0-2"})
    assert r.status_code == 206 and r.content == b"<p>"
    assert httpx.get(f"{server}/gibtsnicht", headers={"Range": "bytes=0-2"}).status_code == 404


def test_check_range_tool_ok_and_detects_missing_range(server, tmp_path):
    assert check_range.check(f"{server}/tiles/region.pmtiles") == []

    def no_range(request: httpx.Request) -> httpx.Response:  # Server, der Range ignoriert (wie ein schlechter Proxy)
        return httpx.Response(200, content=b"PMTiles" + b"x" * 500)

    with httpx.Client(transport=httpx.MockTransport(no_range)) as c:
        problems = check_range.check("https://example.invalid/x.pmtiles", client=c)
    assert problems and "ignoriert Range" in problems[0]

    def wrong_file(request: httpx.Request) -> httpx.Response:
        return httpx.Response(206, content=b"<html>Fehlerseite!", headers={"content-range": "bytes 0-15/900"})

    with httpx.Client(transport=httpx.MockTransport(wrong_file)) as c:
        problems = check_range.check("https://example.invalid/x.pmtiles", n=16, client=c)
    assert any("PMTiles-Kennung" in p or "Bytes" in p for p in problems)
