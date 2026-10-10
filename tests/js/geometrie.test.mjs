// Kreis und Vignette der Lagekarte (web/js/lage/geometrie.js): rein, ohne DOM.
import test from 'node:test';
import assert from 'node:assert/strict';
import { circle, vignette, VIG_RINGS, VIG_FADE_KM, baseAnchor } from '../../web/js/lage/geometrie.js';

const km = (a, b) => {   // Haversine, unabhängig von der Implementierung
  const R = 6371.0088, rad = (x) => (x * Math.PI) / 180;
  const dLat = rad(b[1] - a[1]), dLon = rad(b[0] - a[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
};

test('Kreis: geschlossener Ring, alle Punkte im gewünschten Abstand', () => {
  const f = circle(49.85, 6.45, 50, 64);
  const ring = f.geometry.coordinates[0];
  assert.equal(ring.length, 65);
  assert.deepEqual(ring[0], ring[ring.length - 1]);
  for (const p of ring) assert.ok(Math.abs(km([6.45, 49.85], p) - 50) < 0.05, `Abstand ${km([6.45, 49.85], p)}`);
});

test('Vignette: Alpha steigt stufenlos von 0 auf 1, am Ende eine volle Fläche', () => {
  const v = vignette(49.85, 6.45, 120);
  assert.equal(v.features.length, VIG_RINGS + 1);
  const a = v.features.map((f) => f.properties.a);
  for (let i = 1; i < a.length; i++) assert.ok(a[i] >= a[i - 1], `nicht monoton bei ${i}`);
  assert.ok(a[0] < 0.001 && a[VIG_RINGS - 1] > 0.99 && a[VIG_RINGS] === 1);
  assert.ok(VIG_FADE_KM > 0);
});

test('Ankerebene heißt radius-fill (alle Datenebenen werden davor einsortiert)', () => {
  assert.equal(baseAnchor(), 'radius-fill');
});
