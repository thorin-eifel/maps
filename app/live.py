"""Live-Schleife: Luftverkehr im Sekundentakt, Rest bleibt im Fünf-Minuten-Zyklus.

Zweck:      Holt die Quellen mit `params.live: true` (derzeit adsb.lol) in kurzem Abstand, schreibt danach
            nur `aircraft.json` und `status.json` und lädt beide (falls aktiviert) hoch. Der Webspace
            führt nichts aus; „live“ heißt hier: Der Browser holt alle 15 Sekunden die kleine Datei.
Aufruf:     python -m app.live                 Dauerlauf (launchd/systemd, siehe deploy/)
            python -m app.live --once          ein Durchlauf, dann Ende (Test)
Parameter:  --interval S   Sekunden zwischen zwei Abrufen (Standard: Intervall aus sources.yaml, mindestens 10)
Umgebung:   PUBLISH_ENABLED=1        nach jedem Schreiben `deploy/publish.sh --live` starten
            OSINT_LIVE_PUBLISH_S     frühestens alle N Sekunden hochladen (Standard 30); läuft ein
                                     Upload noch, wird übersprungen statt gestapelt
Höflichkeit: Untergrenze 10 s je Quelle. Fehler lassen den Circuit Breaker der Collector-Basis greifen.
Datenschutz: unverändert wie adsblol.py: keine Kennungen, keine Spuren; Zusatzangaben nur Kurs und Tempo.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import signal
import sys
import time
from pathlib import Path

import httpx

from .collect import build_collectors
from .config import Settings
from .db import Storage
from .export import build_live, write_all
from .registry import Registry

log = logging.getLogger("osint.live")
MIN_INTERVAL_S = 10.0
PUBLISH_TIMEOUT_S = 60


async def _publish(root: Path) -> bool:
    proc = await asyncio.create_subprocess_exec(
        str(root / "deploy" / "publish.sh"), "--live",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=PUBLISH_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        log.error("Upload nach %d s abgebrochen", PUBLISH_TIMEOUT_S)
        return False
    if proc.returncode != 0:
        log.error("Upload fehlgeschlagen: %s", out.decode(errors="replace").strip()[-300:])
        return False
    return True


async def run(settings: Settings, interval: float | None, once: bool) -> int:
    registry = Registry.load(settings.sources_path)
    live_ids = [e.id for e in registry.active() if e.params.get("live")]
    if not live_ids:
        log.error("Keine Quelle mit params.live im Register")
        return 1
    storage = Storage(settings.db_path)
    out = settings.web_dir / "data"
    root = Path(__file__).resolve().parent.parent
    publish = os.environ.get("PUBLISH_ENABLED") == "1"
    publish_every = float(os.environ.get("OSINT_LIVE_PUBLISH_S", "30"))
    stop = asyncio.Event()
    if not once:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    uploading: asyncio.Task | None = None
    last_upload = 0.0
    async with httpx.AsyncClient(follow_redirects=False) as client:
        collectors = build_collectors(settings, storage, client, live_ids)
        wait_s = max(MIN_INTERVAL_S, interval or min(c.entry.intervall for c in collectors))
        log.info("Live-Schleife: %s alle %.0f s%s", ", ".join(live_ids), wait_s, ", Upload an" if publish else ", Upload aus")
        while not stop.is_set():
            started = time.monotonic()
            await asyncio.gather(*(c.run_once() for c in collectors))
            try:
                sizes = await asyncio.to_thread(lambda: write_all(build_live(storage, registry), out))
                log.debug("geschrieben: %s", sizes)
            except Exception:  # noqa: BLE001 — ein Schreibfehler darf die Schleife nicht beenden
                log.exception("Export fehlgeschlagen")
            if publish and (uploading is None or uploading.done()) and time.monotonic() - last_upload >= publish_every:
                last_upload = time.monotonic()
                uploading = asyncio.create_task(_publish(root))
            if once:
                if uploading:
                    await uploading
                break
            pause = max(1.0, wait_s - (time.monotonic() - started)) + random.uniform(0, wait_s * 0.1)
            try:
                await asyncio.wait_for(stop.wait(), timeout=pause)
            except asyncio.TimeoutError:
                pass
    storage.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, help="Sekunden zwischen zwei Abrufen (mindestens 10)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return asyncio.run(run(Settings.from_env(), args.interval, args.once))


if __name__ == "__main__":
    sys.exit(main())
