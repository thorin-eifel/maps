"""Tests für tools/build_vignette.py: UTM-Rechnung, Abstandsmaske entlang der Landesgrenze, erzeugte Dateien."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("build_vignette", ROOT / "tools" / "build_vignette.py")
bv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bv)
from app import geo  # noqa: E402


def test_utm32_rechnet_wie_die_umkehrung():
    for lon, lat in [(6.456, 49.846), (4.2, 51.0), (8.9, 48.3), (7.5, 50.4)]:
        x, y = bv.utm32(np.array([lon]), np.array([lat]))
        la, lo = geo.utm32_to_wgs84(float(x[0]), float(y[0]))
        assert abs(lo - lon) < 1e-6 and abs(la - lat) < 1e-6


def test_smoothstep_ist_monoton_und_begrenzt():
    t = np.linspace(-1, 2, 50)
    s = bv.smoothstep(t)
    assert s.min() == 0 and s.max() == 1 and np.all(np.diff(s) >= 0)


def test_maske_klar_innen_schwarz_aussen_und_form_folgt_der_grenze():
    meta = json.loads((ROOT / "web/geo/vignette.json").read_text(encoding="utf-8"))
    a = np.array(Image.open(ROOT / "web/geo/vignette.png"))[:, :, 1].astype(float) / 255
    assert a.shape == (meta["hoehe"], meta["breite"])
    assert a[0].min() == 1 and a[-1].min() == 1 and a[:, 0].min() == 1 and a[:, -1].min() == 1   # Rand voll schwarz
    x0, y0, x1, y1 = meta["mercator"]

    def alpha_at(lon: float, lat: float) -> float:
        mx, my = bv.lonlat_to_merc(lon, lat)
        ix = int((mx - x0) / (x1 - x0) * meta["breite"])
        iy = int((y1 - my) / (y1 - y0) * meta["hoehe"])
        return float(a[iy, ix])

    assert alpha_at(7.3, 49.9) == 0.0          # Mitte von Rheinland-Pfalz
    assert alpha_at(6.45, 49.85) == 0.0        # Irrel
    assert alpha_at(8.2, 49.2) == 0.0          # Pfalz, weit im Südosten: mit einem Kreis um Irrel schon dunkel
    assert alpha_at(4.3, 49.0) > 0.99          # weit im Westen (Frankreich/Belgien)
    # Entlang der Grenze: im Osten (Rhein bei Mainz) reicht das Klare viel weiter als im Westen bei gleichem Abstand zu Irrel
    assert alpha_at(9.6, 50.0) < 0.5
