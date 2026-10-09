"""Lokaler Dienst der Desktop-App: Weboberfläche, Ersteinrichtung, Kartenabruf und Sammler in einem Prozess.

Zweck:     Die Tauri-Hülle startet diesen Dienst als Begleitprozess (Sidecar). Er liefert web/ auf 127.0.0.1 aus (mit Teilabrufen
           für PMTiles), fragt beim ersten Start nach dem Mittelpunkt, lädt dann Karte (120 km) und läuft als Sammelzyklus weiter.
Aufruf:    python -m app.desktop --data-dir ~/.local/share/osint [--port 0] [--pmtiles /pfad/pmtiles]
Beispiel:  python -m app.desktop --data-dir /tmp/osint-demo --port 8765   → http://127.0.0.1:8765/
Ablauf:    Start → Zeile "OSINT_READY port=N" auf stdout → Seite einrichtung.html, solange settings.json fehlt.
Sicherheit: nur 127.0.0.1, Host-Prüfung gegen DNS-Rebinding, schreibende Aufrufe nur mit Header X-OSINT und gleicher Herkunft.
           Nach außen geht: Ortsname an Nominatim (nur auf Knopfdruck, nur der Suchtext), Kartenabruf bei Protomaps, die Quellen laut sources.yaml.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("osint.desktop")
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CYCLE_S = 300


class Job:
    """Zustand der Einrichtung, thread-sicher lesbar."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.phase, self.msg, self.pct, self.error = "idle", "", 0, ""

    def set(self, phase: str, msg: str = "", pct: int | None = None, error: str = "") -> None:
        with self.lock:
            self.phase, self.msg, self.error = phase, msg, error
            if pct is not None:
                self.pct = pct

    def snapshot(self) -> dict:
        with self.lock:
            return {"phase": self.phase, "msg": self.msg, "pct": self.pct, "error": self.error}


class App:
    def __init__(self, data_dir: Path, web_dir: Path, pmtiles: Path, repo_dir: Path) -> None:
        self.data_dir, self.web_dir, self.pmtiles, self.repo_dir = data_dir, web_dir.resolve(), pmtiles, repo_dir
        self.job = Job()
        self.settings_path = data_dir / "settings.json"
        self.worker: threading.Thread | None = None
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "data").mkdir(exist_ok=True)
        (data_dir / "tiles").mkdir(exist_ok=True)

    def settings(self) -> dict | None:
        try:
            s = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return s if {"lat", "lon"} <= s.keys() else None
        except (OSError, ValueError):
            return None

    def env(self, s: dict) -> dict:
        e = dict(os.environ)
        e.update(OSINT_CENTER_LAT=str(s["lat"]), OSINT_CENTER_LON=str(s["lon"]), OSINT_DB_PATH=str(self.data_dir / "osint.sqlite"),
                 OSINT_WEB_DIR=str(self.web_dir), OSINT_NO_DOTENV="1")
        return e

    def _run(self, args: list[str], s: dict) -> int:
        """Sammler und Export als Kindprozess. Im gebündelten Programm (PyInstaller) ruft es sich selbst mit --run auf."""
        cmd = [sys.executable, "--run", *args] if getattr(sys, "frozen", False) else [sys.executable, "-m", *args]
        return subprocess.run(cmd, cwd=self.repo_dir, env=self.env(s), timeout=1800).returncode

    def start(self, s: dict) -> bool:
        if self.worker and self.worker.is_alive():
            return False
        self.worker = threading.Thread(target=self.work, args=(s,), daemon=True, name="osint-worker")
        self.worker.start()
        return True

    def work(self, s: dict) -> None:
        """Karte holen (einmalig), danach Sammeln und Exportieren im Takt. Fehler stoppen die Einrichtung sichtbar, nie still."""
        from app import tilebuild
        try:
            if not all((self.data_dir / "tiles" / n).exists() for n in ("region.pmtiles", "core.pmtiles", "ring.pmtiles")):
                self.job.set("tiles", "Kartenversion wird gesucht", 2)
                with urllib.request.urlopen(urllib.request.Request("https://build-metadata.protomaps.dev/builds.json", headers={"User-Agent": ua()}), timeout=30) as r:
                    bid = tilebuild.latest_build(lambda _u: r.read())
                tilebuild.build(s["lat"], s["lon"], self.data_dir / "tiles", self.pmtiles, bid,
                                progress=lambda i, n, m: self.job.set("tiles", m, 5 + int(60 * i / n)))
            while True:
                self.job.set("collect", "Daten werden abgerufen", 70)
                if self._run(["app.collect", "--once"], s) != 0:
                    log.warning("Sammelzyklus mit Fehlern beendet")
                self.job.set("export", "Daten werden aufbereitet", 90)
                if self._run(["app.export", "--out", str(self.data_dir / "data")], s) != 0:
                    raise RuntimeError("Export fehlgeschlagen")
                self.job.set("ready", "Bereit", 100)
                time.sleep(CYCLE_S)
        except Exception as err:   # sichtbar machen, nicht verschlucken
            log.exception("Einrichtung abgebrochen")
            self.job.set("error", "Abbruch", error=str(err)[:300])


def ua() -> str:
    return f"WasIstLosBeiUns/1.0 (+{os.environ.get('OSINT_CONTACT', 'kontakt@example.invalid')})"


def geocode(q: str) -> list[dict]:
    """Ortssuche über Nominatim (OSM). Es geht nur der Suchtext hinaus; Adressen (Hausnummern) werden nicht angeboten."""
    q = q.strip()[:80]
    if len(q) < 2:
        return []
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 8, "addressdetails": 0, "accept-language": "de"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua()}), timeout=15) as r:
        rows = json.load(r)
    out = []
    for x in rows:
        if x.get("category") in ("place", "boundary") or x.get("addresstype") in ("city", "town", "village", "hamlet", "suburb", "municipality", "county"):
            out.append({"name": str(x.get("display_name", ""))[:120], "lat": round(float(x["lat"]), 4), "lon": round(float(x["lon"]), 4)})
    return out[:6]


def make_handler(app: App, port_box: list[int]):
    class H(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".json": "application/json", ".pmtiles": "application/octet-stream",
                          ".css": "text/css", ".html": "text/html; charset=utf-8", ".mjs": "text/javascript"}

        def log_message(self, fmt: str, *a) -> None:
            log.debug(fmt, *a)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            super().end_headers()

        def host_ok(self) -> bool:
            return (self.headers.get("Host") or "") in {f"127.0.0.1:{port_box[0]}", f"localhost:{port_box[0]}"}

        def json(self, obj: object, code: int = 200) -> None:
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def translate_path(self, path: str) -> str:
            """/data/ nur aus dem Datenordner (nie Beispieldaten eines anderen Ortes), /tiles/ erst dort, dann aus der App."""
            p = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
            roots = [app.data_dir] if p.startswith("/data/") else [app.data_dir, app.web_dir] if p.startswith("/tiles/") else [app.web_dir]
            for root in roots:
                cand = (root / p.lstrip("/")).resolve()
                if (cand == root or root in cand.parents) and (cand.is_file() or cand.is_dir()):
                    return str(cand)
            return str(app.web_dir / "__nicht_da__")

        def do_GET(self) -> None:
            if not self.host_ok():
                return self.json({"error": "host"}, 403)
            u = urllib.parse.urlsplit(self.path)
            if u.path == "/api/state":
                s = app.settings()
                return self.json({"configured": s is not None, "center": s, "job": app.job.snapshot()})
            if u.path == "/api/geocode":
                try:
                    q = urllib.parse.parse_qs(u.query).get("q", [""])[0]
                    return self.json({"results": geocode(q)})
                except (OSError, ValueError) as err:
                    log.warning("Ortssuche: %s", err)
                    return self.json({"results": [], "error": "Ortssuche nicht erreichbar"}, 502)
            if u.path.startswith("/api/"):
                return self.json({"error": "unbekannt"}, 404)
            return self.serve_range()

        def do_POST(self) -> None:
            if not self.host_ok() or self.headers.get("X-OSINT") != "1":
                return self.json({"error": "verweigert"}, 403)
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{port_box[0]}", f"http://localhost:{port_box[0]}"}:
                return self.json({"error": "herkunft"}, 403)
            if self.path != "/api/setup":
                return self.json({"error": "unbekannt"}, 404)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
                lat, lon = float(body["lat"]), float(body["lon"])
                from app.tilebuild import validate_center
                validate_center(lat, lon)
            except (ValueError, KeyError, TypeError):
                return self.json({"error": "Mittelpunkt ungültig"}, 400)
            old = app.settings()
            if old and (abs(old["lat"] - lat) > 1e-4 or abs(old["lon"] - lon) > 1e-4):
                return self.json({"error": "Mittelpunkt ist gesetzt. Zum Ändern den Datenordner zurücksetzen."}, 409)
            s = {"lat": round(lat, 5), "lon": round(lon, 5), "name": str(body.get("name", ""))[:80]}
            tmp = app.settings_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
            tmp.replace(app.settings_path)
            app.start(s)
            self.json({"ok": True})

        def serve_range(self) -> None:
            header, path = self.headers.get("Range"), self.translate_path(self.path)
            m = _RANGE.match(header.strip()) if header else None
            if not m or not os.path.isfile(path) or (m.group(1) == "" and m.group(2) == ""):
                return SimpleHTTPRequestHandler.do_GET(self)
            size = os.path.getsize(path)
            if m.group(1) == "":
                start, end = max(0, size - int(m.group(2))), size - 1
            else:
                start, end = int(m.group(1)), min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
            if start >= size or start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                return self.end_headers()
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        def do_HEAD(self) -> None:
            if not self.host_ok():
                return self.json({"error": "host"}, 403)
            super().do_HEAD()
    return H


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--run"] and len(argv) >= 2:   # Kindaufruf im gebündelten Programm: python -m <modul> <args>
        import runpy
        sys.argv = [argv[1], *argv[2:]]
        runpy.run_module(argv[1], run_name="__main__")
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))   # gebündelt: Entpackordner von PyInstaller
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--web-dir", type=Path, default=root / "web")
    ap.add_argument("--pmtiles", type=Path, default=Path("pmtiles"))
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--log-level", default="INFO")
    a = ap.parse_args(argv)
    logging.basicConfig(level=a.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = App(a.data_dir, a.web_dir, a.pmtiles, root)
    box = [0]
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(app, box))
    box[0] = srv.server_address[1]
    s = app.settings()
    if s:
        app.start(s)
    print(f"OSINT_READY port={box[0]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
