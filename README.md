# Was ist los bei uns?

Ein Lagebild aus offenen Daten: Warnungen, Wetter, Pegel, Verkehr, Luft und Strahlung auf einer Karte, mit Quelle, Alter und Lizenz an jedem Datum. Es zeigt Orte, Zeiten und Zahlen, keine Personen. Kein Tracking, keine Drittanbieter, keine US-Cloud.

Privates Open-Source-Projekt von Thorsten Schleicher, Ferschweiler. Kontakt: thorin.eifel@icloud.com. Seit dem 9. Oktober 2026 privat (vorher als Schaufenster der CTW Computer-Irrel GmbH). Kein amtliches Warnsystem: im Notfall 112 und die offiziellen Warn-Apps (NINA, KATWARN).

Zielbild: Rheinland-Pfalz plus 80 km jenseits der Landesgrenze. Heute läuft noch der Kreis von 120 km um Irrel. Der Umbau läuft in Phasen R0 bis R7, den Stand zeigt der Block unten.

## Schnellstart

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q && node --test tests/js/*.test.mjs

cp .env.example .env && chmod 600 .env     # OSINT_CONTACT prüfen
python -m app.collect --once               # alle fälligen Quellen einmal abrufen
python -m app.export                       # schreibt web/data/*.json
python -m http.server 8000 -d web          # http://localhost:8000
```

Die Karte braucht eigene Kacheln (`web/tiles/*.pmtiles`, nicht im Repository). Bau und Größen: `docs/betrieb.md`, Abschnitt Karte.

Andere Region ausprobieren: `OSINT_REGION=region-rlp.yaml python -m app.region` zeigt die Landesfläche. Die Fläche steht in `region.yaml` (Kreis oder Polygon), das Polygon baut `tools/build_region.py` aus BKG VG250.

## So hängt es zusammen

```
Quellen → Sammler (app/collectors) → Geofilter (app/region.py) → SQLite → Export (JSON) → statisches Frontend (web/)
```

Ein Rechner ruft die Quellen ab und schreibt fertige JSON-Dateien. Der Webspace liefert nur HTML, CSS, JavaScript und diese Dateien aus (kein Python dort). Fällt eine Quelle aus, bleibt der Rest stehen und die Kachel sagt es. Ausführlich mit Betrieb, IONOS-Einrichtung und Desktop-App: `docs/betrieb.md`.

## Regeln, die nicht verhandelt werden

- Ereignisse statt Personen. Keine Klarnamen, Profile, Adressen oder Bilder von Personen.
- Keine Quelle ohne Eintrag in `sources.yaml` (Lizenz, Namensnennung, Intervall, Ratenlimit, Datenschutzrisiko). Unklare Bedingungen heißen: Quelle bleibt aus.
- Jede Kachel zeigt Quelle, Abrufzeit und Alter. Alte Daten werden als alt markiert.
- KI-Auswertung ist gekennzeichnet und optional. Keine Warnung, die nur ein Modell behauptet.
- Keine externen Skripte, Schriften oder Kacheln, keine Cookies außer technisch nötigen.
- Zugangsdaten nur in `.env`, nie im Repository.

Die ursprüngliche Projektanweisung steht in `docs/projektanweisung.md` (CTW-Bezüge und Radius dort überholt, Grundsätze gelten). Maßgeblich für Fläche und Phasen ist `docs/rlp/plan.md`.

## Stand

<!-- stand:start -->

<!-- Dieser Block wird von tools/update_readme.py erzeugt. Nicht von Hand ändern. -->

### Region

- Aktiv (`region.yaml`): Südeifel und Umgebung (120 km um Irrel): Kreis, 120 km um Irrel
- Ziel (`region-rlp.yaml`, noch nicht aktiv): Rheinland-Pfalz plus 80 km: Polygon aus `app/data/region/rlp_plus80.json`, Bezugspunkt Irrel

### Phasen

| Phase | Inhalt | Stand | Pull Request |
|---|---|---|---|
| R0 | Repository und Baseline | fertig | [#1](https://github.com/thorin-eifel/maps/pull/1) |
| R1 | Raumabstraktion | fertig | [#2](https://github.com/thorin-eifel/maps/pull/2) |
| R2 | Kartenbasis | fertig | [#3](https://github.com/thorin-eifel/maps/pull/3) |
| R3 | Datenpipeline | fertig | [#4](https://github.com/thorin-eifel/maps/pull/4) |
| R4 | Export und Auslieferung | wartet auf Freigabe | [#5](https://github.com/thorin-eifel/maps/pull/5) |
| R5 | Frontend | offen |  |
| R6 | Betrieb und Härtung | offen |  |
| R7 | Abnahme | offen |  |

Plan und Begründung: `docs/rlp/plan.md`. Entscheidung: `docs/adr/0001-region-rlp.md`.

### Zahlen

- Quellen im Register: 42, davon aktiv: 40
- Sammler (Module in `app/collectors/`): 43
- Tests: 395 Python, 41 JavaScript

### Quellen und Lizenzen

| Kennung | Quelle | Lizenz | Intervall | aktiv |
|---|---|---|---|---|
| `nina` | NINA / BBK | Nutzungsbedingungen NINA/BBK | 5 min | ja |
| `dwd_warnungen` | DWD | GeoNutzV (DWD Open Data) | 5 min | ja |
| `brightsky` | DWD via Bright Sky | DWD GeoNutzV; Bright Sky Software MIT | 15 min | ja |
| `pegelonline` | WSV Pegelonline | Datenlizenz Deutschland – Namensnennung 2.0 (zu bestätigen) | 10 min | ja |
| `autobahn` | Autobahn GmbH | Nutzungsbedingungen Autobahn GmbH (zu bestätigen) | 5 min | ja |
| `adsblol` | adsb.lol | ODbL 1.0 (laut Betreiber-Dokumentation) | 15 s | ja |
| `lbm_baustellen` | Mobilitätsatlas RLP | nicht angegeben (zu klären) | 10 min | ja |
| `hochwasser_rlp` | Hochwasser RLP | nicht angegeben (zu klären) | 15 min | ja |
| `bfs_odl` | BfS ODL | Datenlizenz Deutschland – Namensnennung – Version 2.0 (nach Kenntnisstand) | 30 min | ja |
| `uba_luft` | UBA Luftdaten | Datenlizenz Deutschland – Namensnennung – Version 2.0 (nach Kenntnisstand) | 30 min | ja |
| `emsc` | EMSC | CC BY 4.0 (laut Dienstseite) | 15 min | ja |
| `dwd_radar` | DWD Radar | GeoNutzV (Geodatennutzungsverordnung), Quellenvermerk Deutscher Wetterdienst | 5 min | ja |
| `dwd_icon_d2_wind` | DWD Wind | GeoNutzV (Geodatennutzungsverordnung), Quellenvermerk Deutscher Wetterdienst | 1 h | ja |
| `eumetsat_li` | EUMETSAT Blitze | EUMETSAT-Datenpolitik, Quellenvermerk EUMETSAT (Bedingungen für MTG-LI über EUMETView nicht abschließend geprüft) | 5 min | ja |
| `nasa_firms` | NASA FIRMS | NASA Earthdata-Datennutzungsrichtlinie (frei, auch kommerziell), Quellenangabe NASA FIRMS | 30 min | ja |
| `gtfs_static` | GTFS Fahrplan | CC BY 4.0 (Luxemburg laut Datensatz, Deutschland laut gtfs.de "Creative Commons 4.0") | 168 h | ja |
| `gtfs_rt_de` | ÖPNV Echtzeit | CC BY-SA 4.0 (Namensnennung, Weitergabe unter gleichen Bedingungen), ohne Gewähr | 10 min | ja |
| `osm_natur` | Landmarken | ODbL 1.0 (© OpenStreetMap-Mitwirkende) | 168 h | ja |
| `osm_infra` | Infrastruktur | ODbL 1.0 (© OpenStreetMap-Mitwirkende) | 168 h | ja |
| `osm_anbau` | Anbauflächen | ODbL 1.0 (© OpenStreetMap-Mitwirkende) | 168 h | ja |
| `osm_routen` | Routen | ODbL 1.0 (© OpenStreetMap-Mitwirkende) | 168 h | ja |
| `meteolux` | MeteoLux Findel | CC0 1.0 | 10 min | ja |
| `metno` | MET Norway | CC BY 4.0 | 1 h | ja |
| `sensor_community` | Sensor.Community | Datenbank ODbL 1.0, Inhalte DbCL 1.0 (laut Betreiberangabe, zu bestätigen) | 10 min | ja |
| `presseportal` | Presseportal Polizei | keine offene Lizenz; nur Überschrift, Ort, Zeit und Link | 10 min | nein |
| `volksfreund` | Volksfreund | keine offene Lizenz; nur Überschrift, Zeit und Link, kein Text, kein Bild | 15 min | ja |
| `lu_pegel` | Pegel Luxemburg | CC0 1.0 | 15 min | ja |
| `cita_lu` | CITA Luxemburg | CC0 1.0 | 5 min | ja |
| `dwd_waldbrand` | DWD Waldbrandindex | CC BY 4.0 | 3 h | ja |
| `dwd_gesundheit` | DWD Pollen/UV | GeoNutzV (Namensnennung DWD), Bedingungen laut Open-Data-Hinweisen des DWD | 1 h | ja |
| `tankerkoenig` | Tankerkönig | CC BY 4.0 | 2 min | ja |
| `mastodon_themen` | Themenradar Mastodon | keine; es werden keine Beiträge gespeichert, nur Zählungen je Hashtag | 1 h | nein |
| `hubeau_pegel` | Hub'eau Pegel | Licence Ouverte 2.0 (Etalab), nach Kenntnis | 15 min | ja |
| `wallonie_pegel` | SPW Pegel | keine ausdrückliche Lizenzangabe am Dienst gefunden | 15 min | ja |
| `brf` | BRF | keine offene Lizenz; nur Überschrift, Zeit und Link, kein Text, kein Bild | 15 min | ja |
| `meteoalarm` | MeteoAlarm | laut Anbieter gleichwertig CC BY 4.0 mit zusätzlichen Auflagen für die Weiterverbreitung | 10 min | ja |
| `bison_fute` | Bison Futé | Licence Ouverte 2.0 (Etalab) | 10 min | ja |
| `statec_sprit` | Höchstpreise Luxemburg | CC0 1.0 | 1 h | ja |
| `osm_tankstellen_lu` | Tankstellen Luxemburg | ODbL 1.0 (© OpenStreetMap-Mitwirkende) | 168 h | ja |
| `dwd_stationen` | DWD-Stationen | DWD GeoNutzV; Bright Sky Software MIT | 30 min | ja |
| `irceline` | IRCEL-CELINE | CC BY 4.0 (nach Kenntnisstand) | 30 min | ja |
| `kmi_stationen` | KMI-Stationen | CC BY 4.0 (nach Kenntnisstand) | 30 min | ja |

Vollständig mit Namensnennung: `sources.yaml` und die Seite „Quellen und Lizenzen“ der Anwendung.

### Dokumente

- `docs/baseline.md`
- `docs/betrieb.md`
- `docs/dsfa-entwurf.md`
- `docs/projektanweisung.md`
- `docs/rlp/` (Plan, Prompt, Status, offene Punkte)
- `docs/adr/` (Entscheidungen)

<!-- stand:end -->

## Mitarbeiten

Je Phase ein Branch `rlp/r<N>-<kurzname>` und ein Pull Request. Vor jedem Push: Tests grün, `docs/rlp/status.yaml` nachführen und `python tools/update_readme.py` ausführen. Die CI prüft mit `--check`, ob der Stand-Block zur Wirklichkeit passt.

## Lizenz und Nachweise

Code und Texte: GPL-3.0 (`LICENSE`). Daten haben ihre eigenen Lizenzen (Block oben, vollständig in `sources.yaml`). Kartendaten: © OpenStreetMap-Mitwirkende (ODbL), Protomaps. Verwaltungsgrenzen: © BKG (2026) dl-de/by-2-0.
