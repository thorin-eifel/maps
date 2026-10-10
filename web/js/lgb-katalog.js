// LGB-Katalog: reine Funktionen (kein DOM) für das Menü "LGB Daten" (js/lage/lgb.js).
//
// Zweck:  Maßstab → Zoom, Kachel-URL der WMS-Dienste, Ebenenbaum glätten, Titel kürzen, Quellenvermerk. Getrennt von der Oberfläche, damit
//         node --test sie ohne Browser prüft (tests/js/lgb.test.mjs).
// Regel:  Kachel-URLs gibt es nur für https://mapserver.lgb-rlp.de; alles andere wirft. Die Seite ruft keinen anderen Dritten auf.
export const MAX_AKTIV = 6;
export const WMS_PARAMS = 'SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&STYLES=&CRS=EPSG:3857&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=TRUE';
const Z0_DENOM = 559082264.028;   // Maßstabsnenner bei Kartenzoom 0 (256-px-Kacheln, 0,28 mm je Pixel, Web-Mercator)
export const HOST = 'mapserver.lgb-rlp.de';

/** Maßstabsnenner → Kartenzoom. */
export const zoomFuerNenner = (n) => Math.log2(Z0_DENOM / n);

/** Zoombereich einer Ebene aus ihren Maßstabsgrenzen (min_scale = stärkste Vergrößerung, max_scale = gröbste Ansicht). */
export function zoomBereich(ebene) {
  const out = {};
  if (ebene.max_scale) out.minzoom = Math.max(0, +(zoomFuerNenner(ebene.max_scale) - 0.3).toFixed(2));
  if (ebene.min_scale) out.maxzoom = Math.min(24, +(zoomFuerNenner(ebene.min_scale) + 0.3).toFixed(2));
  return out;
}

/** Kachel-URL-Vorlage für MapLibre. Der Name kommt aus dem Katalog und wird trotzdem kodiert. */
export function kachelUrl(dienst, name) {
  const u = new URL(dienst.url);
  if (u.hostname !== HOST || u.protocol !== 'https:') throw new Error(`Dienst außerhalb ${HOST}: ${dienst.url}`);
  return `${u.origin}${u.pathname}?${WMS_PARAMS}&LAYERS=${encodeURIComponent(name)}&BBOX={bbox-epsg-3857}`;
}

/** Alle benannten Ebenen eines Dienstes flach (Ordner ohne Name werden aufgelöst); Pfad der Ordnertitel dazu. */
export function flacheEbenen(knoten, pfad = []) {
  const out = [];
  for (const n of knoten) {
    if (n.name) out.push({ ...n, pfad });
    if (n.children) out.push(...flacheEbenen(n.children, n.name ? pfad : [...pfad, n.title]));
  }
  return out;
}

/** Anzeigetitel: Kürzel vor dem Doppelpunkt ("GÜK300: Geologische Übersichtskarte" → Rest) weglassen, wenn die Gruppe es schon trägt. */
export const kurzTitel = (t) => (t.includes(': ') ? t.slice(t.indexOf(': ') + 2) : t).trim();

export const layerId = (dienst, name) => `lgb-${dienst.id}-${name}`.replace(/[^A-Za-z0-9_-]/g, '_');

/** Quellenvermerk laut Nutzungsbedingungen des LGB. */
export const vermerk = (katalog, jahr) => katalog.vermerk.replace('{jahr}', String(jahr));
