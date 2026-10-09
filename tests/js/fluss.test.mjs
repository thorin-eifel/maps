// Tests für den reinen Teil von web/js/fluss.js (Richtung, Windklassen, Strichfolge). Aufruf: node tests/js/fluss.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { travelShift, waveSpec, waveKey, DASH_SEQ, IMPOUNDED } from '../../web/js/fluss.js';

test('Westwind zieht nach Osten (rechts), Nordwind nach Süden (unten)', () => {
  const w = travelShift(270); assert.deepEqual([w.a, w.b], [1, 0]);
  const n = travelShift(0); assert.deepEqual([n.a, n.b], [0, 1]);
  const s = travelShift(180); assert.deepEqual([s.a, s.b], [0, -1]);
});
test('Zwischenrichtungen bleiben ganzzahlige Gittervektoren und weichen höchstens 14 Grad ab', () => {
  for (let f = 0; f < 360; f += 5) {
    const t = travelShift(f);
    assert.ok(Number.isInteger(t.a) && Number.isInteger(t.b) && Math.abs(t.a) <= 2 && Math.abs(t.b) <= 2);
    assert.ok(t.cos > Math.cos(14 * Math.PI / 180), `Abweichung bei ${f}`);
  }
});
test('Windklassen', () => {
  assert.equal(waveSpec(null).cls, 'calm');
  assert.equal(waveSpec(0.3).cls, 'calm');
  assert.equal(waveSpec(2).cls, 'light');
  assert.equal(waveSpec(5).cls, 'moderate');
  assert.equal(waveSpec(12).cls, 'strong');
  assert.ok(waveSpec(12).crests > waveSpec(2).crests);
});
test('Schlüssel ändert sich nur bei Klassen- oder Richtungsstufe', () => {
  assert.equal(waveKey({ speed: 4, from: 270 }), waveKey({ speed: 5, from: 272 }));
  assert.notEqual(waveKey({ speed: 4, from: 270 }), waveKey({ speed: 4, from: 300 }));
  assert.notEqual(waveKey({ speed: 4, from: 270 }), waveKey({ speed: 8, from: 270 }));
  assert.equal(waveKey({ speed: 0.2, from: 10 }), waveKey({ speed: 0.1, from: 200 }));
  assert.equal(waveKey(null), 'none');
});
test('Strichfolge hat gleiche Periode (7 Einheiten) in jedem Schritt', () => {
  for (const s of DASH_SEQ) assert.equal(s.reduce((a, b) => a + b, 0), 7);
});
test('Gestaute Flüsse sind benannt', () => { assert.ok(IMPOUNDED.includes('Mosel') && IMPOUNDED.includes('Saar')); });
