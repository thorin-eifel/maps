// node --test tests/js/
import test from 'node:test';
import assert from 'node:assert/strict';
import { windowFilter, deriveStatus, overall, exportStale, exportAgeMin, iconFor, trafficLevel, advance } from '../../web/js/rules.js';

const NOW = Date.parse('2026-09-29T12:00:00Z');
const H = 3600 * 1000;
const iso = (offsetH) => new Date(NOW + offsetH * H).toISOString();
const f = (id, from, to, seen = iso(-5)) => ({ properties: { id, valid_from: from, valid_to: to, first_seen: seen } });

test('Zeitfenster: jetzt / 24 Std. / 7 Tage', () => {
  const feats = [
    f('jetzt', iso(-1), null), f('morgen', iso(20), null), f('woche', iso(120), null),
    f('spaeter', iso(240), null), f('abgelaufen', iso(-72), iso(-24)), f('ohne-start', null, null),
  ];
  const ids = (w) => windowFilter(feats, w, NOW).map((x) => x.properties.id).sort();
  assert.deepEqual(ids('now'), ['jetzt', 'ohne-start']);
  assert.deepEqual(ids('24h'), ['jetzt', 'morgen', 'ohne-start']);
  assert.deepEqual(ids('7d'), ['jetzt', 'morgen', 'ohne-start', 'woche']);
});

const base = { interval_s: 600, consecutive_failures: 0, last_attempt: iso(-0.1), last_success: iso(-0.1), status: 'ok' };
test('Quellenzustand', () => {
  assert.equal(deriveStatus(base, NOW).status, 'ok');
  assert.equal(deriveStatus({ ...base, consecutive_failures: 1 }, NOW).status, 'degraded');
  assert.equal(deriveStatus({ ...base, consecutive_failures: 3 }, NOW).status, 'down');
  assert.equal(deriveStatus({ ...base, last_success: null }, NOW).status, 'down');
  assert.equal(deriveStatus({ ...base, last_success: null, last_attempt: null }, NOW).status, 'pending');
  assert.equal(deriveStatus({ ...base, status: 'disabled' }, NOW).status, 'disabled');
});

test('Veralterung wird gegen die Uhr des Betrachters gerechnet, nicht gegen den Exportzeitpunkt', () => {
  // Export sagt „ok“, ist aber zwei Stunden alt und das Intervall beträgt 10 Minuten → stale
  const src = { ...base, last_success: iso(-2), status: 'ok' };
  assert.equal(deriveStatus(src, NOW).status, 'stale');
  assert.equal(overall([deriveStatus(base, NOW), deriveStatus(src, NOW)]), 'stale');
});

test('Export-Alter', () => {
  assert.equal(exportStale(iso(-0.1), NOW), false);
  assert.equal(exportStale(iso(-0.5), NOW), true);
  assert.equal(exportAgeMin(null, NOW), Infinity);
  assert.equal(exportStale(null, NOW), true);
});

test('Symbolwahl je Ereignisart', () => {
  assert.equal(iconFor({ type: 'aircraft' }), 'flug');
  assert.equal(iconFor({ type: 'congestion', attrs: { kind: 'zaehfliessend' } }), 'stau');
  assert.equal(iconFor({ type: 'traffic', attrs: { kind: 'baustelle' } }), 'baustelle');
  assert.equal(iconFor({ type: 'traffic', attrs: { kind: 'sperrung' } }), 'sperrung');
  assert.equal(iconFor({ type: 'traffic' }), 'warnung');
  assert.equal(iconFor({ type: 'flood' }), 'hochwasser');
  assert.equal(iconFor({ type: 'weather' }), 'warnung');
  assert.equal(iconFor({ type: 'radiation' }), 'strahlung');
  assert.equal(iconFor({ type: 'air' }), 'luft');
  assert.equal(iconFor({ type: 'earthquake' }), 'beben');
});

test('Flugzeug rückt entlang des Kurses weiter', () => {
  const [lon, lat] = advance(6.45, 49.85, 90, 360, 10); // 1 km nach Osten
  assert.ok(Math.abs(lat - 49.85) < 1e-3);
  const km = (lon - 6.45) * 111.32 * Math.cos((49.85 * Math.PI) / 180);
  assert.ok(Math.abs(km - 1) < 0.02, `km=${km}`);
  const [, lat2] = advance(6.45, 49.85, 0, 360, 10); // nach Norden: ≈ 1 km = 0,009°
  assert.ok(Math.abs(lat2 - 49.85 - 0.009) < 0.0005);
  assert.deepEqual(advance(6.45, 49.85, null, 360, 10), [6.45, 49.85]); // ohne Kurs bleibt es stehen
  assert.deepEqual(advance(6.45, 49.85, 90, 360, 0), [6.45, 49.85]);
});

test('Verkehrsstufen: gelb, orange, rot, schwarz', () => {
  const t = (type, severity, attrs) => trafficLevel({ type, severity, attrs });
  assert.equal(t('traffic', 'info', { kind: 'baustelle' }), 'yellow');
  assert.equal(t('traffic', 'notice', { kind: 'baustelle' }), 'orange');
  assert.equal(t('congestion', 'notice', { kind: 'zaehfliessend' }), 'orange');
  assert.equal(t('congestion', 'warning', { kind: 'stau', delay_min: 35 }), 'red');
  assert.equal(t('traffic', 'warning', { kind: 'sperrung', sperr: 'richtung' }), 'red');
  assert.equal(t('traffic', 'warning', { kind: 'sperrung', sperr: 'voll' }), 'black');
  assert.equal(t('traffic', 'warning', { kind: 'sperrung' }), 'black');
  assert.equal(t('flood', 'warning', {}), null);
});

test('iconFor: Brandverdacht bekommt das Feuer-Symbol', () => {
  assert.equal(iconFor({ type: 'fire', attrs: { kind: 'brand' } }), 'feuer');
});

test('trafficLevel: ÖPNV nach Verspätung, Ausfall und Störung', () => {
  const t = (attrs, severity = 'info') => trafficLevel({ type: 'transit', severity, attrs });
  assert.equal(t({ kind: 'verspaetung', delay_min: 6 }), 'yellow');
  assert.equal(t({ kind: 'verspaetung', delay_min: 12 }), 'orange');
  assert.equal(t({ kind: 'verspaetung', delay_min: 25 }), 'red');
  assert.equal(t({ kind: 'ausfall' }, 'notice'), 'red');
  assert.equal(t({ kind: 'stoerung' }, 'warning'), 'red');
  assert.equal(t({ kind: 'stoerung' }, 'notice'), 'orange');
  assert.equal(iconFor({ type: 'transit' }), 'bahn');
});
