import { infraText } from '../infra.js';
import { deriveStatus } from '../rules.js';
import { TYPE_LABEL, ageEl, fmtDateTime, h, link, sevBadge } from '../util.js';
import { EUR_SHORT, fmtDay } from './messnetz.js';
import { map, popup, state } from './zustand.js';

export function showPopup(p, kind, lngLat) {
  const box = h('div', { class: 'pop' });
  if (kind === 'station') {
    box.append(h('h3', {}, h('span', { class: 'ico ico-pegel', 'aria-hidden': 'true' }), `Pegel ${p.name} (${p.water ?? '–'})`),
      h('p', {}, `${p.value} ${p.unit}`, p.trend !== undefined && p.trend !== 'null' ? ` · ${trendText(Number(p.trend))}` : ''),
      h('p', { class: 'k' }, `Messung ${fmtDateTime(p.ts)} · Zustand laut Quelle: ${p.state ?? '–'}`),
      h('p', { class: 'k' }, (p.attribution ?? state.gew?.source?.attribution ?? '') + (p.operator ? ` · Betreiber: ${p.operator}` : '')));
  } else if (kind === 'tank') {
    const prices = JSON.parse(p.prices);
    const isLu = p.lu === true || p.lu === 'true';
    const rows = (isLu ? [['sp95', 'Super 95'], ['sp98', 'Super 98'], ['diesel', 'Diesel']] : [['e5', 'Super E5'], ['e10', 'Super E10'], ['diesel', 'Diesel']]).filter(([k]) => prices[k]);
    box.append(h('h3', {}, h('span', { class: 'ico ico-tanken', 'aria-hidden': 'true' }), p.name),
      h('p', { class: 'k' }, `${p.ort ? `${p.ort} · ` : ''}${p.km} km von Irrel${isLu ? ' · Luxemburg' : ''}`));
    if (isLu) box.append(h('p', {}, h('strong', {}, 'Höchstpreis, nicht Stationspreis.'), ' Der Staat setzt den Höchstpreis für ganz Luxemburg fest; diese Station kann darunter liegen.'));
    box.append(h('table', { class: 'pop-prices' }, h('caption', { class: 'sr-only' }, `${isLu ? 'Amtliche Höchstpreise' : 'Aktuelle Preise'} ${p.name}`),
      h('tbody', {}, ...rows.map(([k, label]) => h('tr', {}, h('th', { scope: 'row' }, label), h('td', {}, `${isLu ? '≤ ' : ''}${EUR_SHORT(prices[k].value)} €`),
        h('td', { class: 'muted small' }, isLu ? `ab ${fmtDay(prices[k].valid_from)}` : ageEl(prices[k].ts)))))));
    box.append(isLu
      ? h('p', { class: 'k' }, `Preise: ${state.fuel?.lu?.max_source?.attribution ?? 'STATEC / LUSTAT, CC0'} · Standort: ${state.fuel?.lu?.stations_source?.attribution ?? '© OpenStreetMap-Mitwirkende (ODbL)'}`)
      : h('p', { class: 'k' }, `${state.fuel?.source?.attribution ?? 'Tankerkönig (CC BY 4.0)'} · Preise ohne Gewähr, Abruf `, ageEl(state.fuel?.source?.last_success)));
  } else if (kind === 'route') {
    box.append(h('h3', {}, p.name), h('p', {}, p.kind === 'bike' ? 'Radroute' : 'Wanderroute', p.ref ? ` ${p.ref}` : '', p.network ? ` · ${({ iwn: 'international', nwn: 'national', rwn: 'regional', icn: 'international', ncn: 'national', rcn: 'regional' })[p.network] ?? p.network}` : ''),
      h('p', { class: 'k' }, `${state.routen?.source?.attribution ?? '© OpenStreetMap-Mitwirkende (ODbL)'} · Stand `, ageEl(state.routen?.source?.last_success)),
      h('p', { class: 'k' }, 'Ehrenamtlich gepflegt; Sperrungen und Umleitungen zeigt die Karte nicht. Maßgeblich ist die Wegweisung vor Ort.'));
  } else if (kind === 'infra') {
    box.append(h('h3', {}, infraText(p)),
      h('p', { class: 'k' }, `${state.infra?.source?.attribution ?? '© OpenStreetMap-Mitwirkende (ODbL)'} · Stand `, ageEl(state.infra?.source?.last_success)),
      h('p', { class: 'k' }, 'Ehrenamtlich gepflegt, ohne Gewähr; im Notfall 112.'));
  } else if (kind === 'env') {
    box.append(h('h3', {}, h('span', { class: `ico ico-${p.icon}`, 'aria-hidden': 'true' }), `${p.kind === 'radiation' ? 'Strahlung' : p.kind === 'weather' ? 'Wetterstation' : 'Luft'}: ${p.name}`),
      ...(p.kind === 'weather' ? [] : [h('p', {}, sevBadge(p.severity))]));
    for (const line of JSON.parse(p.lines)) box.append(h('p', {}, line));
    box.append(h('p', { class: 'k' }, `Messung ${fmtDateTime(p.ts)} · ${p.attribution ?? ''}`));
  } else {
    box.append(h('h3', {}, h('span', { class: `ico ico-${p.icon ?? 'warnung'}`, 'aria-hidden': 'true' }), p.title), h('p', {}, sevBadge(p.severity), ' ', TYPE_LABEL[p.type] ?? p.type));
    if (p.summary) box.append(h('p', {}, p.summary.length > 320 ? `${p.summary.slice(0, 319)}…` : p.summary));
    box.append(h('p', { class: 'k' }, `${p.distance_km} km von Irrel · gültig ab ${fmtDateTime(p.valid_from)}${p.valid_to ? ` bis ${fmtDateTime(p.valid_to)}` : ''}`));
    if (Number(p.confidence) < 1) box.append(h('p', { class: 'k' }, `Ortsgenauigkeit eingeschränkt (Konfidenz ${p.confidence})`));
    box.append(h('p', { class: 'k' }, `${p.attribution ?? p.source_name} · Abruf `, ageEl(p.fetched_at), p.raw_ref ? [' · ', link(p.raw_ref, 'Original')] : ''));
  }
  popup.setLngLat(lngLat).setDOMContent(box).addTo(map);
}

// ------------------------------------------------------------------ Bausteine
export const trendText = (v) => (v === null || Number.isNaN(v) ? 'Trend unbekannt' : v > 0.4 ? `steigend (+${v} cm/3 Std.)` : v < -0.4 ? `fallend (${v} cm/3 Std.)` : 'gleichbleibend');

export function sourceLine(srcRaw, extra) {
  const src = srcRaw ? deriveStatus(srcRaw, Date.now()) : null;
  if (!src) return h('div', { class: 'card-f' }, 'Quellenstatus unbekannt');
  const kids = [h('span', {}, src.attribution), h('span', {}, 'Abruf ', ageEl(src.last_success))];
  if (['down', 'stale'].includes(src.status)) {
    kids.push(h('span', { class: 'stale-note' },
      src.status === 'down' ? `Quelle nicht erreichbar seit ${fmtDateTime(src.failing_since ?? src.last_attempt)}` : 'Daten veraltet'));
  }
  if (extra) kids.push(extra);
  return h('div', { class: 'card-f' }, kids);
}
