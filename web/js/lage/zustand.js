// Laufzeitobjekte der Seite. Andere Module lesen sie über die gebundenen Importe; gesetzt wird nur über die Setzer unten.
export let map = null, popup = null, sweep = null, ripples = null, wind = null, windLow = null, flow = null;
export let mapReady = false, basemapOk = false, coreOk = false, ringOk = false, reliefOk = false;
export let light = null;   // Lichtquelle am Zeiger (js/licht.js)
export function setMap(v) { map = v; }
export function setPopup(v) { popup = v; }
export function setSweep(v) { sweep = v; }
export function setRipples(v) { ripples = v; }
export function setWind(v) { wind = v; }
export function setWindLow(v) { windLow = v; }
export function setFlow(v) { flow = v; }
export function setMapReady(v) { mapReady = v; }
export function setBasemapOk(v) { basemapOk = v; }
export function setCoreOk(v) { coreOk = v; }
export function setRingOk(v) { ringOk = v; }
export function setReliefOk(v) { reliefOk = v; }
export function setLight(v) { light = v; }

// Startansicht und Bezugspunkt für Entfernungen: Irrel (Ortsmitte, Koordinate vom Betreiber angegeben).
export const START_VIEW = { lat: 49.84615562322509, lon: 6.456057281843173 };
export const TOWNS = [
  ['Irrel', 49.850, 6.450, true], ['Bitburg', 49.975, 6.526], ['Trier', 49.750, 6.637], ['Echternach', 49.812, 6.418],
  ['Wasserbillig', 49.714, 6.503], ['Luxemburg', 49.611, 6.130], ['Prüm', 50.208, 6.423], ['Wittlich', 49.985, 6.894],
  ['Saarburg', 49.607, 6.547], ['Daun', 50.199, 6.830], ['Merzig', 49.444, 6.639],
  // weitere Orte der Region (Radius 120 km): Luxemburg, Ostbelgien, Lothringen, Saarland, Mosel, Hunsrück
  ['Diekirch', 49.868, 6.157], ['Wiltz', 49.966, 5.932], ['Esch-sur-Alzette', 49.495, 5.981], ['Arlon', 49.683, 5.816], ['Bastogne', 50.000, 5.717],
  ['St. Vith', 50.281, 6.128], ['Gerolstein', 50.224, 6.657], ['Bernkastel-Kues', 49.916, 7.070], ['Cochem', 50.146, 7.166], ['Idar-Oberstein', 49.708, 7.310],
  ['Saarlouis', 49.314, 6.751], ['Saarbrücken', 49.234, 6.996], ['Thionville', 49.358, 6.168], ['Metz', 49.119, 6.176], ['Koblenz', 50.357, 7.589],
];
// Radarbild blendet beim Hineinzoomen aus (Zoom 11 bis 13); die Regentropfen-Animation bleibt und läuft aus denselben Radardaten weiter
export const RADAR_OPACITY = ['interpolate', ['linear'], ['zoom'], 11, 0.6, 13, 0];
export const RING_URL = 'tiles/ring.pmtiles'; // Zoom 14 rund um den Kern bis zum 120-km-Rand: nur dafür da, dass Häuserumrisse im ganzen Gebiet stehen
export const CORE_URL = 'tiles/core.pmtiles'; // Kern um Irrel mit Zoom 15: Gebäude und Hausnummern (die große Datei reicht nur bis Zoom 13)
export const TILES_URL = 'tiles/region.pmtiles'; // OSM-Ausschnitt (Protomaps-Build), liegt auf demselben Server

// Schalter im Ebenenmenü → Ereignisarten (Schema: app/models.py EventType). Ebenen ohne Ereignisart (Pegel, Radar, Blitze, Relief, Natur, Basiskarte) stehen nicht hier.
export const GROUPS = { traffic: ['traffic', 'congestion'], transit: ['transit'], warning: ['warning', 'weather'], flood: ['flood'], air: ['aircraft'],
  airq: ['air'], rad: ['radiation'], quake: ['earthquake'], fire: ['fire'] };
export const state = { gopen: new Map(), net: null, within: 'now', layers: { warning: false, flood: false, fire: false, quake: false, news: false, social: false, traffic: false, transit: false, stops: false, air: false, signs: false,
    radar: true, drops: true, wind: false, windlow: false, blitz: true, wehr: false, bruecke: false, rast: false, civic: false, cemetery: false, hike: false, bike: false, charge: false, wturb: false, emerg: false, gew: true, tank: false, wxst: true, airq: true, rad: true, nature: true, herCastle: false, herArch: false, herMonastery: false, herBuilding: false, herChurch: false, herChapel: false, herCross: false, herMill: false, herFord: false, herBorder: false, herGallows: false, herWell: false, relief: true,
    vegForest: true, vegMeadow: true, vegScrub: true, vegField: true, vegVine: true, vegWet: true, vegRock: true,
    bndCountry: true, bndRegion: true, bndCounty: true, bndLocal: false, protNature: true, protPark: true, protMil: true, flow: false, cliffs: true, buildings: true, licht: false, roadHw: true, roadMain: true, roadMid: true, roadMinor: true, roadPath: true, rail: true, roadNames: true, medieval: false }, meta: null, env: null, radar: null, wind: null, blitz: null, stops: null, landmarks: null, base: [], airRaw: [], airAt: 0, all: [], events: [], gew: null, wx: null, idx: null, fuel: null, infra: null, routen: null, themen: null, statuses: [], iconsOk: false };
export const AIR_IMG = { civil: 'plane-', mil: 'mplane-', heli: 'heli-', milheli: 'mheli-' }; // Bildname je Klasse, dazu die Stufe
export const AIR_POLL_MS = 15000;  // aircraft.json: so oft schreibt die Live-Schleife
export const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
if (reduceMotion) { state.layers.drops = false; const cb = document.querySelector('input[data-layer="drops"]'); if (cb) cb.checked = false; } // Animation nur auf Wunsch
export const SYMBOL_LAYERS = ['ev-sym-pt', 'ev-sym-ln', 'ev-sym-pt-w', 'ev-sym-ln-w', 'ev-dot-w'];
