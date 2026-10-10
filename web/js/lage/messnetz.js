import { tempClass } from '../icons.js';
import { stationRank } from '../pegel.js';
import { iconFor, trafficLevel } from '../rules.js';
import { pushAir } from './flugverkehr.js';
import { ebenenBudget } from '../zellen.js';
import { map, mapReady, state } from './zustand.js';

export function pushMapData() {
  if (!mapReady) return;
  const nonAir = state.events.filter((f) => f.properties.type !== 'aircraft');
  const shown = (state.zellen ? ebenenBudget(nonAir, map.getZoom()) : nonAir).map((f) => ({ ...f, properties: { ...f.properties, icon: iconFor(f.properties), lvl: trafficLevel(f.properties) ?? undefined } }));
  map.getSource('events').setData({ type: 'FeatureCollection', features: shown });
  pushAir();
  const feats = (state.gew?.stations ?? []).filter((s) => s.latest).map((s) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
    properties: { rank: stationRank(s, state.net), name: s.name, water: s.water, value: s.latest.value, unit: s.latest.unit, ts: s.latest.ts, state: s.latest.state, trend: s.trend_cm_3h, attribution: s.attribution, operator: s.meta?.operator },
  }));
  map.getSource('stations').setData({ type: 'FeatureCollection', features: feats });
  map.getSource('env').setData({ type: 'FeatureCollection', features: envFeatures() });
  map.getSource('tank').setData({ type: 'FeatureCollection', features: tankFeatures() });
}

// Tankstellen: nur Marke, Ort, Koordinaten und Preise (keine Straße, keine Hausnummer); Preise als Text, weil MapLibre keine Objekte in Eigenschaften führt
export function tankFeatures() {
  const de = (state.fuel?.stations ?? []).filter((r) => Number.isFinite(r.lat) && Number.isFinite(r.lon)).map((r) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
    properties: { name: r.name, ort: r.ort ?? '', km: Math.round(r.distance_km ?? 0), prices: JSON.stringify(r.prices), lu: false,
      label: (r.prices.e10 ?? r.prices.e5 ?? r.prices.diesel) ? EUR_SHORT((r.prices.e10 ?? r.prices.e5 ?? r.prices.diesel).value) : '' },
  }));
  // Luxemburg: Standorte aus OpenStreetMap, dazu der amtliche Höchstpreis (gleich für alle); die Beschriftung trägt ein "≤"
  const lu = state.fuel?.lu, mx = lu?.max_prices ?? {};
  const luFeatures = !mx.sp95 && !mx.diesel ? [] : (lu?.stations ?? []).map((r) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
    properties: { name: r.name, ort: '', km: Math.round(r.distance_km ?? 0), prices: JSON.stringify(mx), lu: true,
      label: '' },   // gleicher Höchstpreis an jeder Station: kein Preis auf der Karte, er steht im Popup
  }));
  return [...de, ...luFeatures];
}
export const fmtDay = (d) => String(d ?? '').split('-').reverse().join('.');   // 2026-10-06 → 06.10.2026
export const EUR_SHORT = (v) => Number(v).toFixed(3).replace('.', ',');

// ------------------------------------------------------------------ Luft, Strahlung, Radar
// Stufe je Station: Strahlung nach eigener Orientierung (0,3 / 1,0 µSv/h), Luft nach dem Index der Quelle (3 = schlecht, 4 = sehr schlecht)
export function envLevel(s) {
  if (s.kind === 'weather') return 'info';
  if (s.kind === 'radiation') { const v = s.values.odl?.value ?? 0; return v >= 1 ? 'warning' : v >= 0.3 ? 'notice' : 'info'; }
  const q = s.values.lqi?.value ?? 0;
  return q >= 4 ? 'warning' : q >= 3 ? 'notice' : 'info';
}
export const ENV_LABEL = { odl: 'Ortsdosisleistung', lqi: 'Luftqualitätsindex', NO2: 'Stickstoffdioxid', PM10: 'Feinstaub PM10', 'PM2.5': 'Feinstaub PM2,5', O3: 'Ozon', temperature: 'Temperatur', relative_humidity: 'Luftfeuchte', pressure_msl: 'Luftdruck (auf Meereshöhe)', wind_speed_10: 'Wind', wind_gust_speed_10: 'Böen', precipitation_60: 'Niederschlag (60 min)' };
export function envText(s) {
  return Object.entries(s.values).map(([k, v]) => `${ENV_LABEL[k] ?? k}: ${k === 'lqi' ? (v.state ?? v.value) : `${String(v.value).replace('.', ',')} ${v.unit}`}`);
}
export function envFeatures() {
  // Strahlung erscheint auf der Karte erst ab dem Orientierungswert (0,3 µSv/h); darunter nur in der Liste
  return (state.env?.stations ?? []).filter((s) => s.kind !== 'radiation' || envLevel(s) !== 'info').map((s) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
    properties: { name: s.name, kind: s.kind, icon: s.kind === 'radiation' ? 'strahlung' : s.kind === 'weather' ? 'temperatur' : 'luft', severity: envLevel(s),
      label: s.kind === 'weather' && s.values.temperature ? `${String(Math.round(s.values.temperature.value))}°` : '', lines: JSON.stringify(envText(s)),
      ts: Object.values(s.values)[0]?.ts, attribution: s.attribution,
      ...(s.kind === 'weather' && Number.isFinite(s.values.temperature?.value) ? { tclass: tempClass(s.values.temperature.value) } : {}) },
  }));
}
