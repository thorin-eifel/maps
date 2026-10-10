// Tests für die reinen Funktionen des LGB-Menüs (web/js/lgb-katalog.js): Zoombereich, Kachel-URL, Ebenenbaum, Titel, Vermerk.
// Aufruf: node --test tests/js/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const mod = await import('../../web/js/lgb-katalog.js');
{
  const { zoomFuerNenner, zoomBereich, kachelUrl, flacheEbenen, kurzTitel, layerId, vermerk, MAX_AKTIV } = mod;
  const kat = JSON.parse(readFileSync(new URL('../../web/geo/lgb.json', import.meta.url)));

  test('Maßstab 1:559082264 ist Zoom 0, jede Halbierung ein Zoom mehr', () => {
    assert.ok(Math.abs(zoomFuerNenner(559082264.028)) < 1e-9);
    assert.ok(Math.abs(zoomFuerNenner(559082264.028 / 1024) - 10) < 1e-9);
  });
  test('Zoombereich aus Maßstabsgrenzen (1:1900 bis 1:10000000)', () => {
    const z = zoomBereich({ min_scale: 1900, max_scale: 10000000 });
    assert.ok(z.minzoom > 5 && z.minzoom < 6, String(z.minzoom));
    assert.ok(z.maxzoom > 18 && z.maxzoom < 19, String(z.maxzoom));
    assert.deepEqual(zoomBereich({}), {});
  });
  test('Kachel-URL: nur https und nur mapserver.lgb-rlp.de, Name kodiert, BBOX-Platzhalter', () => {
    const u = kachelUrl({ url: 'https://mapserver.lgb-rlp.de/cgi-bin/mc_erdbeben' }, 'Erdbeben ä&x');
    assert.match(u, /^https:\/\/mapserver\.lgb-rlp\.de\/cgi-bin\/mc_erdbeben\?SERVICE=WMS/);
    assert.match(u, /LAYERS=Erdbeben%20%C3%A4%26x&BBOX=\{bbox-epsg-3857\}$/);
    assert.match(u, /CRS=EPSG:3857/);
    assert.throws(() => kachelUrl({ url: 'https://example.org/wms' }, 'a'));
    assert.throws(() => kachelUrl({ url: 'http://mapserver.lgb-rlp.de/cgi-bin/x' }, 'a'));
  });
  test('Ebenenbaum wird flach, Ordnertitel bleiben als Pfad', () => {
    const f = flacheEbenen([{ title: 'A', name: 'a' }, { title: 'Ordner', children: [{ title: 'B', name: 'b' }] }]);
    assert.deepEqual(f.map((e) => [e.name, e.pfad.join('/')]), [['a', ''], ['b', 'Ordner']]);
  });
  test('Titel ohne Kürzel, Ebenen-ID ohne Sonderzeichen, Vermerk mit Jahr', () => {
    assert.equal(kurzTitel('GÜK300: Geologische Störungslinien'), 'Geologische Störungslinien');
    assert.equal(kurzTitel('Ohne Kürzel'), 'Ohne Kürzel');
    assert.match(layerId({ id: 'mc_x' }, 'A b/ä'), /^lgb-mc_x-[A-Za-z0-9_-]+$/);
    assert.equal(vermerk({ vermerk: '©LGB-RLP {jahr}, dl-de/by-2-0, www.lgb-rlp.de [Daten bearbeitet]' }, 2026), '©LGB-RLP 2026, dl-de/by-2-0, www.lgb-rlp.de [Daten bearbeitet]');
    assert.equal(MAX_AKTIV, 6);
  });
  test('Katalog: neun Themen wie auf der LGB-Seite, jeder Dienst auf mapserver.lgb-rlp.de, Ebenennamen eindeutig je Dienst', () => {
    assert.deepEqual(kat.groups.map((g) => g.title), ['Bergbau', 'Boden', 'Erdbeben', 'Geologiedatengesetz', 'Geologie', 'Geothermie', 'Hydrogeologie', 'Ingenieurgeologie', 'Rohstoffgeologie']);
    assert.equal(kat.lizenz, 'dl-de/by-2-0');
    for (const g of kat.groups) for (const s of g.services) {
      const ebenen = flacheEbenen(s.layers);
      assert.ok(ebenen.length > 0, s.id);
      assert.equal(new Set(ebenen.map((e) => e.name)).size, ebenen.length, `Namen doppelt in ${s.id}`);
      for (const e of ebenen) assert.doesNotThrow(() => kachelUrl(s, e.name));
      if (s.id === 'mc_erdbeben') assert.equal(ebenen.length, 6);
    }
    const alle = kat.groups.flatMap((g) => g.services.flatMap((s) => flacheEbenen(s.layers)));
    assert.equal(alle.length, 222);
  });
}

// ---- Katalog "Landesdaten" (web/geo/landesdaten.json) und mehrere erlaubte Server ----
{
  const { kachelUrl, flacheEbenen, layerId, vermerke } = mod;
  const lad = JSON.parse(readFileSync(new URL('../../web/geo/landesdaten.json', import.meta.url)));
  const html = readFileSync(new URL('../../web/index.html', import.meta.url), 'utf8');
  const htaccess = readFileSync(new URL('../../web/.htaccess', import.meta.url), 'utf8');

  test('Kachel-URL mit erlaubter Serverliste: fremde Server und http werden abgelehnt, vorhandene Parameter bleiben', () => {
    const hosts = ['geo4.service24.rlp.de'];
    const u = kachelUrl({ url: 'https://geo4.service24.rlp.de/wms/x.fcgi?map=/data/a.map' }, 'e', hosts);
    assert.match(u, /^https:\/\/geo4\.service24\.rlp\.de\/wms\/x\.fcgi\?map=\/data\/a\.map&SERVICE=WMS/);
    assert.throws(() => kachelUrl({ url: 'https://geo5.service24.rlp.de/wms/x' }, 'e', hosts));
    assert.throws(() => kachelUrl({ url: 'http://geo4.service24.rlp.de/wms/x' }, 'e', hosts));
    assert.throws(() => kachelUrl({ url: 'https://mapserver.lgb-rlp.de/cgi-bin/x' }, 'e', hosts));
  });
  test('Ebenen-ID mit Vorsatz, Vermerke ohne Dubletten', () => {
    assert.match(layerId({ id: 'gp12' }, 'a b', 'lad'), /^lad-gp12-a_b$/);
    const v = vermerke([{ vermerk: '©A {jahr}, x' }, { vermerk: '©A {jahr}, x' }, { vermerk: '©B {jahr}, y' }], { vermerk: '©K {jahr}' }, 2026);
    assert.deepEqual(v, ['©A 2026, x', '©B 2026, y']);
    assert.deepEqual(vermerke([{}], { vermerk: '©K {jahr}' }, 2026), ['©K 2026']);
  });
  test('Landesdaten: jeder Dienst auf einem Server aus `hosts`, mit Lizenz und Vermerk, Ebenennamen eindeutig, IDs eindeutig', () => {
    assert.equal(lad.lizenz_geprueft, false);
    assert.ok(lad.hosts.length > 0 && lad.groups.length > 0);
    const ids = new Set();
    for (const g of lad.groups) for (const s of g.services) {
      assert.ok(!ids.has(s.id), `Dienst doppelt: ${s.id}`); ids.add(s.id);
      assert.ok(s.lizenz && s.betreiber && s.vermerk.includes('{jahr}'), s.id);
      const e = flacheEbenen(s.layers);
      assert.ok(e.length > 0, s.id);
      assert.equal(new Set(e.map((x) => x.name)).size, e.length, `Namen doppelt in ${s.id}`);
      for (const x of e) assert.doesNotThrow(() => kachelUrl(s, x.name, lad.hosts), s.id);
    }
  });
  test('Jeder Server des Katalogs steht in der CSP von index.html und .htaccess (img-src und connect-src)', () => {
    for (const quelle of [html, htaccess]) {
      for (const dir of ['img-src', 'connect-src']) {
        const teil = quelle.match(new RegExp(`${dir}[^;]*`))[0];
        for (const h of lad.hosts) assert.ok(teil.includes(`https://${h}`), `${h} fehlt in ${dir}`);
      }
    }
  });
  test('Seite hat beide Menüs mit allen Elementen', () => {
    for (const v of ['lgb', 'lad']) for (const id of ['gruppe', 'hinweis', 'ok', 'nein', 'deckkraft', 'aus', 'status', 'menu', 'vermerk']) assert.ok(html.includes(`id="${v}-${id}"`), `${v}-${id}`);
  });
}
