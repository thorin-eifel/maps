import { renderFuel } from '../indizes.js';
import { deriveStatus, windowFilter } from '../rules.js';
import { $, ageEl, getJSON, h } from '../util.js';
import { renderEvents } from './ereignisliste.js';
import { pushAir } from './flugverkehr.js';
import { pushMapData } from './messnetz.js';
import { applyNature } from './natur.js';
import { applyInfra, applyRoutes, applyStops } from './orte.js';
import { renderGewaesser, renderUmwelt, renderWarnband, renderWetter, renderWxBand } from './panels.js';
import { sourceLine } from './popup.js';
import { applyBlitz, applyRadar, applyWind } from './wetterkarte.js';
import { state } from './zustand.js';
import { ladeIndex, loadView, setzeAenderungsfunktion } from './zellenlauf.js';

// ------------------------------------------------------------------ Laden
export const WARN_TYPES = ['warning', 'weather', 'flood', 'radiation', 'air', 'earthquake', 'fire'];

// Flachdateien, die es immer gibt (landesweit oder klein); die Raumdaten kommen im Zellenbetrieb aus den Zellen (zellenlauf.js)
const GLOBAL = ['meta', 'wetter', 'status', 'radar', 'wind', 'blitz', 'indizes'];
const FLAT_SPATIAL = ['events', 'gewaesser', 'umwelt', 'haltestellen', 'landmarks', 'kraftstoff', 'infrastruktur', 'routen'];

export async function refresh() {
  const cellMode = await ladeIndex();
  const names = cellMode ? GLOBAL : [...GLOBAL, ...FLAT_SPATIAL];
  const settled = await Promise.allSettled(names.map((n) => getJSON(`data/${n}.json`)));
  const got = Object.fromEntries(names.map((n, i) => [n, settled[i].status === 'fulfilled' ? settled[i].value : null]));
  const allFailed = settled.every((r) => r.status === 'rejected') && !cellMode;
  $('#apidown').hidden = !allFailed;
  if (allFailed) return; // letzte bekannte Anzeige bleibt stehen
  // Ein Teilausfall (z. B. Datei mitten im Upload) lässt den letzten guten Stand dieser Kachel stehen
  state.meta = got.meta ?? state.meta;
  if (!cellMode) {
    state.base = got.events?.features ?? state.base;
    state.gew = got.gewaesser ?? state.gew;
    state.env = got.umwelt ?? state.env;
    state.stops = got.haltestellen ?? state.stops;
    state.landmarks = got.landmarks ?? state.landmarks;
    state.fuel = got.kraftstoff ?? state.fuel;
    state.infra = got.infrastruktur ?? state.infra;
    state.routen = got.routen ?? state.routen;
  }
  if (!state.net) state.net = await getJSON('data/gewaessernetz.json').catch(() => null);   // statisch, einmal laden; fehlt sie, bleibt die flache Liste
  state.wx = got.wetter ?? state.wx;
  state.radar = got.radar ?? state.radar;
  state.wind = got.wind ?? state.wind;
  state.blitz = got.blitz ?? state.blitz;
  state.idx = got.indizes ?? state.idx;
  // Im Zellenbetrieb stammt der Quellenzustand aus dem Startpaket (gleiche Zeitbasis wie die Zellen), sonst aus status.json
  const st = cellMode ? { sources: state.start.sources } : got.status;
  state.statuses = (st?.sources ?? state.statuses).map((s) => deriveStatus(s, Date.now()));
  if (cellMode) await loadView(true);
  else render();
}

// Nur, was sich bei einem Flug-Abruf ändert (nicht Warnband, Pegel, Wetter neu bauen)
export function renderAir() {
  state.all = state.layers.air ? [...state.base, ...state.airRaw] : state.base;
  state.events = windowFilter(state.all, state.within, Date.now());
  renderEvents(state.statuses);
  $('#count').textContent = `${state.events.length} Ereignisse`;
  pushAir();
}

export function render() {
  const now = Date.now();
  state.all = state.layers.air ? [...state.base, ...state.airRaw] : state.base;
  state.events = windowFilter(state.all, state.within, now);
  const warn = windowFilter(state.zellen ? state.warnStubs : state.all, 'now', now)
    .filter((f) => WARN_TYPES.includes(f.properties.type) && f.properties.severity_rank >= 1)
    .sort((a, b) => b.properties.severity_rank - a.properties.severity_rank || a.properties.distance_km - b.properties.distance_km);
  renderWarnband(warn, state.statuses);
  renderEvents(state.statuses);
  renderGewaesser();
  renderUmwelt();
  renderFuel($('#panel-fuel'), state.fuel, { h, sourceLine, ageEl });
  renderWetter();
  renderWxBand();
  pushMapData();
  applyRadar();
  applyWind();
  applyBlitz();
  applyStops();
  applyNature();
  applyInfra();
  applyRoutes();
  $('#count').textContent = `${state.events.length} Ereignisse`;
}

setzeAenderungsfunktion(render);

export let timer;
export const debounced = () => { clearTimeout(timer); timer = setTimeout(refresh, 800); };
