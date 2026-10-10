#!/usr/bin/env python3
"""Vignette entlang der Landesgrenze bauen: web/geo/vignette.png und vignette.json.

Zweck:      Die schwarze Vignette der Lagekarte folgt der Landesgrenze von Rheinland-Pfalz statt einem Kreis: bis --abstand-km
            außerhalb der Grenze bleibt die Karte klar, danach steigt die Deckkraft über --fade-km stufenlos (Smoothstep) auf Schwarz.
            Das Werkzeug rechnet dafür den Abstand jedes Bildpunkts zur Landesgrenze und schreibt ihn als Graustufen-PNG mit Alpha
            (Alpha = Deckkraft des Schwarz). Die Seite legt das PNG als Bildquelle über die Karte und liest daraus auch die
            Ausblendung für Wind und Regenwellen (js/lage/vignette.js).
Quelle:     web/geo/rlp.geojson (Landesgrenze aus BKG VG250, dl-de/by-2-0, tools/build_landesgrenze.py).
Rechnung:   Abstände in UTM 32N (EPSG:25832) in Metern, Bildpunkte gleichmäßig in Web-Mercator (wie MapLibre eine Bildquelle legt).
            Die Maßstabsabweichung von UTM 32 liegt in der Region unter 0,2 Prozent, bei 80 km also unter 160 m.
Aufruf:     python tools/build_vignette.py                       schreibt web/geo/vignette.png + vignette.json
            python tools/build_vignette.py --px-m 1000           feiner (Standard 1500 m Mercator-Meter je Bildpunkt)
Abhängig:   numpy, shapely, pillow
Exit:       0 = geschrieben
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from shapely import distance, points
from shapely.geometry import MultiPolygon, Polygon

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("build_vignette")

# WGS84
A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)
K0, LON0, FE = 0.9996, 9.0, 500000.0           # UTM 32N
R_MERC = 6378137.0


def utm32(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """WGS84 lon/lat (Grad) → UTM 32N (Krüger-Reihe, auf Millimeter genau in der Region)."""
    n = F / (2 - F)
    a_ = A / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    alpha = [n / 2 - 2 * n**2 / 3 + 5 * n**3 / 16, 13 * n**2 / 48 - 3 * n**3 / 5, 61 * n**3 / 240]
    phi, dl = np.radians(lat), np.radians(lon - LON0)
    t = np.sinh(np.arctanh(np.sin(phi)) - 2 * math.sqrt(n) / (1 + n) * np.arctanh(2 * math.sqrt(n) / (1 + n) * np.sin(phi)))
    xi = np.arctan2(t, np.cos(dl))
    eta = np.arctanh(np.sin(dl) / np.sqrt(1 + t**2))
    x = FE + K0 * a_ * (eta + sum(alpha[j] * np.cos(2 * (j + 1) * xi) * np.sinh(2 * (j + 1) * eta) for j in range(3)))
    y = K0 * a_ * (xi + sum(alpha[j] * np.sin(2 * (j + 1) * xi) * np.cosh(2 * (j + 1) * eta) for j in range(3)))
    return x, y


def merc_to_lonlat(mx: np.ndarray, my: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.degrees(mx / R_MERC), np.degrees(2 * np.arctan(np.exp(my / R_MERC)) - math.pi / 2)


def lonlat_to_merc(lon: float, lat: float) -> tuple[float, float]:
    return R_MERC * math.radians(lon), R_MERC * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def landesgrenze(path: Path) -> MultiPolygon:
    gj = json.loads(path.read_text(encoding="utf-8"))
    geom = gj["features"][0]["geometry"]
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    out = []
    for rings in polys:
        ex = np.array(rings[0])
        x, y = utm32(ex[:, 0], ex[:, 1])
        holes = []
        for r in rings[1:]:
            h = np.array(r)
            hx, hy = utm32(h[:, 0], h[:, 1])
            holes.append(list(zip(hx, hy)))
        out.append(Polygon(list(zip(x, y)), holes))
    return MultiPolygon(out)


def smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geojson", type=Path, default=ROOT / "web/geo/rlp.geojson")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "web/geo")
    ap.add_argument("--abstand-km", type=float, default=80.0, help="klar bis so weit außerhalb der Landesgrenze")
    ap.add_argument("--fade-km", type=float, default=30.0, help="danach so weit bis volles Schwarz")
    ap.add_argument("--px-m", type=float, default=1500.0, help="Bildpunkt in Mercator-Metern (am Boden ca. 0,65 davon)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    poly = landesgrenze(args.geojson).simplify(200.0)   # 200 m genügen bei 1,5 km Bildpunkt
    geom = json.loads(args.geojson.read_text(encoding="utf-8"))["features"][0]["geometry"]
    teile = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    coords = np.array([p for rings in teile for p in rings[0]])
    lon_min, lat_min = coords.min(axis=0)
    lon_max, lat_max = coords.max(axis=0)
    rand_m = (args.abstand_km + args.fade_km + 20.0) * 1000 * 1.7   # Mercator-Meter mit Reserve (bis 1,7 fach bei 52° N)
    w0, s0 = lonlat_to_merc(lon_min, lat_min)
    e0, n0 = lonlat_to_merc(lon_max, lat_max)
    x0, y0, x1, y1 = w0 - rand_m, s0 - rand_m, e0 + rand_m, n0 + rand_m
    wpx, hpx = int(math.ceil((x1 - x0) / args.px_m)), int(math.ceil((y1 - y0) / args.px_m))
    x1, y1 = x0 + wpx * args.px_m, y0 + hpx * args.px_m
    log.info("Bild %d x %d Bildpunkte", wpx, hpx)

    mx = x0 + (np.arange(wpx) + 0.5) * args.px_m
    my = y1 - (np.arange(hpx) + 0.5) * args.px_m                     # Zeile 0 = Norden
    gx, gy = np.meshgrid(mx, my)
    lon, lat = merc_to_lonlat(gx.ravel(), gy.ravel())
    ux, uy = utm32(lon, lat)
    d_km = distance(points(ux, uy), poly) / 1000.0                   # 0 innerhalb der Fläche
    d_km = d_km.reshape(hpx, wpx)
    alpha = smoothstep((d_km - args.abstand_km) / args.fade_km)
    # Rand: überall volles Schwarz, damit die Fläche außerhalb des Bildes nahtlos anschließt
    alpha[0, :] = alpha[-1, :] = 1.0
    alpha[:, 0] = alpha[:, -1] = 1.0
    a8 = np.round(alpha * 255).astype(np.uint8)
    img = Image.merge("LA", (Image.fromarray(np.zeros_like(a8), "L"), Image.fromarray(a8, "L")))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    png = args.out_dir / "vignette.png"
    img.save(png, optimize=True)
    w, s = merc_to_lonlat(np.array([x0]), np.array([y0]))
    e, n = merc_to_lonlat(np.array([x1]), np.array([y1]))
    meta = {
        "bild": "vignette.png", "breite": wpx, "hoehe": hpx,
        "mercator": [x0, y0, x1, y1],
        "ecken": [[float(w[0]), float(n[0])], [float(e[0]), float(n[0])], [float(e[0]), float(s[0])], [float(w[0]), float(s[0])]],   # oben links, oben rechts, unten rechts, unten links
        "abstand_km": args.abstand_km, "fade_km": args.fade_km,
        "quelle": "Landesgrenze Rheinland-Pfalz, BKG VG250, dl-de/by-2-0 (web/geo/rlp.geojson)",
        "erzeugt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    (args.out_dir / "vignette.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("%s: %.1f KB, klar bis %.0f km, Schwarz ab %.0f km", png, png.stat().st_size / 1e3, args.abstand_km, args.abstand_km + args.fade_km)
    return 0


if __name__ == "__main__":
    sys.exit(main())
