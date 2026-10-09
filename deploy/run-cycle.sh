#!/usr/bin/env bash
# =============================================================================
# OSINT by CTW — ein Durchlauf der Sammelstelle: abrufen → exportieren → hochladen
#
# Zweck:     Von Cron im Fünf-Minuten-Takt gestartet. Holt fällige Quellen (Intervall je Quelle
#            aus sources.yaml), schreibt die JSON-Dateien und lädt sie auf den Webspace.
# Aufruf:    deploy/run-cycle.sh            (Konfiguration aus <Projekt>/.env, siehe .env.example)
# Live:      Quellen mit params.live (Flüge) holt app/live.py in kurzem Takt; OSINT_LIVE=0 legt sie zurück in diesen Zyklus.
# Ablauf:    1. python -m app.collect --due     ein Fehler einer Quelle stoppt den Rest nicht
#            2. python -m app.export            immer, damit der Status („nicht erreichbar seit …“) sichtbar wird
#            3. deploy/publish.sh --data        nur wenn PUBLISH_ENABLED=1
# Sperre:    Läuft schon ein Durchlauf, endet dieser sofort (Exit 0). Portabel per mkdir, läuft auf Linux und macOS.
# Exit:      0 = Export erzeugt (und, falls aktiv, hochgeladen), 1 = Export oder Upload fehlgeschlagen
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="${TMPDIR:-/tmp}/osint-cycle.lock"

log() { printf '%s [cycle] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

PY="${ROOT}/.venv/bin/python"
[[ -x "${PY}" ]] || { log "FEHLER: ${PY} fehlt (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)"; exit 1; }

if ! mkdir "${LOCK}" 2>/dev/null; then
  # Verwaiste Sperre (Absturz, Stromausfall) nach 30 Minuten verwerfen
  if [[ -n "$(find "${LOCK}" -maxdepth 0 -mmin +30 2>/dev/null)" ]]; then
    log "Verwaiste Sperre entfernt"; rmdir "${LOCK}"; mkdir "${LOCK}"
  else
    log "Vorheriger Durchlauf läuft noch, überspringe"; exit 0
  fi
fi
trap 'rmdir "${LOCK}" 2>/dev/null || true' EXIT

cd "${ROOT}"
if [[ "${OSINT_LIVE:-1}" == "1" ]]; then LIVE_FLAG="--skip-live"; else LIVE_FLAG=""; fi
# shellcheck disable=SC2086
"${PY}" -m app.collect --due ${LIVE_FLAG} || log "WARNUNG: mindestens eine Quelle ist fehlgeschlagen (steht im Status)"

"${PY}" -m app.export || { log "FEHLER: Export fehlgeschlagen"; exit 1; }

if [[ "${PUBLISH_ENABLED:-0}" == "1" ]]; then
  "${ROOT}/deploy/publish.sh" --data || { log "FEHLER: Upload fehlgeschlagen, nächster Durchlauf versucht es erneut"; exit 1; }
else
  log "Upload aus (PUBLISH_ENABLED != 1)"
fi
log "fertig"
