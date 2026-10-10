# R3 Datenpipeline: Messwerte und Entscheidungen

Stand: 10. Oktober 2026. Region: Rheinland-Pfalz plus 80 km (`OSINT_REGION=region-rlp.yaml`). Alle Läufe kamen aus dem Sandkasten gegen die echten Dienste, in eine leere Wegwerf-Datenbank. Ausnahme: Overpass (OSM) ist von dort nicht erreichbar.

## Lauf aller aktiven Quellen (je einmal, leere Datenbank)

| Quelle | Dauer | Ergebnis |
|---|---|---|
| NINA (mapData, 5 Kanäle) | 5 s | 5 Warnungen |
| DWD-Warnungen | 1 s | 1 |
| Autobahn-API (40 Strecken, geprüft gegen 113) | 68 s | 1.343 Ereignisse |
| LBM Baustellen RLP | 3 s | 1.970 Ereignisse |
| Bison Futé / CITA / Erdbeben (EMSC) / ADS-B | je 1 bis 2 s | 1 / 13 / 4 / 23 |
| GTFS-RT Deutschland | 2 s | 748 Verspätungen |
| PEGELONLINE | 27 s | 125 Stationen, 29.231 Werte |
| Hochwasser RLP | 3 s | 240 Stationen, 43.365 Werte |
| Pegel Luxemburg, Hub'Eau, Wallonie | 2 / 21 / 12 s | 40, 101, 139 Stationen; 26.828 / 4.322 / 3.230 Werte |
| UBA Luft | 117 s | 119 Stationen, 3.601 Werte (4 Stationen ohne Daten, gemeldet) |
| BfS ODL | 2 s | 328 Stationen |
| DWD-Stationen (200) | 80 s | 198 Stationen, 603 Werte |
| DWD Waldbrand (40 gestreut) | 33 s | 40 Stationen, keine ab Stufe 3 |
| Sensor.Community, IRCELINE, KMI, MeteoLux | 1 bis 2 s | 217 / 17 / 6 / 1 Stationen |
| DWD-Radar, Wind, EUMETSAT-Blitze | 3 / 3 / 116 s | Bilder; Blitze: 1 von 9 Zeitschritten fehlgeschlagen, wird gemeldet |
| Volksfreund, BRF | 1 s | 0 und 2 Schlagzeilen verortet (Rest andere Rubrik oder ohne Ort) |
| MeteoAlarm | 3 s | 0 aktive Warnungen im Gebiet (211 Meldungen geprüft) |

Nicht gelaufen: **Tankerkönig** und **NASA FIRMS** (Schlüssel fehlt im Sandkasten; der Fehler ist klar benannt), alle **OSM-Sammler** (Overpass nicht erreichbar).

Die Datenbank wiegt nach diesem Lauf 28 MB (113.000 Messwerte, 4.200 Ereignisse, 1.500 Stationen).

## Was sich geändert hat

- **NINA**: ein Abruf je Kanal (`mapData`) statt 132 Abrufe je Kreis; Warnungen ohne Fläche fallen weg und werden gezählt; Cache je Version.
- **Tankerkönig**: Der Betreiber begrenzt auf **einen Request je Minute** (Startseite, gelesen am 9.10.2026). Der Sammler fragt jetzt je Lauf **einen** Punkt des 59er-Gitters, alle 2 Minuten, reihum (zustandslos aus der Uhrzeit). Ein Umlauf dauert knapp 2 Stunden; jeder Preis trägt den Zeitstempel seines Abrufs. Im Irrel-Modus: fünf Punkte, 10 Minuten.
- **Autobahn**: 40 Kandidaten-Strecken, gegen die Streckenliste der API geprüft; langsame Dienste (Baustellen) alle 15 Minuten.
- **LBM**: eine Abfrage statt Seiten. Der WFS sortiert ohne `sortBy` nicht stabil: zwei Läufe lieferten 200 abweichende Kennungen, das erzeugte bei jedem Lauf Dubletten. Jetzt zwei Läufe, 1.970 und 0 neue.
- **MeteoAlarm**: Grenzen NUTS **2013** (so nennt der Feed die Gebiete) für BE22, BE33 bis BE35, FR211, FR411 bis FR414, FR421, LU00. **Niederlande fehlen**: Der Feed nutzt dort EMMA_ID statt NUTS, ohne Zuordnungstabelle nicht abbildbar.
- **Hub'Eau, UBA, DWD-Stationen, Waldbrand, Pollen, Radar, Wind, Blitze**: Gebiet, Grenzen und Pausen angepasst, siehe `sources.yaml`.
- **Overpass-Sammler** (Infra, Natur, Routen, Anbau): Abfragen **kachelweise** (`app/collectors/osm_tiles.py`, 20 Kacheln statt eines Kastens), Dubletten an den Rändern fallen über die OSM-Kennung weg, ein ausgefallener Kachelzugriff lässt die ganze Art ausfallen (alter Stand bleibt). Obergrenzen angehoben (Natur 60.000, Routen 800 je Art und 250.000 Punkte, Anbau 120.000). **Nicht live gemessen.**

## Wiederholungslauf (Idempotenz)

Zweiter Lauf direkt nach dem ersten: Autobahn, NINA, Hochwasser, Hub'Eau, Wallonie, PEGELONLINE ergeben keine Dubletten, Messwerte wachsen nur um die neu gemeldeten (Hochwasser +372 von 43.365). LBM war nicht idempotent und ist behoben (oben).

## Datenbank: SQLite bleibt

28 MB für 113.000 Messwerte, rund 200 Byte je Zeile mit Indizes. Hochrechnung auf 30 Tage Beobachtungsdauer bei den heutigen Pegel-, Luft- und Stationsraten: etwa 2,5 Millionen Zeilen, also 400 bis 500 MB. Das ist **geschätzt, nicht gemessen**. SQLite trägt das ohne Probleme (ein Schreiber, alle Sammler nacheinander). Eine Umstellung auf PostGIS ist nicht nötig; entschieden wird neu, wenn der 7-Tage-Dauerlauf in R6 die echte Größe zeigt. Hebel davor: `retention_days` für Messwerte auf 14 senken.

## Ausfalltest

`tests/test_ausfall_alle_quellen.py` fährt **jeden** Sammler im Register gegen vier Störungen (HTTP 503, Zeitüberschreitung, HTML statt Daten, leeres JSON) und prüft: kein Absturz, nichts geschrieben, keine Erfolgsmeldung bei Ausfall. Dazu je Quelle die bisherigen Fixture-Tests. Stand: 334 Python-Tests und 41 JS-Tests grün.

## Abweichungen vom Plan

- **OSM nicht auf lokalen Geofabrik-Auszug umgestellt.** Overpass bleibt, mit Kacheln. Grund: Ein lokaler Auszug braucht einen Verarbeitungsschritt (osmium) und Betrieb auf dem Server; das lohnt sich erst, wenn die Overpass-Kachelläufe in der Praxis scheitern. Die Sammler laufen wöchentlich, die Last ist klein (Fair Use). Die Entscheidung gehört zur Messung auf dem Mac.
- **Keine neuen Medienfeeds** (SWR u. a.). Lizenz und robots.txt sind nicht geprüft; ohne Prüfung kommt nichts dazu. Presseportal und Mastodon bleiben aus.
- **Niederlande** bei MeteoAlarm nicht eingebunden (siehe oben).

## Nächster Schritt auf dem Mac

```bash
export OSINT_REGION=region-rlp.yaml
echo 'TANKERKOENIG_API_KEY=...' >> .env          # Schlüssel nie in den Chat
python -m app.collect --once --only osm_natur osm_infra osm_routen osm_anbau   # misst Dauer, Mengen, Fehler von Overpass
python -m app.collect --once --only tankerkoenig                               # ein Punkt je Lauf
```
