/* Ereignisliste: Sortierung und Filter als reine Funktionen (testbar ohne DOM).
 *
 * Standard: Schwere absteigend, dann Entfernung zu Irrel aufsteigend, dann Alter (neu zuerst).
 * Die Sortierschlüssel sind stabil gestaffelt: jeder Schlüssel hat einen Tie-Breaker,
 * damit die Liste bei gleichen Werten nicht springt, wenn sie alle 15 s neu gebaut wird.
 */
const rank = (p) => p.severity_rank ?? 0;
const dist = (p) => (Number.isFinite(p.distance_km) ? p.distance_km : Infinity);
const ts = (p) => Date.parse(p.valid_from ?? p.fetched_at ?? '') || 0;
const by = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

export const SORTS = {
  prio: { label: 'Schwere, dann Entfernung', cmp: (a, b) => rank(b) - rank(a) || by(dist(a), dist(b)) || by(ts(b), ts(a)) },
  dist: { label: 'Entfernung', cmp: (a, b) => by(dist(a), dist(b)) || rank(b) - rank(a) || by(ts(b), ts(a)) },
  age: { label: 'Neueste zuerst', cmp: (a, b) => by(ts(b), ts(a)) || rank(b) - rank(a) || by(dist(a), dist(b)) },
  type: { label: 'Typ', cmp: (a, b) => by(String(a.type), String(b.type)) || rank(b) - rank(a) || by(dist(a), dist(b)) },
};

/** Filter: minSev (0–3), type ('' = alle), maxKm (0 = alle), q (Teilstring in Titel/Quelle, ohne Groß/Klein). */
export function filterEvents(feats, { minSev = 0, type = '', maxKm = 0, q = '' } = {}) {
  const needle = q.trim().toLowerCase();
  return feats.filter((f) => {
    const p = f.properties;
    if (rank(p) < minSev) return false;
    if (type && p.type !== type) return false;
    if (maxKm > 0 && !(dist(p) <= maxKm)) return false;
    if (needle) {
      const hay = `${p.title ?? ''} ${p.summary ?? ''} ${p.source_short ?? p.source_name ?? ''}`.toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  });
}

/** Sortiert eine Kopie. key aus SORTS; reverse dreht die Reihenfolge um. Unbekannter Schlüssel fällt auf 'prio'. */
export function sortEvents(feats, key = 'prio', reverse = false) {
  const cmp = (SORTS[key] ?? SORTS.prio).cmp;
  const out = [...feats].sort((a, b) => cmp(a.properties, b.properties));
  return reverse ? out.reverse() : out;
}
