// Vignette entlang der Landesgrenze: reine Funktionen (kein DOM) für js/lage/vignette.js.
//
// Zweck:  Das PNG geo/vignette.png (tools/build_vignette.py) trägt als Alpha die Deckkraft des Schwarz, gleichmäßig in Web-Mercator über dem
//         Rechteck meta.mercator. Hier: Lage eines Punkts im Bild, Deckkraft an einem Punkt (bilinear), Ausblendfaktor für Wind und Regenwellen
//         (1 = klar, 0 = schwarz) und die schwarze Außenfläche um das Bild. Getrennt vom Browser, damit node --test sie prüft.
// Test:   tests/js/vignette.test.mjs
const R = 6378137;

/** WGS84 lon/lat (Grad) → Web-Mercator-Meter. */
export const mercator = (lon, lat) => [R * (lon * Math.PI) / 180, R * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))];

/** Bildpunkt (Bruchteile, Mitte des ersten Punkts = 0,0) für einen Ort; null außerhalb des Bildes. */
export function bildPunkt(meta, lon, lat) {
  const [x0, y0, x1, y1] = meta.mercator;
  const [mx, my] = mercator(lon, lat);
  if (mx < x0 || mx > x1 || my < y0 || my > y1) return null;
  return [((mx - x0) / (x1 - x0)) * meta.breite - 0.5, ((y1 - my) / (y1 - y0)) * meta.hoehe - 0.5];
}

/** Deckkraft des Schwarz (0 bis 1) am Ort. `alpha` ist die Alpha-Ebene als Folge von Bytes (Zeile für Zeile). Außerhalb des Bildes: 1. */
export function deckkraft(meta, alpha, lon, lat) {
  const p = bildPunkt(meta, lon, lat);
  if (!p) return 1;
  const { breite: w, hoehe: h } = meta;
  const fx = Math.min(Math.max(p[0], 0), w - 1), fy = Math.min(Math.max(p[1], 0), h - 1);
  const ix = Math.min(Math.floor(fx), w - 2), iy = Math.min(Math.floor(fy), h - 2), tx = fx - ix, ty = fy - iy;
  const a = (x, y) => alpha[y * w + x];
  const top = a(ix, iy) * (1 - tx) + a(ix + 1, iy) * tx, bot = a(ix, iy + 1) * (1 - tx) + a(ix + 1, iy + 1) * tx;
  return (top * (1 - ty) + bot * ty) / 255;
}

/** Ausblendfaktor für Wind und Regenwellen: 1 klar, 0 schwarz. */
export const faktor = (meta, alpha, lon, lat) => 1 - deckkraft(meta, alpha, lon, lat);

/** Schwarze Fläche um das Bild: die ganze Welt mit einem Loch knapp innerhalb des Bildrandes (Rand des Bildes ist ohnehin voll schwarz). */
export function aussenflaeche(meta, innen = 0.02) {
  const [[w, n], [e], [, s]] = meta.ecken;
  const welt = [[-179.9, -85], [179.9, -85], [179.9, 85], [-179.9, 85], [-179.9, -85]];
  const loch = [[w + innen, n - innen], [w + innen, s + innen], [e - innen, s + innen], [e - innen, n - innen], [w + innen, n - innen]];   // gegen den Uhrzeigersinn
  return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { a: 1 }, geometry: { type: 'Polygon', coordinates: [welt, loch] } }] };
}
