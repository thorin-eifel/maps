#!/usr/bin/env python3
"""Inkrementeller Upload: bestimmt, welche Dateien aus web/data auf den Webspace müssen.

Zweck:     Nach jedem Export vergleicht dieses Werkzeug das neue manifest.json mit dem Stand des letzten erfolgreichen Uploads
           (`.published.json` im Datenordner) und nennt nur geänderte Dateien. deploy/publish.sh --delta lädt genau diese hoch.
Regeln:    - upload "always" (start.json, manifest.json, status.json, meta.json, aircraft.json): Herzschlag, immer; sie tragen den
             Quellenzustand, ohne den das Frontend "veraltet" falsch anzeigen würde. Zusammen rund 200 KB.
           - upload "on_change": Datei fehlt im letzten Stand, oder content_hash hat sich geändert, oder (nur Flachdateien) die
             Datei wurde länger als max_age_s nicht hochgeladen.
           - manifest.json kommt immer zuletzt, damit kein Besucher ein Manifest sieht, dessen Dateien noch fehlen.
           - Gelöscht wird auf dem Webspace nie (Zellen, die verschwinden, bleiben dort liegen; das Manifest führt sie nicht mehr).
Aufruf:    python tools/publish_delta.py plan   --data web/data [--out plan.txt]    Liste (ein Pfad je Zeile), Zusammenfassung auf stderr
           python tools/publish_delta.py commit --data web/data --plan plan.txt      Stand nach erfolgreichem Upload fortschreiben
           python tools/publish_delta.py reset  --data web/data                      Stand verwerfen (nächster Lauf lädt alles)
Exit:      0 = ok (auch bei leerem Plan), 1 = Fehler (kein Manifest, defektes Manifest)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

STATE = ".published.json"
LAST = "manifest.json"


def load_manifest(data: Path) -> dict:
    try:
        m = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"manifest.json nicht lesbar ({exc}); erst `python -m app.export` laufen lassen")
    if not isinstance(m, dict) or not isinstance(m.get("files"), dict):
        raise SystemExit("manifest.json hat keine Dateiliste")
    return m


def load_state(data: Path) -> dict:
    try:
        d = json.loads((data / STATE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("files"), dict) else {"files": {}}
    except (OSError, ValueError):
        return {"files": {}}


def plan(manifest: dict, state: dict, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    done = state.get("files", {})
    out: list[str] = []
    for rel, info in manifest["files"].items():
        old = done.get(rel)
        if info.get("upload") == "always" or old is None or old.get("content_hash") != info.get("content_hash"):
            out.append(rel)
            continue
        max_age = info.get("max_age_s")
        if max_age and now - old.get("uploaded_at", 0) > max_age:
            out.append(rel)
    out = [r for r in out if r != LAST and r != "start.json"]
    out.sort()
    out += [r for r in ("start.json",) if r in manifest["files"]]
    out.append(LAST)                                   # Manifest immer zuletzt
    return out


def commit(manifest: dict, state: dict, uploaded: list[str], now: float | None = None) -> dict:
    now = time.time() if now is None else now
    files = dict(state.get("files", {}))
    for rel in uploaded:
        info = manifest["files"].get(rel)
        if info:
            files[rel] = {"content_hash": info.get("content_hash"), "uploaded_at": now}
    return {"files": files, "manifest_generated_at": manifest.get("generated_at")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "commit", "reset"])
    ap.add_argument("--data", type=Path, default=Path("web/data"))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--plan", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "reset":
        (a.data / STATE).unlink(missing_ok=True)
        return 0
    m, st = load_manifest(a.data), load_state(a.data)
    if a.cmd == "plan":
        files = plan(m, st)
        total = sum(m["files"][r]["bytes"] for r in files if r in m["files"])
        print(f"{len(files)} von {len(m['files']) + 1} Dateien, {total // 1024} KB (Manifest eingerechnet)", file=sys.stderr)
        text = "\n".join(files) + "\n"
        if a.out:
            a.out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    if not a.plan or not a.plan.exists():
        raise SystemExit("--plan fehlt")
    uploaded = [l.strip() for l in a.plan.read_text(encoding="utf-8").splitlines() if l.strip()]
    new = commit(m, st, uploaded)
    tmp = a.data / (STATE + ".tmp")
    tmp.write_text(json.dumps(new, separators=(",", ":")), encoding="utf-8")
    tmp.replace(a.data / STATE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
