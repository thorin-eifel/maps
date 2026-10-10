# Offene Punkte und Dinge, die nicht funktioniert haben

Wird in jeder Phase fortgeschrieben (Plan: `plan.md`). Stand R4.

## Technik

- **Unstabiler Test** `test_hochwasser_rlp_config_cached_and_second_run_no_duplicates` (2 von 25 Läufen rot, siehe `../baseline.md`). Vermutung: Zeitstempel der Testdaten und `utcnow()` im Sammler laufen auseinander. In R3 in 15 Einzelläufen nicht reproduziert (0 rot); bleibt beobachtet, Behebung mit fester Uhr, falls er wieder auftritt.
- **Bundle-Kennung und launchd-Labels** heißen noch `de.ctw.osint`. Umbenennen verschiebt das Datenverzeichnis der Desktop-App und braucht eine Migration. Nicht in R1.
- **Texte mit festem Radius** in `docs/betrieb.md`, `web/einrichtung.html`, `tools/build_tiles.sh`, `tools/build_dem.py`, `app/tilebuild.py`, `app/collectors/dwd_radar.py` und `web/js/*` (Kreis, Vignette, Sweep nutzen `meta.radius_km`) werden mit Karte (R2) und Frontend (R5) angepasst. Im Polygonmodus liefert `meta.radius_km` den umschließenden Kreis, die Darstellung ist bis R5 nur für den Kreis richtig.
- **Länderkennung außerhalb Deutschlands** (LU, BE, FR): `Gliederung.kreis()` kennt nur VG250. Für ausländische Punkte bleibt die bisherige Logik der Sammler (`region_tag`). Eine einheitliche Länderzuordnung braucht Landesgrenzen (z. B. Natural Earth, gemeinfrei); in R3 nicht gebraucht, kommt mit dem Länderfilter in R5.

- **Ladezeit der Karte im Browser** nicht gemessen (nur Übertragungsmenge, `docs/rlp/r2-kartenbasis.md`). Die Baseline zeigte 30 bis 45 s Beobachtung; Ursache nicht geklärt.
- **Gewässernetz** für die neue Fläche: jetzt möglich (Pegellisten liegen vor: PEGELONLINE 125, Hochwasser RLP 240, Hub'Eau 101, Wallonie 139, LU 40 Stationen), Bau gehört zu R4/R5.
- **Neue Archive** liegen auf dem Mac unter `~/r2/final`, `~/r2/dem` (Sandkasten-VM), noch nicht in `web/tiles`. Einspielen und Upload gehören zu R4.
- **Heimatkern** (Zoom 15 um Irrel) bleibt als Kern erhalten, abweichend von der Regel "nur Städte" aus Entscheidung 5. Vorschlag steht im PR.

## Recht und Lizenz

- **Quellen im privaten Betrieb neu bewerten.** Einige Entscheidungen hingen daran, dass der Betreiber eine GmbH war (adsb.lol, Blitzdaten/LightningMaps). Seit dem 9. Oktober 2026 ist das Projekt privat. Eine öffentliche Seite bleibt trotzdem ein Angebot an Dritte; die Bewertung gehört in die Rechtsprüfung vor dem öffentlichen Start, nicht in diese Datei. Bis dahin bleibt alles wie zuvor entschieden.
- **Impressum und Datenschutzerklärung** nennen jetzt Name, Anschrift und E-Mail. Name in der Schreibweise "Schleicher" (laut Profil); bitte gegen den Personalausweis prüfen. Datenschutz: Angaben zu IONOS-Logs und Auftragsverarbeitung fehlen weiter.

## R3: offen geblieben

- **Overpass-Sammler nicht live gemessen** (Infra, Natur, Routen, Anbau): Overpass ist aus dem Sandkasten nicht erreichbar. Lauf auf dem Mac, Messung von Dauer, Mengen und Fehlern; danach Entscheidung lokaler Geofabrik-Auszug ja/nein. Mengen der Obergrenzen (Natur 60.000, Routen 250.000 Punkte, Anbau 120.000) sind geschätzt.
- **Tankerkönig** nicht live gelaufen (Schlüssel nur auf dem Mac). Umlauf knapp 2 Stunden bei einem Request alle 2 Minuten; ob das für die Anzeige reicht, zeigt der erste Tag. Betreiber nennt zusätzlich "nicht öfter als alle 5 Minuten" für Dauerabfragen einzelner Systeme; wir bleiben bei 1 Request je 2 Minuten und fragen im Zweifel beim Betreiber nach.
- **NASA FIRMS** braucht `FIRMS_MAP_KEY`, im Sandkasten nicht gesetzt (kein Fehler des Sammlers).
- **MeteoAlarm Niederlande** fehlt (EMMA_ID statt NUTS im Feed). Zuordnung nur mit Tabelle des Anbieters; bei Bedarf anfragen.
- **Medienfeeds** (SWR RLP u. a.) nicht eingebunden: Lizenz und robots.txt ungeprüft. Entscheidung des Betreibers, ob geprüft werden soll.
- **EUMETSAT-Blitze**: bei der größeren Fläche 116 s Laufzeit, einzelne Zeitschritte laufen in Fehler (1 von 9, wird als "teilweise" gemeldet). Beobachten.
- **Datenmenge Messwerte**: Hochrechnung 400 bis 500 MB bei 30 Tagen, nicht gemessen. 7-Tage-Lauf in R6 klärt SQLite vs. PostGIS.
- **Nur GTFS-Statik/GTFS-RT Deutschland** bewertet nach Menge (748 Verspätungen); Zuschnitt auf die Fläche der Fahrpläne nicht gesondert geprüft.

## R4: offen geblieben

- **Upload nicht gegen den echten Webspace getestet** (kein `lftp` im Sandkasten). Trockenlauf und Plan sind getestet. Erster echter Lauf auf dem Mac.
- **Zelle `z/16_98/events.json` 509 KB** (Budget 500 KB): gemeldet, nicht gekürzt. Geometrien liegen über Zellgrenzen mehrfach (Ereignisse 5,6 MB statt 3,5 MB); Vereinfachung nach Zoomstufe gehört in R5.
- **Flachdateien** (`events.json` usw.) bleiben bis R5; `events.json` dort weiter bei 2.000 Einträgen, im alten Frontend fehlen damit Ereignisse im Osten der Region. Abhilfe ist das Zellenfrontend, nicht eine größere Flachdatei.
- **Radar, Wind, Suchindex** sind global (1,2 MB / 110 KB / 136 KB), nicht in Zellen; Nachladestrategie in R5.
- **Herzschlag** (162 KB je Zyklus) trägt den Quellenzustand. Wird das zu viel, kann `start.json` auf Zustand und Warnband verkleinert werden.
- Neue Kachelarchive (913 MB) und Höhenmodell (676 MB) liegen weiter auf dem Mac; Einspielen und Hochladen ist nicht Teil dieses PR (siehe PR-Text, Frage 1).

## Aus R5 (Frontend)

- **60 fps:** auf dem Mac (M4, Chrome) erreicht, auch mit den RLP-Archiven und dem synthetischen RLP-Bestand (`docs/perf.md`). Offen: Tauri-Hülle, echte Sammlerdaten für ganz RLP, Gestentest.
- **Verdichtung** ist eine Zähl-Ebene je Rasterzelle unter Zoom 8 plus Mengenbegrenzung der Einzelmeldungen (`ebenenBudget`), kein MapLibre-Clustering. Pegel und Umweltstationen werden nicht verdichtet, sondern erst ab Zoom 8 geladen; darunter sind die Reiter Gewässer und Umwelt leer.
- **Dichte-Ebene per Tastatur:** Die Zahlen lassen sich nur mit der Maus anklicken. Ersatz für Tastaturnutzer sind Zoomtasten, der Landkreisfilter und die Tabelle (Warnungen sind auch unter Zoom 8 in der Tabelle).
- **Länderkennung** außerhalb Deutschlands bleibt `region_tag` des Sammlers; `EU` und ein deutsches Kürzel ohne Kreis ergeben „unbekannt“ und fallen bei gesetztem Filter heraus. Landesgrenzen (Natural Earth) wären die saubere Lösung.
- **Kraftstoff:** Statistik und Luxemburg-Block liegen landesweit im Startpaket, die Stationen kommen aus den Zellen; die Flachdatei kappt bei 200 Stationen, die Zellen nicht.
- **Flachdateien** werden weiter exportiert (Rückfall ohne Manifest). Entscheidung des Betreibers: in R6 abschaffen, sobald alle Stellen auf Zellen laufen.
- **Suchindex** für ganz RLP: Rechenzeit gemessen (bis 300 000 Einträge unter 100 ms), Dateigröße mit echten Namen ungemessen.
- **Abruf je Ereignis:** Im Zellenbetrieb ist `fetched_at` die letzte erfolgreiche Abrufzeit der Quelle, nicht die der einzelnen Meldung.

## Aus LGB Daten (Okt. 2026)

- Rechtliche Endabnahme der Einbindung (Nutzungsbedingungen gelesen, dl-de/by-2-0, Einbindung erlaubt; `lizenz_geprueft` bleibt auf false).
- Datenschutzerklärung nennt den Dritt-Abruf; Wortlaut vor dem öffentlichen Start vom Datenschutzbeauftragten prüfen lassen.
- Katalog (`web/geo/lgb.json`) ist ein Stand; wer pflegt ihn, wenn das LGB Dienste ändert? Vorschlag: Neubau bei jedem Release, Test schlägt bei Abweichung der Gruppen an.
- GetFeatureInfo (Objektabfrage per Klick) und Legenden fehlen bewusst; beides wären weitere Abrufe beim Dritten.
- "Cross Compliance Erosion" ist auf der Onlinekarten-Seite des LGB gelistet, hat aber keinen WMS in der OGC-Liste; Rückfrage beim LGB, ob es einen gibt.

## Aus Landesdaten (Okt. 2026)

- Lizenzen und Betreiber je Dienst stammen aus dem Geoportal und sind nicht einzeln gelesen; `lizenz_geprueft` bleibt false, Endabnahme steht aus.
- Statistisches Landesamt (64 Dienste), SGD Nord ROK und LANIS fehlen, weil die Zertifikatsprüfung in der Bauumgebung scheiterte. Erneut bauen von einem Rechner mit vollständigem Zertifikatsspeicher; falls die Ketten wirklich unvollständig sind, beim Betreiber melden.
- Kommunale Dienste (Stadt Trier, Verbandsgemeinden) sind nicht aufgenommen; Entscheidung: nur Landesstellen. Spätere Erweiterung wäre ein dritter Katalog, nicht eine Mischung.
- Dienste nur mit WMS 1.1.1 (13 im Geoportal selbst, u. a. Forsten) fehlen; ein 1.1.1-Pfad wäre ein eigener Parser und eigene Kachelanfragen.
- Der Katalog ist ein Stand; Pflege wie bei `lgb.json`: Neubau bei jedem Release.

## Aus Vignette entlang der Landesgrenze (Okt. 2026)

- Radar-Sweep zeichnet weiter um den Mittelpunkt Irrel (Kreis); die Vignette dahinter ist jetzt eine andere Form. Entscheidung offen, ob der Sweep der Landesform folgt oder bleibt.
- Die Karte zieht nur so weit, wie Kacheln und Daten reichen: Die Kacheln auf dem Mac decken noch 120 km, die Vignette lässt Rheinland-Pfalz plus 80 km klar. Bis die großen Kacheln eingespielt sind, sieht man im Osten leere Fläche statt Schwarz.
- Kleine Knicke im Verlauf an einspringenden Ecken der Grenze sind Eigenschaft des Abstandsfelds, kein Fehler.
