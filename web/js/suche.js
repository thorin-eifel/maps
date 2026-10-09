// Suche über alle Namen (Orte, Straßen, Gewässer, Gelände, Einrichtungen, Haltestellen, Routen, Pegel).
// Alles läuft im Browser: Index aus data/suche_geo.json (Kartenkacheln, statisch) und data/suche.json (Export, dynamisch).
// Keine Anfrage nach außen, keine Adressen, keine Hausnummern. Namen kommen aus OpenStreetMap (ODbL) und unseren Collectoren.
// Kern (fold, loadIndex, search) ist rein und ohne DOM, damit er unter node getestet werden kann.

export const MAX_RESULTS = 12;

/** Suchform: klein, ohne Akzente, ß zu ss, Satzzeichen zu Leerzeichen (gleich wie app/search.py fold). */
export function fold(text) {
  return String(text ?? '').toLowerCase().replace(/ß/g, 'ss').normalize('NFKD').replace(/\p{M}/gu, '').replace(/[^0-9a-z]+/g, ' ').trim();
}

/** Zwei Indexdateien (Format v1) zu einer Liste verbinden. Fehlende oder kaputte Teile werden übergangen. */
export function mergeIndex(parts) {
  const out = [];
  for (const p of parts) {
    if (!p || p.v !== 1 || !Array.isArray(p.e) || !Array.isArray(p.t)) continue;
    const types = p.t, orte = Array.isArray(p.o) ? p.o : [];
    for (const e of p.e) {
      if (!Array.isArray(e) || e.length < 5 || typeof e[0] !== 'string') continue;
      const lat = e[2] / 1e4, lon = e[3] / 1e4;
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      out.push({ name: e[0], f: ' ' + fold(e[0]), typ: types[e[1]] ?? 'Ort', rank: e[1], lat, lon, ort: e[4] >= 0 ? (orte[e[4]] ?? '') : '' });
    }
  }
  return out;
}

const dist2 = (a, b) => { const dx = (a.lon - b.lon) * Math.cos(a.lat * Math.PI / 180), dy = a.lat - b.lat; return dx * dx + dy * dy; };

/**
 * Treffer für eine Eingabe. Jedes Suchwort muss am Anfang eines Namenswortes stehen ("trier str" findet "Trierer Straße").
 * Reihenfolge: Güte des Treffers (ganzer Name, Namensanfang, Wortanfang), dann Typ (Stadt vor Straße), dann Nähe zu `near`.
 */
export function search(entries, query, near = { lat: 49.846, lon: 6.456 }, limit = MAX_RESULTS) {
  const q = fold(query);
  if (q.length < 2) return [];
  const toks = q.split(' ');
  const scored = [];
  for (const e of entries) {
    let ok = true;
    for (const t of toks) { if (!e.f.includes(' ' + t)) { ok = false; break; } }
    if (!ok) continue;
    const full = e.f.slice(1);
    const quality = full === q ? 0 : full.startsWith(q) ? 1 : full.startsWith(toks[0]) ? 2 : 3;
    scored.push({ e, quality, d: dist2(e, near) });
  }
  scored.sort((a, b) => a.quality - b.quality || a.e.rank - b.e.rank || a.d - b.d);
  return scored.slice(0, limit).map((s) => s.e);
}

/** Zoomstufe je Typ, damit der Treffer sinnvoll im Bild liegt. */
export function zoomFor(typ) {
  if (typ === 'Stadt') return 12;
  if (['Ort', 'Gemeinde', 'Ortsteil', 'Naturschutzgebiet', 'Wald', 'Park', 'See', 'Fluss', 'Flugplatz', 'Steinbruch'].includes(typ)) return 13;
  if (['Weiler', 'Bach', 'Gipfel', 'Wanderweg', 'Radroute', 'Windpark', 'Campingplatz', 'Freizeit'].includes(typ)) return 14;
  return 15;
}

// ---------- Oberfläche ----------

/** Suchleiste an vorhandenes Markup binden (siehe index.html). `onPick(entry)` setzt Markierung und Karte. */
export function mountSearch({ input, list, status, getNear, onPick, loadParts }) {
  let entries = null, loading = null, hits = [], active = -1;

  const ensure = () => {
    if (entries) return Promise.resolve(entries);
    loading ??= loadParts().then((parts) => { entries = mergeIndex(parts); if (!entries.length) throw new Error('leer'); return entries; })
      .catch((err) => { loading = null; throw err; });
    return loading;
  };
  const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); active = -1; };
  const mark = (i) => {
    active = i;
    [...list.children].forEach((li, k) => li.setAttribute('aria-selected', String(k === i)));
    if (i >= 0) { input.setAttribute('aria-activedescendant', list.children[i].id); list.children[i].scrollIntoView({ block: 'nearest' }); }
    else input.removeAttribute('aria-activedescendant');
  };
  const pick = (i) => {
    const e = hits[i];
    if (!e) return;
    input.value = e.name;
    close();
    onPick(e);
  };
  const render = () => {
    list.replaceChildren();
    hits.forEach((e, i) => {
      const li = document.createElement('li');
      li.id = `suche-t${i}`; li.setAttribute('role', 'option'); li.setAttribute('aria-selected', 'false');
      const n = document.createElement('span'); n.className = 'suche-name'; n.textContent = e.name;
      const m = document.createElement('span'); m.className = 'suche-meta'; m.textContent = e.ort ? `${e.typ} · ${e.ort}` : e.typ;
      li.append(n, m);
      li.addEventListener('mousedown', (ev) => { ev.preventDefault(); pick(i); });   // vor dem blur des Feldes
      li.addEventListener('click', () => { if (!list.hidden) pick(i); });             // Rückfall für Eingabegeräte ohne mousedown (Touch, Automatik)
      list.append(li);
    });
    list.hidden = hits.length === 0;
    input.setAttribute('aria-expanded', String(hits.length > 0));
    active = -1;
  };
  const run = async () => {
    const q = input.value;
    if (fold(q).length < 2) { hits = []; render(); status.textContent = ''; return; }
    try { await ensure(); } catch { status.textContent = 'Der Suchindex konnte nicht geladen werden.'; hits = []; render(); return; }
    if (input.value !== q) return;                                   // inzwischen weitergetippt
    hits = search(entries, q, getNear());
    render();
    status.textContent = hits.length ? `${hits.length} Treffer. Mit Pfeiltasten wählen, mit Eingabe öffnen.` : 'Kein Treffer.';
  };

  input.form?.addEventListener('submit', (ev) => ev.preventDefault());   // kein Inline-Handler wegen CSP
  input.addEventListener('focus', () => { ensure().catch(() => {}); if (hits.length) { list.hidden = false; input.setAttribute('aria-expanded', 'true'); } });
  input.addEventListener('input', run);
  input.addEventListener('blur', () => setTimeout(close, 120));
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowDown') { ev.preventDefault(); if (list.hidden && hits.length) { list.hidden = false; input.setAttribute('aria-expanded', 'true'); } if (hits.length) mark((active + 1) % hits.length); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); if (hits.length) mark((active - 1 + hits.length) % hits.length); }
    else if (ev.key === 'Enter') { ev.preventDefault(); if (hits.length) pick(active >= 0 ? active : 0); }
    else if (ev.key === 'Escape') { if (!list.hidden) close(); else { input.value = ''; hits = []; onPick(null); } }
  });
  document.addEventListener('keydown', (ev) => {
    const typing = /^(input|textarea|select)$/i.test(document.activeElement?.tagName ?? '');
    if ((ev.key === '/' && !typing) || ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'k')) { ev.preventDefault(); input.focus(); input.select(); }
  });
}
