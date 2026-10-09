// Reine Regeln ohne DOM — im Browser und unter Node testbar (tests/js/rules.test.mjs).
// Spiegeln app/payloads.py: Zeitfenster und Quellenzustand. Das Frontend rechnet gegen die Uhr des
// Betrachters, damit ein veralteter Export nicht als „aktuell“ durchgeht.

export const WINDOW_HOURS = { now: 0, '24h': 24, '7d': 168 };
export const EXPORT_STALE_MIN = 20; // Cron läuft alle 5 Min.; ab 20 Min. ohne neuen Export gilt er als veraltet

const ms = (iso) => new Date(iso).getTime();

// Relevant, wenn jetzt gültig oder innerhalb des Fensters beginnend (wie DB-Abfrage active_events)
export function windowFilter(features, within, nowMs) {
  const horizon = nowMs + WINDOW_HOURS[within] * 3600 * 1000;
  return features.filter((f) => {
    const p = f.properties;
    const end = p.valid_to ? ms(p.valid_to) : Infinity;
    const start = ms(p.valid_from || p.first_seen);
    return end >= nowMs && start <= horizon;
  });
}

// down: nie erfolgreich oder ≥ 3 Fehlläufe · stale: älter als 3× Intervall · degraded: letzter Lauf Fehler
export function deriveStatus(src, nowMs) {
  if (!src) return null;
  if (src.status === 'disabled') return { ...src };
  const lastOk = src.last_success ? ms(src.last_success) : null;
  const ageS = lastOk === null ? null : Math.round((nowMs - lastOk) / 1000);
  let status;
  if (lastOk === null) status = src.last_attempt ? 'down' : 'pending';
  else if (src.consecutive_failures >= 3) status = 'down';
  else if (ageS > 3 * src.interval_s) status = 'stale';
  else if (src.consecutive_failures > 0) status = 'degraded';
  else status = 'ok';
  return { ...src, status, age_s: ageS };
}

// Sammelstatus der Anzeige
const RANK = { ok: 0, pending: 1, disabled: 1, degraded: 2, stale: 3, down: 4 };
export function overall(sources) {
  return sources.reduce((w, s) => (RANK[s.status] > RANK[w] ? s.status : w), 'ok');
}

// Ist der Export selbst veraltet (Sammelrechner aus, Upload klemmt)?
export function exportAgeMin(generatedAt, nowMs) {
  return generatedAt ? Math.round((nowMs - ms(generatedAt)) / 60000) : Infinity;
}
export const exportStale = (generatedAt, nowMs) => exportAgeMin(generatedAt, nowMs) > EXPORT_STALE_MIN;

// Symbolname (Datei web/icons/<name>.svg) je Ereignis
export function iconFor(p) {
  const kind = p.attrs?.kind;
  if (p.type === 'aircraft') return 'flug';
  if (p.type === 'congestion') return 'stau';
  if (p.type === 'flood') return 'hochwasser';
  if (p.type === 'radiation') return 'strahlung';
  if (p.type === 'air') return 'luft';
  if (p.type === 'earthquake') return 'beben';
  if (p.type === 'fire') return 'feuer';
  if (p.type === 'transit') return 'bahn';
  if (p.type === 'traffic') return kind === 'sperrung' ? 'sperrung' : kind === 'baustelle' ? 'baustelle' : 'warnung';
  return 'warnung';
}

// Flugzeug zwischen zwei Abrufen weiterrücken (geradeaus, Großkreis). Rein optisch, nichts davon wird gespeichert.
// Kurs in Grad, Tempo in km/h, dtS in Sekunden. Fehlt eine Angabe, bleibt die Position stehen.
export function advance(lon, lat, trackDeg, speedKmh, dtS) {
  if (![trackDeg, speedKmh, dtS].every(Number.isFinite) || dtS <= 0) return [lon, lat];
  const R = 6371.0088, dr = (speedKmh * dtS / 3600) / R, br = (trackDeg * Math.PI) / 180;
  const la = (lat * Math.PI) / 180, lo = (lon * Math.PI) / 180;
  const la2 = Math.asin(Math.sin(la) * Math.cos(dr) + Math.cos(la) * Math.sin(dr) * Math.cos(br));
  const lo2 = lo + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(la), Math.cos(dr) - Math.sin(la) * Math.sin(la2));
  return [(lo2 * 180) / Math.PI, (la2 * 180) / Math.PI];
}

// Verkehrsstufe für die Karte: gelb = Baustelle ohne Behinderung, orange = Behinderung oder Stau, rot = langer Stau oder
// Sperrung einer Richtung, schwarz = Vollsperrung. Andere Ereignisarten haben keine (null) und bleiben bei severity.
export function trafficLevel(p) {
  const a = p.attrs ?? {};
  if (p.type === 'congestion') return p.severity === 'warning' || p.severity === 'critical' ? 'red' : 'orange';
  if (p.type === 'transit') { // ÖPNV: Verspätung ab 5 Minuten gelb, ab 10 orange, ab 20 rot; Ausfall und Störung rot
    if (a.kind === 'verspaetung') return a.delay_min >= 20 ? 'red' : a.delay_min >= 10 ? 'orange' : 'yellow';
    return a.kind === 'ausfall' || p.severity === 'warning' ? 'red' : 'orange';
  }
  if (p.type !== 'traffic') return null;
  if (a.kind === 'sperrung') return a.sperr === 'richtung' ? 'red' : 'black';
  if (a.kind === 'baustelle') return p.severity === 'info' ? 'yellow' : 'orange';
  return 'orange';
}
