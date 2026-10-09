// Status- und Quellenseiten.
import { $, h, getJSON, fmtDateTime, ageEl, tickAges, statusBadge, initTheme, link } from './util.js';
import { deriveStatus, overall, exportStale } from './rules.js';

async function status() {
  const box = $('#status-body');
  let d;
  try { d = await getJSON('data/status.json'); } catch { box.replaceChildren(h('div', { class: 'empty' }, 'API nicht erreichbar.')); return; }
  const now = Date.now();
  d.sources = d.sources.map((s) => deriveStatus(s, now));
  const stale = exportStale(d.generated_at, now);
  $('#overall').replaceChildren(statusBadge(overall(d.sources)), ' Export erzeugt ', ageEl(d.generated_at),
    ...(stale ? [h('span', { class: 'stale-note' }, ' — Sammelstelle liefert nichts Neues')] : []));
  const tbody = h('tbody');
  for (const s of d.sources) {
    const runs = h('span', { class: 'runs', 'aria-label': `letzte ${s.recent_runs.length} Läufe` },
      [...s.recent_runs].reverse().map((r) => h('span', { class: `run${r.ok ? '' : ' bad'}`, title: `${fmtDateTime(r.started_at)}: ${r.ok ? `${r.n_new} neu` : r.error}` })));
    tbody.append(h('tr', {},
      h('td', {}, h('strong', {}, s.name), h('div', { class: 'muted mono' }, s.id)),
      h('td', {}, statusBadge(s.status), s.status === 'down' ? h('div', { class: 'stale-note' }, `seit ${fmtDateTime(s.failing_since ?? s.last_attempt)}`) : null),
      h('td', {}, s.last_success ? [fmtDateTime(s.last_success), h('div', { class: 'muted' }, ageEl(s.last_success))] : 'noch nie'),
      h('td', { class: 'num' }, `${Math.round(s.interval_s / 60)} Min.`),
      h('td', { class: 'num' }, String(s.consecutive_failures)),
      h('td', { class: 'num' }, String(s.active_events)),
      h('td', {}, runs),
      h('td', {}, s.last_error_or_note ? h('span', { class: 'mono' }, s.last_error_or_note) : '–', s.circuit_open_until ? h('div', { class: 'stale-note' }, `Circuit offen bis ${fmtDateTime(s.circuit_open_until)}`) : null)));
  }
  box.replaceChildren(h('div', { class: 'scroll-x' }, h('table', {},
    h('caption', { class: 'sr-only' }, 'Zustand aller Collector'),
    h('thead', {}, h('tr', {}, ['Quelle', 'Zustand', 'Letzter Erfolg', 'Intervall', 'Fehler in Folge', 'Aktive Ereignisse', 'Letzte Läufe', 'Hinweis / Fehler'].map((t, i) => h('th', { scope: 'col', class: i >= 3 && i <= 5 ? 'num' : '' }, t)))),
    tbody)));
}

async function quellen() {
  const box = $('#quellen-body');
  let d;
  try { d = await getJSON('data/sources.json'); } catch { box.replaceChildren(h('div', { class: 'empty' }, 'API nicht erreichbar.')); return; }
  box.replaceChildren(...d.sources.map((s) => h('section', { class: 'src' },
    h('h2', {}, s.name),
    h('div', { class: 'muted' }, s.betreiber),
    h('dl', {},
      h('dt', {}, 'Namensnennung'), h('dd', {}, s.namensnennung),
      h('dt', {}, 'Lizenz'), h('dd', {}, s.lizenz, ' ', s.lizenz_geprueft ? h('span', { class: 'badge st-ok' }, 'geprüft') : h('span', { class: 'badge st-stale' }, 'noch zu bestätigen')),
      s.lizenz_hinweis ? [h('dt', {}, 'Hinweis'), h('dd', {}, s.lizenz_hinweis)] : null,
      h('dt', {}, 'Endpunkt'), h('dd', {}, link(s.url, s.url)),
      h('dt', {}, 'Abrufintervall'), h('dd', {}, `${Math.round(s.intervall / 60)} Minuten`),
      h('dt', {}, 'Ratenlimit'), h('dd', {}, s.ratenlimit),
      h('dt', {}, 'Zugang'), h('dd', {}, s.auth),
      h('dt', {}, 'Räumlicher Bezug'), h('dd', {}, s.geo_bezug),
      h('dt', {}, 'Datenschutzrisiko'), h('dd', {}, s.datenschutz_risiko),
      h('dt', {}, 'Zuletzt geprüft'), h('dd', {}, s.zuletzt_geprüft)))));
  $('#disclaimer').textContent = d.disclaimer;
}

initTheme($('#theme'));
if ($('#status-body')) { status(); setInterval(status, 30000); }
if ($('#quellen-body')) quellen();
setInterval(tickAges, 30000);
