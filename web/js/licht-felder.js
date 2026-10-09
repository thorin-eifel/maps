// Felder für die Lichtebenen: aus den Vektorkacheln der Grundkarte werden zwei kleine Bilder gezeichnet, die der Shader abtastet.
//   Strömung: Wasserlinien (Fluss, Bach, Kanal) mit Fließrichtung (Digitalisierungsrichtung wie in fluss.js) und Tempoklasse
//   Stoffe:   Landnutzung mit Rückstrahlung, Streuung und Glanz (Wald schluckt und streut, Feld und Fels strahlen hell zurück, Feuchtgebiet glänzt)
// Der reine Teil (Klassen, Kodierung, Zerlegung) ist ohne Browser testbar; nur paintFlow/paintMaterial brauchen ein 2D-Canvas.
import { IMPOUNDED, WIDE_RIVERS } from './fluss.js';

/** Stoffklassen je Landnutzungsart (Schlüssel wie LAND_KINDS in lage.js): [Rückstrahlung 0..1, Streuung 0..1, Glanz 0..1]. */
export const MATERIAL = {
  forest: [0.30, 1.00, 0.00], wood: [0.30, 1.00, 0.00],
  meadow: [0.66, 0.60, 0.08], grass: [0.66, 0.60, 0.08], grassland: [0.66, 0.60, 0.08], park: [0.66, 0.60, 0.08], garden: [0.62, 0.60, 0.08],
  recreation_ground: [0.66, 0.60, 0.08], golf_course: [0.70, 0.55, 0.10], dog_park: [0.66, 0.60, 0.08], village_green: [0.66, 0.60, 0.08],
  scrub: [0.45, 0.80, 0.03], heath: [0.48, 0.75, 0.04],
  farmland: [0.78, 0.45, 0.12], orchard: [0.55, 0.70, 0.05], vineyard: [0.58, 0.55, 0.07], allotments: [0.60, 0.60, 0.08],
  wetland: [0.50, 0.30, 0.50], bare_rock: [0.88, 0.35, 0.28], sand: [0.96, 0.50, 0.10], beach: [0.96, 0.50, 0.10], cemetery: [0.60, 0.60, 0.06],
};
export const MATERIAL_KINDS = Object.keys(MATERIAL);
export const DEFAULT_MATERIAL = [0.6, 0.5, 0.04];

/** Tempoklasse einer Wasserlinie 0..1 (Anteil des höchsten Wellentempos) und Breite in Metern (für das Wellenfeld). */
export function flowClass(kind, name) {
  const wide = WIDE_RIVERS[name] ?? 0;
  const still = IMPOUNDED.includes(name);
  const speed = still ? 0.18 : kind === 'stream' ? 1 : kind === 'canal' ? 0.35 : 0.7;
  const width = wide ? wide * 1.35 : kind === 'stream' ? 4 : kind === 'canal' ? 8 : 12;
  return { speed, width };
}

/** Richtung (dx,dy) auf der Bildebene (x Osten, y Süden) als Bytes 0..255 für Rot und Grün: 128 ± 127·Einheitsvektor. */
export function encodeDir(dx, dy) {
  const l = Math.hypot(dx, dy) || 1;
  return [Math.round(128 + (127 * dx) / l), Math.round(128 + (127 * dy) / l)];
}
export function decodeDir(r, g) {
  const x = (r - 128) / 127, y = (g - 128) / 127, l = Math.hypot(x, y) || 1;
  return [x / l, y / l];
}

/** Mercator 0..1 (x Osten, y Süden) */
export const merc = (lng, lat) => [(lng + 180) / 360, 0.5 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / (2 * Math.PI)];

/** Linienstücke aus GeoJSON-Merkmalen der Ebene water: nur Fluss, Bach, Kanal; Mercator-Koordinaten, Breite in Metern, Tempo. */
export function flowSegments(features) {
  const out = [];
  for (const f of features) {
    const k = f.properties?.kind;
    if (k !== 'river' && k !== 'stream' && k !== 'canal') continue;
    const g = f.geometry;
    const lines = g?.type === 'LineString' ? [g.coordinates] : g?.type === 'MultiLineString' ? g.coordinates : [];
    const { speed, width } = flowClass(k, f.properties?.name);
    for (const l of lines) {
      for (let i = 1; i < l.length; i++) {
        const a = merc(l[i - 1][0], l[i - 1][1]), b = merc(l[i][0], l[i][1]);
        if (a[0] === b[0] && a[1] === b[1]) continue;
        out.push({ a, b, speed, width });
      }
    }
  }
  return out;
}

/** Strömungsbild zeichnen: pro Stück eine Linie, Farbe = Richtung (R, G) und Tempo (B). win = {x,y,w,h} in Mercator, mpp = Meter je Bildpunkt des Canvas. */
export function paintFlow(ctx, cw, ch, win, segs, mppCanvas) {
  ctx.clearRect(0, 0, cw, ch);
  ctx.lineCap = 'round';
  const toX = (m) => ((m[0] - win.x) / win.w) * cw, toY = (m) => ((m[1] - win.y) / win.h) * ch;
  // breite zuerst, damit schmale Zuflüsse darüber liegen
  for (const s of [...segs].sort((p, q) => q.width - p.width)) {
    const x0 = toX(s.a), y0 = toY(s.a), x1 = toX(s.b), y1 = toY(s.b);
    if ((x0 < -50 && x1 < -50) || (x0 > cw + 50 && x1 > cw + 50) || (y0 < -50 && y1 < -50) || (y0 > ch + 50 && y1 > ch + 50)) continue;
    const [r, g] = encodeDir(x1 - x0, y1 - y0);
    ctx.strokeStyle = `rgb(${r},${g},${Math.round(s.speed * 255)})`;
    ctx.lineWidth = Math.max(2.5, s.width / mppCanvas);
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  }
}

/** Stoffbild zeichnen: Landnutzungsflächen, Farbe = (Rückstrahlung, Streuung, Glanz). */
export function paintMaterial(ctx, cw, ch, win, features) {
  ctx.clearRect(0, 0, cw, ch);
  for (const f of features) {
    const m = MATERIAL[f.properties?.kind];
    if (!m) continue;
    const g = f.geometry;
    const polys = g?.type === 'Polygon' ? [g.coordinates] : g?.type === 'MultiPolygon' ? g.coordinates : [];
    ctx.fillStyle = `rgb(${Math.round(m[0] * 255)},${Math.round(m[1] * 255)},${Math.round(m[2] * 255)})`;
    for (const poly of polys) {
      ctx.beginPath();
      for (const ring of poly) {
        ring.forEach(([lng, lat], i) => { const p = merc(lng, lat); const x = ((p[0] - win.x) / win.w) * cw, y = ((p[1] - win.y) / win.h) * ch; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
        ctx.closePath();
      }
      ctx.fill('evenodd');
    }
  }
}
