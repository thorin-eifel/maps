import { FullscreenControl, Map as MlMap, Marker, NavigationControl, Popup, ScaleControl, addProtocol } from '../../vendor/maplibre-gl/maplibre-gl.js';
import { PMTiles, Protocol } from '../../vendor/pmtiles/pmtiles.js';
import { createFlow, registerArrow } from '../fluss.js';
import { MIL_COLOUR, iconStatus, registerIcons, registerMedieval, registerSigns } from '../icons.js';
import { registerInfra } from '../infra.js';
import { buildRainLegend } from '../legend.js';
import { createLight } from '../licht.js';
import { FAUNA_SOURCE, faunaPoints, registerFauna, registerMedievalPatterns } from '../medieval.js';
import { ping as pingSound, silence as silenceSound, sizzle as sizzleSound, zap as zapSound } from '../ping-sound.js';
import { RELIEF_ATTRIBUTION, demTile, glyphsUrl, setupRelief } from '../relief.js';
import { createRipples } from '../ripples.js';
import { SWEEP_GREEN, createSweep } from '../sweep.js';
import { KIND_MIN_ZOOM } from '../zellen.js';
import { loadTerrain } from '../terrain.js';
import { $, getJSON, h, link } from '../util.js';
import { createWind, fillWindLegend } from '../wind.js';
import { applyBasemap, wireElevation } from './basiskarte.js';
import { debugHook } from './debug.js';
import { applyLayerFilters } from './ebenen.js';
import { palette, sevColor } from './farben.js';
import { VIG_FADE_KM, VIG_ID, circle, vignette } from './geometrie.js';
import { pushMapData } from './messnetz.js';
import { windroseUpdate } from './mittelalter.js';
import { INFRA_LAYER_IDS } from './orte.js';
import { showPopup } from './popup.js';
import { initSearch } from './suche-karte.js';
import { applyWind, fillTempLegend, showFlowWind, trackLegendBottom } from './wetterkarte.js';
import { CORE_URL, RING_URL, START_VIEW, SYMBOL_LAYERS, TILES_URL, TOWNS, light, map, reduceMotion, reliefOk, ripples, setBasemapOk, setCoreOk, setFlow, setLight, setMap, setMapReady, setPopup, setReliefOk, setRingOk, setRipples, setSweep, setWind, setWindLow, state, sweep, wind, windLow } from './zustand.js';

// ------------------------------------------------------------------ Karte
export async function initMap() {
  const c = palette();
  const m = state.meta;
  setMap(new MlMap({
    container: 'map',
    style: { version: 8, sources: {}, glyphs: glyphsUrl(), layers: [{ id: 'bg', type: 'background', paint: { 'background-color': c.bg } }] },
    center: [m.center?.lon ?? START_VIEW.lon, m.center?.lat ?? START_VIEW.lat], zoom: 8.0, attributionControl: false, dragRotate: false, pitchWithRotate: false,
    locale: { 'FullscreenControl.Enter': 'Vollbild', 'FullscreenControl.Exit': 'Vollbild beenden', 'NavigationControl.ZoomIn': 'Vergrößern', 'NavigationControl.ZoomOut': 'Verkleinern' },
    maxBounds: [[m.bbox.lon_min - 0.45, m.bbox.lat_min - 0.28], [m.bbox.lon_max + 0.45, m.bbox.lat_max + 0.28]],
  }));
  map.touchZoomRotate.disableRotation();
  map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
  if (document.fullscreenEnabled || document.webkitFullscreenEnabled) map.addControl(new FullscreenControl({ container: document.querySelector('.map-wrap') }), 'top-right');      // Karte samt Cartouche, Windrose und Legende
  map.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-right');
  setPopup(new Popup({ closeButton: true, maxWidth: '320px' }));

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

  // Dichte bei kleinen Zoomstufen (unter EVENTS_MIN_ZOOM): je Rasterzelle eine Zahl statt Tausender Einzelsymbole; Daten aus start.json
  map.addSource('dichte', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'dichte-kreis', type: 'circle', source: 'dichte', maxzoom: KIND_MIN_ZOOM.events,
    paint: { 'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'n']], 1, 9, 30, 26], 'circle-color': sevColor(c, 'sev'), 'circle-opacity': 0.85, 'circle-stroke-color': c.white, 'circle-stroke-width': 1.5 } });
  map.addLayer({ id: 'dichte-zahl', type: 'symbol', source: 'dichte', maxzoom: KIND_MIN_ZOOM.events,
    layout: { 'text-field': ['to-string', ['get', 'n']], 'text-font': ['Noto Sans Regular'], 'text-size': 12, 'text-allow-overlap': true },
    paint: { 'text-color': c.white } });

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
  setReliefOk(await setupRelief(map));
  if (reliefOk) setLight(createLight(map, { demTile, onError: (e) => console.warn('Licht:', e), reduce: reduceMotion, wind: () => { const c = map.getCenter(); const w = wind?.sample?.(c.lng, c.lat); return w ? { speed: w.speed, from: w.from } : null; } }));
  setMapReady(true);
  map.on('move', windroseUpdate);
  initSearch();
  if (location.hash === '#debug') debugHook(map); // nur für Prüfungen im Browser
  setRipples(createRipples(map, { center: state.meta.center, radiusKm: state.meta.radius_km, fadeKm: VIG_FADE_KM, onSizzle: sizzleSound }));
  // Untere Schicht zuerst anlegen, damit die obere (reiner Modellwind) darüber liegt
  setWindLow(createWind(map, { center: state.meta.center, radiusKm: state.meta.radius_km, fadeKm: VIG_FADE_KM, adjusted: true }));
  setWind(createWind(map, { center: state.meta.center, radiusKm: state.meta.radius_km, fadeKm: VIG_FADE_KM }));
  loadTerrain('data/terrain.json').then((t) => { state.terrain = t; windLow.setTerrain(t); applyWind(); });
  ripples.setWind((lon, lat, out) => wind.sample(lon, lat, out));   // Dampf des Lasers driftet mit dem Modellwind
  setFlow(createFlow(map, { sampleWind: (lon, lat, out) => wind.sample(lon, lat, out), reduce: reduceMotion, onWind: showFlowWind }));   // Wellen auf Stillgewässern ziehen mit dem Modellwind
  const windBar = $('#wind-bar'); if (windBar) fillWindLegend(windBar);
  const windBarLow = $('#wind-bar-low'); if (windBarLow) fillWindLegend(windBarLow, undefined, true);
  fillTempLegend();
  trackLegendBottom();
  buildRainLegend($('#rain-strip'), $('#rain-labels'));
  setSweep(createSweep(map, { center: state.meta.center, radiusKm: state.meta.radius_km, mil: MIL_COLOUR, reducedMotion: reduceMotion, onPing: (e) => (e.zap ? zapSound(e) : pingSound(e)) }));
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
export async function setupBasemap() {
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
    (state.zellen ? Promise.resolve(null) : getJSON('data/anbau.json')).then((j) => { if (Array.isArray(j?.features)) map.getSource('anbau')?.setData(j); }).catch(() => {});
    setBasemapOk(true);
    try {   // Kern mit Gebäudedetail; fehlt er, bleibt die Karte wie sie ist (Gebäude dann nur grob aus Zoom 13, keine Hausnummern)
      const coreUrl = new URL(CORE_URL, location.href).href;
      const core = new PMTiles(coreUrl);
      await core.getHeader();
      protocol.add(core);
      map.addSource('basemap-core', { type: 'vector', url: `pmtiles://${coreUrl}`, tileSize: 256 });   // 256er Kachelmaß: die Zoom-15-Kacheln (alle Gebäude) gelten schon ab Kartenzoom 14
      setCoreOk(true);
    } catch (err) { console.warn('Kernkarte (Zoom 15) nicht verfügbar:', err?.message ?? err); }
    try {   // Ring um den Kern (nur Zoom 14): Häuserumrisse im restlichen Radius, ohne Hausnummern
      const ringUrl = new URL(RING_URL, location.href).href;
      const ring = new PMTiles(ringUrl);
      await ring.getHeader();
      protocol.add(ring);
      map.addSource('basemap-ring', { type: 'vector', url: `pmtiles://${ringUrl}` });
      setRingOk(true);
    } catch (err) { console.warn('Ringkarte (Zoom 14) nicht verfügbar:', err?.message ?? err); }
    note.replaceChildren('Karte: ', link('https://www.openstreetmap.org/copyright', '© OpenStreetMap-Mitwirkende (ODbL)'), ' · Protomaps');
    if (globalThis.mlcontour) note.append(' · ', RELIEF_ATTRIBUTION);
  } catch (err) {
    console.warn('Basiskarte nicht verfügbar:', err?.message ?? err);
    note.replaceChildren('Basiskarte nicht verfügbar');
  }
}
