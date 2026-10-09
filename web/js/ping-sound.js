// Ton für den Radar-Ping: kurzer Sinuston aus dem Browser selbst (Web Audio), keine Audiodatei, kein Abruf bei Dritten.
// Standardmäßig aus; wird nur nach einem Klick auf „Ton (Ping, Laser)“ angelegt (Browser verlangen eine Nutzergeste).
// Laser-Modus: Treffer auf ein Flugzeug = kurzes elektrisches Zappen (zap), verdampfender Regen = leises Zischen (sizzle). Ebenfalls synthetisch.
// Zivil klingt hoch und kurz, Militär tiefer und etwas länger. Links/rechts folgt der Lage des Flugzeugs auf der Karte.
let ctx = null;
let master = null;   // alle Töne laufen über diesen Ausgang (Lautstärke + Begrenzer gegen Übersteuern)
let lastAt = 0;

export function enableSound(on) {
  if (on && !ctx) {
    const AC = globalThis.AudioContext ?? globalThis.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -14; limiter.knee.value = 10; limiter.ratio.value = 10; limiter.attack.value = 0.003; limiter.release.value = 0.2;
    master = ctx.createGain(); master.gain.value = 0.85;
    master.connect(limiter); limiter.connect(ctx.destination);
  }
  if (!on) silence();
  if (ctx) (on ? ctx.resume() : ctx.suspend()).catch(() => {});
  return Boolean(ctx);
}

export function ping({ mil = false, pan = 0 } = {}) {
  if (!ctx || ctx.state !== 'running') return;
  const t = ctx.currentTime;
  if (t - lastAt < 0.12) return; // mehrere Flugzeuge im selben Moment nicht zu einem Knall verschmelzen lassen
  lastAt = t;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  const f0 = mil ? 660 : 1320, len = mil ? 0.65 : 0.45;
  osc.type = 'sine';
  osc.frequency.setValueAtTime(f0, t);
  osc.frequency.exponentialRampToValueAtTime(f0 * 0.985, t + len); // leicht absinkend, wie ein Sonar-Ping
  gain.gain.setValueAtTime(0.0001, t);
  gain.gain.exponentialRampToValueAtTime(0.16, t + 0.012);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + len);
  let out = gain;
  if (ctx.createStereoPanner) {
    const p = ctx.createStereoPanner();
    p.pan.value = Math.max(-1, Math.min(1, pan)) * 0.8;
    gain.connect(p); out = p;
  }
  osc.connect(gain); out.connect(master);
  osc.start(t); osc.stop(t + len + 0.05);
}

let noise = null;
function noiseBuffer() {
  if (!noise) {
    noise = ctx.createBuffer(1, Math.floor(ctx.sampleRate * 1.2), ctx.sampleRate);
    const d = noise.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }
  return noise;
}

/** Laser trifft ein Flugzeug: Sägezahn rauscht in ~0,2 s von hoch nach tief, darunter ein Knistern aus gefiltertem Rauschen. */
export function zap({ pan = 0 } = {}) {
  if (!ctx || ctx.state !== 'running') return;
  const t = ctx.currentTime;
  if (t - lastAt < 0.08) return;
  lastAt = t;
  const out = ctx.createGain();
  out.gain.value = 1;
  let dest = out;
  if (ctx.createStereoPanner) { const p = ctx.createStereoPanner(); p.pan.value = Math.max(-1, Math.min(1, pan)) * 0.8; out.connect(p); dest = p; }
  dest.connect(master);
  const osc = ctx.createOscillator(), g = ctx.createGain();
  osc.type = 'sawtooth';
  osc.frequency.setValueAtTime(2600, t);
  osc.frequency.exponentialRampToValueAtTime(90, t + 0.22);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.11, t + 0.006);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.24);
  osc.connect(g); g.connect(out);
  osc.start(t); osc.stop(t + 0.28);
  const n = ctx.createBufferSource(), hp = ctx.createBiquadFilter(), ng = ctx.createGain();
  n.buffer = noiseBuffer(); hp.type = 'highpass'; hp.frequency.value = 3000;
  ng.gain.setValueAtTime(0.0001, t);
  ng.gain.exponentialRampToValueAtTime(0.09, t + 0.004);
  ng.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
  n.connect(hp); hp.connect(ng); ng.connect(out);
  n.start(t, Math.random() * 0.8, 0.2);
}

// Zischen: EINE durchgehende Rauschstimme, deren Pegel bei jedem Treffer angehoben wird und von selbst wieder auf null fällt
// (kein Aneinanderreihen einzelner Stöße: das klang verzerrt und hörte nicht auf). Ohne neue Treffer ist nach ~0,4 s Stille,
// nach 1,5 s wird die Stimme abgebaut.
let hiss = null;
let hissTimer = 0;
function killHiss() {
  clearTimeout(hissTimer);
  if (!hiss) return;
  try { hiss.src.stop(); hiss.src.disconnect(); hiss.bp.disconnect(); hiss.g.disconnect(); } catch { /* schon beendet */ }
  hiss = null;
}

/** Regen verdampft: `count` = Treffer des Lasers in diesem Bild; mehr Treffer = etwas lauter. */
export function sizzle(count = 1) {
  if (!ctx || ctx.state !== 'running' || count < 1) return;
  const t = ctx.currentTime;
  if (!hiss) {
    const src = ctx.createBufferSource(), bp = ctx.createBiquadFilter(), g = ctx.createGain();
    src.buffer = noiseBuffer(); src.loop = true;
    bp.type = 'bandpass'; bp.frequency.value = 5600; bp.Q.value = 0.7;
    g.gain.value = 0;
    src.connect(bp); bp.connect(g); g.connect(master);
    src.start(t, Math.random() * 0.8);
    hiss = { src, bp, g };
  }
  const level = Math.min(0.045, 0.008 + count * 0.003);
  hiss.g.gain.cancelScheduledValues(t);
  hiss.g.gain.setValueAtTime(hiss.g.gain.value, t);
  hiss.g.gain.setTargetAtTime(level, t, 0.025);
  hiss.g.gain.setTargetAtTime(0, t + 0.12, 0.09);
  hiss.bp.frequency.setTargetAtTime(4800 + Math.random() * 2400, t, 0.06);
  clearTimeout(hissTimer);
  hissTimer = setTimeout(killHiss, 1500);
}

/** Sofort still: Zischen abbauen, bereits geplante Zapper ausblenden. Aufruf beim Ausschalten von Laser oder Ton. */
export function silence() {
  killHiss();
  if (!ctx || !master) return;
  const t = ctx.currentTime;
  master.gain.cancelScheduledValues(t);
  master.gain.setValueAtTime(0, t);
  master.gain.setValueAtTime(0.85, t + 0.4);   // kurze Stummschaltung, danach wieder bereit
}
