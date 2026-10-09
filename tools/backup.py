#!/usr/bin/env python3
"""Konsistente Sicherung der SQLite-Datenbank (Online-Backup-API, auch bei laufendem Collector).

Zweck:      Tägliche Kopie nach BACKUP_DIR, ältere Sicherungen werden nach --keep aufgeräumt,
            die Kopie wird auf Integrität geprüft (PRAGMA integrity_check).
Parameter:  --db PFAD      Quelle (Standard $OSINT_DB_PATH oder data/osint.sqlite)
            --dir PFAD     Ziel (Standard $OSINT_BACKUP_DIR oder data/backup)
            --keep N       Anzahl aufzubewahrender Sicherungen (Standard 14)
            --loop SEK     Dauerbetrieb: alle SEK Sekunden wiederholen (Standard: einmalig)
Beispiel:   python tools/backup.py --keep 7
Exit-Code:  0 = Sicherung ok und geprüft, 1 = Fehler
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("backup")


def backup_once(db: Path, out_dir: Path, keep: int) -> Path:
    if not db.exists():
        raise FileNotFoundError(f"Datenbank nicht gefunden: {db}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"osint-{stamp}.sqlite"
    tmp = target.with_suffix(".tmp")
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    if result != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Integritätsprüfung der Sicherung fehlgeschlagen: {result}")
    tmp.replace(target)
    old = sorted(out_dir.glob("osint-*.sqlite"))[:-keep] if keep > 0 else []
    for f in old:
        f.unlink()
        log.info("alte Sicherung entfernt: %s", f.name)
    log.info("Sicherung ok: %s (%d Bytes)", target.name, target.stat().st_size)
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("OSINT_DB_PATH", "data/osint.sqlite"))
    ap.add_argument("--dir", default=os.environ.get("OSINT_BACKUP_DIR", "data/backup"))
    ap.add_argument("--keep", type=int, default=14)
    ap.add_argument("--loop", type=int, default=0, metavar="SEK")
    args = ap.parse_args()
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    rc = 0
    while True:
        try:
            backup_once(Path(args.db), Path(args.dir), args.keep)
            rc = 0
        except Exception as exc:  # noqa: BLE001
            log.error("Sicherung fehlgeschlagen: %s", exc)
            rc = 1
        if not args.loop:
            return rc
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(main())
