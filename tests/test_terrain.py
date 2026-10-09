"""Geländefaktoren: Talachse und Stärke an einem künstlichen Tal (Höhenmodell synthetisch, Verfahren aus tools/build_terrain.py)."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("build_terrain", Path(__file__).resolve().parent.parent / "tools" / "build_terrain.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)  # type: ignore[union-attr]


def _valley(angle_deg: float, m_per_px: float = 100.0, n: int = 300) -> np.ndarray:
    """Tal mit Sohle auf der Linie durch die Mitte, Richtung angle_deg (ab Ost gegen den Uhrzeigersinn), Wände steigen 300 m auf 2 km."""
    y, x = np.mgrid[0:n, 0:n].astype(float)
    x = (x - n / 2) * m_per_px
    y = -(y - n / 2) * m_per_px          # Nord oben
    a = math.radians(angle_deg)
    across = -x * math.sin(a) + y * math.cos(a)
    return (np.minimum(np.abs(across), 2000.0) * 0.15 + 200.0).astype(np.float32)


def test_valley_axis_and_strength_for_northeast_valley():
    axis, valley, ridge = bt.analyse(_valley(45.0), 100.0)
    c = (150, 150)
    assert abs(axis[c] - 45.0) < 6.0
    assert valley[c] > 0.5 and ridge[c] < 0.05


def test_flat_land_has_no_effect():
    axis, valley, ridge = bt.analyse(np.full((200, 200), 300.0, dtype=np.float32), 100.0)
    assert valley.max() < 0.01 and ridge.max() < 0.01
