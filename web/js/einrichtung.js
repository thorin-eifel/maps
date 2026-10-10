// Ersteinrichtung der Desktop-App: Mittelpunkt wählen, Fortschritt zeigen, danach zur Karte. Spricht nur mit dem lokalen Dienst (api/…).
const $ = (id) => document.getElementById(id);
let wahl = null;
let hintergrund = null;

async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-OSINT': '1' }, body: JSON.stringify(body) } : undefined);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Fehler ${r.status}`);
  return j;
}
const fehler = (t) => { $('fehler').textContent = t || ''; };

function pick(name, lat, lon) {
  wahl = { name, lat, lon };
  $('wahl').textContent = `Mittelpunkt: ${name || 'eigener Punkt'} (${lat.toFixed(4)} N, ${lon.toFixed(4)} E)`;
  $('schritt2').hidden = false; $('los').focus();
  zeigeWahl(lat, lon);
}

// Gewählter Ort auf dem Hintergrund: Punkt, Kamera rechts neben die Karten gerückt, damit er nicht dahinter liegt. Ohne Hintergrundkarte passiert nichts.
function zeigeWahl(lat, lon) {
  const m = hintergrund;
  if (!m) return;
  const punkt = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [lon, lat] } }] };
  const setze = () => {
    if (m.getSource('wahl')) m.getSource('wahl').setData(punkt);
    else {
      m.addSource('wahl', { type: 'geojson', data: punkt });
      m.addLayer({ id: 'wahl', type: 'circle', source: 'wahl', paint: { 'circle-radius': 7, 'circle-color': '#b3261e', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 } });
    }
    m.flyTo({ center: [lon, lat], zoom: 5.4, duration: 2000, offset: [window.innerWidth > 900 ? Math.min(window.innerWidth * 0.3, 420) : 0, 0] });   // bei reduzierter Bewegung ohne Flug
  };
  if (m.loaded()) setze(); else m.once('load', setze);
}

$('suche').addEventListener('submit', async (e) => {
  e.preventDefault(); fehler('');
  const ul = $('treffer'); ul.replaceChildren();
  try {
    const { results } = await api(`api/geocode?q=${encodeURIComponent($('q').value)}`);
    if (!results.length) fehler('Kein Ort gefunden.');
    for (const r of results) {
      const li = document.createElement('li'), b = document.createElement('button');
      b.type = 'button'; b.className = 'btn'; b.textContent = r.name;
      b.addEventListener('click', () => pick(r.name.split(',')[0], r.lat, r.lon));
      li.append(b); ul.append(li);
    }
  } catch (err) { fehler(`Ortssuche nicht erreichbar. Koordinaten kannst du unten selbst eingeben. (${err.message})`); }
});

$('manuell').addEventListener('click', () => {
  const lat = Number($('lat').value.replace(',', '.')), lon = Number($('lon').value.replace(',', '.'));
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 80 || Math.abs(lon) > 180) return fehler('Koordinaten ungültig.');
  fehler(''); pick('', lat, lon);
});

async function poll() {
  try {
    const s = await api('api/state');
    const j = s.job;
    $('bar').hidden = false; $('bar').setAttribute('aria-valuenow', j.pct); $('barfill').style.width = `${j.pct}%`;
    $('status').textContent = j.msg ? `${j.msg} (${j.pct} %)` : '';
    if (j.phase === 'error') return fehler(`Abbruch: ${j.error}. Beim nächsten Start geht es dort weiter, wo es stand.`);
    if (j.phase === 'ready') { location.href = './'; return; }
  } catch (err) { fehler(err.message); }
  setTimeout(poll, 2000);
}

$('los').addEventListener('click', async () => {
  $('los').disabled = true; fehler('');
  try { await api('api/setup', wahl); poll(); } catch (err) { fehler(err.message); $('los').disabled = false; }
});

// Schon eingerichtet? Dann weiter zur Karte, sonst bei laufendem Aufbau Fortschritt zeigen.
api('api/state').then((s) => { if (s.configured) { $('schritt1').hidden = true; $('schritt2').hidden = false; $('los').hidden = true; $('wahl').textContent = `Mittelpunkt: ${s.center.name || 'eigener Punkt'}`; poll(); } }).catch(() => fehler('Dieser Dienst läuft nur in der Desktop-App.'));

// Mitgeliefert ist nur die Schrift "Noto Sans Regular" und kein Symbolsatz: Beschriftungen auf Regular zwingen, Symbole weglassen.
function nurRegular(l) {
  if (l.type !== 'symbol') return l;
  const { 'icon-image': _drop, ...layout } = l.layout ?? {};
  return { ...l, layout: { ...layout, 'text-font': ['Noto Sans Regular'] } };
}

// Hintergrund: Weltkarte Zoom 0 bis 5, liegt im Programm (basis/welt.pmtiles, rund 15 MB). Fehlt sie oder eine Bibliothek,
// bleibt die Seite ohne Karte und funktioniert trotzdem. Ohne Netz, ohne Drittanbieter.
(async () => {
  try {
    const [{ Map: MlMap, addProtocol }, { PMTiles, Protocol }, { layers, namedFlavor }] = await Promise.all([
      import('../vendor/maplibre-gl/maplibre-gl.js'), import('../vendor/pmtiles/pmtiles.js'), import('../vendor/protomaps-basemaps/basemaps.js')]);
    const url = new URL('basis/welt.pmtiles', location.href).href;
    const archive = new PMTiles(url);
    await archive.getHeader();
    const protocol = new Protocol();
    protocol.add(archive);
    addProtocol('pmtiles', protocol.tile);
    hintergrund = new MlMap({
      container: 'hintergrund', interactive: false, attributionControl: false, center: [10, 49.5], zoom: 3.4,
      style: { version: 8, glyphs: `${new URL('fonts/', location.href).href}{fontstack}/{range}.pbf`, sources: { basemap: { type: 'vector', url: `pmtiles://${url}` } },
        layers: layers('basemap', namedFlavor('grayscale'), { lang: 'de' }).filter((l) => !/^(pois$|roads_shields)/.test(l.id)).map(nurRegular) },
    });
    if (wahl) zeigeWahl(wahl.lat, wahl.lon);
  } catch (err) { console.warn('Hintergrundkarte nicht verfügbar:', err?.message ?? err); }
})();
