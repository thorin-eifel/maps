import test from 'node:test';
import assert from 'node:assert/strict';
import { sortEvents, filterEvents } from '../../web/js/eventlist.js';

const f = (id, severity_rank, distance_km, type = 'traffic', extra = {}) => ({ properties: { id, severity_rank, distance_km, type, title: id, ...extra } });
const DATA = [f('a', 1, 5), f('b', 3, 40), f('c', 3, 10), f('d', 0, 1), f('e', 2, 2, 'flood')];

test('Standard: Schwere absteigend, dann Entfernung', () => {
  assert.deepEqual(sortEvents(DATA).map((x) => x.properties.id), ['c', 'b', 'e', 'a', 'd']);
});
test('Sortierung nach Entfernung, Gleichstand nach Schwere', () => {
  const d = [f('x', 1, 5), f('y', 3, 5), f('z', 0, 2)];
  assert.deepEqual(sortEvents(d, 'dist').map((x) => x.properties.id), ['z', 'y', 'x']);
});
test('reverse dreht um, Eingabe bleibt unverändert', () => {
  const copy = DATA.map((x) => x.properties.id);
  assert.deepEqual(sortEvents(DATA, 'dist', true).map((x) => x.properties.id), ['b', 'c', 'a', 'e', 'd']);
  assert.deepEqual(DATA.map((x) => x.properties.id), copy);
});
test('fehlende Entfernung landet hinten, unbekannter Schlüssel = prio', () => {
  const d = [f('n', 1, undefined), f('m', 1, 3)];
  assert.deepEqual(sortEvents(d, 'nope').map((x) => x.properties.id), ['m', 'n']);
});
test('Alter: neueste zuerst', () => {
  const d = [f('o', 1, 1, 'traffic', { valid_from: '2026-09-30T08:00:00Z' }), f('n', 1, 9, 'traffic', { valid_from: '2026-09-30T10:00:00Z' })];
  assert.deepEqual(sortEvents(d, 'age').map((x) => x.properties.id), ['n', 'o']);
});
test('Filter: Mindeststufe, Typ, Radius, Text kombiniert', () => {
  assert.deepEqual(filterEvents(DATA, { minSev: 2 }).map((x) => x.properties.id), ['b', 'c', 'e']);
  assert.deepEqual(filterEvents(DATA, { type: 'flood' }).map((x) => x.properties.id), ['e']);
  assert.deepEqual(filterEvents(DATA, { maxKm: 10 }).map((x) => x.properties.id), ['a', 'c', 'd', 'e']);
  assert.deepEqual(filterEvents(DATA, { minSev: 3, maxKm: 20 }).map((x) => x.properties.id), ['c']);
  const t = [f('A64 Sperrung', 2, 3, 'traffic', { title: 'A64 Sperrung' }), f('x', 2, 3, 'traffic', { title: 'Ampel' })];
  assert.deepEqual(filterEvents(t, { q: ' a64 ' }).map((x) => x.properties.id), ['A64 Sperrung']);
});
