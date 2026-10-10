// Zellenbetrieb der Lagekarte: Startpaket und Manifest holen, Zellen im Bildausschnitt laden, in die alten Zustandsfelder einsetzen.
//
// Zweck:   Verbindet den Zellenlader (js/zellen.js, rein) mit Karte und Seitenzustand. Gibt es kein Manifest (alter Export, Entwicklung),
//          bleibt `state.zellen` leer und laden.js lädt wie bisher die Flachdateien.
// Ablauf:  initZellen() beim Start → loadView() nach jeder Kartenbewegung (entprellt) → applyCells() setzt state.base, state.gew … und
//          zeichnet Dichte-Ebene und Statuszeile neu. Gebietsfilter (Land, Landkreis) wirkt in applyCells().
// Stufen:  Zoom < 7: keine Zellen, nur Dichte-Ebene (Zählwerte je Zelle) und Warnband-Punkte aus dem Startpaket.
//          Zoom ≥ 7: Zellen im Ausschnitt plus Rand (ab Zoom 9), Arten nach Ebenenbudget (zellen.js KIND_MIN_ZOOM).
// Fehler:  Eine Zelle, die nicht kommt, steht in der Statuszeile ("1 Zelle fehlt"); die übrigen bleiben. Nach 30 s ein neuer Versuch.
import { getJSON } from '../util.js';
import { GEBIET_LEER, gebietPasst, gebietAktiv } from '../gebiet.js';
import { KIND_KEY, KIND_MIN_ZOOM, ZellenSpeicher, anreichern, cellsInBounds, dichtePunkte, kindsForZoom, warnbandAlsEreignisse } from '../zellen.js';
import { map, mapReady, state } from './zustand.js';

export const EVENTS_MIN_ZOOM = KIND_MIN_ZOOM.events;
const MARGIN_ZOOM = 9;       // ab hier eine Zelle Rand rund um den Ausschnitt mitladen (darunter wäre der Rand mehr als der Ausschnitt)
const MAX_CELLS = 60;        // Obergrenze gleichzeitig gehaltener Zellen; die Mitte des Ausschnitts hat Vorrang
const FIELD = { events: 'base', gewaesser: 'gew', umwelt: 'env', haltestellen: 'stops', landmarks: 'landmarks', infrastruktur: 'infra', routen: 'routen', sakral: 'sakral', kraftstoff: 'fuel' };

let lastKey = '', running = Promise.resolve(), onChange = () => {};
export const setzeAenderungsfunktion = (fn) => { onChange = fn; };

state.gebiet = { ...GEBIET_LEER };

/** Manifest und Startpaket holen; ohne beides bleibt der Zellenbetrieb aus. Gibt true zurück, wenn er läuft. */
export async function ladeIndex() {
  const [man, start] = await Promise.all([getJSON('data/manifest.json').catch(() => null), getJSON('data/start.json').catch(() => null)]);
  if (!man?.files || !start?.cells) return !!state.zellen;   // einmal gelaufen: letzten guten Stand behalten
  if (!state.zellen) state.zellen = new ZellenSpeicher({ fetchJSON: getJSON, maxCells: MAX_CELLS });
  state.zellen.setManifest(man);
  state.start = start;
  return true;
}

function statusMap() {
  return new Map(state.statuses.map((s) => [s.id, s]));
}

function viewCells() {
  const b = map.getBounds(), z = map.getZoom(), c = map.getCenter();
  const ids = cellsInBounds({ w: b.getWest(), s: b.getSouth(), e: b.getEast(), n: b.getNorth() }, z >= MARGIN_ZOOM ? 1 : 0);
  const mid = (id) => { const [x, y] = id.split('_').map(Number); return (x / 2 + 0.25 - c.lng) ** 2 + (y / 2 + 0.25 - c.lat) ** 2; };
  return ids.filter((id) => state.zellen.has(id)).sort((a, b2) => mid(a) - mid(b2)).slice(0, MAX_CELLS);
}

function wantedKinds(z) {
  return kindsForZoom(z).filter((k) => k !== 'sakral' || state.layers.medieval);
}

export function setzeStatuszeile() {
  const el = document.getElementById('zellen');
  if (!el || !state.zellen) return;
  const s = state.zellen.status();
  const parts = [];
  if (s.loading) parts.push(`${s.loading} Datei${s.loading > 1 ? 'en' : ''} laden`);
  if (s.error) parts.push(`${s.error} Datei${s.error > 1 ? 'en' : ''} nicht erreichbar`);
  el.textContent = parts.length ? parts.join(', ') : '';
  el.dataset.state = s.error ? 'error' : s.loading ? 'loading' : 'ok';
  el.title = s.errors.map((e) => `${e.rel}: ${e.err}`).join('\n');
}

/** Lädt, was der Ausschnitt braucht, wirft Entferntes weg und setzt die Zustandsfelder. Läuft nie doppelt. */
export function loadView(force = false) {
  running = running.then(async () => {
    if (!state.zellen || !mapReady) return;
    const z = map.getZoom(), ids = viewCells(), kinds = wantedKinds(z);
    state.zellen.evict(ids, kinds);
    const pending = state.zellen.ensure(ids, kinds);
    setzeStatuszeile();
    await pending;
    setzeStatuszeile();
    applyCells(force);
  }).catch((e) => console.warn('Zellen laden:', e));
  return running;
}

export const zellenWarten = async () => { await new Promise((r) => setTimeout(r, 400)); await running; };

export function bandKey(z) { return z < EVENTS_MIN_ZOOM ? 'L' : z < 9 ? 'M' : 'H'; }

function filterStations(payload, key) {
  if (!gebietAktiv(state.gebiet)) return payload;
  return { ...payload, [key]: payload[key].filter((s) => gebietPasst(s, state.gebiet)) };
}

/** Setzt die Zustandsfelder aus den gehaltenen Zellen. Ruft onChange (render), wenn sich etwas geändert hat. */
export function applyCells(force = false) {
  const zs = state.zellen;
  if (!zs || !state.start) return;
  const z = map.getZoom(), key = `${zs.version}|${bandKey(z)}|${state.gebiet.land}|${state.gebiet.ars}|${state.start.generated_at}|${state.statuses.length}`;
  if (!force && key === lastKey) return;
  lastKey = key;
  const src = statusMap(), now = Date.now();
  state.warnStubs = warnbandAlsEreignisse(state.start.warnband, src, now, { lat: state.meta?.center?.lat ?? 49.846, lon: state.meta?.center?.lon ?? 6.456 })
    .filter((f) => gebietPasst(f.properties, state.gebiet));
  const held = new Set([...zs.held.keys()].map((rel) => rel.split('/')[2].replace('.json', '')));
  for (const kind of Object.keys(KIND_KEY)) {
    if (!held.has(kind) || !FIELD[kind]) continue;
    let p = anreichern(kind, zs.merged(kind), src, now);
    if (kind === 'events') {
      const feats = p.features.filter((f) => gebietPasst(f.properties, state.gebiet));
      state.base = z < EVENTS_MIN_ZOOM ? state.warnStubs : feats;
    } else if (kind === 'anbau') {
      if (mapReady && map.getSource('anbau')) map.getSource('anbau').setData(p);
    } else if (kind === 'kraftstoff') {
      p = filterStations(p, 'stations');
      state.fuel = { ...p, stats: state.start.kraftstoff?.stats ?? {}, lu: state.start.kraftstoff?.lu ?? null };
    } else {
      const k = KIND_KEY[kind];
      state[FIELD[kind]] = gebietAktiv(state.gebiet) && ['stations', 'stops'].includes(k) ? filterStations(p, k) : p;
    }
  }
  if (z < EVENTS_MIN_ZOOM || !held.has('events')) state.base = state.warnStubs;
  pushDichte();
  onChange();
}

export function pushDichte() {
  if (!mapReady || !state.start || !map.getSource('dichte')) return;
  map.getSource('dichte').setData({ type: 'FeatureCollection', features: dichtePunkte(state.start.cells) });
}

/** Gebiet geändert (Auswahl im Ereignisfilter): neu einsetzen und zeichnen. */
export function gebietGeaendert() {
  applyCells(true);
}

/** Karte verdrahten: nach jeder Bewegung nachladen (entprellt), Klick auf eine Dichte-Zahl zoomt in die Zelle. */
export function wireView() {
  if (!state.zellen) return;
  let t = 0;
  const later = () => { clearTimeout(t); t = setTimeout(() => loadView(), 250); };
  map.on('moveend', later);
  map.on('click', 'dichte-kreis', (e) => {
    const f = e.features?.[0];
    if (!f) return;
    const [w, s, ea, n] = JSON.parse(f.properties.bbox);
    map.fitBounds([[w, s], [ea, n]], { padding: 40, duration: 600, maxZoom: EVENTS_MIN_ZOOM + 1.5 });
  });
  for (const id of ['dichte-kreis']) {
    map.on('mouseenter', id, () => (map.getCanvas().style.cursor = 'pointer'));
    map.on('mouseleave', id, () => (map.getCanvas().style.cursor = ''));
  }
  // Statuszeile auch während des Ladens aktuell halten
  setInterval(setzeStatuszeile, 700);
}
