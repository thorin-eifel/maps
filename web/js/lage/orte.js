import { INFRA_MEDIEVAL, SACRAL_KINDS, infraFeatures } from '../infra.js';
import { getJSON } from '../util.js';
import { MED } from './mittelalter.js';
import { map, mapReady, state } from './zustand.js';

// Bahnhöfe und Haltestellen der Schiene (GTFS Luxemburg und Deutschland, haltestellen.json): kleine Punkte mit Namen ab Zoom 10
export const STOP_STYLE = { light: ['#ffffff', '#1f3a5f', '#1f3a5f', 'rgba(255,255,255,0.95)'], dark: ['#1f3a5f', '#e6eefc', '#e6eefc', 'rgba(16,16,16,0.95)'] };
export function stopFeatures() {
  return { type: 'FeatureCollection', features: (state.stops?.stops ?? []).map((s) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] }, properties: { name: s.name, mode: s.mode } })) };
}
export function paintStops() {
  if (!mapReady || !map.getLayer('stops-dot')) return;
  const [fill, edge, text, halo] = STOP_STYLE[document.documentElement.dataset.ansicht === 'dunkel' ? 'dark' : 'light'];
  map.setPaintProperty('stops-label', 'text-color', text); map.setPaintProperty('stops-label', 'text-halo-color', halo);
}
// Infrastruktur aus OpenStreetMap (Windräder, Ladesäulen, Notfallpunkte). Eine Quelle, eine Zeichen- und eine Namensebene; welche Arten stehen, regelt der Filter.
export let infraKey = '';
export function ensureSakral() {   // Kirchen, Kapellen, Wegkreuze gibt es nur auf der Karte um 1450: Datei erst dann laden
  if (!state.layers.medieval || state.sakral || state.sakralLoading) return;
  state.sakralLoading = true;
  getJSON('data/sakral.json').then((j) => { state.sakral = j; applyInfra(); }).catch(() => {}).finally(() => { state.sakralLoading = false; });
}
export const INFRA_GROUP = { church: 'herChurch', chapel: 'herChapel', cross: 'herCross', shrine: 'herCross', watermill: 'herMill', windmill: 'herMill', ford: 'herFord', border: 'herBorder', gallows: 'herGallows', well: 'herWell', wind: 'wturb', charging: 'charge', aed: 'emerg', fire_station: 'emerg', hospital: 'emerg',
  weir: 'wehr', lock: 'wehr', ferry: 'wehr', bridge: 'bruecke', tunnel: 'bruecke', picnic: 'rast', shelter: 'rast', bathing: 'rast', school: 'civic', townhall: 'civic', cemetery: 'cemetery' };
// Ebene je Art: dichte Arten (Feuerwachen, Brücken, Rastplätze) erst bei größerem Zoom
export const INFRA_LAYERS = [['inf-sym', 9.5], ['inf-fire', 11], ['inf-sac', 11.5], ['inf-wasser', 11], ['inf-brueck', 12.5], ['inf-rast', 12.5], ['inf-civ', 11.5]];
export const INFRA_LAYER_IDS = INFRA_LAYERS.map(([id]) => id);
export const INFRA_LAYER_OF = { fire_station: 'inf-fire', church: 'inf-sac', chapel: 'inf-sac', cross: 'inf-sac', shrine: 'inf-sac', watermill: 'inf-sac', windmill: 'inf-sac', ford: 'inf-sac', border: 'inf-sac', gallows: 'inf-sac', well: 'inf-sac', weir: 'inf-wasser', lock: 'inf-wasser', ferry: 'inf-wasser',
  bridge: 'inf-brueck', tunnel: 'inf-brueck', picnic: 'inf-rast', shelter: 'inf-rast', bathing: 'inf-rast', school: 'inf-civ', townhall: 'inf-civ', cemetery: 'inf-civ' };
export function infraFeaturesOn() {
  const med = !!state.layers.medieval;
  const group = (k) => (med && (k === 'ferry' || k === 'bridge') ? 'herFord' : INFRA_GROUP[k]);      // um 1450: Fähren und alte Brücken gehören zum Erbe, nicht zu Wehr/Brücke
  return Object.keys(INFRA_GROUP).filter((k) => state.layers[group(k)] && (med ? INFRA_MEDIEVAL.has(k) : !SACRAL_KINDS.includes(k)));
}
export function applyInfra() {
  if (!mapReady || !state.infra) return;
  ensureSakral();
  const sak = state.layers.medieval && state.sakral;
  const items = sak ? [...state.infra.items, ...state.sakral.items] : state.infra.items;
  const key = `${state.infra.fetched_at}|${sak ? state.sakral.fetched_at : '-'}`;
  const src = map.getSource('infra');
  if (src) { if (key !== infraKey) src.setData(infraFeatures(items)); }
  else {
    map.addSource('infra', { type: 'geojson', data: infraFeatures(items) });
    // Feuerwachen sind zahlreich (fast jedes Dorf): eigene Ebene erst ab Zoom 11, der Rest ab 9,5
    for (const [id, minzoom] of INFRA_LAYERS) {
      map.addLayer({ id, type: 'symbol', source: 'infra', minzoom,
        layout: { 'icon-image': ['concat', 'inf-', ['get', 'kind']], 'icon-size': ['interpolate', ['linear'], ['zoom'], 9.5, 0.5, 14, 0.8], 'icon-allow-overlap': false, 'icon-padding': 2,
          'symbol-sort-key': ['match', ['get', 'kind'], 'hospital', 0, 'fire_station', 1, 'wind', 2, 'aed', 3, 4],
          'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 11, 'text-offset': [0, 1.2], 'text-anchor': 'top', 'text-max-width': 9, 'text-optional': true },
        paint: { 'text-color': '#1c1c1c', 'text-halo-color': '#fff', 'text-halo-width': 1.8, 'text-opacity': ['step', ['zoom'], 0, 12, 1] } }, 'radius-fill');
    }
  }
  infraKey = key;
  applyInfraVisibility();
}
// Wander- und Radrouten (überregional, OpenStreetMap): Linien mit hellem Saum, Name entlang der Linie; auf der Karte um 1450 ausgeblendet
export const ROUTE_COLOR = { hike: '#c2410c', bike: '#6d28d9' };
export function routeFeatures() {
  return { type: 'FeatureCollection', features: (state.routen?.items ?? []).map((r) => ({ type: 'Feature', geometry: { type: 'MultiLineString', coordinates: r.lines },
    properties: { kind: r.kind, name: r.name, ref: r.ref || '', network: r.network || '', label: r.ref && !r.name.includes(r.ref) ? `${r.name} (${r.ref})` : r.name } })) };
}
export function applyRoutes() {
  if (!mapReady || !state.routen) return;
  const src = map.getSource('routen');
  if (src) src.setData(routeFeatures());
  else {
    map.addSource('routen', { type: 'geojson', data: routeFeatures() });
    const lineLayout = { 'line-cap': 'round', 'line-join': 'round' };
    for (const k of ['hike', 'bike']) {
      const f = ['==', ['get', 'kind'], k], w = ['interpolate', ['linear'], ['zoom'], 8, 1.4, 14, 3];
      map.addLayer({ id: `routes-${k}-casing`, type: 'line', source: 'routen', filter: f, layout: lineLayout, paint: { 'line-color': '#ffffff', 'line-opacity': 0.85, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 3.4, 14, 5] } }, 'radius-fill');
      map.addLayer({ id: `routes-${k}`, type: 'line', source: 'routen', filter: f, layout: lineLayout,
        paint: { 'line-color': ROUTE_COLOR[k], 'line-width': w, ...(k === 'hike' ? { 'line-dasharray': [2, 1.2] } : {}) } }, 'radius-fill');
    }
    map.addLayer({ id: 'routes-hit', type: 'line', source: 'routen', layout: lineLayout, paint: { 'line-color': '#000000', 'line-opacity': 0.01, 'line-width': 14 } }, 'radius-fill');
    map.addLayer({ id: 'routes-label', type: 'symbol', source: 'routen', minzoom: 11,
      layout: { 'symbol-placement': 'line', 'symbol-spacing': 420, 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 11, 'text-max-angle': 35, 'text-padding': 6 },
      paint: { 'text-color': ['match', ['get', 'kind'], 'hike', '#9a3412', '#4c1d95'], 'text-halo-color': '#fff', 'text-halo-width': 1.8 } }, 'radius-fill');
  }
  applyRoutesVisibility();
}
export function applyRoutesVisibility() {
  if (!mapReady || !map.getLayer('routes-hit')) return;
  const med = !!state.layers.medieval, kinds = ['hike', 'bike'].filter((k) => state.layers[k] && !med);
  for (const k of ['hike', 'bike']) for (const id of [`routes-${k}-casing`, `routes-${k}`]) map.setLayoutProperty(id, 'visibility', kinds.includes(k) ? 'visible' : 'none');
  const f = ['in', ['get', 'kind'], ['literal', kinds]];
  for (const id of ['routes-hit', 'routes-label']) { map.setLayoutProperty(id, 'visibility', kinds.length ? 'visible' : 'none'); map.setFilter(id, f); }
}
export function applyInfraVisibility() {
  if (!mapReady || !map.getLayer('inf-sym')) return;
  const med = !!state.layers.medieval, kinds = infraFeaturesOn();
  const sets = Object.fromEntries(INFRA_LAYER_IDS.map((id) => [id, kinds.filter((k) => (INFRA_LAYER_OF[k] ?? 'inf-sym') === id)]));
  for (const [id, ks] of Object.entries(sets)) {
    map.setLayoutProperty(id, 'visibility', ks.length ? 'visible' : 'none');
    const kindIn = ['in', ['get', 'kind'], ['literal', ks]];
    map.setFilter(id, med && id === 'inf-brueck' ? ['all', kindIn, ['==', ['get', 'old'], 1]] : kindIn);      // um 1450 nur alte Brücken
    map.setLayoutProperty(id, 'icon-image', ['concat', med ? 'med-inf-' : 'inf-', ['get', 'kind']]);
    map.setLayoutProperty(id, 'text-field', ['get', med ? 'labelMed' : 'label']);
    map.setLayoutProperty(id, 'text-font', [med ? 'Grenze Gotisch Regular' : 'Noto Sans Regular']);
    map.setLayoutProperty(id, 'text-size', med ? 13 : 11);
    map.setPaintProperty(id, 'text-color', med ? MED.ink : '#1c1c1c');
    map.setPaintProperty(id, 'text-halo-color', med ? MED.halo : '#fff');
  }
}

export function applyStops() {
  if (!mapReady || !state.stops) return;
  const src = map.getSource('stops');
  if (src) src.setData(stopFeatures());
  else {
    map.addSource('stops', { type: 'geojson', data: stopFeatures() });
    map.addLayer({ id: 'stops-dot', type: 'symbol', source: 'stops', minzoom: 9,
      layout: { 'icon-image': 'stop-bahn', 'icon-size': ['interpolate', ['linear'], ['zoom'], 9, 0.6, 14, 0.85], 'icon-allow-overlap': false, 'icon-padding': 4 } }, 'radius-fill');
    map.addLayer({ id: 'stops-label', type: 'symbol', source: 'stops', minzoom: 11,
      layout: { 'text-field': ['get', 'name'], 'text-font': ['Noto Sans Regular'], 'text-size': 11, 'text-offset': [0, 1.1], 'text-anchor': 'top', 'text-max-width': 9 },
      paint: { 'text-color': '#1f3a5f', 'text-halo-color': '#fff', 'text-halo-width': 1.8 } }, 'radius-fill');
  }
  paintStops();
  applyStopsVisibility();
}
export function applyStopsVisibility() {
  if (!mapReady) return;
  for (const id of ['stops-dot', 'stops-label']) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', state.layers.stops ? 'visible' : 'none');
}
