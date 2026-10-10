import { advance, windowFilter } from '../rules.js';
import { $, getJSON } from '../util.js';
import { renderAir } from './laden.js';
import { AIR_IMG, map, mapReady, reduceMotion, state, sweep } from './zustand.js';

// Flugzeuge zwischen zwei Abrufen weiterrücken lassen; Positionen stammen aus aircraft.json, nichts wird gemerkt
export function pushAir() {
  if (!mapReady) return;
  const now = Date.now();
  const feats = state.layers.air
    ? windowFilter(state.airRaw, 'now', now).map((f) => {
        const p = f.properties, dt = Math.min(45, (now - new Date(p.fetched_at).getTime()) / 1000);
        const [lon, lat] = reduceMotion ? f.geometry.coordinates : advance(f.geometry.coordinates[0], f.geometry.coordinates[1], p.attrs?.track, p.attrs?.speed_kmh, dt);
        const klass = p.attrs?.klass ?? 'civil';
        return { type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties: { ...p, track: p.attrs?.track ?? 0, klass, icon: 'flug', img: AIR_IMG[klass] ?? 'plane-' } };
      })
    : [];
  map.getSource('air').setData({ type: 'FeatureCollection', features: feats });
  sweep?.update(state.layers.air, feats.map((f) => ({ id: f.properties.id, lng: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], mil: f.properties.klass.startsWith('mil') })));
  const note = $('#airnote');
  if (note) {
    if (!state.layers.air) note.textContent = '';
    else if (!state.airAt) note.textContent = 'lädt …';
    else {
      const age = Math.round((now - state.airAt) / 1000), newest = Math.max(0, ...state.airRaw.map((f) => new Date(f.properties.fetched_at).getTime()));
      const dataAge = newest ? Math.round((now - newest) / 1000) : null;
      note.textContent = dataAge === null ? `keine Flugzeuge im Radius (geprüft vor ${age} s)` : dataAge > 90 ? `veraltet (Stand vor ${dataAge} s)` : `live, Stand vor ${dataAge} s`;
    }
  }
}

export async function refreshAir() {
  if (!state.layers.air || document.hidden) return;
  try {
    const d = await getJSON('data/aircraft.json');
    state.airRaw = d.features ?? [];
    state.airAt = Date.now();
    renderAir();
  } catch { /* letzter Stand bleibt; die Punkte laufen selbst ab (valid_to) */ }
}
