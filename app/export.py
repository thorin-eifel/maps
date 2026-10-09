"""Statischer Export: schreibt die JSON-Dateien, die das Frontend auf dem Webspace liest.

Zweck:      Der Webspace (IONOS) führt kein Python aus. Der Collector läuft auf einem Rechner des Betreibers,
            dieser Export macht aus der Datenbank kleine JSON-Dateien, ein Upload (deploy/publish.sh)
            bringt sie auf den Webspace.
Parameter:  --out PFAD   Zielordner (Standard web/data)
            --db PFAD    Datenbank (Standard $OSINT_DB_PATH oder data/osint.sqlite)
Beispiel:   python -m app.export --out web/data
Dateien:    meta.json events.json aircraft.json gewaesser.json wetter.json umwelt.json indizes.json kraftstoff.json themen.json radar.json radar.png blitz.json blitz.png wind.json haltestellen.json landmarks.json infrastruktur.json routen.json anbau.json sakral.json suche.json status.json sources.json
Schreiben:  je Datei erst *.tmp, dann Umbenennen — kein halbes JSON im Zielordner.
Datenschutz: Die Dateien enthalten nur Ereignisse, Messwerte und Quellenstatus.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from . import payloads
from .config import Settings
from .db import Storage
from .registry import Registry

log = logging.getLogger("osint.export")


def build_all(storage: Storage, registry: Registry) -> dict[str, Any]:
    radar_meta, radar_png = payloads.radar_payload(storage, registry)
    blitz_meta, blitz_png = payloads.blitz_payload(storage, registry)
    files: dict[str, Any] = {
        "meta.json": payloads.meta_payload(storage),
        "events.json": payloads.events_payload(storage, registry, within="7d", exclude_types=("aircraft",)),  # Obermenge; Fenster rechnet das Frontend
        "aircraft.json": payloads.aircraft_payload(storage, registry),
        "gewaesser.json": payloads.gewaesser_payload(storage, registry, series_step=4),  # stündlich statt viertelstündlich
        "wetter.json": payloads.wetter_payload(storage, registry),
        "umwelt.json": payloads.umwelt_payload(storage, registry),
        "indizes.json": payloads.indizes_payload(storage, registry),
        "kraftstoff.json": payloads.kraftstoff_payload(storage, registry),
        "themen.json": payloads.themen_payload(storage, registry),
        "radar.json": radar_meta,
        "blitz.json": blitz_meta,
        "wind.json": payloads.wind_payload(storage, registry),
        "haltestellen.json": payloads.haltestellen_payload(storage, registry),
        "landmarks.json": payloads.landmarks_payload(storage, registry),
        "infrastruktur.json": payloads.infrastruktur_payload(storage, registry),
        "routen.json": payloads.routen_payload(storage, registry),
        "anbau.json": payloads.anbau_payload(storage, registry),
        "sakral.json": payloads.sakral_payload(storage, registry),
        "suche.json": payloads.suche_payload(storage, registry),
        "status.json": payloads.status_payload(storage, registry),
        "sources.json": payloads.sources_payload(registry),
    }
    if radar_png:
        files["radar.png"] = radar_png  # Bytes, kein JSON
    if blitz_png:
        files["blitz.png"] = blitz_png
    return files


def build_live(storage: Storage, registry: Registry) -> dict[str, Any]:
    """Nur, was sich im Sekundentakt ändert: Luftverkehr und der Quellenstatus (damit „veraltet“ stimmt)."""
    return {
        "aircraft.json": payloads.aircraft_payload(storage, registry),
        "status.json": payloads.status_payload(storage, registry),
    }


def write_all(files: dict[str, Any], out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for name, data in files.items():
        target = out / name
        tmp = out / f".{name}.tmp"
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        tmp.write_bytes(raw)
        os.replace(tmp, target)
        sizes[name] = len(raw)
    return sizes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    settings = Settings.from_env()
    ap.add_argument("--out", default=str(settings.web_dir / "data"))
    ap.add_argument("--db", default=str(settings.db_path))
    args = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Path(args.db)
    if not db.exists():
        log.error("Datenbank nicht gefunden: %s (erst `python -m app.collect --once` laufen lassen)", db)
        return 1
    storage = Storage(db, readonly=True)
    try:
        sizes = write_all(build_all(storage, Registry.load(settings.sources_path)), Path(args.out))
    finally:
        storage.close()
    log.info("Export nach %s: %s", args.out, ", ".join(f"{k} {v // 1024 or 1} KB" for k, v in sizes.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
