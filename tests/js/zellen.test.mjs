// Tests für web/js/zellen.js: Zellenwahl, Laden, Verwerfen, Fehler je Zelle, Prüfsummen, Zusammenführen, Anreichern.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cellId, cellsInBounds, kindsForZoom, ZellenSpeicher, anreichern, ebenenBudget, warnbandAlsEreignisse, dichtePunkte } from '../../web/js/zellen.js';

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

test('Ebenenbudget: unter Zoom 8 nichts, bei Ortszoom alles', () => {
  assert.deepEqual(kindsForZoom(7.5), []);
  assert.deepEqual(kindsForZoom(8), ['events', 'gewaesser', 'umwelt']);
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

test('evict mit Arten wirft nicht mehr gebrauchte Arten derselben Zelle weg', async () => {
  const z = new ZellenSpeicher({ fetchJSON: async () => ({ sources: [], features: [feat('x')], stations: [] }) });
  z.setManifest(manifest({ 'z/1_1/events.json': 'a', 'z/1_1/gewaesser.json': 'b' }));
  await z.ensure(['1_1'], ['events', 'gewaesser']);
  assert.equal(z.evict(['1_1'], ['events']), 1);
  assert.equal(z.status().ok, 1);
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

test('Ebenenbudget: unter Zoom 9 ohne info, über der Grenze nach Stufe gekappt, Eingabe unverändert', () => {
  const mk = (rank) => ({ properties: { severity_rank: rank } });
  const fs = [mk(0), mk(1), mk(3), mk(2)];
  assert.deepEqual(ebenenBudget(fs, 8).map((f) => f.properties.severity_rank), [1, 3, 2]);
  assert.equal(ebenenBudget(fs, 12).length, 4);
  const viele = Array.from({ length: 1600 }, (_, i) => mk(i < 100 ? 3 : 1));
  const out = ebenenBudget(viele, 8);
  assert.equal(out.length, 1500);
  assert.equal(out.filter((f) => f.properties.severity_rank === 3).length, 100);
  assert.equal(fs.length, 4);
});

test('Warnband-Einträge werden zu Punkt-Ereignissen mit Entfernung, Alter und Markierung stub', () => {
  const wb = [{ id: 'n:1', title: 'T', severity: 'critical', type: 'flood', source_id: 'nina', source_short: 'NINA', valid_from: 'a', valid_to: null, lat: 49.85, lon: 6.45, region_tag: 'DE-RLP', ars: '07232', land: 'DE-RP' },
    { id: 'x', lat: null, lon: null }];
  const src = new Map([['nina', { name: 'NINA', last_success: '2026-10-10T10:00:00Z', status: 'ok', attribution: 'BBK' }]]);
  const out = warnbandAlsEreignisse(wb, src, Date.parse('2026-10-10T10:01:00Z'), { lat: 49.85, lon: 6.45 });
  assert.equal(out.length, 1);
  const p = out[0].properties;
  assert.equal(p.severity_rank, 3); assert.equal(p.distance_km, 0); assert.equal(p.age_s, 60); assert.equal(p.stub, true); assert.equal(p.ars, '07232');
});

test('Dichtepunkte: Zellmitte, Anzahl, höchste Stufe; leere Zellen entfallen', () => {
  const cells = { '12_99': { counts: { events: 5 }, bbox: [6, 49.5, 6.5, 50], max_severity: 'warning' }, '1_1': { counts: { events: 0 }, bbox: [0, 0, 0.5, 0.5] } };
  const out = dichtePunkte(cells);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].geometry.coordinates, [6.25, 49.75]);
  assert.equal(out[0].properties.n, 5); assert.equal(out[0].properties.sev, 'warning');
});
