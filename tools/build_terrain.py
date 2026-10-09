#!/usr/bin/env python3
"""Geländefaktoren für die Windansicht aus den lokalen Höhenkacheln ableiten (einmalig, ändert sich nur mit dem Höhenmodell).

Zweck:      Enge Täler lenken den Wind: Er weht eher entlang der Talachse, quer dazu bremst das Gelände, auf Kuppen und Kämmen ist er schneller.
            Dieses Werkzeug rechnet aus den Terrarium-Kacheln (web/tiles/dem, Zoom 10) für jede Rasterzelle drei Zahlen:
              R  Richtung der Talachse (0 bis 180 Grad, gegen den Uhrzeigersinn ab Ost, 255 = 180 Grad)
              G  Talstärke 0 bis 1 (Höhe unter dem Umland und Gelände in einer Richtung geordnet)
              B  Kammstärke 0 bis 1 (Höhe über dem Umland)
            Ergebnis: web/data/terrain.png (verlustfrei) und web/data/terrain.json (Raster, Verfahren, Quelle). Die Karte rechnet daraus im Browser
            eine Schätzung des Windes im Gelände. Das ist ein einfaches geometrisches Modell, keine Strömungsrechnung und keine Messung.
Verfahren:  Höhe glätten (σ ≈ 400 m), Gradient, Strukturtensor (σ ≈ 800 m) → Richtung der Höhenlinien (= Talachse) und Kohärenz;
            Tiefe = Mittel im Umkreis (σ ≈ 1,5 km) minus Höhe. Täler: Tiefe > 0 und Kohärenz hoch. Kämme: Tiefe < 0.
Aufruf:     python tools/build_terrain.py                 Standard (Zoom 10, Zelle etwa 450 m)
            python tools/build_terrain.py --check         nur Kacheln prüfen
Exit:       0 = geschrieben, 1 = Kacheln fehlen
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import config  # noqa: E402

ZOOM = 10
DLAT, DLON = 0.004, 0.006          # Zellgröße in Grad (rund 450 m)
SIG_SMOOTH_M, SIG_TENSOR_M, SIG_AREA_M = 400.0, 800.0, 1500.0
DEPTH_FULL_M = 80.0                # ab dieser Tiefe unter dem Umland gilt ein Tal als voll ausgeprägt


def tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 2**z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def gauss1d(sig_px: float) -> np.ndarray:
    r = max(1, int(3 * sig_px))
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sig_px) ** 2)
    return k / k.sum()


def gauss(a: np.ndarray, sig_px: float) -> np.ndarray:
    k = gauss1d(sig_px)
    pad = len(k) // 2
    out = np.pad(a, ((0, 0), (pad, pad)), mode="edge")
    out = np.apply_along_axis(lambda r: np.convolve(r, k, mode="valid"), 1, out)
    out = np.pad(out, ((pad, pad), (0, 0)), mode="edge")
    return np.apply_along_axis(lambda c: np.convolve(c, k, mode="valid"), 0, out)


def load_mosaic(dem: Path, z: int, x0: int, x1: int, y0: int, y1: int) -> np.ndarray:
    mos = np.full(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), np.nan, dtype=np.float32)
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            f = dem / str(z) / str(x) / f"{y}.png"
            if not f.exists():
                continue
            rgb = np.asarray(Image.open(f).convert("RGB"), dtype=np.float32)
            mos[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
    return mos


def analyse(h: np.ndarray, m_per_px: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Höhenraster (Zeilen nach Süden) → (Achse in Grad 0–180, Talstärke, Kammstärke), alle im Raster von h."""
    hs = gauss(h, SIG_SMOOTH_M / m_per_px)
    gy_img, gx = np.gradient(hs, m_per_px)       # d/dy_img (nach Süden), d/dx (nach Osten)
    gy = -gy_img                                  # nach Norden
    jxx, jyy, jxy = gauss(gx * gx, SIG_TENSOR_M / m_per_px), gauss(gy * gy, SIG_TENSOR_M / m_per_px), gauss(gx * gy, SIG_TENSOR_M / m_per_px)
    theta_g = 0.5 * np.arctan2(2 * jxy, jxx - jyy)            # Richtung des stärksten Gefälles (Ost = 0, nach Norden positiv)
    axis = (np.degrees(theta_g) + 90.0) % 180.0               # Höhenlinien = Talachse
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy**2) / (jxx + jyy + 1e-9)
    depth = gauss(h, SIG_AREA_M / m_per_px) - hs
    valley = np.clip(depth / DEPTH_FULL_M, 0, 1) * np.clip((coh - 0.3) / 0.5, 0, 1)
    ridge = np.clip(-depth / DEPTH_FULL_M, 0, 1)
    return axis, valley, ridge


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dem", type=Path, default=ROOT / "web" / "tiles" / "dem")
    ap.add_argument("--out", type=Path, default=ROOT / "web" / "data")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    s, w, n, e = config.BBOX
    pad = 0.06   # Rand für die Glättung
    xa, ya = tile_xy(n + pad, w - pad, ZOOM)
    xb, yb = tile_xy(s - pad, e + pad, ZOOM)
    x0, x1, y0, y1 = int(xa), int(xb), int(ya), int(yb)
    missing = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1) if not (a.dem / str(ZOOM) / str(x) / f"{y}.png").exists()]
    print(f"Kacheln Zoom {ZOOM}: x {x0}–{x1}, y {y0}–{y1}, fehlen: {len(missing)}")
    if missing or a.check:
        return 1 if missing else 0
    h = load_mosaic(a.dem, ZOOM, x0, x1, y0, y1)
    h = np.where(np.isnan(h), np.nanmean(h), h)
    lat_mid = (s + n) / 2
    m_per_px = 156543.03392 * math.cos(math.radians(lat_mid)) / 2**ZOOM
    axis, valley, ridge = analyse(h, m_per_px)
    nx, ny = int(round((e - w) / DLON)), int(round((n - s) / DLAT))
    out = np.zeros((ny, nx, 3), dtype=np.uint8)
    # Zellmitte → Pixel im Mosaik (Mercator); je Zeile bleibt das Verhältnis fast gleich, daher direkt abtasten
    lons = w + (np.arange(nx) + 0.5) * DLON
    px = ((lons + 180) / 360 * 2**ZOOM - x0) * 256
    for j in range(ny):
        lat = n - (j + 0.5) * DLAT
        _, ty = tile_xy(lat, 0, ZOOM)
        py = (ty - y0) * 256
        iy = int(np.clip(round(py), 0, h.shape[0] - 1))
        ix = np.clip(np.round(px).astype(int), 0, h.shape[1] - 1)
        out[j, :, 0] = np.round(axis[iy, ix] / 180.0 * 255).astype(np.uint8)
        out[j, :, 1] = np.round(valley[iy, ix] * 255).astype(np.uint8)
        out[j, :, 2] = np.round(ridge[iy, ix] * 255).astype(np.uint8)
    a.out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, "RGB").save(a.out / "terrain.png", optimize=True)
    meta = {"bbox": [w, s, e, n], "nx": nx, "ny": ny, "dlon": DLON, "dlat": DLAT, "zoom": ZOOM,
            "channels": {"r": "Talachse in Grad (0 bis 180, ab Ost gegen den Uhrzeigersinn, 255 = 180)", "g": "Talstärke 0 bis 1", "b": "Kammstärke 0 bis 1"},
            "method": "Strukturtensor und Tiefe unter dem Umland aus dem Höhenmodell; einfaches geometrisches Modell, keine Strömungsrechnung",
            "source": "Höhenmodell: Terrarium-Kacheln (SRTM, EU-DEM), siehe Quellen und Lizenzen"}
    (a.out / "terrain.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"terrain.png {nx}x{ny}; Talzellen > 0,3: {int((out[..., 1] > 76).sum())}, Kammzellen > 0,3: {int((out[..., 2] > 76).sum())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
