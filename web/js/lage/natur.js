import { MED } from './mittelalter.js';
import { HALO } from './stil.js';
import { map, mapReady, state } from './zustand.js';

// Natürliche Landmarken. Gipfel (mit Höhe) stammen aus den eigenen Kacheln (pois/peak), Höhlen, Wasserfälle, Quellen, Aussichtspunkte,
// Felsen und Vulkane aus landmarks.json (OpenStreetMap über Overpass, wöchentlich). Jeweils nur Name, Höhe, Ort; nichts Personenbezogenes.
export const NATURE_COLOR = { peak: '#7a5a2e', cave: '#4b3a2c', waterfall: '#1f6fb5', viewpoint: '#8a3fb0', spring: '#12857f', rock: '#8c6b32', volcano: '#c0401f' };
export const NAT_LAYERS = ['nat-t1', 'nat-t2', 'nat-t3', 'nat-t4'];
export const HER_LAYERS = ['her-t1', 'her-t2'];
export const HERITAGE_KINDS = ['castle', 'ruins', 'archaeological', 'monastery', 'building'];
export const NATURE_WORD = { cave: ['Höhle', 'höhl'], waterfall: ['Wasserfall', 'wasserf'], viewpoint: ['Aussicht', 'aussicht|blick'], spring: ['Quelle', 'quell|born'], rock: ['Fels', 'fels|stein|kanzel'], volcano: ['Vulkan', 'vulkan'],
  castle: ['Burg', 'burg|schloss|festung|fort|turm|hof'], ruins: ['Ruine', 'ruine|burg|schloss|turm'], archaeological: ['Fundstelle', 'römisch|villa|kastell|tempel|grab|ring|wall|fundstelle|ausgrab|kelt|hügel'],
  monastery: ['Kloster', 'kloster|abtei|stift|kartause|priorat'], building: ['', '.'] };
export const natureLabel = (kind, name) => {
  const [word, stem] = NATURE_WORD[kind] ?? [kind, kind];
  if (!name) return word;
  if (!word) return name;
  return new RegExp(stem, 'i').test(name) ? name : `${word} ${name}`;
};
export const peakLabel = ['case', ['has', 'elevation'], ['concat', ['get', 'name'], ' ', ['to-string', ['get', 'elevation']], ' m'], ['get', 'name']];
export function peakLayers(dark, icon) {
  const halo = HALO[dark ? 'dark' : 'light'], ink = dark ? '#e9d3ab' : '#5a3f17';
  return [
    ...(icon ? [{ id: 'nat-peak-sym', type: 'symbol', source: 'basemap', 'source-layer': 'pois', minzoom: 11, filter: ['all', ['==', 'kind', 'peak'], ['has', 'name']],
      layout: { 'icon-image': 'peak-tri', 'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.6, 15, 0.9], 'icon-allow-overlap': false,
        'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'elevation'], 0]] },
      paint: { 'icon-color': NATURE_COLOR.peak, 'icon-halo-color': halo, 'icon-halo-width': 1.2 } }] : []),
    { id: 'nat-peak-label', type: 'symbol', source: 'basemap', 'source-layer': 'pois', minzoom: 12, filter: ['all', ['==', 'kind', 'peak'], ['has', 'name']],
      layout: { 'text-field': peakLabel, 'text-font': ['Noto Sans Regular'], 'text-size': 11, 'text-offset': [0, 0.8], 'text-anchor': 'top', 'text-max-width': 9,
        'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'elevation'], 0]] },
      paint: { 'text-color': ink, 'text-halo-color': halo, 'text-halo-width': 1.8, 'text-halo-blur': 0.3 } },
  ];
}
export function natureFeatures() {
  return { type: 'FeatureCollection', features: (state.landmarks?.items ?? []).map((i) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [i.lon, i.lat] },
    properties: { kind: i.kind, label: natureLabel(i.kind, i.name), named: i.name ? 1 : 0, ele: i.ele ?? null } })) };
}
export function paintNature() {
  if (!mapReady || !map.getLayer('nat-t1')) return;
  const dark = document.documentElement.dataset.ansicht === 'dunkel';
  for (const id of [...NAT_LAYERS, ...HER_LAYERS]) {
    if (!map.getLayer(id)) continue;
    map.setPaintProperty(id, 'text-halo-color', HALO[dark ? 'dark' : 'light']);
    map.setPaintProperty(id, 'text-color', dark ? '#f1f1f1' : '#1c1c1c');
  }
  applyNatureVisibility();   // historische Karte überschreibt Schrift und Zeichen der Kulturebene
}
export function applyNature() {
  if (!mapReady || !state.landmarks) return;
  const src = map.getSource('landmarks');
  if (src) src.setData(natureFeatures());
  else {
    map.addSource('landmarks', { type: 'geojson', data: natureFeatures() });
    // Stufen nach Bedeutung, damit die Karte nicht mit Punkten zuläuft: Höhlen, Wasserfälle, Felsen, Vulkane früh; benannte Aussichten
    // später; Quellen (400) ab Zoom 13,5; unbenannte Aussichtspunkte (die meisten) erst ganz nah. Überlappende Symbole entfallen von selbst.
    const tiers = [
      ['nat-t1', 10.5, ['in', ['get', 'kind'], ['literal', ['cave', 'waterfall', 'rock', 'volcano']]], 4],
      ['nat-t2', 12.5, ['all', ['==', ['get', 'kind'], 'viewpoint'], ['==', ['get', 'named'], 1]], 3],
      ['nat-t3', 13.5, ['==', ['get', 'kind'], 'spring'], 2],
      ['nat-t4', 14.5, ['all', ['==', ['get', 'kind'], 'viewpoint'], ['==', ['get', 'named'], 0]], 1],
      // Kultur und Geschichte: Burgen, Ruinen, Ausgrabungen, Klöster früh; historische Gebäude (viele kleine) ab Zoom 12,5
      ['her-t1', 10.5, ['in', ['get', 'kind'], ['literal', ['castle', 'ruins', 'archaeological', 'monastery']]], 4],
      ['her-t2', 12.5, ['==', ['get', 'kind'], 'building'], 2],
    ];
    for (const [id, minzoom, filter, prio] of tiers) {
      map.addLayer({ id, type: 'symbol', source: 'landmarks', minzoom, filter,
        layout: { 'icon-image': ['concat', 'nat-', ['get', 'kind']], 'icon-size': ['interpolate', ['linear'], ['zoom'], 10, 0.7, 15, 1],
          'icon-allow-overlap': false, 'icon-padding': 6, 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 11,
          'text-offset': [0, 1.2], 'text-anchor': 'top', 'text-max-width': 9, 'text-optional': true, 'text-padding': 4,
          'symbol-sort-key': ['-', 0, ['+', prio, ['case', ['==', ['get', 'named'], 1], 1, 0]]] },
        paint: { 'text-color': '#1c1c1c', 'text-halo-color': '#fff', 'text-halo-width': 1.8, 'text-halo-blur': 0.3,
          'text-opacity': ['step', ['zoom'], 0, 12.5, 1] } }, 'radius-fill');
    }
  }
  paintNature();
  applyNatureVisibility();
}
export function applyNatureVisibility() {
  if (!mapReady) return;
  for (const id of [...NAT_LAYERS, 'bm-nat-peak-sym', 'bm-nat-peak-label']) {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', state.layers.nature ? 'visible' : 'none');
  }
  const med = !!state.layers.medieval;
  for (const id of NAT_LAYERS) {
    if (!map.getLayer(id)) continue;
    map.setLayoutProperty(id, 'icon-image', ['concat', med ? 'med-' : 'nat-', ['get', 'kind']]);
    map.setLayoutProperty(id, 'text-font', [med ? 'Grenze Gotisch Regular' : 'Noto Sans Regular']);
    map.setLayoutProperty(id, 'text-size', med ? 13 : 11);
    if (med) { map.setPaintProperty(id, 'text-color', MED.ink); map.setPaintProperty(id, 'text-halo-color', MED.halo); }
  }
  // Kultur: je Art ein Schalter; her-t1 (Burgen, Ruinen, Fundstellen, Klöster) filtert nach den eingeschalteten Arten, her-t2 sind die historischen Gebäude
  const herKinds = [...(state.layers.herCastle ? ['castle', 'ruins'] : []), ...(state.layers.herArch ? ['archaeological'] : []), ...(state.layers.herMonastery ? ['monastery'] : [])];
  if (map.getLayer('her-t1')) map.setFilter('her-t1', herKinds.length ? ['in', ['get', 'kind'], ['literal', herKinds]] : ['==', ['get', 'kind'], '']);
  for (const id of HER_LAYERS) {
    if (!map.getLayer(id)) continue;
    map.setLayoutProperty(id, 'visibility', (id === 'her-t1' ? herKinds.length > 0 : state.layers.herBuilding) ? 'visible' : 'none');
    // historische Karte: eigene Bildzeichen, Schrift und Tinte statt Plaketten
    map.setLayoutProperty(id, 'icon-image', ['concat', med ? 'med-' : 'nat-', ['get', 'kind']]);
    map.setLayoutProperty(id, 'text-font', [med ? 'Grenze Gotisch Regular' : 'Noto Sans Regular']);
    map.setLayoutProperty(id, 'text-size', med ? 13 : 11);
    map.setPaintProperty(id, 'text-color', med ? MED.ink : '#1c1c1c');
    map.setPaintProperty(id, 'text-halo-color', med ? MED.halo : '#fff');
  }
}
