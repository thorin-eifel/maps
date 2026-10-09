// Ersteinrichtung der Desktop-App: Mittelpunkt wählen, Fortschritt zeigen, danach zur Karte. Spricht nur mit dem lokalen Dienst (api/…).
const $ = (id) => document.getElementById(id);
let wahl = null;

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
}

$('suche').addEventListener('submit', async (e) => {
  e.preventDefault(); fehler('');
  const ul = $('treffer'); ul.replaceChildren();
  try {
    const { results } = await api(`api/geocode?q=${encodeURIComponent($('q').value)}`);
    if (!results.length) fehler('Kein Ort gefunden.');
    for (const r of results) {
      const li = document.createElement('li'), b = document.createElement('button');
      b.type = 'button'; b.className = 'btn'; b.textContent = r.name; b.style.cssText = 'display:block;width:100%;text-align:left;margin:.25rem 0';
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
    $('status').textContent = j.msg || '';
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
