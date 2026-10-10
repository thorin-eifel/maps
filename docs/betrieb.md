# Was ist los bei uns?

> **Hinweis:** Diese Betriebsanleitung beschreibt den Stand vor dem Umbau auf Rheinland-Pfalz plus 80 km. Die Fläche kommt jetzt aus `region.yaml` (`app/region.py`); Angaben zu "120 km", Kartengrößen und Kacheln werden in R2 bis R5 angepasst. Der aktuelle Stand steht in der `README.md`. Launchd-Labels und Bundle-Kennung heißen noch `de.ctw.osint`: Umbenennen würde das Datenverzeichnis der Desktop-App verschieben und ist deshalb nicht erfolgt.

Die aktuelle Lage rund um unsere Heimat. Privates Open-Source-Projekt (bis Oktober 2026 ein Schaufenster der CTW Computer-Irrel GmbH).

Regionales Lagebild aus offenen Daten für die Südeifel und ihre Nachbarregionen (zurzeit 120 km um Irrel; Ziel ist Rheinland-Pfalz plus 80 km, siehe `docs/rlp/plan.md`): Warnungen, Verkehr, Pegel, Wetter. Kein Tracking, keine US-Cloud, kein Überwachungswerkzeug: gespeichert werden Orte, Zeiten und Zahlen, keine Personen.

Stand: **Phase 1 (MVP)**. Kein amtliches Warnsystem, kein Ersatz für NINA oder die Leitstelle.

## Wie es läuft (statisch, für IONOS-Webspace)

Der Webspace führt nur HTML, CSS und JavaScript aus, kein Python. Deshalb zwei Teile:

```
Sammelstelle (ein Rechner des Betreibers, Python, Cron alle 5 Min.)          IONOS-Webspace (statisch)
  Quellen → Collector → Geo-Filter → SQLite → Export → JSON-Dateien ──SFTP──▶ web/data/*.json
                                                                            web/ (HTML, CSS, JS, MapLibre)
                                                                                  ▲
                                                                     Browser holt Dateien, rechnet
                                                                     Zeitfenster und Alter selbst
```

Die Sammelstelle braucht Python 3.11+, Internet und `lftp`. Sie kann jeder Rechner sein, der dauerhaft läuft: ein Server, ein Mini-PC, ein Raspberry Pi. Fällt sie aus, bleibt die Seite stehen und sagt es: Das Frontend rechnet Alter und Zustand gegen die Uhr des Besuchers und zeigt „Datenstand veraltet“, sobald der Export älter als 20 Minuten ist.

## Schnellstart

```bash
# Sammelstelle einrichten
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q && node --test tests/js/rules.test.mjs     # 60 + 4 Tests
cp .env.example .env && chmod 600 .env                         # OSINT_CONTACT eintragen

# Lokal ansehen, ohne Upload
python -m app.collect --once          # alle Quellen einmal
python -m app.export                  # schreibt web/data/*.json, manifest.json, start.json und z/<x>_<y>/ (Zellen, siehe docs/rlp/r4-export.md)
deploy/publish.sh --delta            # lädt nur geänderte Dateien hoch, Manifest zuletzt
python -m http.server 8000 -d web     # → http://localhost:8000

# Seite auf den Webspace (einmalig und bei Änderungen an HTML/JS/CSS)
deploy/publish.sh --site --dry-run
deploy/publish.sh --site

# Dauerbetrieb: Cron alle 5 Minuten (Vorlage: deploy/crontab.example)
deploy/run-cycle.sh                   # abrufen (nur Fälliges) → exportieren → hochladen
```

## Einrichtung IONOS

1. **SFTP-Zugang** im IONOS-Kundencenter anlegen (Hosting → SFTP & SSH). Host, Benutzer und Passwort bzw. SSH-Schlüssel in `.env` eintragen: `IONOS_SFTP_HOST`, `IONOS_SFTP_USER`, `IONOS_SFTP_KEY` (oder `IONOS_SFTP_PASSWORD`), `IONOS_REMOTE_DIR`, `PUBLISH_ENABLED=1`.
2. **Host-Schlüssel** einmalig ins `known_hosts`, den Fingerabdruck vorher gegen die Angabe im Kundencenter prüfen: `ssh-keyscan -t ed25519 "$IONOS_SFTP_HOST" >> ~/.ssh/known_hosts`. Das Skript prüft den Schlüssel strikt.
3. **HTTPS** für die Domain im Kundencenter aktivieren (SSL-Zertifikat). Die `.htaccess` leitet auf HTTPS um.
4. **Erster Upload:** `deploy/publish.sh --site`, danach `deploy/run-cycle.sh`.
5. **Prüfen:** `curl -sI https://<domain>/` muss die Header `Content-Security-Policy`, `X-Content-Type-Options` und `Strict-Transport-Security` zeigen. Fehlen sie, wertet der Webspace die `.htaccess` nicht aus. Die CSP steht dann trotzdem als Meta-Tag in jeder Seite; `frame-ancestors` geht nur per Header.
6. **Auftragsverarbeitung:** IONOS verarbeitet die Zugriffsprotokolle. Ohne Vertrag zur Auftragsverarbeitung mit IONOS nicht öffentlich schalten (siehe `docs/dsfa-entwurf.md`).

## Aufbau

| Datei / Ordner | Inhalt |
|---|---|
| `sources.yaml` | Quellenregister. Ohne Eintrag läuft kein Collector. Speist die Seite „Quellen und Lizenzen“. |
| `app/collectors/` | `nina`, `dwd_warnungen`, `brightsky`, `pegelonline`, `autobahn`, Basisklasse `base.py` (Retry, Backoff, Circuit Breaker) |
| `app/collect.py` | Runner: `--once`, `--due` (nur Fälliges, für Cron), `--only`, `--healthcheck` |
| `app/export.py`, `app/payloads.py` | Datenbank → `meta, events, gewaesser, wetter, status, sources` als JSON |
| `web/` | Die Seite: `index.html`, `status.html`, `quellen.html`, `js/`, `css/`, `geo/`, `vendor/maplibre-gl/`, `.htaccess` |
| `web/js/rules.js` | Zeitfenster und Quellenzustand, rechnen im Browser gegen die aktuelle Uhr |
| `deploy/` | `run-cycle.sh`, `publish.sh`, `crontab.example` |
| `tools/` | `backup.py`, `build_orientation.py` (Kreisgrenzen für die Karte) |
| `tests/` | Python-Tests, `tests/js/` (Node), `fixtures/` mit echten Antworten |

Die Sammelstelle liest aus dem Netz und schreibt in ihre Datenbank und den Exportordner, sonst nichts. Der Webspace enthält nur die Seite und die fertigen JSON-Dateien: keine Datenbank, keine Zugangsdaten, kein Code, der etwas ausführt.

## Das Quellenregister (`sources.yaml`)

Pflichtfelder je Quelle: `id, name, betreiber, url, lizenz, namensnennung, intervall, ratenlimit, auth, geo_bezug, datenschutz_risiko, aktiv, zuletzt_geprüft, collector`. Dazu `params`, `lizenz_geprueft` und optional `erstlauf` (`spaeter` für große, langsame Abfragen: die Desktop-App holt sie erst nach dem ersten Export im Hintergrund; derzeit die fünf OSM-Quellen). Steht dort `false`, wurde der Endpunkt live getestet, der Lizenztext aber noch nicht an der Primärquelle bestätigt. Die Seite „Quellen und Lizenzen“ zeigt das offen an. **Vor dem öffentlichen Start muss jede Zeile auf `true`.**

Neue Quelle: erst Nutzungsbedingungen, Lizenz und Ratenlimit klären, dann Registereintrag, dann Collector (Vorlage: `pegelonline.py`), Fixture mit echter Antwort, Test.

## Ereignisse und Messwerte

Ereignisse (Warnung, Verkehr, Verkehrslage, Flug) tragen `source_id, type, title, summary, severity, confidence, geometry, region_tag, valid_from, valid_to, fetched_at, raw_ref, ai_generated, model` und optional `attrs` (Art, Verzögerung, Tempo, Kurs; nie Kennungen). Messreihen (Pegel, Wetter) liegen in eigenen Tabellen. Schweregrade: `info, notice, warning, critical`; `critical` (rot) gibt es nur bei CAP `Severe`/`Extreme`.

Snapshot-Semantik: Ein Collector liefert die vollständige aktive Menge seiner Quelle, was fehlt, wird inaktiv. Nur bei **vollständigem** Abruf. Ein halber Abruf (eine Region oder Autobahn nicht erreichbar) schreibt, räumt aber nichts ab.

Zeitfenster („Jetzt“, 24 Std., 7 Tage): Der Export liefert die Obermenge für 7 Tage, der Browser filtert. Die Regel steht zweimal (`app/db.py`, `web/js/rules.js`), beide sind getestet.

## Betrieb

### Runbook: „Collector kaputt“

1. `https://<domain>/status.html` öffnen: Zustand, letzter Erfolg, Fehler in Folge, Fehlertext, letzte Läufe. Steht dort „Export erzeugt vor … Std.“ in Orange, liegt das Problem bei der Sammelstelle oder beim Upload, nicht bei einer Quelle.
2. Auf der Sammelstelle: `tail -n 100 /var/log/osint-cycle.log`. Details einer Quelle: `.venv/bin/python -m app.collect --once --only <id> --log-level DEBUG`.
3. Häufige Ursachen:
   - **HTTP 4xx**: Endpunkt oder Parameter geändert. Doku des Betreibers lesen, Fixture neu aufnehmen, Collector anpassen.
   - **„Schlüssel … fehlt“ / „ohne 'features'“**: Schema geändert. Der Collector rät nicht, er meldet. Fixture ersetzen, Test rot sehen, dann fixen.
   - **Timeout, 5xx, 429**: Quelle down oder drosselt. Retry mit Backoff läuft, nach 5 Fehlläufen pausiert der Collector 15 Minuten (Circuit Breaker). Abwarten oder Intervall erhöhen.
   - **Upload schlägt fehl**: `deploy/publish.sh --data` von Hand laufen lassen. Meist Zugang, Host-Schlüssel oder Netz. Der nächste Cron-Lauf versucht es erneut.
4. Quelle vorübergehend abschalten: `aktiv: false` in `sources.yaml`.

Bei Ausfall bleibt die Seite stehen: „Quelle nicht erreichbar seit …“, die letzten guten Daten sind sichtbar und als veraltet markiert (Chaos-Test in `tests/test_payloads_export.py`).

### Backup

`tools/backup.py` sichert die Datenbank der Sammelstelle (Online-Backup, Integritätsprüfung, 14 Stück, Cron 03:15). Wiederherstellen: Cron pausieren, Datei als `data/osint.sqlite` zurückkopieren. Der Webspace braucht kein Backup außer dem Projektordner selbst: alles dort lässt sich mit `publish.sh --site` neu aufspielen. Ein Wiederherstellungstest gehört vor den Livegang in den Ablauf.

### Updates

Abhängigkeiten sind gepinnt (`requirements.txt`), vor Updates `pip-audit -r requirements.txt`. MapLibre liegt unter `web/vendor/` (Version 6.11.2, BSD-3-Clause, Dateiendung auf `.js` geändert, siehe `README.txt` dort). Seite geändert: `deploy/publish.sh --site`.

## Datenschutz und Sicherheit in Kürze

- Keine personenbezogenen Daten. Externe Texte werden beim Sammeln bereinigt (`app/sanitize.py`), das Frontend setzt sie nur per `textContent`. Ein Test prüft, dass keine Kontaktadresse oder Zugangsdaten in den Exportdateien landen.
- CSP ohne `unsafe-inline`, keine Drittanbieter-Anfragen (per Browsertest geprüft), keine Cookies, keine Speicherung der Ansicht, kein `eval`.
- Zugriffsprotokolle führt der Hoster (IONOS), nicht die Anwendung. Speicherdauer und IP-Kürzung dort prüfen.
- Sammelstelle: keine Zugangsdaten im Code, `.env` mit Rechten 600 und in `.gitignore`. Für den Upload ein eigener SFTP-Zugang, der nur auf den Zielordner beschränkt ist.
- Entwürfe: `docs/dsfa-entwurf.md`; „Datenschutz“ und „Impressum“ sind Platzhalter bis zur rechtlichen Endabnahme.

## Was in Phase 1 nicht funktioniert oder offen ist

1. **Lizenzen nicht bestätigt.** Alle zwölf Quellen laufen, kein Lizenztext ist an der Primärquelle geprüft (`lizenz_geprueft: false`). NINA und Autobahn-API nennen in ihrer OpenAPI-Beschreibung keine Datenlizenz. Am heikelsten ist `hochwasser_rlp`: Die JSON-Schnittstelle der Seite hochwasser.rlp.de ist nicht als offene API dokumentiert und trägt keine Lizenzangabe. Vor jeder öffentlichen Nutzung beim Landesamt für Umwelt RLP anfragen; solange bleibt es ein interner Demo-Betrieb.
2. **DWD-Warnungen nur gegen Doku gebaut.** Am Testtag lag bundesweit keine Warnung vor, die Fixture `dwd_wfs_SYNTHETISCH_landkreise.json` ist nachgebaut. Beim ersten echten Warnfall Feldnamen prüfen und durch eine echte Aufnahme ersetzen. Verifiziert: Endpunkt, Layer, BBox-Achsenreihenfolge (lon,lat; lat,lon liefert leere Antworten).
3. **Kein Live-Test auf IONOS.** Upload, Skripte und Seite laufen gegen einen lokalen SFTP-Server und einen lokalen Webserver. Ob `.htaccess` (Header, MIME-Typen, Umleitung) auf dem Tarif greift, zeigt erst der erste Upload (`curl -sI`, siehe oben).
4. **Kein Server-Push.** Die Seite holt die Dateien alle 60 Sekunden. Die Aktualität ist damit höchstens so gut wie der Cron-Takt (5 Minuten) plus Abrufintervall der Quelle.
5. **Keine Basiskarte.** Radius, Kreisgrenzen (DWD), Orte, Ereignisse. Luxemburg und Belgien haben keine Grenzen. Eigene Tiles folgen in Phase 2 und brauchen auf statischem Webspace Platz (PMTiles-Datei, wenige zehn MB, Range-Requests). Ob IONOS die unterstützt, ist vorher zu klären.
6. **Pegel aus zwei Quellen.** PEGELONLINE (WSV: Mosel, Saar) und die Hochwasservorhersagezentrale RLP (Prüm, Kyll, Sauer, Our, Nebengewässer; WSA-Stellen werden dort verworfen, damit nichts doppelt steht). Eigene Hochwasserstufen gibt es nicht; angezeigt wird der Zustand laut Legende der jeweiligen Quelle. Die Luxemburger Pegel kommen nur soweit, wie die RLP-Seite sie führt.
7. **Baustellen-Zeiträume** stehen nur als Fließtext in der Autobahn-API. Der erste Termin wird per Muster gelesen, sonst bleibt der Beginn leer und der Eintrag „(geplant)“.
8. **Öffentliche Bright-Sky-Instanz** im Dauerbetrieb ist unhöflich. Eigene Instanz in Phase 2 (braucht dann etwas mehr als den Cron-Rechner).
9. **Sammelstelle ist ein Einzelpunkt.** Fällt sie aus, wird die Seite ehrlich veraltet, aber nicht aktueller. Wer das nicht will, braucht einen zweiten Rechner oder Überwachung auf `--healthcheck`.
10. **7-Tage-Dauerlauf** (Definition of Done) steht aus.
11. **Rate Limiting** für eine öffentliche Demo entfällt bei statischen Dateien weitgehend, Missbrauch fängt der Hoster ab. Trotzdem im Vertrag nachsehen.
12. **Offene Punkte aus Abschnitt 12** der Projektanweisung (Name/Domain, Hosting, GPU, Quellenpflege, Luxemburg) sind weiter offen. Hosting ist mit IONOS entschieden; „GPU“ entfällt, solange die lokalen Modelle (Phase 3) nicht kommen.

## Sammelstelle auf dem Mac (launchd)

Stand: läuft auf dem Mac des Betreibers, Python 3.11 in `.venv`, Zyklus alle 5 Minuten.

```
launchctl print gui/$(id -u)/de.ctw.osint-cycle | grep -E 'state|last exit'
tail -f ~/Library/Logs/osint-cycle.log
launchctl bootout gui/$(id -u)/de.ctw.osint-cycle      # anhalten
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/de.ctw.osint-cycle.plist   # starten
```

Lokale Ansicht: http://127.0.0.1:8080 (Job `de.ctw.osint-web`, nur localhost).
Fallstricke: Schläft der Mac, steht der Zyklus; die Seite zeigt dann nach 20 Minuten
"Datenstand veraltet". Upload bleibt aus, bis `PUBLISH_ENABLED=1` und die IONOS-Werte in `.env` stehen
(lftp fehlt noch: `brew install lftp`). `OSINT_CONTACT` in `.env` ist noch der Platzhalter.

## Luftverkehr (adsb.lol) und warum keine Schiffe

**Flugzeuge:** Quelle adsb.lol (ODbL 1.0 laut Betreiber, Ratenlimit unveröffentlicht, ein Abruf alle 15 Sekunden in der Live-Schleife, siehe „Live, Stau, Icons“). OpenSky ist bewusst draußen: dort braucht jede kommerzielle Stelle, auch bei interner Nutzung, eine Lizenz, und CTW ist eine GmbH. Gespeichert wird nur Position, Höhe, Geschwindigkeit, Kurs und grobe Klasse. Hex-Code, Rufzeichen, Kennzeichen und Typ werden nie geschrieben. Die Ereignis-ID ist ein Hash mit täglich wechselndem Salz (Tabelle `kv_cache`, nicht im Export): innerhalb eines Tages überschreibt der Upsert die Position, es entsteht keine Spur, über Tage lässt sich nichts verknüpfen. Transpondercodes 7500/7600/7700 erscheinen als Hinweis mit Konfidenz 0,4, nicht als Warnung. Die Ebene ist auf der Karte standardmäßig aus. Fixture: `tests/fixtures/adsblol_point_ANONYMISIERT_SYNTHETISCH.json` (echte Struktur, Kennungen ersetzt, Positionen teils erfunden).

**Schiffe: nicht gebaut.** Für Mosel, Saar und Sauer gibt es keine offen lizenzierten Positionsdaten. Inland-AIS der WSV ist nicht öffentlich. aisstream.io nennt keine Nutzungsbedingungen, keinen Umfang für Binnengewässer und keine Zusage zu gewerblicher Nutzung (die Anfragen dazu im Issue-Tracker sind unbeantwortet); außerdem identifiziert die MMSI Schiffe, bei Sportbooten also Halter. Möglich wären: Anfrage an das WSV Trier, ein eigener AIS-Empfänger an der Mosel (dann eigene Daten, keine Lizenzfrage), oder nur Schleusen- und Pegeldaten, die schon da sind.

## Baustellen und Sperrungen RLP (Mobilitätsatlas)

Quelle: WFS `https://maps.mobilitaetsatlas.de/geoserver/ows` (Layer `mwvlw:baustelle`, `mwvlw:verlauf`), derselbe Bestand, den die Karte auf mobilitaetsatlas.de zeigt. Er umfasst Bundes-, Landes-, Kreis- und Gemeindestraßen der Verkehrsbehörden in Rheinland-Pfalz sowie Meldungen aus Luxemburg (`region_tag` LU). Aktualisierung im Dienst alle 10 Minuten, Verzug bis 20 Minuten. Abfrage mit Bounding Box, Feinfilter auf 80 km am Rand.

Entscheidungen: (1) Meldungen der Autobahn GmbH aus diesem Dienst werden verworfen, der Autobahn-Collector liefert sie. (2) Der Verlauf (Linie) ersetzt den Punkt, wo er vorhanden ist. (3) Das Feld `ansprechpartner` (Behörden-Postfächer) wird nie gelesen, im Freitext werden E-Mail-Adressen und Telefonnummern entfernt. (4) Typen: G Vollsperrung und F Fahrtrichtung gesperrt = Warnung, C halbseitig und N Lkw-Sperre = Hinweis, B Einschränkung = Info; `_GEPLANT` bekommt den Zusatz „(geplant)“ im Titel. Umleitungen (`mwvlw:umleitung`) sind noch nicht eingebaut.

Offen: Der Dienst nennt keine Lizenz (Capabilities ohne Fees/AccessConstraints, die Erläuterung ebenfalls). Anfrage an das Mobilitätsatlas-Team, Referat 8702 im Ministerium: mobilitaetsatlas@rlp.de. Der Betreiber weist selbst darauf hin, dass nicht alle Kommunen liefern.

Die Presseseite des LBM (lbm.rlp.de/service/presse-aktuelles) ist keine Datenquelle für die Karte: kein Feed, keine Koordinaten, nur Pressetext. Sie taugt später für das Modul „Meldungen“ (nur Titel, Datum, Dienststelle und Link), das ohne Kartenpunkt auskommt. Phase 2.

## Basiskarte (eigene PMTiles)

Die Karte nutzt keine Kacheln von Dritten. `web/tiles/region.pmtiles` ist ein Ausschnitt des Protomaps-Basiskartenbaus (OSM-Daten, ODbL): Bounding Box 4.63/48.61/8.28/51.08 (120-km-Radius plus Rand), Zoom 0 bis 13 (ca. 285 MB), Luxemburg inklusive. Tiefer als Zoom 13 bricht der Abruf für die ganze Region am Protomaps-Server immer wieder ab, und Hausnummern stehen erst in Zoom 15 in den Kacheln. Darum gibt es `web/tiles/core.pmtiles` (ca. 120 MB): derselbe Build, Kern 5.90/49.49/7.02/50.21 um Irrel (rund 80 x 80 km) mit Zoom 0 bis 15. Nur die Ebenen `buildings` und `address_label` lesen daraus; fehlt die Datei, bleibt die Karte ohne Gebäudedetail. Außerhalb des Kerns gäbe es demnach kaum Gebäude; deshalb gibt es `web/tiles/ring.pmtiles` (ca. 140 MB): derselbe Kartenbau, nur Zoom 14, nur im 120-km-Kreis außerhalb des Kerns (GeoJSON mit Loch, damit nichts doppelt liegt). Das Frontend zeichnet die Gebäudeebenen aus Kern und Ring; fehlt der Ring, fehlen die Umrisse außerhalb des Kerns. Hausnummern gibt es nur im Kern, im Ring nie. Der Ring kam aus einem neueren Protomaps-Build als Region und Kern (die alten Builds liegen nicht mehr am Server); beim nächsten Gesamtbau mit `tools/build_tiles.sh` sind alle drei wieder aus einem Guss. Gebaut mit `tools/build_tiles.sh [JJJJMMTT]` (lädt nur den Ausschnitt per Teilabruf, nicht den Planet; braucht die `pmtiles`-CLI in `tools/bin/`). Das Frontend liest die Datei im Browser per HTTP Range (pmtiles.js, MapLibre); Stil aus `@protomaps/basemaps` mit Option `lang: 'de'` (nur damit liefert die Bibliothek Beschriftungen), ohne Symbol-Layer (POIs, Einbahnpfeile; sie bräuchten Sprite-Bilder). Schrift: nur „Noto Sans Regular“ aus `web/fonts/` (Bereiche 0–511 und Satzzeichen). Hell = Grau, Dunkel = Dunkel.

Ehrlich bei Ausfall: Fehlt die Datei oder kann der Server keine Teilabrufe, bleibt die Karte ohne Basis benutzbar und der Kartenhinweis sagt „Basiskarte nicht verfügbar“.

**Vor dem Produktivbetrieb auf IONOS prüfen:** `python tools/check_range.py https://<domain>/tiles/region.pmtiles` muss „Teilabrufe funktionieren“ melden (Status 206, keine Kompression). `deploy/publish.sh --site` lädt die Dateien mit hoch (beim ersten Mal rund 410 MB, ein Schritt für sich; die Datei ändert sich nur bei neuem Kartenbau). Die `.htaccess` nimmt `.pmtiles` bewusst aus der Kompression aus. Antwortet der Webspace mit 200 statt 206: Kachelverzeichnis (`z/x/y.pbf`) statt einer Datei bauen, das läuft auf jedem Webspace.

Die lokale Ansicht auf dem Mac nutzt `deploy/serve-local.py` (versteht Range), nicht `python -m http.server`.

Offen: Beschriftungen (Straßen, Orte) brauchen Schriftdateien (Glyphen) auf dem Server; Zoom über 13 wird nur hochskaliert; Kartenstand ist der Build vom 29.09.2026, Aktualisierung von Hand.

## Live, Stau, Icons

**Flüge live.** Ein Webspace ohne Server kann nicht schieben, und der Browser darf keine Drittserver anfragen (CSP, Datenschutz). „Live“ heißt deshalb: Die Live-Schleife (`python -m app.live`, launchd-Job `deploy/de.ctw.osint-live.plist`) holt adsb.lol alle 15 Sekunden (Untergrenze 10 s), schreibt nur `data/aircraft.json` und `data/status.json` und lädt sie hoch, wenn `PUBLISH_ENABLED=1` (höchstens alle `OSINT_LIVE_PUBLISH_S`, Standard 30 s; läuft ein Upload noch, wird übersprungen). Der Browser holt `aircraft.json` alle 15 s, solange die Ebene an und der Tab sichtbar ist, und lässt die Flugzeuge dazwischen auf Kurs und Tempo weiterrücken (`advance()` in `rules.js`, rein optisch, nichts wird gemerkt; bei „weniger Bewegung“ im System aus). Der Fünf-Minuten-Zyklus überspringt Quellen mit `params.live` (`--skip-live`; `OSINT_LIVE=0` in `.env` legt sie zurück in den Zyklus). Steht die Schleife, laufen die Punkte nach 90 s ab und die Quelle zeigt „veraltet“. Ratenlimit von adsb.lol ist unveröffentlicht: vor öffentlichem Start nachfragen.

```
python -m app.live --once             # ein Durchlauf zum Testen
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/de.ctw.osint-live.plist
tail -f ~/Library/Logs/osint-live.log
```

**Stau und zähfließender Verkehr.** Kommt aus derselben Autobahn-API (`warning` mit `abnormalTrafficType`): `QUEUING_TRAFFIC` = Stau, `SLOW_TRAFFIC` = zähfließend, `STATIONARY_TRAFFIC` = Stillstand, dazu Verzögerung (Minuten) und Durchschnittstempo. Eigener Ereignistyp `congestion`, gezeichnet als Linie von Anfang bis Ende der Meldung (gerade Verbindung, nur Näherung des Straßenverlaufs). Stau ab 30 Minuten Verzögerung und Stillstand sind `warning`, gewöhnlicher Stau `notice`, zähfließend `info`. Sie erscheinen nicht im Warnband, das bleibt für NINA/DWD/Pegel. Eine eigene Stufe „Stop-and-go“ kennt die API nicht. Der Autobahn-Lauf kommt jetzt alle 3 Minuten (vorher 10). Grenzen: nur Autobahnen (A1, A48, A60, A64), keine Bundes- und Landesstraßen, kein Luxemburg. Die Kennungen tragen den Vermerk INRIX; das gehört in die Lizenzanfrage an die Autobahn GmbH. Fixture: `tests/fixtures/autobahn_A64_warning_STAU_SYNTHETISCH.json` (echte Struktur, Orte verlegt).

**Icons.** Einzige Quelle: uxwing.com. Die Lizenz erlaubt Nutzung in Websites, auch gewerblich, ohne Namensnennung, mit Änderung; verboten sind Weiterverkauf, Weiterverbreitung und Unterlizenzierung. Darum liegen die SVGs nicht im Repository (`.gitignore`), `tools/fetch_icons.sh` holt sie (Rollenname → uxwing-Name steht im Skript). Die fertige Webseite liefert sie aus, das ist Nutzung in einer Website. Nicht in ein öffentliches Repository oder Paket legen. Im HTML als CSS-Maske (`css/icons.css`, Farbe folgt dem Text), auf der Karte als Bitmap (`js/icons.js`: Plakette in Stufenfarbe, Flugzeug mit Umriss). Fehlen die Dateien, fällt die Karte auf Kreise zurück, der Text trägt die Bedeutung.

## Höhenrelief

Schummerung, Höhenfärbung, Höhenlinien (mit Beschriftung der Hauptlinien) und Höhenanzeige unter dem Zeiger.
Datenbasis: Terrarium-Kacheln der Mapzen Terrain Tiles (AWS Open Data; hier EU-DEM und SRTM), einmalig geholt:

    .venv/bin/python tools/build_dem.py            # Zoom 6 bis 12, ca. 200 MB nach web/tiles/dem/ (Ausschnitt 48.9–50.8 N, 5.0–7.9 O)
    .venv/bin/python tools/build_dem.py --max-zoom 11   # gröber, deutlich kleiner

Die Kacheln liegen nicht im Repository (`.gitignore`) und müssen mit auf den Webspace (`web/tiles/dem/`, inkl. `README.txt`, die dient als Prüfdatei).
Höhenlinien rechnet `web/vendor/maplibre-contour` (BSD-3) im Browser in einem Worker; Ziffern kommen aus `web/fonts/` (Noto Sans, OFL).
Fehlt `tiles/dem/README.txt`, bleibt die Karte ohne Relief und läuft normal. Code: `web/js/relief.js`.
Namensnennung steht auf `quellen.html`. Höhenwerte sind Raster (ca. 30 m), keine Vermessung.

## Weitere Quellen (Umwelt)

| Quelle | Collector | Inhalt | Takt |
|---|---|---|---|
| Hochwasservorhersagezentrale RLP | `hochwasser_rlp` | Pegel (89 Messstellen im Radius), Klassen laut Quellenlegende, Ereignis ab HW-Stufe 2 | 15 min |
| BfS ODL | `bfs_odl` | Ortsdosisleistung (Sonden im Radius), Ereignis erst ab eigener Orientierungsschwelle 0,3 / 1,0 µSv/h | 30 min |
| UBA Luftdaten | `uba_luft` | Luftqualitätsindex und PM10, PM2.5, NO2, O3 (RLP/Saarland), Ereignis ab Index 3 | 30 min |
| EMSC | `emsc` | Erdbeben der letzten 7 Tage, ab M 3,0 Hinweis, ab M 4,0 Warnung; Sprengungen werden verworfen | 15 min |
| DWD Radar | `dwd_radar` | Regenradar als Bild, wird auf dem Mac geholt und mit hochgeladen (`radar.png`) | 5 min |
| MeteoLux (Findel) | `meteolux` | Minutenwerte der Station Findel (CC0): Temperatur, Feuchte, Druck, Wind; Wetter-Reiter, Tabelle „Weitere Messungen“ | 10 min |
| MET Norway | `metno` | zweites Vorhersagemodell (CC BY 4.0), 48 h, im Wetter-Diagramm gestrichelt neben DWD | 60 min |
| Sensor.Community | `sensor_community` | Temperatur und Feuchte von Bürgersensoren, nur als 0,1°-Raster-Median aus mindestens 3 Außensensoren, keine Sensor-IDs gespeichert | 10 min |

Lücken, die man wissen muss: Luxemburg und Frankreich (Cattenom) liefern weder BfS noch UBA; „keine Farbe“ im Radar heißt kein Regen ODER außerhalb der Radarreichweite. Die Sonde Biringen (UBA) liefert keine Daten. Pillow (Radarbild) steht in `requirements.txt`; nach dem Update `pip install -r requirements.txt`.
Tests: `tests/test_collectors_umwelt.py`, `tests/test_wetter_quellen.py` (echte gekürzte Antworten, Abwandlungen sind im Test mit SYNTHETISCH markiert).

## Meldungen, Luxemburg, Indizes, Spritpreise, Themenradar

| Quelle | Collector | Inhalt | Takt |
|---|---|---|---|
| Presseportal (Polizei) | `presseportal` | Überschrift, Ort (aus der Datumszeile), Zeit, Link der Dienststellen Trier und Wittlich; Text wird verworfen, Fahndungen und Vermisste nie übernommen | 10 min |
| Trierischer Volksfreund | `rss_volksfreund` | Schlagzeilen der Rubriken Region und Blaulicht, nur mit Ortsname im Radius; Titel und Link | 15 min |
| Pegel Luxemburg (AGE) | `lu_pegel` | 40 Stationen (Sauer, Our, Alzette, Mosel), CC0, im Gewässer-Reiter; keine Warnstufen der Quelle | 15 min |
| CITA Luxemburg | `cita_lu` | Verkehrsmeldungen DATEX II (Unfälle, Baustellen, Hindernisse), CC0 | 5 min |
| DWD Waldbrand/Grasland | `dwd_waldbrand` | Stationsindex Stufe 1 bis 5 (10 nächste Stationen), Ereignis ab Stufe 3, Umwelt-Reiter | 3 h |
| DWD Pollen/UV | `dwd_gesundheit` | Pollenflug Teilregionen 101/102, UV-Index Station Hahn, Umwelt-Reiter | 60 min |
| Tankerkönig | `tankerkoenig` | Spritpreise deutsche Seite (CC BY 4.0), **inaktiv, bis `TANKERKOENIG_API_KEY` in `.env` steht**, dann `aktiv: true` im Register | 15 min |
| Mastodon | `mastodon_themen` | Themenradar: Beiträge je Regions-Hashtag und begleitende Themen, nur Zählungen, Schwelle 3 verschiedene Konten | 60 min |

Ortszuordnung ohne externen Geocoder: `app/geoparse.py` nutzt das Ortsverzeichnis `app/data/orte.json` (OSM, ODbL, gebaut mit `tools/build_gazetteer.py`). Meldungen ohne erkennbaren Ort im Radius werden verworfen, nicht auf einen Kreismittelpunkt geraten. Neue Ausgabedateien: `indizes.json`, `kraftstoff.json`, `themen.json`.

Bewusst nicht eingebunden: Wort.lu (behält sich Text- und Data-Mining ausdrücklich vor), Bluesky (öffentliche Suche verlangt Anmeldung), Telegram (Projektanweisung), Luxemburger Luftqualität und Spritpreise je Tankstelle (kein offener Datensatz gefunden), Copernicus EMS (nur bei konkretem Einsatz). Lizenz von Presseportal, Volksfreund, DWD Pollen/UV und Mastodon ist im Register mit `lizenz_geprueft: false` vermerkt und vor dem öffentlichen Start zu klären.
Tests: `tests/test_quellen_batch2.py`.

## Ostbelgien, Wallonie, Grand Est

| Quelle | Collector | Inhalt | Takt |
|---|---|---|---|
| Hub'eau Hydrométrie | `hubeau_pegel` | Wasserstände Nordlothringen (Mosel, Nied, Orne, Seille), mm zu cm, im Gewässer-Reiter; keine Warnstufen der Quelle; Lizenz nicht gegengelesen | 15 min |
| BRF Ostbelgien | `rss_brf` | Rubrik Regional, nur mit Ort im Radius (Schlagzeile oder Schlagwort); Titel und Link | 15 min |
| MeteoAlarm | `meteoalarm` | Wetterwarnungen BE, FR, LU als Fläche je NUTS-Gebiet (`app/data/nuts_meteoalarm.json`, gebaut mit `tools/build_nuts.py`); nur Stufe, Art, Gebiet, Zeit, Link; Auflagen der Quelle nicht gelesen | 10 min |

Der Radius von 120 km reicht nach Süden bis Metz und Thionville, nach Westen bis Bastogne, Namur bleibt draußen, nach Norden bis Eupen und Aachen, nach Osten bis Koblenz und Bad Kreuznach. Noch nicht eingebunden: SPW Wallonie Hydrometrie, IRCELINE, ATMO Grand Est, IRSN Téléray, Vigicrues (Endpunkte und Lizenzen nicht geprüft). Tests: `tests/test_quellen_batch3.py`.

## Kultur und Geschichte

Der Landmarken-Collector `osm_natur` (Overpass, wöchentlich) liefert neben der Natur jetzt Burgen und Schlösser (`historic=castle|fort|manor`), Ruinen, archäologische Stätten, Klöster sowie historische Gebäude, Stadttore und Türme. Nur benannte Objekte; Gedenkorte (`memorial`, Stolpersteine) fehlen absichtlich, weil sie oft Personen nennen. Auf der Karte gibt es eine eigene Ebene „Kultur und Geschichte" (Zeichen aus Maki, CC0, geholt mit `tools/fetch_icons.sh`). Nach dem Update einmal `tools/fetch_icons.sh` und `python -m app.collect --once --only osm_natur` ausführen.

## Große Bildschirme

Ab 1800 px Breite skaliert die Oberfläche über die Schriftgröße der Wurzel (`app.css`, Abschnitt „Große Bildschirme“): Inhalt in einem Rahmen (`--frame`), Kartenhöhe aus `--map-h`. Geprüft bei 1440 und 3440 px Breite.

## Karte: Aufbau, Straßen, Radar-Sweep

**Layout.** Ab 1001 px Breite füllt die Karte den ganzen Rahmen. Zeitraum/Ebenen (links, einklappbar) und die Liste (rechts) schweben darüber; darunter stehen die Teile untereinander. Kartensteuerung und Höhenlegende weichen den schwebenden Karten aus (`app.css`, letzter Abschnitt).

**Straßen.** Autobahnen, Bundes-/Landstraßen und Anschlüsse (auch Brücken, Tunnel) sind gelborange (`#f6a81c`) mit 1 px schwarzer Kontur. Die Umstellung passiert beim Aufbau des Basiskartenstils (`mainRoad` in `lage.js`); Grenzlinien des Stils (`boundaries*`) werden nicht gezeichnet.

**Radius und Sweep.** Der 120-km-Kreis ist grün (Fläche 1 % Deckkraft, Rand 2 px voll). Ist die Luftverkehr-Ebene an und mindestens ein Flugzeug aktiv, läuft ein Radarstrahl (6 s je Umlauf, Zeichnung auf einer eigenen Canvas, `web/js/sweep.js`); überstreicht er ein Flugzeug, sendet es einen Ping. Ohne aktive Flugzeuge, bei ausgeblendeter Ebene, verstecktem Tab oder „weniger Bewegung“ im System steht alles still.

**Schweife.** Jedes Flugzeug zieht 200 px Schweif entlang der beobachteten Bahn, nach hinten schwächer. Die Bahn besteht nur aus Positionen, die der Browser in dieser Sitzung gesehen hat (Arbeitsspeicher, höchstens 30 Minuten); sie wird nie gespeichert oder hochgeladen. Neu geladene Seite = Schweife beginnen von vorn.

**Flugzeugklassen.** Der Collector speichert `klass`: `civil`, `mil` (Militär-Kennzeichen der adsb.lol-Datenbank, `dbFlags` Bit 0), `heli` (Kategorie A7) oder `milheli`. Kennzeichen, Hex-Code und Typ bleiben draußen, gespeichert wird nur die Klasse. Darstellung: zivil = dunkles Flugzeug, militärisch = violett im Ring, Hubschrauber = eigenes Symbol (uxwing „helicopter“, Seitenansicht, dreht sich nicht). Die Klasse ist so gut wie die Datenbank von adsb.lol: nicht gemeldete oder nicht erfasste Militärflugzeuge erscheinen als zivil.

### Gebäude, Straßenschilder, Beschriftung, Verkehrsfarben

- **Gebäude** bordeaux (`#800020` hell, `#9c2a4b` dunkel), 60 % transparent (`BUILDING_OPACITY` in `lage.js`). Standardmäßig an. Die Ebene beginnt bei Zoom 13 (nur große Gebäude, die Kacheln führen darunter nicht mehr). Alle Gebäude gibt es ab Kartenzoom 14: der Kern wird mit `tileSize: 256` eingebunden, dadurch gelten die Zoom-15-Kacheln eine Stufe früher. Weiter vorzuziehen (Zoom 13) würde viermal so viele Kacheln je Bild laden; dafür bräuchte es eigene Gebäudekacheln.
- **Autobahnen** blau mit schwarzer Kontur; auf der Strecke Schilder mit der OSM-Nummer (`ref`): A blau/weiß, B gelb, L und K weiß. Nur Nummern bis 8 Zeichen ohne Semikolon; Anschlussstellen tragen kein Schild.
- **Straßennamen** ab Zoom 13, **Hausnummern** ab Zoom 16 (Kacheln bis Zoom 15, darüber wird vergrößert). Es sind Kartenbeschriftungen aus OSM, keine Adresssuche und kein Geocoding; die Daten liegen in den Kacheln, nicht in der Datenbank. Wo OSM keine Namen oder Nummern kennt (kleine Weiler), bleibt die Karte leer.
- **Verkehrsmeldungen** in vier Stufen (`trafficLevel` in `rules.js`): gelb Baustelle, orange Behinderung oder Stau, rot langer Stau (ab 30 Min.) oder eine Richtung gesperrt, schwarz Vollsperrung. Die Stufe folgt aus `type`, `severity` und `attrs.sperr` (`voll`/`richtung`, gesetzt von den Collectoren `lbm_baustellen` und `autobahn`); die Liste rechts zeigt weiter die Stufe der Quelle. Schwarze Linien bekommen einen weißen Saum.
- **Detailfeld** rechts lässt sich mit dem Knopf „Details ausblenden“ einklappen; Ebenen, Höhenlegende und Detailfeld haben dasselbe Material (Deckkraft, Unschärfe, Rand, Schatten).
- **Prüfzugang:** mit `#debug` in der Adresse reagiert die Seite auf das Ereignis `osint-debug` (Auftrag als JSON in `data-debug-in`, Zählwerte in `data-debug-out`). Nur zum Testen, nichts geht nach außen.

## Radius: 120 km, endgültig

Das Lagebild gilt der Region, nicht dem Ort. `RADIUS_KM` in `app/config.py` steht auf 120; die Bounding Box wird daraus berechnet (`config.BBOX`, nach außen auf 0,01° gerundet), es gibt keine zweite Stelle, an der sie stehen müsste. Außerhalb blendet die Karte in 14 Stufen von je 5 km in die Hintergrundfarbe aus (Vignette, `vig-0` bis `vig-13` in `web/js/lage.js`); das Kartenfenster (`maxBounds`) endet kurz dahinter. Größer wird es nicht.

Nach einer Änderung des Radius neu bauen, in dieser Reihenfolge: `tools/build_tiles.sh`, `tools/build_dem.py`, `tools/build_gazetteer.py` (Ortsverzeichnis für das Geoparsing), `tools/build_nuts.py` (MeteoAlarm-Flächen), danach `tools/check_range.py <URL>` gegen den Server. NINA fragt 21 Kreise ab (RLP, Saarland, Euskirchen, Aachen), Tankerkönig fünf Umkreise zu je 25 km.

## Suche über alle Namen

Suchfeld oben links in der Karte (Taste `/` oder Strg+K). Alles läuft im Browser, keine Anfrage nach außen. Der Index wird erst beim ersten Fokus geladen.

- `web/data/suche_geo.json` (statisch, ca. 2,5 MB): Orte, Straßen, Bäche, Gipfel, Wälder, Schutzgebiete aus unseren Kartenkacheln. Bauen: `python tools/build_search_index.py --rescan` (liest `web/tiles/region.pmtiles` und `core.pmtiles`, Zwischenstand in `data/search_raw.json.gz`; ohne `--rescan` wird der Zwischenstand benutzt). Nach jedem Kachel-Neubau wiederholen.
- `web/data/suche.json` (dynamisch, ca. 1,3 MB): Schulen, Kirchen, Feuerwachen, Brücken, Landmarken, Haltestellen, Routen, Pegel. Entsteht bei `python -m app.export`.
- Format `{"v":1,"t":[Typen],"o":[Orte],"e":[[Name,Typ,Breite*1e4,Länge*1e4,Ort]]}`; `TYPES` in `app/search.py` nur anhängen, nie umsortieren.
- Datenschutz: keine Hausnummern, keine Adressen, keine Personennamen. Reine Zahlennamen werden verworfen. Lizenz: © OpenStreetMap-Mitwirkende (ODbL).
- Test: `python -m pytest tests/test_search.py && node --test tests/js/suche.test.mjs`

Die Karte im Stil des 15. Jahrhunderts hat keine Papiertextur mehr (Foto und Überlagerung entfernt); Farben, Schrift, Windrose und Zeichen bleiben.

## Vegetation und Wasserbewegung

**Vegetation:** `web/js/lage.js` (`LAND`, `LAND_KINDS`) zeichnet 13 Klassen nach Naturfarben (Wald, Wiese, Rasen/Park, Busch, Heide, Acker, Obst, Wein, Kleingarten, Moor, Fels, Sand, Friedhof). Ab Zoom 12 liegen feine Signaturen darüber (`icons.js`, `registerLandPatterns`). Schutzgebiete haben eine gestrichelte grüne Kante. Die Kacheln tragen keinen Blatttyp, Laub-, Nadel- und Mischwald sind daher nicht trennbar (dafür wäre ein OSM-Collector für `leaf_type` nötig).

**Wasserbewegung** (Ebene „Wasserbewegung“, standardmäßig aus, `web/js/fluss.js`): Striche und Pfeile entlang der Gewässerlinien zeigen die Fließrichtung (Digitalisierungsrichtung der OSM-Linien, geprüft an Mosel, Saar, Our, Sûre, Kyll, Prüm, Nims, Alzette, Lieser, Ruwer). Tempo ist eine Klasse (Bach, Fluss, gestaut), kein gemessener Abfluss. `IMPOUNDED` (Mosel, Saar) bewegt sich kaum: staugeregelt. Seen, Teiche und Becken zeigen Wellenzeichen, die mit dem Modellwind (ICON-D2, Kartenmitte) ziehen; bei Flaute oder ohne Windmodell bleibt das Wasser glatt. Flächen ohne Gewässerart gelten als Stillgewässer. Bei `prefers-reduced-motion` stehen die Zeichen still. Tests: `node tests/js/fluss.test.mjs`. Prüfhilfe: `#debug` schreibt Seitenfehler nach `data-debug-err` am `<html>`.

## Lichtquelle am Zeiger

Ebene „Lichtquelle am Zeiger“ (aus, unter Kartengrundlage; braucht Höhenrelief). `web/js/licht.js` rechnet im Fragment-Shader (WebGL2): Höhenmosaik aus den sichtbaren Terrarium-Kacheln (höchstens 48, Zoom 6 bis 12), Hangneigung per Sobel, Punktlicht über dem Zeiger (Höhe einstellbar), Schatten durch Strahlverfolgung mit weichem Rand (48 Schritte). Ohne Maus gilt die Bildmitte bzw. der letzte Tippunkt. Gilt nur bei Nordausrichtung ohne Neigung. Prüfzugang: `licht:{on,lon,lat,hoehe}` im `#debug`-Auftrag.

## Desktop-App (Tauri, lokal, GPU)

Dieselbe Oberfläche als App für Windows 10+, Linux und macOS. Gezeichnet wird mit dem System-WebView (WebView2, WebKitGTK, WKWebView), WebGL läuft dort auf der GPU. Daten und Karte liegen lokal, es gibt keinen Server und keine US-Cloud.

```
Tauri-Hülle (Rust) ──startet──▶ osint-core (Python, Sidecar) ──▶ 127.0.0.1:<Port>
                                  ├─ liefert web/ (mit Teilabrufen für PMTiles)
                                  ├─ Ersteinrichtung: Mittelpunkt wählen → Karte 120 km laden (pmtiles-CLI)
                                  └─ Sammelzyklus alle 5 Min: app.collect → app.export → <Datenordner>/data
```

Beim ersten Start fragt `einrichtung.html` nach dem Mittelpunkt (Ortsname über Nominatim, nur der Suchtext geht hinaus, oder Koordinaten von Hand). Danach lädt die App die Karte für 120 km (ca. 550 MB, einmalig, wiederaufnehmbar) und beginnt zu sammeln. Der Mittelpunkt ist danach festgelegt; ändern heißt Datenordner zurücksetzen.

Ablauf in der App: Als Hintergrund der Einrichtungsseite dient die mitgelieferte Weltkarte `web/basis/welt.pmtiles` (Zoom 0 bis 5, rund 15 MB, Herkunft in `web/basis/README.txt`). Der Balken zeigt beim Kartenabruf die geladenen MB, beim Sammeln „n von m abgerufen, läuft noch: <Name>" (`.collect-progress.json` im Datenordner, nur Quellennamen). Der erste Lauf überspringt die Quellen mit `erstlauf: spaeter`; sobald der erste Export steht, zeigt die App „Bereit", die langsamen Quellen laufen im Hintergrund (`--due`) und erscheinen mit dem nächsten Export (alle 5 Minuten). Spätere Zyklen holen nur noch fällige Quellen (`--due`), nicht mehr jede Quelle bei jedem Zyklus.

```bash
# Dienst allein ausprobieren (ohne Hülle)
python -m app.desktop --data-dir /tmp/osint-demo --pmtiles tools/bin/pmtiles     # → "OSINT_READY port=N", dann http://127.0.0.1:N/

# App bauen (je Betriebssystem auf diesem System; CI: .github/workflows/desktop.yml)
desktop/build-sidecar.sh && cd desktop && npm install --include=dev && npx tauri build
```

Grenzen der ersten Fassung: Suchindex, Gewässernetz, Höhenkacheln und Routen (`web/geo`, `web/tiles/dem`, `tools/build_*.py`) sind noch auf Irrel gebaut und werden nicht für einen anderen Mittelpunkt erzeugt. Quellen für Luxemburg, Rheinland-Pfalz und Ostbelgien liefern nur dort Daten; bundesweite (DWD, NINA, Autobahn, Bright Sky) funktionieren überall in Deutschland. Das Bündeln mit PyInstaller und die Installer sind hier nicht gebaut worden (Sandbox ohne WebKit, nur Linux): erster Build auf Mac, Windows und Linux steht aus.
