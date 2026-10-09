// Wasserbewegung: Fließrichtung der Gewässerlinien, Stau und Wellen auf Stillgewässern nach Modellwind.
// Zweck:    Ebene "Wasserbewegung" der Lagekarte. Alles läuft im Browser auf den Gewässern der eigenen Kacheln (Protomaps, Ebene water):
//           - Flüsse und Bäche (Linien): wandernde Striche in Fließrichtung, dazu Richtungspfeile. Bäche laufen schneller als Flüsse.
//           - Breite Flüsse (Mosel, Saar, Sauer/Sûre, WIDE_RIVERS): Wellenfeld über die ganze Breite, in Fließrichtung bewegt, ähnlich den Seen.
//           - Gestaute Flüsse (Mosel, Saar: staugeregelt): das Wellenfeld rückt kaum, Pfeile zeigen die Richtung. Siehe IMPOUNDED.
//           - Stillgewässer (Seen, Teiche, Becken, Stauseen): Wellenzeichen, die mit dem Wind ziehen; Dichte und Tempo folgen der Windstärke.
//             Ohne Windmodell oder bei Flaute bleibt das Wasser glatt.
// Darstellung, keine Messung: Die Fließrichtung ist die Digitalisierungsrichtung der OSM-Linien (geprüft an Mosel, Saar, Our, Sûre, Kyll,
//           Prüm, Nims, Alzette, Lieser, Ruwer). Die Geschwindigkeit ist eine Klasse (Bach, Fluss, gestaut), nicht der Abfluss. Wind: ICON-D2
//           (wind.js, 10 m, Kartenmitte). Wo OSM eine Fläche ohne Gewässerart führt, gilt sie als Stillgewässer.
// Reduzierte Bewegung (prefers-reduced-motion): nichts wandert, Pfeile und stehende Zeichen bleiben.
// Aufruf:   const flow = createFlow(map, { sampleWind, reduce, onWind }); flow.layers({ dark, med }) → Layer-Liste; flow.setEnabled(true); flow.update()

export const IMPOUNDED = ['Mosel', 'Saar'];
const LINE_KINDS = ['river', 'stream', 'canal'];
const FLOWING_DETAIL = ['river', 'stream', 'canal'];
const STILL_KINDS = ['water', 'lake', 'basin', 'reservoir'];
const T = 32;                     // Kachel der Wellenzeichen in Bildpunkten (pixelRatio 2 = 16 px auf dem Schirm)
const CSS_T = T / 2;
export const WAVE_MIN_ZOOM = 9;
const MAXF = 15;                  // Zahl der Wellen-Ebenen: jede trägt ein festes Bild, umgeschaltet wird nur die Deckkraft (ein Musterwechsel würde flackern)
const WAVE_ON = ['interpolate', ['linear'], ['zoom'], WAVE_MIN_ZOOM, 0, WAVE_MIN_ZOOM + 2, 0.95];
const LINE_MIN_ZOOM = { stream: 11, river: 9 };
const LINE_STEP_MS = { stream: 55, river: 95 };   // Takt der 14 Striche-Schritte: kleiner = schneller
// Breite Flüsse (Mosel, Saar, Sauer/Sûre): Wellenfeld über die ganze Breite statt eines Strichs. Breite in Metern, grob und absichtlich etwas
// schmaler als der Fluss, damit das Muster nicht über die Ufer ragt. Die Zeile zeigt die Form wie bei Seen, nur in Fließrichtung bewegt.
export const WIDE_RIVERS = { Mosel: 100, Saar: 60, Sauer: 40, 'Sûre': 40 };
const RIP_FRAMES = 6, RIP_MS = { wide: 110, stau: 650 };

// Strichfolge (Einheiten der Linienbreite): die Striche rücken mit jedem Schritt ein Stück in Richtung der Linie
export const DASH_SEQ = [[0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
  [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5]];

const COLORS = {
  light: { dash: '#ffffff', arrow: '#17436f', wave: '#ffffff' },
  dark: { dash: '#bfe0ff', arrow: '#e8f3ff', wave: '#a9d2f5' },
  med: { dash: '#efe0b0', arrow: '#3a2614', wave: '#efe0b0' },
};

/** Verschiebung je Welle-Zyklus als ganze Kachelvielfache (a, b ∈ −2…2), damit die Zeichnung nahtlos wiederkehrt.
 *  `from` = Windrichtung in Grad, AUS der der Wind kommt (meteorologisch). Rückgabe: Bildschirmrichtung (y nach unten) und Länge in Kacheln. */
export function travelShift(from) {
  const to = (((from + 180) % 360) + 360) % 360 * Math.PI / 180;
  const dx = Math.sin(to), dy = -Math.cos(to);
  let best = null;
  for (let a = -2; a <= 2; a++) for (let b = -2; b <= 2; b++) {
    if (!a && !b) continue;
    const len = Math.hypot(a, b), cos = (a * dx + b * dy) / len;
    if (!best || cos > best.cos + 1e-9 || (Math.abs(cos - best.cos) < 1e-9 && len < best.len)) best = { a, b, len, cos };
  }
  return best;
}

/** Wellenbild nach Windstärke (m/s): Flaute glatt, sonst mehr und längere Wellenzeichen, höheres Tempo (Bildpunkte je Sekunde). */
export function waveSpec(speed) {
  if (!Number.isFinite(speed) || speed < 0.8) return { cls: 'calm', crests: 0, len: 0, alpha: 0.28, pxs: 0 };
  if (speed < 3) return { cls: 'light', crests: 2, len: 5, alpha: 0.4, pxs: 9 };
  if (speed < 6) return { cls: 'moderate', crests: 3, len: 7, alpha: 0.55, pxs: 14 };
  return { cls: 'strong', crests: 4, len: 10, alpha: 0.7, pxs: 21 };
}

/** Schlüssel, der sich nur ändert, wenn neue Wellenbilder nötig sind (16 Richtungsstufen, 4 Stärkeklassen). */
export function waveKey(w) {
  if (!w) return 'none';
  const spec = waveSpec(w.speed);
  return spec.cls === 'calm' ? 'calm' : `${spec.cls}-${Math.round(w.from / 22.5) % 16}`;
}

const CRESTS = [[8, 8], [24, 20], [12, 26], [27, 4]];
const SPARKS = [[5, 6], [19, 9], [11, 21], [26, 26]];

function drawFrame(ctx, spec, dir, k, n, ink) {
  ctx.clearRect(0, 0, T, T);
  ctx.strokeStyle = ink; ctx.fillStyle = ink; ctx.lineWidth = 1.1; ctx.lineCap = 'round'; ctx.globalAlpha = spec.alpha;
  if (spec.cls === 'calm') { for (const [x, y] of SPARKS) ctx.fillRect(x, y, 1.3, 1.3); return; }
  const ox = (dir.a * T * k) / n, oy = (dir.b * T * k) / n;
  const len = Math.hypot(dir.a, dir.b), ux = dir.a / len, uy = dir.b / len, px = -uy, py = ux;
  for (const [cx, cy] of CRESTS.slice(0, spec.crests)) {
    for (let m = -1; m <= 1; m++) for (let q = -1; q <= 1; q++) {
      const x = cx + ox + m * T, y = cy + oy + q * T, h = spec.len / 2;
      ctx.beginPath();
      ctx.moveTo(x - px * h, y - py * h);
      ctx.quadraticCurveTo(x + ux * spec.len * 0.3, y + uy * spec.len * 0.3, x + px * h, y + py * h);   // Bogen nach vorn: Welle läuft in Zugrichtung
      ctx.stroke();
    }
  }
}

export function registerArrow(map) {
  const c = document.createElement('canvas'); c.width = 14; c.height = 14;
  const x = c.getContext('2d', { willReadFrequently: true });
  x.fillStyle = '#000000'; x.beginPath(); x.moveTo(1, 1.5); x.lineTo(13, 7); x.lineTo(1, 12.5); x.lineTo(4.5, 7); x.closePath(); x.fill();   // Pfeilspitze nach rechts = Linienrichtung
  const data = x.getImageData(0, 0, 14, 14);
  if (map.hasImage('flow-arrow')) map.updateImage('flow-arrow', data); else map.addImage('flow-arrow', data, { pixelRatio: 2, sdf: true });
}

export function createFlow(map, { sampleWind, reduce = false, onWind = () => {} }) {
  let ripStep = { wide: 0, stau: 0 }, ripLast = { wide: 0, stau: 0 };
  let enabled = false, raf = 0, ink = COLORS.light.wave, theme = 'light';
  let gen = 0, frames = [], frameMs = 0, key = '', cur = 0, lastWave = 0;
  const step = { stream: 0, river: 0 }, last = { stream: 0, river: 0 };
  const tmp = {};

  const wind = () => { const c = map.getCenter(); return sampleWind?.(c.lng, c.lat, tmp) ?? null; };

  function buildWaves(w) {
    const k = `${waveKey(w)}|${theme}`;
    if (k === key && frames.length) return false;
    key = k;
    const spec = waveSpec(w?.speed), dir = travelShift(w?.from ?? 0);
    const n = spec.cls === 'calm' ? 1 : Math.min(MAXF, Math.max(6, Math.ceil(5 * dir.len)));
    const old = frames; gen += 1; frames = [];
    const c = document.createElement('canvas'); c.width = T; c.height = T;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    for (let i = 0; i < n; i++) {
      drawFrame(ctx, spec, dir, i, n, ink);
      const id = `flow-wave-${gen}-${i}`;
      map.addImage(id, ctx.getImageData(0, 0, T, T), { pixelRatio: 2 });
      frames.push(id);
    }
    frameMs = spec.pxs ? (dir.len * CSS_T / spec.pxs * 1000) / n : 0;   // Zyklusdauer = Weg je Zyklus / Tempo, verteilt auf die Bilder
    cur = 0;
    showFrame(0, true);
    setTimeout(() => { for (const id of old) if (map.hasImage(id)) map.removeImage(id); }, 700);   // erst nach dem Umschalten, sonst blitzt es
    return true;
  }

  // Bilder den Ebenen zuordnen (nach Wechsel der Wellenbilder) bzw. nur die Deckkraft der Ebenen umschalten (je Bild)
  function showFrame(i, assign) {
    for (let k = 0; k < MAXF; k++) {
      const id = `bm-flow-still-${k}`;
      if (!map.getLayer(id)) continue;
      if (assign) map.setPaintProperty(id, 'fill-pattern', frames[Math.min(k, frames.length - 1)]);
      if (assign || k === i || k === cur) map.setPaintProperty(id, 'fill-opacity', k === i ? WAVE_ON : 0);
    }
    cur = i;
  }

  function reportWind(w) {
    onWind(w ? { speed: w.speed, from: w.from, cls: waveSpec(w.speed).cls } : null);
  }

  // Wellenfeld für breite Flüsse: Bögen quer zur Strömung (Wölbung flussab = nach rechts), pro Bild um 1/6 Periode nach rechts verschoben
  function ripImages(ink2) {
    const c = document.createElement('canvas'); c.width = T; c.height = T;
    const x = c.getContext('2d', { willReadFrequently: true });
    for (let i = 0; i < RIP_FRAMES; i++) {
      const id = `flow-rip-${theme}-${i}`;
      x.clearRect(0, 0, T, T); x.strokeStyle = ink2; x.lineWidth = 1.2; x.lineCap = 'round'; x.globalAlpha = 0.6;
      const off = (T * i) / RIP_FRAMES;
      for (const [cx, cy] of [[6, 7], [22, 14], [8, 24]]) for (let m = -1; m <= 1; m++) {
        const px = cx + off + m * T;
        x.beginPath(); x.moveTo(px - 1.5, cy - 4.5); x.quadraticCurveTo(px + 2.5, cy, px - 1.5, cy + 4.5); x.stroke();
      }
      const data = x.getImageData(0, 0, T, T);
      if (map.hasImage(id)) map.updateImage(id, data); else map.addImage(id, data, { pixelRatio: 2 });
    }
  }

  function layers({ dark, med }) {
    theme = med ? 'med' : dark ? 'dark' : 'light';
    ink = COLORS[theme].wave;
    key = '';
    for (const id of frames) if (map.hasImage(id)) map.removeImage(id);
    frames = [];
    const w = wind(); buildWaves(w); reportWind(w);
    const col = COLORS[theme];
    ripImages(col.wave);
    const wideNames = Object.keys(WIDE_RIVERS);
    const isWide = ['in', ['get', 'name'], ['literal', wideNames]];
    const wM = ['match', ['get', 'name'], ...Object.entries(WIDE_RIVERS).flat(), 20];
    const ripLayers = ['wide', 'stau'].flatMap((cls) => Array.from({ length: RIP_FRAMES }, (_, i) => ({
      id: `flow-rip-${cls}-${i}`, type: 'line', ...{ source: 'basemap', 'source-layer': 'water' }, minzoom: 11,
      filter: ['all', ['==', ['geometry-type'], 'LineString'], ['==', ['get', 'kind'], 'river'], isWide, cls === 'stau' ? ['in', ['get', 'name'], ['literal', IMPOUNDED]] : ['!', ['in', ['get', 'name'], ['literal', IMPOUNDED]]]],
      layout: { 'line-cap': 'butt', 'line-join': 'round', visibility: 'none' },
      paint: { 'line-pattern': `flow-rip-${theme}-${i}`, 'line-opacity': i === 0 ? 0.9 : 0, 'line-opacity-transition': { duration: 0, delay: 0 },
        'line-width': ['interpolate', ['exponential', 2], ['zoom'], 9, ['*', wM, 1 / 98.6], 17, ['*', wM, 2.597]] },
    })));
    const isLine = ['==', ['geometry-type'], 'LineString'];
    const kind = (...ks) => ['in', ['get', 'kind'], ['literal', ks]];
    const base = { source: 'basemap', 'source-layer': 'water' };
    const line = (id, filter, minzoom, w0, w1) => ({ id, type: 'line', ...base, minzoom, filter: ['all', isLine, ...filter],
      layout: { 'line-cap': 'butt', 'line-join': 'round', visibility: 'none' },
      paint: { 'line-color': col.dash, 'line-opacity': 0.85, 'line-dasharray': DASH_SEQ[0], 'line-width': ['interpolate', ['linear'], ['zoom'], 9, w0, 15, w1] } });
    return [
      ...Array.from({ length: MAXF }, (_, i) => ({ id: `flow-still-${i}`, type: 'fill', ...base, minzoom: WAVE_MIN_ZOOM,
        filter: ['all', ['==', ['geometry-type'], 'Polygon'], kind(...STILL_KINDS), ['!', ['in', ['coalesce', ['get', 'kind_detail'], ''], ['literal', FLOWING_DETAIL]]]],
        layout: { visibility: 'none' },
        paint: { 'fill-pattern': frames[Math.min(i, frames.length - 1)], 'fill-opacity': i === 0 ? WAVE_ON : 0, 'fill-opacity-transition': { duration: 0, delay: 0 }, 'fill-antialias': false } })),
      line('flow-stream', [kind('stream')], LINE_MIN_ZOOM.stream, 0.8, 1.8),
      line('flow-river', [kind('river', 'canal'), ['!', isWide]], LINE_MIN_ZOOM.river, 1.3, 3),
      ...ripLayers,
      { id: 'flow-arrow', type: 'symbol', ...base, minzoom: 11, filter: ['all', isLine, kind(...LINE_KINDS)],
        layout: { 'symbol-placement': 'line', 'symbol-spacing': 120, 'icon-image': 'flow-arrow', 'icon-rotation-alignment': 'map', 'icon-pitch-alignment': 'map',
          'icon-allow-overlap': true, 'icon-ignore-placement': true, 'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.8, 16, 1.5], visibility: 'none' },
        paint: { 'icon-color': col.arrow, 'icon-opacity': 0.8 } },
    ];
  }

  const visible = (id) => map.getLayer(id) && map.getLayoutProperty(id, 'visibility') !== 'none';

  function tick(t) {
    raf = 0;
    if (!enabled || document.hidden || reduce) return;
    if (map.getZoom() >= 8.5) {
      for (const cls of ['stream', 'river']) {
        if (t - last[cls] < LINE_STEP_MS[cls]) continue;
        last[cls] = t; step[cls] = (step[cls] + 1) % DASH_SEQ.length;
        if (visible(`bm-flow-${cls}`)) map.setPaintProperty(`bm-flow-${cls}`, 'line-dasharray', DASH_SEQ[step[cls]]);
      }
      for (const cls of ['wide', 'stau']) {
        if (t - ripLast[cls] < RIP_MS[cls] || !visible(`bm-flow-rip-${cls}-0`)) continue;
        ripLast[cls] = t;
        const prev = ripStep[cls]; ripStep[cls] = (prev + 1) % RIP_FRAMES;
        map.setPaintProperty(`bm-flow-rip-${cls}-${prev}`, 'line-opacity', 0);
        map.setPaintProperty(`bm-flow-rip-${cls}-${ripStep[cls]}`, 'line-opacity', 0.9);
      }
      if (frameMs && frames.length > 1 && t - lastWave >= frameMs) {
        lastWave = t;
        if (visible('bm-flow-still-0')) showFrame((cur + 1) % frames.length, false);
      }
    }
    raf = requestAnimationFrame(tick);
  }
  const kick = () => { if (!raf && enabled && !reduce && !document.hidden) raf = requestAnimationFrame(tick); };

  /** Wind neu abfragen (Kartenmitte); neue Wellenbilder nur bei geänderter Klasse oder Richtungsstufe. */
  function update() {
    if (!enabled) return;
    const w = wind(); buildWaves(w); reportWind(w);
  }
  function setEnabled(on) {
    enabled = !!on;
    if (enabled) { update(); kick(); } else { cancelAnimationFrame(raf); raf = 0; onWind(null); }
  }
  /** Nach Neuaufbau der Kartenebenen: Taktgeber zurücksetzen. */
  function refresh() { step.stream = step.river = 0; ripStep = { wide: 0, stau: 0 }; if (enabled) { update(); kick(); } }

  let t = 0;
  map.on('moveend', () => { clearTimeout(t); t = setTimeout(update, 400); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; } else kick(); });
  return { layers, setEnabled, update, refresh };
}
