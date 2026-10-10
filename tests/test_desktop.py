import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError

import pytest

from app import desktop


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    web = tmp_path / "web"; (web / "data").mkdir(parents=True); (web / "index.html").write_text("<p>hi</p>")
    (web / "data" / "alt.json").write_text("{}")          # Beispieldaten der App dürfen nie ausgeliefert werden
    d = tmp_path / "d"
    app = desktop.App(d, web, tmp_path / "pmtiles", tmp_path)
    started = []
    monkeypatch.setattr(app, "start", lambda s: started.append(s) or True)
    box = [0]
    s = ThreadingHTTPServer(("127.0.0.1", 0), desktop.make_handler(app, box)); box[0] = s.server_address[1]
    threading.Thread(target=s.serve_forever, daemon=True).start()
    (d / "tiles" / "x.pmtiles").write_bytes(bytes(range(256)) * 4)
    yield app, box[0], started
    s.shutdown()


def call(port, path, method="GET", body=None, headers=None, host=None):
    h = {"Host": host or f"127.0.0.1:{port}", **(headers or {})}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_state_unconfigured(srv):
    _, port, _ = srv
    st, body, _ = call(port, "/api/state")
    assert st == 200 and json.loads(body)["configured"] is False


def test_foreign_host_rejected(srv):
    _, port, _ = srv
    assert call(port, "/api/state", host="evil.example")[0] == 403


def test_post_needs_header_and_valid_center(srv):
    app, port, started = srv
    assert call(port, "/api/setup", "POST", {"lat": 49.8, "lon": 6.4})[0] == 403
    assert call(port, "/api/setup", "POST", {"lat": 99, "lon": 6.4}, {"X-OSINT": "1"})[0] == 400
    assert call(port, "/api/setup", "POST", {"lat": 49.8, "lon": 6.4, "name": "Irrel"}, {"X-OSINT": "1"})[0] == 200
    assert started and app.settings()["lat"] == 49.8
    assert call(port, "/api/setup", "POST", {"lat": 52.5, "lon": 13.4}, {"X-OSINT": "1"})[0] == 409   # kein stilles Umsetzen


def test_data_comes_only_from_data_dir_and_range_works(srv):
    _, port, _ = srv
    assert call(port, "/data/alt.json")[0] == 404
    st, body, hd = call(port, "/tiles/x.pmtiles", headers={"Range": "bytes=2-5"})
    assert st == 206 and body == bytes([2, 3, 4, 5]) and hd["Content-Range"] == "bytes 2-5/1024"


def test_no_path_traversal(srv):
    _, port, _ = srv
    assert call(port, "/tiles/..%2f..%2fetc%2fpasswd")[0] == 404


def test_use_certifi_sets_bundle_and_respects_user_value(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    path = desktop.use_certifi()
    assert path and path.endswith("cacert.pem") and desktop.os.environ["SSL_CERT_FILE"] == path
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/eigenes.pem")
    assert desktop.use_certifi() == "/etc/eigenes.pem"


def test_user_agent_has_real_contact_by_default(monkeypatch):
    monkeypatch.delenv("OSINT_CONTACT", raising=False)
    assert ".invalid" not in desktop.ua() and desktop.PROJECT_URL in desktop.ua()    # Nominatim: 403 bei Platzhalteradresse
    monkeypatch.setenv("OSINT_CONTACT", "mail@beispiel.de")
    assert "mail@beispiel.de" in desktop.ua()
