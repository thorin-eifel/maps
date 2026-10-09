#!/usr/bin/env bash
# Hinweis:  Für Rheinland-Pfalz plus 80 km gilt tools/build_region_tiles.py (Stücke, wiederaufnehmbar, siehe docs/rlp/r2-kartenbasis.md).
#           Dieses Skript baut den 120-km-Kreis um Irrel und bleibt für den Betrieb der bisherigen Region.
# Zweck:    Baut den Kartenausschnitt (OSM, Protomaps-Basiskarte) als PMTiles-Datei für das Lagebild.
# Aufruf:   tools/build_tiles.sh [BUILD_DATUM]   z. B. tools/build_tiles.sh 20260929
#           Ohne Datum wird der neueste Build aus build-metadata.protomaps.dev genommen.
# Ergebnis: web/tiles/region.pmtiles, core.pmtiles, ring.pmtiles und web/tiles/README.txt (Stand, Ausschnitt, Lizenz)
# Braucht:  pmtiles-CLI (tools/bin/pmtiles oder im PATH), curl, python3, Netz zu build.protomaps.com
# Hinweis:  Es wird nur der Ausschnitt geladen (Teilabrufe, je nach Zoom 200 bis 650 MB), nicht der Planet.
#           Ausschnitt: etwas größer als die Bounding Box des Lagebilds (Südeifel + 120 km, inkl. Luxemburg).
#           Danach hochladen: deploy/publish.sh --site, dann tools/check_range.py <URL der Datei>.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BBOX="4.63,48.61,8.28,51.08"   # lon_min,lat_min,lon_max,lat_max: Kasten des 120-km-Radius (48.76/4.78 bis 50.93/8.13) plus 0,15° Rand
CORE_BBOX="5.90,49.49,7.02,50.21"   # Kern um Irrel (ca. 80 x 80 km: Trier, Bitburg, Echternach, Luxemburg) mit Zoom 15: Gebäude und Hausnummern, ca. 120 MB
RING_KM="${RING_KM:-121}"   # Kreis des Rings in km um Irrel
CENTER="49.846,6.456"
THREADS="${THREADS:-2}"   # der Protomaps-Server bricht bei vielen parallelen Strömen gern ab (INTERNAL_ERROR); zwei sind langsamer, aber halten
MAXZOOM="${MAXZOOM:-13}"   # 13 = grob (ca. 285 MB bei 120 km; Gebäude und Hausnummern kommen aus core.pmtiles); 14 = bei 120 km grob 700 MB und bricht am Server gern ab; 15 = über 1 GB; per MAXZOOM=... überschreibbar
OUT_DIR="${ROOT}/web/tiles"
log() { printf '%s [tiles] %s\n' "$(date '+%F %T')" "$*"; }
die() { log "FEHLER: $*"; exit 1; }

PMTILES="${ROOT}/tools/bin/pmtiles"
[[ -x "${PMTILES}" ]] || PMTILES="$(command -v pmtiles || true)"
[[ -n "${PMTILES}" ]] || die "pmtiles-CLI fehlt (github.com/protomaps/go-pmtiles/releases, nach tools/bin/ legen)"

BUILD="${1:-}"
if [[ -z "${BUILD}" ]]; then
  BUILD="$(curl -fsS -m 30 https://build-metadata.protomaps.dev/builds.json \
    | python3 -c 'import json,sys; b=json.load(sys.stdin); print(sorted(x["key"] for x in b)[-1].split(".")[0])')" \
    || die "Build-Liste nicht erreichbar"
fi
[[ "${BUILD}" =~ ^[0-9]{8}$ ]] || die "Build-Datum muss JJJJMMTT sein, war: ${BUILD}"

mkdir -p "${OUT_DIR}"
TMP="${OUT_DIR}/.region.tmp.pmtiles"
trap 'rm -f "${TMP}"' EXIT
log "Build ${BUILD}, Ausschnitt ${BBOX}, Zoom 0-${MAXZOOM}"
rm -f "${TMP}"
"${PMTILES}" extract "https://build.protomaps.com/${BUILD}.pmtiles" "${TMP}" --bbox="${BBOX}" --maxzoom="${MAXZOOM}" --download-threads="${THREADS:-2}"
"${PMTILES}" show "${TMP}" >/dev/null || die "Ergebnis nicht lesbar"
mv -f "${TMP}" "${OUT_DIR}/region.pmtiles"

# Kern mit Zoom 15 (Gebäude, Hausnummern stehen erst in Zoom 15 in den Kacheln): die große Datei geht nur bis Zoom 13, weil der Abruf in der Tiefe über 120 km am Protomaps-Server abbricht
log "Kern ${CORE_BBOX}, Zoom 0-15"
rm -f "${TMP}"
"${PMTILES}" extract "https://build.protomaps.com/${BUILD}.pmtiles" "${TMP}" --bbox="${CORE_BBOX}" --maxzoom=15 --download-threads="${THREADS:-2}"
"${PMTILES}" show "${TMP}" >/dev/null || die "Kern nicht lesbar"
mv -f "${TMP}" "${OUT_DIR}/core.pmtiles"

# Ring mit Zoom 14: Häuserumrisse im ganzen 120-km-Kreis. Gebäude stehen erst ab Zoom 14 in den Kacheln, die große Datei endet bei 13.
# Nur Zoom 14 und nur außerhalb des Kerns (GeoJSON mit Loch), damit nichts doppelt liegt: ca. 140 MB statt 700 MB für Zoom 0-14 über den ganzen Kreis.
log "Ring Zoom 14 (Kreis ${RING_KM} km um ${CENTER}, ohne Kern)"
REGION="${TMP}.geojson"
python3 - "${REGION}" "${RING_KM}" "${CORE_BBOX}" <<'PY'
import json, math, sys
out, km, core = sys.argv[1], float(sys.argv[2]), [float(x) for x in sys.argv[3].split(",")]
clat, clon = 49.846, 6.456
ring = [[round(clon + km * math.sin(a) / (111.32 * math.cos(math.radians(clat))), 5), round(clat + km * math.cos(a) / 110.57, 5)]
        for a in (2 * math.pi * i / 180 for i in range(181))]
hole = [[core[0], core[1]], [core[0], core[3]], [core[2], core[3]], [core[2], core[1]], [core[0], core[1]]]
json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring, hole]}}]}, open(out, "w"))
PY
rm -f "${TMP}"
"${PMTILES}" extract "https://build.protomaps.com/${BUILD}.pmtiles" "${TMP}" --region="${REGION}" --minzoom=14 --maxzoom=14 --download-threads="${THREADS:-2}"
rm -f "${REGION}"
"${PMTILES}" show "${TMP}" >/dev/null || die "Ring nicht lesbar"
mv -f "${TMP}" "${OUT_DIR}/ring.pmtiles"

cat > "${OUT_DIR}/README.txt" <<TXT
region.pmtiles: Protomaps-Basiskarte, Build ${BUILD}, Ausschnitt ${BBOX} (lon_min,lat_min,lon_max,lat_max), Zoom 0-${MAXZOOM}.
core.pmtiles: derselbe Build, Kern ${CORE_BBOX}, Zoom 0-15 (Gebäude und Hausnummern).
ring.pmtiles: derselbe Build, Kreis ${RING_KM} km um Irrel ohne den Kern, nur Zoom 14 (Häuserumrisse im restlichen Gebiet).
Daten: © OpenStreetMap-Mitwirkende (ODbL 1.0), Natural Earth (gemeinfrei); Kachelbau: Protomaps (Schema-Version 4).
Neu bauen: tools/build_tiles.sh [JJJJMMTT]. Diese Datei gehört nicht ins Git (siehe .gitignore).
TXT
log "fertig: $(du -h "${OUT_DIR}/region.pmtiles" | cut -f1)"
