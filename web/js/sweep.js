// Radar-Sweep um Irrel (120-km-Kreis als Linie, der Strahl selbst reicht bis zum Bildschirmrand): ein Strahl läuft im Uhrzeigersinn um Irrel, überstreicht er ein Flugzeug, sendet es einen Ping.
// Läuft nur, solange die Luftverkehr-Ebene an ist, mindestens ein Flugzeug aktiv (nicht abgelaufen) ist, der Tab sichtbar ist
// und das System keine reduzierte Bewegung verlangt. Sonst steht alles still und die Zeichenfläche ist leer.
// Dazu die Schweife: 200 px lang, hinter dem Flugzeug entlang der beobachteten Bahn, nach hinten schwächer werdend. Die Bahn
// besteht aus den Positionen, die der Browser während dieser Sitzung gesehen hat; sie liegt nur im Arbeitsspeicher, wird nie
// gespeichert oder hochgeladen und verschwindet mit Neuladen, Ausblenden der Ebene oder Ablauf des Flugzeugs.
// Gezeichnet wird auf einer eigenen Canvas über der Karte (kein Drittanbieter, keine Inline-Styles im Markup: Größen per CSSOM).
export const SWEEP_GREEN = '#22c55e';
export const PING_ORANGE = '#ff5a1f'; // Pings, Flash und Schweife ziviler Flugzeuge (Strahl und Kreis bleiben grün)
const PING_ORANGE_RGB = '255,90,31';
const TAU = Math.PI * 2;
function TAU_TRAIL() { return TAU * 0.985; }
const PERIOD_S = 6;        // eine Umdrehung
const TRAIL = TAU_TRAIL(); // Nachleuchten des Strahls: fast ganzer Umlauf, so füllt der Strahl die ganze Kreisfläche
const PING_S = 2.4;        // Lebensdauer eines Pings
const PING_MAX_PX = 56;
const ZAP_S = 1.5;         // Laser-Modus: Lebensdauer des Treffer-Effekts (Spaß-Effekt, verändert keine Daten)
const TRAIL_PX = 200;       // Länge des Schweifs auf dem Bildschirm
const TRACK_MAX_POINTS = 1800; // Obergrenze je Flugzeug (30 Minuten bei 1 Punkt je Sekunde)
const TRACK_MIN_STEP_DEG = 0.00004; // ca. 4 m: kleinere Bewegungen erzeugen keinen Punkt

export function createSweep(map, { center, radiusKm, mil = '#8e44ad', reducedMotion = false, onPing = null }) {
  const canvas = document.createElement('canvas');
  canvas.className = 'sweep';
  canvas.setAttribute('aria-hidden', 'true');
  map.getCanvasContainer().appendChild(canvas);
  const ctx = canvas.getContext('2d');
  let planes = [];   // [{id, lng, lat, mil}]
  const tracks = new Map(); // id → [[lng, lat], …] (alt → neu), nur im Arbeitsspeicher
  let pings = [];    // [{lng, lat, t0, mil}]
  let raf = 0, last = 0, theta = 0, enabled = false, laser = false;
  let dpr = 1;


  function resize() {
    const box = map.getContainer();
    dpr = window.devicePixelRatio || 1;
    const w = box.clientWidth, h = box.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
    }
  }
  const clear = () => ctx.clearRect(0, 0, canvas.width, canvas.height);

  function drawTrails() {
    ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.lineWidth = 2.2 * dpr;
    for (const p of planes) {
      const pts = tracks.get(p.id);
      if (!pts || pts.length < 2) continue;
      ctx.strokeStyle = p.mil ? mil : PING_ORANGE;
      let acc = 0;
      let prev = map.project(pts[pts.length - 1]);
      for (let i = pts.length - 2; i >= 0 && acc < TRAIL_PX; i--) {
        const q = map.project(pts[i]);
        const seg = Math.hypot(q.x - prev.x, q.y - prev.y);
        if (seg < 0.3) continue;
        const take = Math.min(seg, TRAIL_PX - acc); // letztes Stück auf genau 200 px kürzen
        const k = take / seg;
        const ex = prev.x + (q.x - prev.x) * k, ey = prev.y + (q.y - prev.y) * k;
        ctx.globalAlpha = Math.pow(1 - (acc + take / 2) / TRAIL_PX, 1.4) * 0.9;
        ctx.beginPath(); ctx.moveTo(prev.x * dpr, prev.y * dpr); ctx.lineTo(ex * dpr, ey * dpr); ctx.stroke();
        acc += take; prev = q;
      }
    }
    ctx.globalAlpha = 1;
  }
  /** Laser trifft ein Flugzeug: weißer Blitz, Funken, danach ein Rauchwölkchen, das aufsteigt. Nur Darstellung. */
  function drawZap(x, y, k, seed) {
    if (k < 0.18) {
      const R = 34 * dpr, g = ctx.createRadialGradient(x, y, 0, x, y, R);
      g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.35, 'rgba(255,170,90,0.85)'); g.addColorStop(1, 'rgba(255,60,30,0)');
      ctx.globalAlpha = 1 - k / 0.18; ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(x, y, R, 0, TAU); ctx.fill();
    }
    const e = 1 - Math.pow(1 - Math.min(1, k / 0.6), 2);
    ctx.lineCap = 'round';
    for (let i = 0; i < 9; i++) {
      const a = seed + (i / 9) * TAU + Math.sin(seed * (i + 1)) * 0.3, d0 = (5 + 26 * e) * dpr, d1 = (9 + 40 * e) * dpr;
      ctx.globalAlpha = Math.max(0, 1 - k * 1.25);
      ctx.strokeStyle = i % 2 ? 'rgba(255,240,220,1)' : 'rgba(255,110,40,1)'; ctx.lineWidth = (i % 2 ? 1.4 : 2.2) * dpr;
      ctx.beginPath(); ctx.moveTo(x + Math.cos(a) * d0, y + Math.sin(a) * d0); ctx.lineTo(x + Math.cos(a) * d1, y + Math.sin(a) * d1); ctx.stroke();
    }
    if (k > 0.1) {
      const t = (k - 0.1) / 0.9;
      for (let i = 0; i < 3; i++) {
        const ox = Math.sin(seed * (i + 2)) * 7 * dpr, oy = -(10 + 26 * t + i * 7) * dpr;
        ctx.globalAlpha = 0.5 * (1 - t) * (1 - i * 0.2);
        ctx.fillStyle = 'rgba(70,70,74,1)';
        ctx.beginPath(); ctx.arc(x + ox, y + oy, (4 + 9 * t + i * 2) * dpr, 0, TAU); ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
  }
  function redraw() { resize(); clear(); drawTrails(); }
  // Laser-Modus: der Strahl läuft auch ohne Flugzeuge und ohne eingeschaltete Luftverkehr-Ebene (bei reduzierter Bewegung nie)
  const active = () => (laser || (enabled && planes.length > 0)) && !document.hidden && !reducedMotion;

  function frame(now) {
    raf = 0;
    if (!active() && !pings.length) { redraw(); return; }
    resize();
    const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;
    const prev = theta;
    if (active()) theta = (theta + (TAU / PERIOD_S) * dt) % TAU;
    const c = map.project([center.lon, center.lat]);
    const cx = c.x * dpr, cy = c.y * dpr;
    // Strahl und Verlauf reichen immer bis zum Bildschirmrand: Radius = Abstand zur am weitesten entfernten Ecke der Zeichenfläche
    const r = Math.max(Math.hypot(cx, cy), Math.hypot(canvas.width - cx, cy), Math.hypot(cx, canvas.height - cy), Math.hypot(canvas.width - cx, canvas.height - cy)) + 2;

    clear();
    drawTrails();
    if (active()) {
      // Ping, sobald der Strahl den Peilwinkel eines Flugzeugs (von Irrel aus, im Uhrzeigersinn ab Norden) erreicht
      for (const p of planes) {
        const q = map.project([p.lng, p.lat]);
        const a = (Math.atan2(q.x - c.x, -(q.y - c.y)) + TAU) % TAU;
        const crossed = prev <= theta ? a > prev && a <= theta : a > prev || a <= theta; // Umlauf über Norden
        if (crossed && dt > 0) {
          pings.push({ lng: p.lng, lat: p.lat, t0: now, mil: p.mil, zap: laser, seed: Math.random() * TAU });
          onPing?.({ mil: p.mil, zap: laser, pan: Math.max(-1, Math.min(1, (q.x / (canvas.width / dpr)) * 2 - 1)) });
        }
      }
      const ang = theta - Math.PI / 2; // Canvas: 0 = Osten, im Uhrzeigersinn
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, canvas.width, canvas.height); ctx.clip();
      if (laser) {
        // Laser: schmale Glut hinter dem Strahl, Strahl als weißer Kern mit rotem Schein
        if (ctx.createConicGradient) {
          const glow = (16 * Math.PI) / 180, g = ctx.createConicGradient(ang - glow, cx, cy), f = glow / TAU;
          for (let i = 0; i <= 8; i++) { const k = i / 8; g.addColorStop(f * k, `rgba(255,60,30,${(0.26 * Math.pow(k, 2.4)).toFixed(3)})`); }
          g.addColorStop(Math.min(1, f + 0.001), 'rgba(255,60,30,0)');
          g.addColorStop(1, 'rgba(255,60,30,0)');
          ctx.fillStyle = g; ctx.fillRect(0, 0, canvas.width, canvas.height);
        }
        const ex = cx + r * Math.cos(ang), ey = cy + r * Math.sin(ang);
        ctx.lineCap = 'round';
        ctx.shadowColor = 'rgba(255,50,20,0.95)'; ctx.shadowBlur = 16 * dpr;
        ctx.strokeStyle = 'rgba(255,64,40,0.95)'; ctx.lineWidth = 3.2 * dpr;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(ex, ey); ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = 'rgba(255,244,236,0.95)'; ctx.lineWidth = 1.1 * dpr;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(ex, ey); ctx.stroke();
      } else {
        if (ctx.createConicGradient) {
          // Verlauf über fast den ganzen Umlauf: hell am Strahl, hinten auslaufend; Fläche = ganzer Kreis
          const g = ctx.createConicGradient(ang - TRAIL, cx, cy);
          const f = TRAIL / TAU;
          for (let i = 0; i <= 12; i++) {
            const k = i / 12;                       // 0 = Schwanzende, 1 = Strahl
            g.addColorStop(f * k, `rgba(34,197,94,${(0.30 * Math.pow(k, 2.2)).toFixed(3)})`);
          }
          g.addColorStop(Math.min(1, f + 0.001), 'rgba(34,197,94,0)');
          g.addColorStop(1, 'rgba(34,197,94,0)');
          ctx.fillStyle = g; ctx.fillRect(0, 0, canvas.width, canvas.height);
        }
        ctx.strokeStyle = 'rgba(34,197,94,0.85)'; ctx.lineWidth = 1.5 * dpr;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + r * Math.cos(ang), cy + r * Math.sin(ang)); ctx.stroke();
      }
      ctx.restore();
    }
    pings = pings.filter((p) => (now - p.t0) / 1000 < (p.zap ? ZAP_S : PING_S));
    for (const p of pings) {
      const q = map.project([p.lng, p.lat]);
      const x = q.x * dpr, y = q.y * dpr;
      if (p.zap) { drawZap(x, y, (now - p.t0) / 1000 / ZAP_S, p.seed); continue; }
      const k = (now - p.t0) / 1000 / PING_S;
      const col = p.mil ? mil : PING_ORANGE;
      // kurzer Lichtblitz am Flugzeug
      if (k < 0.35) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, 26 * dpr);
        g.addColorStop(0, p.mil ? 'rgba(142,68,173,0.75)' : `rgba(${PING_ORANGE_RGB},0.75)`);
        g.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.globalAlpha = 1 - k / 0.35; ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, 26 * dpr, 0, TAU); ctx.fill();
      }
      // drei Ringe nacheinander, je mit hellem Rand, damit sie auf Relief und Straßen lesbar bleiben
      for (let i = 0; i < 3; i++) {
        const kk = k - i * 0.16;
        if (kk <= 0) continue;
        const rr = (6 + (PING_MAX_PX - 6) * kk) * dpr;
        ctx.globalAlpha = Math.pow(1 - kk, 1.3) * 0.95;
        ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 5.5 * dpr;
        ctx.beginPath(); ctx.arc(x, y, rr, 0, TAU); ctx.stroke();
        ctx.strokeStyle = col; ctx.lineWidth = 3 * dpr;
        ctx.beginPath(); ctx.arc(x, y, rr, 0, TAU); ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    raf = requestAnimationFrame(frame);
  }

  function sync() {
    if ((active() || pings.length) && !raf) { last = 0; raf = requestAnimationFrame(frame); }
    else if (!active() && !pings.length && !raf) redraw();
  }
  document.addEventListener('visibilitychange', sync);
  map.on('resize', () => { resize(); if (!raf) redraw(); });
  map.on('move', () => { if (!raf && tracks.size) redraw(); });

  return {
    /** Laser-Modus an/aus: roter Strahl, läuft auch ohne Flugzeuge. */
    setLaser(on) { laser = !!on; if (!laser) pings = []; sync(); if (!raf) redraw(); },
    /** Aktueller Strahlwinkel (Bogenmaß, im Uhrzeigersinn ab Norden) oder null, solange der Strahl steht. */
    beam() { return active() ? { theta } : null; },
    /** Ebene an/aus und aktuelle Flugzeuge ([{id, lng, lat, mil}]); ohne Flugzeuge steht der Sweep still. */
    update(on, list) {
      enabled = on; planes = on ? list : [];
      if (!on || !list.length) pings = [];
      if (!on) tracks.clear();
      const seen = new Set();
      for (const p of planes) {
        seen.add(p.id);
        const t = tracks.get(p.id) ?? [];
        const l = t[t.length - 1];
        if (!l || Math.abs(l[0] - p.lng) + Math.abs(l[1] - p.lat) >= TRACK_MIN_STEP_DEG) t.push([p.lng, p.lat]);
        if (t.length > TRACK_MAX_POINTS) t.splice(0, t.length - TRACK_MAX_POINTS);
        tracks.set(p.id, t);
      }
      for (const id of tracks.keys()) if (!seen.has(id)) tracks.delete(id); // abgelaufene Flugzeuge: Bahn weg
      sync();
    },
  };
}
