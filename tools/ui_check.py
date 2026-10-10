#!/usr/bin/env python3
"""Verhaltensabzug der Lagekarte im Browser: Ebenenmenü, Zeitfenster, Ereignisfilter, Hell/Dunkel, Karte um 1450.

Zweck:     Beweist bei einem Umbau ("ohne Verhaltensänderung"), dass die Seite dasselbe tut wie vorher. Das Werkzeug fährt die Seite
           durch eine feste Abfolge von Bedienschritten und schreibt je Schritt einen Fingerabdruck (Kartenebenen mit Sichtbarkeit,
           Tabellenzeilen, Zählwerte) als JSON. Zwei Läufe (vorher, nachher) lassen sich mit `--diff` vergleichen.
Aufruf:    python tools/ui_check.py --url http://127.0.0.1:8099/ --out /tmp/r5/vorher.json
           python tools/ui_check.py --diff /tmp/r5/vorher.json /tmp/r5/nachher.json
Braucht:   Python-Paket playwright und ein Chromium (PLAYWRIGHT_BROWSERS_PATH oder --chromium PFAD); der Prüfzugang der Seite (#debug).
Hinweis:   Hinweis: Das ist ein Entwicklerwerkzeug, kein Teil des Betriebs. Es sendet nichts nach außen und meldet jede Anfrage, die nicht
           an den geprüften Server ging.
Ausgang:   0 bei Erfolg (bei --diff: 0 = gleich, 1 = Unterschiede).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

FILTER_STEPS = [
    ("sev1", "#ev-tools .ev-chip[data-sev='1']"),
    ("sev2", "#ev-tools .ev-chip[data-sev='2']"),
    ("sev0", "#ev-tools .ev-chip[data-sev='0']"),
]


def sha(o) -> str:
    return hashlib.sha1(json.dumps(o, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


class Page:
    def __init__(self, pg):
        self.pg = pg

    def dbg(self, cmd: dict, timeout: int = 20000) -> dict:
        self.pg.evaluate("(c) => { document.documentElement.dataset.debugOut = ''; document.documentElement.dataset.debugIn = JSON.stringify(c); document.dispatchEvent(new Event('osint-debug')); }", cmd)
        self.pg.wait_for_function("() => document.documentElement.dataset.debugOut", timeout=timeout)
        return json.loads(self.pg.evaluate("() => document.documentElement.dataset.debugOut"))

    def layers(self) -> dict:
        ids = self.dbg({"order": "."})["order"].split(",")
        vis = self.dbg({"vis": ids})
        return {i: vis.get(f"vis:{i}") for i in ids}

    def fingerprint(self) -> dict:
        lay = self.layers()
        rows = self.pg.locator("#ev-list tbody tr").count()
        count = self.pg.evaluate("() => document.querySelector('#count')?.textContent ?? ''")
        shown = {k: v for k, v in lay.items() if v != "none"}
        return {"layers": len(lay), "visible": len(shown), "layer_hash": sha(lay), "visible_ids": sorted(shown)[:0], "rows": rows, "count": count}


def run(url: str, chromium: str | None) -> dict:
    from playwright.sync_api import sync_playwright

    host = urlparse(url).netloc
    out: dict = {"url": url, "steps": {}, "console_errors": [], "external": []}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium, args=["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        pg.on("console", lambda m: out["console_errors"].append(m.text[:200]) if m.type == "error" else None)
        pg.on("pageerror", lambda e: out["console_errors"].append(f"pageerror: {str(e)[:200]}"))
        pg.on("request", lambda r: out["external"].append(r.url[:120]) if urlparse(r.url).netloc not in (host, "") and not r.url.startswith(("blob:", "data:")) else None)
        pg.goto(url.rstrip("#") + "#debug", wait_until="load")
        pg.wait_for_function("() => document.querySelector('#count')?.textContent.includes('Ereignisse')", timeout=60000)
        pg.wait_for_timeout(2500)
        P = Page(pg)
        out["steps"]["start"] = P.fingerprint()
        out["layer_inputs"] = pg.evaluate("() => [...document.querySelectorAll('input[data-layer]')].map(i => [i.dataset.layer, i.checked])")
        out["groups"] = pg.evaluate("() => [...document.querySelectorAll('.layer-group')].map(g => [g.querySelector('summary span')?.textContent.trim(), g.querySelectorAll('input[data-layer]').length])")
        out["tabs"] = pg.evaluate("() => [...document.querySelectorAll('[role=tab]')].map(t => t.id)")

        # Zeitfenster
        for w in ("24h", "7d", "now"):
            pg.evaluate("(w) => document.querySelector(`input[name='within'][value='${w}']`).click()", w)
            pg.wait_for_timeout(400)
            out["steps"][f"within_{w}"] = P.fingerprint()

        # Ebenenschalter einzeln: ein, Fingerabdruck, aus
        names = [n for n, _ in out["layer_inputs"] if n != "medieval"]
        for n in names:
            pg.evaluate("(n) => document.querySelector(`input[data-layer='${n}']`).click()", n)
            pg.wait_for_timeout(120)
            out["steps"][f"toggle_{n}"] = P.fingerprint()
            pg.evaluate("(n) => document.querySelector(`input[data-layer='${n}']`).click()", n)
            pg.wait_for_timeout(120)
        out["steps"]["toggles_restored"] = P.fingerprint()

        # Themenschalter
        for i in range(len(out["groups"])):
            pg.evaluate("(i) => document.querySelectorAll('.group-toggle')[i].click()", i)
            pg.wait_for_timeout(150)
            out["steps"][f"group_{i}_toggle"] = P.fingerprint()
            pg.evaluate("(i) => document.querySelectorAll('.group-toggle')[i].click()", i)
            pg.wait_for_timeout(150)

        # Ereignisfilter
        pg.evaluate("() => document.querySelector(\"input[data-layer='traffic']\") && (document.querySelector(\"input[data-layer='traffic']\").checked || document.querySelector(\"input[data-layer='traffic']\").click())")
        pg.evaluate("() => { for (const n of ['warning','flood']) { const c = document.querySelector(`input[data-layer='${n}']`); if (c && !c.checked) c.click(); } }")
        pg.wait_for_timeout(300)
        out["steps"]["filter_base"] = P.fingerprint()
        for name, sel in FILTER_STEPS:
            pg.evaluate("(s) => document.querySelector(s)?.click()", sel)
            pg.wait_for_timeout(200)
            out["steps"][f"filter_{name}"] = P.fingerprint()
        pg.evaluate("() => { const q = document.querySelector('#ev-q'); q.value = 'Stau'; q.dispatchEvent(new Event('input', { bubbles: true })); }")
        pg.wait_for_timeout(200)
        out["steps"]["filter_q_stau"] = P.fingerprint()
        pg.evaluate("() => document.querySelector('#ev-reset')?.click()")
        pg.wait_for_timeout(200)
        out["steps"]["filter_reset"] = P.fingerprint()

        # Reiter
        for t in out["tabs"]:
            pg.evaluate("(t) => document.getElementById(t).click()", t)
            pg.wait_for_timeout(150)
            # Zahlen im Text (Alter in Minuten, Uhrzeiten) ändern sich mit der Zeit: Form des Textes vergleichen, nicht die Ziffern
            out["steps"][f"tab_{t}"] = {"text_shape": pg.evaluate("(t) => { const p = document.getElementById(document.getElementById(t).getAttribute('aria-controls')); const s = p.textContent.replace(/\\d+/g, '#'); return [s.length, s.split('').reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7)]; }", t),
                                        "hidden": pg.evaluate("(t) => [...document.querySelectorAll('.panel')].filter(p => !p.hidden).map(p => p.id)", t)}

        # Hell und Dunkel, Karte um 1450
        pg.evaluate("() => document.getElementById('theme')?.click()")
        pg.wait_for_timeout(2500)
        out["steps"]["theme_dark"] = {**P.fingerprint(), "ansicht": pg.evaluate("() => document.documentElement.dataset.ansicht")}
        pg.evaluate("() => document.getElementById('theme')?.click()")
        pg.wait_for_timeout(2500)
        out["steps"]["theme_back"] = {**P.fingerprint(), "ansicht": pg.evaluate("() => document.documentElement.dataset.ansicht")}
        pg.evaluate("() => document.querySelector(\"input[data-layer='medieval']\")?.click()")
        pg.wait_for_timeout(3500)
        out["steps"]["medieval_on"] = {**P.fingerprint(), "karte": pg.evaluate("() => document.documentElement.dataset.karte"), "windrose": pg.evaluate("() => !!document.getElementById('windrose') && !document.getElementById('windrose').hasAttribute('hidden')")}
        pg.evaluate("() => document.querySelector(\"input[data-layer='medieval']\")?.click()")
        pg.wait_for_timeout(3000)
        out["steps"]["medieval_off"] = {**P.fingerprint(), "karte": pg.evaluate("() => document.documentElement.dataset.karte")}
        b.close()
    import re
    out["console_errors"] = sorted({re.sub(r"https?://[\w.:-]+", "HOST", e) for e in out["console_errors"]})
    out["external"] = sorted(set(out["external"]))
    return out


def diff(a: dict, b: dict) -> int:
    bad = 0
    for k in sorted(set(a["steps"]) | set(b["steps"])):
        x, y = a["steps"].get(k), b["steps"].get(k)
        if x != y:
            bad += 1
            print(f"UNTERSCHIED {k}:\n  vorher  {x}\n  nachher {y}")
    for key in ("layer_inputs", "groups", "tabs", "external"):
        if a.get(key) != b.get(key):
            bad += 1
            print(f"UNTERSCHIED {key}:\n  vorher  {a.get(key)}\n  nachher {b.get(key)}")
    if a["console_errors"] != b["console_errors"]:
        bad += 1
        print(f"UNTERSCHIED Konsolenfehler:\n  vorher  {a['console_errors']}\n  nachher {b['console_errors']}")
    print(f"{len(a['steps'])} Schritte verglichen, {bad} Unterschiede")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--chromium", default=None)
    ap.add_argument("--diff", nargs=2, type=Path)
    a = ap.parse_args(argv)
    if a.diff:
        return diff(json.loads(a.diff[0].read_text()), json.loads(a.diff[1].read_text()))
    if not a.url:
        ap.error("--url fehlt")
    res = run(a.url, a.chromium)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(f"{len(res['steps'])} Schritte, Konsolenfehler: {res['console_errors']}, fremde Anfragen: {res['external']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
