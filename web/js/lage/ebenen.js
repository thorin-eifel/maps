import { decor } from '../medieval.js';
import { enableSound } from '../ping-sound.js';
import { setReliefVisible } from '../relief.js';
import { $, initTheme, tickAges } from '../util.js';
import { applyBaseToggles, applyLegend, applyLight, recolor } from './basiskarte.js';
import { pushAir, refreshAir } from './flugverkehr.js';
import { refresh, render } from './laden.js';
import { windrose } from './mittelalter.js';
import { applyNatureVisibility } from './natur.js';
import { applyInfra, applyInfraVisibility, applyRoutesVisibility, applyStopsVisibility } from './orte.js';
import { applyBlitzVisibility, applyFlow, applyLegends, applyRadarVisibility, applyWind } from './wetterkarte.js';
import { AIR_POLL_MS, GROUPS, map, mapReady, reliefOk, state } from './zustand.js';

export function applyLayerFilters() {
  if (!mapReady) return;
  const types = Object.entries(GROUPS).filter(([g]) => state.layers[g]).flatMap(([, t]) => t);
  const typeFilter = ['in', ['get', 'type'], ['literal', types]];
  const isPoint = ['==', ['geometry-type'], 'Point'];
  const isLine = ['any', ['==', ['geometry-type'], 'LineString'], ['==', ['geometry-type'], 'MultiLineString']];
  const isArea = ['any', ['==', ['geometry-type'], 'Polygon'], ['==', ['geometry-type'], 'MultiPolygon']];
  const works = ['any', ['==', ['get', 'source_id'], 'lbm_baustellen'], ['==', ['get', 'icon'], 'baustelle']], notWorks = ['!', works];
  const base = {
    'ev-fill': isArea, 'ev-outline': isArea, 'ev-line': isLine, 'ev-line-halo': isLine, 'ev-point': isPoint,
    'ev-sym-pt': ['all', isPoint, notWorks], 'ev-sym-ln': ['all', isLine, notWorks],
    'ev-sym-pt-w': ['all', isPoint, works], 'ev-sym-ln-w': ['all', isLine, works], 'ev-dot-w': ['all', isPoint, works],
  };
  for (const [id, f] of Object.entries(base)) map.setFilter(id, ['all', f, typeFilter]);
  const on = (v) => (v ? 'visible' : 'none');
  map.setLayoutProperty('st-sym', 'visibility', on(state.layers.gew && state.iconsOk));
  map.setLayoutProperty('st-circle', 'visibility', on(state.layers.gew && !state.iconsOk));
  map.setLayoutProperty('air-dim', 'visibility', on(state.layers.air));
  map.setLayoutProperty('air-sym', 'visibility', on(state.layers.air && state.iconsOk));
  map.setLayoutProperty('air-circle', 'visibility', on(state.layers.air && !state.iconsOk));
  const envKinds = [state.layers.airq && 'air', state.layers.rad && 'radiation', state.layers.wxst && 'weather'].filter(Boolean);
  const envOn = envKinds.length > 0;
  const envKind = ['in', ['get', 'kind'], ['literal', envKinds]];
  for (const id of ['env-sym', 'env-circle']) map.setFilter(id, envKind);
  map.setLayoutProperty('wxst-label', 'visibility', on(state.layers.wxst && state.iconsOk));
  map.setLayoutProperty('env-sym', 'visibility', on(envOn && state.iconsOk));
  map.setLayoutProperty('env-circle', 'visibility', on(envOn && !state.iconsOk));
  map.setLayoutProperty('tank-sym', 'visibility', on(state.layers.tank && state.iconsOk));
  map.setLayoutProperty('tank-label', 'visibility', on(state.layers.tank && state.iconsOk));
  applyInfraVisibility();
  applyRoutesVisibility();
  map.setLayoutProperty('tank-circle', 'visibility', on(state.layers.tank && !state.iconsOk));
  applyBaseToggles();
  applyFlow();
  applyRadarVisibility();
  applyWind();
  applyBlitzVisibility();
  applyStopsVisibility();
  applyNatureVisibility();
  if (reliefOk) { setReliefVisible(map, state.layers.relief); applyLight(); applyLegend(); }
}

export function wire() {
  initTheme($('#theme'));
  document.addEventListener('ansicht', () => setTimeout(recolor, 0));
  for (const r of document.querySelectorAll('input[name="within"]')) r.addEventListener('change', () => { state.within = r.value; render(); });
  $('#pingsound')?.addEventListener('change', (e) => { // Nutzerklick: erst jetzt darf der Browser Ton erzeugen
    if (!enableSound(e.target.checked)) e.target.checked = false;
  });
  let medApplied = false, autoHeritage = false;
  const setLayer = (name, on) => { const cb = document.querySelector(`input[data-layer="${name}"]`); if (cb) cb.checked = on; state.layers[name] = on; };
  const syncMedieval = () => {
    if (state.layers.medieval === medApplied) return;
    medApplied = state.layers.medieval;
    // Burgen, Ruinen, Klöster und historische Gebäude gehören zur Karte: beim Einschalten mit einblenden, beim Ausschalten wieder zurück
    const HER = ['herCastle', 'herArch', 'herMonastery', 'herBuilding', 'herChurch', 'herChapel', 'herCross', 'herMill', 'herFord', 'herBorder', 'herGallows', 'herWell'];
    if (medApplied && !HER.some((n) => state.layers[n])) { for (const n of HER) setLayer(n, true); autoHeritage = true; }
    else if (!medApplied && autoHeritage) { for (const n of HER) setLayer(n, false); autoHeritage = false; }
    if (!medApplied) autoHeritage = false;
    windrose(medApplied); decor(medApplied); applyLegends();
    applyLayerFilters(); syncGroups(); recolor(); applyInfra();
  };
  const syncGroups = () => { // Themenschalter: an, wenn alle Ebenen des Themas an sind; „gemischt“, wenn nur einige
    for (const g of document.querySelectorAll('.layer-group')) {
      const t = g.querySelector('.group-toggle'), all = [...g.querySelectorAll('input[data-layer]')];
      const n = all.filter((c) => c.checked).length;
      t.checked = n === all.length; t.indeterminate = n > 0 && n < all.length;
    }
  };
  for (const cb of document.querySelectorAll('input[data-layer]')) cb.addEventListener('change', () => {
    state.layers[cb.dataset.layer] = cb.checked; applyLayerFilters(); render(); syncGroups(); syncMedieval();
    if (cb.dataset.layer === 'licht') applyLight();
    if (cb.dataset.layer === 'air' && cb.checked) refreshAir();
  });
  for (const t of document.querySelectorAll('.group-toggle')) t.addEventListener('change', () => {
    const boxes = [...t.closest('.layer-group').querySelectorAll('input[data-layer]')];
    for (const cb of boxes) { cb.checked = t.checked; state.layers[cb.dataset.layer] = t.checked; }
    applyLayerFilters(); render(); syncGroups(); syncMedieval();
    if (boxes.some((cb) => cb.dataset.layer === 'licht')) applyLight();
    if (t.checked && boxes.some((cb) => cb.dataset.layer === 'air')) refreshAir();
  });
  syncGroups();
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  for (const t of tabs) t.addEventListener('click', () => {
    for (const o of tabs) { o.setAttribute('aria-selected', String(o === t)); $(`#${o.getAttribute('aria-controls')}`).hidden = o !== t; }
  });
  setInterval(tickAges, 30000);
  setInterval(refresh, 60000); // Dateien alle 60 s neu holen (kein Server-Push auf statischem Webspace)
  setInterval(refreshAir, AIR_POLL_MS); // Flüge: kleine Datei alle 15 s, nur bei eingeschalteter Ebene und sichtbarem Tab
  setInterval(() => { if (!document.hidden && state.layers.air) pushAir(); }, 1000); // weiterrücken und Stand-Anzeige
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshAir(); });
}
