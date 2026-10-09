# R2 Kartenbasis: Bau und Messwerte

Stand: 9. Oktober 2026. Region: Rheinland-Pfalz plus 80 km (`region-rlp.yaml`). Der Bau läuft auf dem Mac (Linux-VM, 4 Kerne, 3,9 GB RAM), weil der Sandkasten die Kachelquelle nicht erreicht.

## Ablauf (wiederholbar, Reihenfolge einhalten)

```bash
export OSINT_REGION=region-rlp.yaml
pip install -r requirements-tools.txt            # pmtiles, shapely, pyyaml, mapbox-vector-tile
# 1. Karten: Stücke holen, vereinen, prüfen. Exit 2 = Zeitbudget erreicht, Befehl wiederholen.
python tools/build_region_tiles.py --pmtiles ./pmtiles --stage all --work build/tiles --out build/tiles/final --budget-s 150
python tools/check_tiles.py --dir build/tiles/final --volume
# 2. Höhenmodell (Terrarium, Zoom 6 bis 12), ebenfalls wiederaufnehmbar
python tools/build_dem.py --dest build/dem --budget-s 100
# 3. Abgeleitetes
python tools/build_terrain.py --dem build/dem --out build/out/data
python tools/build_orientation.py --out build/out/geo/kreise.geojson
python tools/build_gazetteer.py --output app/data/orte.json
python tools/build_search_index.py --tiles build/tiles/final/region.pmtiles --core build/tiles/final/core.pmtiles \
       --out build/out/data/suche_geo.json --raw build/search_raw.json.gz --budget-s 120
```

`build_region_tiles.py` holt je Stück (Zelle 0,5° x 0,34°) einen Teilauszug aus dem Protomaps-Tagesbuild (`pmtiles extract`, nur Bereichsabrufe, kein Planet-Download), prüft jedes Stück, legt es atomar ab und vereint die Stücke erst, wenn alle da sind. Unterbrechen und Wiederholen ist sicher. Das Build-Datum steht in `work/BUILD`; ein anderes Datum bricht ab, statt zwei Stände zu mischen.

## Archive

| Datei | Zoom | Inhalt | Kacheln | Größe |
|---|---|---|---|---|
| `region.pmtiles` | 0 bis 13 | ganze Fläche | 13.181 | 413 MB |
| `ring.pmtiles` | 14 | Fläche ohne Kerne (Gebäudeumrisse) | 35.681 | 368 MB |
| `core.pmtiles` | 14 bis 15 | 12 Kerne (Heimatkern Südeifel, Mainz, Koblenz, Kaiserslautern, Ludwigshafen/Mannheim, Worms, Speyer, Landau, Neuwied, Bad Kreuznach, Saarbrücken, Metz) | 16.435 | 130 MB |
| `dem/` | 6 bis 12 | Terrarium-PNG | 6.131 | 676 MB |
| `terrain.png` | | Geländefaktoren (769 x 854) | | 1,1 MB |
| `suche_geo.json` | | 159.857 Einträge (gezippt 2,1 MB) | | 6,5 MB |
| `app/data/orte.json` | | 22.482 Orte | | 1,2 MB |
| `kreise.geojson` | | 147 Kreise (DWD, nur Deutschland) | | 0,25 MB |

Karten und Höhenmodell zusammen: rund 1,6 GB (vorher 869 MB für 120 km). Quelle der Kacheln: Protomaps-Build vom Tag des Laufs (OSM, ODbL), Höhen: Mapzen Terrain Tiles (SRTM, EU-DEM).

## Messwerte

- Abruf: 91 + 89 + 12 Stücke in 9 Aufrufen zu je höchstens 150 s, zusammen etwa 12 Minuten reine Laufzeit.
- Vereinen: region 13 s, ring 18 s, cores 1 s. `pmtiles verify` ohne Fehler für alle drei.
- Höhenmodell: 3 Durchgänge, etwa 5 Minuten, 676 MB.
- Suchindex: 2 Minuten 14 Sekunden in einem Durchgang.
- `check_tiles.py`: zehn Orte (Irrel, Trier, Koblenz, Mainz, Kaiserslautern, Saarbrücken, Landau, Neuwied, Pirmasens, Idar-Oberstein) bei Zoom 8, 13 und 14 (Kerne zusätzlich 15): 0 Lücken, Gebäudeebene bei Zoom 13 und 14 gefüllt.
- Startmenge laut `check_tiles.py --volume` (Vektorkacheln, komprimiert, Fenster 1920 x 1080): Heimatansicht Zoom 10 5,9 MB, Landesansicht Zoom 7 1,9 MB, Stadtansicht Mainz Zoom 13 1,3 MB. Dazu kommen Höhenkacheln (rund 120 KB je Kachel bei Zoom 10) und `terrain.png`.

## Nicht gemessen, nicht erledigt

- **Ladezeit im Browser** bis zur sichtbaren Karte (Ziel unter 10 s) ist nicht gemessen. Gemessen ist nur die Übertragungsmenge. Die Messung braucht die neuen Dateien unter `web/tiles` und einen Browser; sie gehört in den Test der Auslieferung (R4).
- **Gewässernetz** (Rhein, Mosel, Nahe, Lahn, Saar, Main, Neckar, Maas): `build_gewaessernetz.py` ordnet die Pegelstationen den Flüssen zu und braucht deren Liste (`gewaesser.json`) aus den Sammlern der neuen Fläche. Das geht erst nach R3 sinnvoll.
- **Lokaler OSM-Auszug** (Geofabrik) ist nicht gebaut. Die Karte braucht ihn nicht, nur die OSM-Sammler in R3 (Overpass-Last). Dort wird er mit der Umstellung der Sammler gebaut.
- **Oberfläche**: Kreis, Vignette und Radar-Sweep zeichnen weiter den Radius aus `meta.radius_km` (R5). Die neuen Archive sind noch nicht in `web/tiles` eingespielt; die laufende Karte bleibt unverändert.
- Das neue Ortsverzeichnis enthält 47 Einträge des alten nicht mehr (Overpass-Stand, Umbenennungen); 4.840 gemeinsame, 17.642 neue. Die Tests laufen unverändert (313 grün).
