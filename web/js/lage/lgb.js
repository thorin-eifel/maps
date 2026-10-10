// Menü "LGB Daten": Kartenebenen des Landesamts für Geologie und Bergbau Rheinland-Pfalz als Schalter nach Themen.
//
// Zweck:   Zeigt die WMS-Dienste des LGB (Bergbau, Boden, Erdbeben, Geologie, Geothermie, Hydrogeologie, Ingenieurgeologie, Rohstoffgeologie)
//          als Rasterebenen auf der Lagekarte (reine Funktionen: js/lgb-katalog.js). Gruppen, Dienste und Ebenen stehen in geo/lgb.json (tools/build_lgb_katalog.py), nicht im Code.
// Datenschutz: Jede eingeschaltete Ebene lädt Bilder direkt von mapserver.lgb-rlp.de (Dritter, die IP-Adresse geht dorthin). Deshalb ist
//          alles aus, bis die Besucherin den Hinweis bestätigt hat; die Bestätigung gilt nur für diesen Seitenaufruf (nichts im Speicher des
//          Browsers). Es gibt keine weiteren Abrufe: kein Capabilities-Abruf, keine Legenden- oder Logo-Bilder, nur GetMap-Kacheln.
// Lizenz:  dl-de/by-2-0. Der Quellenvermerk steht unter der Karte, solange eine LGB-Ebene an ist.
// Grenzen: höchstens MAX_AKTIV Ebenen gleichzeitig (Last beim Betreiber, Lesbarkeit). Keine Objektabfrage (GetFeatureInfo).
// Test:    tests/js/lgb.test.mjs (reine Funktionen unten), Sichtprüfung über #debug (vis:lgb-…)
import { $, getJSON } from '../util.js';
import { map, mapReady } from './zustand.js';
import { MAX_AKTIV, flacheEbenen, kachelUrl, kurzTitel, layerId, vermerk, zoomBereich } from '../lgb-katalog.js';

// ---- Zustand und Oberfläche (nur im Browser) ----
const aktiv = new Map();     // layerId → { dienst, ebene }
let katalog = null, zugestimmt = false, deckkraft = 0.7, wartend = null;
const fehler = new Map();    // Quelle (layerId) → Meldung

function statusZeile() {
  const el = $('#lgb-status');
  if (!el) return;
  const n = aktiv.size, f = fehler.size;
  el.textContent = `${n ? `${n} Ebene${n > 1 ? 'n' : ''} an` : ''}${f ? `${n ? ', ' : ''}${f} nicht erreichbar` : ''}`;
  el.dataset.state = f ? 'error' : 'ok';
  el.title = [...fehler.values()].join('\n');
  const v = $('#lgb-vermerk');
  if (v) v.hidden = n === 0;
  for (const d of document.querySelectorAll('.lgb-thema')) {
    const c = d.querySelectorAll('input[data-lgb]:checked').length;
    const z = d.querySelector('.lgb-zahl');
    if (z) z.textContent = c ? `${c} an` : '';
  }
}

/** Setzt die LGB-Ebenen über die Basiskarte und unter Straßen und Beschriftung (nach jedem Neuaufbau der Basiskarte aufrufen). */
export function placeLgb() {
  if (!mapReady || !aktiv.size) return;
  const layers = map.getStyle().layers.map((l) => l.id);
  const before = layers.find((id) => id.startsWith('bm-roads_')) ?? 'radius-fill';
  for (const id of aktiv.keys()) if (map.getLayer(id)) map.moveLayer(id, before);
}

function einschalten(dienst, ebene) {
  const id = layerId(dienst, ebene.name);
  if (aktiv.has(id)) return true;
  if (aktiv.size >= MAX_AKTIV) return false;
  try {
    map.addSource(id, { type: 'raster', tiles: [kachelUrl(dienst, ebene.name)], tileSize: 256, maxzoom: 19 });
    map.addLayer({ id, type: 'raster', source: id, ...zoomBereich(ebene), paint: { 'raster-opacity': deckkraft, 'raster-fade-duration': 150 } });
  } catch (e) {
    console.warn('LGB-Ebene:', e);
    if (map.getSource(id)) map.removeSource(id);
    return false;
  }
  aktiv.set(id, { dienst, ebene });
  fehler.delete(id);
  placeLgb();
  return true;
}

function ausschalten(dienst, ebene) {
  const id = layerId(dienst, ebene.name);
  if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(id)) map.removeSource(id);
  aktiv.delete(id);
  fehler.delete(id);
}

function checkbox(dienst, ebene) {
  const label = document.createElement('label'), cb = document.createElement('input'), sp = document.createElement('span');
  cb.type = 'checkbox';
  cb.dataset.lgb = layerId(dienst, ebene.name);
  const { minzoom, maxzoom } = zoomBereich(ebene);
  sp.textContent = ` ${kurzTitel(ebene.title)}`;
  label.title = [ebene.abstract, minzoom != null ? `sichtbar ab Zoomstufe ${Math.ceil(minzoom)}` : '', maxzoom != null && maxzoom < 20 ? `bis Zoomstufe ${Math.floor(maxzoom)}` : ''].filter(Boolean).join(' · ');
  label.append(cb, sp);
  cb.addEventListener('change', () => schalten(cb, dienst, ebene));
  return label;
}

function schalten(cb, dienst, ebene) {
  if (!cb.checked) { ausschalten(dienst, ebene); statusZeile(); return; }
  if (!zugestimmt) {   // erst der Hinweis, dann der erste Abruf
    cb.checked = false;
    wartend = { cb, dienst, ebene };
    const h = $('#lgb-hinweis');
    if (h) { h.hidden = false; $('#lgb-ok')?.focus(); }
    return;
  }
  if (!einschalten(dienst, ebene)) {
    cb.checked = false;
    const s = $('#lgb-status');
    if (s) s.textContent = aktiv.size >= MAX_AKTIV ? `Höchstens ${MAX_AKTIV} Ebenen gleichzeitig; zuerst eine ausschalten.` : 'Ebene konnte nicht geladen werden.';
    return;
  }
  statusZeile();
}

function baueDienst(dienst) {
  const box = document.createElement('div');
  box.className = 'lgb-dienst';
  const h = document.createElement('div');
  h.className = 'lgb-dienst-titel';
  h.textContent = dienst.title;
  if (dienst.abstract) h.title = dienst.abstract;
  box.append(h);
  const liste = document.createElement('div');
  liste.className = 'layer-list';
  const einzel = flacheEbenen(dienst.layers);
  let pfad = '';
  let ziel = liste;
  for (const e of einzel) {
    const p = e.pfad.join(' / ');
    if (p !== pfad) {   // Ordner (z. B. Trennhorizonte) als eingeklappte Untergruppe
      pfad = p;
      if (p) {
        const d = document.createElement('details'), s = document.createElement('summary'), inner = document.createElement('div');
        s.textContent = p; inner.className = 'layer-list';
        d.append(s, inner); liste.append(d); ziel = inner;
      } else ziel = liste;
    }
    ziel.append(checkbox(dienst, e));
  }
  box.append(liste);
  return box;
}

function baueMenue(root) {
  for (const g of katalog.groups) {
    const d = document.createElement('details'), s = document.createElement('summary'), z = document.createElement('span');
    d.className = 'lgb-thema';
    s.textContent = g.title;
    z.className = 'lgb-zahl muted small';
    s.append(' ', z);
    d.append(s);
    for (const dienst of g.services) d.append(baueDienst(dienst));
    root.append(d);
  }
}

/** Einmal beim Start: Katalog holen (gleiche Herkunft), Menü bauen, Bedienung verdrahten. Ohne Katalog bleibt die Gruppe verborgen. */
export async function initLgb() {
  const root = $('#lgb-menu'), gruppe = $('#lgb-gruppe');
  if (!root || !gruppe) return;
  try { katalog = await getJSON('geo/lgb.json'); } catch (e) { console.warn('LGB-Katalog fehlt:', e?.message ?? e); return; }
  gruppe.hidden = false;
  baueMenue(root);
  const v = $('#lgb-vermerk');
  if (v) {   // Vermerk wörtlich nach LGB-Vorgabe, die Adresse als Link
    const [vor, nach] = vermerk(katalog, new Date().getFullYear()).split('www.lgb-rlp.de');
    const a = document.createElement('a');
    a.href = 'https://www.lgb-rlp.de'; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = 'www.lgb-rlp.de';
    v.replaceChildren(vor, a, nach ?? '');
  }
  $('#lgb-ok')?.addEventListener('click', () => {
    zugestimmt = true;
    const h = $('#lgb-hinweis'); if (h) h.hidden = true;
    if (wartend) { wartend.cb.checked = true; schalten(wartend.cb, wartend.dienst, wartend.ebene); wartend = null; }
  });
  $('#lgb-nein')?.addEventListener('click', () => { wartend = null; const h = $('#lgb-hinweis'); if (h) h.hidden = true; });
  $('#lgb-deckkraft')?.addEventListener('input', (e) => {
    deckkraft = Number(e.target.value) / 100;
    for (const id of aktiv.keys()) if (map.getLayer(id)) map.setPaintProperty(id, 'raster-opacity', deckkraft);
  });
  $('#lgb-aus')?.addEventListener('click', () => {
    for (const { dienst, ebene } of [...aktiv.values()]) ausschalten(dienst, ebene);
    for (const cb of document.querySelectorAll('input[data-lgb]')) cb.checked = false;
    statusZeile();
  });
  map.on('error', (e) => {   // fällt ein Dienst aus, bleibt der Rest der Karte stehen; die Zeile nennt es
    const id = e?.sourceId;
    if (typeof id !== 'string' || !id.startsWith('lgb-') || !aktiv.has(id)) return;
    fehler.set(id, `${aktiv.get(id).ebene.title}: ${e.error?.message ?? 'nicht erreichbar'}`);
    statusZeile();
  });
  map.on('data', (e) => {   // eine Kachel kam an: Fehlermeldung dieser Ebene zurücknehmen
    if (e?.sourceId && fehler.has(e.sourceId) && e.tile) { fehler.delete(e.sourceId); statusZeile(); }
  });
}
