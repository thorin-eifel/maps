#!/usr/bin/env bash
# Zweck:    Baut den Python-Dienst (app/desktop.py) als Einzeldatei und legt ihn samt pmtiles-CLI als Tauri-Sidecar ab.
# Aufruf:   desktop/build-sidecar.sh            (danach: cd desktop && npm ci && npx tauri build)
# Braucht:  Python 3.11+, pip, curl, unzip/tar; baut für das System, auf dem es läuft (kein Cross-Build).
# Hinweis:  Beispieldaten und Höhenkacheln aus web/ kommen NICHT mit (sie gehören zu Irrel); der Dienst liefert Daten aus dem Datenordner.
#           PMTILES_VERSION (hier 1.31.2) prüfen: github.com/protomaps/go-pmtiles/releases
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ROOT}/desktop/src-tauri/binaries"
PMTILES_VERSION="${PMTILES_VERSION:-1.31.2}"
die() { echo "FEHLER: $*" >&2; exit 1; }
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"; [[ -n "${TRIPLE}" ]] || die "rustc fehlt (Zielplattform unbekannt)"
EXT=""; [[ "${TRIPLE}" == *windows* ]] && EXT=".exe"
mkdir -p "${BIN}"

WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT
python3 -m venv "${WORK}/venv"; PY="${WORK}/venv/bin/python"; [[ -x "${PY}" ]] || PY="${WORK}/venv/Scripts/python.exe"
"${PY}" -m pip install -q -r "${ROOT}/requirements.txt" "pyinstaller==6.*"

# Weboberfläche ohne Beispieldaten und ohne Höhenkacheln
mkdir -p "${WORK}/web"
rsync -a --exclude 'data/' --exclude 'tiles/' "${ROOT}/web/" "${WORK}/web/"
SEP=":"; [[ "${TRIPLE}" == *windows* ]] && SEP=";"
( cd "${ROOT}" && "${PY}" -m PyInstaller --onefile --name osint-core --distpath "${WORK}/dist" --workpath "${WORK}/build" --specpath "${WORK}" \
    --paths "${ROOT}" --collect-submodules app --collect-data app --collect-data certifi \
    --add-data "${WORK}/web${SEP}web" --add-data "${ROOT}/sources.yaml${SEP}." --add-data "${ROOT}/region.yaml${SEP}." app/desktop.py )
# Rauchtest: das Paket muss Region und Quellenregister finden (fehlende Datendateien fielen sonst erst im Betrieb auf)
( cd "${WORK}" && OSINT_NO_DOTENV=1 "${WORK}/dist/osint-core${EXT}" --run app.region >/dev/null ) || die "Rauchtest fehlgeschlagen: app.region lässt sich im Paket nicht laden"
cp "${WORK}/dist/osint-core${EXT}" "${BIN}/osint-core-${TRIPLE}${EXT}"

# pmtiles-CLI (go-pmtiles)
# Dateinamen der Releases sind uneinheitlich: macOS "go-pmtiles-VERSION_Darwin_*.zip", Linux "go-pmtiles_VERSION_Linux_*.tar.gz", Windows "go-pmtiles_VERSION_Windows_*.zip"
case "${TRIPLE}" in
  aarch64-apple-darwin) A="go-pmtiles-${PMTILES_VERSION}_Darwin_arm64.zip" ;; x86_64-apple-darwin) A="go-pmtiles-${PMTILES_VERSION}_Darwin_x86_64.zip" ;;
  x86_64-unknown-linux-gnu) A="go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz" ;; aarch64-unknown-linux-gnu) A="go-pmtiles_${PMTILES_VERSION}_Linux_arm64.tar.gz" ;;
  x86_64-pc-windows-msvc) A="go-pmtiles_${PMTILES_VERSION}_Windows_x86_64.zip" ;; *) die "Plattform ${TRIPLE} nicht vorgesehen" ;;
esac
curl -fsSL "https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/${A}" -o "${WORK}/pm.pkg" || die "pmtiles-Download fehlgeschlagen (Version/Name prüfen)"
mkdir -p "${WORK}/pm"
if [[ "${A}" == *.zip ]]; then unzip -q -o "${WORK}/pm.pkg" -d "${WORK}/pm"; else tar -xzf "${WORK}/pm.pkg" -C "${WORK}/pm"; fi
cp "${WORK}/pm/pmtiles${EXT}" "${BIN}/pmtiles-${TRIPLE}${EXT}"; chmod +x "${BIN}"/*
echo "fertig: ${BIN}"; ls -la "${BIN}"
