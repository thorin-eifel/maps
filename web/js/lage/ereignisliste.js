import { SORTS, filterEvents, sortEvents } from '../eventlist.js';
import { iconFor } from '../rules.js';
import { $, TYPE_LABEL, ageEl, fmtDateTime, h, sevBadge } from '../util.js';
import { GEBIET_LEER, gebietAktiv, kreisWaehlen, kreiseListe, laenderListe, landWaehlen } from '../gebiet.js';
import { showPopup } from './popup.js';
import { gebietGeaendert } from './zellenlauf.js';
import { GROUPS, map, mapReady, state } from './zustand.js';

// ------------------------------------------------------------------ Ereignisse
// Listenansicht: Werkzeugleiste wird einmal gebaut (sonst verliert das Suchfeld alle 15 s den Fokus), nur #ev-list wird neu gefüllt.
export const EV_DEFAULT = { sort: 'prio', reverse: false, minSev: 0, type: '', maxKm: 0, q: '' };
export const evView = { ...EV_DEFAULT };
export const evActive = () => (evView.minSev ? 1 : 0) + (evView.type ? 1 : 0) + (evView.maxKm ? 1 : 0) + (evView.q.trim() ? 1 : 0);

export function syncEventTools(panel) {
  for (const b of panel.querySelectorAll('.ev-chip')) b.setAttribute('aria-pressed', String(Number(b.dataset.sev) === evView.minSev));
  const n = (evView.type ? 1 : 0) + (evView.maxKm ? 1 : 0) + (gebietAktiv(state.gebiet) ? 1 : 0);
  const more = panel.querySelector('#ev-more-n');
  if (more) { more.textContent = n ? String(n) : ''; more.hidden = !n; }
  const rev = panel.querySelector('#ev-rev');
  if (rev) { rev.setAttribute('aria-pressed', String(evView.reverse)); rev.textContent = evView.reverse ? '↑' : '↓'; }
  const reset = panel.querySelector('#ev-reset');
  if (reset) reset.hidden = !evActive() && !gebietAktiv(state.gebiet) && evView.sort === 'prio' && !evView.reverse;
}

// Land und Landkreis (nur im Zellenbetrieb, dort liefert das Startpaket die Kreisliste). Der Filter gilt für Karte, Liste, Messstellen und Warnband.
function gebietAuswahl(upd) {
  const kreise = state.start?.kreise;
  if (!state.zellen || !kreise?.length) return [];
  const opts = (list, leer, cur) => [h('option', { value: '' }, leer), ...list.map(([v, t]) => h('option', { value: v, selected: v === cur ? '' : null }, t))];
  const kreisSel = h('select', { id: 'ev-kreis', 'aria-label': 'Nach Landkreis filtern', onchange: (e) => { state.gebiet = kreisWaehlen(state.gebiet, e.target.value, kreise); landSel.value = state.gebiet.land; gebietGeaendert(); upd(); } },
    opts(kreiseListe(kreise, state.gebiet.land), 'alle Landkreise', state.gebiet.ars));
  const landSel = h('select', { id: 'ev-land', 'aria-label': 'Nach Land filtern', onchange: (e) => {
    state.gebiet = landWaehlen(state.gebiet, e.target.value, kreise);
    kreisSel.replaceChildren(...opts(kreiseListe(kreise, state.gebiet.land), 'alle Landkreise', state.gebiet.ars));
    gebietGeaendert(); upd();
  } }, opts(laenderListe(kreise), 'alle Länder', state.gebiet.land));
  return [h('label', {}, h('span', {}, 'Land'), landSel), h('label', {}, h('span', {}, 'Landkreis'), kreisSel)];
}

export function buildEventTools(panel) {
  const upd = () => { syncEventTools(panel); renderEvents(state.statuses); };
  const sel = (id, label, opts, key, num) => h('select', { id, 'aria-label': label, onchange: (e) => { evView[key] = num ? Number(e.target.value) : e.target.value; upd(); } },
    opts.map(([v, t]) => h('option', { value: String(v), selected: String(evView[key]) === String(v) ? '' : null }, t)));
  const typeOpts = [['', 'Alle Typen'], ...Object.entries(TYPE_LABEL).filter(([t]) => t !== 'aircraft').map(([t, l]) => [t, l])];
  const chips = [[0, 'Alle'], [1, 'Hinweis+'], [2, 'Warnung+'], [3, 'Kritisch']].map(([v, t]) =>
    h('button', { type: 'button', class: 'ev-chip', 'data-sev': v, 'aria-pressed': String(evView.minSev === v), onclick: () => { evView.minSev = v; upd(); } }, t));
  // Typ, Umkreis und Sortierung liegen eingeklappt hinter „Filter“; Stufe und Suche bleiben sichtbar
  const more = h('div', { class: 'ev-more', id: 'ev-more', hidden: '' },
    h('label', {}, h('span', {}, 'Typ'), sel('ev-type', 'Nach Typ filtern', typeOpts, 'type')),
    h('label', {}, h('span', {}, 'Umkreis um Irrel'), sel('ev-km', 'Nach Entfernung filtern', [[0, 'gesamt'], [10, 'bis 10 km'], [25, 'bis 25 km'], [50, 'bis 50 km']], 'maxKm', true)),
    ...gebietAuswahl(upd),
    h('label', { class: 'ev-wide' }, h('span', {}, 'Sortierung'),
      h('span', { class: 'ev-sortbox' }, sel('ev-sort', 'Sortierung', Object.entries(SORTS).map(([k, v]) => [k, v.label]), 'sort'),
        h('button', { type: 'button', id: 'ev-rev', class: 'ev-btn ev-icon', title: 'Reihenfolge umkehren', 'aria-label': 'Reihenfolge umkehren', 'aria-pressed': 'false', onclick: () => { evView.reverse = !evView.reverse; upd(); } }, '↓'))));
  const toggle = h('button', { type: 'button', class: 'ev-btn', id: 'ev-toggle', 'aria-expanded': 'false', 'aria-controls': 'ev-more', onclick: (e) => {
    const open = more.hidden; more.hidden = !open; e.currentTarget.setAttribute('aria-expanded', String(open));
  } }, 'Filter', h('span', { class: 'ev-n', id: 'ev-more-n', hidden: '' }));
  return h('div', { class: 'ev-tools', id: 'ev-tools', role: 'search', 'aria-label': 'Ereignisse suchen, filtern und sortieren' },
    h('div', { class: 'ev-row' },
      h('input', { id: 'ev-q', type: 'search', 'aria-label': 'Ereignisse durchsuchen', placeholder: 'Ereignisse suchen', autocomplete: 'off', maxlength: '60',
        oninput: (e) => { evView.q = e.target.value; upd(); } }), toggle),
    more,
    h('div', { class: 'ev-row ev-row2' }, h('div', { class: 'ev-chips', role: 'group', 'aria-label': 'Mindeststufe' }, chips),
      h('button', { type: 'button', id: 'ev-reset', class: 'ev-link', hidden: '', onclick: () => {
        Object.assign(evView, EV_DEFAULT);
        if (gebietAktiv(state.gebiet)) { state.gebiet = { ...GEBIET_LEER }; gebietGeaendert(); }
        panel.querySelector('#ev-tools')?.replaceWith(buildEventTools(panel)); syncEventTools(panel); renderEvents(state.statuses);
      } }, 'Zurücksetzen')),
    h('div', { class: 'sr-only', id: 'ev-count', 'aria-live': 'polite' }));
}

export function renderEvents(statuses) {
  const panel = $('#panel-events');
  if (!panel.querySelector('#ev-tools')) { panel.replaceChildren(buildEventTools(panel), h('div', { id: 'ev-list' })); syncEventTools(panel); }
  const box = panel.querySelector('#ev-list');
  const top = panel.scrollTop; // die Tabelle wird alle 15 s neu gebaut (Flüge); Lesestelle merken
  box.replaceChildren();
  queueMicrotask(() => { panel.scrollTop = top; });
  const types = Object.entries(GROUPS).filter(([g]) => state.layers[g]).flatMap(([, t]) => t);
  const layered = state.events.filter((f) => types.includes(f.properties.type));
  const rows = sortEvents(filterEvents(layered, evView), evView.sort, evView.reverse);
  const cnt = panel.querySelector('#ev-count');
  const countText = rows.length === layered.length ? `${rows.length} Ereignisse` : `${rows.length} von ${layered.length} Ereignissen`;
  if (cnt) cnt.textContent = countText;
  const q = panel.querySelector('#ev-q'); if (q) q.placeholder = `${countText} durchsuchen`;
  const problems = statuses.filter((s) => ['down', 'stale', 'pending'].includes(s.status) && ['autobahn', 'lbm_baustellen', 'nina', 'dwd_warnungen', 'adsblol'].includes(s.id) && (s.id !== 'adsblol' || state.layers.air));
  for (const s of problems) {
    box.append(h('div', { class: 'card-f' }, h('span', { class: 'stale-note' }, `${s.name}: ${s.status === 'down' ? `nicht erreichbar seit ${fmtDateTime(s.failing_since ?? s.last_attempt)}` : s.status === 'pending' ? 'noch kein Abruf' : 'veraltet'}`)));
  }
  if (!rows.length) {
    box.append(h('div', { class: 'empty' }, layered.length ? 'Kein Ereignis passt zu den Filtern.' : 'Keine Ereignisse in diesem Zeitfenster und dieser Auswahl.'));
    return;
  }
  const tbody = h('tbody');
  for (const f of rows) {
    const p = f.properties;
    tbody.append(h('tr', { class: 'click', tabindex: '0', 'aria-label': `${p.title} auf Karte zeigen`, onclick: () => focusEvent(f), onkeydown: (e) => { if (e.key === 'Enter') focusEvent(f); } },
      h('td', {}, sevBadge(p.severity)),
      h('td', {}, h('div', {}, h('span', { class: `ico ico-${iconFor(p)}`, 'aria-hidden': 'true' }), p.title), h('div', { class: 'muted' }, TYPE_LABEL[p.type] ?? p.type, ' · ', p.source_short ?? p.source_name, ' · ', ageEl(p.fetched_at))),
      h('td', { class: 'num' }, `${Math.round(p.distance_km)} km`)));
  }
  const th = (label, key, cls) => h('th', { scope: 'col', class: cls, 'aria-sort': evView.sort === key ? (evView.reverse ? 'descending' : 'ascending') : 'none' },
    h('button', { type: 'button', class: 'th-sort', onclick: () => {
      if (evView.sort === key) evView.reverse = !evView.reverse; else { evView.sort = key; evView.reverse = false; }
      panel.querySelector('#ev-sort').value = evView.sort; syncEventTools(panel); renderEvents(state.statuses);
    } }, label));
  box.append(h('div', { class: 'scroll-x' }, h('table', {},
    h('caption', { class: 'sr-only' }, 'Ereignisse im Radius, Tabellenansicht der Karte'),
    h('thead', {}, h('tr', {}, th('Stufe', 'prio'), h('th', { scope: 'col' }, 'Ereignis'), th('Abstand', 'dist', 'num'))), tbody)));
}

export function focusEvent(f) {
  if (!mapReady) return;
  const p = f.properties;
  map.flyTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 10), duration: 600 });
  showPopup(p, 'event', [p.lon, p.lat]);
  $('#map').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
