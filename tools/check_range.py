#!/usr/bin/env python3
"""Prüft, ob ein Server Teilabrufe (HTTP Range) für eine Datei richtig beantwortet.

Zweck:    Vor dem Upload der Kartendatei klären, ob der Webspace PMTiles ausliefern kann.
          PMTiles liest nur Ausschnitte der Datei; ohne 206-Antworten bleibt die Basiskarte leer.
Aufruf:   python tools/check_range.py URL [--bytes 16]
Beispiel: python tools/check_range.py https://example.de/tiles/region.pmtiles
Ausgang:  0 = in Ordnung, 1 = Problem, 2 = Server nicht erreichbar
Geprüft:  206 mit passendem Content-Range und Content-Length; keine Content-Encoding-Kompression
          (sonst stimmen die Byte-Positionen nicht); Suchbereich in der Mitte der Datei.
"""
from __future__ import annotations

import argparse
import logging
import sys

import httpx

log = logging.getLogger("osint.check_range")
UA = "OSINT-by-CTW/1.0 (range-check)"


def check(url: str, n: int = 16, client: httpx.Client | None = None) -> list[str]:
    """Liefert eine Liste von Problemen; leer heißt in Ordnung."""
    problems: list[str] = []
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA})
    try:
        head = client.get(url, headers={"Range": f"bytes=0-{n - 1}", "Accept-Encoding": "identity"})
        if head.status_code == 200:
            problems.append("Server ignoriert Range (Status 200 statt 206): PMTiles funktioniert so nicht")
            return problems
        if head.status_code != 206:
            problems.append(f"Unerwarteter Status {head.status_code}")
            return problems
        cr = head.headers.get("content-range", "")
        if not cr.startswith(f"bytes 0-{n - 1}/"):
            problems.append(f"Content-Range passt nicht: {cr!r}")
            return problems
        if len(head.content) != n:
            problems.append(f"Erwartet {n} Bytes, erhalten {len(head.content)}")
        if head.headers.get("content-encoding", "identity") not in ("identity", ""):
            problems.append(f"Antwort ist komprimiert ({head.headers['content-encoding']}): Byte-Positionen stimmen nicht")
        total = int(cr.rsplit("/", 1)[1]) if cr.rsplit("/", 1)[1].isdigit() else 0
        if total > 2 * n:
            mid = total // 2
            r = client.get(url, headers={"Range": f"bytes={mid}-{mid + n - 1}", "Accept-Encoding": "identity"})
            if r.status_code != 206 or len(r.content) != n:
                problems.append(f"Bereich aus der Mitte fehlgeschlagen (Status {r.status_code}, {len(r.content)} Bytes)")
        if url.endswith(".pmtiles") and head.content[:7] != b"PMTiles":
            problems.append("Datei beginnt nicht mit der PMTiles-Kennung (falsche Datei oder Proxy-Seite?)")
    finally:
        if own:
            client.close()
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("--bytes", type=int, default=16)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        problems = check(args.url, args.bytes)
    except httpx.HTTPError as exc:
        log.error("Nicht erreichbar: %s", exc)
        return 2
    for p in problems:
        log.error(p)
    if not problems:
        log.info("Teilabrufe funktionieren: %s", args.url)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
