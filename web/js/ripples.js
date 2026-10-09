// Regentropfen: kleine, flache Ringe wie auf einer Pfütze, verteilt nach der Stärke des Regenradars.
// Zweck: Das Radarbild (radar.png, vom eigenen Server) wird einmal in ein grobes Raster gelesen; aus den Zellen mit Niederschlag
//        entstehen Ringe, die sich ausdehnen und verblassen. Stärkerer Regen: mehr, größere, kräftigere Ringe (Doppelring).
// Ohne Daten, bei ausgeschalteter Ebene, im Hintergrund-Tab oder bei fehlender Unterstützung zeichnet nichts und die Schleife ruht.
// Es werden nur Geokoordinaten und Farbwerte aus dem Bild verwendet, keine Personen- oder Nutzerdaten.
// Aufruf: const rip = createRipples(map, { center: {lat, lon}, radiusKm: 120, fadeKm: 30 });
//         rip.setRadar(url, corners); rip.setEnabled(true);
// Laser-Modus (rip.setLaser(() => ({ theta })) mit dem Strahlwinkel des Sweeps): Ringe, die der Strahl überstreicht, verdampfen zu
//         Dampfwolken, die aufsteigen, und fallen nach ein paar Sekunden als Regen (Fallstrich, dann Ring) wieder herab. Hinter dem
//         Strahl regnet es kurz nicht. Reine Darstellung, nichts wird gespeichert.
// Wind (rip.setWind(fn), Modellwind ICON-D2 aus wind.js): Dampf driftet mit dem Wind (im Zeitraffer, mit luvseitigem Schweif), der
//         Regen fällt dort, wo der Dampf angekommen ist, und kommt schräg herab.

const FRAME_MS = 33;          // ~30 Bilder pro Sekunde reichen für Ringe
const RATE_PER_WEIGHT = 3.2;  // neue Ringe je Sekunde und Gewichtseinheit der sichtbaren Zellen: Dichte folgt dem Radarwert
const MAX_RATE = 640;         // Obergrenze Ringe je Sekunde
const WEIGHT_FLOOR = 0.002;   // schwacher Regen bekommt vereinzelt Tropfen, nicht gar keine
const MAX_PER_FRAME = 48;     // Obergrenze nach Aussetzern (Tab im Hintergrund, träge Rechner)
const MAX_ACTIVE = 1600;
const GRID_DIV = 6;           // Radarbild ist 6-fach hochgerechnet; ein Rasterpunkt je Originalpixel (~1,5 km)
const TAU = Math.PI * 2;
const DEAD_RAD = 1.6;         // Laser: so weit hinter dem Strahl (Bogenmaß, ~90°, ~1,5 s) fällt kein neuer Regen
const MAX_STEAM = 700;
const FALL_MS = 170;          // Fallstrich vor dem Ring, wenn Dampf wieder zu Regen wird
const WIND_VISUAL = 1000;     // Zeitraffer für die Winddrift des Dampfs (wie bei den Windstrichen etwa 1000-fach): 2 m/s wären sonst bei 2 bis 4 s Lebensdauer kaum zu sehen
const MAX_DRIFT_PX_S = 90;    // Obergrenze der Drift in Pixeln je Sekunde
const MIN_ALPHA = 40;         // darunter gilt die Zelle als trocken

const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
const unmerc = (y) => (Math.atan(Math.sinh(y)) * 180) / Math.PI;

/** Stärke 0..1 aus der Radarfarbe: hell/blau gering, grün, gelb, orange, rot, violett stark. Bewusst grob, es ist eine Anmutung, kein Messwert. */
export function intensityFromRgb(r, g, b) {
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (max === 0 || d / max < 0.12) return 0.3;
  let h;
  if (max === r) h = ((g - b) / d) % 6; else if (max === g) h = (b - r) / d + 2; else h = (r - g) / d + 4;
  h = (h * 60 + 360) % 360;
  if (h >= 260 && h < 345) return 0.98;      // violett, magenta
  if (h >= 345 || h < 15) return 0.85;       // rot
  if (h < 40) return 0.7;                    // orange
  if (h < 55) return 0.58;                   // gelb
  if (h < 80) return 0.5;                    // gelbgrün
  if (h < 150) return 0.35;                  // grün
  if (h < 190) return 0.22;                  // türkis
  return 0.15;                               // blau
}

/** Deckkraftfaktor: 1 bis zum Radius, dann wie die schwarze Vignette auf 0 (Smoothstep), damit im Dunkel nichts leuchtet. */
export function vignetteFactor(distKm, radiusKm, fadeKm) {
  if (distKm <= radiusKm) return 1;
  if (distKm >= radiusKm + fadeKm) return 0;
  const t = (distKm - radiusKm) / fadeKm;
  return 1 - t * t * (3 - 2 * t);
}

export function createRipples(map, { center, radiusKm, fadeKm, onSizzle = null }) {
  const host = map.getContainer();
  const canvas = document.createElement('canvas');
  canvas.className = 'ripples';
  canvas.setAttribute('aria-hidden', 'true');
  // Unter die Bedienelemente der Karte setzen, damit Zoom und Attribution klickbar bleiben
  host.insertBefore(canvas, host.querySelector('.maplibregl-control-container'));
  const ctx = canvas.getContext('2d');
  if (!ctx) return { setRadar: async () => {}, setEnabled: () => {}, setLaser: () => {}, setWind: () => {}, stats: () => ({}) };

  let cells = null;            // { lon[], lat[], inten[], rgb[], w[] }
  let loadedUrl = '';
  let enabled = false;
  let raf = 0, last = 0;
  let dpr = 1;
  const drops = [];            // { lon, lat, born, life, rmax, inten, rgb, rings, fallMs? }
  const steam = [];            // { lon, lat, born, life, size, seed, inten, rgb }
  let beam = null;             // () => ({ theta }) | null, Strahl des Sweeps im Laser-Modus
  let prevTheta = null;
  let windAt = null;           // (lon, lat, out) => { u, v } | null; Modellwind (m/s) aus wind.js
  const wtmp = {};
  // weicher Dampfballen als Sprite: billig zu zeichnen, auch mit hunderten Wolken
  const sprite = document.createElement('canvas');
  sprite.width = sprite.height = 64;
  {
    const sctx = sprite.getContext('2d');
    const g = sctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, 'rgba(236,240,246,0.95)'); g.addColorStop(0.45, 'rgba(226,232,240,0.45)'); g.addColorStop(1, 'rgba(226,232,240,0)');
    sctx.fillStyle = g; sctx.fillRect(0, 0, 64, 64);
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(host.clientWidth * dpr);
    canvas.height = Math.round(host.clientHeight * dpr);
  }

  async function setRadar(url, corners) {
    if (!url || url === loadedUrl || !corners?.length) return;
    loadedUrl = url;
    try {
      const img = new Image();
      img.decoding = 'async';
      img.src = url;
      await img.decode();
      const gw = Math.max(8, Math.round(img.naturalWidth / GRID_DIV)), gh = Math.max(8, Math.round(img.naturalHeight / GRID_DIV));
      const off = document.createElement('canvas');
      off.width = gw; off.height = gh;
      const octx = off.getContext('2d', { willReadFrequently: true });
      octx.drawImage(img, 0, 0, gw, gh);
      const px = octx.getImageData(0, 0, gw, gh).data;
      const [nw, ne, , sw] = corners;              // [[lon0,lat1],[lon1,lat1],[lon1,lat0],[lon0,lat0]]
      const lon0 = nw[0], lon1 = ne[0], yN = merc(nw[1]), yS = merc(sw[1]);
      const out = { lon: [], lat: [], inten: [], rgb: [], w: [] };
      // Rand der Radarabdeckung: Zellen in 2 Rasterpunkten Abstand zu einer leeren Zelle zeigen Mischfarben aus der Glättung
      // (violett, orange, braun), die wie starker Regen aussehen. Sie bekommen keine Tropfen; der Bildrand selbst zählt nicht als Rand.
      const nearEdge = (i, j) => {
        for (let dj = -2; dj <= 2; dj++) for (let di = -2; di <= 2; di++) {
          const ii = i + di, jj = j + dj;
          if (ii < 0 || jj < 0 || ii >= gw || jj >= gh) continue;
          if (px[(jj * gw + ii) * 4 + 3] < MIN_ALPHA) return true;
        }
        return false;
      };
      for (let j = 0; j < gh; j++) {
        const lat = unmerc(yN + ((j + 0.5) / gh) * (yS - yN));
        for (let i = 0; i < gw; i++) {
          const k = (j * gw + i) * 4, a = px[k + 3];
          if (a < MIN_ALPHA || nearEdge(i, j)) continue;
          let base = intensityFromRgb(px[k], px[k + 1], px[k + 2]);
          if (base > 0.9 && a < 200) base = 0.3;   // halbtransparentes Violett ist der Saum der Radarabdeckung, kein Starkregen (sonst Tropfenhaufen am Rand)
          const inten = base * (0.6 + 0.4 * (a / 255));
          out.lon.push(lon0 + ((i + 0.5) / gw) * (lon1 - lon0));
          out.lat.push(lat);
          out.inten.push(inten);
          out.rgb.push([px[k], px[k + 1], px[k + 2]]);
          out.w.push(inten ** 4 + WEIGHT_FLOOR);   // überproportional: starker Regen ist deutlich dichter als Nieselregen
        }
      }
      cells = out.lon.length ? out : null;
      drops.length = 0;
      viewDirty = true;
      kick();
    } catch (err) {
      console.warn('Regentropfen: Radarbild nicht lesbar:', err?.message ?? err);
      cells = null;
    }
  }

  // Sichtbare Zellen mit kumulierten Gewichten; wird nur bei Kartenbewegung oder neuem Radarbild neu gebaut
  let view = { idx: [], cum: [], total: 0 };
  let viewDirty = true, viewAt = 0;
  function buildView(w, h, now) {
    viewDirty = false; viewAt = now;
    const idx = [], cum = [];
    let total = 0;
    for (let n = 0; n < cells.lon.length; n++) {
      const p = map.project([cells.lon[n], cells.lat[n]]);
      if (p.x < -24 || p.y < -24 || p.x > w + 24 || p.y > h + 24) continue;
      total += cells.w[n];
      idx.push(n); cum.push(total);
    }
    view = { idx, cum, total };
  }
  function pick() {
    const { cum, total } = view;
    const x = Math.random() * total;
    let lo = 0, hi = cum.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (cum[mid] < x) lo = mid + 1; else hi = mid; }
    return view.idx[lo];
  }

  let centerPx = { x: 0, y: 0 };
  // Peilwinkel eines Bildschirmpunkts vom Kartenzentrum (Bogenmaß, im Uhrzeigersinn ab Norden) wie beim Sweep
  const bearing = (q) => (Math.atan2(q.x - centerPx.x, -(q.y - centerPx.y)) + TAU) % TAU;
  let acc = 0;                 // aufgelaufene, noch nicht erzeugte Ringe
  function spawn(now, dt, zoomScale, th) {
    if (!view.idx.length) return;
    // Rate aus dem Gewicht der sichtbaren Zellen: Gewitterzelle viel, Nieselregen wenig, trockener Ausschnitt nichts
    const rate = Math.min(MAX_RATE, RATE_PER_WEIGHT * view.total);
    acc = Math.min(MAX_PER_FRAME, acc + (rate * dt) / 1000);
    const want = Math.floor(acc);
    let made = 0;
    for (let tries = 0; made < want && tries < want * 3 && drops.length < MAX_ACTIVE; tries++) {
      const n = pick();
      if (th != null) {     // Laser: im Sektor direkt hinter dem Strahl ist der Regen weggebrannt
        const q = map.project([cells.lon[n], cells.lat[n]]);
        const lag = (th - bearing(q) + TAU * 2) % TAU;
        if (lag < DEAD_RAD) continue;
      }
      // kleine Streuung innerhalb der Zelle (~±0,7 km), sonst sieht man das Raster
      const lon = cells.lon[n] + (Math.random() - 0.5) * 0.02, lat = cells.lat[n] + (Math.random() - 0.5) * 0.013;
      const inten = cells.inten[n];
      drops.push({
        lon, lat, born: now, inten, rgb: cells.rgb[n],
        life: 900 + Math.random() * 900 + inten * 700,
        rmax: (4 + 13 * inten) * zoomScale * (0.7 + Math.random() * 0.6),
        rings: inten > 0.5 ? 2 : 1,
      });
      made++;
    }
    acc -= made;
  }

  function frame(now) {
    raf = 0;
    if (!enabled || document.hidden || !cells) { ctx.clearRect(0, 0, canvas.width, canvas.height); return; }
    raf = requestAnimationFrame(frame);
    if (now - last < FRAME_MS) return;
    const dt = Math.min(500, last ? now - last : FRAME_MS);
    last = now;
    const w = host.clientWidth, h = host.clientHeight;
    if (canvas.width !== Math.round(w * dpr)) resize();
    const zoomScale = Math.min(2.4, Math.max(0.7, 2 ** ((map.getZoom() - 8) * 0.5)));
    if (viewDirty && now - viewAt > 250) buildView(w, h, now);
    // Laser: Strahlwinkel jetzt und im letzten Bild; überstrichene Ringe verdampfen
    let th = null, crossed = null;
    const b = beam?.();
    if (b) {
      th = b.theta;
      if (prevTheta != null) { const a0 = prevTheta; crossed = (a) => (a0 <= th ? a > a0 && a <= th : a > a0 || a <= th); }
      prevTheta = th;
    } else prevTheta = null;
    if (th != null) centerPx = map.project([center.lon, center.lat]);
    spawn(now, dt, zoomScale, th);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const dark = document.documentElement.dataset.ansicht === 'dunkel';
    const cosLat = Math.cos((center.lat * Math.PI) / 180);
    let burned = 0;                                          // Treffer des Lasers in diesem Bild (für das Zischen)
    for (let i = drops.length - 1; i >= 0; i--) {
      const d = drops[i], age = now - d.born, t = age / d.life;
      if (t >= 1) { drops.splice(i, 1); continue; }
      const dx = (d.lon - center.lon) * cosLat * 111.32, dy = (d.lat - center.lat) * 110.57;
      const vf = vignetteFactor(Math.hypot(dx, dy), radiusKm, fadeKm);
      if (vf < 0.02) continue;
      const p = map.project([d.lon, d.lat]);
      if (crossed && age >= 0 && crossed(bearing(p))) {      // vom Laser getroffen: Ring weg, Dampf steigt auf
        drops.splice(i, 1); burned++;
        if (steam.length < MAX_STEAM) steam.push({ lon: d.lon, lat: d.lat, born: now, life: 1800 + Math.random() * 2200, size: (9 + 22 * d.inten) * zoomScale, seed: Math.random() * TAU, inten: d.inten, rgb: d.rgb });
        continue;
      }
      const [r, g, b] = d.rgb;
      const k = dark ? 1.3 : 0.35;              // hell auf dunkel, dunkel auf hell: bleibt auf beiden Karten lesbar
      ctx.strokeStyle = `rgb(${Math.min(255, r * k)},${Math.min(255, g * k)},${Math.min(255, b * k)})`;
      if (age < 0) {                                          // zurückkehrender Regen: erst ein Fallstrich von oben
        const s0 = Math.min(1, -age / (d.fallMs || FALL_MS)), hy = p.y - 30 * zoomScale * s0;
        const sx = 30 * zoomScale * (d.slant || 0) * s0;       // Regen kommt mit dem Wind schräg herab: Fallweg liegt luvseitig
        ctx.globalAlpha = Math.min(1, vf * 0.85); ctx.lineWidth = 1.4 + d.inten;
        ctx.beginPath(); ctx.moveTo(p.x - sx - (d.slant || 0) * 9, hy - 9); ctx.lineTo(p.x - sx, hy); ctx.stroke();
        continue;
      }
      for (let ring = 0; ring < d.rings; ring++) {
        const tt = t - ring * 0.22;
        if (tt <= 0 || tt >= 1) continue;
        const rx = 1 + d.rmax * (1 - (1 - tt) ** 2);   // schnell auf, dann ruhig aus
        ctx.globalAlpha = Math.min(1, vf * (1 - tt) ** 1.3 * (0.5 + 0.5 * d.inten));
        ctx.lineWidth = 1.1 + d.inten * 1.3;
        ctx.beginPath();
        ctx.ellipse(p.x, p.y, rx, rx * 0.55, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    if (burned) onSizzle?.(burned);
    // Dampf: steigt auf, weitet sich und verblasst; danach fällt er als Regen (Fallstrich, dann Doppelring) wieder herab
    for (let i = steam.length - 1; i >= 0; i--) {
      const sp = steam[i], t = (now - sp.born) / sp.life;
      if (t >= 1) {
        steam.splice(i, 1);
        drops.push({
          lon: sp.lon + (Math.random() - 0.5) * 0.01, lat: sp.lat + (Math.random() - 0.5) * 0.007, born: now + FALL_MS, fallMs: FALL_MS,
          inten: sp.inten, rgb: sp.rgb, slant: sp.slant || 0, life: 1100 + Math.random() * 900 + sp.inten * 700,
          rmax: (5 + 15 * sp.inten) * zoomScale * (0.8 + Math.random() * 0.5), rings: 2,
        });
        continue;
      }
      // Wind verweht den Dampf: Modellwind am Ort, beschleunigt dargestellt; der Regen fällt später dort, wo der Dampf angekommen ist
      let wpx = 0, wpy = 0;
      const wv = windAt?.(sp.lon, sp.lat, wtmp);
      if (wv) {
        const cl = Math.cos((sp.lat * Math.PI) / 180), mpp = (78271.517 * cl) / 2 ** map.getZoom();
        const speedPx = (Math.hypot(wv.u, wv.v) * WIND_VISUAL) / mpp;          // Pixel je Sekunde
        const eff = WIND_VISUAL * (speedPx > MAX_DRIFT_PX_S ? MAX_DRIFT_PX_S / speedPx : 1);   // Meter je Sekunde und m/s
        const sec = dt / 1000;
        sp.lon += (wv.u * eff * sec) / (111320 * cl);
        sp.lat += (wv.v * eff * sec) / 110540;
        wpx = (wv.u * eff) / mpp; wpy = -(wv.v * eff) / mpp;                   // Bildschirmrichtung der Drift (Pixel je Sekunde)
        sp.slant = Math.max(-0.7, Math.min(0.7, wv.u * 0.06));
      }
      const dxs = (sp.lon - center.lon) * cosLat * 111.32, dys = (sp.lat - center.lat) * 110.57;
      const vfs = vignetteFactor(Math.hypot(dxs, dys), radiusKm, fadeKm);
      if (vfs < 0.02) continue;
      const p = map.project([sp.lon, sp.lat]);
      const rise = 44 * zoomScale * (1 - (1 - t) ** 2), size = sp.size * (0.7 + 1.1 * t);
      const x = p.x + Math.sin(sp.seed + t * 4) * 7 * zoomScale, y = p.y - rise;
      ctx.globalAlpha = Math.min(1, vfs * Math.min(1, t * 7) * (1 - t) ** 1.2 * (0.45 + 0.4 * sp.inten));
      ctx.drawImage(sprite, x - size, y - size, size * 2, size * 2);
      if (wpx || wpy) {                                   // Schweif luvseitig: zeigt, woher der Dampf weht
        const len = Math.hypot(wpx, wpy);
        if (len > 6) {
          const ux = wpx / len, uy = wpy / len, tail = Math.min(1.6, len / 40);
          const a0 = ctx.globalAlpha;
          for (let j = 1; j <= 2; j++) {
            ctx.globalAlpha = a0 * (j === 1 ? 0.55 : 0.28);
            const off = size * 0.8 * tail * j, sj = size * (1 - 0.12 * j);
            ctx.drawImage(sprite, x - ux * off - sj, y - uy * off - sj, sj * 2, sj * 2);
          }
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  function kick() { if (!raf && enabled && cells && !document.hidden) raf = requestAnimationFrame(frame); }
  function setEnabled(on) {
    enabled = !!on;
    if (!enabled) { drops.length = 0; steam.length = 0; ctx.clearRect(0, 0, canvas.width, canvas.height); }
    kick();
  }

  resize();
  map.on('resize', () => { resize(); viewDirty = true; });
  map.on('move', () => { viewDirty = true; });
  document.addEventListener('visibilitychange', kick);
  const stats = () => ({ cells: cells?.lon.length ?? 0, view: view.idx.length, total: Math.round(view.total * 10) / 10, drops: drops.length, steam: steam.length, steam0: steam[0] ? [steam[0].lon, steam[0].lat, steam[0].slant ?? null] : null, laser: !!beam, enabled, raf: !!raf, dirty: viewDirty, url: loadedUrl.slice(-30) });
  /** Laser-Modus: fn liefert den Strahlwinkel des Sweeps ({ theta } oder null); null schaltet aus, vorhandener Dampf fällt noch als Regen. */
  function setLaser(fn) { beam = fn; prevTheta = null; kick(); }
  /** Wind für die Dampfdrift: fn(lon, lat, out) füllt out.u/out.v (m/s, u nach Osten, v nach Norden) und liefert out oder null. */
  function setWind(fn) { windAt = fn; }
  return { setRadar, setEnabled, setLaser, setWind, stats };
}
