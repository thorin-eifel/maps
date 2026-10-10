#!/usr/bin/env python3
"""Messung der Bildrate und Ladelast an festen Messpunkten (Mainz, Trier, Kaiserslautern, Saarbrücken, Frankfurt, Luxemburg) und der Gesamtansicht.

Zweck:    Belegt die Abnahme von R5 (Bildrate beim Schwenken, Startzeit, geladene Zellen). Nutzt den Prüfzugang der Seite (#debug, Befehle zellen und perf).
Aufruf:   python tools/perf_messung.py --url http://127.0.0.1:8099/ --out perf.json [--chromium PFAD] [--frames 40] [--gpu]
Hinweis:  Die Zahlen gelten nur für die Maschine, auf der gemessen wird. In einer Umgebung ohne GPU (Software-Rendering) sind sie
          nicht mit der Referenzmaschine vergleichbar. Entwicklerwerkzeug, sendet nichts nach außen.
Braucht:  Python-Paket playwright und ein Chromium; tools/ui_check.py im selben Ordner.
"""
import argparse
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from playwright.sync_api import sync_playwright
from ui_check import Page
POINTS = [('Mainz', 8.271, 50.000), ('Trier', 6.637, 49.750), ('Kaiserslautern', 7.769, 49.444), ('Saarbrücken', 6.996, 49.234), ('Frankfurt', 8.682, 50.110), ('Luxemburg', 6.130, 49.611)]
ap = argparse.ArgumentParser(); ap.add_argument('--url', required=True); ap.add_argument('--out', default='perf.json'); ap.add_argument('--chromium', default=None); ap.add_argument('--frames', type=int, default=40); ap.add_argument('--gpu', action='store_true', help='echte GPU nutzen (Fenster sichtbar, kein Software-Rendering)')
A = ap.parse_args()
out = {'punkte': [], 'region': None}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=A.chromium, headless=not A.gpu, args=["--ignore-gpu-blocklist"] if A.gpu else ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    out["gpu"] = A.gpu
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    t0 = time.time()
    pg.goto(A.url.rstrip('#') + '#debug', wait_until='load')
    pg.wait_for_function("() => document.querySelector('#count')?.textContent.includes('Ereignisse')", timeout=60000)
    out['start_s'] = round(time.time() - t0, 1)
    P = Page(pg)
    def measure(name, lon, lat, z):
        t = time.time()
        r = P.dbg({"jump": [lon, lat, z], "zellen": True, "perf": {"frames": A.frames}}, timeout=240000)
        zz = r['zellen']; pf = r['perf']['alle']
        row = {'ort': name, 'zoom': z, 'bild_ms_mittel': pf['mean'], 'bild_ms_p95': pf['p95'], 'dateien': zz['ok'], 'zellen': zz['cells'], 'kb': round(zz['bytes'] / 1024), 'ereignisse': zz['events'], 'band': zz['band']}
        print(row, flush=True); return row
    for name, lon, lat in POINTS:
        for z in (8, 12, 15):
            out['punkte'].append(measure(name, lon, lat, z))
    out['region'] = measure('Region (ganz)', 7.3, 49.9, 7.6)
    b.close()
json.dump(out, open(A.out, 'w'), ensure_ascii=False, indent=1)
