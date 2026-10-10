// Zellenlader: holt die Raumzellen (data/z/<x>_<y>/<art>.json), die im Bildausschnitt liegen, und wirft entfernte wieder weg.
//
// Zweck:    Die Seite lädt nicht mehr ganz Rheinland-Pfalz auf einmal, sondern Startpaket (start.json) + Manifest (manifest.json)
//           und danach nur die Zellen im Ausschnitt plus Rand. Dieses Modul kennt weder DOM noch Karte; es bekommt eine
//           Abruffunktion und liefert zusammengeführte Nutzlasten in der Form der alten Flachdateien (features, stations, stops, items).
// Raster:   0,5 Grad, x = floor(lon*2), y = floor(lat*2); ein Punkt auf der Kante gehört zur höheren Zelle (wie app/cells.py).
// Zustand:  je Zelle und Art 'loading' | 'ok' | 'error'. Fehler bleiben sichtbar (status()), ein Fehlschlag in einer Zelle lässt den Rest stehen.
// Änderung: Das Manifest trägt je Datei eine Prüfsumme. Ändert sie sich, wird die gehaltene Datei beim nächsten ensure() neu geholt,
//           sonst nicht (kein Netzverkehr bei jedem Takt).
// Alter:    Zellen tragen keine Uhrzeit des Abrufs (R4-Kontrakt). Das Zusammenführen setzt `fetched_at`, `source_status` und
//           `age_s` aus dem Quellenzustand des Startpakets (anreichern()).
// Test:     tests/js/zellen.test.mjs

export const KIND_KEY = {
  events: 'features', gewaesser: 'stations', umwelt: 'stations', haltestellen: 'stops', landmarks: 'items',
  infrastruktur: 'items', sakral: 'items', routen: 'items', anbau: 'features', kraftstoff: 'stations',
};

// Welche Arten ab welcher Zoomstufe geladen werden (Ebenenbudget). Darunter zeigt die Karte nur Zählwerte aus dem Startpaket.
export const KIND_MIN_ZOOM = {
  events: 8, gewaesser: 8, umwelt: 8, kraftstoff: 9, haltestellen: 10, landmarks: 10, infrastruktur: 11, routen: 10, anbau: 11, sakral: 11,
};

export const cellId = (lon, lat) => `${Math.floor(lon * 2)}_${Math.floor(lat * 2)}`;

/** Zellen, die ein Rechteck {w, s, e, n} berühren, erweitert um `margin` Zellen (Standard 1 = eine halbe Gradbreite Rand). */
export function cellsInBounds(b, margin = 1) {
  const x0 = Math.floor(b.w * 2) - margin, x1 = Math.floor(b.e * 2) + margin;
  const y0 = Math.floor(b.s * 2) - margin, y1 = Math.floor(b.n * 2) + margin;
  const out = [];
  for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) out.push(`${x}_${y}`);
  return out;
}

export function kindsForZoom(zoom, wanted = Object.keys(KIND_KEY)) {
  return wanted.filter((k) => zoom >= (KIND_MIN_ZOOM[k] ?? 99));
}

const itemKey = (kind, it) => it.id ?? it.properties?.id ?? it.station_id ?? `${it.name ?? ''}|${it.lat ?? ''}|${it.lon ?? ''}`;

export class ZellenSpeicher {
  /**
   * @param {{fetchJSON: (path: string) => Promise<any>, parallel?: number, retryMs?: number, maxCells?: number, now?: () => number}} o
   */
  constructor({ fetchJSON, parallel = 6, retryMs = 30000, maxCells = 80, now = Date.now }) {
    this.fetchJSON = fetchJSON;
    this.parallel = parallel;
    this.retryMs = retryMs;
    this.maxCells = maxCells;
    this.now = now;
    this.files = {};          // rel → { sha256, bytes, kind, cell } aus dem Manifest
    this.held = new Map();    // rel → { state, sha, data, err, at }
    this.version = 0;         // zählt jede sichtbare Änderung (für Zwischenspeicher der Abnehmer)
    this._merged = new Map(); // art → { version, value }
    this._queue = [];
    this._active = 0;
  }

  setManifest(m) {
    this.files = m?.files ?? {};
    this.cells = new Set(m?.cells ?? []);
  }

  has(cell) { return !this.cells || this.cells.has(cell); }

  /** Dateien, die für diese Zellen und Arten laut Manifest existieren. */
  wanted(cells, kinds) {
    const out = [];
    for (const c of cells) for (const k of kinds) { const rel = `z/${c}/${k}.json`; if (this.files[rel]) out.push(rel); }
    return out;
  }

  /** Holt fehlende oder veränderte Dateien; gibt ein Versprechen zurück, das erst nach dem letzten Abruf erfüllt wird (Fehler werfen nicht). */
  async ensure(cells, kinds) {
    const rels = this.wanted(cells, kinds);
    const jobs = [];
    for (const rel of rels) {
      const h = this.held.get(rel), sha = this.files[rel].sha256;
      if (h?.state === 'ok' && h.sha === sha) continue;
      if (h?.state === 'loading') { jobs.push(h.promise); continue; }
      if (h?.state === 'error' && h.sha === sha && this.now() - h.at < this.retryMs) continue;
      jobs.push(this._load(rel, sha));
    }
    await Promise.all(jobs);
    return rels.length;
  }

  _load(rel, sha) {
    const prev = this.held.get(rel);
    const entry = { state: 'loading', sha, data: prev?.data ?? null, err: null, at: this.now() };   // alte Daten bleiben sichtbar, bis die neuen da sind
    entry.promise = new Promise((resolve) => {
      const run = async () => {
        this._active++;
        try {
          const d = await this.fetchJSON(`data/${rel}`);
          entry.data = d; entry.state = 'ok'; entry.err = null;
          this.version++;
        } catch (e) {
          entry.state = 'error'; entry.err = String(e?.message ?? e);
        } finally {
          entry.at = this.now(); this._active--; this._pump(); resolve();
        }
      };
      this._queue.push(run);
    });
    this.held.set(rel, entry);
    this._pump();
    return entry.promise;
  }

  _pump() {
    while (this._active < this.parallel && this._queue.length) this._queue.shift()();
  }

  /** Wirft Dateien weg, deren Zelle nicht in `keep` liegt oder (wenn `kinds` gegeben) deren Art bei dieser Zoomstufe nicht gebraucht wird. */
  evict(keep, kinds = null) {
    const keepSet = new Set(keep);
    let dropped = 0;
    for (const [rel, h] of this.held) {
      const [, cell, file] = rel.split('/');
      const kind = file.replace('.json', '');
      if ((!keepSet.has(cell) || (kinds && !kinds.includes(kind))) && h.state !== 'loading') { this.held.delete(rel); dropped++; }
    }
    if (dropped) this.version++;
    return dropped;
  }

  /** Gehaltene Zellen mit Zustand, für Statusanzeige und Prüfzugang. */
  status() {
    const s = { ok: 0, loading: 0, error: 0, cells: new Set(), errors: [] };
    for (const [rel, h] of this.held) {
      s[h.state]++; s.cells.add(rel.split('/')[1]);
      if (h.state === 'error') s.errors.push({ rel, err: h.err });
    }
    s.cells = s.cells.size;
    return s;
  }

  /** Alle gehaltenen Zellen einer Art zu einer Nutzlast in der Form der alten Flachdatei zusammengeführt (Dubletten über Zellkanten entfernt). */
  merged(kind) {
    const c = this._merged.get(kind);
    if (c && c.version === this.version) return c.value;
    const key = KIND_KEY[kind];
    const seen = new Set(), items = [], srcs = new Map();
    for (const [rel, h] of this.held) {
      if (h.data == null || !rel.endsWith(`/${kind}.json`)) continue;
      for (const s of h.data.sources ?? []) srcs.set(s.id, s);
      for (const it of h.data[key] ?? []) {
        const k = itemKey(kind, it);
        if (seen.has(k)) continue;
        seen.add(k); items.push(it);
      }
    }
    const sources = [...srcs.values()].sort((a, b) => (a.id < b.id ? -1 : 1));
    const value = { kind, [key]: items, sources, source: sources[0] ?? null };
    if (kind === 'events') value.type = 'FeatureCollection';
    this._merged.set(kind, { version: this.version, value });
    return value;
  }
}

/**
 * Setzt Abrufzeit, Status und Alter aus dem Quellenzustand des Startpakets (Zellen tragen sie nicht).
 * `sourcesById`: id → { last_success, status, ... } nach deriveStatus (js/rules.js); `nowMs`: Uhr des Betrachters.
 * Verändert die Einträge nicht, sondern gibt flache Kopien zurück; unbekannte Quelle ergibt `source_status: 'unknown'`.
 */
export function anreichern(kind, payload, sourcesById, nowMs) {
  const key = KIND_KEY[kind];
  const stamp = (src) => {
    const ok = src?.last_success ?? null;
    return { fetched_at: ok, source_status: src?.status ?? 'unknown', age_s: ok ? Math.max(0, Math.round((nowMs - Date.parse(ok)) / 1000)) : null };
  };
  const srcs = (payload.sources ?? []).map((s) => ({ ...s, ...stamp(sourcesById.get(s.id)) }));
  const out = { ...payload, sources: srcs, source: srcs[0] ?? null };
  if (kind === 'events') {
    out[key] = payload[key].map((f) => ({ ...f, properties: { ...f.properties, ...stamp(sourcesById.get(f.properties.source_id)) } }));
  } else if (srcs[0]) {
    out.fetched_at = srcs.map((s) => s.fetched_at).filter(Boolean).sort().at(-1) ?? null;
  }
  return out;
}

/**
 * Ebenenbudget für die Karte: wie viele Ereignisse bei welcher Zoomstufe gezeichnet werden.
 * Unter Zoom 9 nur ab Stufe "Hinweis" (info-Meldungen sind dort Rauschen), höchste Stufe zuerst; harte Obergrenze je Band.
 * Rein: gibt eine neue Liste zurück, die Eingabe bleibt unverändert.
 */
export function ebenenBudget(features, zoom) {
  const rank = (f) => f.properties.severity_rank ?? 0;
  const [min, cap] = zoom < 9 ? [1, 1500] : [0, 5000];
  const keep = features.filter((f) => rank(f) >= min);
  if (keep.length <= cap) return keep;
  return keep.slice().sort((a, b) => rank(b) - rank(a)).slice(0, cap);
}

/** Warnband-Einträge des Startpakets als Ereignis-Punkte (für Karte bei kleinen Zoomstufen und für das Warnband). */
export function warnbandAlsEreignisse(warnband, sourcesById, nowMs, bezug) {
  const hav = (lat, lon) => {
    const r = Math.PI / 180, dLat = (lat - bezug.lat) * r, dLon = (lon - bezug.lon) * r;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(bezug.lat * r) * Math.cos(lat * r) * Math.sin(dLon / 2) ** 2;
    return Math.round(2 * 6371.0088 * Math.asin(Math.sqrt(a)) * 10) / 10;
  };
  const RANK = { info: 0, notice: 1, warning: 2, critical: 3 };
  return (warnband ?? []).filter((w) => Number.isFinite(w.lat) && Number.isFinite(w.lon)).map((w) => {
    const src = sourcesById.get(w.source_id);
    const ok = src?.last_success ?? null;
    return {
      type: 'Feature', id: w.id, geometry: { type: 'Point', coordinates: [w.lon, w.lat] },
      properties: {
        id: w.id, source_id: w.source_id, source_short: w.source_short, source_name: src?.name ?? w.source_short, attribution: src?.attribution ?? null,
        type: w.type, title: w.title, summary: '', severity: w.severity, severity_rank: RANK[w.severity] ?? 0, lat: w.lat, lon: w.lon,
        distance_km: hav(w.lat, w.lon), region_tag: w.region_tag, ars: w.ars ?? null, land: w.land ?? null, valid_from: w.valid_from, valid_to: w.valid_to,
        fetched_at: ok, source_status: src?.status ?? 'unknown', age_s: ok ? Math.max(0, Math.round((nowMs - Date.parse(ok)) / 1000)) : null, stub: true,
      },
    };
  });
}

/** Zellen des Startpakets als Punkte für die Dichte-Ebene (Anzahl Ereignisse je Zelle, höchste Stufe). */
export function dichtePunkte(cells, art = 'events') {
  return Object.entries(cells ?? {}).filter(([, c]) => (c.counts?.[art] ?? 0) > 0).map(([id, c]) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [(c.bbox[0] + c.bbox[2]) / 2, (c.bbox[1] + c.bbox[3]) / 2] },
    properties: { id, n: c.counts[art], sev: c.max_severity ?? 'info', bbox: JSON.stringify(c.bbox) },
  }));
}
