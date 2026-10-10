// Vignette entlang der Landesgrenze: laden und auf die Karte legen (reine Funktionen: js/vignette-bild.js).
//
// Zweck:  Holt geo/vignette.json und geo/vignette.png (gleiche Herkunft), liest die Alpha-Ebene des PNG für Wind und Regenwellen aus und
//         legt PNG und schwarze Außenfläche als Ebenen über die Karte. Fehlt eines von beiden, liefert ladeVignette() null und die Karte
//         nimmt den Kreis (js/lage/geometrie.js), die Seite bleibt benutzbar.
import { getJSON } from '../util.js';
import { aussenflaeche, faktor } from '../vignette-bild.js';

export const BILD_QUELLE = 'vignette-bild', BILD_EBENE = 'vig-bild';

/** { meta, url, faktor(lon, lat) } oder null. */
export async function ladeVignette() {
  try {
    const meta = await getJSON('geo/vignette.json');
    const url = new URL(`geo/${meta.bild}`, location.href).href;
    const img = new Image();
    img.src = url;
    await img.decode();
    const cv = document.createElement('canvas');
    cv.width = img.naturalWidth; cv.height = img.naturalHeight;
    if (cv.width !== meta.breite || cv.height !== meta.hoehe) throw new Error('Bildgröße weicht von vignette.json ab');
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const rgba = ctx.getImageData(0, 0, cv.width, cv.height).data;
    const alpha = new Uint8Array(cv.width * cv.height);
    for (let i = 0; i < alpha.length; i++) alpha[i] = rgba[i * 4 + 3];
    return { meta, url, faktor: (lon, lat) => faktor(meta, alpha, lon, lat) };
  } catch (e) {
    console.warn('Vignette entlang der Landesgrenze nicht verfügbar, nehme den Kreis:', e?.message ?? e);
    return null;
  }
}

/** Außenfläche als Daten für die Quelle 'vignette'. */
export const aussenDaten = (v) => aussenflaeche(v.meta);

/** Bild als Quelle und Ebene, direkt über der schwarzen Außenfläche (VIG_ID muss schon da sein). */
export function legeBildAn(map, v) {
  map.addSource(BILD_QUELLE, { type: 'image', url: v.url, coordinates: v.meta.ecken });
  map.addLayer({ id: BILD_EBENE, type: 'raster', source: BILD_QUELLE, paint: { 'raster-opacity': 1, 'raster-fade-duration': 0, 'raster-resampling': 'linear' } });
}
