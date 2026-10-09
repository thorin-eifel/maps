"""Zentrale Konfiguration.

Zweck:      Räumlicher Zuschnitt, Pfade und Betriebsparameter an einer Stelle.
Parameter:  Umgebungsvariablen (siehe .env.example), alle optional.
Beispiel:   OSINT_DB_PATH=./data/osint.sqlite python -m app.collect --once
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

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

# Räumlicher Zuschnitt kommt aus region.yaml (app/region.py), nicht mehr aus Konstanten. Erst nach .env laden,
# damit OSINT_REGION und OSINT_CENTER_* aus der Datei wirken.
# CENTER_* ist der Bezugspunkt für Entfernungsangaben (Irrel), BBOX der Kasten der Region (grober Vorfilter,
# Reihenfolge lat_min, lon_min, lat_max, lon_max). QUERY_* ist ein Kreis, der die Region umschließt, für Quellen,
# die nur "Mittelpunkt plus Radius" können. Ob ein Punkt wirklich in der Region liegt, entscheidet geo.in_region().
from .region import REGION  # noqa: E402

CENTER_LAT = REGION.ref_lat
CENTER_LON = REGION.ref_lon
BBOX = REGION.bbox
QUERY_LAT, QUERY_LON, QUERY_RADIUS_KM = REGION.query_lat, REGION.query_lon, REGION.query_radius_km

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
            user_agent=f"WasIstLosBeiUns/1.0 (+{contact})",
            http_timeout_s=float(os.environ.get("OSINT_HTTP_TIMEOUT", "20")),
            http_max_attempts=int(os.environ.get("OSINT_HTTP_ATTEMPTS", "3")),
            breaker_threshold=int(os.environ.get("OSINT_BREAKER_THRESHOLD", "5")),
            breaker_cooldown_s=int(os.environ.get("OSINT_BREAKER_COOLDOWN", "900")),
            retention_days=int(os.environ.get("OSINT_RETENTION_DAYS", "30")),
        )
