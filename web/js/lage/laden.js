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

// ------------------------------------------------------------------ Laden
export const WARN_TYPES = ['warning', 'weather', 'flood', 'radiation', 'air', 'earthquake', 'fire'];

export async function refresh() {
  const settled = await Promise.allSettled(
    ['meta', 'events', 'gewaesser', 'wetter', 'status', 'umwelt', 'radar', 'wind', 'blitz', 'haltestellen', 'landmarks', 'indizes', 'kraftstoff', 'infrastruktur', 'routen'].map((n) => getJSON(`data/${n}.json`)));
  const [meta, ev, gew, wx, st, env, radar, windJson, blitz, stops, landmarks, idx, fuel, infra, routen] = settled.map((r) => (r.status === 'fulfilled' ? r.value : null));
  const allFailed = settled.every((r) => r.status === 'rejected');
  $('#apidown').hidden = !allFailed;
  if (allFailed) return; // letzte bekannte Anzeige bleibt stehen
  // Ein Teilausfall (z. B. Datei mitten im Upload) lässt den letzten guten Stand dieser Kachel stehen
  state.meta = meta ?? state.meta;
  state.base = ev?.features ?? state.base;
  state.gew = gew ?? state.gew;
  if (!state.net) state.net = await getJSON('data/gewaessernetz.json').catch(() => null);   // statisch, einmal laden; fehlt sie, bleibt die flache Liste
  state.wx = wx ?? state.wx;
  state.env = env ?? state.env;
  state.radar = radar ?? state.radar;
  state.wind = windJson ?? state.wind;
  state.blitz = blitz ?? state.blitz;
  state.stops = stops ?? state.stops;
  state.landmarks = landmarks ?? state.landmarks;
  state.idx = idx ?? state.idx;
  state.fuel = fuel ?? state.fuel;
  state.infra = infra ?? state.infra;
  state.routen = routen ?? state.routen;
  state.statuses = (st?.sources ?? state.statuses).map((s) => deriveStatus(s, Date.now()));
  render();
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
  const warn = windowFilter(state.all, 'now', now)
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

export let timer;
export const debounced = () => { clearTimeout(timer); timer = setTimeout(refresh, 800); };
