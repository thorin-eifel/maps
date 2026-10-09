// Geländefaktoren für den Wind: Talachse, Talstärke und Kammstärke je Rasterzelle (terrain.png, gebaut von tools/build_terrain.py).
// Zweck: Eine vereinfachte Schätzung, wie das Gelände den Modellwind verändert: enge Täler lenken die Strömung entlang der Talachse und
//        beschleunigen sie leicht, quer zum Tal bremst das Gelände; auf Kuppen und Kämmen ist der Wind etwas schneller.
// Das ist ein geometrisches Modell, keine Strömungsrechnung und keine Messung. Ohne terrain.png bleibt der Wind unverändert.
// Aufruf: const t = await loadTerrain('data/terrain.json'); t.at(lon, lat) → { axis (rad), valley, ridge } | null;  t.adjust(u, v, tr) → [u', v']

const CHANNEL_GAIN = 0.35;     // Verstärkung der Komponente entlang der Talachse bei voller Talstärke
const TURN_GAIN = 0.5;         // Anteil der Quer-Komponente, der in Talrichtung umgelenkt wird
const CROSS_DAMP = 0.8;        // Dämpfung quer zum Tal bei voller Talstärke
const RIDGE_GAIN = 0.25;       // Beschleunigung auf Kämmen
const MAX_FACTOR = 1.6;        // nie mehr als das 1,6-fache des Modellwindes

export async function loadTerrain(metaUrl) {
  try {
    const meta = await (await fetch(metaUrl)).json();
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error('terrain.png nicht lesbar')); img.src = metaUrl.replace(/terrain\.json.*$/, 'terrain.png'); });
    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const cx = c.getContext('2d', { willReadFrequently: true });
    cx.drawImage(img, 0, 0);
    const px = cx.getImageData(0, 0, c.width, c.height).data;
    const { nx, ny, dlon, dlat } = meta, [w, , , n] = meta.bbox;
    if (c.width !== nx || c.height !== ny) throw new Error('terrain.png passt nicht zu terrain.json');
    function at(lon, lat, out = {}) {
      const i = Math.floor((lon - w) / dlon), j = Math.floor((n - lat) / dlat);
      if (i < 0 || j < 0 || i >= nx || j >= ny) return null;
      const k = (j * nx + i) * 4;
      out.axis = (px[k] / 255) * Math.PI;          // 0 bis π, ab Ost gegen den Uhrzeigersinn
      out.valley = px[k + 1] / 255; out.ridge = px[k + 2] / 255;
      return out;
    }
    function adjust(u, v, t) {
      if (!t) return [u, v];
      const sp = Math.hypot(u, v);
      if (sp < 0.05) return [u, v];
      const ca = Math.cos(t.axis), sa = Math.sin(t.axis);
      let wa = u * ca + v * sa, wb = -u * sa + v * ca;
      const c = t.valley;
      if (c > 0) {
        wa = wa * (1 + CHANNEL_GAIN * c) + Math.sign(wa || 1) * TURN_GAIN * c * Math.abs(wb);
        wb *= 1 - CROSS_DAMP * c;
      }
      let uu = wa * ca - wb * sa, vv = wa * sa + wb * ca;
      const f = 1 + RIDGE_GAIN * t.ridge;
      uu *= f; vv *= f;
      const k = Math.min(1, (MAX_FACTOR * sp) / Math.max(Math.hypot(uu, vv), 1e-6));
      return [uu * k, vv * k];
    }
    return { at, adjust, meta };
  } catch (err) {
    console.warn('Geländefaktoren nicht verfügbar:', err.message);
    return null;
  }
}
