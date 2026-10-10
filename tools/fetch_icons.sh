#!/usr/bin/env bash
# =============================================================================
# Landblick - RLP — Icons von uxwing.com holen
#
# Zweck:     Lädt die SVG-Icons der Oberfläche von uxwing.com nach web/icons/. Ausnahme (Entscheidung des Betreibers, 2026-09-30):
#            die Kartenzeichen der natürlichen Landmarken kommen aus OpenStreetMap Carto und Maki (beide CC0), siehe unten.
# Lizenz:    UXWing-Lizenz (https://uxwing.com/license/): freie Nutzung auch gewerblich, in Websites, ohne
#            Namensnennung, Änderung erlaubt. VERBOTEN: Weiterverkauf, Weiterverbreitung, Unterlizenzierung.
#            Deshalb liegen die SVG-Dateien NICHT im Repository (.gitignore), sondern werden von diesem Skript
#            bei Bedarf geholt. Die fertige Webseite darf sie ausliefern (Nutzung in einer Website).
# Aufruf:    tools/fetch_icons.sh              lädt fehlende Icons
#            tools/fetch_icons.sh --force      lädt alle neu
# Ablauf:    Rollenname (deutsch, wie im CSS) → uxwing-Name. Die Seite uxwing.com/<name>-icon/ verweist auf die SVG-Datei.
# Exit:      0 = alle Icons vorhanden, 1 = mindestens eines fehlt
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/web/icons"
force=0; [[ "${1:-}" == "--force" ]] && force=1
log() { printf '%s [icons] %s\n' "$(date '+%H:%M:%S')" "$*"; }

# rolle=uxwing-name
ICONS=(
  "flug=aeroplane"
  "stau=cars"
  "baustelle=construction-traffic-cone"
  "sperrung=barrier"
  "warnung=exclamation-warning-round-black"
  "hochwasser=flood"
  "pegel=water-wave"
  "temperatur=thermometer"
  "wolken=cloud"
  "regen=cloud-rain"
  "wind=cloud-wind"
  "feuchte=drop-humidity"
  "druck=pressure-gauge-meter"
  "relief=mountain"
  "strahlung=radiation"
  "luft=lungs"
  "beben=earthquake"
  "hubschrauber=helicopter"
  "ton=volume-up"
  "blitz=lightning"
  "feuer=fire"
  "bahn=metro-train"
  "natur=hiking"
)

mkdir -p "${DEST}"
missing=0
for pair in "${ICONS[@]}"; do
  role="${pair%%=*}"; slug="${pair#*=}"
  if [[ -s "${DEST}/${role}.svg" && "${force}" -eq 0 ]]; then continue; fi
  page="https://uxwing.com/${slug}-icon/"
  url="$(curl -fsS -m 20 -A 'Landblick/1.0 (Icon-Abruf)' "${page}" \
        | grep -o "https://uxwing.com/wp-content/themes/uxwing/download/[a-z0-9-]*/${slug}-icon.svg" | head -1 || true)"
  if [[ -z "${url}" ]]; then log "FEHLT ${role} (${slug}): keine SVG-Adresse auf ${page}"; missing=1; continue; fi
  if curl -fsS -m 20 -A 'Landblick/1.0 (Icon-Abruf)' -o "${DEST}/${role}.svg.tmp" "${url}" && grep -q '<svg' "${DEST}/${role}.svg.tmp"; then
    mv "${DEST}/${role}.svg.tmp" "${DEST}/${role}.svg"; log "ok ${role}"
  else
    rm -f "${DEST}/${role}.svg.tmp"; log "FEHLT ${role} (${slug}): Download fehlgeschlagen"; missing=1
  fi
  sleep 0.3
done

# Kartenzeichen für natürliche Landmarken: gemeinfrei (CC0), keine Namensnennung nötig, aber bewusst als eigene Quelle geführt.
#   OpenStreetMap Carto (CC0 1.0):  https://github.com/gravitystorm/openstreetmap-carto/tree/master/symbols
#   Maki von Mapbox (CC0 1.0):      https://github.com/mapbox/maki
# rolle=adresse
CARTO="https://raw.githubusercontent.com/gravitystorm/openstreetmap-carto/master/symbols"
MAKI="https://raw.githubusercontent.com/mapbox/maki/main/icons"
MAP_ICONS=(
  "hoehle=${CARTO}/natural/cave.svg"
  "wasserfall=${CARTO}/natural/waterfall.svg"
  "fernglas=${CARTO}/tourism/viewpoint.svg"
  "quelle=${MAKI}/water.svg"        # Tropfen; der Carto-Ring liest sich auf der Karte als Punkt
  "gebirge=${MAKI}/mountain.svg"
  "vulkan=${MAKI}/volcano.svg"
  "burg=${MAKI}/castle.svg"                # Burg, Schloss, Festung, Ruine (Ruine in Grau)
  "denkmal=${MAKI}/monument.svg"           # Ausgrabungsstätte, archäologischer Fundort
  "kloster=${MAKI}/religious-christian.svg"
  "gebaeude=${MAKI}/landmark.svg"          # historisches Gebäude, Stadttor, Turm
)
for pair in "${MAP_ICONS[@]}"; do
  role="${pair%%=*}"; url="${pair#*=}"
  if [[ -s "${DEST}/${role}.svg" && "${force}" -eq 0 ]]; then continue; fi
  if curl -fsS -m 20 -A 'Landblick/1.0 (Icon-Abruf)' -o "${DEST}/${role}.svg.tmp" "${url}" && grep -q '<svg' "${DEST}/${role}.svg.tmp"; then
    mv "${DEST}/${role}.svg.tmp" "${DEST}/${role}.svg"; log "ok ${role} (CC0)"
  else
    rm -f "${DEST}/${role}.svg.tmp"; log "FEHLT ${role}: Download von ${url} fehlgeschlagen"; missing=1
  fi
done
exit "${missing}"
