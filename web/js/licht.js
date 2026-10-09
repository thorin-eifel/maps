// Lichtquelle am Zeiger: Das Gelände wird von einem Punktlicht über dem Mauszeiger (bzw. Tippunkt, sonst Bildmitte) beleuchtet.
// Hänge zum Licht hin werden hell, abgewandte dunkel, hinter Kämmen fallen Schatten (Strahlverfolgung über das Höhenmodell, weiche Ränder).
// Rechnet vollständig im Fragment-Shader (WebGL2, GPU) aus einem Höhenmosaik der sichtbaren Terrarium-Kacheln; keine Abrufe nach außen.
// Reiner Rechenteil (tilePlan) ist ohne Browser testbar. Gilt nur bei Nordausrichtung ohne Neigung (so ist die Karte eingestellt).

import { paintFlow, paintMaterial, flowSegments, MATERIAL_KINDS } from './licht-felder.js';
import { waveSpec } from './fluss.js';

const MAX_Z = 12, TILE = 256, MAX_TILES = 48, MARGIN = 0.25;
const WORLD_M = 40075016.686;
export const DEFAULTS = { heightPx: 80, radiusPx: 260 };

/** Mercator-Koordinate 0..1 (x nach Osten, y nach Süden). */
export const merc = (lng, lat) => [(lng + 180) / 360, 0.5 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / (2 * Math.PI)];

/** Welche Kacheln das Mosaik braucht: Sichtfeld (Mercator) plus Rand, Zoom so wählen, dass es höchstens MAX_TILES sind. */
export function tilePlan(x0, y0, x1, y1, mapZoom) {
  let z = Math.max(6, Math.min(MAX_Z, Math.ceil(mapZoom - 0.5)));
  const w = x1 - x0, h = y1 - y0;
  for (;; z--) {
    const n = 2 ** z;
    const tx0 = Math.floor((x0 - w * MARGIN) * n), tx1 = Math.floor((x1 + w * MARGIN) * n);
    const ty0 = Math.max(0, Math.floor((y0 - h * MARGIN) * n)), ty1 = Math.min(n - 1, Math.floor((y1 + h * MARGIN) * n));
    const nx = tx1 - tx0 + 1, ny = ty1 - ty0 + 1;
    if (nx * ny <= MAX_TILES || z <= 6) return { z, tx0, ty0, nx, ny };
  }
}

const VS = `#version 300 es
in vec2 a; out vec2 v_ndc;
void main(){ v_ndc = a; gl_Position = vec4(a, 0.0, 1.0); }`;

const COMMON = `#version 300 es
precision highp float; precision highp int; precision highp sampler2D;
in vec2 v_ndc; out vec4 o;
uniform sampler2D u_h;
uniform sampler2D u_fb;         // Bild bis einschließlich Wasserfläche (nur Wasserpass)
uniform sampler2D u_flow;       // Strömung: RG Richtung, B Tempo, A belegt
uniform sampler2D u_mat;        // Stoffe: R Rückstrahlung, G Streuung, B Glanz, A belegt
uniform vec4 u_fw;              // Fenster der Felder (Mercator)
uniform vec2 u_wind;            // Wellenzug auf Stillwasser in Bildpunkten je Sekunde
uniform float u_flowpx;         // Wellentempo bei Tempo 1 (Bildpunkte je Sekunde)
uniform vec2 u_tl, u_br;        // Mercator der Bildecken
uniform vec4 u_mos;             // Ursprung xy, Größe zw des Mosaiks (Mercator)
uniform vec2 u_tex;             // Mosaik in Texeln
uniform float u_s;              // Meter je Mercator-Einheit
uniform vec2 u_light;           // Mercator des Lichts
uniform float u_lh, u_rad;      // Lichthöhe über Grund, Strahlungsradius (m)
uniform float u_amb, u_glow;    // Dunkelheit fern vom Licht, Leuchtkraft
uniform vec3 u_shadow, u_warm, u_water;
uniform float u_t, u_mpp;       // Zeit (s), Meter je Bildpunkt

float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

float hAt(vec2 m){
  vec2 p = (m - u_mos.xy) / u_mos.zw * u_tex - 0.5;
  if (p.x < -1.0 || p.y < -1.0 || p.x > u_tex.x || p.y > u_tex.y) return -99999.0;
  ivec2 i = ivec2(floor(p)); vec2 f = fract(p); ivec2 mx = ivec2(u_tex) - 1;
  float a = texelFetch(u_h, clamp(i, ivec2(0), mx), 0).r;
  float b = texelFetch(u_h, clamp(i + ivec2(1,0), ivec2(0), mx), 0).r;
  float c = texelFetch(u_h, clamp(i + ivec2(0,1), ivec2(0), mx), 0).r;
  float d = texelFetch(u_h, clamp(i + ivec2(1,1), ivec2(0), mx), 0).r;
  if (a < -9000.0 || b < -9000.0 || c < -9000.0 || d < -9000.0) return -99999.0;
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

// Schatten: Strahl vom Punkt zum Licht, kleinster Abstand zum Gelände bestimmt die Sichtbarkeit (weiche Kante)
float shadowVis(vec2 m, float h, float lz, float dist){
  float vis = 1.0;
  const int STEPS = 48;
  for (int k = 1; k <= STEPS; k++) {
    float t = pow(float(k) / float(STEPS), 1.6);
    float th = hAt(mix(m, u_light, t));
    if (th < -9000.0) continue;
    float dd = (h + lz * t) - th;
    vis = min(vis, clamp(dd / (0.05 * t * dist + 3.0) + 0.15, 0.0, 1.0));
    if (vis < 0.01) break;
  }
  return vis;
}
`;

const FS = COMMON + `
void main(){
  vec2 m = mix(u_tl, u_br, vec2(v_ndc.x, -v_ndc.y) * 0.5 + 0.5);
  float h = hAt(m);
  if (h < -9000.0) discard;
  float tm = u_mos.z / u_tex.x * u_s;           // Meter je Texel
  // Sobel über 1,5 Texel Abstand: die Terrarium-Höhen sind auf ganze Meter gerundet, einfache Differenzen zeigen sonst Streifen
  float d = 1.5; float e = d * tm / u_s;
  float a0 = hAt(m + vec2(-e,-e)), a1 = hAt(m + vec2(0.,-e)), a2 = hAt(m + vec2(e,-e));
  float b0 = hAt(m + vec2(-e,0.)),                            b2 = hAt(m + vec2(e,0.));
  float c0 = hAt(m + vec2(-e,e)),  c1 = hAt(m + vec2(0.,e)),  c2 = hAt(m + vec2(e,e));
  float k8 = 8.0 * d * tm;
  float dE = ((a2 + 2.0*b2 + c2) - (a0 + 2.0*b0 + c0)) / k8;
  float dN = -((c0 + 2.0*c1 + c2) - (a0 + 2.0*a1 + a2)) / k8;   // y zeigt nach Süden
  vec3 N = normalize(vec3(-dE, -dN, 1.0));
  float hl = hAt(u_light); if (hl < -9000.0) hl = h;
  vec3 L = vec3((u_light.x - m.x) * u_s, -(u_light.y - m.y) * u_s, hl + u_lh - h);
  float dist = length(L); vec3 Ld = L / dist;
  float flat0 = max(Ld.z, 0.02);
  float rel = clamp(dot(N, Ld) / flat0, 0.0, 2.0);   // 1 = so hell wie ebener Boden, 2 = dem Licht zugewandt
  float shade = clamp(0.5 * rel, 0.0, 1.0);
  float vis = shadowVis(m, h, L.z, dist);
  float near = exp(-pow(dist / u_rad, 2.0));
  // Stoff unter dem Punkt: Wald schluckt (wenig Rückstrahlung) und streut (flaches Relief, weiche Schatten, Kronenrauschen),
  // Feld und Fels strahlen hell zurück, Feuchtgebiet und Fels glänzen etwas
  vec2 fuv = (m - u_fw.xy) / u_fw.zw;
  vec4 mt = (fuv.x >= 0.0 && fuv.y >= 0.0 && fuv.x <= 1.0 && fuv.y <= 1.0) ? texture(u_mat, fuv) : vec4(0.0);
  vec3 mp = mt.a > 0.5 ? mt.rgb : vec3(0.6, 0.5, 0.04);
  shade = mix(shade, 0.5, mp.y * 0.55);
  vis = mix(vis, 1.0, mp.y * 0.30);
  float lit = mix(shade, 1.0, near) * vis;
  lit *= clamp(0.55 + 0.9 * mp.x, 0.5, 1.25);
  lit *= 1.0 + (hash(floor(gl_FragCoord.xy / 3.0)) - 0.5) * 0.30 * smoothstep(0.85, 1.0, mp.y);
  lit = clamp(lit, 0.0, 1.0);
  float dark = u_amb * (1.0 - lit);
  float glow = u_glow * near * vis * clamp(rel, 0.0, 1.2) * 0.8 * mix(0.5, 1.15, mp.x);
  vec3 Hv = normalize(Ld + vec3(0.0, 0.0, 1.0));
  float spec = pow(max(dot(N, Hv), 0.0), 24.0) * mp.z * exp(-pow(dist / (u_rad * 1.8), 2.0)) * vis * u_glow * 1.4;
  o = vec4(u_shadow * dark + u_warm * (glow + spec), dark);
}`;

// Wasserpass: liegt über der Wasserfläche. Wasser wird an seiner Farbe im bisherigen Bild erkannt (Kopie des Bildes),
// dann wie das Land abgedunkelt und mit Glitzern aus bewegten Wellenneigungen (Blinn-Phong, Blick senkrecht von oben) versehen.
const FSW = COMMON + `
vec2 waves(vec2 x, float t){
  vec2 s = vec2(0.0);
  s += 0.11 * cos(dot(x, vec2( 0.90, 0.30)) + 1.7 * t)        * vec2( 0.95, 0.31);
  s += 0.10 * cos(dot(x, vec2(-0.40, 0.70)) - 1.3 * t + 1.0)  * vec2(-0.50, 0.87);
  s += 0.09 * cos(dot(x, vec2( 0.55,-0.45)) + 2.1 * t + 2.0)  * vec2( 0.77,-0.64);
  s += 0.08 * cos(dot(x, vec2(-0.25,-0.95)) - 1.9 * t + 4.0)  * vec2(-0.25,-0.97);
  s += 0.07 * cos(dot(x, vec2( 1.10, 0.10)) + 2.6 * t + 5.0)  * vec2( 1.0, 0.09);
  return s * 3.2;
}
void main(){
  vec3 dst = texelFetch(u_fb, ivec2(gl_FragCoord.xy), 0).rgb;
  float mask = 1.0 - smoothstep(0.035, 0.10, length(dst - u_water));
  if (mask <= 0.0) discard;
  vec2 m = mix(u_tl, u_br, vec2(v_ndc.x, -v_ndc.y) * 0.5 + 0.5);
  float h = hAt(m); float hl = hAt(u_light);
  if (h < -9000.0) h = (hl < -9000.0) ? 0.0 : hl;
  if (hl < -9000.0) hl = h;
  vec3 L = vec3((u_light.x - m.x) * u_s, -(u_light.y - m.y) * u_s, hl + u_lh - h);
  float dist = length(L); vec3 Ld = L / dist;
  float vis = shadowVis(m, h, L.z, dist);
  float near = exp(-pow(dist / u_rad, 2.0));
  float lit = mix(0.5, 1.0, near) * vis;
  float dark = u_amb * (1.0 - lit);
  // Bewegung: auf Flüssen mit der Strömung (Tempo je Klasse, gestaute Flüsse kaum), auf Stillwasser mit dem Wind
  vec2 fuv = (m - u_fw.xy) / u_fw.zw;
  vec4 fl = (fuv.x >= 0.0 && fuv.y >= 0.0 && fuv.x <= 1.0 && fuv.y <= 1.0) ? texture(u_flow, fuv) : vec4(0.0);
  bool river = fl.a > 0.5;
  vec2 vel = river ? normalize((fl.rg * 255.0 - 128.0) / 127.0 + 1e-4) * fl.b * u_flowpx : u_wind;
  vec2 px = m * u_s / u_mpp;
  vec2 sl = waves((px - vel * u_t) * 0.35, u_t * (river ? 0.25 : 1.0));   // Wellen in Bildpunkten, damit sie bei jedem Zoom lesbar bleiben
  vec3 n = normalize(vec3(-sl, 1.0));
  vec3 H = normalize(Ld + vec3(0.0, 0.0, 1.0));
  float spec = pow(max(dot(n, H), 0.0), 60.0);
  float sheen = pow(max(H.z, 0.0), 14.0);
  float reach = exp(-pow(dist / (u_rad * 2.4), 2.0));
  float g = (spec * 10.0 + sheen * 0.7) * reach * vis;
  o = vec4((u_shadow * dark + u_warm * g * u_glow * 1.4) * mask, dark * mask);
}`;

function compile(gl, type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'Shader');
  return s;
}

const UNIFORMS = ['u_h', 'u_fb', 'u_flow', 'u_mat', 'u_fw', 'u_wind', 'u_flowpx', 'u_tl', 'u_br', 'u_mos', 'u_tex', 'u_s', 'u_light', 'u_lh', 'u_rad', 'u_amb', 'u_glow', 'u_shadow', 'u_warm', 'u_water', 'u_t', 'u_mpp'];

function program(gl, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, VS)); gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || 'Link');
  const loc = {};
  for (const n of UNIFORMS) loc[n] = gl.getUniformLocation(p, n);
  return { p, loc };
}

/** '#rrggbb' oder '#rgb' zu [r,g,b] 0..1; sonst Rückfall auf das helle Wasserblau. */
export function hexRgb(c) {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(c).trim());
  if (!m) return [0x8f / 255, 0xc0 / 255, 0xe8 / 255];
  const h = m[1].length === 3 ? [...m[1]].map((x) => x + x).join('') : m[1];
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}

/** Lichtebenen: Gelände (unter dem Wasser) und Wasserglitzern (über dem Wasser). `demTile(z,x,y)` liefert {width,height,data} (Meter) oder wirft. */
export function createLight(map, { demTile, onError = () => {}, wind = () => null, reduce = false }) {
  const st = {
    on: false, dark: false, med: false, heightPx: DEFAULTS.heightPx, water: [0x8f / 255, 0xc0 / 255, 0xe8 / 255],
    light: null,               // [mx, my]
    mosaic: null, token: 0, gl: null, tex: null, fbTex: null, flowTex: null, matTex: null, fbW: 0, fbH: 0, terrain: null, wat: null, vao: null,
    fw: [-10, -10, 1, 1], hasWater: false, windPx: [0, 0], fields: { segs: 0, polys: 0, ms: 0 }, lastFrame: 0, timer: 0, fieldsTimer: 0,
    stats: { tiles: 0, z: 0, ms: 0 }, err: '', lastMove: 0, animUntil: 0,
  };

  const fail = (err) => { st.err = String(err.message || err); onError(st.err); };
  const ensureGl = (gl) => {
    if (st.vao && st.gl === gl) return;
    st.gl = gl;
    st.vao = gl.createVertexArray(); gl.bindVertexArray(st.vao);
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.bindVertexArray(null); st.attrib = b;
    st.tex = gl.createTexture(); st.fbTex = gl.createTexture(); st.flowTex = gl.createTexture(); st.matTex = gl.createTexture(); st.mosaic = null; st.fbW = st.fbH = 0;
    for (const t of [st.flowTex, st.matTex]) { gl.bindTexture(gl.TEXTURE_2D, t); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4)); }
  };
  const bindQuad = (gl, pr) => {
    gl.bindVertexArray(st.vao); gl.bindBuffer(gl.ARRAY_BUFFER, st.attrib);
    const a = gl.getAttribLocation(pr.p, 'a'); gl.enableVertexAttribArray(a); gl.vertexAttribPointer(a, 2, gl.FLOAT, false, 0, 0);
  };
  const common = (gl, pr, now) => {
    const c = map.getContainer(), w = c.clientWidth, h = c.clientHeight;
    const tl = map.unproject([0, 0]), br = map.unproject([w, h]);
    const [x0, y0] = merc(tl.lng, tl.lat), [x1, y1] = merc(br.lng, br.lat);
    const ctr = map.getCenter(), s = WORLD_M * Math.cos((ctr.lat * Math.PI) / 180);
    const L = st.light ?? merc(ctr.lng, ctr.lat);
    const mpp = s / (512 * 2 ** map.getZoom());
    const k = st.dark ? { amb: 0.6, glow: 0.55, sh: [0, 0, 0], warm: [1, 0.85, 0.55] } : st.med ? { amb: 0.55, glow: 0.35, sh: [0.14, 0.08, 0.02], warm: [1, 0.9, 0.6] } : { amb: 0.58, glow: 0.4, sh: [0.05, 0.08, 0.2], warm: [1, 0.92, 0.65] };
    const u = pr.loc, m = st.mosaic;
    gl.useProgram(pr.p);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.STENCIL_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, st.tex); gl.uniform1i(u.u_h, 0);
    gl.uniform2f(u.u_tl, x0, y0); gl.uniform2f(u.u_br, x1, y1);
    gl.uniform4f(u.u_mos, m.x, m.y, m.w, m.h); gl.uniform2f(u.u_tex, m.tw, m.th); gl.uniform1f(u.u_s, s);
    gl.uniform2f(u.u_light, L[0], L[1]); gl.uniform1f(u.u_lh, st.heightPx * mpp); gl.uniform1f(u.u_rad, DEFAULTS.radiusPx * mpp);
    gl.uniform1f(u.u_amb, k.amb); gl.uniform1f(u.u_glow, k.glow); gl.uniform3f(u.u_shadow, ...k.sh); gl.uniform3f(u.u_warm, ...k.warm);
    gl.uniform3f(u.u_water, ...st.water); gl.uniform1f(u.u_t, (now / 1000) % 600); gl.uniform1f(u.u_mpp, mpp);
    gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, st.flowTex); gl.uniform1i(u.u_flow, 2);
    gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, st.matTex); gl.uniform1i(u.u_mat, 3);
    gl.activeTexture(gl.TEXTURE0);
    gl.uniform4f(u.u_fw, ...st.fw); gl.uniform2f(u.u_wind, ...st.windPx); gl.uniform1f(u.u_flowpx, 34);
  };

  const terrain = {
    id: 'relief-light', type: 'custom', renderingMode: '2d',
    onAdd(_m, gl) { try { ensureGl(gl); st.terrain = program(gl, FS); st.err = ''; refresh(); } catch (err) { fail(err); st.terrain = null; } },
    onRemove(_m, gl) { if (st.terrain) gl.deleteProgram(st.terrain.p); st.terrain = null; },
    render(gl) {
      if (!st.terrain || !st.mosaic || !st.on) return;
      bindQuad(gl, st.terrain); common(gl, st.terrain, performance.now());
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.bindVertexArray(null);
    },
  };

  const water = {
    id: 'relief-light-water', type: 'custom', renderingMode: '2d',
    onAdd(_m, gl) { try { ensureGl(gl); st.wat = program(gl, FSW); } catch (err) { fail(err); st.wat = null; } },
    onRemove(_m, gl) { if (st.wat) gl.deleteProgram(st.wat.p); st.wat = null; },
    render(gl) {
      if (!st.wat || !st.mosaic || !st.on) return;
      const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, st.fbTex);
      if (st.fbW !== w || st.fbH !== h) {   // Speicher nur bei Größenänderung neu anlegen
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
        for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.NEAREST], [gl.TEXTURE_MAG_FILTER, gl.NEAREST], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
        st.fbW = w; st.fbH = h;
      }
      gl.copyTexSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 0, 0, w, h);   // bisheriges Bild bis zur Wasserfläche
      const err = gl.getError();
      if (err) { if (!st.err) fail(`Bildkopie: GL-Fehler ${err}`); return; }
      bindQuad(gl, st.wat); common(gl, st.wat, performance.now());
      gl.uniform1i(st.wat.loc.u_fb, 1);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.bindVertexArray(null);
      gl.activeTexture(gl.TEXTURE0);
      // Wellen laufen mit rund 30 Bildern je Sekunde, solange Wasser im Bild ist und die Seite sichtbar ist; bei reduzierter Bewegung nur
      // während der Zeigerbewegung (plus kurzer Nachlauf)
      const now = performance.now(), moving = now < st.animUntil, cont = st.hasWater && !reduce && document.visibilityState === 'visible';
      if (moving) map.triggerRepaint();
      else if (cont && !st.timer) st.timer = setTimeout(() => { st.timer = 0; map.triggerRepaint(); }, Math.max(0, 33 - (now - st.lastFrame)));
      st.lastFrame = now;
    },
  };

  /** Höhenmosaik für das aktuelle Sichtfeld laden (asynchron, veraltete Läufe werden verworfen). */
  async function refresh() {
    if (!st.on || !st.gl || !st.terrain) return;
    const my = ++st.token, t0 = performance.now();
    const c = map.getContainer(), tl = map.unproject([0, 0]), br = map.unproject([c.clientWidth, c.clientHeight]);
    const [x0, y0] = merc(tl.lng, tl.lat), [x1, y1] = merc(br.lng, br.lat);
    const { z, tx0, ty0, nx, ny } = tilePlan(x0, y0, x1, y1, map.getZoom());
    const n = 2 ** z, jobs = [];
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) jobs.push(demTile(z, ((tx0 + i) % n + n) % n, ty0 + j).then((r) => ({ i, j, r }), () => null));
    const got = await Promise.all(jobs);
    if (my !== st.token) return;
    const ok = got.find((g) => g?.r);
    if (!ok) { st.mosaic = null; st.stats = { tiles: 0, z, ms: 0 }; return; }
    const tw = ok.r.width, th = ok.r.height, W = nx * tw, H = ny * th;
    const data = new Float32Array(W * H).fill(-99999);
    let have = 0;
    for (const g of got) {
      if (!g?.r) continue;
      have++;
      for (let y = 0; y < th; y++) data.set(g.r.data.subarray(y * tw, y * tw + tw), (g.j * th + y) * W + g.i * tw);
    }
    const gl = st.gl;
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, st.tex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, W, H, 0, gl.RED, gl.FLOAT, data);
    for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.NEAREST], [gl.TEXTURE_MAG_FILTER, gl.NEAREST], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
    st.mosaic = { x: tx0 / n, y: ty0 / n, w: nx / n, h: ny / n, tw: W, th: H };
    st.stats = { tiles: have, of: nx * ny, z, ms: Math.round(performance.now() - t0) };
    map.triggerRepaint();
  }

  const cvFlow = typeof document !== 'undefined' ? document.createElement('canvas') : null;
  const cvMat = typeof document !== 'undefined' ? document.createElement('canvas') : null;

  /** Strömungs- und Stoffbild für das Sichtfeld plus Rand neu zeichnen (aus den geladenen Kacheln der Grundkarte). */
  function rebuildFields() {
    if (!st.on || !st.gl || !map.getSource('basemap')) return;
    const t0 = performance.now(), c = map.getContainer(), vw = c.clientWidth, vh = c.clientHeight;
    const w = wind();
    const to = w ? ((((w.from ?? 0) + 180) % 360) * Math.PI) / 180 : 0, px = w ? waveSpec(w.speed).pxs : 0;
    st.windPx = [Math.sin(to) * px, -Math.cos(to) * px];
    if (map.getZoom() < 10) { st.fw = [-10, -10, 1, 1]; st.hasWater = false; return; }
    const k = 1 + 2 * MARGIN;
    const tl = map.unproject([-vw * MARGIN, -vh * MARGIN]), br = map.unproject([vw * (1 + MARGIN), vh * (1 + MARGIN)]);
    const [x0, y0] = merc(tl.lng, tl.lat), [x1, y1] = merc(br.lng, br.lat);
    const win = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    const sc = Math.min(0.75, 1400 / (vw * k), 1400 / (vh * k));
    const cw = Math.max(16, Math.ceil(vw * k * sc)), ch = Math.max(16, Math.ceil(vh * k * sc));
    const s = WORLD_M * Math.cos((map.getCenter().lat * Math.PI) / 180);
    const water = map.querySourceFeatures('basemap', { sourceLayer: 'water', filter: ['in', 'kind', 'river', 'stream', 'canal'] });
    const land = map.querySourceFeatures('basemap', { sourceLayer: 'landuse', filter: ['in', 'kind', ...MATERIAL_KINDS] });
    const segs = flowSegments(water);
    for (const [cv, paint] of [[cvFlow, (ctx) => paintFlow(ctx, cw, ch, win, segs, (win.w * s) / cw)], [cvMat, (ctx) => paintMaterial(ctx, cw, ch, win, land)]]) {
      if (cv.width !== cw) cv.width = cw;
      if (cv.height !== ch) cv.height = ch;
      paint(cv.getContext('2d', { willReadFrequently: false }));
    }
    const gl = st.gl;
    for (const [unit, tex, cv] of [[gl.TEXTURE2, st.flowTex, cvFlow], [gl.TEXTURE3, st.matTex, cvMat]]) {
      gl.activeTexture(unit); gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, cv);
      for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
    }
    gl.activeTexture(gl.TEXTURE0);
    st.fw = [win.x, win.y, win.w, win.h];
    st.hasWater = segs.length > 0 || (map.getLayer('bm-water') ? map.queryRenderedFeatures({ layers: ['bm-water'] }).length > 0 : false);
    st.fields = { segs: segs.length, polys: land.length, water: water.length, ms: Math.round(performance.now() - t0), cw, ch };
    map.triggerRepaint();
  }
  const soon = () => { clearTimeout(st.fieldsTimer); st.fieldsTimer = setTimeout(rebuildFields, 250); };
  const onSource = (e) => { if (e.sourceId === 'basemap' && e.isSourceLoaded) soon(); };

  let raf = 0;
  const onMove = (e) => {
    st.light = merc(e.lngLat.lng, e.lngLat.lat); st.animUntil = performance.now() + 1500;
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; map.triggerRepaint(); });
  };
  const onTap = (e) => { st.light = merc(e.lngLat.lng, e.lngLat.lat); st.animUntil = performance.now() + 1500; map.triggerRepaint(); };
  const onEnd = () => { refresh(); soon(); };
  const has = (id) => !!map.getLayer(id);

  return {
    layer: terrain, stats: () => ({ ...st.stats, fields: st.fields, hasWater: st.hasWater, windPx: st.windPx, err: st.err, on: st.on, terrain: has(terrain.id), water: has(water.id), light: st.light }),
    /** Ebenen neu einhängen (nach jedem Stilwechsel): Gelände unter `beforeId`, Wasserglitzern unter `beforeWater` (nach den Wasserlinien). */
    build(beforeId, beforeWater, { dark = false, med = false, waterColor } = {}) {
      st.dark = dark; st.med = med; if (waterColor) st.water = hexRgb(waterColor);
      for (const l of [terrain, water]) if (has(l.id)) map.removeLayer(l.id);
      if (!st.on) return;
      map.addLayer(terrain, has(beforeId) ? beforeId : undefined);
      map.addLayer(water, has(beforeWater) ? beforeWater : undefined);
    },
    setEnabled(on) {
      if (on === st.on) return;
      st.on = on;
      if (on) { map.on('mousemove', onMove); map.on('click', onTap); map.on('moveend', onEnd); map.on('zoomend', onEnd); map.on('sourcedata', onSource); soon(); }
      else { map.off('mousemove', onMove); map.off('click', onTap); map.off('moveend', onEnd); map.off('zoomend', onEnd); map.off('sourcedata', onSource); for (const l of [terrain, water]) if (has(l.id)) map.removeLayer(l.id); }
    },
    setHeight(px) { st.heightPx = Math.max(20, Math.min(300, px)); map.triggerRepaint(); },
    setLight(lng, lat) { st.light = merc(lng, lat); st.animUntil = performance.now() + 1500; map.triggerRepaint(); },
    refresh, rebuildFields,
  };
}
