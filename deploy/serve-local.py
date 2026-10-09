#!/usr/bin/env python3
"""Lokaler Webserver mit Teilabrufen (HTTP Range) für die Vorschau, auch für PMTiles.

Zweck:    Ersatz für `python -m http.server`, der keine Range-Anfragen versteht und damit
          Kartenkacheln aus einer .pmtiles-Datei nicht liefern kann.
Aufruf:   python deploy/serve-local.py --dir web --port 8080 [--bind 127.0.0.1]
Beispiel: curl -s -H 'Range: bytes=0-15' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/tiles/region.pmtiles
Hinweis:  Nur für die lokale Ansicht. Der Betrieb läuft auf dem Webspace (Apache).
"""
from __future__ import annotations

import argparse
import functools
import logging
import os
import re
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("osint.serve")
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript", ".json": "application/json", ".geojson": "application/geo+json",
        ".pmtiles": "application/octet-stream", ".css": "text/css", ".html": "text/html; charset=utf-8",
    }

    def end_headers(self) -> None:
        # Vorschau: Browser fragen bei jeder Datei nach (ETag/Last-Modified), sonst hängen sie an altem JavaScript
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # ruhiger als der Standard, keine IP im Log
        log.info("%s", fmt % args)

    def send_head(self):
        header = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not header or not os.path.isfile(path):
            return super().send_head()
        m = _RANGE.match(header.strip())
        size = os.path.getsize(path)
        if not m or (m.group(1) == "" and m.group(2) == ""):
            return super().send_head()  # nicht unterstützte Form: ganze Datei
        if m.group(1) == "":  # letzte n Bytes
            n = int(m.group(2))
            start, end = max(0, size - n), size - 1
        else:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
        if start >= size or start > end:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        f = open(path, "rb")
        f.seek(start)
        self._remaining = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._remaining))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile) -> None:
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)
        self._remaining = None


class _Server(ThreadingHTTPServer):
    # Standard ist eine Warteschlange von 5: Karte, Relief und Kacheln öffnen viele Verbindungen auf einmal, der Rest bekäme "connection reset"
    request_queue_size = 128


def make_server(directory: str, port: int, bind: str = "127.0.0.1") -> ThreadingHTTPServer:
    handler = functools.partial(RangeHandler, directory=directory)
    return _Server((bind, port), handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default="web")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--bind", default="127.0.0.1")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.path.isdir(args.dir):
        log.error("Ordner fehlt: %s", args.dir)
        return 2
    srv = make_server(args.dir, args.port, args.bind)
    log.info("Vorschau auf http://%s:%d (Ordner %s)", args.bind, args.port, args.dir)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
