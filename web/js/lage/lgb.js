// Kartenmenüs "LGB Daten" und "Landesdaten": WMS-Ebenen von Landesstellen Rheinland-Pfalz als Schalter nach Themen.
//
// Zweck:   Zeigt die Dienste als Rasterebenen auf der Lagekarte (reine Funktionen: js/lgb-katalog.js). Zwei Menüs, ein Code:
//          "LGB Daten" (Landesamt für Geologie und Bergbau, geo/lgb.json, tools/build_lgb_katalog.py) und
//          "Landesdaten" (offene Dienste weiterer Landesstellen aus dem Geoportal RLP, geo/landesdaten.json, tools/build_landesdaten_katalog.py).
//          Gruppen, Dienste und Ebenen stehen in den Katalogen, nicht im Code.
// Datenschutz: Jede eingeschaltete Ebene lädt Bilder direkt vom Server der Landesstelle (Dritter, die IP-Adresse geht dorthin). Deshalb ist
//          alles aus, bis die Besucherin den Hinweis des jeweiligen Menüs bestätigt hat; die Bestätigung gilt nur für diesen Seitenaufruf
//          (nichts im Speicher des Browsers). Es gibt keine weiteren Abrufe: kein Capabilities-Abruf, keine Legenden- oder Logo-Bilder,
//          nur GetMap-Kacheln. Zugelassen sind nur Server, die der Katalog nennt (und die CSP erlaubt).
// Lizenz:  je Dienst im Katalog (LGB: dl-de/by-2-0; Landesdaten: dl-de/by-2-0, dl-de/zero-2-0, CC BY, ODbL). Der Vermerk steht unter der
//          Karte, solange eine Ebene des Menüs an ist.
// Grenzen: je Menü höchstens MAX_AKTIV Ebenen gleichzeitig (Last beim Betreiber, Lesbarkeit). Keine Objektabfrage (GetFeatureInfo).
// Test:    tests/js/lgb.test.mjs (reine Funktionen), Sichtprüfung über #debug (vis:lgb-… / vis:lad-…)

import { $, getJSON } from '../util.js';
import { map, mapReady } from './zustand.js';
import { HOST, MAX_AKTIV, flacheEbenen, kachelUrl, kurzTitel, layerId, vermerk, vermerke, zoomBereich } from '../lgb-katalog.js';

// Ein Menü je Katalog. `vorsatz` ist Präfix der Karten-Ebenen-IDs und der Seitenelemente (#<vorsatz>-menu …).
const MENUES = [
  { vorsatz: 'lgb', datei: 'geo/lgb.json', name: 'LGB' },
  { vorsatz: 'lad', datei: 'geo/landesdaten.json', name: 'Landesdaten' },
];
const instanzen = [];

/** Setzt alle Katalog-Ebenen über die Basiskarte und unter Straßen und Beschriftung (nach jedem Neuaufbau der Basiskarte aufrufen). */
export function placeLgb() {
  if (!mapReady) return;
  const layers = map.getStyle().layers.map((l) => l.id);
  const before = layers.find((id) => id.startsWith('bm-roads_')) ?? 'radius-fill';
  for (const m of instanzen) for (const id of m.aktiv.keys()) if (map.getLayer(id)) map.moveLayer(id, before);
}

function baueMenue(cfg) {
  const { vorsatz: v } = cfg;
  const el = (name) => $(`#${v}-${name}`);
  const aktiv = new Map();     // layerId → { dienst, ebene }
  const fehler = new Map();    // Quelle (layerId) → Meldung
  let katalog = null, hosts = [HOST], zugestimmt = false, deckkraft = 0.7, wartend = null;
  const inst = { aktiv };

  function vermerkSetzen() {
    const z = el('vermerk');
    if (!z) return;
    z.hidden = aktiv.size === 0;
    if (!aktiv.size) return;
    const dienste = [...new Map([...aktiv.values()].map((a) => [a.dienst.id, a.dienst])).values()];
    const jahr = new Date().getFullYear();
    if (katalog.vermerk && !dienste.some((d) => d.vermerk)) {   // LGB: ein fester Vermerk, die Adresse als Link
      const [vor, nach] = vermerk(katalog, jahr).split('www.lgb-rlp.de');
      const a = document.createElement('a');
      a.href = 'https://www.lgb-rlp.de'; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = 'www.lgb-rlp.de';
      z.replaceChildren(vor, a, nach ?? '');
    } else {
      z.textContent = vermerke(dienste, katalog, jahr).join(' · ');
    }
  }

  function statusZeile() {
    const st = el('status');
    if (st) {
      const n = aktiv.size, f = fehler.size;
      st.textContent = `${n ? `${n} Ebene${n > 1 ? 'n' : ''} an` : ''}${f ? `${n ? ', ' : ''}${f} nicht erreichbar` : ''}`;
      st.dataset.state = f ? 'error' : 'ok';
      st.title = [...fehler.values()].join('\n');
    }
    vermerkSetzen();
    for (const d of el('gruppe').querySelectorAll('.lgb-thema')) {
      const c = d.querySelectorAll('input[data-lgb]:checked').length;
      const z = d.querySelector('.lgb-zahl');
      if (z) z.textContent = c ? `${c} an` : '';
    }
  }

  function einschalten(dienst, ebene) {
    const id = layerId(dienst, ebene.name, v);
    if (aktiv.has(id)) return true;
    if (aktiv.size >= MAX_AKTIV) return false;
    try {
      map.addSource(id, { type: 'raster', tiles: [kachelUrl(dienst, ebene.name, hosts)], tileSize: 256, maxzoom: 19 });
      map.addLayer({ id, type: 'raster', source: id, ...zoomBereich(ebene), paint: { 'raster-opacity': deckkraft, 'raster-fade-duration': 150 } });
    } catch (e) {
      console.warn(`${cfg.name}-Ebene:`, e);
      if (map.getSource(id)) map.removeSource(id);
      return false;
    }
    aktiv.set(id, { dienst, ebene });
    fehler.delete(id);
    placeLgb();
    return true;
  }

  function ausschalten(dienst, ebene) {
    const id = layerId(dienst, ebene.name, v);
    if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(id)) map.removeSource(id);
    aktiv.delete(id);
    fehler.delete(id);
  }

  function schalten(cb, dienst, ebene) {
    if (!cb.checked) { ausschalten(dienst, ebene); statusZeile(); return; }
    if (!zugestimmt) {   // erst der Hinweis, dann der erste Abruf
      cb.checked = false;
      wartend = { cb, dienst, ebene };
      const h = el('hinweis');
      if (h) { h.hidden = false; el('ok')?.focus(); }
      return;
    }
    if (!einschalten(dienst, ebene)) {
      cb.checked = false;
      const s = el('status');
      if (s) s.textContent = aktiv.size >= MAX_AKTIV ? `Höchstens ${MAX_AKTIV} Ebenen gleichzeitig; zuerst eine ausschalten.` : 'Ebene konnte nicht geladen werden.';
      return;
    }
    statusZeile();
  }

  function checkbox(dienst, ebene) {
    const label = document.createElement('label'), cb = document.createElement('input'), sp = document.createElement('span');
    cb.type = 'checkbox';
    cb.dataset.lgb = layerId(dienst, ebene.name, v);
    const { minzoom, maxzoom } = zoomBereich(ebene);
    sp.textContent = ` ${kurzTitel(ebene.title)}`;
    label.title = [ebene.abstract, minzoom != null ? `sichtbar ab Zoomstufe ${Math.ceil(minzoom)}` : '', maxzoom != null && maxzoom < 20 ? `bis Zoomstufe ${Math.floor(maxzoom)}` : ''].filter(Boolean).join(' · ');
    label.append(cb, sp);
    cb.addEventListener('change', () => schalten(cb, dienst, ebene));
    return label;
  }

  function baueDienst(dienst) {
    const box = document.createElement('div');
    box.className = 'lgb-dienst';
    const h = document.createElement('div');
    h.className = 'lgb-dienst-titel';
    h.textContent = dienst.title;
    const tip = [dienst.abstract, dienst.lizenz ? `Lizenz: ${dienst.lizenz}` : ''].filter(Boolean).join(' · ');
    if (tip) h.title = tip;
    box.append(h);
    const liste = document.createElement('div');
    liste.className = 'layer-list';
    let pfad = '', ziel = liste;
    for (const e of flacheEbenen(dienst.layers)) {
      const p = e.pfad.join(' / ');
      if (p !== pfad) {   // Ordner als eingeklappte Untergruppe
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

  function baueGruppen(root) {
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
  inst.init = async () => {
    const root = el('menu'), gruppe = el('gruppe');
    if (!root || !gruppe) return;
    try { katalog = await getJSON(cfg.datei); } catch (e) { console.warn(`${cfg.name}-Katalog fehlt:`, e?.message ?? e); return; }
    if (Array.isArray(katalog.hosts)) hosts = katalog.hosts;
    gruppe.hidden = false;
    baueGruppen(root);
    el('ok')?.addEventListener('click', () => {
      zugestimmt = true;
      const h = el('hinweis'); if (h) h.hidden = true;
      if (wartend) { wartend.cb.checked = true; schalten(wartend.cb, wartend.dienst, wartend.ebene); wartend = null; }
    });
    el('nein')?.addEventListener('click', () => { wartend = null; const h = el('hinweis'); if (h) h.hidden = true; });
    el('deckkraft')?.addEventListener('input', (e) => {
      deckkraft = Number(e.target.value) / 100;
      for (const id of aktiv.keys()) if (map.getLayer(id)) map.setPaintProperty(id, 'raster-opacity', deckkraft);
    });
    el('aus')?.addEventListener('click', () => {
      for (const { dienst, ebene } of [...aktiv.values()]) ausschalten(dienst, ebene);
      for (const cb of gruppe.querySelectorAll('input[data-lgb]')) cb.checked = false;
      statusZeile();
    });
    map.on('error', (e) => {   // fällt ein Dienst aus, bleibt der Rest der Karte stehen; die Zeile nennt es
      const id = e?.sourceId;
      if (typeof id !== 'string' || !aktiv.has(id)) return;
      fehler.set(id, `${aktiv.get(id).ebene.title}: ${e.error?.message ?? 'nicht erreichbar'}`);
      statusZeile();
    });
    map.on('data', (e) => {   // eine Kachel kam an: Fehlermeldung dieser Ebene zurücknehmen
      if (e?.sourceId && fehler.has(e.sourceId) && e.tile) { fehler.delete(e.sourceId); statusZeile(); }
    });
  };
  return inst;
}

/** Einmal beim Start: beide Menüs aufbauen. */
export async function initLgb() {
  for (const cfg of MENUES) instanzen.push(baueMenue(cfg));
  await Promise.all(instanzen.map((m) => m.init()));
}
