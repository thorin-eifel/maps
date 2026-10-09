// Tests für den reinen Teil von web/js/licht.js. Aufruf: node tests/js/licht.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { merc, tilePlan } from '../../web/js/licht.js';

test('Mercator: Greenwich/Äquator liegt in der Mitte, Irrel plausibel', () => {
  const [x, y] = merc(0, 0); assert.ok(Math.abs(x - 0.5) < 1e-12 && Math.abs(y - 0.5) < 1e-12);
  const [ix, iy] = merc(6.456, 49.846); assert.ok(ix > 0.517 && ix < 0.519 && iy > 0.33 && iy < 0.34);
});
test('Kachelplan: nie mehr als 48 Kacheln, Zoom nie über 12, deckt das Sichtfeld ab', () => {
  const [cx, cy] = merc(6.456, 49.846);
  for (const zoom of [6, 8, 10, 12, 14, 17]) {
    const half = 0.5 / (512 * 2 ** zoom) * 700;   // ca. 1400 px breit
    const p = tilePlan(cx - half, cy - half * 0.65, cx + half, cy + half * 0.65, zoom);
    assert.ok(p.nx * p.ny <= 48 || p.z === 6, `zoom ${zoom}: ${p.nx * p.ny}`);
    assert.ok(p.z <= 12 && p.z >= 6);
    const n = 2 ** p.z;
    assert.ok(p.tx0 / n <= cx - half && (p.tx0 + p.nx) / n >= cx + half, `Breite bei ${zoom}`);
    assert.ok(p.ty0 / n <= cy - half * 0.65 && (p.ty0 + p.ny) / n >= cy + half * 0.65, `Höhe bei ${zoom}`);
  }
});
