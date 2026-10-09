"""CAP-Schweregrade auf unser Vierer-Schema abbilden (gilt für NINA und DWD).

Minor → notice (gelb), Moderate → warning (orange), Severe/Extreme → critical (rot).
Rot heißt rot: `critical` wird nur bei Severe/Extreme vergeben.
"""
from __future__ import annotations

_MAP = {"minor": "notice", "moderate": "warning", "severe": "critical", "extreme": "critical"}


def cap_to_severity(value: str | None) -> str:
    return _MAP.get((value or "").strip().lower(), "info")
