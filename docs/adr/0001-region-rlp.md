# ADR 0001: Region Rheinland-Pfalz plus 80 km

Status: angenommen am 9. Oktober 2026 (Freigabe R0 bis R7 mit Empfehlungen)

## Kontext

Das Lagebild deckt einen Kreis von 120 km um Irrel ab. Der Betreiber will es auf ganz Rheinland-Pfalz plus 80 km jenseits der Landesgrenze ausweiten. Der Radius steckt heute in Konstanten (`RADIUS_KM`, `CENTER_*`, Kasten) an vielen Stellen im Code, in `sources.yaml` und im UI. Overpass trägt die Fläche nicht (429/504 schon bei 120 km). `web/js/lage.js` ist eine einzige Datei von rund 150 KB.

## Entscheidungen

1. Die Fläche ist ein Polygon: Landesgrenze (BKG VG250, dl-de/by-2.0) plus 80 km. Der Vorfilterkasten wird daraus berechnet.
2. OSM-Ebenen entstehen aus lokalen Geofabrik-Auszügen, nicht aus Overpass.
3. SQLite bleibt, bis eine Messung (Export über 60 s oder Datei über 2 GB) die Umstellung auf PostGIS begründet.
4. Der Webspace bleibt statisch. Der Export zerlegt die Daten in Raumzellen von 0,5 Grad mit Manifest.
5. Karte: Region bis Zoom 13, Ring Zoom 14, Städtekerne Zoom 15. Größen werden in R2 gemessen.
6. Die Desktop-App behält den Modus Mittelpunkt plus Radius, beide Modi aus einer Codebasis über die Region-Konfiguration.
7. Neue Landesquellen werden einzeln auf Lizenz geprüft, unklare bleiben aus (`docs/rlp/offen.md`).
8. DSFA und Impressum werden um die Fläche ergänzt. Die rechtliche Abnahme liegt beim Betreiber.

## Alternativen

- Rechteck statt Polygon: schneidet Hessen und Baden-Württemberg unsauber ab.
- Eigene Overpass-Instanz: mehr Betrieb als ein wöchentlicher Auszug.
- Sofort PostGIS: Aufwand ohne Messung, siehe Grundsatz "messen, nicht raten".

## Folgen

Mehr Daten je Export und mehr Kartenbytes. Der Zellenlader und die Modularisierung des Frontends sind Pflicht, keine Kür. Die Phasen R1 bis R7 stehen in `docs/rlp/plan.md`.
