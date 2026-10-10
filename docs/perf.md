# Messungen Frontend (R5)

Stand: R5, Branch `feat/r5-frontend`. Werkzeug: `tools/perf_messung.py` (Prüfzugang `#debug`, Befehle `zellen` und `perf`).

## Was diese Zahlen sind und was nicht

Gemessen wurde in der Entwicklungsumgebung (Chromium mit Software-Rendering, SwiftShader, keine GPU), mit dem **synthetischen** RLP-Bestand
(`tools/synth_rlp.py`, 75 Zellen, rund 4,4 MB Ereignisse) und der alten Basiskarte nur um Irrel. **Bildraten sind damit nicht die der Referenzmaschine.**
60 fps ist hier nicht erreichbar und nicht prüfbar; die Abnahme „60 fps beim Schwenken“ ist **offen** bis zur Messung auf dem Mac
(`python tools/perf_messung.py --url … --out perf.json`, mit den echten Kachelarchiven). Belastbar sind die Ladezahlen und der Vergleich der Ebenen.

## Ladelast (belastbar)

Fenster 1400 × 900. „Dateien“ sind gehaltene Zellendateien nach dem Sprung, „MB“ deren Größe laut Manifest (unkomprimiert; der Webspace liefert gzip aus).
Startzeit bis zum ersten Zählerstand: **5.3 s** (Ziel unter 10 s). Zoom 12 und 15 halten dieselben Dateien, weil alle Arten bis Zoom 11 freigeschaltet sind.

| Ort | Zoom | Dateien | Zellen | MB | Ereignisse | Bildintervall ms (Mittel / P95), nur Software |
|---|---|---|---|---|---|---|
| Mainz | 8 | 88 | 32 | 4.3 | 3217 | 1403 / 2733 |
| Mainz | 12 | 108 | 12 | 3.2 | 1899 | 642 / 1200 |
| Mainz | 15 | 108 | 12 | 3.2 | 1899 | 672 / 1467 |
| Trier | 8 | 74 | 27 | 3.9 | 2911 | 1784 / 3250 |
| Trier | 12 | 81 | 9 | 1.8 | 1132 | 1437 / 2433 |
| Trier | 15 | 81 | 9 | 1.8 | 1132 | 946 / 1716 |
| Kaiserslautern | 8 | 99 | 36 | 4.3 | 3127 | 1642 / 3000 |
| Kaiserslautern | 12 | 81 | 9 | 2.0 | 1165 | 702 / 1450 |
| Kaiserslautern | 15 | 81 | 9 | 2.0 | 1165 | 675 / 1300 |
| Saarbrücken | 8 | 68 | 24 | 3.0 | 2155 | 1603 / 2883 |
| Saarbrücken | 12 | 107 | 12 | 2.1 | 1202 | 924 / 1500 |
| Saarbrücken | 15 | 107 | 12 | 2.1 | 1202 | 657 / 1233 |
| Frankfurt | 8 | 88 | 32 | 4.3 | 3217 | 1490 / 2700 |
| Frankfurt | 12 | 79 | 9 | 1.9 | 1097 | 893 / 1633 |
| Frankfurt | 15 | 79 | 9 | 1.9 | 1097 | 648 / 1233 |
| Luxemburg | 8 | 84 | 32 | 3.5 | 2563 | 1794 / 3500 |
| Luxemburg | 12 | 80 | 9 | 1.5 | 845 | 1469 / 1767 |
| Luxemburg | 15 | 80 | 9 | 1.5 | 845 | 978 / 1233 |
| Gesamtansicht | 7.6 | 0 | 0 | 0 | 300 (Warnband-Punkte) | 1066 / 2050 |

Die Gesamtansicht (kleinster Zoom, den `maxBounds` zulässt, hier 7,6) lädt keine Zelle: Dichte-Ebene und Warnband stammen aus `start.json` (146 KB).
Beim Heranzoomen auf 8 sind es je nach Lage 3 bis 4,5 MB, bei Ortszoom 1,5 bis 3,3 MB. Ohne Verwerfen wären es alle 75 Zellen.

## Wo die Zeit hingeht (Ablation, Mainz, Zoom 8, Software)

| Ebenen ausgeblendet | Bildintervall ms (Mittel) |
|---|---|
| keine | 1354 |
| Ereignisse und Dichte (11 Ebenen) | 1436 |
| Messstellen, Tank, Haltestellen (2) | 1397 |
| alle Datenebenen (13) | 1403 |

Die Datenebenen kosten in dieser Messung nichts Messbares; die Zeit geht in Basiskarte und Relief (Software-Rasterung). Das spricht dafür, dass die Datenmenge
nicht der Engpass ist. Es ersetzt keine Messung mit GPU.

## Was tut die Seite für die Bildrate

- Unter Zoom 8 keine Einzelobjekte, sondern eine Zahl je Rasterzelle.
- Unter Zoom 9 nur Meldungen ab „Hinweis“, höchstens 1500; darüber höchstens 5000 (`ebenenBudget`).
- Höchstens 60 Zellen gleichzeitig, entfernte werden verworfen; unveränderte Dateien werden nicht neu geholt (Prüfsumme).
- Nachladen erst 250 ms nach Ende der Bewegung, nicht während des Schwenkens.

## Offen

- 60 fps beim Schwenken: Messung auf der Referenzmaschine (Browser und Tauri-Hülle) mit echten Archiven.
- Größe des Suchindex mit echten RLP-Namen (Rechenzeit gemessen, siehe unten).

## Suche über die ganze Fläche (Rechenzeit)

Synthetischer Index, Node 22: 300 000 Einträge, Aufbau 0,44 s, Suche 19 bis 85 ms (Wortanfang mit vielen Treffern am langsamsten), Heap 106 MB.
50 000 Einträge: 7 bis 24 ms. Die Suche läuft linear über alle Einträge; bis rund 300 000 trägt das. Darüber wäre ein Präfixindex fällig. Die Dateigröße von `suche_geo.json`
für ganz RLP ist ungemessen (hängt an den echten Kacheln).
