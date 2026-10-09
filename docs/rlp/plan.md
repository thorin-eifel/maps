# Lagebild Rheinland-Pfalz: Ablaufplan

Stand 9. Oktober 2026. Teil A ist der Ablaufplan. Der Prompt für Claude Code steht getrennt in `prompt.md`. Ziel-Repository: github.com/thorin-eifel/maps.

## Teil A: Ablaufplan zur Freigabe

### Ausgangslage

Heute deckt das Lagebild einen Kreis von 120 km um den CTW-Firmensitz in Irrel ab. Rund 40 Quellen laufen über Python-Sammler in eine SQLite-Datenbank, ein Export schreibt JSON-Dateien, ein statisches Frontend (Vanilla-JS, MapLibre, eigene PMTiles-Karte) liest sie vom IONOS-Webspace. Es gibt eine Desktop-Hülle (Tauri) mit lokalem Dienst. Die Kartendateien sind zusammen etwa 530 MB groß, die Startseite braucht noch 30 bis 45 Sekunden, bis die Karte steht.

Was wir beim Arbeiten gelernt haben und was den Plan prägt:

- Overpass ist für diese Fläche zu schmal. Schon bei 120 km antwortet die Instanz mit 429 und 504, die Weinberg-Abfrage allein lieferte 9,6 MB. Für ganz Rheinland-Pfalz geht das nur mit einem lokalen OSM-Auszug.
- Das Frontend ist eine einzige Datei (`lage.js`, rund 150 KB) mit Zustand, Karte, Menü und Ebenen. Für die doppelte Fläche muss sie in Module zerlegt werden.
- Die Radiuslogik (Mittelpunkt, Haversine, `RADIUS_KM`) steckt an vielen Stellen. Sie wird durch eine Fläche ersetzt.

### Zielbild

Die Region ist die Landesgrenze von Rheinland-Pfalz plus 80 km nach außen, als Polygon. Grob liegt der Kasten bei 48,25 bis 51,66 Grad Nord und 5,0 bis 9,6 Grad Ost, etwa 330 mal 380 km. Das ist rund 1,75-mal die Fläche des heutigen Kastens. In Reichweite liegen damit unter anderem Saarland, Luxemburg, Lothringen bis Nancy, Nordelsass bis Straßburg, Ostbelgien bis Lüttich, Aachen, Köln, Bonn, Frankfurt, Darmstadt, Mannheim, Karlsruhe und Stuttgart-Rand. Die Startansicht bleibt Irrel. Der Kreis wird weiter nicht gezeichnet.

Unverändert bleiben die Leitplanken aus der Projektanweisung: Ereignisse statt Personen, Quelle, Alter und Lizenz an jedem Datum, kein Tracking, keine Drittanbieter, Themenradar und Presseportal bleiben draußen, Telegram bleibt draußen.

### Entscheidungen, die ich von dir brauche

Jede Entscheidung hat eine Empfehlung. Ohne Widerspruch setze ich die Empfehlung um.

1. **Fläche als Polygon.** Landesgrenze aus BKG VG250 (dl-de/by-2.0), 80 km Puffer, Vorfilterkasten daraus abgeleitet. Empfehlung: ja. Die Alternative, ein Rechteck, schneidet Hessen und Baden-Württemberg unsauber ab.
2. **OSM-Daten lokal statt Overpass.** Geofabrik-Auszüge (Deutschland, Luxemburg, Belgien, Frankreich-Nordost) wöchentlich laden, mit osmium auf die Region zuschneiden, daraus alle OSM-Ebenen bauen (Landmarken, Infrastruktur, Routen, Anbauflächen, Luxemburger Tankstellen). Empfehlung: ja. Das spart die Fair-Use-Last und macht den Bau reproduzierbar.
3. **Datenbank.** SQLite trägt die heutige Menge. Bei der zwei- bis dreifachen Ereigniszahl und Zeitreihen für etwa 300 Pegel würde ich auf PostgreSQL mit PostGIS umstellen. Empfehlung: erst messen (Phase 3), dann umstellen, wenn der Export länger als 60 Sekunden braucht oder die Datei über 2 GB geht.
4. **Auslieferung.** Der Webspace bleibt statisch. Die JSON-Dateien werden in Raumzellen zerlegt (Raster von 0,5 Grad) mit einem kleinen Manifest, das Frontend lädt nur, was im Bild liegt. Empfehlung: ja. Ein Python-Server auf dem Webspace geht nicht.
5. **Kartenumfang.** Eine Region-Datei bis Zoom 13 für die ganze Fläche, Ring bei Zoom 14, Gebäude und Hausnummern bei Zoom 15 nur für Städte (Mainz, Koblenz, Trier, Kaiserslautern, Ludwigshafen, Worms, Speyer, Landau, Neuwied, Bad Kreuznach, dazu Luxemburg, Saarbrücken, Metz). Geschätzt 450 bis 700 MB für die Region-Datei, Rest nach Messung. Empfehlung: ja, mit gemessenen Größen im Bericht von Phase 2.
6. **Desktop-App.** Sie behält den Modus "Mittelpunkt plus Radius", die Web-Fassung läuft mit der Landesfläche. Empfehlung: ja, beides aus einer Codebasis über die Region-Konfiguration.
7. **Quellen.** Neue Landesquellen (Hochwasser, Straßen, Behörden) werden einzeln auf Lizenz geprüft, bevor ein Sammler entsteht. Wo die Bedingungen unklar sind, bleibt die Quelle aus und steht in der Liste "offen". Empfehlung: ja. LGB-Daten stehen weiter hinten an.
8. **Veröffentlichung.** Die DSFA und das Impressum werden um die größere Fläche ergänzt, die rechtliche Abnahme bleibt bei dir und deinem Berater. Empfehlung: ja.

### Phasen

Die Aufwände sind Schätzungen, keine Messwerte. Eine Einheit ist ein konzentrierter Arbeitstag von Claude Code samt deiner Prüfzeit.

**R0. Repository und Baseline (1 Einheit).**
Heutigen Stand ins Repository übernehmen (ohne Daten, Kacheln, Zugangsdaten), `.gitignore`, Lizenz, CI (pytest, node-Tests, Lint, Abhängigkeitsprüfung), Entscheidungsdatei `docs/adr/0001-region-rlp.md`. Messbaseline festhalten: Dateigrößen, Ladezeit, Zahl der Ereignisse, Exportdauer. Ergebnis: grüne CI auf `main`, Baseline in `docs/baseline.md`.

**R1. Raumabstraktion (2 Einheiten).**
Neue Region-Konfiguration (`region.yaml`: Name, Grenzquelle, Puffer, Startansicht). `geo.in_region()` mit Polygon, schneller Vorfilter über den Kasten, Tests mit Grenzfällen (Rheinufer, Luxemburger Grenze, Saarland, Punkt im Puffer, Punkt knapp draußen). Alle Stellen mit `RADIUS_KM`, `CENTER_*`, `BBOX` und "120 km" im Code, in Texten, in `sources.yaml` und im UI auf die Region umstellen. Die Entfernung zu Irrel bleibt als optionale Angabe, die Zuordnung zu Landkreis und Land (`region_tag`, `kreis`) kommt neu. Ergebnis: die bestehende Fläche läuft unverändert, nur aus der Konfiguration gespeist.

**R2. Kartenbasis (3 Einheiten).**
Lokaler OSM-Auszug (Geofabrik), Zuschnitt, Protomaps-Kacheln für die neue Fläche, Städtekerne bei Zoom 15, Ring bei Zoom 14. Geländemodell für die ganze Fläche (Terrarium-Kacheln bis Zoom 12), Reliefbild, Orientierung. Suchindex und Gazetteer für Rheinland-Pfalz und die Randgebiete, Gewässernetz für Rhein, Mosel, Nahe, Lahn, Saar, Main, Neckar, Maas und Zuflüsse. Der Bau läuft als Skript und ist wiederholbar. Weil die Kacheln aus dem Sandkasten nicht erreichbar sind, läuft dieser Teil auf dem Mac oder dem CTW-Server, Claude Code liefert Skript, Prüfskript und Größenbericht. Ergebnis: Karte für die ganze Fläche, gemessene Größen, Ladezeit unter 10 Sekunden bis zur sichtbaren Karte.

**R3. Datenpipeline (4 Einheiten).**
Sammler quellenweise auf die Fläche bringen, je Quelle nach dem Muster "Lizenz prüfen, Fixtures, Test, Register, Lauf". Umfang je Quelle in der Tabelle unten. OSM-Sammler auf den lokalen Auszug umstellen. Datenbank messen und, falls nötig, auf PostGIS umstellen. Ergebnis: alle bisherigen Quellen liefern für die Fläche, jede mit Fixture-Test und Ausfalltest.

**R4. Export und Auslieferung (2 Einheiten).**
Raumzellen, Manifest, Größenbudgets (Startpaket unter 2 MB, je Zelle unter 500 KB, Karte lädt nur den Bildausschnitt nach). Stempel für Quelle und Alter in jeder Datei, "veraltet" bleibt serverlos berechnet. Hochladen über das bestehende Skript, aber inkrementell (nur geänderte Zellen). Ergebnis: Export in unter 60 Sekunden, Upload nur der Änderungen.

**R5. Frontend (3 Einheiten).**
`lage.js` in Module zerlegen (Zustand, Karte, Ebenenmenü, Panels, Debug), Zellen-Lader, Verdichtung bei kleinen Zoomstufen (Cluster für Pegel, Stationen, Meldungen), Ebenenbudget je Zoom, Landkreis- und Länderfilter, Suche über die ganze Fläche, Warnband nach Landkreis. Profiling im Browser und in der Tauri-Hülle, Maßzahl: Bildrate beim Schwenken und Zoomen auf der Referenzmaschine. Barrierefreiheit prüfen (Tastatur, Kontraste, Tabellenansicht je Karte). Ergebnis: flüssig bei 60 fps in der Landesansicht und an Messpunkten (Mainz, Trier, Kaiserslautern, Saarbrücken, Frankfurt).

**R6. Betrieb und Härtung (2 Einheiten).**
Zeitplan (Cron oder systemd, kein Docker), Backup mit Wiederherstellungstest, Quellenstatus je Region, Runbook "Sammler kaputt", Chaos-Test (Quelle abschalten, Kartenfläche prüfen), pip-audit und npm-audit, Aktualisierungsplan der Pakete. 7-Tage-Dauerlauf ohne Handeingriff. Ergebnis: Protokoll des Dauerlaufs.

**R7. Abnahme (1 Einheit).**
Vorführung, Liste "was nicht funktioniert hat", DSFA- und Impressums-Nachtrag, Seite "Quellen und Lizenzen" vollständig. Ergebnis: Freigabe oder Mängelliste.

Jede Phase endet mit einem Pull Request, einem Bericht (was läuft, was nicht, was gemessen wurde) und deiner Freigabe für die nächste.

### Quellen: was sich je Sammler ändert

| Bereich | Heute | Neu für Rheinland-Pfalz plus 80 km |
|---|---|---|
| Warnungen | NINA für wenige Kreise, DWD, Meteoalarm | NINA für alle ARS-Schlüssel der Fläche (RLP, Saarland, Teile von NRW, Hessen, BW), DWD nach Warnzellen, Meteoalarm für LU, BE, FR |
| Pegel | PEGELONLINE, Hochwasser RLP, LU, Wallonie, Hub'Eau | Alle Pegel in der Fläche, Rhein bis Main und Neckar, Hochwasser RLP landesweit, Zeitreihen gedrosselt |
| Verkehr | Autobahn-API, LBM, Bison Futé, CITA | Autobahn-API für alle Autobahnen der Fläche, LBM landesweit, Hessen und NRW nur über offene Landesquellen nach Prüfung |
| Tanken | Tankerkönig im Umkreis, LU-Höchstpreise | Tankerkönig über Raster (Ratenlimit prüfen, sonst nur Ballungsräume), LU und Saarland-Grenze beibehalten |
| ÖPNV | GTFS, GTFS-RT | Zuschnitt des Gesamtdatensatzes auf die Fläche, Größe messen |
| Luft, Strahlung | UBA, ODL, Sensor.Community | Alle Messstellen der Fläche, Sensoren aggregiert auf Raster, Kernkraftwerke in Reichweite als Randnotiz (Cattenom, Tihange, Doel liegt außerhalb, Philippsburg, Neckarwestheim, Mülheim-Kärlich stillgelegt) |
| Wetter | DWD, MeteoLux, MET Norway | DWD-Stationen der Fläche, Radar bundesweit zugeschnitten, Wind-Raster größer |
| Medien | Volksfreund, BRF | Regionale Feeds nach Lizenzprüfung (SWR Rheinland-Pfalz, weitere), nur Titel, Datum, Link |
| OSM-Ebenen | Overpass | Lokaler Geofabrik-Auszug, gleiche Ebenen |
| Erdbeben | EMSC | Zuschnitt auf die Fläche |

### Risiken

- **Datenmenge im Browser.** Die doppelte Fläche mit Zellenlader lösen, nicht mit mehr Rechenzeit. Messpunkte in R5 entscheiden.
- **Kachelbau am Protomaps-Server.** Große Auszüge brechen gern ab. Der Bau muss wiederaufsetzbar sein, Alternative ist der Planetenauszug lokal.
- **Ratenlimits.** Tankerkönig und Overpass sind die Engpässe, die Pläne dafür stehen oben.
- **Mac-Übertragung.** Dateien kamen heute zweimal abgeschnitten auf dem Mac an. Jede Übertragung wird durch Größenvergleich geprüft, besser noch durch Prüfsumme. Das Repository auf GitHub löst das Problem, weil der Mac dann per `git pull` holt.
- **Lizenz und Recht.** Landesquellen sind nicht alle offen. Unklare Quellen bleiben aus.
- **Aufwand.** 18 Einheiten sind eine Schätzung ohne Puffer. Mit Messung und Nacharbeit gehe ich eher von 22 bis 26 aus.

### Freigabe

Erteilt am 9. Oktober 2026: "Freigabe R0 bis R7 mit Empfehlungen". Den Arbeitsstand aus dem Mac-Ordner übernimmt Claude Code selbst ins Repository. Der Umsetzungsprompt steht in `docs/rlp/prompt.md`.
