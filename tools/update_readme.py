#!/usr/bin/env python3
"""Hält den Stand-Block der README aktuell.

Zweck:      Die README ist von Hand geschrieben bis auf den Block zwischen <!-- stand:start --> und <!-- stand:end -->.
            Den Block erzeugt dieses Skript aus den Dateien, die die Wahrheit enthalten: region.yaml, region-rlp.yaml,
            sources.yaml, docs/rlp/status.yaml, den Testläufen (Anzahl) und dem Ordner docs/. Der Block enthält kein
            Datum, damit er sich nur ändert, wenn sich etwas geändert hat.
Aufruf:     python tools/update_readme.py            # schreibt README.md
            python tools/update_readme.py --check    # Exit 1, wenn die README nicht zum Stand passt (läuft in der CI)
Hinweis:    Die Testanzahl kommt aus `pytest --collect-only` und einem Lauf von `node --test` über tests/js. Beides ohne Netz.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
README = ROOT / "README.md"
START, END = "<!-- stand:start -->", "<!-- stand:end -->"


def count_py_tests() -> int:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                         cwd=ROOT, capture_output=True, text=True, check=False).stdout
    m = re.search(r"(\d+) tests? collected", out) or re.search(r"^(\d+) tests?", out, re.M)
    if m:
        return int(m.group(1))
    return sum(1 for line in out.splitlines() if "::" in line)


def count_js_tests() -> int:
    files = sorted((ROOT / "tests" / "js").glob("*.test.mjs"))
    try:
        out = subprocess.run(["node", "--test", *map(str, files)], cwd=ROOT, capture_output=True, text=True, check=False).stdout
        m = re.search(r"^# tests (\d+)", out, re.M)
        if m:
            return int(m.group(1))
    except OSError:
        pass
    n = 0
    for f in files:
        n += len(re.findall(r"^\s*test\(", f.read_text(encoding="utf-8"), re.M))
    return n


def region_line(path: Path) -> str:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    if cfg["mode"] == "radius":
        return f"{cfg['name']}: Kreis, {cfg['radius_km']:g} km um {cfg['reference']['name']}"
    return f"{cfg['name']}: Polygon aus `{cfg['polygon_file']}`, Bezugspunkt {cfg['reference']['name']}"


def build_block() -> str:
    from app.registry import Registry  # erst hier, damit --help ohne Abhängigkeiten läuft

    reg = Registry.load(ROOT / "sources.yaml")
    phases = yaml.safe_load((ROOT / "docs" / "rlp" / "status.yaml").read_text(encoding="utf-8"))["phasen"]
    docs = sorted(p.name for p in (ROOT / "docs").glob("*.md"))
    collectors = len([p for p in (ROOT / "app" / "collectors").glob("*.py") if p.stem not in ("__init__", "base", "rsslib", "severity")])
    lines = [START, "", "<!-- Dieser Block wird von tools/update_readme.py erzeugt. Nicht von Hand ändern. -->", ""]
    lines += ["### Region", "",
              f"- Aktiv (`region.yaml`): {region_line(ROOT / 'region.yaml')}",
              f"- Ziel (`region-rlp.yaml`, noch nicht aktiv): {region_line(ROOT / 'region-rlp.yaml')}", ""]
    lines += ["### Phasen", "", "| Phase | Inhalt | Stand | Pull Request |", "|---|---|---|---|"]
    for p in phases:
        pr = f"[#{p['pr']}](https://github.com/thorin-eifel/maps/pull/{p['pr']})" if p.get("pr") else ""
        lines.append(f"| {p['id']} | {p['name']} | {p['stand']} | {pr} |")
    lines += ["", f"Plan und Begründung: `docs/rlp/plan.md`. Entscheidung: `docs/adr/0001-region-rlp.md`.", ""]
    lines += ["### Zahlen", "",
              f"- Quellen im Register: {len(reg.entries)}, davon aktiv: {len(reg.active())}",
              f"- Sammler (Module in `app/collectors/`): {collectors}",
              f"- Tests: {count_py_tests()} Python, {count_js_tests()} JavaScript", ""]
    lines += ["### Quellen und Lizenzen", "", "| Kennung | Quelle | Lizenz | Intervall | aktiv |", "|---|---|---|---|---|"]
    for e in reg.entries:
        iv = f"{e.intervall // 3600} h" if e.intervall % 3600 == 0 else (f"{e.intervall // 60} min" if e.intervall % 60 == 0 else f"{e.intervall} s")
        lines.append(f"| `{e.id}` | {e.kurzname or e.name} | {e.lizenz} | {iv} | {'ja' if e.aktiv else 'nein'} |")
    lines += ["", "Vollständig mit Namensnennung: `sources.yaml` und die Seite „Quellen und Lizenzen“ der Anwendung.", ""]
    lines += ["### Dokumente", ""] + [f"- `docs/{d}`" for d in docs] + ["- `docs/rlp/` (Plan, Prompt, Status, offene Punkte)", "- `docs/adr/` (Entscheidungen)", "", END]
    return "\n".join(lines)


def render(current: str) -> str:
    if START not in current or END not in current:
        raise SystemExit(f"README.md: Marker {START} / {END} fehlen")
    head, rest = current.split(START, 1)
    _, tail = rest.split(END, 1)
    return head + build_block() + tail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="nur prüfen, nicht schreiben")
    args = ap.parse_args(argv)
    current = README.read_text(encoding="utf-8")
    new = render(current)
    if args.check:
        if new != current:
            print("README.md ist nicht aktuell. `python tools/update_readme.py` ausführen und mitcommitten.", file=sys.stderr)
            return 1
        print("README.md ist aktuell.")
        return 0
    if new != current:
        README.write_text(new, encoding="utf-8")
        print("README.md aktualisiert.")
    else:
        print("README.md unverändert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
