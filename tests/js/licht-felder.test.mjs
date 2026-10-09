// Tests für den reinen Teil von web/js/licht-felder.js. Aufruf: node tests/js/licht-felder.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { MATERIAL, flowClass, encodeDir, decodeDir, flowSegments } from '../../web/js/licht-felder.js';

test('Wald schluckt und streut, Fels und Feld strahlen heller zurück, Feuchtgebiet glänzt', () => {
  assert.ok(MATERIAL.forest[0] < MATERIAL.meadow[0] && MATERIAL.meadow[0] < MATERIAL.farmland[0] && MATERIAL.farmland[0] < MATERIAL.bare_rock[0]);
  assert.ok(MATERIAL.forest[1] > MATERIAL.farmland[1]);
  assert.ok(MATERIAL.wetland[2] > MATERIAL.forest[2] && MATERIAL.wetland[2] > MATERIAL.meadow[2]);
  for (const m of Object.values(MATERIAL)) for (const v of m) assert.ok(v >= 0 && v <= 1);
});
test('Mosel und Saar sind gestaut (langsam), Bäche am schnellsten, Mosel breit', () => {
  assert.ok(flowClass('river', 'Mosel').speed < flowClass('river', 'Sauer').speed);
  assert.ok(flowClass('stream', 'x').speed > flowClass('river', 'Sauer').speed);
  assert.ok(flowClass('river', 'Mosel').width > flowClass('river', 'Sauer').width);
});
test('Richtungskodierung hin und zurück', () => {
  for (const [dx, dy] of [[1, 0], [0, 1], [-1, 0], [0, -1], [3, -4]]) {
    const [r, g] = encodeDir(dx, dy), [x, y] = decodeDir(r, g), l = Math.hypot(dx, dy);
    assert.ok(Math.abs(x - dx / l) < 0.02 && Math.abs(y - dy / l) < 0.02, `${dx},${dy}`);
  }
});
test('Linienstücke: nur Fließgewässer, Reihenfolge bleibt, Nullstücke fallen weg', () => {
  const f = (kind, name, coords) => ({ properties: { kind, name }, geometry: { type: 'LineString', coordinates: coords } });
  const segs = flowSegments([f('river', 'Sauer', [[6.4, 49.8], [6.41, 49.8], [6.41, 49.8]]), f('lake', 'See', [[6, 49], [6.1, 49]]), f('stream', 'x', [[6.5, 49.7], [6.5, 49.71]])]);
  assert.equal(segs.length, 2);
  assert.ok(segs[0].b[0] > segs[0].a[0]);      // nach Osten gezeichnet
  assert.ok(segs[1].b[1] < segs[1].a[1]);      // nach Norden = Mercator-y kleiner
});
