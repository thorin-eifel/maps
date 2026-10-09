import test from 'node:test';
import assert from 'node:assert/strict';
import { waterName, sortStations } from '../../web/js/pegel.js';

test('Gewässernamen: Artikel weg, Französisch auf Deutsch, leer bleibt leer', () => {
  assert.equal(waterName('La Moselle'), 'Mosel');
  assert.equal(waterName('Mosel'), 'Mosel');
  assert.equal(waterName("L'Orne"), 'Orne');
  assert.equal(waterName('La Sarre'), 'Saar');
  assert.equal(waterName('Ruisseau de Vaux'), 'Vaux');
  assert.equal(waterName('Ruisseau le Woigot'), 'Woigot');
  assert.equal(waterName('  '), null);
  assert.equal(waterName(null), null);
});

test('Sortierung: Gewässer alphabetisch, darin Stationen alphabetisch, ohne Gewässer zuletzt', () => {
  const s = [
    { name: 'Wasserbillig', water: 'Sauer', station_id: '4' }, { name: 'Trier', water: 'Mosel', station_id: '1' },
    { name: 'Uckange', water: 'La Moselle', station_id: '5' }, { name: 'Ärmelkanal', water: null, station_id: '9' },
    { name: 'Bollendorf', water: 'Sauer', station_id: '3' }, { name: 'Cochem', water: 'Mosel', station_id: '2' },
    { name: 'Échternach', water: 'Sauer', station_id: '6' },
  ];
  const out = sortStations(s).map((x) => `${x.water_label}/${x.name}`);
  assert.deepEqual(out, ['Mosel/Cochem', 'Mosel/Trier', 'Mosel/Uckange', 'Sauer/Bollendorf', 'Sauer/Échternach', 'Sauer/Wasserbillig', 'null/Ärmelkanal']);
});

test('Sortierung verändert die Eingabe nicht und ist stabil bei gleichen Namen', () => {
  const s = [{ name: 'A', water: 'Our', station_id: '2' }, { name: 'A', water: 'Our', station_id: '1' }];
  const copy = JSON.stringify(s);
  assert.deepEqual(sortStations(s).map((x) => x.station_id), ['1', '2']);
  assert.equal(JSON.stringify(s), copy);
});

test('Sammelgruppe "Kommunale Messstelle" steht nach den Flüssen, vor "ohne Angabe"', () => {
  const s = [{ name: 'Z', water: null, station_id: '1' }, { name: 'B', water: 'Kommunale Messstelle', station_id: '2' },
    { name: 'C', water: 'Zorn', station_id: '3' }, { name: 'A', water: 'Mosel', station_id: '4' }];
  assert.deepEqual(sortStations(s).map((x) => x.name), ['A', 'C', 'B', 'Z']);
});

import { buildTree, distKm } from '../../web/js/pegel.js';

const NET = {
  map: { 'p|Mosel': 'M', 'p|Sauer': 'S', 'p|Our': 'O', 'h|Kyll': 'K', 'w|Maas': 'X' },
  rivers: {
    R: { name: 'Rhein', parent: null, mouth: [51.98, 4.09], src: null },
    M: { name: 'Mosel', parent: 'R', mouth: [50.36, 7.6], src: null },
    S: { name: 'Sauer', parent: 'M', mouth: [49.71, 6.49], src: null },
    O: { name: 'Our', parent: 'S', mouth: [49.88, 6.39], src: null },
    K: { name: 'Kyll', parent: 'M', mouth: [49.8, 6.69], src: null },
    X: { name: 'Maas', parent: null, mouth: [51.8, 4.6], src: null },
  },
};
const st = (id, source_id, water, name, lat, lon) => ({ station_id: id, source_id, water, water_label: water, name, lat, lon, latest: { value: 1 } });

test('Baum: Strom → Fluss → Bach, Stationen und Zuflüsse von der Mündung zur Quelle', () => {
  const t = buildTree([
    st('1', 'p', 'Mosel', 'Cochem', 50.15, 7.17), st('2', 'p', 'Mosel', 'Trier', 49.75, 6.64), st('3', 'p', 'Sauer', 'Wasserbillig', 49.71, 6.5),
    st('4', 'p', 'Our', 'Dasburg', 50.0, 6.2), st('5', 'h', 'Kyll', 'Kordel', 49.8, 6.7),
  ], NET);
  assert.deepEqual(t.roots.map((r) => r.name), ['Rhein']);
  const mosel = t.roots[0].items[0];
  assert.equal(mosel.name, 'Mosel');
  assert.equal(mosel.total, 5);
  // Koblenz → Cochem → Kyll-Mündung (liegt unterhalb von Trier) → Trier → Sauer-Mündung bei Wasserbillig
  const names = mosel.items.map((i) => i.name);
  assert.deepEqual(names, ['Cochem', 'Kyll', 'Trier', 'Sauer']);
  const sauer = mosel.items.find((i) => i.name === 'Sauer');
  assert.deepEqual(sauer.items.map((i) => i.name), ['Wasserbillig', 'Our']);
});

test('Baum: Unbekanntes bleibt offen, ohne Gewässer getrennt, leere Äste fallen weg', () => {
  const t = buildTree([st('1', 'p', 'Mühlbach', 'Irgendwo', 50, 7), { ...st('2', 'p', null, 'Ohne', 50, 7), water_label: null }], NET);
  assert.equal(t.roots.length, 0);
  assert.equal(t.open.groups[0].label, 'Mühlbach');
  assert.equal(t.none.length, 1);
  assert.deepEqual(buildTree([], null).roots, []);
});

test('Baum: Fluss ohne Mündungspunkt, aber mit Quelle: von weit nach nah an der Quelle', () => {
  const net = { map: { 'p|Lahn': 'L' }, rivers: { L: { name: 'Lahn', parent: null, mouth: null, src: [50.89, 8.24] } } };
  const t = buildTree([st('1', 'p', 'Lahn', 'Nah Quelle', 50.8, 8.2), st('2', 'p', 'Lahn', 'Mündung', 50.3, 7.6)], net);
  assert.deepEqual(t.roots[0].items.map((i) => i.name), ['Mündung', 'Nah Quelle']);
});

test('Entfernung Trier–Luxemburg ungefähr 47 km', () => {
  assert.ok(Math.abs(distKm([49.75, 6.64], [49.61, 6.13]) - 40) < 10);
});

import { stationRank } from '../../web/js/pegel.js';
test('Kartenrang: Strom 0, Zufluss 1, tiefer wächst, unbekannt 4, ohne Netz 2', () => {
  assert.equal(stationRank({ source_id: 'p', water: 'Mosel' }, NET), 1);
  assert.equal(stationRank({ source_id: 'p', water: 'Our' }, NET), 3);
  assert.equal(stationRank({ source_id: 'w', water: 'Maas' }, NET), 0);
  assert.equal(stationRank({ source_id: 'p', water: 'Unbekannt' }, NET), 4);
  assert.equal(stationRank({ source_id: 'p', water: 'Mosel' }, null), 2);
});
