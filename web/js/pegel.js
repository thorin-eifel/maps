/* Pegelliste: Gewässernamen vereinheitlichen und sortieren (reine Funktionen, ohne DOM).
 *
 * Reihenfolge: Gewässer alphabetisch (deutsche Sortierung), innerhalb eines Gewässers die Stationen alphabetisch.
 * Stationen ohne Gewässername kommen ans Ende. Dasselbe Gewässer aus mehreren Quellen (Mosel aus PEGELONLINE, Luxemburg
 * und Hub'eau) steht in einem Block; dafür werden die französischen Namen auf die deutschen gelegt.
 */
const FR_TO_DE = { moselle: 'Mosel', sarre: 'Saar', meuse: 'Maas', sure: 'Sauer', 'sûre': 'Sauer', chiers: 'Chiers' };
const collator = new Intl.Collator('de', { sensitivity: 'base', numeric: true });

/** "La Moselle" → "Mosel", "Ruisseau de Vaux" → "Vaux", "L'Orne" → "Orne", null → null. */
export function waterName(raw) {
  if (raw == null) return null;
  let s = String(raw).trim().replace(/\s+/g, ' ');
  if (!s) return null;
  s = s.replace(/^ruisseau\s+(?:de\s+la\s+|de\s+l['’]\s*|du\s+|des\s+|de\s+|le\s+|la\s+|l['’]\s*)?/i, '');
  s = s.replace(/^(?:la|le|les)\s+/i, '').replace(/^l['’]\s*/i, '');
  if (!s) return null;
  const hit = FR_TO_DE[s.toLowerCase()];
  return hit ?? s.charAt(0).toUpperCase() + s.slice(1);
}

// Echte Gewässer zuerst, dann Sammelgruppen ohne Flussnamen (RLP-Feld "Kommunale Messstelle"), dann ohne Angabe.
const groupRank = (label) => (label == null ? 2 : /^kommunale messstelle/i.test(label) ? 1 : 0);

/** Sortiert eine Kopie der Stationsliste. Jede Station bekommt `water_label` (vereinheitlicht). */
export function sortStations(stations) {
  return stations.map((s) => ({ ...s, water_label: waterName(s.water) })).sort((a, b) => {
    const ra = groupRank(a.water_label), rb = groupRank(b.water_label);
    if (ra !== rb) return ra - rb;
    return collator.compare(a.water_label ?? '', b.water_label ?? '') || collator.compare(a.name ?? '', b.name ?? '')
      || collator.compare(String(a.station_id ?? ''), String(b.station_id ?? ''));
  });
}

// ------------------------------------------------------------------ Gewässerbaum (Strom → Fluss → Bach, von der Mündung zur Quelle)
// Grundlage ist web/data/gewaessernetz.json (tools/build_gewaessernetz.py, Wikidata): map "quelle|gewässername" → Kennung,
// rivers Kennung → {name, parent, mouth [lat,lon], src [lat,lon]}. Was nicht zugeordnet ist, bleibt in "Zuordnung offen"; geraten wird nicht.
const R = Math.PI / 180;
export function distKm(a, b) {
  const x = Math.sin((b[0] - a[0]) * R / 2) ** 2 + Math.cos(a[0] * R) * Math.cos(b[0] * R) * Math.sin((b[1] - a[1]) * R / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(x));
}

/** Position entlang des Laufs als Zahl: aufsteigend heißt von der Mündung zur Quelle. Ohne Mündungspunkt zählt der Abstand zur Quelle rückwärts. */
function along(node, pt) {
  if (!pt) return Infinity;
  if (node.mouth) return distKm(node.mouth, pt);
  if (node.src) return -distKm(node.src, pt);
  return Infinity;
}

/**
 * Baut den Baum. Rückgabe: { roots: [Knoten], open: { groups: [{label, stations}] }, none: [Stationen] }
 * Knoten: { id, name, items: [Station | Knoten] (von der Mündung zur Quelle), total }
 */
export function buildTree(stations, net) {
  const map = net?.map ?? {}, rivers = net?.rivers ?? {};
  const nodes = new Map();
  const get = (id) => {
    if (!rivers[id]) return null;
    if (!nodes.has(id)) nodes.set(id, { id, name: rivers[id].name, mouth: rivers[id].mouth ?? null, src: rivers[id].src ?? null, parent: rivers[id].parent ?? null, own: [], kids: [], total: 0 });
    return nodes.get(id);
  };
  const open = new Map(), none = [];
  for (const s of stations) {
    const id = map[`${s.source_id}|${s.water ?? ''}`];
    const n = id ? get(id) : null;
    if (n) { n.own.push(s); continue; }
    if (s.water_label == null) { none.push(s); continue; }
    if (!open.has(s.water_label)) open.set(s.water_label, []);
    open.get(s.water_label).push(s);
  }
  for (const n of [...nodes.values()]) {            // Vorfahren nachziehen, damit die Kette bis zum Strom steht
    let p = n.parent, guard = 0;
    while (p && guard++ < 12) { const pn = get(p); if (!pn) break; p = pn.parent; }
  }
  const roots = [];
  for (const n of nodes.values()) {
    const p = n.parent && nodes.get(n.parent);
    (p ? p.kids : roots).push(n);
  }
  const fin = (n) => {
    for (const k of n.kids) fin(k);
    n.total = n.own.length + n.kids.reduce((a, k) => a + k.total, 0);
    const keyed = [
      ...n.own.map((s) => ({ k: along(n, [s.lat, s.lon]), t: s, s })),
      ...n.kids.filter((k) => k.total).map((k) => ({ k: along(n, k.mouth), t: k.name, s: k })),
    ].sort((a, b) => (a.k === b.k ? collator.compare(String(a.t.name ?? a.t), String(b.t.name ?? b.t)) : a.k - b.k));
    n.items = keyed.map((x) => x.s);
  };
  roots.forEach(fin);
  const live = roots.filter((r) => r.total).sort((a, b) => collator.compare(a.name, b.name));
  const groups = [...open.entries()].sort((a, b) => (groupRank(a[0]) - groupRank(b[0])) || collator.compare(a[0], b[0]))
    .map(([label, st]) => ({ label, stations: st.sort((a, b) => collator.compare(a.name ?? '', b.name ?? '')) }));
  none.sort((a, b) => collator.compare(a.name ?? '', b.name ?? ''));
  return { roots: live, open: { groups }, none };
}

/** Gewicht einer Station für die Karte: Tiefe im Gewässerbaum (0 Strom, 1 Hauptzufluss …); ohne Zuordnung 4 (kleinste Stufe). Ohne Netzdatei 2. */
export function stationRank(s, net) {
  if (!net?.map) return 2;
  let id = net.map[`${s.source_id}|${s.water ?? ''}`];
  if (!id || !net.rivers?.[id]) return 4;
  let depth = 0;
  while (net.rivers[id]?.parent && depth < 8) { id = net.rivers[id].parent; depth += 1; }
  return Math.min(depth, 4);
}
