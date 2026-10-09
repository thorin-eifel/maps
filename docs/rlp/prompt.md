<!-- Umsetzungsprompt für Claude Code, Stand 9. Oktober 2026, freigegeben R0 bis R7. -->
# Auftrag: Lagebild Rheinland-Pfalz plus 80 km

Du bist Claude Code im Repository thorin-eifel/maps. Du baust das Lagebild "Was ist los bei uns?" (früher OSINT by CTW; seit dem 9. Oktober 2026 ein privates Projekt von Thorsten Schleicher, kein Firmenprojekt mehr) von einem Kreis mit 120 km um Irrel zu einer Fläche um: Landesgrenze Rheinland-Pfalz plus 80 km nach außen. Du arbeitest weitgehend selbstständig, Phase für Phase, und meldest dich an den unten genannten Haltepunkten.

## 1. Ton und Arbeitsweise

Deutsch, ruhig, knapp, sachlich. Kein Pathos, keine Emojis, keine Füllwörter, keine Beteuerungen. Code-Kommentare und Bezeichner auf Englisch sind in Ordnung, Texte im UI, Doku, Commit-Beschreibungen und Berichte auf Deutsch. Bei Unsicherheit sagst du es und prüfst nach, du rätst nicht. Jede Aussage über Daten, Größen oder Zeiten stützt sich auf eine Messung, die du im Bericht nennst.

## 2. Vorrang bei Konflikt

Rechtmäßigkeit und Datenschutz, dann Korrektheit der Daten, dann Stabilität, dann Optik. Ein hübsches Dashboard mit falschen Zahlen ist schlechter als eine hässliche Tabelle mit richtigen.

## 3. Harte Regeln (gelten in jeder Phase)

- Ereignisse statt Personen: Orte, Zeiten, Themen, Zahlen. Keine Klarnamen, keine Profile, keine Adressen, keine Bilder von Personen. Anfragen nach einer Person, Adresse oder einem Account gehören nicht ins Projekt.
- Jede Quelle steht in `sources.yaml` mit Lizenz, Namensnennung, Intervall, Ratenlimit, Datenschutzrisiko und Prüfdatum. Ohne Eintrag läuft kein Sammler. Vor einer neuen Quelle liest du Nutzungsbedingungen und Lizenz, nennst sie im Bericht und schreibst erst dann den Sammler. Sind die Bedingungen unklar oder verbieten sie die Nutzung, bleibt die Quelle aus und steht in `docs/rlp/offen.md`.
- Jede Kachel und jeder Alarm zeigt Quelle, Abrufzeit und Alter. Alte Daten werden als alt markiert, nicht versteckt. Fällt eine Quelle aus, bleibt der Rest stehen und die Kachel sagt "Quelle nicht erreichbar seit …".
- KI-Auswertung ist gekennzeichnet und optional. Es gibt keine Warnung, die nur ein Modell behauptet.
- Keine Drittanbieter-Skripte, keine externen Schriften oder CDNs, kein Tracking, keine Cookies außer technisch nötigen. Keine Standard-Kacheln von tile.openstreetmap.org.
- Keine Zugangsdaten im Code, in Logs oder im Repository. Schlüssel nur in `.env` (steht in `.gitignore`), im Repository liegt nur `.env.example`.
- Nicht ins Repository gehören: `data/`, `*.sqlite*`, `web/data/`, `web/tiles/*.pmtiles`, `web/tiles/dem/`, `build/`, `tools/bin/`, `.env`. Große Artefakte entstehen durch Skripte und werden mit Prüfsumme dokumentiert.
- Themenradar (Mastodon, Bluesky), Presseportal, Telegram, X und Meta bleiben draußen. Reddit bleibt draußen.
- Das Lagebild ist kein amtliches Warnsystem. Der Hinweis im Footer und im Impressumstext bleibt.
- Kein Docker. Betrieb mit Cron oder systemd, Python 3.11+, venv.
- Collector: Header-Kommentar (Zweck, Quelle, Lizenz, Intervall, Beispielaufruf), ehrlicher User-Agent, Timeout, Retry mit Backoff, Circuit Breaker, Idempotenz, Logging mit Anzahl und Dauer, Filter am Rand statt im UI.

## 4. Ausgangslage im Repository

Lies zuerst `README.md` (Projektanweisung und Betriebsanleitung), `sources.yaml`, `app/config.py`, `app/geo.py`, `app/export.py`, `app/payloads.py`, `app/collectors/base.py`, dann die Sammler, die du in der jeweiligen Phase anfasst, und `web/js/lage.js`. Verschaffe dir mit `pytest -q` und den Node-Tests (`tests/js/*.mjs`) einen Ausgangszustand. Notiere die Zahlen in `docs/baseline.md`. Bekannt und nicht von dir verursacht: `tests/test_wetter_quellen.py::test_metno_collector_sends_limited_coordinates_and_identifies` hängt an einer zeitabhängigen Fixture. Repariere ihn in R0 mit einer festen Uhr.

Architektur: Quellen, Sammler, Normalisierung mit Geofilter, SQLite, Export als JSON, statisches Frontend (Vanilla-ES-Module, MapLibre GL, eigene PMTiles aus Protomaps-Auszug, lokale Schriften), Hosting statisch auf IONOS per SFTP. Dazu die Tauri-Desktop-Hülle in `desktop/` mit lokalem Dienst `app/desktop.py`. Modus Mittelpunkt plus Radius bleibt für die Desktop-App erhalten.

## 5. Zielbild

Region = Landesgrenze Rheinland-Pfalz (BKG VG250, dl-de/by-2.0) plus 80 km Puffer, als Polygon. Vorfilter über den Kasten (ungefähr 48,25 bis 51,66 N, 5,0 bis 9,6 O, aus dem Polygon berechnet, nicht hartkodiert), Feinfilter über Punkt-im-Polygon. Startansicht Irrel, Kreis nicht gezeichnet. Quellen kommen auf Deutsch, Französisch, Luxemburgisch, Niederländisch und Englisch.

## 6. Git-Arbeitsweise

- Arbeite nie direkt auf `main`. Je Phase ein Branch `rlp/r<N>-<kurzname>`, je Aufgabe kleine Commits mit sachlicher deutscher Beschreibung (Was, Warum). Am Phasenende ein Pull Request nach `main` mit Bericht (Vorlage in Abschnitt 9).
- Vor jedem Push: Tests grün, `git status` ohne Daten und ohne Geheimnisse (`git diff --cached --stat` ansehen, keine Datei über 5 MB).
- Du holst vor dem Push `git fetch origin main` und rebased bei Bedarf, damit der Push klein bleibt.
- Du mergst nicht selbst. Das Zusammenführen und die Freigabe der nächsten Phase gehören dem Nutzer.
- Commits enden mit den Attributionszeilen, die die Sitzung vorgibt.
- Die `README.md` zeigt immer den aktuellen Stand. Vor jedem Push: `docs/rlp/status.yaml` nachführen (Stand, Pull-Request-Nummer), dann `python tools/update_readme.py` ausführen und die README mitcommitten. Die CI prüft das mit `--check`. Handgeschriebene Teile der README änderst du, wenn sich Schnellstart, Aufbau oder Regeln ändern.
- Seit dem 9. Oktober 2026 ist das Projekt privat: keine CTW-Marke, keine Firmenbezüge in neuen Texten. Betreiberangaben stehen in `web/impressum.html`.

## 7. Selbstständigkeit: was du allein entscheidest und wo du anhältst

Allein: Dateistruktur, Modulzuschnitt, Namen, Tests, Fixtures, Bauskripte, Refactorings innerhalb der Phase, Reihenfolge der Aufgaben, Wahl von Bibliotheken aus der vorhandenen Abhängigkeitsliste, Korrektur von Fehlern, die du findest (im Bericht erwähnen).

Anhalten und im Bericht als Frage stellen (nicht raten, nicht umgehen):
- eine neue Abhängigkeit mit Lizenz außerhalb von MIT, BSD, Apache-2.0, ISC, PSF oder MPL-2.0
- Quellen mit unklaren oder verbietenden Bedingungen
- alles, was personenbezogene Daten berühren könnte (Freitext, Fotos, Nutzernamen)
- Umstellung der Datenbank auf PostGIS (erst nach Messung und Vorlage der Zahlen)
- Änderungen am Hosting, an Zugangsdaten, am Upload-Ziel, an der Domain
- Löschen oder Überschreiben von Daten außerhalb des Repositories
- Aufwand, der die Schätzung der Phase um mehr als die Hälfte überschreitet

Wenn du in einer Phase hängst und die Frage warten kann, arbeite an einer anderen Aufgabe derselben Phase weiter und sammle die Fragen am Ende.

## 8. Sandkasten und Rechner des Nutzers

Die Sitzung läuft in einem Linux-Container ohne Zugriff auf alle Hosts (Overpass, Protomaps-Server und manche Landesportale sind dort nicht oder nur eingeschränkt erreichbar). Kacheln, das Geländemodell und große OSM-Auszüge baust du deshalb nicht im Container. Du lieferst dafür Skripte (`tools/`), eine Prüfroutine, die Dateigrößen und Kachelabdeckung mit Stichproben prüft, und eine Anleitung, die der Nutzer auf seinem Mac oder einem Server des Betreibers startet. Prüfe vorher mit einem kurzen Netztest (`curl -sI`) pro Host, was der Container erreicht, und halte das Ergebnis in `docs/rlp/netz.md` fest.

Wo das Gerät des Nutzers über die Desktop-Verbindung erreichbar ist, darfst du dort Skripte laufen lassen und Ergebnisse prüfen. Dateien, die du dorthin überträgst, prüfst du nach der Übertragung gegen die Größe und eine SHA-256-Summe, weil Übertragungen schon unvollständig angekommen sind. Mit dem Repository auf GitHub entfällt das für Code: der Mac holt per `git pull`.

Prüfen im Browser: Die Seite startet mit `#debug` und hat einen Prüfzugang (Ereignis `osint-debug`, Auftrag als JSON in `data-debug-in`, Antwort in `data-debug-out`). Er registriert sich erst, wenn die Karte geladen ist, die Seite lädt bei großer Fläche langsam. Eine Adresse, die sich nur im Hash unterscheidet, lädt die Seite nicht neu, hänge einen Abfrageparameter an. Skripte im Browser-Fenster brechen nach etwa 45 Sekunden ab, teile längere Abläufe.

## 9. Berichtsvorlage je Phase (Pull-Request-Text)

1. Ergebnis in zwei Sätzen.
2. Was läuft, mit Messwerten (Größen, Zeiten, Anzahl, Bildrate).
3. Was nicht läuft oder nur teilweise, und warum.
4. Neue Quellen mit Lizenz, Ratenlimit, Datenschutzbewertung.
5. Offene Fragen an den Nutzer, nummeriert, mit Empfehlung.
6. Wie man es prüft (Befehle, Seiten, Stichproben).
7. Aufwand gegenüber der Schätzung.

## 10. Phasen und Abnahmekriterien

### R0. Repository und Baseline

Aufgaben: aktuelle Codebasis aus dem Arbeitsstand übernehmen (nur Quellcode, Tests, Doku, Skripte, `sources.yaml`, `web/` ohne `data/`, Kacheln und Symbole, die im Skript erzeugt werden), `.gitignore`, `LICENSE` bleibt, `.env.example`, CI-Workflow (pytest, node-Tests, ruff oder flake8 nach vorhandener Konfiguration, `pip-audit`, `npm audit` nur wo es `package.json` gibt), `docs/adr/0001-region-rlp.md` (Entscheidung, Alternativen, Folgen), `docs/baseline.md`, `docs/rlp/plan.md` und `docs/rlp/prompt.md` (dieser Text).
Abnahme: CI grün, Klon in leeres Verzeichnis, `pip install -r requirements.txt`, `pytest -q` grün, Node-Tests grün, `docs/baseline.md` mit Zahlen.

### R1. Raumabstraktion

Aufgaben: `region.yaml` und `app/region.py` (Laden, Puffern mit `shapely`, falls Lizenz und Gewicht tragbar, sonst eigene Rechnung mit lokaler Projektion; Vorfilterkasten; `contains(lat, lon)`, `region_tag`, `kreis`). Grenzdaten aus BKG VG250 (Lizenz prüfen, Stand und Prüfsumme dokumentieren), vereinfacht auf ein Maß, das Punkttests schnell macht. Alle Verwendungen von `RADIUS_KM`, `CENTER_*`, `BBOX`, `haversine` im Code durchgehen (`grep`), ersetzen oder bewusst als Entfernung zu Irrel behalten. Texte, `sources.yaml` (`geo_bezug`), README, UI-Texte ("120 km") auf die Region umstellen. Tests: Punkte knapp innerhalb und außerhalb der Landesgrenze und des Puffers, Rheinufer, Luxemburg, Saarland, Grenzfall Straßburg, Polygon mit Loch oder Insel (Exklaven).
Abnahme: alle Tests grün, der Export für die alte Fläche bleibt inhaltlich gleich, wenn `region.yaml` auf den Kreis um Irrel gestellt wird (Regressionstest mit Fixture), Geschwindigkeitsmessung des Punkttests (Ziel: unter 20 Mikrosekunden je Punkt nach Vorfilter).

### R2. Kartenbasis

Aufgaben:
- `tools/build_osm_extract.sh` und Python-Hilfen: Geofabrik-Auszüge (Deutschland, Luxemburg, Belgien, Frankreich Nordost) laden, Prüfsumme speichern, mit osmium auf die Region zuschneiden, Ergebnis als PBF in `build/`.
- `tools/build_tiles.sh` erweitern: Region-Datei Zoom 0 bis 13 für den Kasten der Region, Ring Zoom 14 mit Polygon der Region ohne die Kerne, Städtekerne Zoom 15 je Stadtpolygon (nicht ein Rechteck), alles wiederaufsetzbar (Teilergebnisse behalten, Abbrüche am Server abfangen, Threads gedrosselt). Größen, Dauer und Kachelzahl je Datei im Bericht.
- Geländemodell: `tools/build_dem.py` für die neue Fläche (Terrarium-Kacheln Zoom 6 bis 12), Reliefbild und Orientierung (`build_terrain.py`, `build_orientation.py`) für die neue Fläche prüfen und anpassen.
- Suchindex und Gazetteer (`build_search_index.py`, `build_gazetteer.py`) für Rheinland-Pfalz und Randgebiete, Größenbudget: Suchindex unter 8 MB, lazy geladen.
- Gewässernetz (`build_gewaessernetz.py`) für Rhein, Mosel, Nahe, Lahn, Saar, Main, Neckar, Maas und große Zuflüsse.
- Prüfskript `tools/check_tiles.py`: Stichproben (zehn Orte über die Fläche, drei Zoomstufen), Kachel vorhanden, Gebäude vorhanden, Abdeckung der Region.
Abnahme: Karte lädt für die ganze Fläche, Zeit bis zur sichtbaren Karte unter 10 Sekunden auf der Referenzmaschine (Cache leer, lokaler Server), Größen gemessen und gelistet, Städtekerne zeigen Gebäude und Hausnummern, Ring zeigt Gebäudeumrisse, Rheinland-Pfalz-Stichproben vollständig.

### R3. Datenpipeline

Aufgaben: Sammler nacheinander durchgehen, je Sammler eine Aufgabenkarte `docs/rlp/sammler/<id>.md` (Änderung, Lizenzprüfung, Fixture, Test, Ratenlimit, Risiko).
- Warnungen: NINA für alle ARS-Schlüssel der Fläche (Liste aus `region`, Kreise und kreisfreie Städte in RLP, Saarland, die Teile von NRW, Hessen, BW im Puffer), DWD-Warnungen nach Warnzellen, Meteoalarm für LU, BE, FR.
- Pegel: PEGELONLINE alle Stationen der Fläche, Hochwasser RLP landesweit, LU, Wallonie, Hub'Eau; Zeitreihen auf Stundentakt gedrosselt, Warnstufen erhalten.
- Verkehr: Autobahn-API für alle Autobahnen der Fläche (Straßenliste aus der OSM-Auszugsdatei ableiten), LBM-Baustellen landesweit, Bison Futé, CITA; weitere Landesquellen nur nach Lizenzprüfung.
- Tankerkönig: Raster aus Abfragepunkten, Ratenlimit der Schnittstelle zuerst lesen, bei Überschreitung auf Ballungsräume und Grenzräume begrenzen.
- ÖPNV: GTFS-Gesamtdatensatz auf die Fläche zuschneiden, Größe messen, GTFS-RT nach Verfügbarkeit.
- Luft, Strahlung, Erdbeben, Wetter: Messstellen der Fläche, Sensor.Community aggregiert auf Raster mit gröberen Standorten, Kernkraftwerke in Reichweite als Randnotiz mit Herkunft.
- Medien: regionale Feeds nach Lizenzprüfung, nur Titel, Datum, Link.
- OSM-Sammler (`osm_natur`, `osm_infra`, `osm_routen`, `osm_anbau`, `osm_tankstellen_lu`): von Overpass auf den lokalen Auszug umstellen (`pyosmium` oder `osmium export`), gleiche Ausgabeformate, Fixtures aus echten Ausschnitten, Laufzeit und Größe messen. Vorhandene Abfragen und Filter sind in den Sammlern dokumentiert, die Regeln "nur benannt", "keine Gedenkorte", "keine Freitextfelder" gelten weiter.
- Datenbank: Messung (Schreibzeit je Zyklus, Dateigröße nach 7 Tagen, Exportdauer). Wenn der Export über 60 Sekunden braucht oder die Datei über 2 GB wächst, lege eine begründete Vorlage zur Umstellung auf PostgreSQL/PostGIS vor und halte an.
Abnahme: jeder Sammler hat Fixture-Test, Ausfalltest (Quelle down, Schemawechsel, Timeout) und Registereintrag. Ein vollständiger Zyklus über alle Quellen läuft in unter 10 Minuten. Stichprobe: kein personenbezogenes Datum in Datenbank und Logs.

### R4. Export und Auslieferung

Aufgaben: Raumzellen von 0,5 Grad, Dateien `data/z/<x>_<y>/<typ>.json` plus `data/manifest.json` (Version, Zeitstempel, Zellenliste, Größen, Prüfsummen). Startpaket (Warnband, Status, Zählwerte, Landesübersicht) unter 2 MB. Ereignisse, Pegel, Messstellen, OSM-Ebenen je Zelle. Inkrementeller Upload nur geänderter Zellen (Prüfsumme gegen Manifest). Jede Datei trägt Quelle, Abrufzeit, Lizenzvermerk. Atomare Schreibvorgänge (temporäre Datei, dann umbenennen) bleiben.
Abnahme: Export unter 60 Sekunden, ein Zyklus ohne Änderungen lädt nichts hoch, Zelle über 500 KB gibt eine Warnung, Tests für Zellenzuordnung (Punkt an Zellkante, Linien über mehrere Zellen, Flächen über mehrere Zellen).

### R5. Frontend

Aufgaben:
- `web/js/lage.js` in ES-Module zerlegen (Zustand, Karte und Basiskarte, Ebenenmenü, Panels, Debug, Licht, Landnutzung), ohne Verhaltensänderung. Vor dem Zerlegen Tests ergänzen, die das heutige Verhalten sichern (Menü, Ebenenschalter, Zeitfenster, Filter).
- Zellenlader: lädt Zellen im Bild plus einen Rand, verwirft weit entfernte, zeigt Ladezustand und Fehler je Zelle.
- Verdichtung bei kleinen Zoomstufen (Cluster oder Raster-Zählung), Ebenenbudget je Zoom, symbolweise Priorität.
- Landkreis- und Länderfilter, Suche über die Region, Warnband nach Landkreis.
- Profiling: Bildrate, Frame-Zeiten je Ebenengruppe (der Prüfzugang hat einen Befehl `perf`), Messpunkte Mainz, Trier, Kaiserslautern, Saarbrücken, Frankfurt, Luxemburg, jeweils Zoom 8, 12, 15, einmal Landesansicht. Ergebnis in `docs/perf.md`.
- Barrierefreiheit: Tastaturbedienung, Kontraste, Alternativtexte, Tabellenansicht zu jeder Karte.
- Menüstruktur bleibt thematisch (Warnungen, Wetter, Gewässer, Verkehr, Straßen, Gemeinwesen, Natur, Bewuchs, Kultur, Grenzen, Kartengrundlage). Neue Ebenen reihst du thematisch ein.
Abnahme: 60 fps beim Schwenken in der Landesansicht und an den Messpunkten auf der Referenzmaschine oder eine dokumentierte Begründung mit Gegenmaßnahme, Startzeit unter 10 Sekunden, Tests grün, keine Konsolenfehler im Normalbetrieb.

### R6. Betrieb und Härtung

Aufgaben: Zeitplan (Cron-Vorlage oder systemd-Timer, keine Container), Sammler-Gesundheitsprüfung je Quelle, Backup der Datenbank mit Wiederherstellungstest (`tools/backup.py` erweitern), Runbook "Sammler kaputt", Chaos-Test (eine Quelle abschalten, mehrere gleichzeitig, Netz weg, Platte voll bei Export), `pip-audit` und `npm audit`, Pinning und Aktualisierungsplan, Zeitzonen und Sommerzeit im Altersvergleich testen. 7-Tage-Dauerlauf mit Protokoll.
Abnahme: 7 Tage ohne Handeingriff, Protokoll mit Ausfällen und Wiederanlauf, Chaos-Test dokumentiert, Backup wiederhergestellt.

### R7. Abnahme

Aufgaben: Seite "Quellen und Lizenzen" vollständig, DSFA-Entwurf (`docs/dsfa-entwurf.md`) und Impressumstext um die neue Fläche ergänzt, Liste "was nicht funktioniert hat" (`docs/rlp/offen.md`), Vorführskript (zehn Minuten, zehn Stationen), README auf den Stand bringen.
Abnahme: Nutzer gibt frei oder nennt Mängel. Rechtliche Endabnahme vor Veröffentlichung macht der Nutzer mit Berater, nicht du.

## 11. Qualitätsregeln

- Tests für Normalisierer, Geofilter, Zellenzuordnung, jeden Sammler mit echter Beispielantwort als Fixture. Ein Schemawechsel beim Anbieter muss ein Test sofort zeigen.
- Ein Ausfall eines Sammlers darf die App nicht umwerfen. Das Frontend zeigt Ausfall und Alter.
- Performance misst du, bevor du optimierst. Zahlen kommen in den Bericht.
- Datenalter im UI gegen die Systemzeit prüfen, UTC und lokale Zeit sauber trennen.
- Dokumentation: README mit Betrieb, `sources.yaml`-Erklärung, Runbook, Architekturskizze, Beispiele zuerst.
- Selbstprüfung vor jeder Ausgabe: Steht bei jedem Datum die Quelle? Habe ich irgendwo eine Person statt eines Ereignisses gespeichert? Läuft das auch, wenn die Quelle morgen weg ist? Kann ich jeden Satz erklären, wenn jemand fragt, wieso er so dasteht?

## 12. Start

1. Lies die Dateien aus Abschnitt 4 und führe die Tests aus.
2. Lege `docs/rlp/plan.md` und `docs/rlp/prompt.md` an, falls sie fehlen.
3. Arbeite R0 ab, eröffne den Pull Request mit Bericht, halte an und warte auf die Freigabe für R1.
4. Danach R1 bis R7 in dieser Reihenfolge, jede mit eigenem Branch, Pull Request und Bericht.
