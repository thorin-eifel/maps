"""Kartenausschnitt um einen frei wählbaren Mittelpunkt (Python-Fassung von tools/build_tiles.sh).

Zweck:     Aus Mittelpunkt und Radius die Kästen und den Ring für `pmtiles extract` berechnen und die Abrufe ausführen.
Aufruf:    python -m app.tilebuild --lat 49.846 --lon 6.456 --out ./tiles --pmtiles ./pmtiles [--dry-run]
Beispiel:  python -m app.tilebuild --lat 52.52 --lon 13.40 --out /tmp/t --dry-run
Hinweis:   Quelle build.protomaps.com (Teilabrufe, ca. 550 MB bei 120 km). Der reine Rechenteil ist ohne Netz testbar.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger("osint.tilebuild")

RADIUS_KM = 120.0
MARGIN_DEG = 0.15      # Rand um den Kasten des Kreises
CORE_HALF_LAT = 0.36   # Kern ca. 80 x 80 km (wie tools/build_tiles.sh)
CORE_HALF_LON = 0.56
RING_KM = 121.0
LAT_KM = 110.57
LON_KM = 111.32
# Erwartete Größe der drei Dateien bei 120 km (Messwerte, MB). Dient nur der Fortschrittsanzeige; wird die Datei größer, wächst die Schätzung mit.
EXPECTED_MB = {"region.pmtiles": 360, "core.pmtiles": 130, "ring.pmtiles": 210}


def region_bbox(lat: float, lon: float, km: float = RADIUS_KM) -> tuple[float, float, float, float]:
    """lon_min, lat_min, lon_max, lat_max des Kreises plus Rand (Reihenfolge wie pmtiles --bbox)."""
    dlat = km / LAT_KM
    dlon = km / (LON_KM * math.cos(math.radians(lat)))
    return (round(lon - dlon - MARGIN_DEG, 2), round(lat - dlat - MARGIN_DEG, 2),
            round(lon + dlon + MARGIN_DEG, 2), round(lat + dlat + MARGIN_DEG, 2))


def core_bbox(lat: float, lon: float) -> tuple[float, float, float, float]:
    return (round(lon - CORE_HALF_LON, 2), round(lat - CORE_HALF_LAT, 2), round(lon + CORE_HALF_LON, 2), round(lat + CORE_HALF_LAT, 2))


def ring_geojson(lat: float, lon: float, km: float = RING_KM) -> dict:
    """Kreis mit rechteckigem Loch (dem Kern): Zoom 14 nur außerhalb des Kerns, damit nichts doppelt liegt."""
    pts = [[round(lon + km * math.sin(a) / (LON_KM * math.cos(math.radians(lat))), 5), round(lat + km * math.cos(a) / LAT_KM, 5)]
           for a in (2 * math.pi * i / 180 for i in range(181))]
    c = core_bbox(lat, lon)
    hole = [[c[0], c[1]], [c[0], c[3]], [c[2], c[3]], [c[2], c[1]], [c[0], c[1]]]
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [pts, hole]}}]}


def validate_center(lat: float, lon: float) -> None:
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-80 <= lat <= 80) or not (-180 <= lon <= 180):
        raise ValueError("Mittelpunkt außerhalb des gültigen Bereichs")


def plan(lat: float, lon: float) -> list[tuple[str, list[str]]]:
    """Die drei Abrufe als (Dateiname, Argumente für `pmtiles extract`)."""
    validate_center(lat, lon)
    b = ",".join(map(str, region_bbox(lat, lon)))
    c = ",".join(map(str, core_bbox(lat, lon)))
    return [("region.pmtiles", [f"--bbox={b}", "--maxzoom=13"]),
            ("core.pmtiles", [f"--bbox={c}", "--maxzoom=15"]),
            ("ring.pmtiles", ["--region=@RING@", "--minzoom=14", "--maxzoom=14"])]


def latest_build(fetch: Callable[[str], bytes]) -> str:
    data = json.loads(fetch("https://build-metadata.protomaps.dev/builds.json"))
    return sorted(x["key"] for x in data)[-1].split(".")[0]


def step_fraction(done_mb: float, current_mb: float, expected_mb: float, total_mb: float) -> float:
    """Gesamtfortschritt 0..1 aus fertigen MB und der wachsenden Datei. Die Datei zählt höchstens zu 99 %, bis sie wirklich fertig ist."""
    cur = min(current_mb, expected_mb * 0.99)
    return max(0.0, min(1.0, (done_mb + cur) / total_mb)) if total_mb > 0 else 0.0


def run_watched(cmd: list[str], tmp: Path, on_size: Callable[[float], None], timeout: float, interval: float = 1.0) -> None:
    """Führt `cmd` aus und meldet jede Sekunde die Größe der entstehenden Datei (MB). Bei Zeitüberschreitung wird abgebrochen."""
    start = time.monotonic()
    proc = subprocess.Popen(cmd)
    try:
        while True:
            try:
                rc = proc.wait(timeout=interval)
                break
            except subprocess.TimeoutExpired:
                on_size((tmp.stat().st_size if tmp.exists() else 0) / 1e6)
                if time.monotonic() - start > timeout:
                    raise subprocess.TimeoutExpired(cmd, timeout)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)


def build(lat: float, lon: float, out: Path, pmtiles: Path, build_id: str, progress: Callable[..., None] = lambda *_: None,
          threads: int = 2, dry_run: bool = False) -> list[Path]:
    """Lädt die drei Dateien nach `out`. Fertige Dateien werden übersprungen (wiederaufnehmbar), Teilergebnisse nie stehen gelassen.

    progress(i, n, text, frac): frac ist der Gesamtfortschritt 0..1 nach geschätzter Größe, text nennt die geladenen MB."""
    if not (build_id.isdigit() and len(build_id) == 8):
        raise ValueError("Build-Datum muss JJJJMMTT sein")
    out.mkdir(parents=True, exist_ok=True)
    steps = plan(lat, lon)
    done: list[Path] = []
    exp = {name: float(EXPECTED_MB.get(name, 200)) for name, _ in steps}
    total = sum(exp.values())
    finished_mb = 0.0
    for i, (name, args) in enumerate(steps):
        target = out / name
        if target.exists():
            done.append(target)
            finished_mb += exp[name]
            progress(i + 1, len(steps), f"{name} vorhanden", finished_mb / total)
            continue
        tmp = out / f".{name}.tmp"
        ring = out / ".ring.geojson"
        if "--region=@RING@" in args:
            ring.write_text(json.dumps(ring_geojson(lat, lon)), encoding="utf-8")
            args = [a.replace("@RING@", str(ring)) for a in args]
        cmd = [str(pmtiles), "extract", f"https://build.protomaps.com/{build_id}.pmtiles", str(tmp), *args, f"--download-threads={threads}"]
        progress(i, len(steps), f"Karte {i + 1} von {len(steps)} wird geladen", finished_mb / total)
        log.info("%s", " ".join(cmd))
        if dry_run:
            continue
        tmp.unlink(missing_ok=True)
        try:
            def on_size(mb: float, i=i, name=name) -> None:
                exp[name] = max(exp[name], mb * 1.02)   # Schätzung wächst mit, der Balken läuft nie rückwärts über 99 %
                progress(i, len(steps), f"Karte {i + 1} von {len(steps)}: {mb:,.0f} MB von etwa {exp[name]:,.0f} MB geladen".replace(",", "."),
                         step_fraction(finished_mb, mb, exp[name], sum(exp.values())))
            run_watched(cmd, tmp, on_size, 3 * 3600)
            subprocess.run([str(pmtiles), "show", str(tmp)], check=True, stdout=subprocess.DEVNULL, timeout=120)
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
            ring.unlink(missing_ok=True)
        done.append(target)
        finished_mb += exp[name]
        progress(i + 1, len(steps), f"Karte {i + 1} von {len(steps)} fertig", finished_mb / sum(exp.values()))
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pmtiles", type=Path, default=Path("pmtiles"))
    ap.add_argument("--build", help="JJJJMMTT; ohne Angabe der neueste")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        bid = a.build
        if not bid:
            import urllib.request
            req = urllib.request.Request("https://build-metadata.protomaps.dev/builds.json", headers={"User-Agent": "WasIstLosBeiUns/1.0"})
            bid = latest_build(lambda u: urllib.request.urlopen(req, timeout=30).read()) if not a.dry_run else "20260101"
        build(a.lat, a.lon, a.out, a.pmtiles, bid, dry_run=a.dry_run)
    except (ValueError, subprocess.SubprocessError, OSError) as err:
        log.error("%s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
