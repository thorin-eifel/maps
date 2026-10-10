// Windströmung: Partikel, die dem 10-m-Wind des DWD-Modells ICON-D2 folgen (Vorbild: Strömungsansichten wie bei earth.nullschool.net).
// Zweck: wind.json (vom eigenen Server, Collector dwd_icon_d2_wind) liefert u/v in m/s auf einem ~3-km-Gitter. Tausende kurze Striche
//        wandern mit dem Wind über die Karte und hinterlassen einen verblassenden Schweif; Farbe = Windgeschwindigkeit.
// Darstellung, keine Messung: Modellwerte für den Rasterpunkt. Geschwindigkeit der Striche ist beschleunigt (Zeitraffer), steht in der Legende.
// Ohne Daten, bei ausgeschalteter Ebene oder im Hintergrund-Tab zeichnet nichts und die Schleife ruht. Keine Personen- oder Nutzerdaten.
// Aufruf: const w = createWind(map, { center: {lat, lon}, radiusKm: 120, fadeKm: 30 });
//         w.setGrid(payload.grid); w.setEnabled(true); w.sample(lon, lat) → { u, v, speed, from } | null
import { vignetteFactor } from './ripples.js';

const FRAME_MS = 33;
const TRAIL_FADE = 0.07;       // Anteil, der je Bild vom Schweif abgezogen wird (kleiner = längerer Schweif)
const TIME_SCALE = 900;        // Zeitraffer: 10 m/s sind dann bei Zoom 9 etwa 90 Pixel pro Sekunde
const MAX_PX_PER_S = 160;
const SLOW_FROM_ZOOM = 9;      // ab hier wird der Zeitraffer mit jeder Zoomstufe halbiert: die Bildschirmgeschwindigkeit bleibt beim Hineinzoomen gleich
const MIN_LIFE = 60, MAX_LIFE = 140;   // Bilder
const PER_PIXELS = 2200;       // ein Partikel je so viele Bildschirmpixel
const MAX_PARTICLES = 4500;
const TAU = Math.PI * 2;
const R_EARTH_KM = 6371;

// Farbstufen (m/s → Farbe). Zwei Schichten, zwei Farbfamilien, damit man sie auseinanderhält und beide lesbar bleiben:
// obere Schicht (reines Modell) blau, untere Schicht (Gelände) orange. Blau und Orange liegen im Farbkreis gegenüber und
// mischen sich dort, wo beide laufen, nicht zu Grau. Die Windstärke steckt im Helligkeitsverlauf: dunkle Karte, stärker = heller;
// helle Karte, stärker = dunkler (helle Striche verschwinden dort im Relief), dort zusätzlich dicker und deckender.
export const WIND_STOPS = {
  dark: [[0, '#4f7fb8'], [2, '#5a8cc6'], [4, '#67a0d6'], [7, '#7ab4e4'], [10, '#92c8f0'], [14, '#addcf8'], [18, '#c6ebfc'], [24, '#dff5fe'], [30, '#f2fbff']],
  light: [[0, '#6c98d0'], [2, '#5280c2'], [4, '#3d6db5'], [7, '#2d5ba3'], [10, '#1f4a90'], [14, '#163c7a'], [18, '#0f2f66'], [24, '#0a2150'], [30, '#06153a']],
};
export const WIND_STOPS_LOW = {
  dark: [[0, '#a8641e'], [2, '#bf7424'], [4, '#d68529'], [7, '#e8982f'], [10, '#f4ab3c'], [14, '#fabf5c'], [18, '#fdd283'], [24, '#fee3ab'], [30, '#fff1d4']],
  light: [[0, '#e8943c'], [2, '#dc7c26'], [4, '#cc6714'], [7, '#b8550a'], [10, '#a24607'], [14, '#8c3a05'], [18, '#772f04'], [24, '#612503'], [30, '#4a1b02']],
};
const BIN_EDGES = [1.5, 3, 5, 7.5, 10, 14, 18, 24];   // 9 Klassen
const STYLE = { dark: { alphas: [0.9, 0.55, 0.22], width: 1 }, light: { alphas: [1, 0.78, 0.4], width: 1 } };
const ALPHA_LEVELS = 3;
const isDark = () => document.documentElement.dataset.ansicht === 'dunkel';

export const WIND_LEGEND_MAX = 30;

/** Farbverlauf für die Legende; Farben über CSSOM gesetzt (die CSP verbietet Inline-Styles im Markup). */
export function fillWindLegend(bar, dark = isDark(), low = false) {
  const stops = low ? WIND_STOPS_LOW : WIND_STOPS;
  bar.style.background = `linear-gradient(to right, ${stops[dark ? 'dark' : 'light'].map(([v, c]) => `${c} ${((v / WIND_LEGEND_MAX) * 100).toFixed(1)}%`).join(', ')})`;
}

const speedBin = (s) => { let b = 0; while (b < BIN_EDGES.length && s >= BIN_EDGES[b]) b++; return b; };

function distKm(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180, dLat = (lat2 - lat1) * r, dLon = (lon2 - lon1) * r;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
  return 2 * R_EARTH_KM * Math.asin(Math.sqrt(a));
}

// adjusted: true → zweite, untere Schicht: derselbe Modellwind, verändert durch die Geländefaktoren (terrain.js). Gezeichnet werden Partikel
//             nur dort, wo das Gelände etwas ändert (Täler, Kämme); sonst läge sie als Doppelung auf der oberen Schicht.
export function createWind(map, { center, radiusKm, fadeKm, vig = null, adjusted = false }) {
  // Ausblendfaktor am Ort: entlang der Landesgrenze (vig) oder als Kreis um die Mitte
  const vf = vig ?? ((lon, lat) => vignetteFactor(distKm(center.lat, center.lon, lat, lon), radiusKm, fadeKm));
  const host = map.getContainer();
  const canvas = document.createElement('canvas');
  canvas.className = adjusted ? 'windflow windflow-low' : 'windflow';
  canvas.setAttribute('aria-hidden', 'true');
  host.insertBefore(canvas, host.querySelector('.maplibregl-control-container'));
  const ctx = canvas.getContext('2d');
  const none = { setGrid: () => {}, setEnabled: () => {}, setTerrain: () => {}, sample: () => null, stats: () => ({}) };
  if (!ctx) return none;

  let terrain = null, ttmp = {};   // Geländefaktoren (nur für adjusted)
  const MIN_INFLUENCE = 0.12;
  let grid = null;             // { lon0, lat1, dlon, dlat, nx, ny, u: Float32Array, v: Float32Array }
  let enabled = false;
  let raf = 0, last = 0, dpr = 1;
  let parts = [];              // { lon, lat, age, life }
  let cw = 0, ch = 0;

  function setGrid(g) {
    if (!g?.u?.length || !g.bbox) { grid = null; return; }
    const { nx, ny } = g;
    const u = new Float32Array(nx * ny), v = new Float32Array(nx * ny);
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) { u[j * nx + i] = g.u[j][i]; v[j * nx + i] = g.v[j][i]; }
    grid = { lon0: g.bbox[0], lat1: g.bbox[3], dlon: g.dlon, dlat: g.dlat, nx, ny, u, v };
    kick();
  }

  /** Bilinear interpolierter Wind; null außerhalb des Gitters. */
  function sample(lon, lat, out = {}) {
    if (!grid) return null;
    const fx = (lon - grid.lon0) / grid.dlon, fy = (grid.lat1 - lat) / grid.dlat;
    if (fx < 0 || fy < 0 || fx > grid.nx - 1 || fy > grid.ny - 1) return null;
    const i = Math.min(grid.nx - 2, Math.floor(fx)), j = Math.min(grid.ny - 2, Math.floor(fy));
    const tx = fx - i, ty = fy - j, k = j * grid.nx + i, n = grid.nx;
    const lerp = (a) => (a[k] * (1 - tx) + a[k + 1] * tx) * (1 - ty) + (a[k + n] * (1 - tx) + a[k + n + 1] * tx) * ty;
    out.u = lerp(grid.u); out.v = lerp(grid.v);
    if (adjusted) {
      const t = terrain?.at(lon, lat, ttmp);
      out.influence = t ? Math.max(t.valley, t.ridge * 0.5) : 0;
      if (t) [out.u, out.v] = terrain.adjust(out.u, out.v, t);
    }
    out.speed = Math.hypot(out.u, out.v);
    out.from = (Math.atan2(-out.u, -out.v) * 180 / Math.PI + 360) % 360; // meteorologisch: Richtung, AUS der der Wind kommt
    return out;
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    cw = host.clientWidth; ch = host.clientHeight;
    canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr);
    reseed();
  }

  function spawn(p) {
    const b = map.getBounds();
    for (let t = 0; t < (adjusted ? 80 : 8); t++) {
      const lon = b.getWest() + Math.random() * (b.getEast() - b.getWest());
      const lat = b.getSouth() + Math.random() * (b.getNorth() - b.getSouth());
      const smp = sample(lon, lat);
      if (!smp || (adjusted && smp.influence < MIN_INFLUENCE)) continue;
      if (vf(lon, lat) <= 0.02) continue;
      p.lon = lon; p.lat = lat; p.age = 0; p.life = MIN_LIFE + Math.random() * (MAX_LIFE - MIN_LIFE);
      return true;
    }
    p.life = 0; p.age = 1; p.lon = NaN;
    return false;
  }

  function reseed() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const n = Math.min(MAX_PARTICLES, Math.round((cw * ch) / PER_PIXELS));
    parts = Array.from({ length: n }, () => { const p = { lon: NaN, lat: 0, age: 0, life: 0 }; spawn(p); p.age = Math.random() * p.life; return p; });
  }

  const bins = Array.from({ length: (BIN_EDGES.length + 1) * ALPHA_LEVELS }, () => []);
  const tmp = {};
  function frame(now) {
    raf = 0;
    if (!enabled || !grid || document.hidden) { last = 0; return; }
    raf = requestAnimationFrame(frame);
    if (now - last < FRAME_MS) return;
    const dt = last ? Math.min(0.1, (now - last) / 1000) : FRAME_MS / 1000;
    last = now;
    // Schweif ausblenden (transparente Fläche): alte Striche verlieren Deckkraft
    ctx.globalCompositeOperation = 'destination-out';
    ctx.fillStyle = `rgba(0,0,0,${TRAIL_FADE})`;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.globalCompositeOperation = 'source-over';
    const zoom = map.getZoom();
    const damp = zoom > SLOW_FROM_ZOOM ? 2 ** -(zoom - SLOW_FROM_ZOOM) : 1;
    const cosf = (lat) => Math.cos((lat * Math.PI) / 180);
    for (const b of bins) b.length = 0;
    for (const p of parts) {
      if (!(p.age < p.life) || Number.isNaN(p.lon)) { spawn(p); continue; }
      const w = sample(p.lon, p.lat, tmp);
      if (!w || (adjusted && w.influence < MIN_INFLUENCE * 0.6)) { spawn(p); continue; }   // aus dem Talbereich gelaufen: neu setzen
      const mpp = (78271.517 * cosf(p.lat)) / 2 ** zoom;              // Meter je Bildpunkt (512er Kacheln)
      let k = (TIME_SCALE * damp * dt) / mpp;                                 // Pixel je m/s in diesem Bild
      if (w.speed * k > MAX_PX_PER_S * dt) k = (MAX_PX_PER_S * dt) / Math.max(w.speed, 0.01);
      const a = map.project([p.lon, p.lat]);
      const dx = w.u * k, dy = -w.v * k;                               // Bildschirm: y nach unten
      const nlngLat = map.unproject([a.x + dx, a.y + dy]);
      const f = vf(nlngLat.lng, nlngLat.lat);
      const edge = Math.min(p.age / 12, (p.life - p.age) / 12, 1);     // sanftes Ein- und Ausblenden der Lebensdauer
      const lvl = f > 0.66 ? 0 : f > 0.33 ? 1 : 2;
      if (f > 0.05 && edge > 0.15) bins[speedBin(w.speed) * ALPHA_LEVELS + lvl].push(a.x, a.y, a.x + dx, a.y + dy);
      p.lon = nlngLat.lng; p.lat = nlngLat.lat; p.age++;
    }
    ctx.save();
    ctx.scale(dpr, dpr);
    const mode = isDark() ? 'dark' : 'light', st = STYLE[mode], colors = (adjusted ? WIND_STOPS_LOW : WIND_STOPS)[mode].map((x) => x[1]);
    ctx.lineWidth = st.width; ctx.lineCap = 'round';
    bins.forEach((seg, bi) => {
      if (!seg.length) return;
      ctx.strokeStyle = colors[Math.floor(bi / ALPHA_LEVELS)];
      ctx.globalAlpha = st.alphas[bi % ALPHA_LEVELS];
      ctx.beginPath();
      for (let s = 0; s < seg.length; s += 4) { ctx.moveTo(seg[s], seg[s + 1]); ctx.lineTo(seg[s + 2], seg[s + 3]); }
      ctx.stroke();
    });
    ctx.restore();
  }

  function setTerrain(t) { terrain = t; if (adjusted) reseed(); }
  function kick() { if (!raf && enabled && grid && !document.hidden) raf = requestAnimationFrame(frame); }
  function setEnabled(on) {
    enabled = !!on;
    canvas.style.display = enabled ? '' : 'none';
    if (enabled) { resize(); kick(); } else { cancelAnimationFrame(raf); raf = 0; ctx.clearRect(0, 0, canvas.width, canvas.height); }
  }

  map.on('movestart', () => ctx.clearRect(0, 0, canvas.width, canvas.height));
  map.on('moveend', () => { if (enabled) reseed(); });
  map.on('resize', () => { if (enabled) resize(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; last = 0; } else kick(); });
  canvas.style.display = 'none';
  return { setGrid, setEnabled, setTerrain, sample, stats: () => ({ enabled, particles: parts.length, grid: grid ? `${grid.nx}x${grid.ny}` : null, running: !!raf }) };
}
