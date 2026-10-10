// Tests für web/js/zellen.js: Zellenwahl, Laden, Verwerfen, Fehler je Zelle, Prüfsummen, Zusammenführen, Anreichern.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cellId, cellsInBounds, kindsForZoom, ZellenSpeicher, anreichern } from '../../web/js/zellen.js';

const manifest = (files) => ({ cells: [...new Set(Object.keys(files).map((r) => r.split('/')[1]))], files: Object.fromEntries(Object.entries(files).map(([r, sha]) => [r, { sha256: sha }])) });
const feat = (id, cell) => ({ type: 'Feature', id, geometry: { type: 'Point', coordinates: [0, 0] }, properties: { id, source_id: 'nina' } });

test('Zellkennung: Irrel in 12_99, Kante gehört zur höheren Zelle', () => {
  assert.equal(cellId(6.45, 49.85), '12_99');
  assert.equal(cellId(6.5, 49.7), '13_99');
});

test('cellsInBounds liefert Ausschnitt plus Rand', () => {
  const ids = cellsInBounds({ w: 6.1, s: 49.6, e: 6.4, n: 49.9 }, 0);
  assert.deepEqual(ids.sort(), ['12_99']);
  assert.equal(cellsInBounds({ w: 6.1, s: 49.6, e: 6.4, n: 49.9 }, 1).length, 9);
});

test('Ebenenbudget: bei Landeszoom keine Messstellen, bei Ortszoom alles', () => {
  assert.deepEqual(kindsForZoom(6), ['events']);
  assert.ok(!kindsForZoom(8).includes('haltestellen'));
  assert.equal(kindsForZoom(15).length, 10);
});

test('ensure lädt nur Dateien aus dem Manifest, begrenzt parallel, und merged entfernt Dubletten über Zellkanten', async () => {
  const calls = []; let live = 0, peak = 0;
  const fetchJSON = async (p) => {
    calls.push(p); live++; peak = Math.max(peak, live); await new Promise((r) => setTimeout(r, 5)); live--;
    const cell = p.split('/')[2];
    return { kind: 'events', cell, sources: [{ id: 'nina' }], features: [feat('a'), feat(`nur-${cell}`)] };
  };
  const z = new ZellenSpeicher({ fetchJSON, parallel: 2 });
  z.setManifest(manifest({ 'z/1_1/events.json': 'x', 'z/1_2/events.json': 'y', 'z/1_3/events.json': 'z' }));
  await z.ensure(['1_1', '1_2', '1_3', '9_9'], ['events', 'gewaesser']);
  assert.equal(calls.length, 3);
  assert.ok(peak <= 2);
  const m = z.merged('events');
  assert.equal(m.features.length, 4);              // 'a' nur einmal
  assert.equal(m.type, 'FeatureCollection');
  assert.equal(m.source.id, 'nina');
});

test('unveränderte Prüfsumme: kein zweiter Abruf; geänderte Prüfsumme: neuer Abruf, alte Daten bleiben bis dahin', async () => {
  let n = 0;
  const fetchJSON = async () => ({ sources: [], features: [feat(`v${++n}`)] });
  const z = new ZellenSpeicher({ fetchJSON });
  z.setManifest(manifest({ 'z/1_1/events.json': 'a' }));
  await z.ensure(['1_1'], ['events']); await z.ensure(['1_1'], ['events']);
  assert.equal(n, 1);
  z.setManifest(manifest({ 'z/1_1/events.json': 'b' }));
  await z.ensure(['1_1'], ['events']);
  assert.equal(n, 2);
  assert.equal(z.merged('events').features[0].id, 'v2');
});

test('Fehler in einer Zelle lässt die anderen stehen, wird gemeldet und erst nach Wartezeit wiederholt', async () => {
  let t = 0, bad = true;
  const fetchJSON = async (p) => { if (p.includes('1_2') && bad) throw new Error('HTTP 503'); return { sources: [], features: [feat(p)] }; };
  const z = new ZellenSpeicher({ fetchJSON, retryMs: 1000, now: () => t });
  z.setManifest(manifest({ 'z/1_1/events.json': 'a', 'z/1_2/events.json': 'b' }));
  await z.ensure(['1_1', '1_2'], ['events']);
  let s = z.status();
  assert.equal(s.ok, 1); assert.equal(s.error, 1); assert.match(s.errors[0].err, /503/);
  assert.equal(z.merged('events').features.length, 1);
  bad = false; t = 500; await z.ensure(['1_2'], ['events']);
  assert.equal(z.status().error, 1);                // noch in der Wartezeit
  t = 2000; await z.ensure(['1_2'], ['events']);
  assert.equal(z.status().error, 0); assert.equal(z.merged('events').features.length, 2);
});

test('evict verwirft entfernte Zellen und behält die gewünschten', async () => {
  const z = new ZellenSpeicher({ fetchJSON: async (p) => ({ sources: [], features: [feat(p)] }) });
  z.setManifest(manifest({ 'z/1_1/events.json': 'a', 'z/5_5/events.json': 'b' }));
  await z.ensure(['1_1', '5_5'], ['events']);
  assert.equal(z.evict(['1_1']), 1);
  assert.equal(z.status().cells, 1);
  assert.equal(z.merged('events').features.length, 1);
});

test('anreichern setzt Abruf, Status und Alter aus dem Startpaket und lässt das Original unverändert', () => {
  const p = { sources: [{ id: 'nina' }], features: [{ properties: { source_id: 'nina' } }, { properties: { source_id: 'fremd' } }] };
  const src = new Map([['nina', { last_success: '2026-10-10T10:00:00Z', status: 'ok' }]]);
  const out = anreichern('events', p, src, Date.parse('2026-10-10T10:05:00Z'));
  assert.equal(out.features[0].properties.age_s, 300);
  assert.equal(out.features[0].properties.source_status, 'ok');
  assert.equal(out.features[1].properties.source_status, 'unknown');
  assert.equal(out.features[1].properties.fetched_at, null);
  assert.equal(p.features[0].properties.age_s, undefined);
});
