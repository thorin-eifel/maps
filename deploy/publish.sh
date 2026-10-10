#!/usr/bin/env bash
# =============================================================================
# Was ist los bei uns? — Upload auf den IONOS-Webspace per SFTP
#
# Zweck:     Lädt entweder nur die Datendateien (alle paar Minuten) oder die ganze Seite (bei Änderungen).
# Aufruf:    deploy/publish.sh --data          nur web/data/*.json und radar.png
#            deploy/publish.sh --delta         nur geänderte Dateien laut manifest.json (tools/publish_delta.py), Manifest zuletzt
#            deploy/publish.sh --live          nur web/data/aircraft.json und status.json (Live-Schleife)
#            deploy/publish.sh --site          Seite ohne web/data/ (HTML, CSS, JS, MapLibre, .htaccess)
#            deploy/publish.sh --site --dry-run   zeigt nur, was passieren würde
# Konfiguration (Umgebung bzw. <Projekt>/.env):
#            IONOS_SFTP_HOST      z. B. access-XXXX.webspace-host.com
#            IONOS_SFTP_USER      z. B. u12345678
#            IONOS_SFTP_PORT      Standard 22
#            IONOS_SFTP_KEY       Pfad zum privaten SSH-Schlüssel (empfohlen) ODER
#            IONOS_SFTP_PASSWORD  Passwort (geht nur über stdin an lftp, nicht in die Prozessliste)
#            IONOS_REMOTE_DIR     Zielordner im Webspace, z. B. /lagebild (Standard /)
# Voraussetzung: lftp (apt install lftp / brew install lftp). Host-Schlüssel einmalig ins known_hosts:
#            ssh-keyscan -t ed25519 "$IONOS_SFTP_HOST" >> ~/.ssh/known_hosts   (Fingerabdruck vorher gegen
#            die Angabe im IONOS-Kundencenter prüfen)
# Nebenwirkung: überschreibt Dateien im Zielordner. Löscht nichts (kein --delete).
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log() { printf '%s [publish] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "FEHLER: $*" >&2; exit 1; }

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

mode=""; dry=0
for arg in "$@"; do
  case "${arg}" in
    --data) mode="data" ;;
    --delta) mode="delta" ;;
    --live) mode="live" ;;
    --site) mode="site" ;;
    --dry-run) dry=1 ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "Unbekannte Option: ${arg}" ;;
  esac
done
[[ -n "${mode}" ]] || die "Bitte --data, --delta, --live oder --site angeben."

[[ "${dry}" -eq 1 ]] || command -v lftp >/dev/null || die "lftp fehlt."
: "${IONOS_SFTP_HOST:?IONOS_SFTP_HOST fehlt}"
: "${IONOS_SFTP_USER:?IONOS_SFTP_USER fehlt}"
remote="${IONOS_REMOTE_DIR:-/}"
[[ "${remote}" == /* ]] || die "IONOS_REMOTE_DIR muss mit / beginnen."

if [[ -n "${IONOS_SFTP_KEY:-}" ]]; then
  [[ -r "${IONOS_SFTP_KEY}" ]] || die "Schlüssel nicht lesbar: ${IONOS_SFTP_KEY}"
  connect="ssh -a -x -i ${IONOS_SFTP_KEY} -o BatchMode=yes -o StrictHostKeyChecking=yes"
  login="${IONOS_SFTP_USER},x"
elif [[ -n "${IONOS_SFTP_PASSWORD:-}" ]]; then
  connect="ssh -a -x -o StrictHostKeyChecking=yes"
  login="${IONOS_SFTP_USER},${IONOS_SFTP_PASSWORD}"
else
  die "Weder IONOS_SFTP_KEY noch IONOS_SFTP_PASSWORD gesetzt."
fi

PLAN=""
if [[ "${mode}" == "delta" ]]; then
  PY="${ROOT}/.venv/bin/python"; [[ -x "${PY}" ]] || PY="python3"
  PLAN="$(mktemp "${TMPDIR:-/tmp}/osint-plan.XXXXXX")"
  trap 'rm -f "${PLAN}"' EXIT
  "${PY}" "${ROOT}/tools/publish_delta.py" plan --data "${ROOT}/web/data" --out "${PLAN}" || die "Plan fehlgeschlagen (manifest.json fehlt? erst python -m app.export)"
  cmd=""
  while IFS= read -r f; do
    [[ "${f}" =~ ^[A-Za-z0-9_./-]+$ && "${f}" != *..* ]] || die "Unzulässiger Pfad im Plan: ${f}"
    d="$(dirname "${f}")"; target="${remote%/}/data"
    if [[ "${d}" != "." ]]; then target="${target}/${d}"; cmd+="mkdir -p -f ${target}"$'\n'; fi
    cmd+="put -O ${target} web/data/${f}"$'\n'
  done < "${PLAN}"
elif [[ "${mode}" == "live" ]]; then
  [[ -f "${ROOT}/web/data/aircraft.json" ]] || die "web/data/aircraft.json fehlt (erst python -m app.live --once)."
  cmd="put -O ${remote%/}/data web/data/aircraft.json web/data/status.json"
elif [[ "${mode}" == "data" ]]; then
  [[ -f "${ROOT}/web/data/events.json" ]] || die "web/data/events.json fehlt (erst python -m app.export)."
  cmd="mirror -R --no-perms --include-glob '*.json' --include-glob 'radar.png' --exclude-glob '.*' web/data ${remote%/}/data"
else
  cmd="mirror -R --no-perms -x '^data/' --exclude-glob '.*' web ${remote%/}"
  # .htaccess ist versteckt und würde vom Ausschluss '.*' erfasst; gezielt nachreichen
  cmd="${cmd}
put -O ${remote} web/.htaccess"
fi

if [[ "${dry}" -eq 1 ]]; then
  log "Trockenlauf: ${IONOS_SFTP_USER}@${IONOS_SFTP_HOST}, Modus ${mode}"
  printf '%s\n' "${cmd}"
  exit 0
fi

cd "${ROOT}"
# Anmeldung und Befehle über stdin: Passwort taucht nicht in der Prozessliste auf
lftp -f /dev/stdin <<LFTP || die "Upload fehlgeschlagen"
set cmd:fail-exit yes
set net:max-retries 3
set net:timeout 20
set sftp:connect-program "${connect}"
set sftp:auto-confirm no
open -u "${login}" -p "${IONOS_SFTP_PORT:-22}" sftp://${IONOS_SFTP_HOST}
${cmd}
bye
LFTP
if [[ "${mode}" == "delta" ]]; then
  "${PY}" "${ROOT}/tools/publish_delta.py" commit --data "${ROOT}/web/data" --plan "${PLAN}"
fi
log "Upload (${mode}) fertig"
