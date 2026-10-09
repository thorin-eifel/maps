"""Zentrale Konfiguration.

Zweck:      Räumlicher Zuschnitt, Pfade und Betriebsparameter an einer Stelle.
Parameter:  Umgebungsvariablen (siehe .env.example), alle optional.
Beispiel:   OSINT_DB_PATH=./data/osint.sqlite python -m app.collect --once
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Räumlicher Zuschnitt (Projektanweisung Abschnitt 1)
# Mittelpunkt des Radius: Firmensitz CTW in Irrel (Wert vom Betreiber vorgegeben), vorher Ortsmitte 49.850 / 6.450.
# Das Lagebild gilt der Region, nicht dem Ort: 120 km, mehr wird es nicht (Entscheidung des Betreibers).
# Die Desktop-App setzt den Mittelpunkt bei der Ersteinrichtung über OSINT_CENTER_LAT/-LON (Radius bleibt 120 km).
CENTER_LAT = float(os.environ.get("OSINT_CENTER_LAT", 49.84615562322509))
CENTER_LON = float(os.environ.get("OSINT_CENTER_LON", 6.456057281843173))
RADIUS_KM = 120.0


def _bbox(lat: float, lon: float, km: float) -> tuple[float, float, float, float]:
    """Umschließender Kasten (lat_min, lon_min, lat_max, lon_max) um den Kreis, nach außen auf 0,01° gerundet."""
    dlat = km / 111.195
    dlon = km / (111.195 * math.cos(math.radians(lat)))
    return (math.floor((lat - dlat) * 100) / 100, math.floor((lon - dlon) * 100) / 100,
            math.ceil((lat + dlat) * 100) / 100, math.ceil((lon + dlon) * 100) / 100)


# Grober Vorfilter; der Feinfilter ist die Distanzberechnung in app.geo
BBOX = _bbox(CENTER_LAT, CENTER_LON, RADIUS_KM)  # (lat_min, lon_min, lat_max, lon_max)

def load_dotenv(path: Path | None = None) -> int:
    """Liest KEY=VALUE-Zeilen aus .env in die Umgebung. Bereits gesetzte Variablen gewinnen (Shell schlägt Datei).

    Kein Ersatz für einen Secret-Store, nur die Datei, die .env.example beschreibt. Werte werden nie geloggt.
    Rückgabe: Anzahl neu gesetzter Variablen."""
    path = path or BASE_DIR / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    n = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value
            n += 1
    return n


if not os.environ.get("OSINT_NO_DOTENV"):
    load_dotenv()

CONTACT = os.environ.get("OSINT_CONTACT", "kontakt@example.invalid")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    sources_path: Path
    web_dir: Path
    user_agent: str
    http_timeout_s: float
    http_max_attempts: int
    breaker_threshold: int
    breaker_cooldown_s: int
    retention_days: int

    @classmethod
    def from_env(cls) -> "Settings":
        contact = os.environ.get("OSINT_CONTACT", CONTACT)
        return cls(
            db_path=Path(os.environ.get("OSINT_DB_PATH", BASE_DIR / "data" / "osint.sqlite")),
            sources_path=Path(os.environ.get("OSINT_SOURCES", BASE_DIR / "sources.yaml")),
            web_dir=Path(os.environ.get("OSINT_WEB_DIR", BASE_DIR / "web")),
            user_agent=f"OSINT-by-CTW/1.0 (+{contact})",
            http_timeout_s=float(os.environ.get("OSINT_HTTP_TIMEOUT", "20")),
            http_max_attempts=int(os.environ.get("OSINT_HTTP_ATTEMPTS", "3")),
            breaker_threshold=int(os.environ.get("OSINT_BREAKER_THRESHOLD", "5")),
            breaker_cooldown_s=int(os.environ.get("OSINT_BREAKER_COOLDOWN", "900")),
            retention_days=int(os.environ.get("OSINT_RETENTION_DAYS", "30")),
        )
