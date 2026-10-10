#!/usr/bin/env python3
"""Welche Autobahnen der Autobahn-API berühren die Region? (Grundlage für params.roads in sources.yaml)

Zweck:    Der Sammler fragt je Autobahn drei Dienste ab. Diese Liste muss zur Fläche passen, ohne dass 100 Strecken
          bundesweit abgefragt werden. Das Werkzeug holt einmal alle Strecken und alle drei Dienste und zählt Meldungen in der Region.
Aufruf:   OSINT_REGION=region-rlp.yaml python tools/check_autobahn_roads.py [--pause 0.4] [--out liste.json]
Ausgabe:  je Strecke Zahl der Meldungen in der Region, danach eine fertige YAML-Zeile. Strecken ohne Meldung zum Zeitpunkt des
          Laufs erscheinen nicht; die Liste in sources.yaml ergänzt sie um bekannte Strecken (siehe docs/rlp/r3-datenpipeline.md).
Höflich:  ein Abruf alle 0,4 s, ehrlicher User-Agent. Lauf dauert bei rund 120 Strecken etwa zwei Minuten.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, geo  # noqa: E402

BASE = "https://verkehr.autobahn.de/o/autobahn"
SERVICES = ("roadworks", "warning", "closure")


def points(item: dict) -> list[tuple[float, float]]:
    out = []
    c = item.get("coordinate") or {}
    try:
        out.append((float(c["lat"]), float(c["long"])))
    except (KeyError, TypeError, ValueError):
        pass
    for seg in (item.get("geometry") or {}).get("coordinates") or []:
        try:
            out.append((float(seg[1]), float(seg[0])))
        except (IndexError, TypeError, ValueError):
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pause", type=float, default=0.4)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", nargs="*", help="nur diese Strecken (zum Wiederaufsetzen)")
    a = ap.parse_args()
    hits: Counter[str] = Counter()
    seen = 0
    with httpx.Client(headers={"User-Agent": f"Landblick/1.0 (+{config.CONTACT}) road list"}, timeout=30) as c:
        roads = a.only or c.get(BASE).json()["roads"]
        for road in roads:
            for svc in SERVICES:
                time.sleep(a.pause)
                try:
                    data = c.get(f"{BASE}/{road}/services/{svc}").json()
                except (httpx.HTTPError, ValueError) as exc:
                    print(f"{road}/{svc}: {exc}", file=sys.stderr)
                    continue
                for item in data.get(svc) or []:
                    seen += 1
                    if any(geo.in_region(lat, lon) for lat, lon in points(item)):
                        hits[road] += 1
    print(f"{len(roads)} Strecken, {seen} Meldungen bundesweit, {sum(hits.values())} in der Region")
    for road, n in sorted(hits.items(), key=lambda t: (len(t[0]), t[0])):
        print(f"{road:8} {n}")
    print("roads: [" + ", ".join(sorted(hits, key=lambda r: (len(r), r))) + "]")
    if a.out:
        a.out.write_text(json.dumps(dict(hits), indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
