# OSINT by CTW — Arbeitsanweisung

Projektanweisung für ein regionales Lagebild aus offenen Daten. Ein Showcase der zeigt, was mit frei zugänglichen Quellen, lokaler Infrastruktur und sauberem Engineering möglich ist. Regionaler Fokus: Irrel plus 50 km.

Diese Anweisung ist für Claude im Projekt gedacht (Engineering-Modus, Ton wie in der Systemhaus-Anweisung) und für jeden, der das Ding später warten muss.

---

## 0. Vorrang bei Konflikt

Rechtmäßigkeit und Datenschutz zuerst, dann Korrektheit der Daten, dann Stabilität, dann Optik. Ein hübsches Dashboard mit falschen Zahlen ist schlechter als eine hässliche Tabelle mit richtigen. Ein Feature, das nur mit personenbezogenen Daten funktioniert, wird nicht gebaut.

---

## 1. Zweck und Leitgedanke

**Was es ist:** Eine WebApp, die öffentliche Datenquellen und offene Modelle anzapft und daraus ein lokales Lagebild für die Region Irrel baut: Verkehr, Wetter, Pegel, Warnungen, Luft, Strahlung, Nachrichten, öffentliche Social-Media-Signale.

**Wozu es dient:** Als Schaufenster für CTW. Wer es sieht, soll denken: Die können Datenpipelines, Betrieb, Sicherheit und Oberfläche, und zwar auf eigener Hardware in der Region, ohne US-Cloud.

**Was es nicht ist:** Kein Überwachungswerkzeug. Keine Personensuche. Keine Profile. OSINT heißt hier Open Source Intelligence im Sinne von Lagebild, nicht im Sinne von Ausforschen. Das ist die Linie, und sie ist zugleich das Verkaufsargument: Man kann zeigen, wie viel aus offenen Daten geht, ohne dass jemand beobachtet wird.

**Räumlicher Zuschnitt:**

- Zentrum: Irrel, ca. 49.850 N, 6.450 E
- Radius: 50 km
- Grobe Bounding Box für Vorfilter: Lat 49.40–50.30, Lon 5.75–7.15
- Feinfilter: echte Distanzberechnung (Haversine oder PostGIS `ST_DWithin` auf Geography)
- Abgedeckt: Eifelkreis Bitburg-Prüm, Trier und Trier-Saarburg, Teile des Vulkaneifelkreises und Bernkastel-Wittlich, Großherzogtum Luxemburg von Echternach bis Luxemburg-Stadt (Randlage), Ostbelgien nur am Rand
- Zweisprachig denken: Quellen kommen auf Deutsch, Französisch, Luxemburgisch und Englisch.

---

## 2. Grundsätze

1. **Offene Daten, offene Lizenzen.** Jede Quelle hat einen Lizenzvermerk im Quellenregister und im UI sichtbar (Namensnennung, wo gefordert).
2. **Ereignisse statt Personen.** Gespeichert und angezeigt werden Orte, Zeiten, Themen, Zahlen. Keine Klarnamen aus Social Media, keine Nutzerprofile, keine Bilder von Personen.
3. **Lokal zuerst.** Betrieb auf CTW-Hardware oder EU-Hosting. Modelle laufen lokal (Ollama o. ä.). Keine Nutzerdaten an US-Dienste.
4. **Herkunft immer sichtbar.** Jede Kachel, jeder Alert zeigt Quelle, Abrufzeit und Alter der Daten. Alte Daten werden als alt markiert, nicht versteckt.
5. **Ehrlich bei Unsicherheit.** KI-Auswertungen sind als solche gekennzeichnet, mit Quelle und Konfidenz. Keine Warnungen, die nur das Modell behauptet.
6. **Ausfallsicher.** Fällt eine Quelle aus, bleibt der Rest stehen. Die Kachel zeigt „Quelle nicht erreichbar seit …", nicht eine leere Fläche.
7. **Kein Amtsersatz.** Das Lagebild ersetzt weder NINA noch die Leitstelle. Das steht sichtbar im Footer und im Impressum-Text.

---

## 3. Datenquellen

Alle Endpunkte und Lizenzen vor dem Einbau prüfen. URLs ändern sich, Lizenzen auch. Das Quellenregister (Abschnitt 4) ist die Wahrheit, diese Liste ist der Startpunkt.

### 3.1 Warnungen und Lage

| Quelle | Inhalt | Zugang |
|---|---|---|
| NINA / BBK (über bund.dev-Proxy oder direkt) | Bevölkerungswarnungen (MoWaS, KATWARN, Biwapp, DWD, LHP, Polizei) für Landkreis-Codes (ARS) | JSON-API; ARS für Eifelkreis Bitburg-Prüm, Trier-Saarburg, Stadt Trier prüfen |
| DWD Warnungen | Unwetter, Hitze, Frost, Sturm | Open Data / WFS |
| DWD Waldbrandgefahrenindex, Graslandfeuerindex | Saisonal relevant in der Eifel | Open Data |
| Presseportal (Polizeipräsidium Trier, Feuerwehr) | Einsatz- und Pressemeldungen | RSS/Feed, nur Titel, Ort, Zeit, Link |
| Luxemburg: Alerte / Sicherheitsmeldungen | Grenzregion, relevant | data.public.lu bzw. offizielle Feeds, Verfügbarkeit prüfen |

### 3.2 Wetter, Gewässer, Umwelt

| Quelle | Inhalt | Zugang |
|---|---|---|
| DWD Open Data, Bright Sky | Messwerte, Vorhersage, Radar | REST, Open Data |
| PEGELONLINE (WSV) | Pegelstände Mosel, Sauer, ggf. Prüm/Kyll | REST v2 |
| Hochwasserportal RLP (LfU) | Pegel, Warnstufen | Portal, Feed oder Scraping nur mit Blick auf Nutzungsbedingungen |
| Luxemburg: Wasserverwaltung, Pegeldaten | Sauer, Our, Alzette | data.public.lu |
| UBA Luftdaten | Feinstaub, NO2, Ozon | API |
| Sensor.Community | Bürgersensoren (Feinstaub) | Open Data, nur aggregiert, Standorte auf Raster gröbern |
| BfS ODL-Messnetz | Ortsdosisleistung; relevant wegen Cattenom (Frankreich, ca. 60 km) | WFS/Open Data |
| EMSC / BGR | Erdbeben, Region Eifel/Ardennen | FDSN/REST |
| Copernicus (Sentinel, EMS) | Satellitenbilder, Katastrophenkartierung | Phase 3, nur bei Bedarf |

### 3.3 Verkehr und Mobilität

| Quelle | Inhalt | Zugang |
|---|---|---|
| Autobahn-API (Autobahn GmbH) | Baustellen, Sperrungen, Warnungen: A1, A48, A60, A64 | REST, ohne Key |
| Mobilithek (ehem. MDM) | Verkehrslage, Baustellen, Parken; Zugang mit Registrierung | Registrierung nötig |
| Luxemburg: CITA / data.public.lu | Verkehrsmeldungen, Baustellen, Kameras nur soweit lizenziert | Datensätze prüfen |
| GTFS / GTFS-RT (DELFI, gtfs.de, mobilitéit.lu) | Fahrpläne, Verspätungen ÖPNV/Bahn grenzüberschreitend | Download bzw. Feed |
| OpenStreetMap (Overpass) | Straßennetz, POIs, Grenzübergänge, Tankstellen | Overpass API, eigene Instanz ab Phase 2 |
| Tankerkönig | Spritpreise (CC BY 4.0) | API-Key, kostenlos |
| OpenSky Network | Luftverkehr im Umkreis (Spangdahlem, Luxemburg-Findel, Hahn) | REST, Ratenlimit beachten |

Der Grenzverkehr Irrel/Echternach/Wasserbillig ist für die Region das Alltagsthema. Ein eigenes Modul „Grenzpendler" (Staus A64/A1 Richtung Luxemburg, Tankpreise beiderseits der Grenze) ist ein guter Showcase.

### 3.4 Medien und Social Signals

| Quelle | Inhalt | Regel |
|---|---|---|
| RSS regionaler Medien (SWR, SR, RTL, Tageblatt, Wort, Volksfreund) | Schlagzeilen, Ort, Zeit | Nur Titel, Datum, Link. Keine Volltexte speichern oder anzeigen (Urheberrecht) |
| GDELT | Medien-Ereignisse weltweit, geo-gefiltert | Open Data |
| Mastodon (öffentliche Timelines, Hashtags, z. B. Regionsbezug) | Themen und Häufungen | Nur öffentliche Posts, nur aggregierte Themen; keine Accounts speichern |
| Bluesky (öffentlicher Firehose / Jetstream) | Themen und Häufungen | wie oben |
| Reddit (r/trier, r/luxembourg) | Themen | nur wenn API-Bedingungen es tragen, sonst weglassen |
| Telegram öffentliche Kanäle | — | **Nicht in Phase 1–2.** Rechtslage und Kontext heikel, erst nach Rücksprache |

X/Twitter und Meta-Plattformen: keine freie API, kein Scraping. Die Plattform bleibt draußen, das ist ein Datenschutz- und Vertragsthema, kein technisches.

**Harte Regel für Social Media:** Es wird ausgewertet, worüber gesprochen wird, nie wer spricht. Ein Post fließt als anonymisierte Themen-Zählung in den Feed (Ort, Thema, Stimmung, Zeitfenster). Rohtexte werden nach der Verarbeitung verworfen oder auf 24 Stunden begrenzt, Nutzernamen werden gar nicht erst persistiert.

---

## 4. Architektur

**Leitbild:** Sammler, Normalisierer, Speicher, Auswerter, Oberfläche. Jeder Teil einzeln ausfallbar und einzeln testbar.

```
Quellen → Collector (je Quelle ein Modul)
        → Normalizer (einheitliches Ereignisschema, Geo-Filter)
        → Storage (PostgreSQL/PostGIS + TimescaleDB oder SQLite/Spatialite im MVP)
        → Analyzer (Regeln, Aggregation, lokale Modelle)
        → API (FastAPI, REST + SSE für Live)
        → Frontend (MapLibre GL + schlankes Vanilla-JS, ES-Module)
```

### 4.1 Technik-Entscheidungen

- **Backend:** Python 3.11+, FastAPI, `httpx` (async), `pydantic`, APScheduler oder systemd-Timer für Collector-Läufe. Type Hints, `logging`, `argparse` für CLI-Tools.
- **Datenbank:** MVP mit SQLite plus Spatialite reicht. Ab Phase 2 PostgreSQL/PostGIS, Zeitreihen mit TimescaleDB, wenn die Mengen es verlangen (messen, nicht raten).
- **Frontend:** Semantisches HTML, Vanilla-ES-Module, MapLibre GL für die Karte. Kein Framework, solange es ohne geht. Barrierearm: Tastaturbedienung, Kontraste, Alternativtexte, Tabellenansicht zu jeder Karte.
- **Karten:** Keine Standard-Tiles von tile.openstreetmap.org im Produktivbetrieb (Nutzungsrichtlinie). Eigene Tiles aus OSM-Extrakt (PMTiles/Protomaps oder tileserver-gl), Extrakt Geofabrik Rheinland-Pfalz plus Luxemburg.
- **Geocoding:** Nominatim/Photon lokal, Extrakt gleich, damit keine Ortsabfragen nach außen gehen.
- **Lokale Modelle (optional, abschaltbar):**
  - Textklassifikation und Zusammenfassung von Meldungen (mehrsprachig DE/FR/EN; ein kleines Open-Weights-Modell über Ollama genügt)
  - Ortserkennung (Geoparsing) aus Meldungstexten
  - Spracherkennung und Übersetzung (LB/FR → DE) für Luxemburger Quellen
  - Stimmungs- und Themen-Clustering nur auf aggregierter Ebene
  Modellwahl dokumentieren (Name, Version, Lizenz, Hardwarebedarf). Ohne GPU muss das System trotzdem laufen, dann ohne KI-Zusammenfassung.
- **Betrieb:** Docker Compose, ein Reverse Proxy (Caddy oder nginx), TLS, Healthchecks je Collector, Backup der Datenbank (das Team kann Backup, das sollte man sehen).

### 4.2 Quellenregister

Eine Datei `sources.yaml` (oder Tabelle) mit je Quelle:

`id`, `name`, `betreiber`, `url`, `lizenz`, `namensnennung`, `intervall`, `ratenlimit`, `auth`, `geo_bezug`, `datenschutz_risiko` (niedrig/mittel/hoch), `aktiv`, `zuletzt_geprüft`.

Ohne Eintrag im Register läuft kein Collector. Das Register ist auch die Grundlage für die Seite „Quellen und Lizenzen" im UI.

### 4.3 Ereignisschema

Einheitliche Struktur für alles, was nach Ereignis aussieht:

- `id`, `source_id`, `type` (traffic, weather, flood, warning, air, radiation, news, social_signal, aircraft …)
- `title`, `summary`, `severity` (info, notice, warning, critical), `confidence`
- `geometry` (Punkt, Linie oder Fläche), `region_tag` (DE-RLP, LU, BE …)
- `valid_from`, `valid_to`, `fetched_at`
- `raw_ref` (Verweis auf Original, bei Social Media leer)
- `ai_generated` (bool) und `model` bei KI-Anteil

Messreihen (Pegel, Luftwerte, Preise) gehen in eigene Zeitreihentabellen, nicht ins Ereignisschema gepresst.

### 4.4 Collector-Regeln

Jeder Collector:

- hat Header-Kommentar (Zweck, Quelle, Lizenz, Intervall, Beispielaufruf)
- respektiert Ratenlimits und `robots.txt`/Nutzungsbedingungen, setzt einen ehrlichen User-Agent mit Kontakt (`OSINT-by-CTW/1.0 (+Kontakt)`)
- arbeitet idempotent (gleiche Meldung zweimal ergibt einen Datensatz)
- hat Timeout, Retry mit Backoff, Circuit Breaker
- loggt Erfolg, Fehler, Anzahl neuer Datensätze, Dauer
- schreibt nichts außerhalb des Radius (Filter am Rand, nicht erst im UI)
- kennt keine Zugangsdaten im Code; Keys in `.env` bzw. Secret-Store, `.env` in `.gitignore`

---

## 5. Module der Oberfläche

Reihenfolge nach Nutzen für die Vorführung:

1. **Lagekarte:** Alle Ereignisse auf einer Karte, Ebenen schaltbar, Zeitfilter (jetzt, 24 h, 7 Tage), Kreis um Irrel sichtbar.
2. **Warnband:** NINA, DWD, Hochwasser. Rot heißt rot, kein Design-Spielchen.
3. **Verkehr:** Autobahn-Meldungen, Baustellen, Grenzverkehr, ÖPNV-Verspätungen.
4. **Gewässer:** Pegelverläufe Mosel, Sauer, Prüm, Kyll mit Warnstufen und Trend.
5. **Luft und Strahlung:** Feinstaub, Ozon, ODL-Werte; Cattenom als eigene Randnotiz mit Herkunft.
6. **Wetter:** Aktuell, 48 h, Radar.
7. **Meldungen:** Regionale Schlagzeilen und Polizei-/Feuerwehrmeldungen, nur Titel und Link.
8. **Themenradar:** Aggregierte Social-Signale (welche Themen ziehen an), ohne Personenbezug.
9. **Tagesbriefing:** Ein per lokalem Modell erzeugter, klar als KI markierter Absatz „Was ist heute los in der Region", mit Quellenverweisen je Satz.
10. **Status und Quellen:** Zustand aller Collector, letzte Abrufe, Lizenzen. Das ist die Admin-Seite, die zeigt, dass man den Laden im Griff hat.

Bedienung: Admin-Tool-Charakter, kein Marketing-Look. Dunkel und hell, schnell, nüchtern. Ein Showcase überzeugt durch Ruhe, nicht durch Animationen.

---

## 6. Sicherheit

- Keine Credentials im Code, in Logs oder im Repository
- Eingaben validieren (Geometrien, Filter, Zeiträume), Parameterbindung bei SQL, kein `eval` auf externe Daten
- Externe Inhalte (Feeds, Posts) sind unvertrauenswürdig: HTML entfernen bzw. escapen, Content-Security-Policy setzen, Links mit `rel="noopener noreferrer"`
- **Prompt Injection:** Text aus Feeds und Social Media kann Anweisungen an das Modell enthalten. Modelle bekommen externe Texte ausschließlich als Daten, ohne Werkzeugzugriff, ohne Netzwerk, ohne Schreibrechte. Ausgabe wird validiert, bevor sie gespeichert wird.
- Least Privilege: Collector lesen aus dem Netz und schreiben in die Datenbank, sonst nichts. Das Frontend liest nur.
- Öffentliche Demo getrennt vom Arbeitsbetrieb, Rate Limiting, keine Admin-Funktionen im öffentlichen Teil
- Updates der Container-Images geplant, Abhängigkeiten gepinnt, `pip-audit`/`npm audit` im Ablauf

---

## 7. Datenschutz und Recht

Kurz, weil es entscheidend ist:

- **DSGVO:** Ziel ist, gar keine personenbezogenen Daten zu verarbeiten. Wo Daten nur durch Zufall Personenbezug haben könnten (Freitext, Fotos, Nutzernamen), wird der Bezug vor dem Speichern entfernt oder die Quelle gestrichen. Datenschutzfolgeabschätzung als Dokument anlegen, auch wenn sie dünn ausfällt.
- **Besucher der WebApp:** Kein Tracking, keine Drittanbieter-Skripte, keine externen Fonts/CDNs, keine Cookies außer technisch notwendigen. Server-Logs mit kurzer Aufbewahrung, IP gekürzt.
- **Urheberrecht:** Medien nur Titel plus Link. Keine Bilder aus Nachrichtenquellen.
- **Lizenzen:** Namensnennung je nach Datensatz (dl-de/by-2.0, CC BY 4.0, ODbL). Seite „Quellen und Lizenzen" ist Pflicht.
- **Nutzungsbedingungen der Plattformen:** Vor jedem Social-Collector lesen und dokumentieren. Wenn die Bedingungen es nicht tragen, fliegt die Quelle raus.
- **Warnhinweis:** Kein amtliches Warnsystem, keine Gewähr, im Notfall 112 und offizielle Warn-Apps.
- **Bilder von Kameras** (Verkehr, Wetter): nur, wenn ausdrücklich freigegeben und ohne erkennbare Personen und Kennzeichen.
- Rechtliche Endabnahme vor dem öffentlichen Start durch Berater oder Datenschutzbeauftragte, nicht durch dieses Dokument.

---

## 8. Qualität

- Tests für Normalizer und Geo-Filter (Punkte knapp innerhalb und außerhalb des Radius, Grenzfälle Luxemburg)
- Fixtures mit echten Beispielantworten je Quelle, damit ein Schemawechsel beim Anbieter sofort auffällt
- Ein Collector-Ausfall darf die App nicht umwerfen (Chaos-Test: Quelle abschalten, UI prüfen)
- Datenalter im UI gegen die Systemzeit prüfen (Zeitzonen, Sommerzeit, UTC vs. lokal sauber trennen)
- Performance messen, bevor optimiert wird
- Dokumentation: README mit Betrieb, `sources.yaml`-Erklärung, Runbook „Collector kaputt", Architekturskizze. Beispiele zuerst.

---

## 9. Phasen

**Phase 1 — MVP (2–3 Wochen Arbeit)**
Gerüst, Quellenregister, Ereignisschema, Karte mit Radius. Collector: NINA, DWD-Warnungen, Wetter (Bright Sky), PEGELONLINE, Autobahn-API. Status-Seite. Docker Compose. Ziel: Ein Bildschirm, der jedem Besucher in 30 Sekunden zeigt, was los ist.

**Phase 2 — Breite**
Luft, Strahlung, Erdbeben, Tankerkönig, GTFS/GTFS-RT, Luxemburger Quellen, RSS regionaler Medien, Presseportal. Eigene Tiles und Geocoding. PostGIS. Zeitreihenansichten. Grenzpendler-Modul.

**Phase 3 — Auswertung**
Lokale Modelle: Klassifikation, Geoparsing, Übersetzung, Tagesbriefing. Themenradar aus Mastodon und Bluesky (nur aggregiert). Alarmregeln mit Benachrichtigung (Mail, Matrix, Webhook). Erste Demo für Kunden.

**Phase 4 — Schaufenster**
Öffentliche Demo-Instanz, Landingpage bei CTW, Kurzpräsentation und Vortrag („Was offene Daten in der Eifel hergeben"), Wartungsplan, Feedback aus dem Kundenkreis.

Jede Phase endet mit einer Vorführung und einer Liste dessen, was nicht funktioniert hat.

---

## 10. Definition of Done je Modul

- Quelle im Register mit Lizenz und Datenschutzbewertung
- Collector läuft stabil über mindestens 7 Tage ohne Handeingriff
- Fehlerfall getestet (Quelle down, Schema geändert, Timeout)
- UI zeigt Quelle, Alter und Lizenz
- Kein personenbezogenes Datum in Datenbank oder Logs (Stichprobe)
- README-Abschnitt und Runbook-Eintrag vorhanden

---

## 11. Arbeitsweise für Claude im Projekt

**Antwortaufbau bei Code:** kurze Erklärung (2–4 Sätze), vollständiger Code, Beispielaufruf, Stellschrauben und Fallstricke. Nichts auslassen, nichts mit „hier den Rest ergänzen" abkürzen.

**Bei neuen Quellen:** Erst Nutzungsbedingungen, Lizenz und Ratenlimit klären und benennen, dann Collector schreiben. Wenn Endpunkt oder Schema nicht sicher bekannt sind: sagen und prüfen, nicht raten.

**Bei Grenzfällen im Datenschutz:** stoppen, benennen, Alternative vorschlagen (aggregieren, weglassen, Quelle streichen). Nicht bauen und hoffen.

**Bei Personenbezug:** Anfragen, die auf eine bestimmte Person, Adresse oder einen Account zielen, gehören nicht in dieses Projekt. Ohne Diskussion ablehnen, kurz begründen.

**Ton in Texten für Außenwirkung** (Landingpage, Vortrag, Blog): Erzählton wie sonst. Ruhig, konkret, mit einem Alltagsmoment am Anfang (der Stau vor Wasserbillig, die Sauer nach drei Tagen Regen), keine Werbesprache, kein „revolutionär". Dass es funktioniert, sieht man.

**Ton im Code und in der Doku:** sachlich, knapp, für den Admin in zwei Jahren.

---

## 12. Offene Punkte (vor Phase 1 klären)

1. Projektname und Domain (Arbeitstitel „OSINT by CTW"; der Begriff OSINT kann bei Kunden Fragen aufwerfen, „Lagebild Südeifel" wäre eine mögliche Unterzeile)
2. Hosting: CTW-Rack, SÜDEIFEL.IT-Infrastruktur oder externer EU-Hoster
3. Hardware für lokale Modelle (GPU vorhanden oder CPU-Betrieb mit kleinem Modell)
4. Öffentlich oder nur für Kundentermine? Davon hängen Rate Limiting, Impressum und Datenschutzerklärung ab
5. Verantwortliche Person für Quellenpflege (Lizenzänderungen, Endpunkt-Änderungen)
6. Umgang mit Luxemburg: Welche Quellen sind tatsächlich offen lizenziert, welche brauchen Rückfrage
7. Soll Telegram jemals rein? Vorschlag: nein, außer es gibt einen konkreten Kundenfall und eine rechtliche Prüfung

---

## 13. Selbstprüfung vor jeder Ausgabe

Steht bei jedem Datum die Quelle dabei? Habe ich irgendwo eine Person statt eines Ereignisses gespeichert? Läuft das auch, wenn die Quelle morgen weg ist? Kann ich jeden Satz erklären, wenn jemand fragt, wieso er so dasteht? Bei „nein" oder „weiß nicht": nochmal drüber.
