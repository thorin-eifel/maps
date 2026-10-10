import { namedFlavor } from '../../vendor/protomaps-basemaps/basemaps.js';
import { extraLayers, faunaLayers, patternLayer, waterPatternLayer } from '../medieval.js';
import { map, mapReady, wind } from './zustand.js';

// ------------------------------------------------------------------ Karte „um 1450“
// Schaltbar unter „Kultur und Geschichte“: Pergament, Tinte, Wege statt Straßen, ohne Bahn, Flughäfen und Grenzen; Höhenlinien, Gebäude, Schilder und Klippen bleiben über ihre Schalter nutzbar, Schrift in Textura-Art (Grenze Gotisch).
// Nur die Darstellung ändert sich; Ereignisse und Messwerte liegen unverändert darüber. Schrift: Grenze Gotisch (OFL), Glyphen unter fonts/.
export const MED = { bg: '#d9c28c', paper: '#e8d6a6', ink: '#3a2614', road: '#7a5530', water: '#a6bcb0', edge: '#58726a', halo: 'rgba(238,224,182,0.92)', waterLabel: '#1f4f86' };
export const MED_FONT = ['Grenze Gotisch Regular'];
// Schriftgröße skalieren, ohne den Zoom-Ausdruck zu verschachteln (MapLibre erlaubt "zoom" nur direkt in step/interpolate): Ausgabewerte der Stützstellen mit k multiplizieren
export function scaleSize(e, k) {
  if (typeof e === 'number') return e * k;
  if (!Array.isArray(e)) return e;
  if (e[0] === 'interpolate' || e[0] === 'interpolate-hcl' || e[0] === 'interpolate-lab') return e.map((v, i) => (i >= 3 && i % 2 === 0 ? scaleSize(v, k) : v));
  if (e[0] === 'step') return e.map((v, i) => (i === 2 || (i > 2 && i % 2 === 0) ? scaleSize(v, k) : v));
  return ['*', k, e];
}
export const RETINA = (window.devicePixelRatio || 1) >= 1.5;
// Farben der Zeichen in der historischen Karte (Pigmente: Zinnober, Ocker, Krapp); Stufen bleiben unterscheidbar, Rot heißt weiter Rot
export const MED_COLORS = { bg: '#efe0b0', line: '#7a5530', fg: MED.ink, muted: '#7a6850', critical: '#7a1020', warning: '#b03a22', notice: '#b7791f',
  yellow: '#d9a520', orange: '#c8661c', red: '#a33a22', black: '#2b1d10', info: '#3f6b72', accent: '#a33a22', white: '#efe0b0', ink: MED.ink };
export const MED_ICON_STYLE = { light: '#efe0b0', dark: '#3a2614' };
export const MED_LAND = { forest: ['#8fa672', 0.55], meadow: ['#d6c88c', 0.15], scrub: ['#a9a66e', 0.35], farmland: ['#e3cf94', 0.2], wetland: ['#a9bdb0', 0.55], rock: ['#a89678', 0.55] };
// neue Klassen der Naturfarben auf die Pigmente der alten Karte abbilden (Schutzgebiete und moderne Signaturen entfallen)
export const MED_CLASS = { grass: 'meadow', heath: 'scrub', orchard: 'farmland', vineyard: 'farmland', allotment: 'farmland', sand: 'farmland', cemetery: 'meadow' };
export const MED_DROP = /^(land-([a-z]+-pat|protected-|military-|bound-|cliff-(band|case))|roads_oneway|roads_rail|roads_runway|roads_taxiway|roads_pier|roads_labels_|roads_tunnels_|roads_.*casing|landuse_(park|runway|aerodrome|industrial|school|hospital|zoo|pedestrian|pier|urban_green|beach)|boundaries|address_label)/;
export const medFlavor = () => ({ ...namedFlavor('grayscale'), background: MED.bg, earth: MED.paper, water: MED.water, city_label: MED.ink, subplace_label: MED.ink, city_label_halo: MED.halo, subplace_label_halo: MED.halo });
export function medievalize(styled) {
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
export function windrose(on) {
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
export const COMPASS = ['N', 'NNO', 'NO', 'ONO', 'O', 'OSO', 'SO', 'SSO', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
// Wind am Ort der Rose: Kartenpunkt unter dem Mittelpunkt, Modellwert aus dem Windgitter (Richtung: woher er kommt; der Pfeil zeigt, wohin er weht)
export function windroseUpdate() {
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
