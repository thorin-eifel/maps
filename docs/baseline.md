# Baseline vor dem Umbau auf Rheinland-Pfalz plus 80 km

Gemessen am 9. Oktober 2026 im Branch `rlp/r0-baseline`. Fläche: Kreis 120 km um Irrel. Quelle der Zahlen: Mac des Betreibers (Datenbank, Kacheln, Export), frischer Klon dieses Repositories. Wo nur eine frühere Beobachtung vorliegt, steht es dabei.

## Code und Tests

| Messgröße | Wert |
|---|---|
| Python `app/` | 7 962 Zeilen, 47 Dateien in `app/collectors/` |
| Python-Tests | 3 288 Zeilen, 265 Tests grün (frische venv, Python 3.11) |
| JavaScript `web/js/` | 5 803 Zeilen, davon `lage.js` rund 150 KB in einer Datei |
| JS-Tests | 41 Tests grün (`node --test tests/js/*.test.mjs`, Node 22) |
| Quellen in `sources.yaml` | 42 Einträge, davon 40 aktiv (gezählt über `Registry.load`) |

## Daten (Sammelstelle, Mac)

| Messgröße | Wert |
|---|---|
| SQLite-Datei | 158 MB plus 10 MB WAL |
| Ereignisse | 59 545 |
| Messwerte (Zeitreihen) | 574 042 |
| Stationen | 970 |
| Sammlerläufe protokolliert | 32 128 |
| Export (`python -m app.export`) | 2,3 Sekunden, 22,5 MB in 23 Dateien |
| Größte Exportdateien | `anbau.json` 8,1 MB, `sakral.json` 2,9 MB, `infrastruktur.json` 2,8 MB, `gewaesser.json` 1,8 MB, `routen.json` 1,7 MB |

Der Export läuft hier gegen eine Kopie der Datenbank in der Linux-VM des Macs (Python 3.10, mit den Paketen aus `requirements.txt`).

## Karte

| Datei | Größe |
|---|---|
| `region.pmtiles` | 285 MB |
| `ring.pmtiles` | 139 MB |
| `core.pmtiles` | 119 MB |
| `dem/` (Terrarium, Zoom 6 bis 12) | gehört zu den 869 MB in `web/tiles/` insgesamt |

Zeit bis zur sichtbaren Karte: 30 bis 45 Sekunden. Das ist eine Beobachtung aus der Arbeit mit dem Prüfzugang (`#debug`) vom 7. bis 9. Oktober, keine kontrollierte Messung. Eine Messung mit leerem Cache und lokalem Server folgt in R2 und R5.

## Bekannte Mängel zum Start

- `tests/test_wetter_quellen.py::test_metno_...` hing an der Systemuhr. Behoben mit fester Uhr (`metno._now`).
- `requirements-dev.txt` enthielt nur pytest. Jetzt mit `-r requirements.txt`. Kartenbau-Pakete (numpy, mapbox-vector-tile) stehen in `requirements-tools.txt`, weil pip sie nicht neben `protobuf==7.34.1` auflöst.
- `.gitignore` hatte `data/` überall ausgeschlossen und damit `app/data/` verschluckt. Jetzt nur `/data/` und `/web/data/`.
- Mac-Anwendung ist nicht signiert, CI-Builds für Windows und Linux sind nie gelaufen.
- Offen: Kontaktadresse für den User-Agent (`OSINT_CONTACT`) steht noch auf einem Platzhalter.
