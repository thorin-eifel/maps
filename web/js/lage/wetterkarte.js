import { TEMP_COLOURS, TEMP_MIN, TEMP_STEP } from '../icons.js';
import { updateLegend } from '../legend.js';
import { fillLegend as fillMedLegend } from '../medieval.js';
import { $, fmtTime } from '../util.js';
import { baseAnchor } from './geometrie.js';
import { COMPASS, windroseUpdate } from './mittelalter.js';
import { RADAR_OPACITY, basemapOk, flow, map, mapReady, ripples, state, wind, windLow } from './zustand.js';

// Radar: ein Bild vom eigenen Server (radar.png), vom Collector aus dem DWD-WMS geholt; hier wird nur angezeigt
export function applyRadar() {
  const r = state.radar;
  if (!mapReady || !r?.corners || !r.time) return;
  const url = new URL(`data/radar.png?v=${encodeURIComponent(r.time)}`, location.href).href;
  const src = map.getSource('radar');
  if (src) { if (src.url !== url) src.updateImage({ url, coordinates: r.corners }); src.url = url; }
  else {
    map.addSource('radar', { type: 'image', url, coordinates: r.corners });
    map.getSource('radar').url = url;
    map.addLayer({ id: 'radar', type: 'raster', source: 'radar', paint: { 'raster-opacity': RADAR_OPACITY, 'raster-fade-duration': 0, 'raster-resampling': 'linear' } }, baseAnchor());
  }
  ripples?.setRadar(url, r.corners);
  applyRadarVisibility();
  const note = $('#radarnote');
  if (note) note.textContent = state.layers.radar ? `Stand ${fmtTime(r.time)}` : '';
}
export function applyRadarVisibility() {
  applyLegends();
  ripples?.setEnabled(state.layers.radar && state.layers.drops);
  if (mapReady && map.getLayer('radar')) map.setLayoutProperty('radar', 'visibility', state.layers.radar ? 'visible' : 'none');
  const note = $('#radarnote');
  if (note && state.radar?.time) note.textContent = state.layers.radar ? `Stand ${fmtTime(state.radar.time)}` : '';
}
// Zeichenerklärung: je aktiver Ebene ein Abschnitt (Regenradar, Wind, Blitze, Verkehr, Luftverkehr)
// Legendenleiste der Wetterstationen: dieselben Farbfelder wie die Symbole, ausgeschnitten auf -20 bis 40 °C
// Legende neben den Details: gleiche Unterkante wie die Detailkarte. Die Karte ist oben verankert und so hoch wie ihr Inhalt, ihre Unterkante
// lässt sich nur messen. Gesetzt wird --legend-bottom (Abstand zur Unterkante der Karte); ohne Messwert gilt der Standard im CSS.
export function trackLegendBottom() {
  const side = $('#side'), legend = $('#map-legend'), wrap = document.querySelector('.map-wrap');
  if (!side || !legend || !wrap || !window.ResizeObserver) return;
  const set = () => {
    const wide = window.matchMedia('(min-width: 1001px)').matches, min = side.dataset.min === 'true';
    if (!wide || min) { wrap.style.removeProperty('--legend-bottom'); return; }
    const w = wrap.getBoundingClientRect(), r = side.getBoundingClientRect();
    const gap = Math.max(0, Math.round(w.bottom - r.bottom));
    wrap.style.setProperty('--legend-bottom', `${gap}px`);
  };
  const ro = new ResizeObserver(set);
  ro.observe(side); ro.observe(wrap);
  new MutationObserver(set).observe(side, { attributes: true, attributeFilter: ['data-min'] });
  window.addEventListener('resize', set);
  set();
}
export function fillTempLegend() {
  const bar = $('#temp-bar'); if (!bar) return;
  const stops = TEMP_COLOURS.map((c, k) => [TEMP_MIN + TEMP_STEP * k, c]).filter(([t]) => t >= -23 && t <= 43);
  bar.style.background = `linear-gradient(to right, ${stops.map(([t, c]) => `${c} ${(((t + 20) / 60) * 100).toFixed(1)}%`).join(', ')})`;
}
export function applyLegends() {
  updateLegend($('#map-legend'), {
    radar: state.layers.radar && !!state.radar?.time, wind: (state.layers.wind || state.layers.windlow) && !!state.wind?.grid, windlow: state.layers.windlow && !!state.terrain,
    flow: state.layers.flow && basemapOk, blitz: state.layers.blitz && !!state.blitz?.time, wxst: state.layers.wxst && !!state.env?.stations?.some((x) => x.kind === 'weather'), tank: state.layers.tank && !!state.fuel?.stations?.length, traffic: state.layers.traffic || state.layers.transit, air: state.layers.air, medieval: state.layers.medieval,
  });
  if (state.layers.medieval) fillMedLegend(document.querySelector('#map-legend [data-legend="medieval"]'));
}
// Wind: Gitter (wind.json) vom eigenen Server, die Partikel rechnet wind.js im Browser; Quelle und Stand stehen im Ebenenmenü
// Wasserbewegung: Schalter, Legende, Windzeile (Wind der Kartenmitte aus dem Modell)
export function applyFlow() { flow?.setEnabled(state.layers.flow && basemapOk); applyLegends(); }
export function showFlowWind(w) {
  const el = $('#flow-wind'); if (!el) return;
  const txt = { calm: 'Flaute, die Seen liegen glatt', light: 'schwacher Wind, feine Wellen', moderate: 'mäßiger Wind, deutliche Wellen', strong: 'kräftiger Wind, dichte Wellen' };
  el.textContent = w ? `Wind jetzt (Modell, Kartenmitte): aus ${COMPASS[Math.round(w.from / 22.5) % 16]}, ${Math.round(w.speed * 3.6)} km/h, ${txt[w.cls]}.` : state.layers.flow ? 'Kein Windmodell geladen: Stillgewässer bleiben glatt.' : '';
}
export function applyWind() {
  const g = state.wind?.grid;
  if (g) { wind?.setGrid(g); windLow?.setGrid(g); }
  wind?.setEnabled(state.layers.wind && !!g);
  windroseUpdate();
  windLow?.setEnabled(state.layers.windlow && !!g && !!state.terrain);
  flow?.update();
  applyLegends();
  const note = $('#windnote');
  if (note) note.textContent = !state.layers.wind ? '' : g ? `Modell für ${fmtTime(g.time)}` : 'keine Daten';
  const lnote = $('#windlownote');
  if (lnote) lnote.textContent = !state.layers.windlow ? '' : !g ? 'keine Daten' : state.terrain ? 'Schätzung' : 'Geländedaten fehlen';
}
export function placeRadar() {
  if (mapReady && map.getLayer('radar')) map.moveLayer('radar', baseAnchor());
  if (mapReady && map.getLayer('blitz')) map.moveLayer('blitz', baseAnchor()); // Blitze über dem Regenradar
}

// Blitze (EUMETSAT MTG-LI): fertig eingefärbtes Bild vom eigenen Server (blitz.png), Alter steckt in der Farbe; leerer Himmel wird gesagt
export function applyBlitz() {
  const b = state.blitz;
  if (!mapReady || !b?.corners || !b.time) return;
  const url = new URL(`data/blitz.png?v=${encodeURIComponent(b.time)}`, location.href).href;
  const src = map.getSource('blitz');
  if (src) src.updateImage({ url, coordinates: b.corners });
  else {
    map.addSource('blitz', { type: 'image', url, coordinates: b.corners });
    map.addLayer({ id: 'blitz', type: 'raster', source: 'blitz', paint: { 'raster-opacity': 0.95, 'raster-fade-duration': 0, 'raster-resampling': 'linear' } }, baseAnchor());
  }
  applyBlitzVisibility();
}
export function applyBlitzVisibility() {
  applyLegends();
  if (mapReady && map.getLayer('blitz')) map.setLayoutProperty('blitz', 'visibility', state.layers.blitz ? 'visible' : 'none');
  const note = $('#blitznote'), b = state.blitz;
  if (!note) return;
  if (!state.layers.blitz || !b?.time) { note.textContent = ''; return; }
  const n = Object.values(b.counts ?? {}).reduce((a, c) => a + c, 0);
  note.textContent = `Stand ${fmtTime(b.time)} · ${n ? `${n} Zellen in ${b.window_min} min` : `keine Blitze in ${b.window_min} min`}`;
}
