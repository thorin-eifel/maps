# Offene Punkte und Dinge, die nicht funktioniert haben

Wird in jeder Phase fortgeschrieben (Plan: `plan.md`). Stand R2.

## Technik

- **Unstabiler Test** `test_hochwasser_rlp_config_cached_and_second_run_no_duplicates` (2 von 25 Läufen rot, siehe `../baseline.md`). Vermutung: Zeitstempel der Testdaten und `utcnow()` im Sammler laufen auseinander. Mit fester Uhr (wie bei met.no) beheben, sobald R3 den Sammler anfasst.
- **Bundle-Kennung und launchd-Labels** heißen noch `de.ctw.osint`. Umbenennen verschiebt das Datenverzeichnis der Desktop-App und braucht eine Migration. Nicht in R1.
- **Texte mit festem Radius** in `docs/betrieb.md`, `web/einrichtung.html`, `tools/build_tiles.sh`, `tools/build_dem.py`, `app/tilebuild.py`, `app/collectors/dwd_radar.py` und `web/js/*` (Kreis, Vignette, Sweep nutzen `meta.radius_km`) werden mit Karte (R2) und Frontend (R5) angepasst. Im Polygonmodus liefert `meta.radius_km` den umschließenden Kreis, die Darstellung ist bis R5 nur für den Kreis richtig.
- **Länderkennung außerhalb Deutschlands** (LU, BE, FR): `Gliederung.kreis()` kennt nur VG250. Für ausländische Punkte bleibt die bisherige Logik der Sammler (`region_tag`). Eine einheitliche Länderzuordnung braucht Landesgrenzen (z. B. Natural Earth, gemeinfrei) und kommt in R3, wenn sie gebraucht wird.

- **Ladezeit der Karte im Browser** nicht gemessen (nur Übertragungsmenge, `docs/rlp/r2-kartenbasis.md`). Die Baseline zeigte 30 bis 45 s Beobachtung; Ursache nicht geklärt.
- **Gewässernetz** für die neue Fläche erst nach R3 (braucht die Pegelliste der Sammler). **Lokaler OSM-Auszug** (Geofabrik) für R3.
- **Neue Archive** liegen auf dem Mac unter `~/r2/final`, `~/r2/dem` (Sandkasten-VM), noch nicht in `web/tiles`. Einspielen und Upload gehören zu R4.
- **Heimatkern** (Zoom 15 um Irrel) bleibt als Kern erhalten, abweichend von der Regel "nur Städte" aus Entscheidung 5. Vorschlag steht im PR.

## Recht und Lizenz

- **Quellen im privaten Betrieb neu bewerten.** Einige Entscheidungen hingen daran, dass der Betreiber eine GmbH war (adsb.lol, Blitzdaten/LightningMaps). Seit dem 9. Oktober 2026 ist das Projekt privat. Eine öffentliche Seite bleibt trotzdem ein Angebot an Dritte; die Bewertung gehört in die Rechtsprüfung vor dem öffentlichen Start, nicht in diese Datei. Bis dahin bleibt alles wie zuvor entschieden.
- **Impressum und Datenschutzerklärung** nennen jetzt Name, Anschrift und E-Mail. Name in der Schreibweise "Schleicher" (laut Profil); bitte gegen den Personalausweis prüfen. Datenschutz: Angaben zu IONOS-Logs und Auftragsverarbeitung fehlen weiter.
