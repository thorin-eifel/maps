// Lagekarte: Karte, Warnband, Ereignistabelle, Gewässer, Wetter.
import { Map as MlMap, Marker, Popup, NavigationControl, FullscreenControl, ScaleControl, addProtocol } from '../vendor/maplibre-gl/maplibre-gl.js';
import { PMTiles, Protocol } from '../vendor/pmtiles/pmtiles.js';
import { layers as basemapLayers, namedFlavor } from '../vendor/protomaps-basemaps/basemaps.js';
import {
  $, h, getJSON, fmtDateTime, fmtTime, fmtHour, ageEl, tickAges, SEV, TYPE_LABEL, sevBadge, statusBadge,
  link, initTheme, cssColor, sparkline,
} from './util.js';
import { mountSearch, zoomFor } from './suche.js';
import { createSweep, SWEEP_GREEN } from './sweep.js';
import { enableSound, ping as pingSound, zap as zapSound, sizzle as sizzleSound, silence as silenceSound } from './ping-sound.js';
import { MIL_COLOUR } from './icons.js';
import { registerMedievalPatterns, extraLayers, patternLayer, waterPatternLayer, decor, fillLegend as fillMedLegend, registerFauna, faunaPoints, faunaLayers, FAUNA_SOURCE } from './medieval.js';
import { renderIndizes, renderFuel } from './indizes.js';
import { SORTS, sortEvents, filterEvents } from './eventlist.js';
import { sortStations, buildTree, stationRank } from './pegel.js';
import { windowFilter, deriveStatus, overall, exportStale, exportAgeMin, iconFor, trafficLevel, advance } from './rules.js';
import { registerIcons, registerSigns, registerMedieval, setIconStyle, iconStatus, tempClass, TEMP_COLOURS, TEMP_MIN, TEMP_STEP } from './icons.js';
import { setupRelief, buildRelief, setReliefVisible, elevationAt, demTile, fillLegend, glyphsUrl, RELIEF_ATTRIBUTION } from './relief.js';
import { createLight } from './licht.js';
import { createRipples } from './ripples.js';
import { createWind, fillWindLegend } from './wind.js';
import { loadTerrain } from './terrain.js';
import { createFlow, registerArrow } from './fluss.js';
import { buildRainLegend, updateLegend } from './legend.js';
import { INFRA_MEDIEVAL, SACRAL_KINDS, registerInfra, infraFeatures, infraText } from './infra.js';

// Startansicht und Bezugspunkt für Entfernungen: Irrel (Ortsmitte, Koordinate vom Betreiber angegeben).
const START_VIEW = { lat: 49.84615562322509, lon: 6.456057281843173 };
const TOWNS = [
  ['Irrel', 49.850, 6.450, true], ['Bitburg', 49.975, 6.526], ['Trier', 49.750, 6.637], ['Echternach', 49.812, 6.418],
  ['Wasserbillig', 49.714, 6.503], ['Luxemburg', 49.611, 6.130], ['Prüm', 50.208, 6.423], ['Wittlich', 49.985, 6.894],
  ['Saarburg', 49.607, 6.547], ['Daun', 50.199, 6.830], ['Merzig', 49.444, 6.639],
  // weitere Orte der Region (Radius 120 km): Luxemburg, Ostbelgien, Lothringen, Saarland, Mosel, Hunsrück
  ['Diekirch', 49.868, 6.157], ['Wiltz', 49.966, 5.932], ['Esch-sur-Alzette', 49.495, 5.981], ['Arlon', 49.683, 5.816], ['Bastogne', 50.000, 5.717],
  ['St. Vith', 50.281, 6.128], ['Gerolstein', 50.224, 6.657], ['Bernkastel-Kues', 49.916, 7.070], ['Cochem', 50.146, 7.166], ['Idar-Oberstein', 49.708, 7.310],
  ['Saarlouis', 49.314, 6.751], ['Saarbrücken', 49.234, 6.996], ['Thionville', 49.358, 6.168], ['Metz', 49.119, 6.176], ['Koblenz', 50.357, 7.589],
];
// Radarbild blendet beim Hineinzoomen aus (Zoom 11 bis 13); die Regentropfen-Animation bleibt und läuft aus denselben Radardaten weiter
const RADAR_OPACITY = ['interpolate', ['linear'], ['zoom'], 11, 0.6, 13, 0];
const RING_URL = 'tiles/ring.pmtiles'; // Zoom 14 rund um den Kern bis zum 120-km-Rand: nur dafür da, dass Häuserumrisse im ganzen Gebiet stehen
const CORE_URL = 'tiles/core.pmtiles'; // Kern um Irrel mit Zoom 15: Gebäude und Hausnummern (die große Datei reicht nur bis Zoom 13)
const TILES_URL = 'tiles/region.pmtiles'; // OSM-Ausschnitt (Protomaps-Build), liegt auf demselben Server
if (location.hash === '#debug') {   // Prüfhilfe: Fehler der Seite in ein Attribut schreiben, weil die Konsole nicht überall lesbar ist
  const note = (m) => { document.documentElement.dataset.debugErr = `${document.documentElement.dataset.debugErr ?? ''}${m}\n`.slice(-1500); };
  window.addEventListener('error', (e) => note(`${e.message} @${e.lineno}`));
  window.addEventListener('unhandledrejection', (e) => note(`rej: ${e.reason?.stack ?? e.reason}`));
}
let basemapOk = false;
let coreOk = false, ringOk = false;
let reliefOk = false;
let light = null;   // Lichtquelle am Zeiger (js/licht.js)
// Schalter im Ebenenmenü → Ereignisarten (Schema: app/models.py EventType). Ebenen ohne Ereignisart (Pegel, Radar, Blitze, Relief, Natur, Basiskarte) stehen nicht hier.
const GROUPS = { traffic: ['traffic', 'congestion'], transit: ['transit'], warning: ['warning', 'weather'], flood: ['flood'], air: ['aircraft'],
  airq: ['air'], rad: ['radiation'], quake: ['earthquake'], fire: ['fire'] };
const state = { gopen: new Map(), net: null, within: 'now', layers: { warning: false, flood: false, fire: false, quake: false, news: false, social: false, traffic: false, transit: false, stops: false, air: false, signs: false,
    radar: true, drops: true, wind: false, windlow: false, blitz: true, wehr: false, bruecke: false, rast: false, civic: false, cemetery: false, hike: false, bike: false, charge: false, wturb: false, emerg: false, gew: true, tank: false, wxst: true, airq: true, rad: true, nature: true, herCastle: false, herArch: false, herMonastery: false, herBuilding: false, herChurch: false, herChapel: false, herCross: false, herMill: false, herFord: false, herBorder: false, herGallows: false, herWell: false, relief: true,
    vegForest: true, vegMeadow: true, vegScrub: true, vegField: true, vegVine: true, vegWet: true, vegRock: true,
    bndCountry: true, bndRegion: true, bndCounty: true, bndLocal: false, protNature: true, protPark: true, protMil: true, flow: false, cliffs: true, buildings: true, licht: false, roadHw: true, roadMain: true, roadMid: true, roadMinor: true, roadPath: true, rail: true, roadNames: true, medieval: false }, meta: null, env: null, radar: null, wind: null, blitz: null, stops: null, landmarks: null, base: [], airRaw: [], airAt: 0, all: [], events: [], gew: null, wx: null, idx: null, fuel: null, infra: null, routen: null, themen: null, statuses: [], iconsOk: false };
const AIR_IMG = { civil: 'plane-', mil: 'mplane-', heli: 'heli-', milheli: 'mheli-' }; // Bildname je Klasse, dazu die Stufe
const AIR_POLL_MS = 15000;  // aircraft.json: so oft schreibt die Live-Schleife
const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
if (reduceMotion) { state.layers.drops = false; const cb = document.querySelector('input[data-layer="drops"]'); if (cb) cb.checked = false; } // Animation nur auf Wunsch
const SYMBOL_LAYERS = ['ev-sym-pt', 'ev-sym-ln', 'ev-sym-pt-w', 'ev-sym-ln-w', 'ev-dot-w'];
let map, popup, sweep, ripples, wind, windLow, flow, mapReady = false;

// ------------------------------------------------------------------ Geometrie
function circle(lat, lon, km, n = 128) {
  const R = 6371.0088, d = km / R, la = (lat * Math.PI) / 180, lo = (lon * Math.PI) / 180, ring = [];
  for (let i = 0; i <= n; i++) {
    const b = (i / n) * 2 * Math.PI;
    const la2 = Math.asin(Math.sin(la) * Math.cos(d) + Math.cos(la) * Math.sin(d) * Math.cos(b));
    const lo2 = lo + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(la), Math.cos(d) - Math.sin(la) * Math.sin(la2));
    ring.push([(lo2 * 180) / Math.PI, (la2 * 180) / Math.PI]);
  }
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } };
}

// Vignette: oberste Kartenebene, Schwarz. Ab dem Radius steigt die Deckkraft stufenlos (Smoothstep) von 0 auf 1, bei Radius + VIG_FADE_KM
// ist nichts mehr zu sehen. Gebaut aus schmalen Ringen (je ~0,15 km) mit eigener Deckkraft, dahinter eine volle schwarze Fläche.
const VIG_FADE_KM = 30, VIG_RINGS = 200, VIG_ID = 'vig';
function vignette(lat, lon, km) {
  const world = [[-179.9, -85], [179.9, -85], [179.9, 85], [-179.9, 85], [-179.9, -85]];
  const ring = (r) => circle(lat, lon, r, 96).geometry.coordinates[0];
  const feats = [];
  let inner = ring(km);
  for (let k = 0; k < VIG_RINGS; k++) {
    const outer = ring(km + ((k + 1) / VIG_RINGS) * VIG_FADE_KM);
    const t = (k + 0.5) / VIG_RINGS;
    feats.push({ type: 'Feature', properties: { a: t * t * (3 - 2 * t) }, geometry: { type: 'Polygon', coordinates: [outer, inner] } });
    inner = outer;
  }
  feats.push({ type: 'Feature', properties: { a: 1 }, geometry: { type: 'Polygon', coordinates: [world, inner] } });
  return { type: 'FeatureCollection', features: feats };
}
// Unsichtbarer Anker: darunter liegen Basiskarte, Relief und Regenradar, darüber die Datenebenen (die Vignette liegt über allem)
const baseAnchor = () => 'radius-fill';

// ------------------------------------------------------------------ Farben
function palette() {
  return {
    bg: cssColor('--surface'), line: cssColor('--border-strong'), fg: cssColor('--fg'), muted: cssColor('--fg-muted'),
    critical: cssColor('--brand-red-600'), warning: 'rgb(230,130,30)', notice: cssColor('--sys-yellow'),
    // Verkehr: feste Signalfarben, unabhängig vom Farbschema
    yellow: '#f5c400', orange: '#f28c1a', red: '#d62828', black: '#111111',
    info: cssColor('--sys-blue'), accent: cssColor('--accent'), white: '#fff', ink: cssColor('--fg'), bg: cssColor('--bg-elevated'),
  };
}
// Verkehrsmeldungen tragen zusätzlich `lvl` (yellow/orange/red/black, siehe trafficLevel), alles andere die Stufe `severity`
const sevColor = (c) => ['match', ['coalesce', ['get', 'lvl'], ['get', 'severity']], 'critical', c.critical, 'warning', c.warning, 'notice', c.notice,
  'yellow', c.yellow, 'orange', c.orange, 'red', c.red, 'black', c.black, c.info];

// ------------------------------------------------------------------ Detailfeld ein-/ausklappen
function setupSideToggle() {
  const btn = $('#side-toggle'), side = $('#side');
  if (!btn || !side) return;
  btn.addEventListener('click', () => {
    const min = btn.getAttribute('aria-expanded') === 'true'; // war offen → jetzt einklappen
    btn.setAttribute('aria-expanded', String(!min));
    side.dataset.min = String(min);
    $('.lage')?.classList.toggle('side-min', min);
    $('.side-label', btn).textContent = min ? 'Details einblenden' : 'Details ausblenden';
  });
}

// Prüfzugang (nur mit #debug in der Adresse): Ereignis 'osint-debug', Auftrag als JSON in <html data-debug-in>: {jump:[lng,lat,zoom], layer:'id'} setzt die Ansicht und
// schreibt Zählwerte der gezeichneten Objekte nach <html data-debug-out>. Kein eval, keine Daten nach außen.
function debugHook(m) {
  document.addEventListener('osint-debug', async (e) => {
    const cmd = JSON.parse(document.documentElement.dataset.debugIn || '{}');
    if (cmd.jump) { m.jumpTo({ center: [cmd.jump[0], cmd.jump[1]], zoom: cmd.jump[2] }); await new Promise((r) => { m.once('idle', r); setTimeout(r, 6000); }); }
    const out = { zoom: m.getZoom() };
    for (const id of cmd.layers ?? []) out[id] = m.getLayer(id) ? m.queryRenderedFeatures({ layers: [id] }).length : 'fehlt';
    for (const im of cmd.images ?? []) out[`img:${im}`] = m.hasImage(im);
    for (const id of cmd.vis ?? []) out[`vis:${id}`] = m.getLayer(id) ? m.getLayoutProperty(id, 'visibility') : 'fehlt';
    if (cmd.order) out.order = m.getStyle().layers.map((l) => l.id).filter((id) => new RegExp(cmd.order).test(id)).join(',');
    if (cmd.paint) out.paint = cmd.paint.map((p) => `${p[0]}.${p[1]}=${JSON.stringify(m.getPaintProperty(p[0], p[1]))}`);
    if (cmd.cliffs) { // Hilfsabfrage: längste Klippenlinien im geladenen Bereich (Anfangspunkt)
      const found = new Map();
      for (const f of m.querySourceFeatures('basemap', { sourceLayer: 'earth', filter: ['==', 'kind', 'cliff'] })) {
        const l = f.geometry.type === 'LineString' ? f.geometry.coordinates : f.geometry.coordinates?.[0];
        if (l?.length) found.set(l[0].map((v) => +v.toFixed(4)).join(','), l.length);
      }
      out.cliffs = [...found.entries()].sort((x, y) => y[1] - x[1]).slice(0, 6);
    }
    if (cmd.perf) { // Messung: Bildintervall (ms) bei Dauer-Neuzeichnen, je Layergruppe ausgeblendet. Auftrag: {groups:{name:'regex'}, frames:90}
      const frames = cmd.perf.frames ?? 90, all = m.getStyle().layers.map((l) => l.id), res = {};
      const run = () => new Promise((resolve) => {
        const dts = []; let last = performance.now(), n = 0;
        const step = (t) => { dts.push(t - last); last = t; m.setBearing((n % 2) * 0.02); if (++n < frames) requestAnimationFrame(step); else { dts.shift(); dts.sort((a, b) => a - b); resolve({ mean: +(dts.reduce((a, b) => a + b, 0) / dts.length).toFixed(1), p95: +dts[Math.floor(dts.length * 0.95)].toFixed(1) }); } };
        requestAnimationFrame(step);
      });
      res.alle = await run();
      for (const [name, rx] of Object.entries(cmd.perf.groups ?? {})) {
        const ids = all.filter((id) => new RegExp(rx).test(id) && m.getLayoutProperty(id, 'visibility') !== 'none');
        for (const id of ids) m.setLayoutProperty(id, 'visibility', 'none');
        res[`ohne ${name} (${ids.length})`] = await run();
        for (const id of ids) m.setLayoutProperty(id, 'visibility', 'visible');
      }
      m.setBearing(0); out.perf = res;
    }
    if (cmd.licht) { // Prüfzugang: Licht setzen und Zustand lesen ({on, lon, lat, hoehe})
      if (cmd.licht.rebuild) light?.rebuildFields();
      if (cmd.licht.on !== undefined) { state.layers.licht = !!cmd.licht.on; const cb = document.querySelector('input[data-layer="licht"]'); if (cb) cb.checked = !!cmd.licht.on; applyLight(); }
      if (cmd.licht.px) { const ll = map.unproject(cmd.licht.px); light?.setLight(ll.lng, ll.lat); }
      if (cmd.licht.lon !== undefined) light?.setLight(cmd.licht.lon, cmd.licht.lat);
      if (cmd.licht.hoehe) light?.setHeight(cmd.licht.hoehe);
      await light?.refresh(); await new Promise((r) => setTimeout(r, 300));
      out.licht = light?.stats();
    }
    if (cmd.probe) { // Hilfsabfrage: Flächenarten unter dem Bildmittelpunkt
      const pt = m.project(m.getCenter()), ids = ['bm-water', 'bm-land-forest'].filter((i) => m.getLayer(i));
      out.probe = m.queryRenderedFeatures([[pt.x - 3, pt.y - 3], [pt.x + 3, pt.y + 3]], { layers: ids }).map((f) => `${f.layer.id}:${f.properties.kind ?? ''}`);
    }
    if (cmd.inscribe) { // Hilfsabfrage: Punkt größten Abstands zum Ufer in der Bildmitte (Gitter 10 px), für Zeichen in Seen
      const cv = m.getCanvas(), w = cv.clientWidth, hgt = cv.clientHeight, st = 10, nx = Math.floor(w / st), ny = Math.floor(hgt / st), cx = w / 2, cy = hgt / 2;
      const water = [];
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) water.push(m.queryRenderedFeatures([i * st + st / 2, j * st + st / 2], { layers: [cmd.inscribe] }).length > 0);
      let best = null;
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
        if (!water[j * nx + i]) continue;
        let dmin = 1e9;
        for (let b = 0; b < ny; b++) for (let a = 0; a < nx; a++) if (!water[b * nx + a]) { const d = (a - i) ** 2 + (b - j) ** 2; if (d < dmin) dmin = d; }
        const far = Math.hypot(i * st + st / 2 - cx, j * st + st / 2 - cy);
        if (far < Math.min(w, hgt) * 0.45 && (!best || dmin > best.d)) best = { d: dmin, i, j };
      }
      if (best) { const ll = m.unproject([best.i * st + st / 2, best.j * st + st / 2]); out.inscribe = { c: [+ll.lng.toFixed(4), +ll.lat.toFixed(4)], r: Math.sqrt(best.d) * st }; }
    }
    if (cmd.scan) { // Hilfsabfrage: größte Flächen einer Quellschicht im Bild (Mitte, Größe der Hülle)
      const seen = new Map();
      for (const f of m.querySourceFeatures('basemap', { sourceLayer: cmd.scan.layer, filter: cmd.scan.filter })) {
        const ring = f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] : f.geometry.coordinates?.[0]?.[0];
        if (!Array.isArray(ring) || !Array.isArray(ring[0])) continue;
        const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
        const w = Math.max(...xs) - Math.min(...xs), hh = Math.max(...ys) - Math.min(...ys);
        const key = `${(xs[0]).toFixed(4)},${(ys[0]).toFixed(4)}`;
        seen.set(key, { n: f.properties.name ?? '', k: f.properties.kind ?? '', c: [+((Math.max(...xs) + Math.min(...xs)) / 2).toFixed(4), +((Math.max(...ys) + Math.min(...ys)) / 2).toFixed(4)], a: +(w * hh * 1e4).toFixed(2) });
      }
      out.scan = [...seen.values()].sort((a, b) => b.a - a.a).slice(0, cmd.scan.top ?? 12);
    }
    if (cmd.kinds) { // Hilfsabfrage: Zählung der Arten (kind, kind_detail) einer Quellschicht im Bild
      const t = {};
      for (const f of m.querySourceFeatures('basemap', { sourceLayer: cmd.kinds })) { const k = `${f.properties.kind ?? ''}|${f.properties.kind_detail ?? ''}|${f.geometry.type}`; t[k] = (t[k] ?? 0) + 1; }
      out.kinds = t;
    }
    if (cmd.flow) { // Hilfsabfrage: Richtung und Art der Wasserlinien (erste und letzte Koordinate), um Fließrichtung gegen bekannte Flüsse zu prüfen
      const kinds = {}, named = [];
      for (const f of m.querySourceFeatures('basemap', { sourceLayer: 'water' })) {
        const g = f.geometry; if (g.type !== 'LineString' && g.type !== 'MultiLineString') { const k = `${g.type}:${f.properties.kind ?? ''}`; kinds[k] = (kinds[k] ?? 0) + 1; continue; }
        const k = `${g.type}:${f.properties.kind ?? ''}`; kinds[k] = (kinds[k] ?? 0) + 1;
        const n = f.properties.name; if (n && cmd.flow.names?.includes(n)) { const l = g.type === 'LineString' ? g.coordinates : g.coordinates[0]; named.push({ n, k: f.properties.kind, a: l[0].map((v) => +v.toFixed(4)), b: l[l.length - 1].map((v) => +v.toFixed(4)), len: l.length }); }
      }
      out.flow = { kinds, named: named.slice(0, cmd.flow.top ?? 20) };
    }
    out.ripples = ripples?.stats?.();
    document.documentElement.dataset.debugOut = JSON.stringify(out);
  });
}

// ------------------------------------------------------------------ Karte
async function initMap() {
  const c = palette();
  const m = state.meta;
  map = new MlMap({
    container: 'map',
    style: { version: 8, sources: {}, glyphs: glyphsUrl(), layers: [{ id: 'bg', type: 'background', paint: { 'background-color': c.bg } }] },
    center: [m.center?.lon ?? START_VIEW.lon, m.center?.lat ?? START_VIEW.lat], zoom: 8.0, attributionControl: false, dragRotate: false, pitchWithRotate: false,
    locale: { 'FullscreenControl.Enter': 'Vollbild', 'FullscreenControl.Exit': 'Vollbild beenden', 'NavigationControl.ZoomIn': 'Vergrößern', 'NavigationControl.ZoomOut': 'Verkleinern' },
    maxBounds: [[m.bbox.lon_min - 0.45, m.bbox.lat_min - 0.28], [m.bbox.lon_max + 0.45, m.bbox.lat_max + 0.28]],
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
  if (document.fullscreenEnabled || document.webkitFullscreenEnabled) map.addControl(new FullscreenControl({ container: document.querySelector('.map-wrap') }), 'top-right');      // Karte samt Cartouche, Windrose und Legende
  map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-right');
  popup = new Popup({ closeButton: true, maxWidth: '320px' });

  await new Promise((res) => map.on('load', res));
  map.addSource('radius', { type: 'geojson', data: circle(m.center.lat, m.center.lon, m.radius_km) });
  // Verdunklung unter den Daten-Ebenen, nur bei eingeblendetem Luftverkehr: 80 % Schwarz bei 50 % Deckkraft = 0,4 wirksam
  map.addLayer({ id: 'air-dim', type: 'background', layout: { visibility: 'none' }, paint: { 'background-color': '#000000', 'background-opacity': 0.8 * 0.5 } });
  // Kein sichtbarer Kreis mehr; 'radius-fill' bleibt als unsichtbarer Anker, vor dem alle anderen Ebenen einsortiert werden
  map.addLayer({ id: 'radius-fill', type: 'fill', source: 'radius', layout: { visibility: 'none' }, paint: { 'fill-color': SWEEP_GREEN, 'fill-opacity': 0 } });
  map.addSource('vignette', { type: 'geojson', data: vignette(m.center.lat, m.center.lon, m.radius_km) });

  map.addSource('events', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  const isPoly = ['==', ['geometry-type'], 'Polygon'], isMulti = ['==', ['geometry-type'], 'MultiPolygon'];
  map.addLayer({ id: 'ev-fill', type: 'fill', source: 'events', filter: ['any', isPoly, isMulti],
    paint: { 'fill-color': sevColor(c), 'fill-opacity': 0.22 } });
  map.addLayer({ id: 'ev-outline', type: 'line', source: 'events', filter: ['any', isPoly, isMulti],
    paint: { 'line-color': sevColor(c), 'line-width': 2 } });
  map.addLayer({ id: 'ev-line-halo', type: 'line', source: 'events', layout: { 'line-cap': 'round' }, paint: { 'line-color': c.white, 'line-width': ['case', ['==', ['get', 'type'], 'congestion'], 10, ['==', ['get', 'severity'], 'info'], 6.5, 8], 'line-opacity': 0.8 } });
  map.addLayer({ id: 'ev-line', type: 'line', source: 'events', filter: ['any', ['==', ['geometry-type'], 'LineString'], ['==', ['geometry-type'], 'MultiLineString']],
    paint: { 'line-color': sevColor(c), 'line-width': ['case', ['==', ['get', 'type'], 'congestion'], 6, ['==', ['get', 'severity'], 'info'], 3, 4.5], 'line-opacity': 0.9 } });
  state.signsOk = registerSigns(map);
  registerArrow(map);
  state.iconsOk = await registerIcons(map, palette());
  try { registerMedieval(map); registerMedievalPatterns(map); registerFauna(map); registerInfra(map); map.addSource(FAUNA_SOURCE, { type: 'geojson', data: faunaPoints() }); } catch (err) { console.warn('Zeichen der historischen Karte fehlen:', err); }
  if (!state.iconsOk) $('.map-note')?.append(` · Symbole nicht geladen, Ersatzdarstellung (${iconStatus.errors[0] ?? 'Dateien fehlen'})`);
  // Rückfall ohne Icons (Dateien fehlen): die früheren Kreise
  map.addLayer({ id: 'ev-point', type: 'circle', source: 'events', filter: ['==', ['geometry-type'], 'Point'],
    layout: { visibility: state.iconsOk ? 'none' : 'visible' },
    paint: { 'circle-radius': 7, 'circle-color': sevColor(c), 'circle-stroke-color': c.white, 'circle-stroke-width': 1.5 } });
  // Symbole: Punkte am Ort, Linien in der Mitte. Wichtigeres wird zuerst gesetzt und nicht überdeckt.
  const iconImage = ['concat', 'ico-', ['get', 'icon'], '-', ['coalesce', ['get', 'lvl'], ['get', 'severity']]];
  const sym = (id, placement, works) => map.addLayer({
    id, type: 'symbol', source: 'events', minzoom: works ? 10 : 0,
    layout: { visibility: state.iconsOk ? 'visible' : 'none', 'symbol-placement': placement, 'icon-image': iconImage, 'icon-size': 1,
      // Plaketten stehen immer aufrecht; nur bewegte Objekte (Flugzeuge) drehen sich. Bei line-center würde MapLibre sonst dem Linienverlauf folgen.
      'icon-rotation-alignment': 'viewport', 'icon-rotate': 0, 'icon-keep-upright': false,
      // Stau, Sperrung, Warnung dürfen sich überlagern und werden nie ausgeblendet; Baustellen weichen einander aus
      'icon-allow-overlap': !works, 'icon-padding': 3, 'symbol-sort-key': ['-', 0, ['get', 'severity_rank']] },
  });
  sym('ev-sym-pt', 'point', false); sym('ev-sym-ln', 'line-center', false);
  // Örtliche Baustellen (Mobilitätsatlas, Autobahn-Baustellen) erst ab Zoom 10 als Symbol; davor kleine Punkte, sonst Teppich
  sym('ev-sym-pt-w', 'point', true); sym('ev-sym-ln-w', 'line-center', true);
  map.addLayer({ id: 'ev-dot-w', type: 'circle', source: 'events', maxzoom: 10,
    layout: { visibility: state.iconsOk ? 'visible' : 'none' },
    paint: { 'circle-radius': 3.5, 'circle-color': sevColor(c), 'circle-stroke-color': c.white, 'circle-stroke-width': 1 } });

  // Luftverkehr: eigene Quelle, weil sie sich jede Sekunde bewegt
  map.addSource('air', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'air-circle', type: 'circle', source: 'air', layout: { visibility: 'none' },
    paint: { 'circle-radius': 5, 'circle-opacity': 0, 'circle-stroke-color': sevColor(c), 'circle-stroke-width': 2 } });
  map.addLayer({ id: 'air-sym', type: 'symbol', source: 'air', layout: { visibility: 'none', 'icon-image': ['concat', ['get', 'img'], ['get', 'severity']],
    // Hubschrauber (Seitenansicht) bleiben aufrecht, Flächenflugzeuge drehen sich mit dem Kurs
    'icon-rotate': ['case', ['in', ['get', 'klass'], ['literal', ['heli', 'milheli']]], 0, ['coalesce', ['to-number', ['get', 'track']], 0]], 'icon-rotation-alignment': 'map', 'icon-allow-overlap': true, 'icon-size': 1 } });

  map.addSource('stations', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'st-circle', type: 'circle', source: 'stations', layout: { visibility: state.iconsOk ? 'none' : 'visible' },
    paint: { 'circle-radius': 5, 'circle-color': c.white, 'circle-stroke-color': c.info, 'circle-stroke-width': 2.5 } });
  map.addLayer({ id: 'st-sym', type: 'symbol', source: 'stations', layout: { visibility: state.iconsOk ? 'visible' : 'none', 'icon-image': 'ico-pegel-info', 'icon-rotation-alignment': 'viewport',
    // Dichte steuern: große Läufe immer, kleinere Läufe erst bei näherem Zoom (Größe 0 = nicht gezeichnet, ohne Kollisionsfläche);
    // nichts übereinander; bei Gedränge gewinnt der größere Lauf, bei gleichem Rang der Pegel mit Warnstufe
    // (MapLibre erlaubt nur einen Zoom-Ausdruck: die Stufen stehen deshalb in den Stützstellen der einen Interpolation)
    'icon-size': ['interpolate', ['linear'], ['zoom'],
      7, ['case', ['<=', ['get', 'rank'], 1], 0.55, 0], 8.9, ['case', ['<=', ['get', 'rank'], 1], 0.7, 0],
      9, ['case', ['<=', ['get', 'rank'], 1], 0.7, ['<=', ['get', 'rank'], 3], 0.7, 0], 10.4, ['case', ['<=', ['get', 'rank'], 3], 0.85, 0],
      10.5, 0.85, 11, 0.9],
    'icon-allow-overlap': false, 'icon-padding': 3,
    'symbol-sort-key': ['-', ['get', 'rank'], ['case', ['to-boolean', ['get', 'state']], 5, 0]] } });

  // Messstationen Luft und Strahlung: eigene Quelle, Plakette in der Stufenfarbe je Messwert
  map.addSource('env', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'env-circle', type: 'circle', source: 'env', layout: { visibility: 'none' },
    paint: { 'circle-radius': 5, 'circle-color': c.white, 'circle-stroke-color': sevColor(c), 'circle-stroke-width': 2.5 } });
  map.addLayer({ id: 'env-sym', type: 'symbol', source: 'env', layout: { visibility: 'none',
    'icon-image': ['case', ['has', 'tclass'], ['concat', 'wx-', ['to-string', ['get', 'tclass']]], ['concat', 'ico-', ['get', 'icon'], '-', ['get', 'severity']]],
    'icon-rotation-alignment': 'viewport', 'icon-size': ['interpolate', ['linear'], ['zoom'], 7, 0.55, 11, 1],
    // Messstellen nicht übereinander legen; Warnungen und Auffälliges zuerst, damit sie bei Gedränge stehen bleiben
    'icon-allow-overlap': false, 'icon-padding': 2,
    'symbol-sort-key': ['match', ['get', 'severity'], 'critical', 0, 'warning', 1, 'notice', 2, 3] } });

  map.addLayer({ id: 'wxst-label', type: 'symbol', source: 'env', minzoom: 9, filter: ['==', ['get', 'kind'], 'weather'], layout: { visibility: 'none',
    'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 11, 'text-offset': [0, 1.1], 'text-anchor': 'top', 'text-optional': true },
    paint: { 'text-color': '#1f3a5f', 'text-halo-color': '#fff', 'text-halo-width': 1.8 } });
  // Tankstellen (Tankerkönig): Zapfsäule am Standort, ab Zoom 11 der Preis für E10 daneben; Anklicken öffnet die Preiskarte
  map.addSource('tank', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'tank-circle', type: 'circle', source: 'tank', layout: { visibility: 'none' },
    paint: { 'circle-radius': 5, 'circle-color': c.white, 'circle-stroke-color': '#c2570c', 'circle-stroke-width': 2.5 } });
  map.addLayer({ id: 'tank-sym', type: 'symbol', source: 'tank', minzoom: 9.5, layout: { visibility: 'none', 'icon-image': 'stop-tanken',
    'icon-size': ['interpolate', ['linear'], ['zoom'], 9.5, 0.5, 13, 0.85], 'icon-allow-overlap': false, 'icon-padding': 2 } });
  map.addLayer({ id: 'tank-label', type: 'symbol', source: 'tank', minzoom: 12, layout: { visibility: 'none', 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'],
    'text-size': 11, 'text-offset': [0, 1.2], 'text-anchor': 'top', 'text-optional': true },
    paint: { 'text-color': '#8a3d06', 'text-halo-color': '#fff', 'text-halo-width': 1.8 } });

  const syncTowns = () => map.getContainer().classList.toggle('z-close', map.getZoom() >= 9);
  map.on('zoom', syncTowns); syncTowns();
  for (const [name, lat, lon, home] of TOWNS) {
    const el = h('div', { class: `town${home ? ' home' : ''}` }, home ? `● ${name}` : name);
    new Marker({ element: el, anchor: 'left', offset: [6, 0] }).setLngLat([lon, lat]).addTo(map);
  }

  for (const id of ['ev-fill', 'ev-outline', 'ev-line', 'ev-point', ...SYMBOL_LAYERS, 'air-circle', 'air-sym', 'st-circle', 'st-sym', 'env-circle', 'env-sym', 'tank-circle', 'tank-sym', ...INFRA_LAYER_IDS, 'routes-hit']) {
    map.on('mouseenter', id, () => (map.getCanvas().style.cursor = 'pointer'));
    map.on('mouseleave', id, () => (map.getCanvas().style.cursor = ''));
  }
  map.on('click', (e) => {
    const order = ['air-sym', 'air-circle', ...SYMBOL_LAYERS, ...INFRA_LAYER_IDS, 'routes-hit', 'ev-point', 'env-sym', 'env-circle', 'tank-sym', 'tank-circle', 'st-sym', 'st-circle', 'ev-line', 'ev-fill'];
    const hit = map.queryRenderedFeatures(e.point, { layers: order.filter((l) => map.getLayer(l)) })[0];
    if (!hit) return;
    showPopup(hit.properties, hit.layer.id === 'routes-hit' ? 'route' : hit.layer.id.startsWith('inf-') ? 'infra' : hit.layer.id.startsWith('tank-') ? 'tank' : hit.layer.id.startsWith('st-') ? 'station' : hit.layer.id.startsWith('env-') ? 'env' : 'event', e.lngLat);
  });

  const b = circle(m.center.lat, m.center.lon, m.radius_km).geometry.coordinates[0];
  map.fitBounds([[Math.min(...b.map((p) => p[0])), Math.min(...b.map((p) => p[1]))], [Math.max(...b.map((p) => p[0])), Math.max(...b.map((p) => p[1]))]], { padding: 24, animate: false });
  await setupBasemap();
  reliefOk = await setupRelief(map);
  if (reliefOk) light = createLight(map, { demTile, onError: (e) => console.warn('Licht:', e), reduce: reduceMotion, wind: () => { const c = map.getCenter(); const w = wind?.sample?.(c.lng, c.lat); return w ? { speed: w.speed, from: w.from } : null; } });
  mapReady = true;
  map.on('move', windroseUpdate);
  initSearch();
  if (location.hash === '#debug') debugHook(map); // nur für Prüfungen im Browser
  ripples = createRipples(map, { center: state.meta.center, radiusKm: state.meta.radius_km, fadeKm: VIG_FADE_KM, onSizzle: sizzleSound });
  // Untere Schicht zuerst anlegen, damit die obere (reiner Modellwind) darüber liegt
  windLow = createWind(map, { center: state.meta.center, radiusKm: state.meta.radius_km, fadeKm: VIG_FADE_KM, adjusted: true });
  wind = createWind(map, { center: state.meta.center, radiusKm: state.meta.radius_km, fadeKm: VIG_FADE_KM });
  loadTerrain('data/terrain.json').then((t) => { state.terrain = t; windLow.setTerrain(t); applyWind(); });
  ripples.setWind((lon, lat, out) => wind.sample(lon, lat, out));   // Dampf des Lasers driftet mit dem Modellwind
  flow = createFlow(map, { sampleWind: (lon, lat, out) => wind.sample(lon, lat, out), reduce: reduceMotion, onWind: showFlowWind });   // Wellen auf Stillgewässern ziehen mit dem Modellwind
  const windBar = $('#wind-bar'); if (windBar) fillWindLegend(windBar);
  const windBarLow = $('#wind-bar-low'); if (windBarLow) fillWindLegend(windBarLow, undefined, true);
  fillTempLegend();
  trackLegendBottom();
  buildRainLegend($('#rain-strip'), $('#rain-labels'));
  sweep = createSweep(map, { center: state.meta.center, radiusKm: state.meta.radius_km, mil: MIL_COLOUR, reducedMotion: reduceMotion, onPing: (e) => (e.zap ? zapSound(e) : pingSound(e)) });
  const laserBtn = $('#laser');   // Radarstrahl als Laser: verdampft den Regen, der fällt später wieder herab
  if (laserBtn) {
    if (reduceMotion) laserBtn.hidden = true;   // ohne Bewegung kein Strahl
    else laserBtn.addEventListener('click', () => {
      const on = laserBtn.getAttribute('aria-pressed') !== 'true';
      laserBtn.setAttribute('aria-pressed', String(on));
      sweep.setLaser(on);
      if (!on) silenceSound();
      ripples.setLaser(on ? () => sweep.beam() : null);
    });
  }
  applyBasemap();
  // Vignette zuletzt und ohne Zielebene: liegt damit über Karte, Daten und Sweep
  map.addLayer({ id: VIG_ID, type: 'fill', source: 'vignette', paint: { 'fill-color': '#000000', 'fill-opacity': ['get', 'a'], 'fill-antialias': false } });
  wireElevation();
  $('#licht-hoehe')?.addEventListener('input', (e) => light?.setHeight(Number(e.target.value)));
  applyLayerFilters();
  pushMapData();
}

// Basiskarte aus eigener PMTiles-Datei. Fehlt sie oder kann der Server keine Teilabrufe (HTTP Range),
// bleibt die Karte ohne Basis benutzbar und sagt das ehrlich im Kartenhinweis.
async function setupBasemap() {
  // Die Kartenleiste ist aus der Seite genommen (Quellenangabe steht im Footer und unter Quellen und Lizenzen); ohne Element läuft es still weiter
  const note = $('.map-note') ?? document.createElement('span');
  try {
    const url = new URL(TILES_URL, location.href).href;
    const archive = new PMTiles(url);
    await archive.getHeader(); // wirft, wenn Datei fehlt oder der Server Range nicht unterstützt
    const protocol = new Protocol();
    protocol.add(archive);
    addProtocol('pmtiles', protocol.tile);
    map.addSource('basemap', { type: 'vector', url: `pmtiles://${url}` });
    // Weinberge und Obstanlagen fehlen in den Kacheln: eigene Flächen aus data/anbau.json (OpenStreetMap, wöchentlich), Schalter "Obst und Wein"
    map.addSource('anbau', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    getJSON('data/anbau.json').then((j) => { if (Array.isArray(j?.features)) map.getSource('anbau')?.setData(j); }).catch(() => {});
    basemapOk = true;
    try {   // Kern mit Gebäudedetail; fehlt er, bleibt die Karte wie sie ist (Gebäude dann nur grob aus Zoom 13, keine Hausnummern)
      const coreUrl = new URL(CORE_URL, location.href).href;
      const core = new PMTiles(coreUrl);
      await core.getHeader();
      protocol.add(core);
      map.addSource('basemap-core', { type: 'vector', url: `pmtiles://${coreUrl}`, tileSize: 256 });   // 256er Kachelmaß: die Zoom-15-Kacheln (alle Gebäude) gelten schon ab Kartenzoom 14
      coreOk = true;
    } catch (err) { console.warn('Kernkarte (Zoom 15) nicht verfügbar:', err?.message ?? err); }
    try {   // Ring um den Kern (nur Zoom 14): Häuserumrisse im restlichen Radius, ohne Hausnummern
      const ringUrl = new URL(RING_URL, location.href).href;
      const ring = new PMTiles(ringUrl);
      await ring.getHeader();
      protocol.add(ring);
      map.addSource('basemap-ring', { type: 'vector', url: `pmtiles://${ringUrl}` });
      ringOk = true;
    } catch (err) { console.warn('Ringkarte (Zoom 14) nicht verfügbar:', err?.message ?? err); }
    note.replaceChildren('Karte: ', link('https://www.openstreetmap.org/copyright', '© OpenStreetMap-Mitwirkende (ODbL)'), ' · Protomaps');
    if (globalThis.mlcontour) note.append(' · ', RELIEF_ATTRIBUTION);
  } catch (err) {
    console.warn('Basiskarte nicht verfügbar:', err?.message ?? err);
    note.replaceChildren('Basiskarte nicht verfügbar');
  }
}

// Hauptstraßen (Autobahn, Bundes-/Landstraße, Anschlussstellen, auch Brücken und Tunnel) mit 1-px-Kontur in Schwarz:
// Autobahnen blau, alle anderen Hauptstraßen gelborange. Die Konturen des Stils sind Linien neben der Straße
// (line-gap-width), ihre Breite ist die Konturbreite.
const MAIN_ROAD = /^roads_(highway|major|link|bridges_(highway|major|link)|tunnels_(highway|major|link))(_casing(_early|_late)?)?$/;
const ROAD_FILL = '#f6a81c';
const AUTOBAHN_FILL = '#1f5fbf';
// Breite der Fahrbahn (Füllung) in px; die Konturlinien sitzen mit line-gap-width genau daneben. Größer als im Stil, damit die Farbe
// schon bei kleinem Maßstab sichtbar ist und nicht nur die schwarze Kontur.
const ROAD_W = ['interpolate', ['exponential', 1.6], ['zoom'], 6, 1.2, 9, 2.4, 12, 3.6, 15, 7, 18, 15];
const LINK_W = ['interpolate', ['exponential', 1.6], ['zoom'], 11, 0, 12, 1.4, 15, 4, 18, 10];
// Zwei Klassen außerhalb der Autobahn: Bundes- und Nationalstraßen (B, N, RN; in OSM primary/trunk) kräftig orange und breiter,
// Land-, Kreis- und Departementsstraßen (L, K, D, CR; secondary/tertiary) hellgelb und schmaler. Die Klasse kommt aus kind_detail
// und dem Kürzel der Straßennummer (ref); beides steht in den Kacheln.
const ROAD_FILL_MINOR = '#f8df85';
const NATIONAL = ['any',
  ['in', ['coalesce', ['get', 'kind_detail'], ''], ['literal', ['primary', 'trunk', 'primary_link', 'trunk_link']]],
  ['in', ['slice', ['coalesce', ['get', 'ref'], ''], 0, 1], ['literal', ['B', 'N']]]];
// Zoom-Stützwerte einzeln mit dem Klassenfaktor multiplizieren (zoom darf nur oberster interpolate-Eingang sein)
const scaled = (w, k) => w.map((x, i) => (i >= 4 && i % 2 === 0 && typeof x === 'number' && x > 0 ? ['*', k, x] : x));
function mainRoad(l) {
  if (!MAIN_ROAD.test(l.id)) return l;
  const casing = l.id.includes('casing');
  const motorway = /^roads_(bridges_|tunnels_)?highway/.test(l.id);
  const base = l.id.includes('link') ? LINK_W : ROAD_W;
  const w = motorway ? base : scaled(base, ['case', NATIONAL, 1.2, 0.8]);
  const fill = motorway ? AUTOBAHN_FILL : ['case', NATIONAL, ROAD_FILL, ROAD_FILL_MINOR];
  const paint = { ...l.paint, 'line-color': casing ? '#000000' : fill };
  if (casing) {
    paint['line-gap-width'] = w;
    paint['line-width'] = 1;
    paint['line-opacity'] = ['interpolate', ['linear'], ['zoom'], 9.5, 0, 10.5, 1]; // weit herausgezoomt keine schwarze Kontur
  } else paint['line-width'] = w;
  return { ...l, paint };
}

// Gebäude in Bordeaux; Beschriftungen (Straßennamen, Hausnummern) mit der einzigen mitgelieferten Schrift, früher einsetzend als im Stil
const SIZE_MIN_PX = 8 * 4 / 3;    // 8 pt kleinster Ortsname (Einzelhof, Weiler)
const SIZE_MAX_PX = 12 * 4 / 3;   // 12 pt größter Ortsname (Großstadt)
const LABEL_SKIP = /^(boundaries|pois$|roads_shields|roads_oneway|places_(country|region)|water_label_ocean|earth_label_islands)/;
const INK = { light: '#111111', dark: '#f4f4f4' };
const WATER_INK = { light: '#0b4f9c', dark: '#8cc4ff' };   // Gewässernamen immer blau
const HALO = { light: 'rgba(255,255,255,0.95)', dark: 'rgba(16,16,16,0.95)' };
const BUILDING_OPACITY = 0.4; // 60 % Transparenz, damit Relief und Straßen durchscheinen
const BUILDING = { light: '#800020', dark: '#9c2a4b' };
const GREEN = { light: '#9fc98a', dark: '#2f6a43' };
// Flächenfarben nach OSM-Klasse (Farbe, Deckkraft); dezent, damit Relief, Straßen und Ereignisse führen
// Farben nach der Natur: Wald dunkles Blattgrün, Wiese frisches Gelbgrün, Weide/Rasen satteres Grün, Busch olivgrau,
// Heide Heidekraut-Violett, Acker Stoppelgelb, Obst helles Apfelgrün, Wein Strohgelb, Moor blaugrün, Fels Steingrau, Sand Hellgelb.
const LAND = {
  light: { forest: ['#5f9f5b', 0.55], meadow: ['#c4dc8a', 0.5], grass: ['#a9d57c', 0.5], scrub: ['#94a862', 0.5], heath: ['#bb98ae', 0.5],
    farmland: ['#e9dcaa', 0.45], orchard: ['#bdd677', 0.5], vineyard: ['#cfc27c', 0.5], allotment: ['#d6e4a2', 0.5], wetland: ['#8fc4a8', 0.55],
    rock: ['#b6ab9c', 0.6], sand: ['#f0e3b2', 0.6], cemetery: ['#b5d0a4', 0.55] },
  dark: { forest: ['#245234', 0.6], meadow: ['#4a7240', 0.5], grass: ['#3f7040', 0.5], scrub: ['#505e36', 0.5], heath: ['#5e4a58', 0.5],
    farmland: ['#5f5733', 0.4], orchard: ['#4c6a35', 0.5], vineyard: ['#5d5a30', 0.5], allotment: ['#4f6a3f', 0.5], wetland: ['#2b5f58', 0.55],
    rock: ['#6d675f', 0.6], sand: ['#6f6747', 0.55], cemetery: ['#3d5f45', 0.55] },
};
// Tinte der Signaturen (Rgba), Bilder lp-<klasse>-<light|dark> aus icons.js registerLandPatterns()
const PAT_MIN_ZOOM = 12;
const PROTECTED = { light: '#2e7d3c', dark: '#7fd18a' };
const CLIFF = { light: '#0e0f11', dark: '#dedad2' }; // dunkles Steingrau bzw. helles Grau, bewusst kein Braun: Höhenlinien sind braun
const CLIFF_SCREE = { light: '#6f675b', dark: '#8d8578' };   // Geröllband am Fuß der Wand
const QUARRY = { light: ['#8a6d3b', '#4a3a1c'], dark: ['#d9b56b', '#f0dcae'] };
const LAND_KINDS = {
  forest: ['forest', 'wood'],
  meadow: ['meadow'],
  grass: ['grass', 'grassland', 'park', 'garden', 'recreation_ground', 'golf_course', 'dog_park', 'village_green'],
  scrub: ['scrub'],
  heath: ['heath'],
  farmland: ['farmland'],
  orchard: ['orchard'],
  vineyard: ['vineyard'],
  allotment: ['allotments'],
  wetland: ['wetland'],
  rock: ['bare_rock'],
  sand: ['sand', 'beach'],
  cemetery: ['cemetery'],
};
const PROTECTED_KINDS_NR = ['protected_area', 'nature_reserve'];
const PROTECTED_KINDS_NP = ['national_park'];
const PARK_NAT = { light: '#0f7a73', dark: '#5fd1c4' };
const MILITARY = { light: '#b23b2a', dark: '#f08b78' };
// Grenzen: id, Filter, Mindestzoom, Breite, Strichmuster
const BOUNDS = [
  ['local', ['in', 'kind_detail', 7, 8], 10, 0.8, [1, 3]],
  ['county', ['==', 'kind_detail', 6], 8, 1, [4, 2]],
  ['region', ['==', 'kind_detail', 4], 5, 1.3, [6, 2, 1, 2]],
  ['country', ['==', 'kind_detail', 2], 3, 1.8, null],
];
const BOUND_COLOR = { light: { country: '#4b2e83', region: '#6a4aa5', county: '#8a74b8', local: '#9a8fb5' }, dark: { country: '#c3a8ff', region: '#a98cf0', county: '#9a86d0', local: '#7f76a0' } };
const HOUSENO = { light: ['#6b0019', 'rgba(255,255,255,0.9)'], dark: ['#f0b3c4', 'rgba(20,20,20,0.9)'] };
function labelsAndBuildings(dark) {
  const k = dark ? 'dark' : 'light';
  return (l) => {
    let out = l;
    if (l.layout?.['text-font']) {
      const layout = { ...out.layout, 'text-font': ['Noto Sans Regular'] };
      delete layout['icon-image']; // ohne Sprite kein Symbol, der Text bleibt
      out = { ...out, layout };
    }
    if (l.id === 'buildings') {
      out = { ...out, minzoom: 13, paint: { ...out.paint, 'fill-color': BUILDING[k], 'fill-outline-color': dark ? '#5a1830' : '#4d0013',
        'fill-opacity': BUILDING_OPACITY } };
    } else if (l.id === 'landuse_park') {
      // Wald, Wiese, Acker und Co. zeichnet landUseLayers() nach Klasse; hier bleibt, was der Stil sonst noch kennt
      out = { ...out, filter: ['in', 'kind', 'airfield', 'glacier'] };
    } else if (l.id === 'landuse_urban_green') {
      out = { ...out, paint: { ...out.paint, 'fill-color': LAND[k].meadow[0], 'fill-opacity': LAND[k].meadow[1] } };
    } else if (l.id === 'landcover') {
      // nur Wald, Wiese und Buschland grün; Acker, Siedlung und Kahlland behalten die Farbe des Stils
      out = { ...out, paint: { ...out.paint,
        'fill-color': ['match', ['get', 'kind'], ['forest', 'grassland', 'scrub'], GREEN[k], out.paint['fill-color']],
        'fill-opacity': ['interpolate', ['linear'], ['zoom'], 5, 0.5, 8, 0.3] } };
    } else if (l.id === 'address_label') {
      out = { ...out, minzoom: 16, layout: { ...out.layout, 'text-size': ['interpolate', ['linear'], ['zoom'], 16, 10, 19, 13], 'text-allow-overlap': false },
        paint: { ...out.paint, 'text-color': HOUSENO[k][0], 'text-halo-color': HOUSENO[k][1], 'text-halo-width': 1.5 } };
    } else if (l.id === 'roads_labels_minor' || l.id === 'roads_labels_major') {
      // Straßennamen: dunkle Schrift auf kräftigem hellem Saum (dunkel: umgekehrt), größer als im Stil
      out = { ...out, minzoom: l.id === 'roads_labels_minor' ? 13 : l.minzoom,
        layout: { ...out.layout, 'text-size': ['interpolate', ['linear'], ['zoom'], 11, 11, 15, 12.5, 18, 15] },
        paint: { ...out.paint, 'text-color': INK[k], 'text-halo-color': HALO[k], 'text-halo-width': 2.4, 'text-halo-blur': 0.3 } };
    } else if (l.id === 'water_waterway_label' || l.id === 'water_label_lakes') {
      out = { ...out, paint: { ...out.paint, 'text-color': WATER_INK[k], 'text-halo-color': HALO[k], 'text-halo-width': 2.2, 'text-halo-blur': 0.3 } };
    } else if (l.id === 'places_locality' || l.id === 'places_subplace') {
      // Ortsnamen: größer, gesperrt, in voller Textfarbe mit breitem Saum; Irrel steht schon als eigener Marker
      // Größe nach Siedlungsgröße: population_rank der Kacheln (1 Einzelhof … 9 Großstadt) → 8 pt bis 12 pt (10,67 bis 16 px),
      // unabhängig vom Zoom. Weiler = Rang 2, Dorf 3 bis 5, Stadt 6 bis 7, Trier = 9. Fehlt der Rang, gilt der kleinste Wert.
      const rank = ['max', 1, ['min', 9, ['to-number', ['get', 'population_rank'], 1]]];
      out = { ...out, minzoom: 9, filter: ['all', ...(l.filter ? [l.filter] : []), ['!=', 'name', 'Irrel']],
        layout: { ...out.layout, 'text-size': ['interpolate', ['linear'], rank, 1, SIZE_MIN_PX, 9, SIZE_MAX_PX],
          'text-letter-spacing': 0.06, 'text-transform': ['case', ['>=', rank, 6], 'uppercase', 'none'], 'text-max-width': 8 },
        paint: { ...out.paint, 'text-color': INK[k], 'text-halo-color': HALO[k], 'text-halo-width': 2.8, 'text-halo-blur': 0.3 } };
    }
    return out;
  };
}

// Flächen nach Klasse (Wald, Wiese, Buschland, Acker, Feuchtgebiet, Fels), Klippenlinien und Steinbrüche aus der Basiskarte.
// Die Kacheln führen Klippen als earth/cliff (Linien) und Steinbrüche als benannte Punkte in pois/quarry.
function landUseLayers(dark, ticks) {
  const k = dark ? 'dark' : 'light';
  const fills = Object.entries(LAND_KINDS).flatMap(([cls, kinds]) => {
    // Weinberg und Obstanlage kommen aus der eigenen GeoJSON-Quelle (die Kacheln führen sie nicht)
    const own = cls === 'vineyard' || cls === 'orchard';
    const src = own ? { source: 'anbau' } : { source: 'basemap', 'source-layer': 'landuse' };
    const flt = own ? ['==', ['get', 'kind'], cls] : ['in', 'kind', ...kinds];
    const fill = {
      id: `land-${cls}`, type: 'fill', ...src, filter: flt,
      paint: { 'fill-color': LAND[k][cls][0], 'fill-opacity': LAND[k][cls][1], 'fill-antialias': true },
    };
    // Signatur (Baumkronen, Furchen, Rebzeilen …) ab Zoom 12 darüber; fehlt das Bild, bleibt die Farbe allein
    const img = `lp-${cls}-${k}`;
    if (!map.hasImage(img)) return [fill];
    return [fill, { id: `land-${cls}-pat`, type: 'fill', ...src, minzoom: PAT_MIN_ZOOM - 1, filter: fill.filter,
      paint: { 'fill-pattern': img, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], PAT_MIN_ZOOM - 1, 0, PAT_MIN_ZOOM + 1, 0.9], 'fill-antialias': false } }];
  });
  return [
    ...fills,
    // Schutzgebiete: Flächenton kaum sichtbar, gestrichelte Kante; Naturschutzgebiete grün, Nationalparks blaugrün
    ...[['nr', PROTECTED_KINDS_NR, PROTECTED[k]], ['np', PROTECTED_KINDS_NP, PARK_NAT[k]]].flatMap(([id, kinds, col]) => [
      { id: `land-protected-${id}-fill`, type: 'fill', source: 'basemap', 'source-layer': 'landuse', filter: ['in', 'kind', ...kinds],
        paint: { 'fill-color': col, 'fill-opacity': 0.07 } },
      { id: `land-protected-${id}-line`, type: 'line', source: 'basemap', 'source-layer': 'landuse', minzoom: 9, filter: ['in', 'kind', ...kinds],
        layout: { 'line-join': 'round' },
        paint: { 'line-color': col, 'line-opacity': 0.75, 'line-dasharray': [4, 3],
          'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.8, 14, 1.8], 'line-offset': ['interpolate', ['linear'], ['zoom'], 9, 0.4, 14, 1] } },
    ]),
    // Militärgelände und Sperrgebiete: rötlicher Ton, Strichpunkt-Kante
    { id: 'land-military-fill', type: 'fill', source: 'basemap', 'source-layer': 'landuse', filter: ['in', 'kind', 'military', 'naval_base'],
      paint: { 'fill-color': MILITARY[k], 'fill-opacity': 0.12 } },
    { id: 'land-military-line', type: 'line', source: 'basemap', 'source-layer': 'landuse', minzoom: 9, filter: ['in', 'kind', 'military', 'naval_base'],
      layout: { 'line-join': 'round' },
      paint: { 'line-color': MILITARY[k], 'line-opacity': 0.85, 'line-dasharray': [6, 2, 1, 2],
        'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.8, 14, 1.8], 'line-offset': ['interpolate', ['linear'], ['zoom'], 9, 0.4, 14, 1] } },
    // Verwaltungsgrenzen aus den Kacheln (kind_detail = admin_level: 2 Staat, 4 Land, 6 Kreis, 7 und 8 Gemeinde)
    ...BOUNDS.map(([id, filter, minzoom, width, dash]) => ({ id: `land-bound-${id}`, type: 'line', source: 'basemap', 'source-layer': 'boundaries', minzoom, filter,
      layout: { 'line-join': 'round', 'line-cap': 'butt' },
      paint: { 'line-color': BOUND_COLOR[k][id], 'line-opacity': 0.85, 'line-width': ['interpolate', ['linear'], ['zoom'], 5, width * 0.7, 14, width * 1.8], ...(dash ? { 'line-dasharray': dash } : {}) } })),
    // Klippe in drei Lagen: weiches Geröllband auf der Abbruchseite (rechts der Linienrichtung), heller Saum für Lesbarkeit im Wald,
    // dünne Wandlinie mit Schraffen (lange und kurze Striche im Wechsel, Bild cliff-tick)
    { id: 'land-cliff-band', type: 'line', source: 'basemap', 'source-layer': 'earth', minzoom: 12, filter: ['==', 'kind', 'cliff'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': CLIFF_SCREE[k], 'line-opacity': 0.55, 'line-blur': 2.5, 'line-offset': ['interpolate', ['linear'], ['zoom'], 12, 2, 17, 6],
        'line-width': ['interpolate', ['linear'], ['zoom'], 12, 4, 17, 12] } },
    { id: 'land-cliff-case', type: 'line', source: 'basemap', 'source-layer': 'earth', minzoom: 12, filter: ['==', 'kind', 'cliff'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': dark ? '#161616' : '#ffffff', 'line-opacity': 0.5, 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 2.4, 16, 4] } },
    { id: 'land-cliff', type: 'line', source: 'basemap', 'source-layer': 'earth', minzoom: 12, filter: ['==', 'kind', 'cliff'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': CLIFF[k], 'line-opacity': 1, 'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1.1, 16, 2.2] } },
    ...(ticks ? [{ id: 'land-cliff-teeth', type: 'symbol', source: 'basemap', 'source-layer': 'earth', minzoom: 13, filter: ['==', 'kind', 'cliff'],
      layout: { 'symbol-placement': 'line', 'symbol-spacing': 8, 'icon-image': 'cliff-tick', 'icon-anchor': 'top', 'icon-offset': [0, 0.5],
        'icon-rotation-alignment': 'map', 'icon-allow-overlap': true, 'icon-ignore-placement': true,
        'icon-size': ['interpolate', ['linear'], ['zoom'], 13, 0.85, 17, 1.25] },
      paint: { 'icon-color': CLIFF[k], 'icon-opacity': 1 } }] : []),
    { id: 'land-quarry-dot', type: 'circle', source: 'basemap', 'source-layer': 'pois', minzoom: 11, filter: ['==', 'kind', 'quarry'],
      paint: { 'circle-radius': 4.5, 'circle-color': QUARRY[k][0], 'circle-stroke-color': dark ? '#161616' : '#ffffff', 'circle-stroke-width': 1.5 } },
    { id: 'land-quarry-label', type: 'symbol', source: 'basemap', 'source-layer': 'pois', minzoom: 12, filter: ['==', 'kind', 'quarry'],
      layout: { 'text-field': ['concat', 'Steinbruch ', ['coalesce', ['get', 'name'], '']], 'text-font': ['Noto Sans Regular'], 'text-size': 11,
        'text-offset': [0, 0.9], 'text-anchor': 'top', 'text-max-width': 9 },
      paint: { 'text-color': QUARRY[k][1], 'text-halo-color': HALO[k], 'text-halo-width': 2, 'text-halo-blur': 0.3 } },
  ];
}

// Dunkelblaue Kontrastlinie um Gewässer, im Maßstab wie die Straßenkanten: Seen und Flussflächen bekommen eine Randlinie,
// Flüsse und Bäche (als Linien) einen dunkleren, etwas breiteren Saum unter der Wasserlinie.
// Linienbreite um `add` px verbreitern. Zoom-Ausdrücke dürfen nur oberste interpolate/step sein, also die Stützwerte einzeln anheben
// (Nullstellen bleiben null, damit der Saum dort einsetzt, wo die Linie selbst beginnt).
function widen(w, add) {
  if (typeof w === 'number') return w + add;
  if (Array.isArray(w) && w[0] === 'interpolate') return w.map((x, i) => (i >= 4 && i % 2 === 0 && typeof x === 'number' && x > 0 ? x + add : x));
  return w;
}
const WATER_EDGE = { light: '#1a4a85', dark: '#7db7f0' };
function waterEdges(styled, dark) {
  const k = dark ? 'dark' : 'light', color = WATER_EDGE[k];
  const at = (id) => styled.findIndex((x) => x.id === id);
  // Flüsse und Bäche sind in OSM teils Fläche (breite Abschnitte), teils nur Mittellinie (schmale, ungemappte Abschnitte wie die Prüm).
  // Linie samt dunklem Saum liegt deshalb UNTER der Wasserfläche: wo eine Fläche ist, verdeckt sie die Linie (kein Strich mitten im Fluss),
  // wo keine ist, bleibt die Linie mit Saum sichtbar und der Fluss reißt nicht ab.
  const casings = [], tops = [];
  for (const id of ['water_stream', 'water_river']) {
    const i = at(id);
    if (i < 0) continue;
    const base = styled[i];
    styled.splice(i, 1);
    // Breite im Maßstab der Wirklichkeit (Fluss etwa 12 m, Bach etwa 3 m; Pixel verdoppeln sich je Zoomstufe), damit die Linie dort, wo nur
    // die Mittellinie gemappt ist, so breit aussieht wie die Wasserfläche daneben. Farbe wie die Fläche (paintWater), Saum wie ihr Rand.
    const width = id === 'water_river'
      ? ['interpolate', ['exponential', 2], ['zoom'], 8, 1.2, 12, 1.8, 14, 3.4, 16, 8, 19, 62]
      : ['interpolate', ['exponential', 2], ['zoom'], 8, 0.6, 12, 1, 14, 1.6, 16, 3, 19, 22];
    const round = { ...base.layout, 'line-cap': 'round', 'line-join': 'round' };
    casings.push({ ...base, id: `${id}_casing`, layout: round, minzoom: Math.max(base.minzoom ?? 0, 8),
      paint: { 'line-color': color, 'line-opacity': 0.9, 'line-width': widen(width, 2.2) } });
    tops.push({ ...base, layout: round, paint: { ...base.paint, 'line-width': width, 'line-opacity': 1 } });
  }
  // Reihenfolge von unten: dunkle Säume der Linien, dunkler Rand der Flächen (doppelt breit, unter der Fläche nur die Außenhälfte sichtbar),
  // Wasserfläche, zuletzt die hellen Mittellinien in Flächenfarbe. So verdeckt die helle Linie den Querstrich, wo eine gemappte Fläche endet
  // und die bloße Mittellinie weiterläuft: Fläche und Linie lesen sich als ein Fluss.
  const edge = { id: 'water_edge', type: 'line', source: 'basemap', 'source-layer': 'water', minzoom: 8, filter: ['==', ['geometry-type'], 'Polygon'],
    layout: { 'line-join': 'round' },
    paint: { 'line-color': color, 'line-opacity': 0.9, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 1, 12, 2.2, 16, 4.4] } };
  const w = at('water');
  if (w >= 0) styled.splice(w, 1, ...casings, edge, styled[w], ...tops);
  else styled.push(...casings, ...tops);
}

// Straßenschilder auf der Karte (Ausgangsbild: icons.js registerSigns): A blau, B gelb, L und K weiß. Text ist die Straßennummer
// aus OSM (ref, z. B. "A 60", "B 257", "L 4"); Mehrfachbezeichnungen mit Semikolon oder mehr als 8 Zeichen bleiben weg.
function signLayers(dark) {
  const first = ['slice', ['get', 'ref'], 0, 1];
  const mk = (id, kinds, prefixes, image, text, minzoom) => ({
    id, type: 'symbol', source: 'basemap', 'source-layer': 'roads', minzoom,
    filter: ['all', ['in', ['get', 'kind'], ['literal', kinds]], ['has', 'ref'], ['in', first, ['literal', prefixes]],
      ['<=', ['length', ['get', 'ref']], 8], ['!', ['has', 'is_link']]],
    layout: { 'symbol-placement': 'line', 'symbol-spacing': 340, 'text-field': ['get', 'ref'], 'text-font': ['Noto Sans Regular'], 'text-size': 11,
      'icon-image': image, 'icon-text-fit': 'both', 'icon-text-fit-padding': [2, 5, 2, 5], 'icon-rotation-alignment': 'viewport',
      'text-rotation-alignment': 'viewport', 'text-keep-upright': false, 'text-padding': 8, 'icon-padding': 8 },
    paint: { 'text-color': text },
  });
  void dark;
  return [
    mk('bm-sign-autobahn', ['highway'], ['A'], 'sign-autobahn', '#ffffff', 8),
    mk('bm-sign-bundes', ['major_road'], ['B', 'N'], 'sign-bundes', '#111111', 10),
    mk('bm-sign-land', ['major_road'], ['L', 'K', 'D', 'C'], 'sign-land', '#111111', 12),
  ];
}

// ------------------------------------------------------------------ Karte „um 1450“
// Schaltbar unter „Kultur und Geschichte“: Pergament, Tinte, Wege statt Straßen, ohne Bahn, Flughäfen und Grenzen; Höhenlinien, Gebäude, Schilder und Klippen bleiben über ihre Schalter nutzbar, Schrift in Textura-Art (Grenze Gotisch).
// Nur die Darstellung ändert sich; Ereignisse und Messwerte liegen unverändert darüber. Schrift: Grenze Gotisch (OFL), Glyphen unter fonts/.
const MED = { bg: '#d9c28c', paper: '#e8d6a6', ink: '#3a2614', road: '#7a5530', water: '#a6bcb0', edge: '#58726a', halo: 'rgba(238,224,182,0.92)', waterLabel: '#1f4f86' };
const MED_FONT = ['Grenze Gotisch Regular'];
// Schriftgröße skalieren, ohne den Zoom-Ausdruck zu verschachteln (MapLibre erlaubt "zoom" nur direkt in step/interpolate): Ausgabewerte der Stützstellen mit k multiplizieren
function scaleSize(e, k) {
  if (typeof e === 'number') return e * k;
  if (!Array.isArray(e)) return e;
  if (e[0] === 'interpolate' || e[0] === 'interpolate-hcl' || e[0] === 'interpolate-lab') return e.map((v, i) => (i >= 3 && i % 2 === 0 ? scaleSize(v, k) : v));
  if (e[0] === 'step') return e.map((v, i) => (i === 2 || (i > 2 && i % 2 === 0) ? scaleSize(v, k) : v));
  return ['*', k, e];
}
const RETINA = (window.devicePixelRatio || 1) >= 1.5;
// Farben der Zeichen in der historischen Karte (Pigmente: Zinnober, Ocker, Krapp); Stufen bleiben unterscheidbar, Rot heißt weiter Rot
const MED_COLORS = { bg: '#efe0b0', line: '#7a5530', fg: MED.ink, muted: '#7a6850', critical: '#7a1020', warning: '#b03a22', notice: '#b7791f',
  yellow: '#d9a520', orange: '#c8661c', red: '#a33a22', black: '#2b1d10', info: '#3f6b72', accent: '#a33a22', white: '#efe0b0', ink: MED.ink };
const MED_ICON_STYLE = { light: '#efe0b0', dark: '#3a2614' };
const MED_LAND = { forest: ['#8fa672', 0.55], meadow: ['#d6c88c', 0.15], scrub: ['#a9a66e', 0.35], farmland: ['#e3cf94', 0.2], wetland: ['#a9bdb0', 0.55], rock: ['#a89678', 0.55] };
// neue Klassen der Naturfarben auf die Pigmente der alten Karte abbilden (Schutzgebiete und moderne Signaturen entfallen)
const MED_CLASS = { grass: 'meadow', heath: 'scrub', orchard: 'farmland', vineyard: 'farmland', allotment: 'farmland', sand: 'farmland', cemetery: 'meadow' };
const MED_DROP = /^(land-([a-z]+-pat|protected-|military-|bound-|cliff-(band|case))|roads_oneway|roads_rail|roads_runway|roads_taxiway|roads_pier|roads_labels_|roads_tunnels_|roads_.*casing|landuse_(park|runway|aerodrome|industrial|school|hospital|zoo|pedestrian|pier|urban_green|beach)|boundaries|address_label)/;
const medFlavor = () => ({ ...namedFlavor('grayscale'), background: MED.bg, earth: MED.paper, water: MED.water, city_label: MED.ink, subplace_label: MED.ink, city_label_halo: MED.halo, subplace_label_halo: MED.halo });
function medievalize(styled) {
  const rank = ['max', 1, ['min', 9, ['to-number', ['get', 'population_rank'], 1]]];
  const out = [], pat = [];
  for (const l of styled) {
    if (MED_DROP.test(l.id)) continue;
    let x = l;
    if (l.id === 'background') x = { ...l, paint: { 'background-color': MED.bg } };
    else if (l.id === 'earth') x = { ...l, paint: { ...l.paint, 'fill-color': MED.paper } };
    else if (l.id === 'water') { x = { ...l, paint: { ...l.paint, 'fill-color': MED.water } }; pat.push([out.length + 1, waterPatternLayer()]); }
    else if (l.id === 'water_edge' || l.id.endsWith('_casing') && l.id.startsWith('water_')) x = { ...l, paint: { ...l.paint, 'line-color': MED.edge, 'line-opacity': 0.75 } };
    else if (l.id.startsWith('roads_') && l.type === 'line') {
      const major = /highway|major/.test(l.id);
      x = { ...l, layout: { ...l.layout, 'line-cap': 'round' }, paint: { 'line-color': MED.road, 'line-opacity': 0.8,
        'line-width': ['interpolate', ['linear'], ['zoom'], 8, major ? 0.9 : 0.5, 12, major ? 1.6 : 0.8, 16, major ? 2.6 : 1.4],
        ...(major ? {} : { 'line-dasharray': [3, 2] }) } };
    } else if (l.id.startsWith('land-') && MED_LAND[MED_CLASS[l.id.slice(5)] ?? l.id.slice(5)]) {
      const cls = l.id.slice(5), mk = MED_CLASS[cls] ?? cls;
      const [c, o] = MED_LAND[mk];
      x = { ...l, paint: { ...l.paint, 'fill-color': c, 'fill-opacity': o } };
      pat.push([out.length + 1, patternLayer(x, cls, mk)]);
    } else if (l.id === 'buildings') x = { ...l, paint: { 'fill-pattern': 'med-bldg', 'fill-opacity': 1 } };
    else if (l.id === 'nat-peak-sym') x = { ...l, layout: { ...l.layout, 'icon-image': 'med-peak', 'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.55, 15, 0.85] } };
    else if (l.id === 'land-cliff') x = { ...l, minzoom: 11, paint: { 'line-color': MED.ink, 'line-opacity': 0.95, 'line-width': ['interpolate', ['linear'], ['zoom'], 11, 1.1, 16, 2.6] } };
    else if (l.id === 'land-cliff-teeth') x = { ...l, minzoom: 12, layout: { ...l.layout, 'icon-image': 'med-cliff', 'symbol-spacing': 6, 'icon-offset': [0, 0.5],
      'icon-size': ['interpolate', ['linear'], ['zoom'], 12, 0.6, 17, 1.15] }, paint: { 'icon-opacity': 0.95 } };
    else if (l.id === 'land-quarry-dot') x = { ...l, paint: { ...l.paint, 'circle-color': MED.road, 'circle-stroke-color': MED.paper } };
    if (x.layout?.['text-font']) {
      const water = /^water_/.test(x.id);
      const layout = { ...x.layout, 'text-font': MED_FONT };
      if (x.id === 'places_locality' || x.id === 'places_subplace') {
        delete layout['text-variable-anchor']; delete layout['text-radial-offset'];
        layout['text-anchor'] = 'top'; layout['text-offset'] = [0, 0.95];   // dicht unter dem Siedlungszeichen
        layout['text-transform'] = 'none'; layout['text-letter-spacing'] = 0;   // gebrochene Schrift: keine Versalien, keine Sperrung
        if (Array.isArray(layout['text-size'])) layout['text-size'] = scaleSize(layout['text-size'], RETINA ? 1.32 : 1.15);   // gebrochene Schrift braucht auf Retina mehr Höhe
      } else if (RETINA && Array.isArray(layout['text-size'])) layout['text-size'] = scaleSize(layout['text-size'], 1.12);
      x = { ...x, layout, paint: { ...x.paint, 'text-color': water ? MED.waterLabel : MED.ink, 'text-halo-color': MED.halo, 'text-halo-width': 2, 'text-halo-blur': 0.3 } };
    }
    out.push(x);
    if (l.id === 'buildings') {   // Umriss: das Füllmuster zeichnet keinen eigenen Rand
      out.push({ id: 'buildings-line', type: 'line', source: l.source, 'source-layer': l['source-layer'], ...(l.filter ? { filter: l.filter } : {}), ...(l.minzoom != null ? { minzoom: l.minzoom } : {}),
        layout: { 'line-join': 'miter' }, paint: { 'line-color': MED.ink, 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 0.5, 17, 1.3] } });
    }
  }
  // Muster über den Flächen (von hinten einfügen, damit die Indizes stimmen)
  for (const [i, layer] of pat.reverse()) out.splice(i, 0, layer);
  // Hügel- und Wellenzeichen unter die Beschriftung, Siedlungszeichen obenauf
  const extra = extraLayers(!!map.getSource('contours'));
  const firstText = out.findIndex((l) => l.layout?.['text-font']);
  const under = extra.filter((l) => !l.id.startsWith('med-place-')), over = extra.filter((l) => l.id.startsWith('med-place-'));
  out.splice(firstText < 0 ? out.length : firstText, 0, ...under);
  out.push(...over, ...faunaLayers());
  return out;
}

// Windrose der historischen Karte: eigene Zeichnung als SVG über der Karte (nur Zierde, aria-hidden). Norden ist oben, die Karte lässt sich nicht drehen.
function windrose(on) {
  let el = document.getElementById('windrose');
  if (!on) { if (el) el.setAttribute('hidden', ''); return; }
  if (!el) {
    const NS = 'http://www.w3.org/2000/svg';
    const mk = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); parent?.append(n); return n; };
    el = mk('svg', { id: 'windrose', class: 'windrose', viewBox: '-80 -80 160 232', 'aria-hidden': 'true', focusable: 'false' });
    const ink = MED.ink, paper = '#efe0b0', red = '#a33a22';
    const pol = (deg, r) => [Math.sin((deg * Math.PI) / 180) * r, -Math.cos((deg * Math.PI) / 180) * r];
    const pts = (a) => a.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
    // Pergamentscheibe hinter der Rose, damit sie auf dem Flächenmuster nicht untergeht
    // Eine Form: oben der Rosenkreis, unten die Tafel für Windangabe und Maßstab, mit geraden Seiten und gerundeten Ecken; doppelt gerahmt wie eine Kartusche
    const shape = (r, bottom, rc) => `M${-r},0 A${r},${r} 0 0 1 ${r},0 L${r},${bottom - rc} A${rc},${rc} 0 0 1 ${r - rc},${bottom} L${-(r - rc)},${bottom} A${rc},${rc} 0 0 1 ${-r},${bottom - rc} Z`;
    mk('path', { d: shape(76, 140, 28), fill: paper, 'fill-opacity': 0.84 }, el);
    mk('path', { d: shape(76, 140, 28), fill: 'none', stroke: ink, 'stroke-width': 1.3 }, el);
    mk('path', { d: shape(72.5, 136.5, 24.5), fill: 'none', stroke: ink, 'stroke-width': 0.5 }, el);
    mk('line', { x1: -52, y1: 98, x2: 52, y2: 98, stroke: ink, 'stroke-width': 0.5, 'stroke-opacity': 0.6 }, el);
    // Ringe und Teilstriche
    mk('circle', { r: 56, fill: 'none', stroke: ink, 'stroke-width': 1.3 }, el);
    mk('circle', { r: 52.5, fill: 'none', stroke: ink, 'stroke-width': 0.5 }, el);
    mk('circle', { r: 36, fill: 'none', stroke: ink, 'stroke-width': 0.6, 'stroke-dasharray': '2 2' }, el);
    for (let i = 0; i < 64; i++) { const [x1, y1] = pol(i * 5.625, i % 4 === 0 ? 49 : 51), [x2, y2] = pol(i * 5.625, 52.5); mk('line', { x1, y1, x2, y2, stroke: ink, 'stroke-width': i % 4 === 0 ? 0.9 : 0.5 }, el); }
    // 16 Striche der Zwischenwinde, dann Nebenrichtungen, zuletzt die vier Hauptrichtungen (zwei Hälften: dunkel und hell)
    for (let d = 22.5; d < 360; d += 45) mk('polygon', { points: pts([pol(d, 24), pol(d - 4, 6), pol(d + 4, 6)]), fill: paper, stroke: ink, 'stroke-width': 0.6 }, el);
    const kite = (deg, len, half, main) => {
      const tip = pol(deg, len), l = pol(deg - 90 + 0, half), r2 = pol(deg + 90, half), back = pol(deg + 180, half * 1.6);
      const tipN = tip, c = [0, 0];
      mk('polygon', { points: pts([tipN, [l[0], l[1]], back]), fill: main ? red : ink, stroke: ink, 'stroke-width': 0.8 }, el);
      mk('polygon', { points: pts([tipN, [r2[0], r2[1]], back]), fill: paper, stroke: ink, 'stroke-width': 0.8 }, el);
      void c;
    };
    for (const d of [45, 135, 225, 315]) kite(d, 34, 5.5, false);
    kite(90, 49, 7, false); kite(180, 49, 7, false); kite(270, 49, 7, false); kite(0, 49, 7, true);
    mk('circle', { r: 4.2, fill: red, stroke: ink, 'stroke-width': 1 }, el);
    mk('circle', { r: 1.4, fill: paper }, el);
    // Lilie am Norden: drei Blätter über dem Ring
    mk('path', { d: 'M0,-67 C-3,-64 -3,-60 0,-58.5 C3,-60 3,-64 0,-67 Z M-1.4,-58.5 C-6,-59.5 -6.5,-64.5 -3,-65 C-3.5,-62 -2.5,-60 -1.4,-58.5 Z M1.4,-58.5 C6,-59.5 6.5,-64.5 3,-65 C3.5,-62 2.5,-60 1.4,-58.5 Z', fill: red, stroke: ink, 'stroke-width': 0.5 }, el);
    for (const [t, x, y] of [['O', 63, 4.5], ['S', 0, 71], ['W', -63, 4.5]]) { const n = mk('text', { x, y, 'text-anchor': 'middle', 'font-size': 15, fill: ink, class: 'windrose-t' }, el); n.textContent = t; }
    // Windfahne: Pfeil in Strömungsrichtung (wie die Striche der Windebene), darunter die Angabe aus Modell und Ort der Rose
    const vane = mk('g', { id: 'windrose-vane', class: 'windrose-vane' }, el);
    mk('polygon', { points: '0,-54 -10,-35 0,-41 10,-35', fill: '#1f4f5a', stroke: paper, 'stroke-width': 1.6, 'stroke-linejoin': 'round' }, vane);
    mk('line', { x1: 0, y1: 38, x2: 0, y2: -38, stroke: paper, 'stroke-width': 5, 'stroke-linecap': 'round' }, vane);
    mk('line', { x1: 0, y1: 38, x2: 0, y2: -38, stroke: '#1f4f5a', 'stroke-width': 2.6, 'stroke-linecap': 'round' }, vane);
    mk('polygon', { points: '0,-52 -8,-37 0,-42 8,-37', fill: '#1f4f5a' }, vane);
    for (const y of [30, 38]) { mk('line', { x1: 0, y1: y, x2: -7, y2: y + 7, stroke: '#1f4f5a', 'stroke-width': 2.2, 'stroke-linecap': 'round' }, vane); mk('line', { x1: 0, y1: y, x2: 7, y2: y + 7, stroke: '#1f4f5a', 'stroke-width': 2.2, 'stroke-linecap': 'round' }, vane); }
    const info = mk('text', { id: 'windrose-info', x: 0, y: 91, 'text-anchor': 'middle', 'font-size': 14, fill: ink, stroke: paper, 'stroke-width': 4, 'paint-order': 'stroke', 'stroke-linejoin': 'round', class: 'windrose-t' }, el);
    info.textContent = '';
    // Maßstab als Messlatte: zwei Hälften abwechselnd in Tinte und Pergament, Länge und Beschriftung setzt windroseUpdate
    const rule = mk('g', { id: 'windrose-rule' }, el);
    mk('rect', { id: 'wr-a', x: -40, y: 105, width: 40, height: 5, fill: ink, stroke: ink, 'stroke-width': 0.8 }, rule);
    mk('rect', { id: 'wr-b', x: 0, y: 105, width: 40, height: 5, fill: paper, stroke: ink, 'stroke-width': 0.8 }, rule);
    const rl = mk('text', { id: 'wr-t', x: 0, y: 127, 'text-anchor': 'middle', 'font-size': 14, fill: ink, class: 'windrose-t' }, rule);
    rl.textContent = '';
    document.getElementById('map')?.append(el);
  }
  el.removeAttribute('hidden');
  windroseUpdate();
}
const COMPASS = ['N', 'NNO', 'NO', 'ONO', 'O', 'OSO', 'SO', 'SSO', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
// Wind am Ort der Rose: Kartenpunkt unter dem Mittelpunkt, Modellwert aus dem Windgitter (Richtung: woher er kommt; der Pfeil zeigt, wohin er weht)
function windroseUpdate() {
  const el = document.getElementById('windrose');
  if (!el || el.hasAttribute('hidden') || !mapReady || !wind) return;
  const vane = el.querySelector('#windrose-vane'), info = el.querySelector('#windrose-info');
  const r = el.getBoundingClientRect(), m = map.getContainer().getBoundingClientRect();
  const c = map.unproject([r.left + r.width * (80 / 160) - m.left, r.top + r.height * (80 / 232) - m.top]);
  // Maßstab: runde Strecke, deren Länge in der Zeichnung höchstens 96 Einheiten beträgt
  const mpp = (40075016.686 * Math.cos((c.lat * Math.PI) / 180)) / (512 * 2 ** map.getZoom()), unit = r.width / 160;
  const maxM = (96 * unit) * mpp;
  const steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000];
  const d = steps.filter((v) => v <= maxM).pop() ?? steps[0], barW = d / mpp / unit;
  el.querySelector('#wr-a').setAttribute('x', (-barW / 2).toFixed(1)); el.querySelector('#wr-a').setAttribute('width', (barW / 2).toFixed(1));
  el.querySelector('#wr-b').setAttribute('x', '0'); el.querySelector('#wr-b').setAttribute('width', (barW / 2).toFixed(1));
  el.querySelector('#wr-t').textContent = d >= 1000 ? `${d / 1000} km` : `${d} m`;
  const w = wind.sample(c.lng, c.lat);
  if (!w) { vane.setAttribute('visibility', 'hidden'); info.textContent = 'Wind: keine Daten'; return; }
  vane.removeAttribute('visibility');
  vane.setAttribute('transform', `rotate(${((w.from + 180) % 360).toFixed(1)})`);
  info.textContent = `Wind aus ${COMPASS[Math.round(w.from / 22.5) % 16]}, ${Math.round(w.speed * 3.6)} km/h`;
}

// Stil-Layer der Basiskarte unter den eigenen Ebenen; beim Wechsel Hell/Dunkel neu aufgebaut
function applyBasemap() {
  if (!basemapOk) { applyRelief(); placeRadar(); return; }
  for (const l of map.getStyle().layers) if (l.id.startsWith('bm-')) map.removeLayer(l.id);
  const med = !!state.layers.medieval;
  document.documentElement.dataset.karte = med ? 'mittelalter' : '';
  const flavor = !med && document.documentElement.dataset.ansicht === 'dunkel' ? 'dark' : 'grayscale';
  const before = baseAnchor();
  // Keine Grenzlinien (Länder, Kreise): die Karte zeigt Gelände, Gewässer, Straßen und den Radius
  // roads_shields entfällt: es braucht Sprite-Bilder, die wir nicht ausliefern; die Schilder zeichnen signLayers()
  const dark = flavor === 'dark';
  let styled = basemapLayers('basemap', med ? medFlavor() : namedFlavor(flavor), { lang: 'de' }).filter((x) => !LABEL_SKIP.test(x.id)).map(mainRoad).map(labelsAndBuildings(dark))
    .map((x) => (coreOk && (x.id === 'buildings' || x.id === 'address_label') ? { ...x, source: 'basemap-core' } : x));   // Gebäude und Hausnummern aus dem Zoom-15-Kern
  // eigene Flächen- und Geländeebenen gleich hinter dem Landnutzungs-Layer des Stils (unter Wasser, Straßen und Relief-Linien)
  const at = styled.findIndex((x) => x.id === 'landuse_park');
  styled.splice(at >= 0 ? at + 1 : 0, 0, ...landUseLayers(dark, map.hasImage('cliff-tick')));
  waterEdges(styled, dark);
  styled.push(...peakLayers(dark, map.hasImage('peak-tri')));   // Gipfel oben auf den Beschriftungen des Stils
  if (med) styled = medievalize(styled);
  if (ringOk) {   // gleiche Gebäudeebenen noch einmal aus dem Ring; Kern und Ring überlappen nicht, nichts wird doppelt gezeichnet
    const at2 = styled.map((x) => x.id).lastIndexOf('buildings-line');
    const extra = styled.filter((x) => x.id === 'buildings' || x.id === 'buildings-line').map((x) => ({ ...x, id: `${x.id}-ring`, source: 'basemap-ring' }));
    styled.splice((at2 >= 0 ? at2 : styled.findIndex((x) => x.id === 'buildings')) + 1, 0, ...extra);
  }
  if (flow) {   // Wasserbewegung (Ebene "flow")
    const fl = flow.layers({ dark, med });
    const wr = styled.findIndex((x) => x.id === 'water_river'), lab = styled.findIndex((x) => x.layout?.['text-font'] && !x.id.startsWith('land-'));
    styled.splice(wr >= 0 ? wr + 1 : lab < 0 ? styled.length : lab, 0, ...fl);   // gleich über die Gewässerlinien des Stils, unter Straßen und Beschriftung
  }
  for (const l of styled) map.addLayer({ ...l, id: `bm-${l.id}` }, before);
  if (state.signsOk) for (const l of signLayers(dark)) map.addLayer(l, before);
  for (const id of ['routes-hike-casing', 'routes-bike-casing', 'routes-hike', 'routes-bike', 'routes-hit', 'routes-label', ...INFRA_LAYER_IDS]) if (map.getLayer(id)) map.moveLayer(id, before);
  for (const id of [...NAT_LAYERS, ...HER_LAYERS]) if (map.getLayer(id)) map.moveLayer(id, before);   // Landmarken (Höhlen, Burgen …) über die neu gebauten Basislayer, sonst verdecken Flächen und Relief sie
  if (map.getLayer('air-dim')) map.moveLayer('air-dim', before);   // Verdunklung direkt über der Basiskarte, unter allen Datenebenen
  paintWater(flavor === 'dark', med);
  paintStops();
  paintNature();
  applyNatureVisibility();
  applyBaseToggles();
  applyFlow();
  flow?.refresh();
  applyRelief();
  placeRadar();
}

// Gewässer blau, damit Mosel, Sauer und Seen auch auf der grauen Basiskarte und über dem Relief sofort lesbar sind
function paintWater(dark, med) {
  const fill = med ? MED.water : dark ? '#1f4f7a' : '#8fc0e8', line = fill;   // Linie in Flächenfarbe: Mittellinie und Fläche gehen nahtlos ineinander über
  if (map.getLayer('bm-water')) map.setPaintProperty('bm-water', 'fill-color', fill);
  for (const id of ['bm-water_stream', 'bm-water_river']) if (map.getLayer(id)) map.setPaintProperty(id, 'line-color', line);
}

function applyRelief() {
  const dark = document.documentElement.dataset.ansicht === 'dunkel';
  if (reliefOk) buildRelief(map, dark, state.layers.relief, !!state.layers.medieval);
  applyLight(dark);
  fillLegend($('#relief-bar'), dark);
  applyLegend();
}

// Lichtquelle am Zeiger: nur mit Relief; die feste Schummerung wird gedämpft, damit sich beide nicht widersprechen
function applyLight(dark = document.documentElement.dataset.ansicht === 'dunkel') {
  if (!light) return;
  const on = state.layers.licht && state.layers.relief;
  const med = !!state.layers.medieval;
  const before = map.getLayer('bm-water') ? 'bm-water' : 'radius-fill';
  // Wasserglitzern über Wasserfläche und Wasserlinien (Mosel, Bäche haben dieselbe Farbe), aber unter allem, was danach kommt
  const ids = map.getStyle().layers.map((l) => l.id);
  const last = Math.max(...['bm-water', 'bm-water_stream', 'bm-water_river'].map((i) => ids.indexOf(i)));
  const beforeWater = last >= 0 && ids[last + 1] ? ids[last + 1] : 'radius-fill';
  light.setEnabled(on);
  light.build(before, beforeWater, { dark, med, waterColor: med ? MED.water : dark ? '#1f4f7a' : '#8fc0e8' });
  if (map.getLayer('relief-hill')) map.setPaintProperty('relief-hill', 'hillshade-exaggeration', on ? 0.12 : (med ? 0.5 : dark ? 0.32 : 0.42));
  const box = $('#licht-opt'); if (box) box.hidden = !on;
}

function applyLegend() {
  const box = $('#relief-legend');
  if (box) box.hidden = !(reliefOk && state.layers.relief);
}

// Höhe unter dem Zeiger (Maus) bzw. am Tippunkt (Touch), gedrosselt auf einen Abruf gleichzeitig
function wireElevation() {
  const out = $('#relief-elev');
  if (!reliefOk || !out) return;
  let busy = false, last = null;
  const show = async (ll) => {
    last = ll;
    if (busy) return;
    busy = true;
    while (last) {
      const cur = last; last = null;
      const v = state.layers.relief ? await elevationAt(cur.lng, cur.lat) : null;
      out.textContent = v == null ? 'Höhe: –' : `Höhe: ${v} m ü. NN`;
    }
    busy = false;
  };
  map.on('mousemove', (e) => show(e.lngLat));
  map.on('click', (e) => show(e.lngLat));
}

async function recolor() {
  if (!mapReady) return;
  const c = palette();
  const medOn = !!state.layers.medieval;
  if (state.iconsOk) {   // Umriss der Flugzeuge hängt vom Hintergrund ab; historische Karte: eigene Farben, Pergamentsaum und gezeichnete Zeichen
    setIconStyle(medOn ? MED_ICON_STYLE : null);
    try { await registerIcons(map, medOn ? MED_COLORS : c); } finally { setIconStyle(null); }
    if (medOn) registerMedieval(map, MED_COLORS);
  }
  map.setPaintProperty('bg', 'background-color', c.bg);
  applyBasemap();
  for (const id of ['ev-fill', 'ev-outline', 'ev-line', 'ev-point', 'ev-dot-w']) {
    map.setPaintProperty(id, id === 'ev-fill' ? 'fill-color' : id.startsWith('ev-point') || id === 'ev-dot-w' ? 'circle-color' : 'line-color', sevColor(c));
  }
  map.setPaintProperty('st-circle', 'circle-stroke-color', c.info);
  map.setPaintProperty('air-circle', 'circle-stroke-color', sevColor(c));
  map.setPaintProperty('env-circle', 'circle-stroke-color', sevColor(c));
  fillTempLegend();
  const wb = $('#wind-bar'); if (wb) fillWindLegend(wb);
  const wbl = $('#wind-bar-low'); if (wbl) fillWindLegend(wbl, undefined, true);   // Windpalette folgt der Ansicht
}

function applyLayerFilters() {
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

// Schalter für Teile der Basiskarte: Landnutzung, Klippen und Steinbrüche, Gebäude, Straßenschilder (Layer heißen bm-*)
// Straßenarten der Protomaps-Grundkarte (Ebenen roads_*, auch Brücken und Tunnel, mit Rand): je Art ein Schalter
const ROAD_KEYS = [
  ['roadNames', /^bm-roads_(labels_|shields|oneway)/],
  ['rail', /^bm-roads_(?:(?:bridges|tunnels)_)?rail/],
  ['roadHw', /^bm-roads_(?:(?:bridges|tunnels)_)?(?:highway|link)(?:_|$)/],
  ['roadMain', /^bm-roads_(?:(?:bridges|tunnels)_)?major(?:_|$)/],
  ['roadMid', /^bm-roads_(?:(?:bridges|tunnels)_)?medium(?:_|$)/],
  ['roadMinor', /^bm-roads_(?:(?:bridges|tunnels)_)?minor(?:_|$)/],
  ['roadPath', /^bm-roads_(?:(?:bridges|tunnels)_)?other(?:_|$)/],
];
const roadKey = (id) => (id.startsWith('bm-roads_') ? ROAD_KEYS.find(([, rx]) => rx.test(id))?.[0] ?? null : null);

// Flächenklasse → Schalter (Bewuchs); Friedhofsgrün läuft mit den Wiesen
const LAND_KEY = { forest: 'vegForest', meadow: 'vegMeadow', grass: 'vegMeadow', cemetery: 'vegMeadow', scrub: 'vegScrub', heath: 'vegScrub', farmland: 'vegField', allotment: 'vegField',
  orchard: 'vegVine', vineyard: 'vegVine', wetland: 'vegWet', rock: 'vegRock', sand: 'vegRock' };
const BOUND_KEY = { country: 'bndCountry', region: 'bndRegion', county: 'bndCounty', local: 'bndLocal' };
function applyBaseToggles() {
  if (!mapReady || !basemapOk) return;
  const on = (v) => (v ? 'visible' : 'none');
  for (const l of map.getStyle().layers) {
    let key = null;
    if (l.id.startsWith('bm-flow-')) key = 'flow';
    else if (/^bm-land-(cliff|quarry)/.test(l.id)) key = 'cliffs';
    else if (/^bm-land-protected-nr-/.test(l.id)) key = 'protNature';
    else if (/^bm-land-protected-np-/.test(l.id)) key = 'protPark';
    else if (/^bm-land-military-/.test(l.id)) key = 'protMil';
    else if (/^bm-land-bound-/.test(l.id)) key = BOUND_KEY[l.id.slice('bm-land-bound-'.length)];
    else if (l.id.startsWith('bm-land-')) key = LAND_KEY[l.id.slice('bm-land-'.length).replace(/-pat$/, '')];
    else if (/^bm-buildings(-line)?(-ring)?$/.test(l.id)) key = 'buildings';
    else if (l.id.startsWith('bm-sign-')) key = 'signs';
    else key = roadKey(l.id);
    if (key) map.setLayoutProperty(l.id, 'visibility', on(state.layers[key]));
  }
}

function pushMapData() {
  if (!mapReady) return;
  const shown = state.events.filter((f) => f.properties.type !== 'aircraft').map((f) => ({ ...f, properties: { ...f.properties, icon: iconFor(f.properties), lvl: trafficLevel(f.properties) ?? undefined } }));
  map.getSource('events').setData({ type: 'FeatureCollection', features: shown });
  pushAir();
  const feats = (state.gew?.stations ?? []).filter((s) => s.latest).map((s) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
    properties: { rank: stationRank(s, state.net), name: s.name, water: s.water, value: s.latest.value, unit: s.latest.unit, ts: s.latest.ts, state: s.latest.state, trend: s.trend_cm_3h, attribution: s.attribution, operator: s.meta?.operator },
  }));
  map.getSource('stations').setData({ type: 'FeatureCollection', features: feats });
  map.getSource('env').setData({ type: 'FeatureCollection', features: envFeatures() });
  map.getSource('tank').setData({ type: 'FeatureCollection', features: tankFeatures() });
}

// Tankstellen: nur Marke, Ort, Koordinaten und Preise (keine Straße, keine Hausnummer); Preise als Text, weil MapLibre keine Objekte in Eigenschaften führt
function tankFeatures() {
  const de = (state.fuel?.stations ?? []).filter((r) => Number.isFinite(r.lat) && Number.isFinite(r.lon)).map((r) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
    properties: { name: r.name, ort: r.ort ?? '', km: Math.round(r.distance_km ?? 0), prices: JSON.stringify(r.prices), lu: false,
      label: (r.prices.e10 ?? r.prices.e5 ?? r.prices.diesel) ? EUR_SHORT((r.prices.e10 ?? r.prices.e5 ?? r.prices.diesel).value) : '' },
  }));
  // Luxemburg: Standorte aus OpenStreetMap, dazu der amtliche Höchstpreis (gleich für alle); die Beschriftung trägt ein "≤"
  const lu = state.fuel?.lu, mx = lu?.max_prices ?? {};
  const luFeatures = !mx.sp95 && !mx.diesel ? [] : (lu?.stations ?? []).map((r) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
    properties: { name: r.name, ort: '', km: Math.round(r.distance_km ?? 0), prices: JSON.stringify(mx), lu: true,
      label: '' },   // gleicher Höchstpreis an jeder Station: kein Preis auf der Karte, er steht im Popup
  }));
  return [...de, ...luFeatures];
}
const fmtDay = (d) => String(d ?? '').split('-').reverse().join('.');   // 2026-10-06 → 06.10.2026
const EUR_SHORT = (v) => Number(v).toFixed(3).replace('.', ',');

// ------------------------------------------------------------------ Luft, Strahlung, Radar
// Stufe je Station: Strahlung nach eigener Orientierung (0,3 / 1,0 µSv/h), Luft nach dem Index der Quelle (3 = schlecht, 4 = sehr schlecht)
function envLevel(s) {
  if (s.kind === 'weather') return 'info';
  if (s.kind === 'radiation') { const v = s.values.odl?.value ?? 0; return v >= 1 ? 'warning' : v >= 0.3 ? 'notice' : 'info'; }
  const q = s.values.lqi?.value ?? 0;
  return q >= 4 ? 'warning' : q >= 3 ? 'notice' : 'info';
}
const ENV_LABEL = { odl: 'Ortsdosisleistung', lqi: 'Luftqualitätsindex', NO2: 'Stickstoffdioxid', PM10: 'Feinstaub PM10', 'PM2.5': 'Feinstaub PM2,5', O3: 'Ozon', temperature: 'Temperatur', relative_humidity: 'Luftfeuchte', pressure_msl: 'Luftdruck (auf Meereshöhe)', wind_speed_10: 'Wind', wind_gust_speed_10: 'Böen', precipitation_60: 'Niederschlag (60 min)' };
function envText(s) {
  return Object.entries(s.values).map(([k, v]) => `${ENV_LABEL[k] ?? k}: ${k === 'lqi' ? (v.state ?? v.value) : `${String(v.value).replace('.', ',')} ${v.unit}`}`);
}
function envFeatures() {
  // Strahlung erscheint auf der Karte erst ab dem Orientierungswert (0,3 µSv/h); darunter nur in der Liste
  return (state.env?.stations ?? []).filter((s) => s.kind !== 'radiation' || envLevel(s) !== 'info').map((s) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
    properties: { name: s.name, kind: s.kind, icon: s.kind === 'radiation' ? 'strahlung' : s.kind === 'weather' ? 'temperatur' : 'luft', severity: envLevel(s),
      label: s.kind === 'weather' && s.values.temperature ? `${String(Math.round(s.values.temperature.value))}°` : '', lines: JSON.stringify(envText(s)),
      ts: Object.values(s.values)[0]?.ts, attribution: s.attribution,
      ...(s.kind === 'weather' && Number.isFinite(s.values.temperature?.value) ? { tclass: tempClass(s.values.temperature.value) } : {}) },
  }));
}

// Radar: ein Bild vom eigenen Server (radar.png), vom Collector aus dem DWD-WMS geholt; hier wird nur angezeigt
function applyRadar() {
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
function applyRadarVisibility() {
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
function trackLegendBottom() {
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
function fillTempLegend() {
  const bar = $('#temp-bar'); if (!bar) return;
  const stops = TEMP_COLOURS.map((c, k) => [TEMP_MIN + TEMP_STEP * k, c]).filter(([t]) => t >= -23 && t <= 43);
  bar.style.background = `linear-gradient(to right, ${stops.map(([t, c]) => `${c} ${(((t + 20) / 60) * 100).toFixed(1)}%`).join(', ')})`;
}
function applyLegends() {
  updateLegend($('#map-legend'), {
    radar: state.layers.radar && !!state.radar?.time, wind: (state.layers.wind || state.layers.windlow) && !!state.wind?.grid, windlow: state.layers.windlow && !!state.terrain,
    flow: state.layers.flow && basemapOk, blitz: state.layers.blitz && !!state.blitz?.time, wxst: state.layers.wxst && !!state.env?.stations?.some((x) => x.kind === 'weather'), tank: state.layers.tank && !!state.fuel?.stations?.length, traffic: state.layers.traffic || state.layers.transit, air: state.layers.air, medieval: state.layers.medieval,
  });
  if (state.layers.medieval) fillMedLegend(document.querySelector('#map-legend [data-legend="medieval"]'));
}
// Wind: Gitter (wind.json) vom eigenen Server, die Partikel rechnet wind.js im Browser; Quelle und Stand stehen im Ebenenmenü
// Wasserbewegung: Schalter, Legende, Windzeile (Wind der Kartenmitte aus dem Modell)
function applyFlow() { flow?.setEnabled(state.layers.flow && basemapOk); applyLegends(); }
function showFlowWind(w) {
  const el = $('#flow-wind'); if (!el) return;
  const txt = { calm: 'Flaute, die Seen liegen glatt', light: 'schwacher Wind, feine Wellen', moderate: 'mäßiger Wind, deutliche Wellen', strong: 'kräftiger Wind, dichte Wellen' };
  el.textContent = w ? `Wind jetzt (Modell, Kartenmitte): aus ${COMPASS[Math.round(w.from / 22.5) % 16]}, ${Math.round(w.speed * 3.6)} km/h, ${txt[w.cls]}.` : state.layers.flow ? 'Kein Windmodell geladen: Stillgewässer bleiben glatt.' : '';
}
function applyWind() {
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
function placeRadar() {
  if (mapReady && map.getLayer('radar')) map.moveLayer('radar', baseAnchor());
  if (mapReady && map.getLayer('blitz')) map.moveLayer('blitz', baseAnchor()); // Blitze über dem Regenradar
}

// Blitze (EUMETSAT MTG-LI): fertig eingefärbtes Bild vom eigenen Server (blitz.png), Alter steckt in der Farbe; leerer Himmel wird gesagt
function applyBlitz() {
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
function applyBlitzVisibility() {
  applyLegends();
  if (mapReady && map.getLayer('blitz')) map.setLayoutProperty('blitz', 'visibility', state.layers.blitz ? 'visible' : 'none');
  const note = $('#blitznote'), b = state.blitz;
  if (!note) return;
  if (!state.layers.blitz || !b?.time) { note.textContent = ''; return; }
  const n = Object.values(b.counts ?? {}).reduce((a, c) => a + c, 0);
  note.textContent = `Stand ${fmtTime(b.time)} · ${n ? `${n} Zellen in ${b.window_min} min` : `keine Blitze in ${b.window_min} min`}`;
}

// Bahnhöfe und Haltestellen der Schiene (GTFS Luxemburg und Deutschland, haltestellen.json): kleine Punkte mit Namen ab Zoom 10
const STOP_STYLE = { light: ['#ffffff', '#1f3a5f', '#1f3a5f', 'rgba(255,255,255,0.95)'], dark: ['#1f3a5f', '#e6eefc', '#e6eefc', 'rgba(16,16,16,0.95)'] };
function stopFeatures() {
  return { type: 'FeatureCollection', features: (state.stops?.stops ?? []).map((s) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] }, properties: { name: s.name, mode: s.mode } })) };
}
function paintStops() {
  if (!mapReady || !map.getLayer('stops-dot')) return;
  const [fill, edge, text, halo] = STOP_STYLE[document.documentElement.dataset.ansicht === 'dunkel' ? 'dark' : 'light'];
  map.setPaintProperty('stops-label', 'text-color', text); map.setPaintProperty('stops-label', 'text-halo-color', halo);
}
// Infrastruktur aus OpenStreetMap (Windräder, Ladesäulen, Notfallpunkte). Eine Quelle, eine Zeichen- und eine Namensebene; welche Arten stehen, regelt der Filter.
let infraKey = '';
function ensureSakral() {   // Kirchen, Kapellen, Wegkreuze gibt es nur auf der Karte um 1450: Datei erst dann laden
  if (!state.layers.medieval || state.sakral || state.sakralLoading) return;
  state.sakralLoading = true;
  getJSON('data/sakral.json').then((j) => { state.sakral = j; applyInfra(); }).catch(() => {}).finally(() => { state.sakralLoading = false; });
}
const INFRA_GROUP = { church: 'herChurch', chapel: 'herChapel', cross: 'herCross', shrine: 'herCross', watermill: 'herMill', windmill: 'herMill', ford: 'herFord', border: 'herBorder', gallows: 'herGallows', well: 'herWell', wind: 'wturb', charging: 'charge', aed: 'emerg', fire_station: 'emerg', hospital: 'emerg',
  weir: 'wehr', lock: 'wehr', ferry: 'wehr', bridge: 'bruecke', tunnel: 'bruecke', picnic: 'rast', shelter: 'rast', bathing: 'rast', school: 'civic', townhall: 'civic', cemetery: 'cemetery' };
// Ebene je Art: dichte Arten (Feuerwachen, Brücken, Rastplätze) erst bei größerem Zoom
const INFRA_LAYERS = [['inf-sym', 9.5], ['inf-fire', 11], ['inf-sac', 11.5], ['inf-wasser', 11], ['inf-brueck', 12.5], ['inf-rast', 12.5], ['inf-civ', 11.5]];
const INFRA_LAYER_IDS = INFRA_LAYERS.map(([id]) => id);
const INFRA_LAYER_OF = { fire_station: 'inf-fire', church: 'inf-sac', chapel: 'inf-sac', cross: 'inf-sac', shrine: 'inf-sac', watermill: 'inf-sac', windmill: 'inf-sac', ford: 'inf-sac', border: 'inf-sac', gallows: 'inf-sac', well: 'inf-sac', weir: 'inf-wasser', lock: 'inf-wasser', ferry: 'inf-wasser',
  bridge: 'inf-brueck', tunnel: 'inf-brueck', picnic: 'inf-rast', shelter: 'inf-rast', bathing: 'inf-rast', school: 'inf-civ', townhall: 'inf-civ', cemetery: 'inf-civ' };
function infraFeaturesOn() {
  const med = !!state.layers.medieval;
  const group = (k) => (med && (k === 'ferry' || k === 'bridge') ? 'herFord' : INFRA_GROUP[k]);      // um 1450: Fähren und alte Brücken gehören zum Erbe, nicht zu Wehr/Brücke
  return Object.keys(INFRA_GROUP).filter((k) => state.layers[group(k)] && (med ? INFRA_MEDIEVAL.has(k) : !SACRAL_KINDS.includes(k)));
}
function applyInfra() {
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
const ROUTE_COLOR = { hike: '#c2410c', bike: '#6d28d9' };
function routeFeatures() {
  return { type: 'FeatureCollection', features: (state.routen?.items ?? []).map((r) => ({ type: 'Feature', geometry: { type: 'MultiLineString', coordinates: r.lines },
    properties: { kind: r.kind, name: r.name, ref: r.ref || '', network: r.network || '', label: r.ref && !r.name.includes(r.ref) ? `${r.name} (${r.ref})` : r.name } })) };
}
function applyRoutes() {
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
function applyRoutesVisibility() {
  if (!mapReady || !map.getLayer('routes-hit')) return;
  const med = !!state.layers.medieval, kinds = ['hike', 'bike'].filter((k) => state.layers[k] && !med);
  for (const k of ['hike', 'bike']) for (const id of [`routes-${k}-casing`, `routes-${k}`]) map.setLayoutProperty(id, 'visibility', kinds.includes(k) ? 'visible' : 'none');
  const f = ['in', ['get', 'kind'], ['literal', kinds]];
  for (const id of ['routes-hit', 'routes-label']) { map.setLayoutProperty(id, 'visibility', kinds.length ? 'visible' : 'none'); map.setFilter(id, f); }
}
function applyInfraVisibility() {
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

function applyStops() {
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
function applyStopsVisibility() {
  if (!mapReady) return;
  for (const id of ['stops-dot', 'stops-label']) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', state.layers.stops ? 'visible' : 'none');
}

// Natürliche Landmarken. Gipfel (mit Höhe) stammen aus den eigenen Kacheln (pois/peak), Höhlen, Wasserfälle, Quellen, Aussichtspunkte,
// Felsen und Vulkane aus landmarks.json (OpenStreetMap über Overpass, wöchentlich). Jeweils nur Name, Höhe, Ort; nichts Personenbezogenes.
const NATURE_COLOR = { peak: '#7a5a2e', cave: '#4b3a2c', waterfall: '#1f6fb5', viewpoint: '#8a3fb0', spring: '#12857f', rock: '#8c6b32', volcano: '#c0401f' };
const NAT_LAYERS = ['nat-t1', 'nat-t2', 'nat-t3', 'nat-t4'];
const HER_LAYERS = ['her-t1', 'her-t2'];
const HERITAGE_KINDS = ['castle', 'ruins', 'archaeological', 'monastery', 'building'];
const NATURE_WORD = { cave: ['Höhle', 'höhl'], waterfall: ['Wasserfall', 'wasserf'], viewpoint: ['Aussicht', 'aussicht|blick'], spring: ['Quelle', 'quell|born'], rock: ['Fels', 'fels|stein|kanzel'], volcano: ['Vulkan', 'vulkan'],
  castle: ['Burg', 'burg|schloss|festung|fort|turm|hof'], ruins: ['Ruine', 'ruine|burg|schloss|turm'], archaeological: ['Fundstelle', 'römisch|villa|kastell|tempel|grab|ring|wall|fundstelle|ausgrab|kelt|hügel'],
  monastery: ['Kloster', 'kloster|abtei|stift|kartause|priorat'], building: ['', '.'] };
const natureLabel = (kind, name) => {
  const [word, stem] = NATURE_WORD[kind] ?? [kind, kind];
  if (!name) return word;
  if (!word) return name;
  return new RegExp(stem, 'i').test(name) ? name : `${word} ${name}`;
};
const peakLabel = ['case', ['has', 'elevation'], ['concat', ['get', 'name'], ' ', ['to-string', ['get', 'elevation']], ' m'], ['get', 'name']];
function peakLayers(dark, icon) {
  const halo = HALO[dark ? 'dark' : 'light'], ink = dark ? '#e9d3ab' : '#5a3f17';
  return [
    ...(icon ? [{ id: 'nat-peak-sym', type: 'symbol', source: 'basemap', 'source-layer': 'pois', minzoom: 11, filter: ['all', ['==', 'kind', 'peak'], ['has', 'name']],
      layout: { 'icon-image': 'peak-tri', 'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.6, 15, 0.9], 'icon-allow-overlap': false,
        'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'elevation'], 0]] },
      paint: { 'icon-color': NATURE_COLOR.peak, 'icon-halo-color': halo, 'icon-halo-width': 1.2 } }] : []),
    { id: 'nat-peak-label', type: 'symbol', source: 'basemap', 'source-layer': 'pois', minzoom: 12, filter: ['all', ['==', 'kind', 'peak'], ['has', 'name']],
      layout: { 'text-field': peakLabel, 'text-font': ['Noto Sans Regular'], 'text-size': 11, 'text-offset': [0, 0.8], 'text-anchor': 'top', 'text-max-width': 9,
        'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'elevation'], 0]] },
      paint: { 'text-color': ink, 'text-halo-color': halo, 'text-halo-width': 1.8, 'text-halo-blur': 0.3 } },
  ];
}
function natureFeatures() {
  return { type: 'FeatureCollection', features: (state.landmarks?.items ?? []).map((i) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [i.lon, i.lat] },
    properties: { kind: i.kind, label: natureLabel(i.kind, i.name), named: i.name ? 1 : 0, ele: i.ele ?? null } })) };
}
function paintNature() {
  if (!mapReady || !map.getLayer('nat-t1')) return;
  const dark = document.documentElement.dataset.ansicht === 'dunkel';
  for (const id of [...NAT_LAYERS, ...HER_LAYERS]) {
    if (!map.getLayer(id)) continue;
    map.setPaintProperty(id, 'text-halo-color', HALO[dark ? 'dark' : 'light']);
    map.setPaintProperty(id, 'text-color', dark ? '#f1f1f1' : '#1c1c1c');
  }
  applyNatureVisibility();   // historische Karte überschreibt Schrift und Zeichen der Kulturebene
}
function applyNature() {
  if (!mapReady || !state.landmarks) return;
  const src = map.getSource('landmarks');
  if (src) src.setData(natureFeatures());
  else {
    map.addSource('landmarks', { type: 'geojson', data: natureFeatures() });
    // Stufen nach Bedeutung, damit die Karte nicht mit Punkten zuläuft: Höhlen, Wasserfälle, Felsen, Vulkane früh; benannte Aussichten
    // später; Quellen (400) ab Zoom 13,5; unbenannte Aussichtspunkte (die meisten) erst ganz nah. Überlappende Symbole entfallen von selbst.
    const tiers = [
      ['nat-t1', 10.5, ['in', ['get', 'kind'], ['literal', ['cave', 'waterfall', 'rock', 'volcano']]], 4],
      ['nat-t2', 12.5, ['all', ['==', ['get', 'kind'], 'viewpoint'], ['==', ['get', 'named'], 1]], 3],
      ['nat-t3', 13.5, ['==', ['get', 'kind'], 'spring'], 2],
      ['nat-t4', 14.5, ['all', ['==', ['get', 'kind'], 'viewpoint'], ['==', ['get', 'named'], 0]], 1],
      // Kultur und Geschichte: Burgen, Ruinen, Ausgrabungen, Klöster früh; historische Gebäude (viele kleine) ab Zoom 12,5
      ['her-t1', 10.5, ['in', ['get', 'kind'], ['literal', ['castle', 'ruins', 'archaeological', 'monastery']]], 4],
      ['her-t2', 12.5, ['==', ['get', 'kind'], 'building'], 2],
    ];
    for (const [id, minzoom, filter, prio] of tiers) {
      map.addLayer({ id, type: 'symbol', source: 'landmarks', minzoom, filter,
        layout: { 'icon-image': ['concat', 'nat-', ['get', 'kind']], 'icon-size': ['interpolate', ['linear'], ['zoom'], 10, 0.7, 15, 1],
          'icon-allow-overlap': false, 'icon-padding': 6, 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 11,
          'text-offset': [0, 1.2], 'text-anchor': 'top', 'text-max-width': 9, 'text-optional': true, 'text-padding': 4,
          'symbol-sort-key': ['-', 0, ['+', prio, ['case', ['==', ['get', 'named'], 1], 1, 0]]] },
        paint: { 'text-color': '#1c1c1c', 'text-halo-color': '#fff', 'text-halo-width': 1.8, 'text-halo-blur': 0.3,
          'text-opacity': ['step', ['zoom'], 0, 12.5, 1] } }, 'radius-fill');
    }
  }
  paintNature();
  applyNatureVisibility();
}
function applyNatureVisibility() {
  if (!mapReady) return;
  for (const id of [...NAT_LAYERS, 'bm-nat-peak-sym', 'bm-nat-peak-label']) {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', state.layers.nature ? 'visible' : 'none');
  }
  const med = !!state.layers.medieval;
  for (const id of NAT_LAYERS) {
    if (!map.getLayer(id)) continue;
    map.setLayoutProperty(id, 'icon-image', ['concat', med ? 'med-' : 'nat-', ['get', 'kind']]);
    map.setLayoutProperty(id, 'text-font', [med ? 'Grenze Gotisch Regular' : 'Noto Sans Regular']);
    map.setLayoutProperty(id, 'text-size', med ? 13 : 11);
    if (med) { map.setPaintProperty(id, 'text-color', MED.ink); map.setPaintProperty(id, 'text-halo-color', MED.halo); }
  }
  // Kultur: je Art ein Schalter; her-t1 (Burgen, Ruinen, Fundstellen, Klöster) filtert nach den eingeschalteten Arten, her-t2 sind die historischen Gebäude
  const herKinds = [...(state.layers.herCastle ? ['castle', 'ruins'] : []), ...(state.layers.herArch ? ['archaeological'] : []), ...(state.layers.herMonastery ? ['monastery'] : [])];
  if (map.getLayer('her-t1')) map.setFilter('her-t1', herKinds.length ? ['in', ['get', 'kind'], ['literal', herKinds]] : ['==', 1, 0]);
  for (const id of HER_LAYERS) {
    if (!map.getLayer(id)) continue;
    map.setLayoutProperty(id, 'visibility', (id === 'her-t1' ? herKinds.length > 0 : state.layers.herBuilding) ? 'visible' : 'none');
    // historische Karte: eigene Bildzeichen, Schrift und Tinte statt Plaketten
    map.setLayoutProperty(id, 'icon-image', ['concat', med ? 'med-' : 'nat-', ['get', 'kind']]);
    map.setLayoutProperty(id, 'text-font', [med ? 'Grenze Gotisch Regular' : 'Noto Sans Regular']);
    map.setLayoutProperty(id, 'text-size', med ? 13 : 11);
    map.setPaintProperty(id, 'text-color', med ? MED.ink : '#1c1c1c');
    map.setPaintProperty(id, 'text-halo-color', med ? MED.halo : '#fff');
  }
}

// Flugzeuge zwischen zwei Abrufen weiterrücken lassen; Positionen stammen aus aircraft.json, nichts wird gemerkt
function pushAir() {
  if (!mapReady) return;
  const now = Date.now();
  const feats = state.layers.air
    ? windowFilter(state.airRaw, 'now', now).map((f) => {
        const p = f.properties, dt = Math.min(45, (now - new Date(p.fetched_at).getTime()) / 1000);
        const [lon, lat] = reduceMotion ? f.geometry.coordinates : advance(f.geometry.coordinates[0], f.geometry.coordinates[1], p.attrs?.track, p.attrs?.speed_kmh, dt);
        const klass = p.attrs?.klass ?? 'civil';
        return { type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties: { ...p, track: p.attrs?.track ?? 0, klass, icon: 'flug', img: AIR_IMG[klass] ?? 'plane-' } };
      })
    : [];
  map.getSource('air').setData({ type: 'FeatureCollection', features: feats });
  sweep?.update(state.layers.air, feats.map((f) => ({ id: f.properties.id, lng: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], mil: f.properties.klass.startsWith('mil') })));
  const note = $('#airnote');
  if (note) {
    if (!state.layers.air) note.textContent = '';
    else if (!state.airAt) note.textContent = 'lädt …';
    else {
      const age = Math.round((now - state.airAt) / 1000), newest = Math.max(0, ...state.airRaw.map((f) => new Date(f.properties.fetched_at).getTime()));
      const dataAge = newest ? Math.round((now - newest) / 1000) : null;
      note.textContent = dataAge === null ? `keine Flugzeuge im Radius (geprüft vor ${age} s)` : dataAge > 90 ? `veraltet (Stand vor ${dataAge} s)` : `live, Stand vor ${dataAge} s`;
    }
  }
}

async function refreshAir() {
  if (!state.layers.air || document.hidden) return;
  try {
    const d = await getJSON('data/aircraft.json');
    state.airRaw = d.features ?? [];
    state.airAt = Date.now();
    renderAir();
  } catch { /* letzter Stand bleibt; die Punkte laufen selbst ab (valid_to) */ }
}

function showPopup(p, kind, lngLat) {
  const box = h('div', { class: 'pop' });
  if (kind === 'station') {
    box.append(h('h3', {}, h('span', { class: 'ico ico-pegel', 'aria-hidden': 'true' }), `Pegel ${p.name} (${p.water ?? '–'})`),
      h('p', {}, `${p.value} ${p.unit}`, p.trend !== undefined && p.trend !== 'null' ? ` · ${trendText(Number(p.trend))}` : ''),
      h('p', { class: 'k' }, `Messung ${fmtDateTime(p.ts)} · Zustand laut Quelle: ${p.state ?? '–'}`),
      h('p', { class: 'k' }, (p.attribution ?? state.gew?.source?.attribution ?? '') + (p.operator ? ` · Betreiber: ${p.operator}` : '')));
  } else if (kind === 'tank') {
    const prices = JSON.parse(p.prices);
    const isLu = p.lu === true || p.lu === 'true';
    const rows = (isLu ? [['sp95', 'Super 95'], ['sp98', 'Super 98'], ['diesel', 'Diesel']] : [['e5', 'Super E5'], ['e10', 'Super E10'], ['diesel', 'Diesel']]).filter(([k]) => prices[k]);
    box.append(h('h3', {}, h('span', { class: 'ico ico-tanken', 'aria-hidden': 'true' }), p.name),
      h('p', { class: 'k' }, `${p.ort ? `${p.ort} · ` : ''}${p.km} km von Irrel${isLu ? ' · Luxemburg' : ''}`));
    if (isLu) box.append(h('p', {}, h('strong', {}, 'Höchstpreis, nicht Stationspreis.'), ' Der Staat setzt den Höchstpreis für ganz Luxemburg fest; diese Station kann darunter liegen.'));
    box.append(h('table', { class: 'pop-prices' }, h('caption', { class: 'sr-only' }, `${isLu ? 'Amtliche Höchstpreise' : 'Aktuelle Preise'} ${p.name}`),
      h('tbody', {}, ...rows.map(([k, label]) => h('tr', {}, h('th', { scope: 'row' }, label), h('td', {}, `${isLu ? '≤ ' : ''}${EUR_SHORT(prices[k].value)} €`),
        h('td', { class: 'muted small' }, isLu ? `ab ${fmtDay(prices[k].valid_from)}` : ageEl(prices[k].ts)))))));
    box.append(isLu
      ? h('p', { class: 'k' }, `Preise: ${state.fuel?.lu?.max_source?.attribution ?? 'STATEC / LUSTAT, CC0'} · Standort: ${state.fuel?.lu?.stations_source?.attribution ?? '© OpenStreetMap-Mitwirkende (ODbL)'}`)
      : h('p', { class: 'k' }, `${state.fuel?.source?.attribution ?? 'Tankerkönig (CC BY 4.0)'} · Preise ohne Gewähr, Abruf `, ageEl(state.fuel?.source?.last_success)));
  } else if (kind === 'route') {
    box.append(h('h3', {}, p.name), h('p', {}, p.kind === 'bike' ? 'Radroute' : 'Wanderroute', p.ref ? ` ${p.ref}` : '', p.network ? ` · ${({ iwn: 'international', nwn: 'national', rwn: 'regional', icn: 'international', ncn: 'national', rcn: 'regional' })[p.network] ?? p.network}` : ''),
      h('p', { class: 'k' }, `${state.routen?.source?.attribution ?? '© OpenStreetMap-Mitwirkende (ODbL)'} · Stand `, ageEl(state.routen?.source?.last_success)),
      h('p', { class: 'k' }, 'Ehrenamtlich gepflegt; Sperrungen und Umleitungen zeigt die Karte nicht. Maßgeblich ist die Wegweisung vor Ort.'));
  } else if (kind === 'infra') {
    box.append(h('h3', {}, infraText(p)),
      h('p', { class: 'k' }, `${state.infra?.source?.attribution ?? '© OpenStreetMap-Mitwirkende (ODbL)'} · Stand `, ageEl(state.infra?.source?.last_success)),
      h('p', { class: 'k' }, 'Ehrenamtlich gepflegt, ohne Gewähr; im Notfall 112.'));
  } else if (kind === 'env') {
    box.append(h('h3', {}, h('span', { class: `ico ico-${p.icon}`, 'aria-hidden': 'true' }), `${p.kind === 'radiation' ? 'Strahlung' : p.kind === 'weather' ? 'Wetterstation' : 'Luft'}: ${p.name}`),
      ...(p.kind === 'weather' ? [] : [h('p', {}, sevBadge(p.severity))]));
    for (const line of JSON.parse(p.lines)) box.append(h('p', {}, line));
    box.append(h('p', { class: 'k' }, `Messung ${fmtDateTime(p.ts)} · ${p.attribution ?? ''}`));
  } else {
    box.append(h('h3', {}, h('span', { class: `ico ico-${p.icon ?? 'warnung'}`, 'aria-hidden': 'true' }), p.title), h('p', {}, sevBadge(p.severity), ' ', TYPE_LABEL[p.type] ?? p.type));
    if (p.summary) box.append(h('p', {}, p.summary.length > 320 ? `${p.summary.slice(0, 319)}…` : p.summary));
    box.append(h('p', { class: 'k' }, `${p.distance_km} km von Irrel · gültig ab ${fmtDateTime(p.valid_from)}${p.valid_to ? ` bis ${fmtDateTime(p.valid_to)}` : ''}`));
    if (Number(p.confidence) < 1) box.append(h('p', { class: 'k' }, `Ortsgenauigkeit eingeschränkt (Konfidenz ${p.confidence})`));
    box.append(h('p', { class: 'k' }, `${p.attribution ?? p.source_name} · Abruf `, ageEl(p.fetched_at), p.raw_ref ? [' · ', link(p.raw_ref, 'Original')] : ''));
  }
  popup.setLngLat(lngLat).setDOMContent(box).addTo(map);
}

// ------------------------------------------------------------------ Bausteine
const trendText = (v) => (v === null || Number.isNaN(v) ? 'Trend unbekannt' : v > 0.4 ? `steigend (+${v} cm/3 Std.)` : v < -0.4 ? `fallend (${v} cm/3 Std.)` : 'gleichbleibend');

function sourceLine(srcRaw, extra) {
  const src = srcRaw ? deriveStatus(srcRaw, Date.now()) : null;
  if (!src) return h('div', { class: 'card-f' }, 'Quellenstatus unbekannt');
  const kids = [h('span', {}, src.attribution), h('span', {}, 'Abruf ', ageEl(src.last_success))];
  if (['down', 'stale'].includes(src.status)) {
    kids.push(h('span', { class: 'stale-note' },
      src.status === 'down' ? `Quelle nicht erreichbar seit ${fmtDateTime(src.failing_since ?? src.last_attempt)}` : 'Daten veraltet'));
  }
  if (extra) kids.push(extra);
  return h('div', { class: 'card-f' }, kids);
}

// ------------------------------------------------------------------ Warnband
function renderWarnband(warn, statuses) {
  const band = $('#warnband'), box = $('#warnband-in');
  if (!band || !box) return; // Warnband ist aus der Seite genommen, kommt später in anderer Form
  box.replaceChildren();
  const gen = state.meta?.generated_at;
  const stale = exportStale(gen, Date.now());
  // Ist der Export selbst veraltet, sind die Einzelzustände nur Folgen davon: eine Meldung genügt
  const bad = stale ? [] : statuses.filter((s) => ['down', 'stale', 'pending'].includes(s.status));
  const uncertain = stale || bad.length > 0;
  const worst = warn.reduce((m, f) => Math.max(m, SEV[f.properties.severity].rank), -1);
  const level = worst >= 3 ? 'critical' : worst === 2 ? 'warning' : worst === 1 ? 'notice' : 'none';
  band.dataset.level = level !== 'none' ? level : uncertain ? 'down' : 'none';

  if (stale) {
    box.append(h('strong', {}, `Datenstand veraltet: letzter Export ${fmtDateTime(gen)}`),
      h('span', {}, 'Die Sammelstelle liefert gerade nichts Neues. Gezeigt wird der letzte bekannte Stand, aktuelle Warnungen können fehlen.'));
  }
  if (warn.length) {
    box.append(h('strong', {}, `${warn.length} aktive Warnung${warn.length > 1 ? 'en' : ''} im Radius`));
    const ul = h('ul');
    for (const f of warn.slice(0, 4)) {
      const p = f.properties;
      ul.append(h('li', {}, `${SEV[p.severity].label}: `, p.title, ` (${p.distance_km} km, ${p.source_short ?? p.source_name})`));
    }
    if (warn.length > 4) ul.append(h('li', {}, `… und ${warn.length - 4} weitere in der Tabelle`));
    box.append(ul);
  } else if (!uncertain) {
    box.append(h('strong', {}, 'Keine aktiven Warnungen im Radius'), h('span', { class: 'muted' }, 'NINA und DWD melden nichts für die Region.'));
  }
  const badText = (s) => `${s.name}: ${s.status === 'down' ? `nicht erreichbar seit ${fmtDateTime(s.failing_since ?? s.last_attempt)}` : s.status === 'pending' ? 'noch kein Abruf' : 'Daten veraltet'}`;
  if (bad.length === 1) {
    box.append(h('strong', {}, badText(bad[0])), h('span', {}, 'Das Lagebild ist für diese Quelle unvollständig.'));
  } else if (bad.length > 1) {
    // Viele Ausfälle: eine Zeile, Einzelheiten aufklappbar (sonst frisst das Band die Karte)
    box.append(h('strong', {}, `${bad.length} von ${statuses.length} Quellen ohne aktuellen Stand`),
      h('span', {}, 'Das Lagebild ist unvollständig.'),
      h('details', {}, h('summary', {}, 'Welche Quellen?'), h('ul', {}, bad.map((s) => h('li', {}, badText(s))))));
  }
  box.append(h('span', { class: 'meta' }, 'Datenstand ', fmtTime(gen)));
}

// ------------------------------------------------------------------ Ereignisse
// Listenansicht: Werkzeugleiste wird einmal gebaut (sonst verliert das Suchfeld alle 15 s den Fokus), nur #ev-list wird neu gefüllt.
const EV_DEFAULT = { sort: 'prio', reverse: false, minSev: 0, type: '', maxKm: 0, q: '' };
const evView = { ...EV_DEFAULT };
const evActive = () => (evView.minSev ? 1 : 0) + (evView.type ? 1 : 0) + (evView.maxKm ? 1 : 0) + (evView.q.trim() ? 1 : 0);

function syncEventTools(panel) {
  for (const b of panel.querySelectorAll('.ev-chip')) b.setAttribute('aria-pressed', String(Number(b.dataset.sev) === evView.minSev));
  const n = (evView.type ? 1 : 0) + (evView.maxKm ? 1 : 0);
  const more = panel.querySelector('#ev-more-n');
  if (more) { more.textContent = n ? String(n) : ''; more.hidden = !n; }
  const rev = panel.querySelector('#ev-rev');
  if (rev) { rev.setAttribute('aria-pressed', String(evView.reverse)); rev.textContent = evView.reverse ? '↑' : '↓'; }
  const reset = panel.querySelector('#ev-reset');
  if (reset) reset.hidden = !evActive() && evView.sort === 'prio' && !evView.reverse;
}

function buildEventTools(panel) {
  const upd = () => { syncEventTools(panel); renderEvents(state.statuses); };
  const sel = (id, label, opts, key, num) => h('select', { id, 'aria-label': label, onchange: (e) => { evView[key] = num ? Number(e.target.value) : e.target.value; upd(); } },
    opts.map(([v, t]) => h('option', { value: String(v), selected: String(evView[key]) === String(v) ? '' : null }, t)));
  const typeOpts = [['', 'Alle Typen'], ...Object.entries(TYPE_LABEL).filter(([t]) => t !== 'aircraft').map(([t, l]) => [t, l])];
  const chips = [[0, 'Alle'], [1, 'Hinweis+'], [2, 'Warnung+'], [3, 'Kritisch']].map(([v, t]) =>
    h('button', { type: 'button', class: 'ev-chip', 'data-sev': v, 'aria-pressed': String(evView.minSev === v), onclick: () => { evView.minSev = v; upd(); } }, t));
  // Typ, Umkreis und Sortierung liegen eingeklappt hinter „Filter“; Stufe und Suche bleiben sichtbar
  const more = h('div', { class: 'ev-more', id: 'ev-more', hidden: '' },
    h('label', {}, h('span', {}, 'Typ'), sel('ev-type', 'Nach Typ filtern', typeOpts, 'type')),
    h('label', {}, h('span', {}, 'Umkreis um Irrel'), sel('ev-km', 'Nach Entfernung filtern', [[0, 'gesamt'], [10, 'bis 10 km'], [25, 'bis 25 km'], [50, 'bis 50 km']], 'maxKm', true)),
    h('label', { class: 'ev-wide' }, h('span', {}, 'Sortierung'),
      h('span', { class: 'ev-sortbox' }, sel('ev-sort', 'Sortierung', Object.entries(SORTS).map(([k, v]) => [k, v.label]), 'sort'),
        h('button', { type: 'button', id: 'ev-rev', class: 'ev-btn ev-icon', title: 'Reihenfolge umkehren', 'aria-label': 'Reihenfolge umkehren', 'aria-pressed': 'false', onclick: () => { evView.reverse = !evView.reverse; upd(); } }, '↓'))));
  const toggle = h('button', { type: 'button', class: 'ev-btn', id: 'ev-toggle', 'aria-expanded': 'false', 'aria-controls': 'ev-more', onclick: (e) => {
    const open = more.hidden; more.hidden = !open; e.currentTarget.setAttribute('aria-expanded', String(open));
  } }, 'Filter', h('span', { class: 'ev-n', id: 'ev-more-n', hidden: '' }));
  return h('div', { class: 'ev-tools', id: 'ev-tools', role: 'search', 'aria-label': 'Ereignisse suchen, filtern und sortieren' },
    h('div', { class: 'ev-row' },
      h('input', { id: 'ev-q', type: 'search', 'aria-label': 'Ereignisse durchsuchen', placeholder: 'Ereignisse suchen', autocomplete: 'off', maxlength: '60',
        oninput: (e) => { evView.q = e.target.value; upd(); } }), toggle),
    more,
    h('div', { class: 'ev-row ev-row2' }, h('div', { class: 'ev-chips', role: 'group', 'aria-label': 'Mindeststufe' }, chips),
      h('button', { type: 'button', id: 'ev-reset', class: 'ev-link', hidden: '', onclick: () => {
        Object.assign(evView, EV_DEFAULT);
        panel.querySelector('#ev-tools')?.replaceWith(buildEventTools(panel)); syncEventTools(panel); renderEvents(state.statuses);
      } }, 'Zurücksetzen')),
    h('div', { class: 'sr-only', id: 'ev-count', 'aria-live': 'polite' }));
}

function renderEvents(statuses) {
  const panel = $('#panel-events');
  if (!panel.querySelector('#ev-tools')) { panel.replaceChildren(buildEventTools(panel), h('div', { id: 'ev-list' })); syncEventTools(panel); }
  const box = panel.querySelector('#ev-list');
  const top = panel.scrollTop; // die Tabelle wird alle 15 s neu gebaut (Flüge); Lesestelle merken
  box.replaceChildren();
  queueMicrotask(() => { panel.scrollTop = top; });
  const types = Object.entries(GROUPS).filter(([g]) => state.layers[g]).flatMap(([, t]) => t);
  const layered = state.events.filter((f) => types.includes(f.properties.type));
  const rows = sortEvents(filterEvents(layered, evView), evView.sort, evView.reverse);
  const cnt = panel.querySelector('#ev-count');
  const countText = rows.length === layered.length ? `${rows.length} Ereignisse` : `${rows.length} von ${layered.length} Ereignissen`;
  if (cnt) cnt.textContent = countText;
  const q = panel.querySelector('#ev-q'); if (q) q.placeholder = `${countText} durchsuchen`;
  const problems = statuses.filter((s) => ['down', 'stale', 'pending'].includes(s.status) && ['autobahn', 'lbm_baustellen', 'nina', 'dwd_warnungen', 'adsblol'].includes(s.id) && (s.id !== 'adsblol' || state.layers.air));
  for (const s of problems) {
    box.append(h('div', { class: 'card-f' }, h('span', { class: 'stale-note' }, `${s.name}: ${s.status === 'down' ? `nicht erreichbar seit ${fmtDateTime(s.failing_since ?? s.last_attempt)}` : s.status === 'pending' ? 'noch kein Abruf' : 'veraltet'}`)));
  }
  if (!rows.length) {
    box.append(h('div', { class: 'empty' }, layered.length ? 'Kein Ereignis passt zu den Filtern.' : 'Keine Ereignisse in diesem Zeitfenster und dieser Auswahl.'));
    return;
  }
  const tbody = h('tbody');
  for (const f of rows) {
    const p = f.properties;
    tbody.append(h('tr', { class: 'click', tabindex: '0', 'aria-label': `${p.title} auf Karte zeigen`, onclick: () => focusEvent(f), onkeydown: (e) => { if (e.key === 'Enter') focusEvent(f); } },
      h('td', {}, sevBadge(p.severity)),
      h('td', {}, h('div', {}, h('span', { class: `ico ico-${iconFor(p)}`, 'aria-hidden': 'true' }), p.title), h('div', { class: 'muted' }, TYPE_LABEL[p.type] ?? p.type, ' · ', p.source_short ?? p.source_name, ' · ', ageEl(p.fetched_at))),
      h('td', { class: 'num' }, `${Math.round(p.distance_km)} km`)));
  }
  const th = (label, key, cls) => h('th', { scope: 'col', class: cls, 'aria-sort': evView.sort === key ? (evView.reverse ? 'descending' : 'ascending') : 'none' },
    h('button', { type: 'button', class: 'th-sort', onclick: () => {
      if (evView.sort === key) evView.reverse = !evView.reverse; else { evView.sort = key; evView.reverse = false; }
      panel.querySelector('#ev-sort').value = evView.sort; syncEventTools(panel); renderEvents(state.statuses);
    } }, label));
  box.append(h('div', { class: 'scroll-x' }, h('table', {},
    h('caption', { class: 'sr-only' }, 'Ereignisse im Radius, Tabellenansicht der Karte'),
    h('thead', {}, h('tr', {}, th('Stufe', 'prio'), h('th', { scope: 'col' }, 'Ereignis'), th('Abstand', 'dist', 'num'))), tbody)));
}

function focusEvent(f) {
  if (!mapReady) return;
  const p = f.properties;
  map.flyTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 10), duration: 600 });
  showPopup(p, 'event', [p.lon, p.lat]);
  $('#map').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// ------------------------------------------------------------------ Gewässer
function pegelCard(s) {
  return h('div', { class: 'pegel' },
    h('h3', {}, s.name, h('span', { class: 'muted' }, s.km != null ? ` · km ${s.km}` : '')),
    h('div', { class: 'val' }, `${s.latest.value} ${s.latest.unit}`),
    h('div', { class: 'muted' }, trendText(s.trend_cm_3h), ' · ', ageEl(s.latest.ts, 'Messung ')),
    h('div', { class: 'muted right' }, s.latest.state ? `laut Quelle: ${s.latest.state}` : '', s.source_name ? h('span', { class: 'small' }, ` · ${s.source_name}`) : ''),
    sparkline(s.series));
}

// Einklappbarer Ast: Zustand (offen/zu) bleibt über die Aktualisierungen erhalten; Ströme sind anfangs offen
function gNode(key, title, count, body, depth) {
  const open = state.gopen.has(key) ? state.gopen.get(key) : depth === 0;
  const d = h('details', { class: `gnode d${Math.min(depth, 4)}`, 'data-key': key }, h('summary', {}, h('strong', {}, title), h('span', { class: 'muted' }, ` · ${count} ${count === 1 ? 'Pegel' : 'Pegel'}`)), h('div', { class: 'gbody' }, body));
  d.open = open;
  d.addEventListener('toggle', () => state.gopen.set(key, d.open));
  return d;
}

function renderRiver(n, depth) {
  const body = n.items.map((it) => (it.items ? renderRiver(it, depth + 1) : pegelCard(it)));
  return gNode(`r:${n.id}`, n.name, n.total, body, depth);
}

function renderGewaesser() {
  const panel = $('#panel-gew');
  panel.replaceChildren();
  const g = state.gew;
  if (!g) { panel.append(h('div', { class: 'empty' }, 'Keine Daten geladen.')); return; }
  const list = sortStations(g.stations.filter((s) => s.latest)); // Gewässer alphabetisch, darin Stationen alphabetisch
  if (!list.length) panel.append(h('div', { class: 'empty' }, 'Noch keine Messwerte.'));
  const tree = buildTree(list, state.net);
  if (tree.roots.length) {
    const all = (open) => () => { panel.querySelectorAll('details.gnode').forEach((d) => { d.open = open; }); };
    panel.append(h('div', { class: 'card-f gtools' },
      h('span', { class: 'muted small' }, 'Von der Mündung zur Quelle; Zuflüsse stehen dort, wo sie münden.'),
      h('button', { type: 'button', class: 'linkbtn', onclick: all(true) }, 'alles auf'),
      h('button', { type: 'button', class: 'linkbtn', onclick: all(false) }, 'alles zu')));
    for (const r of tree.roots) panel.append(renderRiver(r, 0));
    const rest = tree.open.groups.reduce((a, x) => a + x.stations.length, 0);
    if (rest) panel.append(gNode('open', 'Weitere Gewässer (Zuordnung offen)', rest,
      tree.open.groups.map((x) => gNode(`o:${x.label}`, x.label, x.stations.length, x.stations.map(pegelCard), 2)), 0));
    if (tree.none.length) panel.append(gNode('none', 'Ohne Gewässerangabe', tree.none.length, tree.none.map(pegelCard), 1));
  } else {   // Netzdatei fehlt: flache Liste wie bisher
    let water;
    for (const s of list) {
      if (s.water_label !== water) { water = s.water_label; panel.append(h('div', { class: 'card-f' }, h('strong', {}, water ?? 'Ohne Gewässerangabe'))); }
      panel.append(pegelCard(s));
    }
  }
  panel.append(h('div', { class: 'card-f' }, h('span', { class: 'muted small' }, 'Gewässerzuordnung: Wikidata (CC0), automatisch zugeordnet; wo der Name nicht eindeutig ist, steht der Pegel unter „Zuordnung offen“.')));
  for (const src of g.sources ?? [g.source]) if (src) panel.append(sourceLine(src));
}

// ------------------------------------------------------------------ Umwelt
function renderUmwelt() {
  const panel = $('#panel-env');
  panel.replaceChildren();
  const e = state.env;
  if (!e) { panel.append(h('div', { class: 'empty' }, 'Keine Daten geladen.')); return; }
  let kind = null;
  for (const s of e.stations.filter((x) => x.kind !== 'weather')) {   // Wetterstationen stehen auf der Karte, nicht in dieser Liste
    if (s.kind !== kind) { kind = s.kind; panel.append(h('div', { class: 'card-f' }, h('strong', {}, kind === 'radiation' ? 'Ortsdosisleistung (Gamma)' : 'Luftqualität'))); }
    const first = Object.values(s.values)[0];
    panel.append(h('div', { class: 'pegel' },
      h('h3', {}, s.name, h('span', { class: 'muted' }, ` · ${Math.round(s.distance_km)} km`)),
      h('div', { class: 'val' }, sevBadge(envLevel(s))),
      h('div', { class: 'muted' }, envText(s).join(' · '), ' · ', ageEl(first?.ts, 'Messung ')),
      h('div', { class: 'muted right' }, s.source_name),
      sparkline((s.kind === 'radiation' ? s.values.odl : s.values.NO2 ?? s.values.PM10 ?? s.values.lqi)?.series?.map((v, i) => ({ ts: i, value: v })) ?? [])));
  }
  if (!e.stations.length) panel.append(h('div', { class: 'empty' }, 'Noch keine Messwerte.'));
  for (const src of e.sources ?? []) panel.append(sourceLine(src));
  renderIndizes(panel, state.idx, { h, sevBadge, sourceLine, ageEl });
  panel.append(h('div', { class: 'card-f' }, h('span', { class: 'muted small' }, 'Stufen bei Strahlung sind eigene Orientierung (0,3 und 1,0 µSv/h), kein amtlicher Grenzwert. Luft nach dem Index der Quelle.')));
}

// ------------------------------------------------------------------ Wetter
// Kompaktes „Wetter jetzt“ über der Karte, damit die Lage nicht erst im Reiter gesucht werden muss
function renderWxBand() {
  const box = $('#wxband');
  if (!box) return; // Wetterband ist aus der Seite genommen; das Wetter steht im Reiter
  const w = state.wx;
  box.replaceChildren();
  const c = w?.current;
  if (!c || !c.temperature) {
    box.append(h('strong', {}, 'Wetter jetzt'), h('span', { class: 'muted' }, 'Keine Messwerte geladen'));
    return;
  }
  const num = (k, d = 0) => (c[k] ? `${Number(c[k].value).toFixed(d)} ${c[k].unit}` : '–');
  const src = state.statuses.find((s) => s.id === 'brightsky');
  const items = [
    ['Temperatur', num('temperature', 1), 'temperatur'],
    ['Wind', `${num('wind_speed_10')}${c.wind_gust_speed_10 ? `, Böen ${num('wind_gust_speed_10')}` : ''}`, 'wind'],
    ['Niederschlag (60 Min.)', num('precipitation_60', 1), 'regen'],
    ['Bewölkung', num('cloud_cover'), 'wolken'],
    ['Luftfeuchte', num('relative_humidity'), 'feuchte'],
    ['Luftdruck', num('pressure_msl'), 'druck'],
  ];
  const dl = h('dl', { class: 'wx-items' });
  for (const [k, v, ico] of items) dl.append(h('div', {}, h('dt', {}, h('span', { class: `ico ico-${ico}`, 'aria-hidden': 'true' }), k), h('dd', {}, v)));
  const meta = h('span', { class: 'meta' },
    `Station ${w.station?.name ?? '–'} (${w.station?.distance_km ?? '?'} km) · Messung `, ageEl(c.temperature.ts),
    ` · ${w.source?.attribution ?? 'Quelle: DWD über Bright Sky'}`);
  const old = Date.now() - new Date(c.temperature.ts).getTime() > 2 * 3600 * 1000;
  const note = ['down', 'stale'].includes(src?.status) || old
    ? h('span', { class: 'stale-note' }, src?.status === 'down' ? 'Quelle nicht erreichbar, Werte nicht aktuell' : 'Werte veraltet')
    : null;
  box.append(h('strong', {}, 'Wetter jetzt'), dl, ...(note ? [note] : []), meta);
}

function renderWetter() {
  const panel = $('#panel-wx');
  panel.replaceChildren();
  const w = state.wx;
  if (!w || !w.current.temperature) { panel.append(h('div', { class: 'empty' }, 'Keine Wetterdaten geladen.'), sourceLine(w?.source)); return; }
  const c = w.current, v = (k, d = 0) => (c[k] ? `${Number(c[k].value).toFixed(d)} ${c[k].unit}` : '–');
  panel.append(h('div', { class: 'wx-now' },
    h('div', { class: 'big' }, v('temperature', 1)),
    h('dl', { class: 'kv' }, h('dt', {}, 'Wind (10 Min.)'), h('dd', {}, v('wind_speed_10', 1)), h('dt', {}, 'Böen'), h('dd', {}, v('wind_gust_speed_10', 1))),
    h('dl', { class: 'kv' }, h('dt', {}, 'Luftfeuchte'), h('dd', {}, v('relative_humidity')), h('dt', {}, 'Luftdruck'), h('dd', {}, v('pressure_msl', 1))),
    h('dl', { class: 'kv' }, h('dt', {}, 'Niederschlag (60 Min.)'), h('dd', {}, v('precipitation_60', 1)), h('dt', {}, 'Bewölkung'), h('dd', {}, v('cloud_cover')), h('dt', {}, 'Sicht'), h('dd', {}, c.visibility ? `${(c.visibility.value / 1000).toFixed(0)} km` : '–')),
    h('div', { class: 'muted wx-note' }, `Station ${w.station?.name ?? '–'} (${w.station?.distance_km ?? '?'} km), Messung `, ageEl(c.temperature.ts))));
  const hrs = w.forecast?.payload?.hours ?? [];
  const alt = w.forecast_alt?.hours ?? [];
  if (hrs.length) panel.append(forecastChart(hrs, alt));
  panel.append(sourceLine(w.source, w.forecast ? h('span', {}, 'Vorhersage ', ageEl(w.forecast.fetched_at)) : null));
  if (alt.length) panel.append(sourceLine(w.forecast_alt.source, h('span', {}, 'Vorhersage ', ageEl(w.forecast_alt.fetched_at))));
  if (w.others?.length) panel.append(othersTable(w.others));
}

// Weitere Beobachtungen: MeteoLux Findel und Sensor.Community-Raster, jeweils mit Quelle und Alter der Messung
function othersTable(list) {
  const rows = list.slice(0, 7);
  const cell = (o, k, d = 0) => (o.current[k] ? `${Number(o.current[k].value).toFixed(d)} ${o.current[k].unit}` : '–');
  const newest = (o) => Object.values(o.current).map((x) => x.ts).sort().pop();
  const tbl = h('table', { class: 'wx-others' },
    h('caption', {}, 'Weitere Messungen in der Region'),
    h('thead', {}, h('tr', {}, ...['Ort (Quelle)', 'Temp.', 'Feuchte', 'Wind', 'Alter'].map((t) => h('th', { scope: 'col' }, t)))),
    h('tbody', {}, ...rows.map((o) => h('tr', {},
      h('th', { scope: 'row' }, `${o.name} `, h('span', { class: 'muted small' }, `(${o.source_name}${o.meta?.sensoren ? `, Median aus ${o.meta.sensoren} Sensoren` : ''}, ${o.distance_km} km)`)),
      h('td', {}, cell(o, 'temperature', 1)), h('td', {}, cell(o, 'relative_humidity')), h('td', {}, cell(o, 'wind_speed_10')), h('td', {}, ageEl(newest(o)))))));
  const srcIds = [...new Set(rows.map((o) => o.source_id))];
  const caveat = rows.some((o) => o.source_id === 'sensor_community')
    ? h('p', { class: 'muted small' }, 'Bürgersensoren sind nicht kalibriert und zeigen in der Sonne oder bei erwärmtem Gehäuse oft mehrere Grad zu viel. Richtwert, keine amtliche Messung.')
    : null;
  return h('div', { class: 'wx-chart' }, tbl, ...(caveat ? [caveat] : []), ...srcIds.map((id) => sourceLine(state.statuses.find((x) => x.id === id) ?? null)));
}

function forecastChart(hrs, alt = []) {
  const NS = 'http://www.w3.org/2000/svg', W = 360, H = 120, padL = 22, padB = 16;
  const el = (t, a = {}) => { const e = document.createElementNS(NS, t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Temperatur und Niederschlag, nächste 48 Stunden' });
  const t = [...hrs, ...alt].map((r) => r.temperature).filter((x) => x != null);
  const tmin = Math.floor(Math.min(...t)), tmax = Math.ceil(Math.max(...t)), span = tmax - tmin || 1;
  const x = (i) => padL + (i / (hrs.length - 1)) * (W - padL - 4), y = (val) => H - padB - ((val - tmin) / span) * (H - padB - 8);
  const pmax = Math.max(1, ...hrs.map((r) => r.precipitation ?? 0));
  hrs.forEach((r, i) => { if (r.precipitation > 0) { const bh = (r.precipitation / pmax) * 34; svg.append(el('rect', { class: 'bar', x: x(i) - 2, y: H - padB - bh, width: 4, height: bh })); } });
  for (const val of [tmin, tmax]) { svg.append(el('line', { class: 'grid-line', x1: padL, x2: W, y1: y(val), y2: y(val) })); const l = el('text', { class: 'lbl', x: 0, y: y(val) + 3 }); l.textContent = `${val}°`; svg.append(l); }
  const d = hrs.map((r, i) => (r.temperature == null ? '' : `${i && hrs[i - 1].temperature != null ? 'L' : 'M'}${x(i).toFixed(1)} ${y(r.temperature).toFixed(1)}`)).join(' ');
  svg.append(el('path', { d, class: 'spark' }));
  if (alt.length) {   // zweites Modell: gleiche Zeitachse, gestrichelt; Stunden über die Zeitstempel zugeordnet
    const idx = new Map(hrs.map((r, i) => [r.timestamp.slice(0, 13), i]));
    const pts = alt.map((r) => [idx.get(r.timestamp.slice(0, 13)), r.temperature]).filter(([i, v]) => i != null && v != null);
    svg.append(el('path', { d: pts.map(([i, v], n) => `${n ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' '), class: 'spark spark-alt' }));
  }
  [0, 12, 24, 36, 47].filter((i) => i < hrs.length).forEach((i) => { const l = el('text', { class: 'lbl', x: x(i) - 12, y: H - 3 }); l.textContent = fmtHour(hrs[i].timestamp); svg.append(l); });
  const wrap = h('div', { class: 'wx-chart' }, svg, h('div', { class: 'muted small' }, alt.length ? 'Durchgezogen: Temperatur DWD, gestrichelt: MET Norway, Balken: Niederschlag DWD je Stunde' : 'Linie: Temperatur, Balken: Niederschlag je Stunde'));
  return wrap;
}

// ------------------------------------------------------------------ Laden
const WARN_TYPES = ['warning', 'weather', 'flood', 'radiation', 'air', 'earthquake', 'fire'];

async function refresh() {
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
function renderAir() {
  state.all = state.layers.air ? [...state.base, ...state.airRaw] : state.base;
  state.events = windowFilter(state.all, state.within, Date.now());
  renderEvents(state.statuses);
  $('#count').textContent = `${state.events.length} Ereignisse`;
  pushAir();
}

function render() {
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

let timer;
const debounced = () => { clearTimeout(timer); timer = setTimeout(refresh, 800); };

function wire() {
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

async function main() {
  wire();
  try { state.meta = await getJSON('data/meta.json'); } catch { $('#apidown').hidden = false; return; }
  setupSideToggle();
  await initMap();
  await refresh();
}
main();

// Suche: Index wird erst beim ersten Fokus geladen; Treffer bekommen eine Markierung mit Namen, Art und Ort (nur Text, keine Adressen)
let searchMarker = null;
function initSearch() {
  const input = $('#suche-q'), list = $('#suche-liste'), status = $('#suche-status');
  if (!input || !list || !status) return;
  const clear = () => { searchMarker?.remove(); searchMarker = null; };
  // Im Vollbild ist nur die Kartenfläche sichtbar: die Suchzeile zieht dorthin um und danach wieder in den Menükopf
  const form = $('#suche'), home = form?.parentElement, wrap = $('.map-wrap'), after = home?.querySelector('.controls');
  const place = () => { const fs = document.fullscreenElement ?? document.webkitFullscreenElement; if (fs === wrap) wrap.prepend(form); else if (form.parentElement !== home) home.insertBefore(form, after); };
  document.addEventListener('fullscreenchange', place);
  document.addEventListener('webkitfullscreenchange', place);
  mountSearch({
    input, list, status,
    getNear: () => { const c = map.getCenter(); return { lat: c.lat, lon: c.lng }; },
    loadParts: () => Promise.all(['data/suche_geo.json', 'data/suche.json'].map((p) => getJSON(p).catch(() => null))),
    onPick: (e) => {
      clear();
      if (!e) return;
      const el = document.createElement('div');                     // Träger ohne eigene Drehung (MapLibre setzt dessen transform)
      el.className = 'search-pin';
      el.append(document.createElement('span'));
      const box = document.createElement('div');
      box.className = 'pop search-pop';
      const b = document.createElement('h3'); b.textContent = e.name;
      const t = document.createElement('p'); t.className = 'k'; t.textContent = e.ort ? `${e.typ} · ${e.ort}` : e.typ;
      box.append(b, t);
      searchMarker = new Marker({ element: el, anchor: 'bottom' }).setLngLat([e.lon, e.lat])
        .setPopup(new Popup({ offset: [0, -34], closeButton: true, focusAfterOpen: false, maxWidth: '280px' }).setDOMContent(box)).addTo(map);
      map.flyTo({ center: [e.lon, e.lat], zoom: Math.min(zoomFor(e.typ), map.getMaxZoom()), essential: true });
      map.once('moveend', () => { if (searchMarker) searchMarker.togglePopup(); });
    },
  });
}
