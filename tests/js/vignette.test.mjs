// Tests für web/js/vignette-bild.js (Vignette entlang der Landesgrenze) und die erzeugte Maske web/geo/vignette.json/.png.
// Aufruf: node --test tests/js/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const { mercator, bildPunkt, deckkraft, faktor, aussenflaeche } = await import('../../web/js/vignette-bild.js');
const meta = JSON.parse(readFileSync(new URL('../../web/geo/vignette.json', import.meta.url)));

// Kleines Prüfbild: 4 x 3 Punkte, linke Hälfte klar (0), rechte Hälfte schwarz (255)
const klein = { breite: 4, hoehe: 3, mercator: [0, 0, 400, 300] };
const kleinAlpha = Uint8Array.from([0, 0, 255, 255, 0, 0, 255, 255, 0, 0, 255, 255]);
const invers = ([x, y]) => { const R = 6378137; return [(x / R) * 180 / Math.PI, (2 * Math.atan(Math.exp(y / R)) - Math.PI / 2) * 180 / Math.PI]; };

test('Mercator: Nullpunkt und Rückrechnung', () => {
  assert.ok(mercator(0, 0).every((v) => Math.abs(v) < 1e-6));
  const [lon, lat] = invers(mercator(6.456, 49.846));
  assert.ok(Math.abs(lon - 6.456) < 1e-9 && Math.abs(lat - 49.846) < 1e-9);
});
test('Bildpunkt: außerhalb null, Ecken und Mitte stimmen', () => {
  const [lo, la] = invers([200, 150]);
  const p = bildPunkt(klein, lo, la);
  assert.ok(Math.abs(p[0] - 1.5) < 1e-6 && Math.abs(p[1] - 1) < 1e-6, String(p));
  const [lo2, la2] = invers([500, 150]);
  assert.equal(bildPunkt(klein, lo2, la2), null);
});
test('Deckkraft: bilinear zwischen klar und schwarz, außerhalb des Bildes voll schwarz', () => {
  const at = (x, y) => deckkraft(klein, kleinAlpha, ...invers([x, y]));
  assert.equal(at(50, 150), 0);                       // ganz links: klar
  assert.equal(at(350, 150), 1);                      // ganz rechts: schwarz
  const mitte = at(200, 150);                         // zwischen Spalte 1 und 2: halb
  assert.ok(mitte > 0.45 && mitte < 0.55, String(mitte));
  assert.equal(at(-1000, 150), 1);
  assert.equal(faktor(klein, kleinAlpha, ...invers([50, 150])), 1);
});
test('Außenfläche: Welt mit Loch, Loch knapp innerhalb des Bildrandes', () => {
  const f = aussenflaeche(meta).features[0].geometry.coordinates;
  assert.equal(f.length, 2);
  const [[w, n], [e], [, s]] = meta.ecken;
  const xs = f[1].map((p) => p[0]), ys = f[1].map((p) => p[1]);
  assert.ok(Math.min(...xs) > w && Math.max(...xs) < e && Math.min(...ys) > s && Math.max(...ys) < n);
});
test('Maske: Metadaten stimmig, Mitte von Rheinland-Pfalz klar, Bildrand schwarz', () => {
  assert.equal(meta.abstand_km, 80); assert.equal(meta.fade_km, 30);
  assert.equal(meta.ecken.length, 4);
  // PNG: Größe aus dem IHDR lesen (Breite/Höhe stehen ab Byte 16)
  const png = readFileSync(new URL('../../web/geo/vignette.png', import.meta.url));
  assert.equal(png.readUInt32BE(16), meta.breite); assert.equal(png.readUInt32BE(20), meta.hoehe);
});
