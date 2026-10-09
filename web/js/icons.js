// Karten-Symbole aus den uxwing-SVGs (web/icons, siehe README dort). MapLibre bekommt sie als Bitmaps:
// Meldungen als runde Plakette in der Stufenfarbe mit hellem oder dunklem Zeichen, Flugzeuge als Zeichen
// mit Umriss, das sich nach dem Kurs dreht. Pro Stufe ein Bild; beim Wechsel Hell/Dunkel neu gezeichnet.
export const iconStatus = { missing: [], errors: [] }; // für den Kartenhinweis, wenn Icons fehlen
export const CHIP_ICONS = ['stau', 'baustelle', 'sperrung', 'warnung', 'hochwasser', 'pegel', 'strahlung', 'luft', 'temperatur', 'beben', 'feuer', 'bahn', 'natur'];
const TRAFFIC_ICONS = ['stau', 'baustelle', 'sperrung', 'bahn'];
const TRAFFIC_LEVELS = ['yellow', 'orange', 'red', 'black'];
const LEVELS = ['info', 'notice', 'warning', 'critical', 'yellow', 'orange', 'red', 'black'];
const CHIP_PX = 67;   // Verkehrsplaketten: pixelRatio 2, also 33,5 px (3,5 px größer als vorher) inkl. Rand und Schatten
const BARE_PX = 56;   // Zeichen ohne Plakette: 28 px
const PLANE_PX = 56;

// SVG ohne width/height (uxwing liefert nur viewBox) bekommt Maße aus der viewBox, sonst rechnet der Browser mit 300×150.
async function loadGlyph(name) {
  const res = await fetch(`icons/${name}.svg`);
  if (!res.ok) throw new Error(`${name}: ${res.status}`);
  let text = await res.text();
  const vb = /viewBox="([\d.\s-]+)"/.exec(text)?.[1].trim().split(/\s+/).map(Number);
  const [w, h] = vb && vb.length === 4 ? [vb[2], vb[3]] : [100, 100];
  text = text.replace(/<svg\b([^>]*)>/, (m, attrs) => `<svg${attrs.replace(/\s(width|height)="[^"]*"/g, '')} width="${w}" height="${h}">`);
  const url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml' }));
  try {
    const img = new Image();
    // onload statt decode(): decode() verweigert Safari bei SVG-Bildern gelegentlich
    await new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error('Bild nicht lesbar')); img.src = url; });
    return { img, w, h };
  } finally {
    URL.revokeObjectURL(url);
  }
}

function canvas(px) {
  const c = document.createElement('canvas');
  c.width = c.height = px;
  return [c, c.getContext('2d', { willReadFrequently: true })];
}

// Zeichen einfarbig einfärben (Alphakanal der SVG als Schablone) und mittig in eine Box von `box` px einpassen
function tinted(glyph, colour, box) {
  const [c, x] = canvas(box);
  const k = Math.min(box / glyph.w, box / glyph.h);
  const w = glyph.w * k, h = glyph.h * k;
  // zweimal zeichnen: die Kantenpixel der dünnen uxwing-Linien werden dichter und behalten auf kleinen Plaketten Kontrast
  x.drawImage(glyph.img, (box - w) / 2, (box - h) / 2, w, h);
  x.drawImage(glyph.img, (box - w) / 2, (box - h) / 2, w, h);
  x.globalCompositeOperation = 'source-in';
  x.fillStyle = colour;
  x.fillRect(0, 0, box, box);
  return c;
}

function chip(glyph, fill, ink) {
  const [c, x] = canvas(CHIP_PX);
  const m = CHIP_PX / 2, r = m - 6;               // Platz für Schatten am Rand
  // Schatten und dunkler Außenring heben die Plakette von jedem Kartengrund ab, weißer Ring trennt sie von der Füllung
  x.save();
  x.shadowColor = 'rgba(0,0,0,0.5)'; x.shadowBlur = 5; x.shadowOffsetY = 1.5;
  x.beginPath(); x.arc(m, m, r + 2, 0, Math.PI * 2); x.fillStyle = '#161616'; x.fill();
  x.restore();
  x.beginPath(); x.arc(m, m, r, 0, Math.PI * 2); x.fillStyle = '#fff'; x.fill();
  x.beginPath(); x.arc(m, m, r - 3, 0, Math.PI * 2); x.fillStyle = fill; x.fill();
  const g = Math.round((r - 3) * 2 * 0.74);
  x.drawImage(tinted(glyph, ink, g), m - g / 2, m - g / 2);
  return x.getImageData(0, 0, CHIP_PX, CHIP_PX);
}

// Zeichen ohne Kreis: einfarbig mit schmalem Umriss in der Kartenfarbe, damit es auf Relief, Wald und Straßen lesbar bleibt
// Relative Helligkeit (sRGB, WCAG) einer #rrggbb-Farbe; ohne lesbare Farbe 0.5
function lum(css) {
  const str = String(css).trim();
  let rgb;
  const h = /^#?([0-9a-f]{6})$/i.exec(str), f = /^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)/i.exec(str);
  if (h) rgb = [0, 2, 4].map((i) => parseInt(h[1].slice(i, i + 2), 16));
  else if (f) rgb = [f[1], f[2], f[3]].map(Number);
  else return 0.5;
  const v = rgb.map((u) => u / 255).map((u) => (u <= 0.03928 ? u / 12.92 : ((u + 0.055) / 1.055) ** 2.4));
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);

/** Innere Umrissfarbe: die Farbe mit dem größten Kontrast zur Füllung (Weiß oder Fast-Schwarz). */
let styleOverride = null;   // Karte „um 1450“: Pergament statt Weiß als helle Saumfarbe, Tinte statt Fast-Schwarz
export function setIconStyle(o) { styleOverride = o; }
export function haloFor(fill) {
  if (styleOverride) return lum(fill) < 0.4 ? styleOverride.light : styleOverride.dark;
  return ratio(fill, '#10151c') >= ratio(fill, '#ffffff') ? '#10151c' : '#ffffff';
}
const opposite = (c) => (styleOverride ? (c === styleOverride.light ? styleOverride.dark : styleOverride.light) : c === '#ffffff' ? '#10151c' : '#ffffff');

// Doppelter Umriss, damit ein Zeichen auf jedem Kartengrund steht: innen ein kräftiger Saum in der Kontrastfarbe zur Füllung (trennt das
// Zeichen vom Grund), außen ein feiner Saum in der Gegenfarbe (trennt den Saum vom Grund). Ein einfarbiger Saum scheitert immer auf dem Grund,
// der ihm gleicht: heller Saum auf Radar-Grün oder Papier, dunkler Saum auf Wald und Schatten.
function ring(x, back, o, r, n) {
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    x.drawImage(back, o + Math.cos(a) * r, o + Math.sin(a) * r);
  }
}
function outlined(x, glyph, fill, g, o, size, disc) {
  const inner = haloFor(fill), outer = opposite(inner);
  ring(x, tinted(glyph, outer, g), o, 3.4, 20);
  ring(x, tinted(glyph, inner, g), o, 2, 14);
  if (disc) {   // runde Zeichen: Scheibe in der Saumfarbe, sonst scheint der Grund durch die Aussparung
    const r = (Math.min(glyph.w, glyph.h) * Math.min(g / glyph.w, g / glyph.h)) / 2;
    x.beginPath(); x.arc(size / 2, size / 2, r, 0, Math.PI * 2); x.fillStyle = inner; x.fill();
  }
  x.drawImage(tinted(glyph, fill, g), o, o);
}

// Runde Zeichen (Kreis mit Aussparung: "!", Strahlungszeichen) bekommen eine Scheibe darunter
const DISC_GLYPHS = new Set(['warnung', 'strahlung']);

// Zeichen ohne Kreis: einfarbig, doppelter Umriss (siehe oben). Der dritte Parameter bleibt aus Gründen der Aufrufer, der Umriss richtet sich nach der Füllung.
function bare(glyph, fill, _halo, disc = false) {
  const [c, x] = canvas(BARE_PX);
  const g = BARE_PX - 8, o = (BARE_PX - g) / 2;
  outlined(x, glyph, fill, g, o, BARE_PX, disc);
  return x.getImageData(0, 0, BARE_PX, BARE_PX);
}

function plane(glyph, fill, _halo) {
  const [c, x] = canvas(PLANE_PX);
  const g = Math.round(PLANE_PX * 0.72), o = (PLANE_PX - g) / 2;
  outlined(x, glyph, fill, g, o, PLANE_PX, false);
  return x.getImageData(0, 0, PLANE_PX, PLANE_PX);
}

// Militär: violetter Ring mit hellem Rand um das Zeichen; Hubschrauber (Seitenansicht) bleibt aufrecht, siehe lage.js
function badge(glyph, fill, halo) {
  const [c, x] = canvas(PLANE_PX);
  const r = PLANE_PX / 2 - 3;
  x.beginPath(); x.arc(PLANE_PX / 2, PLANE_PX / 2, r, 0, Math.PI * 2);
  x.fillStyle = halo; x.globalAlpha = 0.9; x.fill(); x.globalAlpha = 1;
  x.lineWidth = 3; x.strokeStyle = fill; x.stroke();
  const g = Math.round(PLANE_PX * 0.56), o = (PLANE_PX - g) / 2;
  x.drawImage(tinted(glyph, fill, g), o, o);
  return x.getImageData(0, 0, PLANE_PX, PLANE_PX);
}

// Temperaturskala der Wetterstationen: 33 Farbfelder von -45 bis 51 °C in 3-Grad-Schritten (Feld k = -45 + 3k, auf das nächste gerundet),
// Farben aus der vom Betreiber vorgegebenen Skala übernommen. Die Plakette je Feld heißt wx-<k>.
export const TEMP_COLOURS = ['#2d0330', '#5b0e60', '#891a91', '#b726c1', '#e532f6', '#b726f5', '#891af4', '#5b0ef4', '#2d03f4', '#1131f4', '#2962f5', '#4294f6', '#5ac5f9', '#69e2ed', '#69e2a5', '#69e283', '#69e265', '#6eec51', '#72f64a', '#fefe54', '#f9e24c', '#f5ca44', '#f2b23e', '#f09b38', '#d8822f', '#d66c2a', '#cb5530', '#b83f2b', '#a52b27', '#9b1e25', '#a52136', '#b72663', '#e93394'];
export const TEMP_MIN = -45, TEMP_STEP = 3;
export const tempClass = (t) => Math.max(0, Math.min(TEMP_COLOURS.length - 1, Math.round((t - TEMP_MIN) / TEMP_STEP)));
export const MIL_COLOUR = '#8e44ad';
// Natürliche Landmarken: Plakette in Artfarbe mit weißem Zeichen (Bild nat-<Art>); Zeichen: OpenStreetMap Carto und Maki (CC0), siehe tools/fetch_icons.sh
export const NATURE_CHIP = { cave: ['hoehle', '#5b4636'], waterfall: ['wasserfall', '#1f6fb5'], viewpoint: ['fernglas', '#8a3fb0'],
  spring: ['quelle', '#12857f'], rock: ['gebirge', '#8c6b32'], volcano: ['vulkan', '#c0401f'],
  castle: ['burg', '#7a2f2f'], ruins: ['burg', '#6f6a62'], archaeological: ['denkmal', '#a0672a'], monastery: ['kloster', '#3f5f8a'], building: ['gebaeude', '#6b4f7a'] };
// Bildzeichen der Karte „um 1450“: Burg, Ruine, Kloster/Kirche, Fundstelle, Haus. Tinte mit Pergamentfüllung und zinnoberroten Dächern, helle Kontur
// für den Stand auf jedem Grund. Eigene Zeichnung, keine Vorlage; Bildname med-<Art>.
const MED_INK = '#3a2614', MED_PAPER = '#efe0b0', MED_STONE = '#d9c68f', MED_ROOF = '#a33a22', MED_WATER = '#8fb0ad';
const medDraw = {
  castle(x, P) {
    P([[4, 34], [4, 12], [14, 12], [14, 34]], MED_PAPER); P([[26, 34], [26, 12], [36, 12], [36, 34]], MED_PAPER);
    P([[14, 34], [14, 20], [26, 20], [26, 34]], MED_STONE);
    P([[3, 12], [9, 3], [15, 12]], MED_ROOF); P([[25, 12], [31, 3], [37, 12]], MED_ROOF);
    P([[17, 34], [17, 28], [20, 25], [23, 28], [23, 34]], MED_INK);
  },
  ruins(x, P) {
    P([[9, 34], [9, 15], [14, 19], [18, 9], [22, 20], [27, 13], [31, 34]], MED_STONE);
    P([[18, 34], [18, 27], [21, 27], [21, 34]], MED_INK);
    P([[3, 34], [5, 30], [8, 34]], MED_STONE); P([[32, 34], [35, 29], [38, 34]], MED_STONE);
  },
  monastery(x, P) {
    P([[5, 34], [5, 21], [26, 21], [26, 34]], MED_PAPER); P([[3, 21], [15, 11], [28, 21]], MED_ROOF);
    P([[26, 34], [26, 14], [36, 14], [36, 34]], MED_PAPER); P([[25, 14], [31, 3], [37, 14]], MED_ROOF);
    P([[11, 34], [11, 28], [14, 25], [17, 28], [17, 34]], MED_INK);
    x.beginPath(); x.moveTo(15, 11); x.lineTo(15, 5); x.moveTo(12.5, 7.5); x.lineTo(17.5, 7.5); x.lineWidth = 2; x.strokeStyle = MED_INK; x.stroke();
  },
  archaeological(x, P) {
    P([[7, 34], [7, 16], [14, 16], [14, 34]], MED_STONE); P([[26, 34], [26, 16], [33, 16], [33, 34]], MED_STONE);
    P([[4, 16], [4, 9], [36, 9], [36, 16]], MED_STONE);
  },
  cave(x, P) { P([[3, 34], [8, 18], [20, 9], [32, 18], [37, 34]], MED_STONE); P([[15, 34], [15, 26], [20, 21], [25, 26], [25, 34]], MED_INK); },
  waterfall(x, P) {
    P([[4, 8], [36, 8], [36, 16], [4, 16]], MED_STONE);
    for (const a of [10, 18, 26]) P([[a, 16], [a + 5, 16], [a + 5, 31], [a, 31]], MED_WATER);
    P([[6, 34], [12, 29], [28, 29], [34, 34]], MED_WATER);
  },
  viewpoint(x, P) {
    P([[14, 34], [14, 14], [26, 14], [26, 34]], MED_PAPER);
    P([[12, 14], [12, 7], [16, 7], [16, 10], [19, 10], [19, 7], [22, 7], [22, 10], [25, 10], [25, 7], [28, 7], [28, 14]], MED_PAPER);
    P([[18, 34], [18, 27], [20, 25], [22, 27], [22, 34]], MED_INK);
  },
  spring(x, P) {
    P([[5, 28], [9, 23], [20, 21], [31, 23], [35, 28], [28, 33], [12, 33]], MED_WATER);
    P([[20, 5], [24, 12], [20, 17], [16, 12]], MED_WATER);
  },
  rock(x, P) { P([[4, 34], [7, 22], [15, 13], [25, 12], [33, 21], [36, 34]], MED_STONE); P([[24, 34], [27, 28], [32, 26], [37, 34]], MED_STONE); },
  volcano(x, P) {
    P([[3, 34], [15, 13], [25, 13], [37, 34]], MED_STONE); P([[15, 13], [18, 10], [22, 10], [25, 13]], MED_ROOF);
    P([[19, 8], [17, 4], [21, 1], [25, 4], [22, 8]], '#e6dfcc');
  },
  peak(x, P, pass) {
    P([[2, 34], [14, 11], [22, 24], [28, 15], [38, 34]], MED_STONE);
    if (pass === 'ink') { x.beginPath(); for (const [a, b, c, d] of [[14, 14, 18, 30], [16, 17, 22, 32], [28, 18, 32, 31], [30, 21, 35, 32]]) { x.moveTo(a, b); x.lineTo(c, d); } x.lineWidth = 1.2; x.strokeStyle = MED_INK; x.stroke(); }
  },
  building(x, P) {
    P([[7, 34], [7, 20], [33, 20], [33, 34]], MED_PAPER); P([[4, 20], [20, 7], [36, 20]], MED_ROOF);
    P([[17, 34], [17, 27], [20, 24], [23, 27], [23, 34]], MED_INK); P([[10, 24], [14, 24], [14, 28], [10, 28]], MED_INK);
  },
};
export function registerMedieval(map, colors = null) {
  const S = 44;
  // Bildgröße muss der des ersetzten Zeichens entsprechen (updateImage), gezeichnet wird immer im 44er Raster
  const mk = (fn, size = S) => { const c = document.createElement('canvas'); c.width = size; c.height = size; const x = c.getContext('2d', { willReadFrequently: true }); x.scale(size / S, size / S); x.lineJoin = 'round'; x.lineCap = 'round'; fn(x); return x.getImageData(0, 0, size, size); };
  const polyPass = (x, pass) => (pts, fill) => {
    x.beginPath(); pts.forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b))); x.closePath();
    if (pass === 'halo') { x.lineWidth = 5; x.strokeStyle = MED_PAPER; x.stroke(); x.fillStyle = MED_PAPER; x.fill(); }
    else { x.fillStyle = fill; x.fill(); x.lineWidth = 1.6; x.strokeStyle = MED_INK; x.stroke(); }
  };
  for (const [kind, draw] of Object.entries(medDraw)) {
    put(map, `med-${kind}`, mk((x) => {
      x.translate((S - 40) / 2, (S - 40) / 2 + 1);
      for (const pass of ['halo', 'ink']) { if (pass === 'halo') x.globalAlpha = 0.9; draw(x, polyPass(x, pass), pass); x.globalAlpha = 1; }
    }));
  }
  if (!colors) return;
  // Verkehrszeichen als Rundmarke in Pergament mit Ring in der Stufenfarbe: Baustelle = Hammer, Sperrung = Schranke, Stau = Karren in Reihe
  const ringCol = { yellow: '#d9a520', orange: '#c8661c', red: '#a33a22', black: '#2b1d10' };
  const oct = (cx, cy, r) => Array.from({ length: 8 }, (_, i) => [cx + Math.cos((i * Math.PI) / 4) * r, cy + Math.sin((i * Math.PI) / 4) * r]);
  const pict = {
    baustelle: (P) => { P([[19, 13], [22, 13], [22, 31], [19, 31]], '#8a6a3c'); P([[10, 8], [30, 8], [30, 16], [10, 16]], MED_STONE); },
    sperrung: (P) => { P([[9, 14], [12, 14], [12, 31], [9, 31]], '#8a6a3c'); P([[28, 14], [31, 14], [31, 31], [28, 31]], '#8a6a3c'); P([[7, 17], [33, 17], [33, 23], [7, 23]], MED_ROOF); },
    stau: (P) => { P([[7, 18], [19, 18], [19, 27], [7, 27]], '#8a6a3c'); P([[22, 18], [34, 18], [34, 27], [22, 27]], '#8a6a3c'); for (const cx of [11, 16, 26, 31]) P(oct(cx, 29, 3), MED_PAPER); },
  };
  for (const [n, draw] of Object.entries(pict)) {
    for (const [lv, col] of Object.entries(ringCol)) {
      put(map, `ico-${n}-${lv}`, mk((x) => {
        x.translate((S - 40) / 2, (S - 40) / 2);
        x.beginPath(); x.arc(20, 20, 19, 0, Math.PI * 2); x.fillStyle = MED_PAPER; x.fill(); x.lineWidth = 1.4; x.strokeStyle = MED_INK; x.stroke();
        x.beginPath(); x.arc(20, 20, 16.2, 0, Math.PI * 2); x.lineWidth = 3.2; x.strokeStyle = col; x.stroke();
        x.save(); x.beginPath(); x.arc(20, 20, 14.2, 0, Math.PI * 2); x.clip(); x.translate(20, 20); x.scale(0.78, 0.78); x.translate(-20, -20);
        draw(polyPass(x, 'ink')); x.restore();
      }, CHIP_PX));
    }
  }
  // Datenzeichen im Stil der Karte: Pegel als Wellenlinien in der Stufenfarbe, Flugzeuge als Vogel von oben (Militär zinnoberrot)
  for (const lv of ['info', 'notice', 'warning', 'critical']) {
    const col = lv === 'info' ? '#3f6b72' : colors[lv];
    put(map, `ico-pegel-${lv}`, mk((x) => {
      x.translate((S - 40) / 2, (S - 40) / 2);
      for (const [pass, w, c] of [['halo', 7, MED_PAPER], ['ink', 2.8, col]]) {
        x.beginPath();
        for (const y of [12, 21, 30]) { x.moveTo(3, y); x.quadraticCurveTo(9, y - 7, 15, y); x.quadraticCurveTo(21, y + 7, 27, y); x.quadraticCurveTo(33, y - 7, 38, y); }
        x.lineWidth = w; x.strokeStyle = c; x.stroke(); void pass;
      }
    }, BARE_PX));
    // Drache von oben (Kopf nach Norden, Fledermausflügel mit Zacken, Schwanz mit Pfeilspitze): rechte Hälfte, die linke wird gespiegelt
    const half = [[20, 1.5], [21.6, 3.2], [23.2, 2.6], [22.3, 5.2], [22, 9.5], [23.6, 12.5], [30, 8.2], [38.2, 6.2], [35.2, 11.4], [38.6, 17.6], [33.4, 16.8], [34.6, 23.4], [28.4, 20.6], [23, 21.4], [22.4, 27.5], [21.4, 32.5], [24.4, 34.2], [20, 39]];
    const bird = [...half, ...half.slice(1, -1).reverse().map(([a, b]) => [40 - a, b])];
    for (const [prefix, col2] of [['plane-', MED_INK], ['heli-', MED_INK], ['mplane-', MED_ROOF], ['mheli-', MED_ROOF]]) {
      put(map, `${prefix}${lv}`, mk((x) => {
        x.translate((S - 40) / 2, (S - 40) / 2);
        const P = (stroke, w, fill) => { x.beginPath(); bird.forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b))); x.closePath(); if (stroke) { x.lineWidth = w; x.strokeStyle = stroke; x.stroke(); } if (fill) { x.fillStyle = fill; x.fill(); } };
        P(MED_PAPER, 6, MED_PAPER); P(MED_INK, 1.2, col2);
      }, PLANE_PX));
    }
  }
}
const put = (map, id, data) => (map.hasImage(id) ? map.updateImage(id, data) : map.addImage(id, data, { pixelRatio: 2 }));

// colors: { info, notice, warning, critical, yellow, orange, red, black, ink, bg } (CSS-Farben). Rückgabe: true, wenn mindestens die Plaketten da sind.
export async function registerIcons(map, colors) {
  const names = [...new Set([...CHIP_ICONS, 'flug', 'hubschrauber', 'tanken', ...Object.values(NATURE_CHIP).map(([g]) => g)])];
  const results = await Promise.allSettled(names.map(async (n) => [n, await loadGlyph(n)]));
  const loaded = Object.fromEntries(results.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : [])));
  const missing = names.filter((n) => !loaded[n]);
  if (loaded.bahn) put(map, 'stop-bahn', bare(loaded.bahn, colors.ink, colors.bg));
  if (loaded.tanken) put(map, 'stop-tanken', bare(loaded.tanken, '#c2570c', colors.bg));
  if (loaded.temperatur) TEMP_COLOURS.forEach((col, k) => put(map, `wx-${k}`, bare(loaded.temperatur, col, colors.bg)));
  for (const [kind, [glyph, col]] of Object.entries(NATURE_CHIP)) if (loaded[glyph]) put(map, `nat-${kind}`, bare(loaded[glyph], col, colors.bg));
  iconStatus.missing = missing;
  iconStatus.errors = results.flatMap((r) => (r.status === 'rejected' ? [String(r.reason?.message ?? r.reason)] : []));
  if (missing.length) console.warn('Icons fehlen (tools/fetch_icons.sh ausführen):', missing.join(', '), iconStatus.errors.join('; '));
  for (const lv of LEVELS) {
    const ink = lv === 'notice' || lv === 'yellow' ? '#1b2b30' : '#fff'; // helles Gelb braucht dunkles Zeichen
    try {
      // Plakette nur für den Verkehr (Stufenfarbe trägt die Bedeutung); alles andere als freies Zeichen in Stufenfarbe
      for (const n of CHIP_ICONS) {
        if (!loaded[n]) continue;
        if (TRAFFIC_ICONS.includes(n)) put(map, `ico-${n}-${lv}`, chip(loaded[n], colors[lv], ink));
        else if (!TRAFFIC_LEVELS.includes(lv)) put(map, `ico-${n}-${lv}`, bare(loaded[n], lv === 'info' ? (colors.muted ?? colors.ink) : colors[lv], colors.bg, DISC_GLYPHS.has(n)));   // Normalzustand tritt zurück: gedämpftes Grau, Signalfarbe erst ab "notice"
      }
      const civil = lv === 'info' ? colors.ink : colors[lv];
      if (['yellow', 'orange', 'red', 'black'].includes(lv)) continue; // Verkehrsstufen gibt es nur als Plakette
      if (loaded.flug) {
        put(map, `plane-${lv}`, plane(loaded.flug, civil, colors.bg));
        put(map, `mplane-${lv}`, badge(loaded.flug, MIL_COLOUR, colors.bg));
      }
      if (loaded.hubschrauber) {
        put(map, `heli-${lv}`, plane(loaded.hubschrauber, civil, colors.bg));
        put(map, `mheli-${lv}`, badge(loaded.hubschrauber, MIL_COLOUR, colors.bg));
      }
    } catch (err) {
      iconStatus.errors.push(String(err?.message ?? err));
      console.warn('Icon konnte nicht gezeichnet werden:', err);
      return false;
    }
  }
  return Boolean(loaded.warnung && loaded.stau);
}

// Signaturen für Vegetation (Kacheln 24 x 24, pixelRatio 2 = 12 px auf dem Schirm), je Klasse hell und dunkel.
// Fein und halbtransparent, damit die Farbfläche trägt und Straßen, Höhenlinien und Beschriftung darüber lesbar bleiben.
// Die Zeichnung wiederholt sich nahtlos (Formen liegen innerhalb der Kachel, Furchen laufen bis zum Rand).
const LAND_INK = {
  light: { forest: '#2a5e33', meadow: '#6f9a3a', grass: '#4f8a38', scrub: '#5d6b36', heath: '#7a4f78', farmland: '#a8923f', orchard: '#4f7a2c',
    vineyard: '#7a6a24', allotment: '#5f8a3a', wetland: '#2f7a78', rock: '#6f665a', sand: '#b29a54', cemetery: '#4c6e47' },
  dark: { forest: '#8fd09a', meadow: '#a8d070', grass: '#8cd08a', scrub: '#c0cc88', heath: '#d6a8d0', farmland: '#d9c27a', orchard: '#b8e08a',
    vineyard: '#e0d083', allotment: '#a8d890', wetland: '#7fd0c8', rock: '#bdb4a6', sand: '#e6d08c', cemetery: '#a8cca4' },
};
const LAND_DRAW = {
  // Baumkronen: zwei Kreise mit Mittelpunkt, versetzt
  forest: (x) => { for (const [cx, cy, r] of [[7, 7, 4], [18, 17, 4.5]]) { x.beginPath(); x.arc(cx, cy, r, 0, Math.PI * 2); x.stroke(); x.beginPath(); x.arc(cx, cy, 0.9, 0, Math.PI * 2); x.fill(); } },
  // Wiese: Grasbüschel (drei Halme)
  meadow: (x) => { for (const [cx, cy] of [[6, 9], [17, 19]]) { x.beginPath(); x.moveTo(cx - 2.5, cy); x.lineTo(cx - 3.5, cy - 4); x.moveTo(cx, cy); x.lineTo(cx, cy - 5); x.moveTo(cx + 2.5, cy); x.lineTo(cx + 3.5, cy - 4); x.stroke(); } },
  // Rasen, Park: feine Punkte
  grass: (x) => { for (const [cx, cy] of [[4, 5], [14, 4], [9, 12], [20, 11], [5, 19], [16, 20]]) { x.beginPath(); x.arc(cx, cy, 0.9, 0, Math.PI * 2); x.fill(); } },
  // Busch: kleine Ringe in Gruppen
  scrub: (x) => { for (const [cx, cy, r] of [[6, 7, 2.2], [11, 10, 1.8], [18, 6, 2], [8, 18, 2], [18, 18, 2.4]]) { x.beginPath(); x.arc(cx, cy, r, 0, Math.PI * 2); x.stroke(); } },
  // Heide: Heidekrautzweige, kurze Y
  heath: (x) => { for (const [cx, cy] of [[6, 10], [17, 8], [12, 20]]) { x.beginPath(); x.moveTo(cx, cy); x.lineTo(cx, cy - 4); x.moveTo(cx, cy - 2); x.lineTo(cx - 2, cy - 5); x.moveTo(cx, cy - 2); x.lineTo(cx + 2, cy - 5); x.stroke(); } },
  // Acker: Furchen
  farmland: (x) => { x.beginPath(); for (const y of [4, 10, 16, 22]) { x.moveTo(0, y); x.lineTo(24, y); } x.stroke(); },
  // Obstwiese: Baumpunkte im Raster mit Ring
  orchard: (x) => { for (const [cx, cy] of [[6, 6], [18, 6], [6, 18], [18, 18]]) { x.beginPath(); x.arc(cx, cy, 2.4, 0, Math.PI * 2); x.stroke(); x.beginPath(); x.arc(cx, cy, 0.7, 0, Math.PI * 2); x.fill(); } },
  // Weinberg: senkrechte Rebzeilen, gestrichelt
  vineyard: (x) => { x.setLineDash([3, 2]); x.beginPath(); for (const px of [3, 9, 15, 21]) { x.moveTo(px, 0); x.lineTo(px, 24); } x.stroke(); x.setLineDash([]); },
  // Kleingarten: Raster
  allotment: (x) => { x.beginPath(); x.moveTo(0, 12); x.lineTo(24, 12); x.moveTo(12, 0); x.lineTo(12, 24); x.stroke(); },
  // Moor: Schilfbüschel auf Wasserstrich
  wetland: (x) => { for (const [cx, cy] of [[6, 8], [17, 18]]) { x.beginPath(); x.moveTo(cx - 5, cy); x.lineTo(cx + 5, cy); x.moveTo(cx - 3, cy); x.lineTo(cx - 3, cy - 3); x.moveTo(cx, cy); x.lineTo(cx, cy - 4); x.moveTo(cx + 3, cy); x.lineTo(cx + 3, cy - 3); x.stroke(); } },
  // Fels: eckige Splitter
  rock: (x) => { for (const pts of [[[4, 8], [9, 5], [11, 10], [6, 12]], [[15, 17], [20, 15], [22, 21], [16, 22]]]) { x.beginPath(); pts.forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b))); x.closePath(); x.stroke(); } },
  // Sand: Körner
  sand: (x) => { for (const [cx, cy] of [[3, 4], [12, 7], [20, 3], [7, 15], [17, 14], [4, 21], [21, 21]]) { x.fillRect(cx, cy, 1.4, 1.4); } },
  // Friedhof: Kreuze
  cemetery: (x) => { for (const [cx, cy] of [[6, 7], [17, 17]]) { x.beginPath(); x.moveTo(cx, cy - 3); x.lineTo(cx, cy + 3); x.moveTo(cx - 2, cy - 1); x.lineTo(cx + 2, cy - 1); x.stroke(); } },
};
export function registerLandPatterns(map) {
  for (const [lv, inks] of Object.entries(LAND_INK)) {
    for (const [cls, draw] of Object.entries(LAND_DRAW)) {
      const c = document.createElement('canvas'); c.width = 24; c.height = 24;
      const x = c.getContext('2d', { willReadFrequently: true });
      x.strokeStyle = inks[cls]; x.fillStyle = inks[cls]; x.lineWidth = 1; x.lineCap = 'round'; x.lineJoin = 'round'; x.globalAlpha = lv === 'dark' ? 0.6 : 0.65;
      draw(x);
      const id = `lp-${cls}-${lv}`, data = x.getImageData(0, 0, 24, 24);
      if (map.hasImage(id)) map.updateImage(id, data); else map.addImage(id, data, { pixelRatio: 2 });
    }
  }
}

// Straßenschilder als dehnbare Hintergrundbilder (icon-text-fit): Rahmen und Füllung, der Text kommt von der Karte.
// A = Autobahn (blau, weiße Schrift), B = Bundesstraße (gelb), L/K = Landes- und Kreisstraße (weiß, schwarzer Rand).
const SIGNS = { 'sign-autobahn': ['#1f5fbf', '#ffffff'], 'sign-bundes': ['#f5c400', '#111111'], 'sign-land': ['#ffffff', '#111111'] };
export function registerSigns(map) {
  try {
    for (const [id, [fill, edge]] of Object.entries(SIGNS)) {
      const W = 32, H = 24; // mit pixelRatio 2: 16 × 12 px, Mittelstück dehnbar
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const x = c.getContext('2d', { willReadFrequently: true });
      const rr = (inset, r) => { x.beginPath(); x.roundRect(inset, inset, W - 2 * inset, H - 2 * inset, r); };
      rr(0.5, 5); x.fillStyle = id === 'sign-autobahn' ? '#ffffff' : '#111111'; x.fill();   // äußerer Rand
      rr(2, 4); x.fillStyle = fill; x.fill();
      if (id === 'sign-autobahn') { rr(3.5, 3); x.lineWidth = 1.5; x.strokeStyle = '#ffffff'; x.stroke(); } // weißer Innenrand wie beim Autobahnschild
      else { rr(3.5, 3); x.lineWidth = 1.5; x.strokeStyle = edge; x.stroke(); }
      const data = x.getImageData(0, 0, W, H);
      const opts = { pixelRatio: 2, stretchX: [[10, 22]], stretchY: [[9, 15]], content: [8, 6, 24, 18] };
      if (map.hasImage(id)) map.updateImage(id, data); else map.addImage(id, data, opts);
    }
    // Klippenschraffe: lange und kurze Striche im Wechsel, von der Wandlinie nach unten (= zur Abbruchseite, rechts der Linienrichtung).
    // SDF, damit die Farbe je Hell/Dunkel per icon-color gesetzt wird. Bild 16 x 10, bei pixelRatio 2 also 8 x 5 px mit zwei Strichen.
    const t = document.createElement('canvas'); t.width = 16; t.height = 10;
    const tx = t.getContext('2d', { willReadFrequently: true });
    tx.fillStyle = '#000000';
    tx.beginPath(); tx.moveTo(3, 0); tx.lineTo(5, 0); tx.lineTo(4.4, 10); tx.lineTo(3.6, 10); tx.closePath(); tx.fill();      // lang, nach unten verjüngt
    tx.beginPath(); tx.moveTo(11, 0); tx.lineTo(13, 0); tx.lineTo(12.4, 6); tx.lineTo(11.6, 6); tx.closePath(); tx.fill();    // kurz
    const tick = tx.getImageData(0, 0, 16, 10);
    if (map.hasImage('cliff-tick')) map.updateImage('cliff-tick', tick); else map.addImage('cliff-tick', tick, { pixelRatio: 2, sdf: true });
    // Gipfeldreieck (Spitze nach oben), SDF wie der Klippenzahn
    const g = document.createElement('canvas'); g.width = 18; g.height = 14;
    const gx = g.getContext('2d', { willReadFrequently: true });
    gx.fillStyle = '#000000'; gx.beginPath(); gx.moveTo(9, 0.5); gx.lineTo(17.5, 13.5); gx.lineTo(0.5, 13.5); gx.closePath(); gx.fill();
    const peak = gx.getImageData(0, 0, 18, 14);
    if (map.hasImage('peak-tri')) map.updateImage('peak-tri', peak); else map.addImage('peak-tri', peak, { pixelRatio: 2, sdf: true });
    registerLandPatterns(map);
    return true;
  } catch (err) {
    iconStatus.errors.push(String(err?.message ?? err));
    return false;
  }
}
