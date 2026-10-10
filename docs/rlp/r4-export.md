# R4 Export und Auslieferung: Aufbau und Messwerte

Stand: 10. Oktober 2026. Messbasis: Datenbank des R3-Laufs (Region Rheinland-Pfalz plus 80 km, 4.200 Ereignisse, 1.500 Stationen, 113.000 Messwerte), Export im Sandkasten.

## Aufbau

```
web/data/
  manifest.json              Version, Zellenliste, je Datei Größe, Prüfsumme, Upload-Regel; Größenwarnungen
  start.json                 Startpaket: Meta, Warnband, Quellenzustand, Zählwerte und Höchststufe je Zelle
  z/<x>_<y>/<art>.json       Zellendateien; Arten: events, gewaesser, umwelt, haltestellen, landmarks,
                             infrastruktur, sakral, routen, anbau, kraftstoff
  *.json, *.png              Flachdateien wie bisher (meta, status, wetter, wind, radar, suche, ...)
  .export-state.json         Zustand des Exports (versteckt, wird nicht hochgeladen)
  .published.json            Stand des letzten erfolgreichen Uploads (versteckt, nur lokal)
```

**Raster.** Zelle `x_y` mit `x = floor(lon * 2)`, `y = floor(lat * 2)`, also 0,5 Grad. Irrel liegt in `12_99`. Ein Punkt auf einer Kante gehört der höheren Zelle. Linien und Flächen liegen in jeder Zelle, die sie berühren (Kante zählt mit, Löcher in Flächen werden beachtet); das Frontend entfernt Dubletten über die Kennung. Code: `app/cells.py`.

**Kontrakt einer Zellendatei.** `kind`, `cell`, `sources` (Id, Name, Betreiber, Lizenz, Namensnennung, Intervall), `stand`, dazu die Liste (`features`, `stations`, `stops` oder `items`). Nicht darin: Alter, Status "veraltet", Abrufzeit je Lauf. Sonst änderte sich jede Datei bei jedem Lauf, und der inkrementelle Upload hätte nichts zu sparen. `stand` ist der Zeitpunkt, an dem sich der Inhalt zuletzt geändert hat. Wann zuletzt abgerufen wurde, steht je Quelle in `start.json` (`last_success`, `interval_s`); daraus rechnet das Frontend "veraltet" gegen die Uhr des Betrachters, nach derselben Regel wie `source_status` (`web/js/rules.js`).

**Stabilität.** Jeder Zelleninhalt wird um flüchtige Felder bereinigt und gehasht. Bleibt der Hash gleich, bleibt die Datei Byte für Byte wie zuvor, einschließlich `stand`.

**Upload.** `deploy/publish.sh --delta` fragt `tools/publish_delta.py` nach den geänderten Dateien (Vergleich Manifest gegen `.published.json`), legt Zellenordner an, lädt Dateien hoch und das Manifest zuletzt. Erst nach erfolgreichem Upload wird der Stand fortgeschrieben; schlägt etwas fehl, wiederholt der nächste Lauf dasselbe. Der Upload löscht nie. `deploy/run-cycle.sh` nutzt `--delta`.

## Messwerte

| Größe | Wert |
|---|---|
| Exportdauer (Region, Testdatenbank) | 5 s (Grenze 60 s) |
| Zellen | 59, davon 199 Zellendateien |
| Zellendatei: Median / 90. Perzentil / Maximum | 10 KB / 134 KB / 509 KB |
| Startpaket | 130 KB (Grenze 2 MB) |
| Alle Zellen zusammen | Ereignisse 5,6 MB, Gewässer 1,7 MB, Messstellen 0,5 MB, Haltestellen 0,2 MB |
| Zyklus ohne Datenänderung | 5 Dateien, 162 KB (start, manifest, status, meta, aircraft) |
| Zyklus mit einer geänderten Zelle | 162 KB plus die Zelle |
| Vollständiger Erstupload | 224 Dateien, 15,4 MB (davon 5,8 MB Flachdateien für das alte Frontend) |

## Was sich nicht erfüllen ließ, und warum

- **"Ein Zyklus ohne Änderungen lädt nichts hoch" gilt mit Einschränkung.** Fünf kleine Herzschlag-Dateien gehen immer raus, 162 KB. Ohne sie zeigte die Seite Quellen fälschlich als veraltet, weil `last_success` nur dort steht. Alles andere bleibt zu Hause.
- **Eine Zelle über dem Budget:** `z/16_98/events.json` (Pfalz um Karlsruhe, 509 KB statt 500 KB). Sie wird nicht gekürzt, sondern im Manifest und im Log gemeldet. Ursache sind lange Baustellenlinien (LBM, Autobahn), die in mehreren Zellen liegen. Ereignisse insgesamt 5,6 MB statt 3,5 MB der Flachdatei, weil Geometrien über Zellgrenzen doppelt vorkommen. Abhilfe in R5, falls nötig: Geometrie bei kleinen Zoomstufen vereinfachen.
- **Flachdateien bleiben bis R5.** Das heutige Frontend liest sie. `events.json` bleibt dort bei 2.000 Einträgen (alte Grenze); die Zellen haben bis 50.000. Mit `--no-legacy` lassen sich die Flachdateien abschalten, sobald das Frontend die Zellen liest.
- **Radarbild (1,2 MB), Wind (110 KB), Suchindex (136 KB) sind global und nicht zellenweise.** Sie liegen außerhalb der Budgets von Startpaket und Zelle. R5 entscheidet, wie sie nachgeladen werden.
- **Upload nicht gegen den echten IONOS-Webspace getestet.** `lftp` ist im Sandkasten nicht vorhanden; geprüft ist der Trockenlauf (Befehle, Reihenfolge, Ordner anlegen) und der Plan. Der erste echte Lauf gehört auf den Mac: `deploy/publish.sh --delta --dry-run`, dann ohne `--dry-run`.

## Prüfen

```bash
export OSINT_REGION=region-rlp.yaml
python -m app.export                         # schreibt web/data inklusive manifest.json und z/
python -c "import json;m=json.load(open('web/data/manifest.json'));print(len(m['cells']),'Zellen',m['warnings'])"
deploy/publish.sh --delta --dry-run          # zeigt, was hochgeladen würde
python tools/publish_delta.py reset          # nächster Lauf lädt alles (z. B. nach Wechsel des Webspace)
```
