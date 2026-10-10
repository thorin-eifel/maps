// Tests für web/js/gebiet.js: Filterregel, Auswahllisten, Land/Kreis-Abgleich.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gebietPasst, gebietAktiv, laenderListe, kreiseListe, landWaehlen, kreisWaehlen, GEBIET_LEER } from '../../web/js/gebiet.js';

const kreise = [
  { ars: '07232', name: 'Eifelkreis Bitburg-Prüm', land: 'DE-RP' },
  { ars: '07211', name: 'Trier', land: 'DE-RP' },
  { ars: '10041', name: 'Regionalverband Saarbrücken', land: 'DE-SL' },
];

test('ohne Filter passt alles, auch Einträge ohne Angaben', () => {
  assert.ok(gebietPasst({}, GEBIET_LEER));
  assert.ok(!gebietAktiv(GEBIET_LEER));
});

test('Kreis zählt über ars, Land über land; Einträge ohne Angabe fallen bei gesetztem Filter heraus', () => {
  assert.ok(gebietPasst({ ars: '07232', land: 'DE-RP' }, { land: '', ars: '07232' }));
  assert.ok(!gebietPasst({ ars: '07211', land: 'DE-RP' }, { land: 'DE-RP', ars: '07232' }));
  assert.ok(gebietPasst({ ars: null, land: 'LU' }, { land: 'LU', ars: '' }));
  assert.ok(!gebietPasst({}, { land: 'DE-RP', ars: '' }));
});

test('Auswahllisten: Länder mit Nachbarn, Kreise nach Land und Name', () => {
  const l = laenderListe(kreise).map((x) => x[0]);
  assert.deepEqual(l.sort(), ['BE', 'DE-RP', 'DE-SL', 'FR', 'LU']);
  assert.deepEqual(kreiseListe(kreise, 'DE-RP').map((x) => x[1]), ['Eifelkreis Bitburg-Prüm', 'Trier']);
  assert.equal(kreiseListe(kreise, '').length, 3);
});

test('Land wechseln verwirft unpassenden Kreis, Kreis wählen setzt das Land', () => {
  assert.deepEqual(landWaehlen({ land: 'DE-RP', ars: '07232' }, 'DE-SL', kreise), { land: 'DE-SL', ars: '' });
  assert.deepEqual(landWaehlen({ land: 'DE-RP', ars: '07232' }, 'DE-RP', kreise), { land: 'DE-RP', ars: '07232' });
  assert.deepEqual(kreisWaehlen(GEBIET_LEER, '10041', kreise), { land: 'DE-SL', ars: '10041' });
  assert.deepEqual(kreisWaehlen({ land: 'DE-SL', ars: '10041' }, '', kreise), { land: 'DE-SL', ars: '' });
});
