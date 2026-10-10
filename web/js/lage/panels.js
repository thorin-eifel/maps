import { renderIndizes } from '../indizes.js';
import { buildTree, sortStations } from '../pegel.js';
import { exportStale } from '../rules.js';
import { $, SEV, ageEl, fmtDateTime, fmtHour, fmtTime, h, sevBadge, sparkline } from '../util.js';
import { envLevel, envText } from './messnetz.js';
import { sourceLine, trendText } from './popup.js';
import { gebietAktiv } from '../gebiet.js';
import { state } from './zustand.js';

// ------------------------------------------------------------------ Detailfeld ein-/ausklappen
export function setupSideToggle() {
  const btn = $('#side-toggle'), side = $('#side');
  if (!btn || !side) return;
  btn.addEventListener('click', () => {
    const min = btn.getAttribute('aria-expanded') === 'true'; // war offen → jetzt einklappen
    btn.setAttribute('aria-expanded', String(!min));
    side.dataset.min = String(min);
    $('.lage')?.classList.toggle('side-min', min);
    $('.side-label', btn).textContent = min ? 'Details einblenden' : 'Details ausblenden';
  });
}

// ------------------------------------------------------------------ Warnband
export function renderWarnband(warn, statuses) {
  const band = $('#warnband'), box = $('#warnband-in');
  if (!band || !box) return; // Warnband ist aus der Seite genommen, kommt später in anderer Form
  box.replaceChildren();
  const gen = state.meta?.generated_at;
  const stale = exportStale(gen, Date.now());
  // Ist der Export selbst veraltet, sind die Einzelzustände nur Folgen davon: eine Meldung genügt
  const bad = stale ? [] : statuses.filter((s) => ['down', 'stale', 'pending'].includes(s.status));
  const uncertain = stale || bad.length > 0;
  const worst = warn.reduce((m, f) => Math.max(m, SEV[f.properties.severity].rank), -1);
  const level = worst >= 3 ? 'critical' : worst === 2 ? 'warning' : worst === 1 ? 'notice' : 'none';
  band.dataset.level = level !== 'none' ? level : uncertain ? 'down' : 'none';

  if (stale) {
    box.append(h('strong', {}, `Datenstand veraltet: letzter Export ${fmtDateTime(gen)}`),
      h('span', {}, 'Die Sammelstelle liefert gerade nichts Neues. Gezeigt wird der letzte bekannte Stand, aktuelle Warnungen können fehlen.'));
  }
  if (warn.length) {
    box.append(h('strong', {}, `${warn.length} aktive Warnung${warn.length > 1 ? 'en' : ''} ${state.zellen ? (gebietAktiv(state.gebiet) ? 'im gewählten Gebiet' : 'im Gebiet') : 'im Radius'}`));
    const ul = h('ul');
    for (const f of warn.slice(0, 4)) {
      const p = f.properties;
      ul.append(h('li', {}, `${SEV[p.severity].label}: `, p.title, ` (${p.distance_km} km, ${p.source_short ?? p.source_name})`));
    }
    if (warn.length > 4) ul.append(h('li', {}, `… und ${warn.length - 4} weitere in der Tabelle`));
    box.append(ul);
  } else if (!uncertain) {
    box.append(h('strong', {}, `Keine aktiven Warnungen ${state.zellen ? (gebietAktiv(state.gebiet) ? 'im gewählten Gebiet' : 'im Gebiet') : 'im Radius'}`), h('span', { class: 'muted' }, 'NINA und DWD melden nichts für die Region.'));
  }
  const badText = (s) => `${s.name}: ${s.status === 'down' ? `nicht erreichbar seit ${fmtDateTime(s.failing_since ?? s.last_attempt)}` : s.status === 'pending' ? 'noch kein Abruf' : 'Daten veraltet'}`;
  if (bad.length === 1) {
    box.append(h('strong', {}, badText(bad[0])), h('span', {}, 'Das Lagebild ist für diese Quelle unvollständig.'));
  } else if (bad.length > 1) {
    // Viele Ausfälle: eine Zeile, Einzelheiten aufklappbar (sonst frisst das Band die Karte)
    box.append(h('strong', {}, `${bad.length} von ${statuses.length} Quellen ohne aktuellen Stand`),
      h('span', {}, 'Das Lagebild ist unvollständig.'),
      h('details', {}, h('summary', {}, 'Welche Quellen?'), h('ul', {}, bad.map((s) => h('li', {}, badText(s))))));
  }
  box.append(h('span', { class: 'meta' }, 'Datenstand ', fmtTime(gen)));
}

// ------------------------------------------------------------------ Gewässer
export function pegelCard(s) {
  return h('div', { class: 'pegel' },
    h('h3', {}, s.name, h('span', { class: 'muted' }, s.km != null ? ` · km ${s.km}` : '')),
    h('div', { class: 'val' }, `${s.latest.value} ${s.latest.unit}`),
    h('div', { class: 'muted' }, trendText(s.trend_cm_3h), ' · ', ageEl(s.latest.ts, 'Messung ')),
    h('div', { class: 'muted right' }, s.latest.state ? `laut Quelle: ${s.latest.state}` : '', s.source_name ? h('span', { class: 'small' }, ` · ${s.source_name}`) : ''),
    sparkline(s.series));
}

// Einklappbarer Ast: Zustand (offen/zu) bleibt über die Aktualisierungen erhalten; Ströme sind anfangs offen
export function gNode(key, title, count, body, depth) {
  const open = state.gopen.has(key) ? state.gopen.get(key) : depth === 0;
  const d = h('details', { class: `gnode d${Math.min(depth, 4)}`, 'data-key': key }, h('summary', {}, h('strong', {}, title), h('span', { class: 'muted' }, ` · ${count} ${count === 1 ? 'Pegel' : 'Pegel'}`)), h('div', { class: 'gbody' }, body));
  d.open = open;
  d.addEventListener('toggle', () => state.gopen.set(key, d.open));
  return d;
}

export function renderRiver(n, depth) {
  const body = n.items.map((it) => (it.items ? renderRiver(it, depth + 1) : pegelCard(it)));
  return gNode(`r:${n.id}`, n.name, n.total, body, depth);
}

export function renderGewaesser() {
  const panel = $('#panel-gew');
  panel.replaceChildren();
  const g = state.gew;
  if (!g) { panel.append(h('div', { class: 'empty' }, 'Keine Daten geladen.')); return; }
  const list = sortStations(g.stations.filter((s) => s.latest)); // Gewässer alphabetisch, darin Stationen alphabetisch
  if (!list.length) panel.append(h('div', { class: 'empty' }, 'Noch keine Messwerte.'));
  const tree = buildTree(list, state.net);
  if (tree.roots.length) {
    const all = (open) => () => { panel.querySelectorAll('details.gnode').forEach((d) => { d.open = open; }); };
    panel.append(h('div', { class: 'card-f gtools' },
      h('span', { class: 'muted small' }, 'Von der Mündung zur Quelle; Zuflüsse stehen dort, wo sie münden.'),
      h('button', { type: 'button', class: 'linkbtn', onclick: all(true) }, 'alles auf'),
      h('button', { type: 'button', class: 'linkbtn', onclick: all(false) }, 'alles zu')));
    for (const r of tree.roots) panel.append(renderRiver(r, 0));
    const rest = tree.open.groups.reduce((a, x) => a + x.stations.length, 0);
    if (rest) panel.append(gNode('open', 'Weitere Gewässer (Zuordnung offen)', rest,
      tree.open.groups.map((x) => gNode(`o:${x.label}`, x.label, x.stations.length, x.stations.map(pegelCard), 2)), 0));
    if (tree.none.length) panel.append(gNode('none', 'Ohne Gewässerangabe', tree.none.length, tree.none.map(pegelCard), 1));
  } else {   // Netzdatei fehlt: flache Liste wie bisher
    let water;
    for (const s of list) {
      if (s.water_label !== water) { water = s.water_label; panel.append(h('div', { class: 'card-f' }, h('strong', {}, water ?? 'Ohne Gewässerangabe'))); }
      panel.append(pegelCard(s));
    }
  }
  panel.append(h('div', { class: 'card-f' }, h('span', { class: 'muted small' }, 'Gewässerzuordnung: Wikidata (CC0), automatisch zugeordnet; wo der Name nicht eindeutig ist, steht der Pegel unter „Zuordnung offen“.')));
  for (const src of g.sources ?? [g.source]) if (src) panel.append(sourceLine(src));
}

// ------------------------------------------------------------------ Umwelt
export function renderUmwelt() {
  const panel = $('#panel-env');
  panel.replaceChildren();
  const e = state.env;
  if (!e) { panel.append(h('div', { class: 'empty' }, 'Keine Daten geladen.')); return; }
  let kind = null;
  for (const s of e.stations.filter((x) => x.kind !== 'weather')) {   // Wetterstationen stehen auf der Karte, nicht in dieser Liste
    if (s.kind !== kind) { kind = s.kind; panel.append(h('div', { class: 'card-f' }, h('strong', {}, kind === 'radiation' ? 'Ortsdosisleistung (Gamma)' : 'Luftqualität'))); }
    const first = Object.values(s.values)[0];
    panel.append(h('div', { class: 'pegel' },
      h('h3', {}, s.name, h('span', { class: 'muted' }, ` · ${Math.round(s.distance_km)} km`)),
      h('div', { class: 'val' }, sevBadge(envLevel(s))),
      h('div', { class: 'muted' }, envText(s).join(' · '), ' · ', ageEl(first?.ts, 'Messung ')),
      h('div', { class: 'muted right' }, s.source_name),
      sparkline((s.kind === 'radiation' ? s.values.odl : s.values.NO2 ?? s.values.PM10 ?? s.values.lqi)?.series?.map((v, i) => ({ ts: i, value: v })) ?? [])));
  }
  if (!e.stations.length) panel.append(h('div', { class: 'empty' }, 'Noch keine Messwerte.'));
  for (const src of e.sources ?? []) panel.append(sourceLine(src));
  renderIndizes(panel, state.idx, { h, sevBadge, sourceLine, ageEl });
  panel.append(h('div', { class: 'card-f' }, h('span', { class: 'muted small' }, 'Stufen bei Strahlung sind eigene Orientierung (0,3 und 1,0 µSv/h), kein amtlicher Grenzwert. Luft nach dem Index der Quelle.')));
}

// ------------------------------------------------------------------ Wetter
// Kompaktes „Wetter jetzt“ über der Karte, damit die Lage nicht erst im Reiter gesucht werden muss
export function renderWxBand() {
  const box = $('#wxband');
  if (!box) return; // Wetterband ist aus der Seite genommen; das Wetter steht im Reiter
  const w = state.wx;
  box.replaceChildren();
  const c = w?.current;
  if (!c || !c.temperature) {
    box.append(h('strong', {}, 'Wetter jetzt'), h('span', { class: 'muted' }, 'Keine Messwerte geladen'));
    return;
  }
  const num = (k, d = 0) => (c[k] ? `${Number(c[k].value).toFixed(d)} ${c[k].unit}` : '–');
  const src = state.statuses.find((s) => s.id === 'brightsky');
  const items = [
    ['Temperatur', num('temperature', 1), 'temperatur'],
    ['Wind', `${num('wind_speed_10')}${c.wind_gust_speed_10 ? `, Böen ${num('wind_gust_speed_10')}` : ''}`, 'wind'],
    ['Niederschlag (60 Min.)', num('precipitation_60', 1), 'regen'],
    ['Bewölkung', num('cloud_cover'), 'wolken'],
    ['Luftfeuchte', num('relative_humidity'), 'feuchte'],
    ['Luftdruck', num('pressure_msl'), 'druck'],
  ];
  const dl = h('dl', { class: 'wx-items' });
  for (const [k, v, ico] of items) dl.append(h('div', {}, h('dt', {}, h('span', { class: `ico ico-${ico}`, 'aria-hidden': 'true' }), k), h('dd', {}, v)));
  const meta = h('span', { class: 'meta' },
    `Station ${w.station?.name ?? '–'} (${w.station?.distance_km ?? '?'} km) · Messung `, ageEl(c.temperature.ts),
    ` · ${w.source?.attribution ?? 'Quelle: DWD über Bright Sky'}`);
  const old = Date.now() - new Date(c.temperature.ts).getTime() > 2 * 3600 * 1000;
  const note = ['down', 'stale'].includes(src?.status) || old
    ? h('span', { class: 'stale-note' }, src?.status === 'down' ? 'Quelle nicht erreichbar, Werte nicht aktuell' : 'Werte veraltet')
    : null;
  box.append(h('strong', {}, 'Wetter jetzt'), dl, ...(note ? [note] : []), meta);
}

export function renderWetter() {
  const panel = $('#panel-wx');
  panel.replaceChildren();
  const w = state.wx;
  if (!w || !w.current.temperature) { panel.append(h('div', { class: 'empty' }, 'Keine Wetterdaten geladen.'), sourceLine(w?.source)); return; }
  const c = w.current, v = (k, d = 0) => (c[k] ? `${Number(c[k].value).toFixed(d)} ${c[k].unit}` : '–');
  panel.append(h('div', { class: 'wx-now' },
    h('div', { class: 'big' }, v('temperature', 1)),
    h('dl', { class: 'kv' }, h('dt', {}, 'Wind (10 Min.)'), h('dd', {}, v('wind_speed_10', 1)), h('dt', {}, 'Böen'), h('dd', {}, v('wind_gust_speed_10', 1))),
    h('dl', { class: 'kv' }, h('dt', {}, 'Luftfeuchte'), h('dd', {}, v('relative_humidity')), h('dt', {}, 'Luftdruck'), h('dd', {}, v('pressure_msl', 1))),
    h('dl', { class: 'kv' }, h('dt', {}, 'Niederschlag (60 Min.)'), h('dd', {}, v('precipitation_60', 1)), h('dt', {}, 'Bewölkung'), h('dd', {}, v('cloud_cover')), h('dt', {}, 'Sicht'), h('dd', {}, c.visibility ? `${(c.visibility.value / 1000).toFixed(0)} km` : '–')),
    h('div', { class: 'muted wx-note' }, `Station ${w.station?.name ?? '–'} (${w.station?.distance_km ?? '?'} km), Messung `, ageEl(c.temperature.ts))));
  const hrs = w.forecast?.payload?.hours ?? [];
  const alt = w.forecast_alt?.hours ?? [];
  if (hrs.length) panel.append(forecastChart(hrs, alt));
  panel.append(sourceLine(w.source, w.forecast ? h('span', {}, 'Vorhersage ', ageEl(w.forecast.fetched_at)) : null));
  if (alt.length) panel.append(sourceLine(w.forecast_alt.source, h('span', {}, 'Vorhersage ', ageEl(w.forecast_alt.fetched_at))));
  if (w.others?.length) panel.append(othersTable(w.others));
}

// Weitere Beobachtungen: MeteoLux Findel und Sensor.Community-Raster, jeweils mit Quelle und Alter der Messung
export function othersTable(list) {
  const rows = list.slice(0, 7);
  const cell = (o, k, d = 0) => (o.current[k] ? `${Number(o.current[k].value).toFixed(d)} ${o.current[k].unit}` : '–');
  const newest = (o) => Object.values(o.current).map((x) => x.ts).sort().pop();
  const tbl = h('table', { class: 'wx-others' },
    h('caption', {}, 'Weitere Messungen in der Region'),
    h('thead', {}, h('tr', {}, ...['Ort (Quelle)', 'Temp.', 'Feuchte', 'Wind', 'Alter'].map((t) => h('th', { scope: 'col' }, t)))),
    h('tbody', {}, ...rows.map((o) => h('tr', {},
      h('th', { scope: 'row' }, `${o.name} `, h('span', { class: 'muted small' }, `(${o.source_name}${o.meta?.sensoren ? `, Median aus ${o.meta.sensoren} Sensoren` : ''}, ${o.distance_km} km)`)),
      h('td', {}, cell(o, 'temperature', 1)), h('td', {}, cell(o, 'relative_humidity')), h('td', {}, cell(o, 'wind_speed_10')), h('td', {}, ageEl(newest(o)))))));
  const srcIds = [...new Set(rows.map((o) => o.source_id))];
  const caveat = rows.some((o) => o.source_id === 'sensor_community')
    ? h('p', { class: 'muted small' }, 'Bürgersensoren sind nicht kalibriert und zeigen in der Sonne oder bei erwärmtem Gehäuse oft mehrere Grad zu viel. Richtwert, keine amtliche Messung.')
    : null;
  return h('div', { class: 'wx-chart' }, tbl, ...(caveat ? [caveat] : []), ...srcIds.map((id) => sourceLine(state.statuses.find((x) => x.id === id) ?? null)));
}

export function forecastChart(hrs, alt = []) {
  const NS = 'http://www.w3.org/2000/svg', W = 360, H = 120, padL = 22, padB = 16;
  const el = (t, a = {}) => { const e = document.createElementNS(NS, t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Temperatur und Niederschlag, nächste 48 Stunden' });
  const t = [...hrs, ...alt].map((r) => r.temperature).filter((x) => x != null);
  const tmin = Math.floor(Math.min(...t)), tmax = Math.ceil(Math.max(...t)), span = tmax - tmin || 1;
  const x = (i) => padL + (i / (hrs.length - 1)) * (W - padL - 4), y = (val) => H - padB - ((val - tmin) / span) * (H - padB - 8);
  const pmax = Math.max(1, ...hrs.map((r) => r.precipitation ?? 0));
  hrs.forEach((r, i) => { if (r.precipitation > 0) { const bh = (r.precipitation / pmax) * 34; svg.append(el('rect', { class: 'bar', x: x(i) - 2, y: H - padB - bh, width: 4, height: bh })); } });
  for (const val of [tmin, tmax]) { svg.append(el('line', { class: 'grid-line', x1: padL, x2: W, y1: y(val), y2: y(val) })); const l = el('text', { class: 'lbl', x: 0, y: y(val) + 3 }); l.textContent = `${val}°`; svg.append(l); }
  const d = hrs.map((r, i) => (r.temperature == null ? '' : `${i && hrs[i - 1].temperature != null ? 'L' : 'M'}${x(i).toFixed(1)} ${y(r.temperature).toFixed(1)}`)).join(' ');
  svg.append(el('path', { d, class: 'spark' }));
  if (alt.length) {   // zweites Modell: gleiche Zeitachse, gestrichelt; Stunden über die Zeitstempel zugeordnet
    const idx = new Map(hrs.map((r, i) => [r.timestamp.slice(0, 13), i]));
    const pts = alt.map((r) => [idx.get(r.timestamp.slice(0, 13)), r.temperature]).filter(([i, v]) => i != null && v != null);
    svg.append(el('path', { d: pts.map(([i, v], n) => `${n ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' '), class: 'spark spark-alt' }));
  }
  [0, 12, 24, 36, 47].filter((i) => i < hrs.length).forEach((i) => { const l = el('text', { class: 'lbl', x: x(i) - 12, y: H - 3 }); l.textContent = fmtHour(hrs[i].timestamp); svg.append(l); });
  const wrap = h('div', { class: 'wx-chart' }, svg, h('div', { class: 'muted small' }, alt.length ? 'Durchgezogen: Temperatur DWD, gestrichelt: MET Norway, Balken: Niederschlag DWD je Stunde' : 'Linie: Temperatur, Balken: Niederschlag je Stunde'));
  return wrap;
}
