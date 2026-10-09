// Karte im Stil des 15. Jahrhunderts: handgezeichnete Kartenzeichen als Flächenmuster (Wald, Acker, Wiese, Gebüsch, Moor, Fels, Wasser),
// Hügel- und Siedlungszeichen, Wellen an Flüssen, dazu Papierkorn und Titelschild. Alles eigene Zeichnung, erzeugt im Browser auf Canvas.
// Nichts davon läuft, solange die Karte im normalen Stil steht. Aufrufer: lage.js (applyBasemap, syncMedieval).
import { FAUNA_DRAWINGS, paintFauna, FAUNA_SIZE } from './fauna.js';
export const MED = { ink: '#3a2614', paper: '#efe0b0', stone: '#d9c68f', roof: '#a33a22', water: '#58726a', wash: 'rgba(239,224,176,0.82)' };

// Wiederholbarer Zufall, damit Zeichnungen bei jedem Laden gleich aussehen
function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const put = (map, id, data, ratio = 2) => { if (map.hasImage(id)) map.updateImage(id, data); else map.addImage(id, data, { pixelRatio: ratio }); };
const canvas = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d', { willReadFrequently: true }); x.lineCap = 'round'; x.lineJoin = 'round'; return [c, x]; };

// Linie durch Punkte, leicht zittrig wie von Hand (weiche Kurve über die Mittelpunkte)
function wob(x, pts, r, j = 0.7) {
  const p = pts.map(([a, b]) => [a + (r() - 0.5) * 2 * j, b + (r() - 0.5) * 2 * j]);
  x.beginPath(); x.moveTo(p[0][0], p[0][1]);
  for (let i = 1; i < p.length - 1; i++) x.quadraticCurveTo(p[i][0], p[i][1], (p[i][0] + p[i + 1][0]) / 2, (p[i][1] + p[i + 1][1]) / 2);
  x.lineTo(p[p.length - 1][0], p[p.length - 1][1]); x.stroke();
}
const line = (x, a, b, c, d) => { x.beginPath(); x.moveTo(a, b); x.lineTo(c, d); x.stroke(); };
const ink = (x, w = 1.3) => { x.strokeStyle = MED.ink; x.lineWidth = w; };

// ---- Bäume: Laubbaum aus runden Büscheln, Nadelbaum aus gestapelten Dreiecken
function leafTree(x, cx, cy, s, r) {
  ink(x); x.fillStyle = MED.wash;
  const lobes = [[-5.5, -2], [0, -6.5], [5.5, -2], [-2.8, 1.5], [3, 1.5]];
  for (const [dx, dy] of lobes) { x.beginPath(); x.arc(cx + dx * s, cy - 11 * s + dy * s, 4.6 * s, 0, Math.PI * 2); x.fill(); }
  for (const [dx, dy] of lobes) { x.beginPath(); x.arc(cx + dx * s, cy - 11 * s + dy * s, 4.6 * s, 0, Math.PI * 2); x.stroke(); }
  x.beginPath(); x.arc(cx - 1.5 * s, cy - 13 * s, 1.5 * s, 0.4, 4.2); x.stroke();   // Wirbel im Laub
  line(x, cx, cy - 6 * s, cx, cy); line(x, cx - 4 * s, cy, cx - 1 * s, cy + (r() - 0.5)); line(x, cx + 1 * s, cy, cx + 4.5 * s, cy);
}
function pineTree(x, cx, cy, s) {
  ink(x); x.fillStyle = MED.wash;
  for (const [top, w, h] of [[-19, 3.6, 7], [-14, 5, 7], [-8.5, 6.4, 7.5]]) {
    x.beginPath(); x.moveTo(cx, cy + top * s); x.lineTo(cx - w * s, cy + (top + h) * s); x.lineTo(cx + w * s, cy + (top + h) * s); x.closePath(); x.fill(); x.stroke();
  }
  line(x, cx, cy - 1 * s, cx, cy); line(x, cx - 3.5 * s, cy, cx + 3.5 * s, cy);
}
function bush(x, cx, cy, s) {
  ink(x, 1.1); x.fillStyle = MED.wash;
  for (const [dx, dy] of [[-3, 0], [0, -2], [3, 0]]) { x.beginPath(); x.arc(cx + dx * s, cy + dy * s, 2.6 * s, 0, Math.PI * 2); x.fill(); x.stroke(); }
  line(x, cx - 5 * s, cy + 3 * s, cx + 5 * s, cy + 3 * s);
}
function tuft(x, cx, cy, s) { ink(x, 1.1); for (const d of [-3, 0, 3]) line(x, cx + d * s, cy, cx + d * 1.6 * s, cy - (4 + Math.abs(d) * -0.4) * s); }
function reeds(x, cx, cy, s) { ink(x, 1.1); for (const d of [-3, 0, 3]) line(x, cx + d * s, cy, cx + d * s, cy - (6 - Math.abs(d) * 0.5) * s); line(x, cx - 7 * s, cy + 2 * s, cx - 2 * s, cy + 2 * s); line(x, cx + 2 * s, cy + 3 * s, cx + 7 * s, cy + 3 * s); }
function stone(x, cx, cy, s, r) {
  ink(x, 1.2); x.fillStyle = MED.wash;
  x.beginPath(); x.moveTo(cx - 6 * s, cy); x.lineTo(cx - 4 * s, cy - 5 * s); x.lineTo(cx + 1 * s, cy - 7 * s); x.lineTo(cx + 6 * s, cy - 3 * s); x.lineTo(cx + 5 * s, cy); x.closePath(); x.fill(); x.stroke();
  line(x, cx - 1 * s, cy - 6 * s, cx + 1 * s, cy - 2 * s); void r;
}

// Muster-Kacheln (128 × 128 Pixel, Pixelverhältnis 2 = 64 px auf dem Schirm)
const T = 128;
const tiles = {
  forest(x, r) {
    for (const [px, py, s, k] of [[18, 36, 1, 'l'], [52, 28, 0.95, 'p'], [90, 42, 1.05, 'l'], [30, 82, 1, 'p'], [72, 72, 1, 'l'], [108, 88, 0.95, 'p'], [14, 120, 0.9, 'l'], [58, 116, 1.05, 'l'], [100, 124, 0.9, 'p']]) (k === 'l' ? leafTree(x, px, py, s, r) : pineTree(x, px, py, s));
  },
  meadow(x) { for (const [px, py] of [[16, 20], [70, 14], [108, 46], [40, 62], [90, 92], [20, 108], [62, 118]]) tuft(x, px, py, 1); },
  scrub(x) { for (const [px, py, s] of [[20, 28, 1], [74, 20, 0.9], [104, 62, 1], [44, 76, 1], [96, 108, 0.9], [18, 112, 1]]) bush(x, px, py, s); },
  wetland(x) { for (const [px, py] of [[22, 30], [80, 24], [48, 72], [104, 80], [20, 108], [74, 116]]) reeds(x, px, py, 1); },
  rock(x, r) { for (const [px, py, s] of [[22, 34, 1], [78, 26, 0.9], [100, 70, 1.1], [42, 80, 1], [86, 116, 0.9], [16, 114, 1]]) stone(x, px, py, s, r); },
  farmland(x, r) {
    ink(x, 1.1);
    for (const [px, py, ang, n] of [[10, 12, 0.15, 5], [72, 8, -0.3, 4], [14, 70, -0.2, 5], [76, 70, 0.25, 5]]) {
      for (let i = 0; i < n; i++) {
        const ox = px - Math.sin(ang) * i * 6, oy = py + Math.cos(ang) * i * 6, len = 36;
        wob(x, [[ox, oy], [ox + Math.cos(ang) * len * 0.5, oy + Math.sin(ang) * len * 0.5 - 2], [ox + Math.cos(ang) * len, oy + Math.sin(ang) * len]], r, 0.5);
      }
    }
  },
  water(x, r) {
    x.strokeStyle = MED.water; x.lineWidth = 1.2;
    for (const [px, py] of [[10, 18], [64, 10], [100, 40], [30, 62], [78, 86], [14, 108], [60, 122]]) wob(x, [[px, py], [px + 6, py - 3], [px + 12, py], [px + 18, py - 3], [px + 24, py]], r, 0.3);
  },
};

export function registerMedievalPatterns(map) {
  drawBuildingHatch(map);
  drawCliffHatch(map);
  let n = 11;
  for (const [name, draw] of Object.entries(tiles)) {
    const [, x] = canvas(T, T), r = rng(n++ * 7919);
    draw(x, r);
    put(map, `pat-${name}`, x.getImageData(0, 0, T, T));
  }
  drawSymbols(map); drawFineHill(map);
}

// ---- Symbole für Hügel, Wellen und Siedlungen (44 × 44 Pixel)
const S = 44;
function shape(x, pts, fill, w = 1.5) {
  x.beginPath(); pts.forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b))); x.closePath();
  x.lineWidth = w + 3.5; x.strokeStyle = MED.paper; x.stroke();   // heller Saum, damit das Zeichen auf Mustern und Wald steht
  x.fillStyle = fill; x.fill(); x.lineWidth = w; x.strokeStyle = MED.ink; x.stroke();
}
const house = (x, px, py, w, h) => { shape(x, [[px, py], [px, py - h], [px + w, py - h], [px + w, py]], MED.paper); shape(x, [[px - 1.5, py - h], [px + w / 2, py - h - w * 0.62], [px + w + 1.5, py - h]], MED.roof); };
const church = (x, px, py, s = 1) => {
  shape(x, [[px, py], [px, py - 8 * s], [px + 8 * s, py - 8 * s], [px + 8 * s, py]], MED.paper);
  shape(x, [[px + 8 * s, py], [px + 8 * s, py - 17 * s], [px + 13 * s, py - 17 * s], [px + 13 * s, py]], MED.paper);
  shape(x, [[px + 7 * s, py - 17 * s], [px + 10.5 * s, py - 27 * s], [px + 14 * s, py - 17 * s]], MED.roof);
  shape(x, [[px - 1 * s, py - 8 * s], [px + 4 * s, py - 13 * s], [px + 9 * s, py - 8 * s]], MED.roof);
  ink(x, 1.3); line(x, px + 10.5 * s, py - 27 * s, px + 10.5 * s, py - 31 * s); line(x, px + 8.7 * s, py - 29 * s, px + 12.3 * s, py - 29 * s);
};
const tower = (x, px, py, w, h) => { shape(x, [[px, py], [px, py - h], [px + w, py - h], [px + w, py]], MED.stone); shape(x, [[px - 1.5, py - h], [px + w / 2, py - h - w * 0.9], [px + w + 1.5, py - h]], MED.roof); };
const symbols = {
  hill(x) {
    shape(x, [[4, 32], [8, 22], [14, 15], [22, 12], [30, 16], [36, 24], [40, 32]], 'rgba(239,224,176,0.7)', 1.4);
    ink(x, 1.1); for (const [a, b, c, d] of [[22, 14, 24, 28], [26, 15, 29, 29], [30, 18, 34, 30], [18, 16, 19, 26]]) line(x, a, b, c, d);
  },
  wave(x) { x.strokeStyle = MED.water; x.lineWidth = 1.8; for (const y of [14, 24, 34]) { x.beginPath(); x.moveTo(8, y); x.quadraticCurveTo(14, y - 6, 20, y); x.quadraticCurveTo(26, y + 6, 32, y); x.stroke(); } },
  hamlet(x) { house(x, 14, 34, 16, 10); },
  village(x) { house(x, 4, 34, 13, 9); church(x, 20, 34, 1); },
  town(x) { house(x, 3, 34, 11, 8); house(x, 30, 34, 11, 8); church(x, 12, 34, 1.15); ink(x, 1.3); line(x, 2, 35, 42, 35); },
  city(x) {
    shape(x, [[2, 36], [2, 24], [42, 24], [42, 36]], MED.stone);
    tower(x, 2, 24, 8, 9); tower(x, 34, 24, 8, 9);
    church(x, 12, 24, 1.2);
    shape(x, [[18, 36], [18, 30], [22, 27], [26, 30], [26, 36]], MED.ink, 1.2);
  },
};
function drawSymbols(map) {
  for (const [name, draw] of Object.entries(symbols)) {
    const [c, x] = canvas(S, S);
    draw(x);
    if (/^(hamlet|village|town|city)$/.test(name)) {   // Pergament-Saum, damit das Siedlungszeichen vom Flächenmuster absteht
      const [, h] = canvas(S, S);
      for (let a = 0; a < 16; a++) h.drawImage(c, Math.cos((a / 16) * Math.PI * 2) * 3, Math.sin((a / 16) * Math.PI * 2) * 3);
      h.globalCompositeOperation = 'source-in'; h.fillStyle = MED.paper; h.fillRect(0, 0, S, S);
      h.globalCompositeOperation = 'source-over'; h.drawImage(c, 0, 0);
      put(map, `med-${name}`, h.getImageData(0, 0, S, S));
      continue;
    }
    put(map, `med-${name}`, x.getImageData(0, 0, S, S));
  }
}

// Gebäudegrundrisse wie im Stich: schräge Strichlage in Tinte, unregelmäßig im Abstand; der Umriss kommt als eigene Linienebene
function drawBuildingHatch(map) {
  const T2 = 12, [, x] = canvas(T2, T2);
  x.fillStyle = 'rgba(122,85,48,0.28)'; x.fillRect(0, 0, T2, T2);
  x.strokeStyle = MED.ink; x.lineWidth = 2.7; x.lineCap = 'butt';
  for (const c of [0, 6, 12, 18, 24]) { x.beginPath(); x.moveTo(c + 1, -1); x.lineTo(-1, c + 1); x.stroke(); }
  put(map, 'med-bldg', x.getImageData(0, 0, T2, T2));
}

// Felsabbruch wie im Stich: an der Kante eine Reihe spitz zulaufender Striche, lang und kurz im Wechsel, nach unten (Abbruchseite) gezogen
function drawCliffHatch(map) {
  const [, x] = canvas(12, 18);
  x.fillStyle = MED.ink;
  for (const [cx, len, w] of [[3, 17, 2.4], [9, 9, 2]]) {
    x.beginPath(); x.moveTo(cx - w / 2, 0); x.lineTo(cx + w / 2, 0); x.lineTo(cx + 0.15, len); x.lineTo(cx - 0.15, len); x.closePath(); x.fill();
  }
  put(map, 'med-cliff', x.getImageData(0, 0, 12, 18));
}

// Feines Hügelzeichen: Umriss mit Strichlage auf der Schattenseite (rechts unten) und Tupfen, wie im Stich
function drawFineHill(map) {
  const W = 96, [, x] = canvas(W, W), r = rng(2025);
  const top = []; const a = [4, 70], b = [14, 44], c = [34, 22], d = [52, 24], e = [68, 28], f = [84, 50], g = [92, 70];
  const pt = (p0, p1, p2, p3, t) => { const u = 1 - t; return [u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0], u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]]; };
  for (let t = 0; t <= 1; t += 0.02) top.push(pt(a, b, c, d, t)); for (let t = 0.02; t <= 1; t += 0.02) top.push(pt(d, e, f, g, t));
  x.beginPath(); top.forEach(([px, py], i) => (i ? x.lineTo(px, py) : x.moveTo(px, py))); x.quadraticCurveTo(50, 78, a[0], a[1]); x.closePath();
  x.fillStyle = 'rgba(239,224,176,0.8)'; x.fill();
  x.save(); x.clip();
  x.strokeStyle = MED.ink; x.lineCap = 'round';
  for (let i = 0; i < 84; i++) { // Strichlage: von der Kammlinie nach unten rechts, rechts dichter und länger
    const k = Math.floor(r() * (top.length - 6)) + 3, [px, py] = top[k], side = k / top.length;
    if (side < 0.3 && r() < 0.65) continue;
    const len = 6 + r() * 16 * (0.4 + side), drift = 0.35 + r() * 0.4;
    x.lineWidth = 0.55 + r() * 0.35; x.globalAlpha = 0.45 + r() * 0.4;
    x.beginPath(); x.moveTo(px + r() * 2, py + 2 + r() * 3); x.quadraticCurveTo(px + len * drift * 0.5, py + len * 0.55, px + len * drift, py + len); x.stroke();
  }
  x.globalAlpha = 0.55; x.fillStyle = MED.ink;
  for (let i = 0; i < 70; i++) { const px = 40 + r() * 50, py = 36 + r() * 36; if (py > 36 + (px - 40) * 0.35) { x.beginPath(); x.arc(px, py, 0.5 + r() * 0.4, 0, Math.PI * 2); x.fill(); } }
  x.restore();
  x.globalAlpha = 1; x.strokeStyle = MED.ink; x.lineWidth = 1.2; x.beginPath(); top.forEach(([px, py], i) => (i ? x.lineTo(px, py) : x.moveTo(px, py))); x.stroke();
  put(map, 'med-hillx', x.getImageData(0, 0, W, W));
}

// Zusatzebenen der historischen Karte. `lastBase` = Anker, vor dem alle Basislayer eingefügt werden.
// Rückgabe: Liste von Layerdefinitionen; Hügelzeichen entlang der Höhenlinien nur, wenn die Quelle existiert.
export function extraLayers(hasContours) {
  const rank = ['max', 1, ['min', 9, ['to-number', ['get', 'population_rank'], 1]]];
  const out = [];
  if (hasContours) {
    out.push({ id: 'med-hills', type: 'symbol', source: 'contours', 'source-layer': 'contours', minzoom: 9.5, maxzoom: 14.6,
      filter: ['>=', ['coalesce', ['get', 'ele'], 0], 250],
      layout: { 'symbol-placement': 'line', 'symbol-spacing': 190, 'icon-image': 'med-hillx', 'icon-size': ['interpolate', ['linear'], ['zoom'], 9.5, 0.4, 14, 0.7],
        'icon-allow-overlap': false, 'icon-padding': 16, 'icon-rotation-alignment': 'viewport' },
      paint: { 'icon-opacity': 0.9 } });
  }
  out.push({ id: 'med-river-waves', type: 'symbol', source: 'basemap', 'source-layer': 'water', minzoom: 10.5,
    filter: ['all', ['any', ['==', ['geometry-type'], 'LineString'], ['==', ['geometry-type'], 'MultiLineString']], ['in', ['get', 'kind'], ['literal', ['river', 'stream']]]],
    layout: { 'symbol-placement': 'line', 'symbol-spacing': 120, 'icon-image': 'med-wave', 'icon-size': 0.55, 'icon-allow-overlap': false, 'icon-padding': 8, 'icon-rotation-alignment': 'map', 'icon-keep-upright': true } });
  // Siedlungszeichen nach Größe: Weiler, Dorf, Stadt, Großstadt; sie verdrängen weder Namen noch einander
  const tiers = [['hamlet', 11.5, ['<=', rank, 2], 0.8], ['village', 10, ['all', ['>=', rank, 3], ['<=', rank, 5]], 0.9], ['town', 8.8, ['all', ['>=', rank, 6], ['<=', rank, 8]], 1], ['city', 8, ['>=', rank, 9], 1.15]];
  for (const [kind, minzoom, cond, size] of tiers) {
    out.push({ id: `med-place-${kind}`, type: 'symbol', source: 'basemap', 'source-layer': 'places', minzoom,
      filter: ['all', ['==', ['get', 'kind'], 'locality'], ['!=', ['get', 'name'], 'Irrel'], cond],
      layout: { 'icon-image': `med-${kind}`, 'icon-size': size * 1.25, 'icon-allow-overlap': true, 'icon-ignore-placement': true } });
  }
  return out;
}

// Flächenmuster über den Landnutzungsflächen: erst ab Zoom 9,5 sichtbar, damit weit draußen die Farbe trägt
export function patternLayer(base, name, image = name) {
  return { id: `land-pat-${name}`, type: 'fill', source: base.source, ...(base['source-layer'] ? { 'source-layer': base['source-layer'] } : {}), filter: base.filter,
    paint: { 'fill-pattern': `pat-${image}`, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0, 10.5, 0.95], 'fill-antialias': false } };
}
export function waterPatternLayer() {
  return { id: 'water-pattern', type: 'fill', source: 'basemap', 'source-layer': 'water', filter: ['==', ['geometry-type'], 'Polygon'],
    paint: { 'fill-pattern': 'pat-water', 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0, 11, 0.8], 'fill-antialias': false } };
}

// Zierde über der Karte: Titelschild (DOM, nur Darstellung)
export function decor(on) {
  const mapEl = document.getElementById('map');
  if (!mapEl) return;
  let c = document.getElementById('med-cartouche');
  if (!c) {
    c = document.createElement('div'); c.id = 'med-cartouche'; c.className = 'med-cartouche'; c.setAttribute('aria-hidden', 'true');
    const t = document.createElement('div'); t.className = 'med-cartouche-t'; t.textContent = 'Die Südeifel';
    const u = document.createElement('div'); u.className = 'med-cartouche-u'; u.textContent = 'anno Domini MMXXVI';
    c.append(t, u); mapEl.append(c);
  }
  c.hidden = !on;
}

// Zeichenerklärung: dieselben Zeichnungen als kleine Zeichenflächen (einmal gefüllt, danach nur ein-/ausgeblendet)
const LEGEND = [['hill', 'Hügel'], ['wave', 'fließendes Wasser'], ['hamlet', 'Weiler'], ['village', 'Dorf mit Kirche'], ['town', 'Stadt'], ['city', 'Großstadt, ummauert']];
export function fillLegend(section) {
  if (!section || section.dataset.filled) return;
  section.dataset.filled = '1';
  for (const [name, label] of LEGEND) {
    const [c, x] = canvas(S, S);
    symbols[name](x);
    c.className = 'med-leg-sym'; c.setAttribute('aria-hidden', 'true');
    const row = document.createElement('div'); row.className = 'legend-row med-leg-row';
    row.append(c, document.createTextNode(label)); section.append(row);
  }
}

// ---- Seeungeheuer und Drachen: sehr vereinzelt, erst bei starkem Zoom; die Zeichnungen stehen in fauna.js
// Orte von Hand gesetzt und gegen die Kartendaten geprüft (Seen: Wasserfläche, Drachen: Waldfläche unter dem Punkt).
const FAUNA = [
  [6.7564, 50.1008, 'sea-a'], [6.8494, 50.1761, 'sea-c'], [6.9259, 50.1311, 'sea-d'],
  [7.2685, 50.4162, 'sea-b'], [5.9, 49.897, 'sea-a', true], [6.8575, 50.1695, 'sea-b', true],
  [6.9, 49.6, 'dragon-a'], [6.3, 50.1, 'dragon-b'], [6.1, 50.2, 'dragon-c', true],
  [7.0, 50.2, 'dragon-a', true], [6.45, 50.12, 'dragon-b', true], [6.36, 49.86, 'dragon-c'],
];
export const faunaPoints = () => ({ type: 'FeatureCollection', features: FAUNA.map(([lon, lat, name, mirror], i) => ({ type: 'Feature', id: i, properties: { img: `med-${name}${mirror ? '-r' : ''}`, kind: name.split('-')[0] }, geometry: { type: 'Point', coordinates: [lon, lat] } })) });
export function registerFauna(map) {
  for (const name of Object.keys(FAUNA_DRAWINGS)) for (const mirror of [false, true]) {
    const [, x] = canvas(FAUNA_SIZE, FAUNA_SIZE);
    paintFauna(name, x, mirror);
    put(map, `med-${name}${mirror ? '-r' : ''}`, x.getImageData(0, 0, FAUNA_SIZE, FAUNA_SIZE));
  }
}
export const FAUNA_SOURCE = 'med-fauna';
export function faunaLayers() {
  const size = ['interpolate', ['linear'], ['zoom'], 13, 0.8, 15.5, 1.7];
  return [{ id: 'med-fauna', type: 'symbol', source: FAUNA_SOURCE, minzoom: 13,
    layout: { 'icon-image': ['get', 'img'], 'icon-size': size, 'icon-allow-overlap': true, 'icon-ignore-placement': true },
    paint: { 'icon-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 13.6, 1] } }];
}
