import test from 'node:test';
import assert from 'node:assert/strict';
import { fold, mergeIndex, search, zoomFor } from '../../web/js/suche.js';

const geo = { v: 1, t: ['Stadt', 'Ort', 'Straße', 'Bach'], o: ['Irrel', 'Trier'], e: [
  ['Trier', 0, 497500, 66400, -1], ['Trierer Straße', 2, 498000, 64000, 0], ['Irrel', 1, 498500, 64500, -1],
  ['Hauptstraße', 2, 498400, 64400, 0], ['Hauptstraße', 2, 497600, 66000, 1], ['Prüm', 3, 498600, 64600, 0], ['Straße der Überlegung', 2, 498000, 64000, 0], ['40', 1, 498000, 64000, -1]] };

test('fold: Umlaute, ß, Satzzeichen', () => {
  assert.equal(fold('Straße der Überlegung'), 'strasse der uberlegung');
  assert.equal(fold('Saint-Rémy  (L 65)'), 'saint remy l 65');
});
test('mergeIndex: ungültige Teile und Zeilen werden übergangen', () => {
  assert.equal(mergeIndex([null, { v: 2, e: [], t: [] }, geo]).length, 8);
  assert.equal(mergeIndex([{ v: 1, t: ['Ort'], o: [], e: [['x', 0, 'a', 1, -1], 'kaputt', null] }]).length, 0);
});
test('search: Wortanfänge, Güte vor Typ', () => {
  const idx = mergeIndex([geo]);
  assert.deepEqual(search(idx, 'trier').map((e) => e.name), ['Trier', 'Trierer Straße']);
  assert.equal(search(idx, 'ueberlegung').length, 0);               // ü wird zu u, nicht zu ue
  assert.equal(search(idx, 'uberlegung')[0].name, 'Straße der Überlegung');
  assert.equal(search(idx, 'str uber')[0].name, 'Straße der Überlegung');
  assert.equal(search(idx, 't').length, 0);                         // zu kurz
});
test('search: gleiche Namen nach Nähe, Ort bleibt erhalten', () => {
  const idx = mergeIndex([geo]);
  const r = search(idx, 'hauptstrasse', { lat: 49.76, lon: 6.6 });
  assert.equal(r[0].ort, 'Trier');
  assert.equal(search(idx, 'hauptstrasse', { lat: 49.85, lon: 6.45 })[0].ort, 'Irrel');
});
test('zoomFor: Stadt weiter weg als Straße', () => { assert.ok(zoomFor('Stadt') < zoomFor('Straße')); });
