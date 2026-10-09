// Gemeinsame Helfer. Externe Texte gehen ausschließlich über textContent in die Seite.
export const $ = (sel, root = document) => root.querySelector(sel);

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export async function getJSON(path) {
  const r = await fetch(path, { cache: 'no-cache', headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

const TZ = 'Europe/Berlin';
const fDT = new Intl.DateTimeFormat('de-DE', { timeZone: TZ, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const fT = new Intl.DateTimeFormat('de-DE', { timeZone: TZ, hour: '2-digit', minute: '2-digit' });
const fD = new Intl.DateTimeFormat('de-DE', { timeZone: TZ, weekday: 'short', hour: '2-digit' });
export const fmtDateTime = (iso) => (iso ? fDT.format(new Date(iso)) : '–');
export const fmtTime = (iso) => (iso ? fT.format(new Date(iso)) : '–');
export const fmtHour = (iso) => fD.format(new Date(iso));

// Alter gegen die Systemzeit des Betrachters, nicht gegen einen mitgelieferten Wert
export function ageText(iso) {
  if (!iso) return 'unbekannt';
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 90) return 'gerade eben';
  const m = Math.round(s / 60);
  if (m < 90) return `vor ${m} Min.`;
  const hh = Math.round(m / 60);
  if (hh < 48) return `vor ${hh} Std.`;
  return `vor ${Math.round(hh / 24)} Tagen`;
}

// <time>-Element, dessen Alterstext alle 30 s neu berechnet wird
export function ageEl(iso, prefix = '') {
  const t = h('time', { datetime: iso || '', 'data-age': iso || '' }, prefix + ageText(iso));
  t.dataset.prefix = prefix;
  return t;
}
export function tickAges() {
  for (const t of document.querySelectorAll('time[data-age]')) {
    t.textContent = (t.dataset.prefix || '') + ageText(t.dataset.age);
  }
}

export const SEV = {
  critical: { label: 'Kritisch', rank: 3 },
  warning: { label: 'Warnung', rank: 2 },
  notice: { label: 'Hinweis', rank: 1 },
  info: { label: 'Info', rank: 0 },
};
export const TYPE_LABEL = {
  traffic: 'Verkehr', congestion: 'Verkehrslage', warning: 'Bevölkerungswarnung', weather: 'Wetterwarnung', flood: 'Hochwasser',
  air: 'Luft', radiation: 'Strahlung', earthquake: 'Erdbeben', fire: 'Brandverdacht', transit: 'ÖPNV', news: 'Meldung', social_signal: 'Themenradar', aircraft: 'Luftverkehr',
};
export const STATUS_LABEL = {
  ok: 'aktuell', degraded: 'eingeschränkt', stale: 'veraltet', down: 'nicht erreichbar',
  pending: 'wartet auf ersten Abruf', disabled: 'abgeschaltet',
};

export const sevBadge = (sev) => h('span', { class: `badge sev-${sev}` }, SEV[sev]?.label ?? sev);
export const statusBadge = (st) => h('span', { class: `badge st-${st}` }, STATUS_LABEL[st] ?? st);

// Nur http(s)-Links aus Daten zulassen
export function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch { return null; }
}
export function link(href, text) {
  const u = safeUrl(href);
  return u ? h('a', { href: u, rel: 'noopener noreferrer', target: '_blank' }, text) : h('span', {}, text);
}

// Dunkel nur auf Wunsch (Design System v5.1). Keine Speicherung: kein Cookie, kein Storage.
export function initTheme(btn) {
  const root = document.documentElement;
  const sync = () => btn.setAttribute('aria-pressed', root.dataset.ansicht === 'dunkel' ? 'true' : 'false');
  btn.addEventListener('click', () => {
    if (root.dataset.ansicht === 'dunkel') delete root.dataset.ansicht; else root.dataset.ansicht = 'dunkel';
    sync();
    document.dispatchEvent(new CustomEvent('ansicht'));
  });
  sync();
}

// oklch() & Co. → rgb(): MapLibre versteht nur klassische Farbschreibweisen
const cv = document.createElement('canvas'); cv.width = cv.height = 1;
const cx = cv.getContext('2d', { willReadFrequently: true });
export function cssColor(varName) {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  const probe = h('span'); probe.style.color = raw; document.body.append(probe);
  const resolved = getComputedStyle(probe).color; probe.remove();
  cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = resolved; cx.fillRect(0, 0, 1, 1);
  const [r, g, b] = cx.getImageData(0, 0, 1, 1).data;
  return `rgb(${r},${g},${b})`;
}

export function sparkline(points, { w = 200, h: hh = 34 } = {}) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${hh}`); svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('role', 'img');
  if (points.length < 2) return svg;
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const xy = points.map((p, i) => [(i / (points.length - 1)) * w, hh - 3 - ((p.value - min) / span) * (hh - 6)]);
  const d = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const area = document.createElementNS(NS, 'path'); area.setAttribute('d', `${d} L${w} ${hh} L0 ${hh} Z`); area.setAttribute('class', 'spark-area');
  const line = document.createElementNS(NS, 'path'); line.setAttribute('d', d); line.setAttribute('class', 'spark');
  svg.append(area, line);
  return svg;
}
