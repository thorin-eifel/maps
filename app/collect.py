"""Collector-Runner.

Zweck:      Führt die im Quellenregister aktiven Collector aus — einmalig oder als Dauerlauf.
Parameter:  --once            jeder Collector genau einmal, dann Ende
            --due             nur Quellen, deren Intervall seit dem letzten Versuch abgelaufen ist
                              (für Cron im Fünf-Minuten-Takt; bleibt höflich gegenüber den Quellen)
            --skip-live       Quellen mit params.live überspringen (die holt die Live-Schleife, app/live.py)
            --only ID [ID..]  nur diese Quellen
            --skip-later      Quellen mit erstlauf: spaeter überspringen (große Abfragen, z. B. OSM)
            --only-later      nur Quellen mit erstlauf: spaeter
            --healthcheck     Exit 0, wenn in den letzten 20 Minuten ein Lauf protokolliert wurde
            --log-level       DEBUG|INFO|WARNING (Standard INFO)
Beispiele:  python -m app.collect --once
            python -m app.collect --once --only autobahn pegelonline
            python -m app.collect --due                # Cron-Betrieb
            python -m app.collect                      # Dauerlauf (Container-Standard)

Fortschritt: Ist OSINT_PROGRESS_FILE gesetzt, schreibt der Lauf dorthin (JSON: total, done, running, failed), damit die Desktop-App
            "n von m, läuft noch: <Name>" anzeigen kann. Die Datei enthält nur Quellennamen, keine Daten.

Least Privilege: Dieser Prozess liest aus dem Netz und schreibt in die Datenbank, sonst nichts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import signal
import sys
from datetime import timedelta
from pathlib import Path

import httpx

from .collectors import load_collector_class
from .config import Settings
from .db import Storage
from .models import iso, utcnow
from .registry import Registry

log = logging.getLogger("osint.runner")


def build_collectors(settings: Settings, storage: Storage, client: httpx.AsyncClient, only: list[str] | None):
    registry = Registry.load(settings.sources_path)
    out = []
    for entry in registry.active():
        if only and entry.id not in only:
            continue
        cls = load_collector_class(entry.collector)
        out.append(cls(entry, storage, client, settings))
    if only:
        missing = set(only) - {c.entry.id for c in out}
        if missing:
            raise SystemExit(f"Unbekannte oder inaktive Quelle(n): {', '.join(sorted(missing))}")
    return out


def select_collectors(collectors, skip_later: bool = False, only_later: bool = False):
    """Filter nach erstlauf: spaeter (große, langsame Abfragen). Beide Schalter zusammen ergeben nichts."""
    if skip_later:
        collectors = [c for c in collectors if c.entry.erstlauf != "spaeter"]
    if only_later:
        collectors = [c for c in collectors if c.entry.erstlauf == "spaeter"]
    return collectors


def is_due(entry, state: dict, now=None, slack: float = 0.9) -> bool:
    """Fällig, wenn nie versucht oder seit dem letzten Versuch mindestens 90 % des Intervalls vergangen sind.

    Der Abschlag fängt Cron-Jitter ab (Lauf um 12:05:03, nächster Takt 12:10:01 soll nicht ausfallen).
    """
    from datetime import datetime
    last = state.get("last_attempt")
    if not last:
        return True
    now = now or utcnow()
    return (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() >= entry.intervall * slack


class Progress:
    """Schreibt den Stand eines Laufs atomar in eine JSON-Datei. Ohne Pfad passiert nichts."""

    def __init__(self, path: str | Path | None, total: int) -> None:
        self.path = Path(path) if path else None
        self.total, self.done, self.failed = total, 0, []
        self.running: list[str] = []
        self.write()

    def start(self, name: str) -> None:
        self.running.append(name)
        self.write()

    def finish(self, name: str, ok: bool) -> None:
        if name in self.running:
            self.running.remove(name)
        self.done += 1
        if not ok:
            self.failed.append(name)
        self.write()

    def write(self) -> None:
        if not self.path:
            return
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"total": self.total, "done": self.done, "running": self.running, "failed": self.failed}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:   # Fortschritt ist Beiwerk, er darf den Lauf nie stoppen
            log.warning("Fortschrittsdatei nicht schreibbar: %s", exc)


def label(c) -> str:
    return c.entry.kurzname or c.entry.name


async def run_once(collectors, progress_path: str | Path | None = None) -> int:
    prog = Progress(progress_path, len(collectors))

    async def one(c) -> bool:
        prog.start(label(c))
        ok = False
        try:
            ok = await c.run_once()
            return ok
        finally:
            prog.finish(label(c), ok)

    results = await asyncio.gather(*(one(c) for c in collectors))
    failed = [c.entry.id for c, ok in zip(collectors, results) if not ok]
    if failed:
        log.error("Fehlgeschlagen: %s", ", ".join(failed))
    return 1 if failed else 0


async def _loop(collector, stop: asyncio.Event) -> None:
    interval = collector.entry.intervall
    # Startversatz, damit nicht alle Quellen im selben Moment anklopfen
    await _sleep(stop, random.uniform(0, min(30, interval / 4)))
    while not stop.is_set():
        await collector.run_once()
        await _sleep(stop, interval + random.uniform(0, interval * 0.05))


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _maintenance(storage: Storage, settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await asyncio.to_thread(storage.purge, settings.retention_days)
        await _sleep(stop, 6 * 3600)


async def run_forever(settings: Settings, storage: Storage, collectors) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    tasks = [asyncio.create_task(_loop(c, stop)) for c in collectors]
    tasks.append(asyncio.create_task(_maintenance(storage, settings, stop)))
    log.info("Dauerlauf mit %d Collectorn gestartet", len(collectors))
    await stop.wait()
    log.info("Beende …")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def healthcheck(settings: Settings) -> int:
    try:
        storage = Storage(settings.db_path, readonly=True)
        cutoff = iso(utcnow() - timedelta(minutes=20))
        rows = storage._query("SELECT COUNT(*) n FROM collector_runs WHERE started_at >= ?", (cutoff,))  # noqa: SLF001
        return 0 if rows[0]["n"] > 0 else 1
    except Exception as exc:  # noqa: BLE001
        print(f"healthcheck: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--due", action="store_true")
    ap.add_argument("--skip-live", action="store_true")
    ap.add_argument("--only", nargs="+", metavar="ID")
    ap.add_argument("--skip-later", action="store_true")
    ap.add_argument("--only-later", action="store_true")
    ap.add_argument("--healthcheck", action="store_true")
    ap.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx loggt sonst vollständige URLs
    settings = Settings.from_env()
    if args.healthcheck:
        return healthcheck(settings)

    async def _main() -> int:
        storage = Storage(settings.db_path)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            collectors = build_collectors(settings, storage, client, args.only)
            if args.skip_live:
                collectors = [c for c in collectors if not c.entry.params.get("live")]
            collectors = select_collectors(collectors, args.skip_later, args.only_later)
            progress = os.environ.get("OSINT_PROGRESS_FILE")
            if args.due:
                due = [c for c in collectors if is_due(c.entry, storage.get_state(c.entry.id))]
                log.info("Fällig: %s", ", ".join(c.entry.id for c in due) or "nichts")
                if not due:
                    return 0
                return await run_once(due, progress)
            if args.once:
                return await run_once(collectors, progress)
            await run_forever(settings, storage, collectors)
            return 0

    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
