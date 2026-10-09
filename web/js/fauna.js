// Karte im Stil des 15. Jahrhunderts: Drachen und Seeungeheuer als Randzeichnungen im Stichstil.
// Alles eigene Zeichnung, im Browser auf Canvas erzeugt. Die Körper sind je ein durchgehender Umriss um eine Wirbelsäulenlinie
// (Breitenprofil mit leichtem Zittern), außen mit einer einzigen Tintenkontur, innen Schraffur entlang der Körperform,
// Schuppen, Bauchplatten und Flügel mit Fingerknochen und Faltenstrichen. Nur im Modus „Karte im Stil des 15. Jahrhunderts“
// im Stil eingebunden (lage.js); die Orte setzt medieval.js.
const INK = '#3a2614', PAPER = '#efe0b0', TAU = Math.PI * 2;
const G = 96;          // Zeichenraster; Bild 2 × so groß (pixelRatio 2)
const SIZE = G * 2;
const LIGHT = [0.58, 0.81]; // Schattenseite: nach unten rechts (Licht fällt von links oben)

const C = { green: '#bcbf86', greenD: '#9ea56a', belly: '#e3d7a0', red: '#c0765a', redD: '#a85a40', wing: '#c47a5c', water: '#2f5560', sea: '#b4c4b2', seaD: '#93aa9b', bone: '#eadfae', mouth: '#7a1c14', fire: '#d9792a', fireIn: '#ecc04a' };

// ---- Werkzeug
const rng = (seed) => { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; };
const lerp = (a, b, t) => a + (b - a) * t;
const mix = (p, q, t) => [lerp(p[0], q[0], t), lerp(p[1], q[1], t)];
const add = (p, q, k = 1) => [p[0] + q[0] * k, p[1] + q[1] * k];
const bez = (a, b, c, d, n = 30) => { const o = []; for (let i = 0; i <= n; i++) { const t = i / n, u = 1 - t; o.push([u * u * u * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t * t * t * d[0], u * u * u * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t * t * t * d[1]]); } return o; };
const chain = (...segs) => segs.flatMap((s, i) => (i ? bez(...s).slice(1) : bez(...s)));
function resample(pts, step) {
  const len = [0];
  for (let i = 1; i < pts.length; i++) len.push(len[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const total = len[len.length - 1], out = [];
  for (let d = 0, j = 1; d <= total + 1e-6; d += step) {
    while (j < pts.length - 1 && len[j] < d) j++;
    const t = (d - len[j - 1]) / ((len[j] - len[j - 1]) || 1);
    out.push([pts[j - 1][0] + (pts[j][0] - pts[j - 1][0]) * t, pts[j - 1][1] + (pts[j][1] - pts[j - 1][1]) * t]);
  }
  return out;
}
const noise = (seed) => { const r = rng(seed), v = Array.from({ length: 70 }, r); return (t) => { const f = Math.abs(t) * 9, i = Math.floor(f) % 66, u = f - Math.floor(f), s = u * u * (3 - 2 * u); return lerp(v[i], v[i + 1], s) - 0.5; }; };
const interp = (keys, t) => { if (t <= keys[0][0]) return keys[0][1]; for (let i = 1; i < keys.length; i++) if (t <= keys[i][0]) { const [t0, w0] = keys[i - 1], [t1, w1] = keys[i]; return lerp(w0, w1, (1 - Math.cos(((t - t0) / (t1 - t0 || 1)) * Math.PI)) / 2); } return keys[keys.length - 1][1]; };
const pen = (x, w, col = INK, a = 1) => { x.lineWidth = w; x.strokeStyle = col; x.globalAlpha = a; };
const ln = (x, a, b, c, d) => { x.beginPath(); x.moveTo(a, b); x.lineTo(c, d); x.stroke(); };
const dot = (x, px, py, r) => { x.beginPath(); x.arc(px, py, r, 0, TAU); x.fill(); };
const hexA = (h, a) => `rgba(${parseInt(h.slice(1, 3), 16)},${parseInt(h.slice(3, 5), 16)},${parseInt(h.slice(5, 7), 16)},${a})`;

/** Geschlossene, weich gerundete Kontur durch Punkte (quadratisch über die Mittelpunkte). */
function closed(pts) {
  const p = new Path2D(), n = pts.length, mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const m0 = mid(pts[n - 1], pts[0]); p.moveTo(m0[0], m0[1]);
  for (let i = 0; i < n; i++) { const c = pts[i], m = mid(c, pts[(i + 1) % n]); p.quadraticCurveTo(c[0], c[1], m[0], m[1]); }
  p.closePath(); return p;
}
/** Teil aus Stützpunkten (Kopf, Flosse …); Ecken durch doppelte Punkte schärfen. */
const blob = (pts) => ({ path: closed(pts), s: null, pts });

/** Teil um eine Wirbelsäulenlinie: Breitenprofil keys = [[t, Breite] …], leichtes Zittern der Kontur. */
function form(spine, keys, o = {}) {
  const s = resample(spine, 0.7), n = s.length, nz = noise(o.seed ?? 1), amp = o.wob ?? 0.3;
  const L = [], R = [], w = [], T = [];
  for (let i = 0; i < n; i++) {
    const a = s[Math.max(0, i - 1)], b = s[Math.min(n - 1, i + 1)], l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, tx = (b[0] - a[0]) / l, ty = (b[1] - a[1]) / l, nx = -ty, ny = tx;
    const t = i / (n - 1), base = interp(keys, t), hw = Math.max(0.04, base / 2 + nz(t * 3.1) * amp * Math.min(1, base / 3));
    L.push([s[i][0] + nx * hw, s[i][1] + ny * hw]); R.push([s[i][0] - nx * hw, s[i][1] - ny * hw]); w.push(hw * 2); T.push([tx, ty]);
  }
  const pts = [...L];
  const e = s[n - 1], he = w[n - 1] / 2, [tx, ty] = T[n - 1];
  if (he > 0.35) for (let k = 1; k < 7; k++) { const a = (Math.PI * k) / 7; pts.push([e[0] - ty * Math.cos(a) * he + tx * Math.sin(a) * he, e[1] + tx * Math.cos(a) * he + ty * Math.sin(a) * he]); }
  pts.push(...R.slice().reverse());
  const b0 = s[0], hb = w[0] / 2, [ux, uy] = T[0];
  if (hb > 0.35) for (let k = 1; k < 7; k++) { const a = (Math.PI * k) / 7; pts.push([b0[0] + uy * Math.cos(a) * hb - ux * Math.sin(a) * hb, b0[1] - ux * Math.cos(a) * hb - uy * Math.sin(a) * hb]); }
  return { path: closed(pts), s, w, T, n };
}

/** Umriss einmal um alle Teile (Vereinigung): Tinte unter die Füllung gelegt, damit zwischen Teilen keine Nähte als Kontur stehen. */
function outline(x, parts, wdt = 2.6) {
  x.save(); x.fillStyle = INK; x.strokeStyle = INK; x.lineWidth = wdt; x.lineJoin = 'round'; x.globalAlpha = 1;
  for (const p of parts) { x.fill(p.path); x.stroke(p.path); }
  x.restore();
}
/** Teil füllen; innere Kontur nur dünn, damit Überlappungen lesbar bleiben. */
function fillPart(x, p, col, inner = 0.55) { x.fillStyle = col; x.fill(p.path); if (inner) { pen(x, inner, INK, 0.9); x.stroke(p.path); x.globalAlpha = 1; } }

/** Schraffur entlang der Form: kurze gebogene Striche von der Schattenseite nach innen; zweite Lage kreuzend im Dunkelsten. */
function shade(x, p, o = {}) {
  const r = rng(o.seed ?? 5), { s, w, T, n } = p, step = o.step ?? 1.15;
  x.save(); x.clip(p.path);
  for (let pass = 0; pass < (o.cross === false ? 1 : 2); pass++) {
    for (let i = 1; i < n - 1; i += Math.max(1, Math.round(step / 0.7))) {
      const [tx, ty] = T[i]; let nx = -ty, ny = tx; if (nx * LIGHT[0] + ny * LIGHT[1] < 0) { nx = -nx; ny = -ny; }
      const half = w[i] / 2, depth = half * (o.depth ?? 0.62) * (0.55 + r() * 0.7) * (pass ? 0.55 : 1);
      if (half < 0.7 || depth < 0.5) continue;
      const sx = s[i][0] + nx * (half + 0.2), sy = s[i][1] + ny * (half + 0.2), tilt = (pass ? -0.55 : 0.4) + (r() - 0.5) * 0.25;
      const ex = sx - nx * depth + tx * depth * tilt, ey = sy - ny * depth + ty * depth * tilt;
      pen(x, (pass ? 0.32 : 0.42) + r() * 0.12, INK, 0.7 + r() * 0.25);
      x.beginPath(); x.moveTo(sx, sy); x.quadraticCurveTo((sx + ex) / 2 + tx * depth * 0.18, (sy + ey) / 2 + ty * depth * 0.18, ex, ey); x.stroke();
    }
  }
  x.globalAlpha = 1; x.restore();
}
/** Schuppen: Reihen kleiner Bögen entlang der Form, unregelmäßig. */
function scales(x, p, o = {}) {
  const r = rng(o.seed ?? 8), { s, w, T, n } = p, size = o.size ?? 1.5, rows = o.rows ?? [-0.62, -0.2, 0.22, 0.64];
  x.save(); x.clip(p.path); pen(x, 0.34, INK, 0.7);
  let k = 0;
  for (let i = 3; i < n - 3; i += Math.max(1, Math.round(size / 0.7))) {
    k++;
    for (const u of rows) {
      const half = w[i] / 2; if (half < 1.2 || r() < 0.12) continue;
      const [tx, ty] = T[i], nx = -ty, ny = tx, off = (k % 2) * size * 0.5;
      const cx = s[i][0] + nx * u * half + tx * off, cy = s[i][1] + ny * u * half + ty * off, a = Math.atan2(ty, tx) + Math.PI, rr = size * (0.5 + r() * 0.22);
      x.beginPath(); x.arc(cx, cy, rr, a - 1.15, a + 1.15); x.stroke();
    }
  }
  x.globalAlpha = 1; x.restore();
}
/** Bauchplatten: hellere Seite mit Querstrichen. side = ±1 gegenüber der Normalen der Linie. */
function belly(x, p, side = 1, frac = 0.42, col = C.belly, o = {}) {
  const { s, w, T, n } = p, r = rng(o.seed ?? 4);
  x.save(); x.clip(p.path);
  const edge = [], inner = [];
  for (let i = 0; i < n; i++) { const [tx, ty] = T[i], nx = -ty * side, ny = tx * side, h = w[i] / 2; edge.push([s[i][0] + nx * (h + 1), s[i][1] + ny * (h + 1)]); inner.push([s[i][0] + nx * h * (1 - 2 * frac), s[i][1] + ny * h * (1 - 2 * frac)]); }
  x.beginPath(); edge.forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b))); inner.slice().reverse().forEach(([a, b]) => x.lineTo(a, b)); x.closePath();
  x.fillStyle = col; x.fill();
  pen(x, 0.4, INK, 0.8);
  for (let i = 2; i < n - 1; i += 2) { const j = i + (r() < 0.3 ? 1 : 0); if (j >= n) continue; x.beginPath(); x.moveTo(edge[j][0], edge[j][1]); x.quadraticCurveTo((edge[j][0] + inner[j][0]) / 2 + T[j][0] * 0.5, (edge[j][1] + inner[j][1]) / 2 + T[j][1] * 0.5, inner[j][0], inner[j][1]); x.stroke(); }
  pen(x, 0.5, INK, 0.9); x.beginPath(); inner.forEach(([a, b], i) => (i ? x.lineTo(a, b) : x.moveTo(a, b))); x.stroke();
  x.globalAlpha = 1; x.restore();
}
/** Aufhellung von links oben über eine Fläche (die Schraffur wird dort ausgedünnt). */
function lift(x, p, bbox, col, a = 0.75) {
  const [x0, y0, x1, y1] = bbox; x.save(); x.clip(p.path);
  const cx = x0 + (x1 - x0) * 0.3, cy = y0 + (y1 - y0) * 0.25, g = x.createRadialGradient(cx, cy, 1, cx, cy, Math.hypot(x1 - x0, y1 - y0) * 0.65);
  g.addColorStop(0, hexA(col, a)); g.addColorStop(1, hexA(col, 0)); x.fillStyle = g; x.fillRect(x0 - 2, y0 - 2, x1 - x0 + 4, y1 - y0 + 4); x.restore();
}
/** Gleichmäßige Schrägschraffur in einer Fläche, danach Aufhellung: für Köpfe und Flossen. */
function hatchArea(x, p, bbox, col, o = {}) {
  const [x0, y0, x1, y1] = bbox, gap = o.gap ?? 1.15, ang = o.ang ?? -0.9, r = rng(o.seed ?? 2);
  x.save(); x.clip(p.path); pen(x, 0.4, INK, 0.75);
  const dx = Math.cos(ang), dy = Math.sin(ang), diag = Math.hypot(x1 - x0, y1 - y0);
  for (let d = -diag; d < diag; d += gap) {
    const cx = (x0 + x1) / 2 - dy * d, cy = (y0 + y1) / 2 + dx * d, jit = (r() - 0.5) * 0.4;
    x.beginPath(); x.moveTo(cx - dx * diag + jit, cy - dy * diag); x.quadraticCurveTo(cx + jit * 4 + dy * 0.8, cy + 0.6, cx + dx * diag, cy + dy * diag); x.stroke();
  }
  x.globalAlpha = 1; x.restore();
  lift(x, p, bbox, col, o.lift ?? 0.8);
}

/** Krallen: gebogene, spitz zulaufende Hornspitzen. */
function talon(x, [px, py], ang, len = 3.6, w = 1.5) {
  const f = form(bez([px, py], [px + Math.cos(ang) * len * 0.5, py + Math.sin(ang) * len * 0.5 - 0.8], [px + Math.cos(ang + 0.5) * len * 0.9, py + Math.sin(ang + 0.5) * len * 0.9], [px + Math.cos(ang + 0.9) * len, py + Math.sin(ang + 0.9) * len], 10), [[0, w], [1, 0.05]], { wob: 0 });
  outline(x, [f], 1.2); fillPart(x, f, C.bone, 0.3);
}
function foot(x, [px, py], dir = 1, toes = 3) { for (let i = 0; i < toes; i++) talon(x, [px + dir * i * 1.1, py - 0.4 + i * 0.3], dir > 0 ? 0.15 - i * 0.12 : Math.PI - 0.15 + i * 0.12, 3.8 - i * 0.3, 1.5); }

/** Bein: Oberschenkel mit Muskel, Knie, dünner Unterschenkel, Fuß. */
function legPart(hip, knee, foot_, w, seed) {
  const k2 = mix(knee, foot_, 0.5);
  const spine = chain([hip, mix(hip, knee, 0.33), mix(hip, knee, 0.75), knee], [knee, mix(knee, k2, 0.5), mix(k2, foot_, 0.5), foot_]);
  return form(spine, [[0, w * 0.9], [0.18, w * 1.15], [0.42, w * 0.5], [0.5, w * 0.62], [0.7, w * 0.4], [1, w * 0.34]], { seed, wob: 0.22 });
}

// ---- Kopf
/** Drachenkopf nach rechts (px, py = Schädelansatz), s = Größe, rot = Neigung, open = Maul 0..1. */
function dhead(x, px, py, s, rot, o = {}) {
  x.save(); x.translate(px, py); x.rotate(rot); x.scale(s, s);
  const open = o.open ?? 1, skin = o.skin ?? C.green, dark = o.dark ?? C.greenD, k = 1 / s;
  const horns = [form(bez([1, -5], [-3, -10], [-9, -10], [-15, -5.5], 12), [[0, 3.6], [1, 0.1]], { wob: 0.1, seed: 3 }), form(bez([4, -6.5], [2, -13], [-3, -16], [-8, -15.5], 12), [[0, 2.6], [1, 0.1]], { wob: 0.1, seed: 4 })];
  const frill = [0, 1, 2].map((i) => form(bez([-2 + i * 0.5, 4 + i * 1.6], [-6, 5 + i * 3], [-10, 8 + i * 3.4], [-14 + i, 9 + i * 4], 10), [[0, 2.2], [1, 0.1]], { wob: 0, seed: 10 + i }));
  const upper = blob([[-4, 3], [-3.5, -3], [1, -7], [7, -8.6], [12, -7.4], [16, -5.4], [21, -4], [26, -2.6], [29.5, -0.4], [29.6, 1.4], [27, 2.6], [23, 2.3], [18, 3.4], [12, 4.4], [6, 5.8], [0, 6.4], [-4, 5.4]]);
  const lower = blob([[1.5, 6], [7, 7 + 1.2 * open], [14, 8.2 + 3 * open], [21, 8.4 + 3.6 * open], [27, 7.4 + 3.4 * open], [28.8, 6.4 + 3 * open], [26, 5.6 + 2.2 * open], [20, 5.2 + 1.4 * open], [13, 5.4 + 0.6 * open], [6, 5.6]]);
  const inner = blob([[3, 5.2], [12, 3.8], [22, 3], [27, 3.4], [28, 6 + 2.6 * open], [20, 6 + 1.4 * open], [10, 5.8]]);
  outline(x, [...horns, ...frill, upper, lower], 2.2 * k);
  x.fillStyle = C.mouth; x.fill(inner.path);
  for (const f of frill) fillPart(x, f, dark, 0.5 * k);
  for (const hh of horns) { fillPart(x, hh, C.bone, 0.5 * k); shade(x, hh, { seed: 2, depth: 0.7, step: 1.0 }); }
  fillPart(x, lower, skin, 0.55 * k); hatchArea(x, lower, [0, 5, 30, 14], skin, { gap: 1.0, ang: -1.0, lift: 0.5 });
  fillPart(x, upper, skin, 0.55 * k); hatchArea(x, upper, [-4, -9, 30, 7], skin, { gap: 1.05, ang: -1.05, lift: 0.82, seed: 3 });
  x.save(); x.clip(upper.path); pen(x, 0.35 * k, INK, 0.75);
  for (let r2 = 0; r2 < 3; r2++) for (let i = 0; i < 7; i++) { const cx = -1 + i * 2.5 + (r2 % 2) * 1.2, cy = -3.5 + r2 * 2.4 + i * 0.12; x.beginPath(); x.arc(cx, cy, 1.1, Math.PI * 0.15, Math.PI * 0.85); x.stroke(); }
  x.restore();
  pen(x, 1.1 * k, INK, 1); x.beginPath(); x.moveTo(4, -5.2); x.quadraticCurveTo(10, -8.8, 16, -5.6); x.stroke();
  pen(x, 0.6 * k, INK, 0.9); x.beginPath(); x.moveTo(17, -4.8); x.quadraticCurveTo(23, -3.2, 27, -1); x.stroke();
  x.fillStyle = INK; dot(x, 25.5, -0.6, 0.55); dot(x, 27, 0.2, 0.4);
  const eye = new Path2D(); eye.moveTo(6.5, -3.2); eye.quadraticCurveTo(9.5, -6, 13, -4); eye.quadraticCurveTo(10, -1.8, 6.5, -3.2);
  x.fillStyle = PAPER; x.fill(eye); pen(x, 0.75 * k, INK, 1); x.stroke(eye);
  x.fillStyle = C.mouth; dot(x, 10, -3.7, 1.35); x.fillStyle = INK; dot(x, 10.2, -3.7, 0.7);
  pen(x, 0.6 * k, INK, 0.9); x.beginPath(); x.moveTo(6, -4.2); x.quadraticCurveTo(9.5, -7.2, 13.6, -4.8); x.stroke();
  x.fillStyle = PAPER; pen(x, 0.45 * k, INK, 1);
  for (const [tx, ty, l] of [[14, 3.6, 2.2], [16.5, 3.3, 1.5], [19, 3.1, 2.8], [22, 2.8, 1.6], [24.5, 2.6, 2.2], [26.6, 2.5, 1.3]]) { x.beginPath(); x.moveTo(tx, ty); x.quadraticCurveTo(tx + 0.9, ty + l * 0.6, tx + 0.5, ty + l); x.quadraticCurveTo(tx + 0.2, ty + l * 0.5, tx - 0.8, ty); x.closePath(); x.fill(); x.stroke(); }
  for (const [tx, l] of [[16, 1.5], [19.5, 2.4], [23, 1.6], [26, 1.8]]) { const by = 5.8 + 3.2 * open + (tx > 20 ? 0.5 : 0); x.beginPath(); x.moveTo(tx, by); x.quadraticCurveTo(tx + 0.7, by - l * 0.6, tx + 0.3, by - l); x.quadraticCurveTo(tx - 0.1, by - l * 0.4, tx - 0.8, by); x.closePath(); x.fill(); x.stroke(); }
  if (open > 0.5) { x.fillStyle = '#b8453a'; x.beginPath(); x.moveTo(8, 6.4 + open); x.quadraticCurveTo(16, 6 + 2 * open, 23, 5.4 + 2 * open); x.quadraticCurveTo(20, 7.6 + 2.2 * open, 11, 7.8 + 1.6 * open); x.closePath(); x.fill(); pen(x, 0.4 * k, INK, 0.8); x.stroke(); x.globalAlpha = 1; }
  if (o.beard) for (let i = 0; i < 5; i++) { const b = form(bez([14 + i * 2.6, 8.8 + 3 * open], [12 + i * 2.2, 13 + i], [9 + i * 2, 17 + i * 1.5], [8 + i * 1.8, 21 + i * 2], 10), [[0, 1.3], [1, 0.1]], { wob: 0 }); outline(x, [b], k); fillPart(x, b, dark, 0.3 * k); }
  if (o.fire) {
    const fl = blob([[27, 3.8], [31, -1.5], [34, 0.5], [38, -4.5], [40, 0.5], [45, -3.5], [46, 2], [52, 1.8], [47, 5], [51, 9], [44, 8], [41, 12], [38, 7.5], [32, 9.5], [29, 7]]);
    x.fillStyle = C.fire; x.fill(fl.path); pen(x, 0.8 * k, C.mouth, 1); x.stroke(fl.path);
    x.fillStyle = C.fireIn; x.beginPath(); x.moveTo(28.5, 4.6); x.quadraticCurveTo(35, 2.5, 41, 4.4); x.quadraticCurveTo(35, 7.2, 28.5, 6.4); x.fill();
    pen(x, 0.4 * k, C.mouth, 0.9); for (let i = 0; i < 6; i++) { x.beginPath(); x.moveTo(33 + i * 2.7, 1 + (i % 2) * 7); x.quadraticCurveTo(35 + i * 2.7, 3.5, 37 + i * 2.7, 2.5 + (i % 2) * 4); x.stroke(); }
    pen(x, 0.5 * k, INK, 0.75); for (const [cx, cy, rr, a0] of [[44, -8, 3.4, 0.4], [49, -12, 2.6, 0.2], [54, -6, 2.2, 0.6], [46, 16, 3.2, 3.2], [51, 18, 2.2, 3.4]]) { x.beginPath(); x.arc(cx, cy, rr, a0, a0 + 4.6); x.stroke(); }
    x.globalAlpha = 1;
  }
  x.restore();
}

// ---- Flügel
/** Fledermausflügel: Arm S–Ellbogen–Handgelenk W, Fingerknochen zu den Spitzen, Membran mit Bogenkante und Faltenstrichen. */
function wing(x, S, E, W, tips, attach, col, seed = 3) {
  const r = rng(seed), memb = new Path2D();
  memb.moveTo(attach[0], attach[1]); memb.lineTo(S[0], S[1]); memb.quadraticCurveTo(E[0], E[1], W[0], W[1]);
  tips.forEach((t, i) => { if (!i) { memb.lineTo(t[0], t[1]); return; } const q = tips[i - 1], c = mix(mix(q, t, 0.5), W, 0.3 + r() * 0.06); memb.quadraticCurveTo(c[0], c[1], t[0], t[1]); });
  const last = tips[tips.length - 1], c2 = mix(mix(last, attach, 0.5), W, 0.2); memb.quadraticCurveTo(c2[0], c2[1], attach[0], attach[1]); memb.closePath();
  const bones = tips.map((t, i) => form(bez(W, mix(W, t, 0.35 + (i % 2) * 0.03), add(mix(W, t, 0.7), [(W[1] - t[1]) * 0.04, (t[0] - W[0]) * 0.04]), t, 12), [[0, 2.2], [0.5, 1.2], [1, 0.3]], { wob: 0.05, seed: seed + i }));
  const arm = form(chain([S, mix(S, E, 0.5), mix(S, E, 0.9), E], [E, mix(E, W, 0.4), mix(E, W, 0.8), W]), [[0, 4], [0.5, 2.6], [1, 2]], { wob: 0.1, seed });
  x.save(); x.lineJoin = 'round'; pen(x, 2.4, INK, 1); x.fillStyle = INK; x.fill(memb); x.stroke(memb); x.restore();
  x.fillStyle = col; x.fill(memb);
  x.save(); x.clip(memb);
  for (let i = 0; i < tips.length - 1; i++) { // Faltenstriche: nahe jedem Knochen dicht, zur Mitte der Bahn ausdünnend
    const a = tips[i], b = tips[i + 1];
    for (let j = 0; j < 12; j++) {
      const side = j % 2, f = side ? 1 - (0.04 + (j >> 1) * 0.055) : 0.04 + (j >> 1) * 0.055;
      const tgt = mix(a, b, f), u0 = 0.3 + r() * 0.12 + (j >> 1) * 0.04, u1 = 0.9 - (j >> 1) * 0.06 + r() * 0.05;
      pen(x, 0.34 + r() * 0.1, INK, 0.75);
      x.beginPath(); x.moveTo(lerp(W[0], tgt[0], u0), lerp(W[1], tgt[1], u0)); x.lineTo(lerp(W[0], tgt[0], u1), lerp(W[1], tgt[1], u1)); x.stroke();
    }
  }
  for (let j = 0; j < 7; j++) { const tgt = mix(last, attach, 0.05 + j * 0.05); pen(x, 0.34, INK, 0.7); ln(x, lerp(W[0], tgt[0], 0.35), lerp(W[1], tgt[1], 0.35), lerp(W[0], tgt[0], 0.92), lerp(W[1], tgt[1], 0.92)); }
  x.restore(); x.globalAlpha = 1;
  pen(x, 0.7, INK, 1); x.stroke(memb); x.globalAlpha = 1;
  for (const b of bones) { outline(x, [b], 1.0); fillPart(x, b, C.bone, 0.3); }
  outline(x, [arm], 1.2); fillPart(x, arm, col, 0.4); shade(x, arm, { depth: 0.8, seed: 2 });
  x.fillStyle = C.bone; dot(x, W[0], W[1], 1.7); pen(x, 0.8, INK, 1); x.beginPath(); x.arc(W[0], W[1], 1.7, 0, TAU); x.stroke(); x.globalAlpha = 1;
  talon(x, [W[0] - 0.5, W[1] - 1], Math.atan2(W[1] - E[1], W[0] - E[0]) - 1.0, 3.8, 1.5);
}

/** Rückenstacheln entlang einer Linie. */
function crest(x, pts, col = C.bone, every = 5, size = 2.6, seed = 1) {
  const s = resample(pts, 0.6), r = rng(seed);
  for (let i = 3; i < s.length - 3; i += every) {
    const a = s[i - 1], b = s[i + 1], l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, tx = (b[0] - a[0]) / l, ty = (b[1] - a[1]) / l;
    let nx = -ty, ny = tx; if (ny > 0) { nx = -nx; ny = -ny; }
    const sz = size * (0.7 + r() * 0.5) * (1 - Math.abs(i / s.length - 0.5) * 0.9);
    x.beginPath(); x.moveTo(s[i][0] - tx * 1.3, s[i][1] - ty * 1.3 + 0.3); x.quadraticCurveTo(s[i][0] + nx * sz * 0.5 - tx * 0.4, s[i][1] + ny * sz * 0.5 - ty * 0.4, s[i][0] + nx * sz + tx * 0.9, s[i][1] + ny * sz + ty * 0.9);
    x.quadraticCurveTo(s[i][0] + tx * 0.5 + nx * sz * 0.3, s[i][1] + ty * 0.5 + ny * sz * 0.3, s[i][0] + tx * 1.4, s[i][1] + ty * 1.4 + 0.3); x.closePath();
    x.fillStyle = col; x.fill(); pen(x, 0.6, INK, 1); x.stroke(); x.globalAlpha = 1;
  }
}
function arrowTail(x, p, ang) { // Schwanzspitze als Pfeil mit Widerhaken
  x.save(); x.translate(p[0], p[1]); x.rotate(ang);
  x.beginPath(); x.moveTo(-1.5, 0); x.quadraticCurveTo(-1.5, -2.6, -4, -3.6); x.quadraticCurveTo(0, -2.2, 6, 0); x.quadraticCurveTo(0, 2.2, -4, 3.6); x.quadraticCurveTo(-1.5, 2.6, -1.5, 0); x.closePath();
  x.fillStyle = C.red; x.fill(); pen(x, 0.8, INK, 1); x.stroke(); pen(x, 0.4, INK, 0.8); ln(x, -1, 0, 4.5, 0); x.restore(); x.globalAlpha = 1;
}

// ---- Wasser
function wavyTop(x, y, amp = 1.2) {
  x.beginPath(); x.moveTo(-4, -4); x.lineTo(G + 4, -4); x.lineTo(G + 4, y);
  for (let px = G + 4; px > -4; px -= 6) x.quadraticCurveTo(px - 1.5, y + amp * (Math.round(px) % 12 ? 1 : -1), px - 3, y);
  x.closePath();
}
function ripples(x, y, x0, x1, seed = 7, rows = 4) {
  const r = rng(seed);
  for (let k = 0; k < rows; k++) {
    const yy = y + 1.1 + k * 2.5, a = x0 + (k % 2) * 3 + r() * 5, b = x1 - r() * 8 - (k % 2) * 4;
    pen(x, 0.5 + (rows - k) * 0.04, C.water, 0.95 - k * 0.12);
    for (let seg = a; seg < b; seg += 5 + r() * 5) { const l = 4 + r() * 5; x.beginPath(); x.moveTo(seg, yy); x.quadraticCurveTo(seg + l * 0.5, yy - 1.4 - r() * 0.9, seg + l, yy + (r() - 0.5) * 0.4); x.stroke(); }
  }
  x.globalAlpha = 1;
}
function foam(x, px, py, w) { pen(x, 0.65, INK, 0.85); x.beginPath(); x.moveTo(px - w, py); for (let i = 0; i < 6; i++) x.quadraticCurveTo(px - w + (i + 0.5) * w / 3, py - 2.2 - (i % 2) * 0.6, px - w + (i + 1) * w / 3, py); x.stroke(); x.globalAlpha = 1; }

// ---- Drachen
const dragons = {
  /** A: aufgerichteter Wappendrache, Flügel gespreizt, Schwanz geringelt */
  a(x) {
    wing(x, [40, 48], [30, 38], [18, 28], [[6, 36], [10, 16], [24, 6], [38, 12]], [41, 62], C.wing, 5);
    wing(x, [53, 48], [64, 38], [76, 28], [[88, 36], [84, 16], [70, 6], [56, 12]], [52, 62], C.wing, 9);
    const tail = form(chain([[46, 72], [56, 80], [72, 78], [72, 66]], [[72, 66], [72, 58], [62, 58], [62, 65]]), [[0, 11], [0.35, 7], [0.8, 2.4], [1, 0.8]], { seed: 6 });
    const torso = form(chain([[46, 78], [42, 66], [44, 56], [47, 46]]), [[0, 12], [0.35, 17], [0.7, 14], [1, 9]], { seed: 2, wob: 0.4 });
    const neck = form(chain([[47, 50], [38, 44], [54, 36], [47, 28]], [[47, 28], [44, 24], [48, 20], [54, 20]]), [[0, 9], [0.6, 6], [1, 5.4]], { seed: 3 });
    const legL = legPart([41, 70], [37, 77], [38, 85], 6.5, 4), legR = legPart([52, 70], [57, 77], [56, 85], 6.5, 5);
    const armL = legPart([41, 53], [32, 55], [31, 46], 3.6, 7), armR = legPart([52, 53], [61, 55], [62, 46], 3.6, 8);
    outline(x, [tail, legL, legR, armL, armR, torso, neck], 2.4);
    [tail, legL, legR, armL, armR, torso, neck].forEach((p, i) => { fillPart(x, p, C.green, 0.5); shade(x, p, { seed: i + 1 }); });
    belly(x, torso, 1, 0.5, C.belly, { seed: 3 }); belly(x, neck, 1, 0.45, C.belly, { seed: 4 });
    for (const p of [tail, legL, legR, torso]) scales(x, p, { seed: 3, size: 1.5 });
    scales(x, neck, { seed: 5, size: 1.2, rows: [-0.5, 0.1] });
    crest(x, bez([47, 47], [38, 43], [54, 36], [47, 28], 20), C.red, 4, 2.6, 3);
    arrowTail(x, tail.s[tail.s.length - 1], -1.4);
    foot(x, [38, 85], -1); foot(x, [56, 85], 1); foot(x, [31, 46], -1, 3); foot(x, [62, 46], 1, 3);
    dhead(x, 53, 19, 0.88, -0.1, {});
  },
  /** B: laufender Feuerspeier, ein Flügel hoch, langer Schwanz mit Pfeilspitze */
  b(x) {
    x.translate(4, 18); x.scale(0.74, 0.74);
    wing(x, [46, 52], [38, 38], [34, 22], [[14, 20], [20, 6], [36, 3], [50, 8], [58, 20]], [56, 54], C.wing, 4);
    const tail = form(chain([[30, 58], [20, 62], [14, 76], [6, 68]], [[6, 68], [2, 63], [6, 54], [13, 56]]), [[0, 10], [0.3, 8], [0.75, 3.2], [1, 0.6]], { seed: 9 });
    const torso = form(chain([[28, 58], [38, 48], [54, 50], [62, 57]]), [[0, 9], [0.25, 14], [0.7, 14.5], [1, 9]], { seed: 4, wob: 0.4 });
    const neck = form(chain([[60, 56], [70, 58], [77, 48], [74, 36]]), [[0, 9.5], [0.5, 7], [1, 5.2]], { seed: 5 });
    const hindFar = legPart([34, 60], [37, 69], [40, 78], 6, 11), foreFar = legPart([57, 61], [61, 69], [67, 77], 5.4, 12);
    const hindNear = legPart([33, 61], [26, 69], [27, 80], 7, 13), foreNear = legPart([60, 59], [68, 64], [74, 72], 5.8, 14);
    outline(x, [tail, hindFar, foreFar, torso, neck, hindNear, foreNear], 2.4);
    fillPart(x, hindFar, C.redD, 0.5); shade(x, hindFar, { seed: 1 }); fillPart(x, foreFar, C.redD, 0.5); shade(x, foreFar, { seed: 2 });
    fillPart(x, tail, C.red, 0.5); shade(x, tail, { seed: 3 });
    fillPart(x, torso, C.red, 0.5); shade(x, torso, { seed: 4 }); belly(x, torso, 1, 0.4, C.belly, { seed: 5 });
    fillPart(x, neck, C.red, 0.5); shade(x, neck, { seed: 5 }); belly(x, neck, -1, 0.4, C.belly, { seed: 6 });
    fillPart(x, hindNear, C.red, 0.5); shade(x, hindNear, { seed: 6 }); fillPart(x, foreNear, C.red, 0.5); shade(x, foreNear, { seed: 7 });
    for (const p of [tail, torso, hindNear, foreNear, neck]) scales(x, p, { seed: 4, size: 1.5 });
    crest(x, bez([34, 50], [42, 44], [54, 44], [62, 52], 20), C.bone, 4, 2.8, 2);
    crest(x, bez([62, 54], [72, 52], [77, 44], [75, 36], 14), C.bone, 4, 2.2, 3);
    arrowTail(x, tail.s[tail.s.length - 1], -0.35);
    foot(x, [27, 80], -1); foot(x, [40, 78], 1); foot(x, [67, 77], 1); foot(x, [74, 72], 1);
    dhead(x, 75, 34, 0.82, 0.12, { fire: true, skin: C.red, dark: C.redD });
  },
  /** C: Lindwurm, schlangenartig, zwei Vorderbeine, Kamm, Bart */
  c(x) {
    x.translate(3, 10); x.scale(0.8, 0.8);
    const sp = chain([[8, 78], [10, 58], [26, 52], [32, 66]], [[32, 66], [36, 80], [54, 80], [58, 66]], [[58, 66], [62, 54], [72, 52], [75, 42]]);
    const body = form(sp, [[0, 1], [0.12, 4.5], [0.3, 8], [0.55, 10], [0.85, 9], [1, 8]], { seed: 12, wob: 0.4 });
    const arm1 = legPart([66, 52], [62, 60], [64, 68], 4.4, 3), arm2 = legPart([59, 64], [54, 70], [55, 78], 4.4, 4);
    outline(x, [body, arm1, arm2], 2.4);
    fillPart(x, arm2, C.greenD, 0.5); shade(x, arm2, { seed: 1 });
    fillPart(x, body, C.green, 0.5); shade(x, body, { seed: 3, depth: 0.7 }); belly(x, body, 1, 0.42, C.belly, { seed: 2 }); scales(x, body, { seed: 4, size: 1.45 });
    fillPart(x, arm1, C.green, 0.5); shade(x, arm1, { seed: 2 });
    crest(x, sp, C.red, 5, 3, 1);
    foot(x, [64, 68], 1); foot(x, [55, 78], 1);
    dhead(x, 74, 38, 0.95, -0.3, { beard: true });
  },
};

// ---- Seeungeheuer
const waterline = 70;
const seas = {
  /** A: Einhornfisch mit Hornspirale und wallender Mähne, taucht aus der Welle */
  a(x) {
    x.save(); wavyTop(x, waterline); x.clip();
    const r = rng(11); // Mähne: viele weiche Strähnen hinter dem Kopf
    for (let i = 0; i < 38; i++) { const y0 = 30 + i, w2 = 0.35 + r() * 0.3; pen(x, w2, INK, 0.5 + r() * 0.4); x.beginPath(); x.moveTo(60 - (i % 3), y0); x.bezierCurveTo(68 + r() * 6, y0 - 8 + r() * 4, 78 + r() * 8, y0 + 2 + r() * 6, 88 + r() * 5, y0 + 12 + i * 0.35 + r() * 3); x.stroke(); }
    x.globalAlpha = 1;
    const neck = form(chain([[54, 86], [58, 70], [52, 58], [47, 48]]), [[0, 18], [0.5, 13], [1, 11]], { seed: 21, wob: 0.5 });
    const horn = form(bez([34, 36], [27, 29], [17, 19], [6, 5], 24), [[0, 4.4], [0.5, 2.4], [1, 0.1]], { wob: 0, seed: 1 });
    const head = blob([[53, 40], [52, 32], [44, 28], [36, 29], [27, 34], [20, 41], [14, 44], [16, 47], [21, 47], [17, 51], [24, 52], [30, 55], [38, 56], [46, 54], [52, 50]]);
    outline(x, [neck, horn, head], 2.4);
    fillPart(x, neck, C.sea, 0.5); shade(x, neck, { seed: 3, depth: 0.7 }); scales(x, neck, { seed: 2, size: 1.6 });
    fillPart(x, horn, C.bone, 0.5);
    pen(x, 0.5, INK, 0.9); const hs = resample(bez([34, 36], [27, 29], [17, 19], [6, 5], 24), 1.6); hs.forEach(([px, py], i) => { const w2 = (4.4 * (1 - i / hs.length)) / 2; if (w2 > 0.35) ln(x, px - w2, py + w2 * 0.9, px + w2, py - w2 * 0.9); });
    fillPart(x, head, C.sea, 0.6); hatchArea(x, head, [12, 26, 54, 58], C.sea, { gap: 1.0, ang: -0.95, lift: 0.78 });
    x.save(); x.clip(head.path); x.fillStyle = C.mouth; x.beginPath(); x.moveTo(13, 45); x.lineTo(30, 49); x.lineTo(20, 55); x.lineTo(17, 51); x.closePath(); x.fill(); x.restore();
    x.fillStyle = PAPER; pen(x, 0.4, INK, 1); for (let i = 0; i < 5; i++) { const tx = 17 + i * 2.4; x.beginPath(); x.moveTo(tx, 47.3 + i * 0.3); x.lineTo(tx + 1.2, 47.8 + i * 0.3); x.lineTo(tx + 0.4, 49.8 + i * 0.3); x.closePath(); x.fill(); x.stroke(); }
    const eye = new Path2D(); eye.moveTo(30, 40); eye.quadraticCurveTo(35, 35.6, 39.5, 39.4); eye.quadraticCurveTo(35, 43.2, 30, 40);
    x.fillStyle = PAPER; x.fill(eye); pen(x, 0.8, INK, 1); x.stroke(eye); x.fillStyle = C.mouth; dot(x, 35, 39.4, 2.3); x.fillStyle = INK; dot(x, 35.2, 39.4, 1.2);
    pen(x, 0.8, INK, 1); x.beginPath(); x.moveTo(28.6, 38.4); x.quadraticCurveTo(35, 32.4, 41, 37.6); x.stroke();
    pen(x, 0.5, INK, 0.9); for (let i = 0; i < 4; i++) { x.beginPath(); x.moveTo(44 + i * 2.1, 34 + i * 0.6); x.quadraticCurveTo(42 + i * 2.1, 42, 44 + i * 2.1, 50); x.stroke(); }
    x.globalAlpha = 1; x.restore();
    ripples(x, waterline, 8, 90, 3, 5); foam(x, 54, waterline - 0.5, 15);
  },
  /** B: Seeschlange mit Rückenstacheln, drei Höckern und gehörntem Kopf */
  b(x) {
    x.translate(4, 6); x.scale(0.92, 0.92);
    x.save(); wavyTop(x, waterline); x.clip();
    const sp = chain([[0, 86], [6, 56], [20, 56], [25, 82]], [[25, 82], [31, 56], [45, 54], [50, 82]], [[50, 82], [54, 66], [60, 64], [65, 56]], [[65, 56], [71, 46], [64, 38], [72, 31]]);
    const body = form(sp, [[0, 7], [0.5, 9], [0.8, 8], [0.92, 6.2], [1, 6]], { seed: 31, wob: 0.45 });
    outline(x, [body], 2.4); fillPart(x, body, C.sea, 0.5); shade(x, body, { seed: 4, depth: 0.7 }); belly(x, body, 1, 0.35, C.belly, { seed: 6 }); scales(x, body, { seed: 5, size: 1.6 });
    crest(x, sp, C.bone, 4, 3.4, 6);
    x.restore();
    dhead(x, 71, 30, 0.82, 0.12, { skin: C.sea, dark: C.seaD, beard: true });
    ripples(x, waterline, 2, 92, 5, 5); foam(x, 22, waterline - 0.5, 10); foam(x, 47, waterline - 0.5, 10);
  },
  /** C: Krake mit spitzer Kuppel, schläfrigen Augen und geringelten Fangarmen mit Saugnäpfen */
  c(x) {
    x.save(); wavyTop(x, waterline + 14); x.clip();
    const armSp = [
      chain([[42, 62], [24, 68], [12, 52], [20, 44]], [[20, 44], [26, 38], [34, 42], [29, 48]]),
      chain([[45, 66], [36, 80], [20, 86], [8, 78]], [[8, 78], [4, 74], [8, 70], [12, 73]]),
      chain([[52, 66], [56, 82], [74, 88], [86, 76]], [[86, 76], [90, 68], [82, 63], [78, 69]]),
      chain([[58, 62], [74, 62], [82, 48], [74, 40]], [[74, 40], [70, 34], [64, 38], [66, 43]]),
      chain([[49, 66], [49, 82], [40, 92], [28, 94]]),
    ];
    const arms = armSp.map((sp, i) => form(sp, [[0, 10], [0.4, 6], [1, 0.5]], { seed: 41 + i, wob: 0.5 }));
    const dome = form(chain([[50, 66], [48, 54], [50, 40], [53, 16]]), [[0, 28], [0.3, 31], [0.65, 22], [0.9, 10], [1, 0.8]], { seed: 44, wob: 0.55 });
    outline(x, [...arms, dome], 2.4);
    arms.forEach((a, i) => {
      fillPart(x, a, C.sea, 0.5); shade(x, a, { seed: i + 1, depth: 0.6 });
      x.fillStyle = PAPER; pen(x, 0.35, INK, 0.9);
      for (let k = 6; k < a.n - 4; k += 5) { const p = a.s[k], q = a.s[k + 1], l = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1, nx = -(q[1] - p[1]) / l, ny = (q[0] - p[0]) / l, rr = 0.35 + 1.3 * (1 - k / a.n) * 0.7, sd = i % 2 ? 1 : -1; x.beginPath(); x.arc(p[0] + nx * 1.3 * sd, p[1] + ny * 1.3 * sd, rr, 0, TAU); x.fill(); x.stroke(); }
    });
    fillPart(x, dome, C.sea, 0.6); shade(x, dome, { seed: 5, depth: 0.55 });
    x.save(); x.clip(dome.path); pen(x, 0.38, INK, 0.7); const r = rng(8);
    for (let i = 0; i < 22; i++) { const px = 36 + i * 1.4 + r(); x.beginPath(); x.moveTo(px, 62); x.quadraticCurveTo(px + 3 - i * 0.2, 40 - r() * 4, 52 + (px - 52) * 0.1, 14 + r() * 6); x.stroke(); }
    x.globalAlpha = 1; x.restore();
    for (const [ex, ey] of [[44, 51], [58, 52]]) { x.fillStyle = PAPER; dot(x, ex, ey, 3.8); pen(x, 0.8, INK, 1); x.beginPath(); x.arc(ex, ey, 3.8, 0, TAU); x.stroke(); x.fillStyle = C.mouth; dot(x, ex + 0.5, ey + 0.3, 2); x.fillStyle = INK; x.beginPath(); x.ellipse(ex + 0.5, ey + 0.3, 0.4, 1.7, 0, 0, TAU); x.fill(); x.fillStyle = C.sea; x.beginPath(); x.moveTo(ex - 4, ey - 0.4); x.quadraticCurveTo(ex, ey - 3.4, ex + 4, ey - 0.4); x.lineTo(ex + 4, ey - 4.4); x.lineTo(ex - 4, ey - 4.4); x.closePath(); x.fill(); pen(x, 0.8, INK, 1); x.beginPath(); x.moveTo(ex - 4, ey - 0.4); x.quadraticCurveTo(ex, ey - 3.4, ex + 4, ey - 0.4); x.stroke(); }
    x.globalAlpha = 1; x.restore();
    ripples(x, waterline + 14, 4, 92, 9, 3); foam(x, 18, waterline + 13.5, 10); foam(x, 80, waterline + 13.5, 10);
  },
  /** D: Meerdrache: Drachenkopf, Schuppenleib, Flossenflügel, Schwanzflosse */
  d(x) {
    x.save(); wavyTop(x, waterline); x.clip();
    const fin = blob([[76, 46], [84, 44], [92, 34], [94, 22], [89, 25], [86, 20], [83, 27], [78, 28], [77, 38]]);
    outline(x, [fin], 2.2); fillPart(x, fin, C.seaD, 0.6); hatchArea(x, fin, [76, 18, 96, 48], C.sea, { gap: 1.1, ang: 1.2, lift: 0.6 });
    pen(x, 0.4, INK, 0.8); for (let i = 0; i < 6; i++) ln(x, 77, 44, 82 + i * 2.1, 22 + i * 2.6); x.globalAlpha = 1;
    const sp = chain([[28, 56], [28, 40], [50, 32], [60, 46]], [[60, 46], [66, 58], [76, 58], [78, 46]]);
    const body = form(sp, [[0, 11], [0.25, 13], [0.65, 9], [1, 4]], { seed: 51, wob: 0.4 });
    const wingFin = blob([[52, 46], [44, 62], [47, 70], [54, 66], [58, 72], [64, 66], [68, 56], [64, 48]]);
    outline(x, [body, wingFin], 2.4);
    fillPart(x, body, C.sea, 0.5); shade(x, body, { seed: 7, depth: 0.7 }); belly(x, body, 1, 0.35, C.belly, { seed: 3 }); scales(x, body, { seed: 6, size: 1.6 });
    fillPart(x, wingFin, C.seaD, 0.6); hatchArea(x, wingFin, [42, 44, 70, 74], C.sea, { gap: 1.1, ang: 0.9, lift: 0.5 });
    pen(x, 0.6, INK, 0.9); for (const t of [[45, 63], [52, 70], [61, 69], [67, 58]]) { x.beginPath(); x.moveTo(58, 48); x.lineTo(t[0], t[1]); x.stroke(); } x.globalAlpha = 1;
    crest(x, sp, C.bone, 5, 3.2, 4);
    x.restore();
    x.save(); x.translate(33, 54); x.scale(-1, 1); dhead(x, 0, 0, 0.9, -0.5, { skin: C.sea, dark: C.seaD, beard: true }); x.restore();
    ripples(x, waterline, 2, 94, 4, 5); foam(x, 22, waterline - 0.5, 12); foam(x, 70, waterline - 0.5, 12);
  },
};

export const FAUNA_DRAWINGS = { 'dragon-a': dragons.a, 'dragon-b': dragons.b, 'dragon-c': dragons.c, 'sea-a': seas.a, 'sea-b': seas.b, 'sea-c': seas.c, 'sea-d': seas.d };

/** Zeichnet eine Figur auf eine Fläche der Größe SIZE; mirror = seitenverkehrt. */
export function paintFauna(name, ctx, mirror = false) {
  ctx.save(); ctx.clearRect(0, 0, SIZE, SIZE);
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.scale(2, 2);
  if (mirror) { ctx.translate(G, 0); ctx.scale(-1, 1); }
  FAUNA_DRAWINGS[name](ctx);
  ctx.restore();
}
export const FAUNA_SIZE = SIZE;
